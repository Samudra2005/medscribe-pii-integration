"""
Runs NER extraction over every transcript for a recording and persists
one ExtractedEntitySet row per transcript, targeting the nurse intake
schema (target_role=NURSE) -- the sensible default for Phase 12, since
intake happens first in the clinical workflow and this project doesn't
yet have logic to separate "nurse portion" vs "doctor portion" of a
conversation. Doctor-targeted extraction (medication orders, diagnoses)
is a natural refinement for a later phase once that separation exists,
not built now.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as DBSession

from app.core.logging_config import get_logger
from app.models.audio import AudioRecording
from app.models.enums import UserRole
from app.models.extracted_entity import ExtractedEntitySet
from app.models.transcript import Transcript
from app.services.audio_service import AudioValidationError
from app.services.ner_validation import build_validated_entities
from app.services.ner_service import extract_entities
from app.core.tracing import bind_appointment_trace
from app.core.metrics_helpers import track_pipeline_stage
from app.core.metrics import NER_ENTITY_VALIDATION_OUTCOME

logger = get_logger(__name__)

NER_MODEL_VERSION = "openmed-superclinical-434m"  # covers both Pharma+Disease models used together


async def run_ner_pipeline(recording_id: uuid.UUID, db: DBSession) -> list[ExtractedEntitySet]:
    result = await db.execute(select(AudioRecording).where(AudioRecording.id == recording_id))
    recording = result.scalar_one_or_none()
    if recording is None:
        raise AudioValidationError("Audio recording not found")
    bind_appointment_trace(recording.appointment_id)

    transcripts_result = await db.execute(
        select(Transcript).where(Transcript.appointment_id == recording.appointment_id)
    )
    transcripts = transcripts_result.scalars().all()

    if not transcripts:
        raise AudioValidationError("No transcripts found for this recording's appointment -- run transcription first")

    # Idempotent re-run, same pattern as chunking/transcription: clear any
    # existing entity sets for these transcripts before regenerating.
    existing_result = await db.execute(
        select(ExtractedEntitySet).where(
            ExtractedEntitySet.transcript_id.in_([t.id for t in transcripts])
        )
    )
    for stale in existing_result.scalars().all():
        await db.delete(stale)
    await db.flush()

    created_entity_sets: list[ExtractedEntitySet] = []

    for transcript in transcripts:
        with track_pipeline_stage("ner"):
            ner_result = await extract_entities(transcript.text)
            validated = build_validated_entities(ner_result)
            for entity in validated.entities:
                NER_ENTITY_VALIDATION_OUTCOME.labels(status=entity.status, label=entity.label).inc()

            entity_set = ExtractedEntitySet(
                appointment_id=transcript.appointment_id,
                transcript_id=transcript.id,
                target_role=UserRole.NURSE,
                raw_entities=ner_result.to_dict(),  # COMPLETE, UNFILTERED output -- every
                                                    # entity both models found, regardless
                                                    # of confidence, never modified after
                                                    # creation. This is the permanent,
                                                    # auditable record of what the models
                                                    # actually produced.
                validated_entities=validated.to_dict(),
                ner_model_name="OpenMed-Pharma+Disease-SuperClinical-434M",  # BUG FIX: was
                                                    # incorrectly attributing ALL entities
                                                    # (including DISEASE-labeled ones from
                                                    # the separate DiseaseDetect model) to
                                                    # only PHARMA_MODEL_ID. Now names both.
                ner_model_version=NER_MODEL_VERSION,
                validation_passed=validated.all_passed,
                confidence_score=validated.mean_confidence,
            )
            db.add(entity_set)
            created_entity_sets.append(entity_set)

            logger.info(
                "transcript_entities_extracted",
                transcript_id=str(transcript.id),
                entity_count=len(ner_result.entities),
            )

    await db.commit()
    for e in created_entity_sets:
        await db.refresh(e)

    logger.info(
        "ner_pipeline_complete",
        recording_id=str(recording_id),
        entity_sets_created=len(created_entity_sets),
    )
    return created_entity_sets