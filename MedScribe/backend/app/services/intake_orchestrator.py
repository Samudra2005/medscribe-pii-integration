"""
Runs AI-assisted vitals extraction, correctly scoped to ONLY
NURSE_INTAKE-stage recordings for the appointment -- not doctor-
consultation recordings, per the real two-recording clinical workflow
(added in this same work session after the initial version incorrectly
pulled from all transcripts regardless of which recording/stage they
came from).
"""
import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as DBSession

from app.core.logging_config import get_logger
from app.models.audio import AudioChunk, AudioRecording
from app.models.enums import InputSource, RecordingStage
from app.models.intake_form import IntakeForm
from app.models.transcript import Transcript
from app.services.audio_service import AudioValidationError
from app.services.intake_prompt_builder import build_intake_extraction_prompt
from app.services.medgemma_service import MODEL_ID, MODEL_VERSION, generate_draft
from app.services.pii_masking_client import PIIMaskingClient, PIIMaskingError
from app.core.config import get_settings

logger = get_logger(__name__)


async def _generate_privacy_safe_draft(prompt: str):
    """Send only reversible PII tokens to MedGemma and restore its reply."""
    settings = get_settings()
    if not settings.PII_MASKING_ENABLED:
        return await generate_draft(prompt)

    client = PIIMaskingClient(
        settings.PII_MASKING_URL,
        settings.PII_MASKING_API_KEY,
        settings.PII_MASKING_TIMEOUT_SECONDS,
    )
    try:
        masked = await asyncio.to_thread(client.mask_text, prompt)
        masked_draft = await generate_draft(masked.text)
        restored_text = await asyncio.to_thread(client.unmask_text, masked_draft.text, masked.session_id)
        return type(masked_draft)(
            text=restored_text,
            input_tokens=masked_draft.input_tokens,
            output_tokens=masked_draft.output_tokens,
            generation_seconds=masked_draft.generation_seconds,
        )
    except PIIMaskingError:
        logger.error("pii_masking_failed", pipeline="intake_draft")
        if settings.PII_MASKING_REQUIRED:
            raise AudioValidationError(
                "PII masking service is unavailable; the AI draft was not generated."
            )
        return await generate_draft(prompt)


async def run_intake_draft_pipeline(
    appointment_id: uuid.UUID, nurse_id: uuid.UUID, db: DBSession
) -> IntakeForm:
    # Only transcripts belonging to chunks of NURSE_INTAKE-stage
    # recordings for this appointment -- explicit join, not a blanket
    # appointment_id filter, per the real two-recording workflow.
    transcripts_result = await db.execute(
        select(Transcript)
        .join(AudioChunk, Transcript.audio_chunk_id == AudioChunk.id)
        .join(AudioRecording, AudioChunk.audio_recording_id == AudioRecording.id)
        .where(
            AudioRecording.appointment_id == appointment_id,
            AudioRecording.recording_stage == RecordingStage.NURSE_INTAKE,
        )
    )
    transcripts = transcripts_result.scalars().all()

    if not transcripts:
        raise AudioValidationError(
            "No nurse-intake-stage transcripts found for this appointment. "
            "Ensure a recording was uploaded with recording_stage=nurse_intake "
            "and has been transcribed."
        )

    prompt = build_intake_extraction_prompt(list(transcripts))
    draft_result = await _generate_privacy_safe_draft(prompt)

    intake_form = IntakeForm(
        appointment_id=appointment_id,
        nurse_id=nurse_id,
        source_entity_set_id=None,
        input_source=InputSource.LIVE_RECORDING,
        # form_data is the RAW extraction text for now -- structured
        # parsing (mirroring Phase 13's prescription_draft_parser.py
        # pattern) is real, separate follow-up work, not built in this
        # pass. Storing the raw quoted-extraction text is itself
        # useful and human-reviewable, even unparsed, given the
        # traceability the prompt now requires.
        form_data={
            "ai_generated": True,
            "ai_model_name": MODEL_ID,
            "ai_model_version": MODEL_VERSION,
            "ai_raw_draft_text": draft_result.text,
            "vitals": {},
            "prior_test_results": [],
            "reason_for_visit": None,
            "known_allergies": None,
        },
        is_final=False,
    )
    db.add(intake_form)
    await db.commit()
    await db.refresh(intake_form)

    logger.info(
        "intake_draft_created",
        appointment_id=str(appointment_id),
        intake_form_id=str(intake_form.id),
        generation_seconds=round(draft_result.generation_seconds, 1),
    )
    return intake_form
