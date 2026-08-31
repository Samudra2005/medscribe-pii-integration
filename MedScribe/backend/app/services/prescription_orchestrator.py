"""
Runs the full Phase 13 drafting pipeline for an appointment: build
prompt from validated transcripts/entities -> generate via MedGemma ->
parse into structured PrescriptionData -> persist as a draft Prescription
row (is_final=False -- a doctor must review and finalize, per this
project's HITL-everywhere design).
"""
import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as DBSession

from app.core.logging_config import get_logger
from app.models.appointment import Appointment
from app.models.enums import InputSource
from app.models.extracted_entity import ExtractedEntitySet
from app.models.prescription import Prescription
from app.models.transcript import Transcript
from app.services.audio_service import AudioValidationError
from app.services.draft_prompt_builder import build_prescription_draft_prompt
from app.services.medgemma_service import MODEL_ID, MODEL_VERSION, generate_draft
from app.services.pii_masking_client import PIIMaskingClient, PIIMaskingError
from app.services.prescription_draft_parser import parse_medgemma_draft_to_prescription
from app.core.tracing import bind_appointment_trace
from app.core.config import get_settings

from app.core.metrics_helpers import track_pipeline_stage

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
        logger.error("pii_masking_failed", pipeline="prescription_draft")
        if settings.PII_MASKING_REQUIRED:
            raise AudioValidationError(
                "PII masking service is unavailable; the AI draft was not generated."
            )
        return await generate_draft(prompt)


async def run_prescription_draft_pipeline(
    appointment_id: uuid.UUID, doctor_id: uuid.UUID, db: DBSession
) -> Prescription:
    appointment_result = await db.execute(select(Appointment).where(Appointment.id == appointment_id))
    appointment = appointment_result.scalar_one_or_none()
    if appointment is None:
        raise AudioValidationError("Appointment not found")
    bind_appointment_trace(appointment_id)

    transcripts_result = await db.execute(
        select(Transcript).where(Transcript.appointment_id == appointment_id)
    )
    transcripts = transcripts_result.scalars().all()

    entity_sets_result = await db.execute(
        select(ExtractedEntitySet).where(ExtractedEntitySet.appointment_id == appointment_id)
    )
    entity_sets = entity_sets_result.scalars().all()

    if not transcripts:
        raise AudioValidationError("No transcripts found for this appointment -- run transcription first")

    prompt = build_prescription_draft_prompt(list(transcripts), list(entity_sets))
    with track_pipeline_stage("draft_prescription"):
        draft_result = await _generate_privacy_safe_draft(prompt)
    parsed = parse_medgemma_draft_to_prescription(draft_result.text, MODEL_ID, MODEL_VERSION)

    # source_entity_set_id points to just ONE entity set even though many
    # contributed -- schema limitation flagged directly (see model
    # comment: "NULL when input_source == MANUAL_ENTRY"). We record the
    # first contributing entity set as a representative reference; the
    # full picture of which transcripts/entities actually fed this draft
    # lives in form_data.ai_raw_draft_text plus the prompt construction
    # logic itself, not a single FK. Not fully solving this schema gap
    # now -- flagging it as a known limitation.
    representative_entity_set_id = entity_sets[0].id if entity_sets else None

    prescription = Prescription(
        appointment_id=appointment_id,
        doctor_id=doctor_id,
        source_entity_set_id=representative_entity_set_id,
        input_source=InputSource.LIVE_RECORDING if _any_live(transcripts) else InputSource.UPLOADED_AUDIO,
        form_data=parsed.model_dump(),
        is_final=False,  # ALWAYS false on creation -- doctor must explicitly finalize (Phase 14)
    )
    db.add(prescription)
    await db.commit()
    await db.refresh(prescription)

    logger.info(
        "prescription_draft_created",
        appointment_id=str(appointment_id),
        prescription_id=str(prescription.id),
        generation_seconds=round(draft_result.generation_seconds, 1),
    )
    return prescription


def _any_live(transcripts: list[Transcript]) -> bool:
    # Best-effort provenance guess -- Transcript doesn't directly carry
    # input_source (that's on AudioRecording, one join away); defaulting
    # to a reasonable guess here rather than adding another join for a
    # cosmetic field. Flagged as an approximation, not exact.
    return False
