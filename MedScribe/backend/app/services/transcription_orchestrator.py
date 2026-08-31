"""
Runs MedASR over every chunk of a recording and persists one Transcript
row per chunk (source=local_asr, status=draft). Confidence scoring and
quality assessment are explicitly Phase 10's job -- this phase only
produces the raw draft transcripts for the quality engine to later
evaluate.
"""
import uuid
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as DBSession

from app.core.logging_config import get_logger
from app.models.audio import AudioChunk, AudioRecording
from app.models.enums import AudioProcessingStatus, HitlStatus, TranscriptSource, TranscriptStatus
from app.models.hitl import HitlItem
from app.models.transcript import Transcript
from app.services.audio_service import AudioValidationError, resolve_absolute_path
from app.services.azure_asr_service import is_azure_configured, transcribe_chunk_azure
from app.services.consensus_service import ConsensusOutcome, compare_transcriptions

from app.services.medasr_service import MODEL_ID, transcribe_chunk
from app.services.quality_engine import assess_transcript_quality
from app.core.tracing import bind_appointment_trace
from app.core.metrics_helpers import track_pipeline_stage
from app.core.metrics import HITL_ITEMS_CREATED, TRANSCRIPT_QUALITY_OUTCOME, CONSENSUS_OUTCOME

logger = get_logger(__name__)

MODEL_VERSION = "1.0.0"  # per MedASR's own model card ("Model version: 1.0.0")


async def run_transcription_pipeline(recording_id: uuid.UUID, db: DBSession) -> list[Transcript]:
    result = await db.execute(select(AudioRecording).where(AudioRecording.id == recording_id))
    recording = result.scalar_one_or_none()
    if recording is None:
        raise AudioValidationError("Audio recording not found")
    bind_appointment_trace(recording.appointment_id)

    if recording.processing_status != AudioProcessingStatus.CHUNKING_COMPLETE:
        raise AudioValidationError(
            f"Recording must be in chunking_complete status to transcribe "
            f"(currently: {recording.processing_status.value})"
        )

    chunks_result = await db.execute(
        select(AudioChunk)
        .where(AudioChunk.audio_recording_id == recording_id)
        .order_by(AudioChunk.chunk_index)
    )
    chunks = chunks_result.scalars().all()

    if not chunks:
        raise AudioValidationError("No chunks found for this recording -- run chunking first")

    # Idempotent re-run, same pattern as chunking: clear any existing
    # LOCAL_ASR draft transcripts for this appointment's chunks before
    # regenerating, rather than accumulating duplicates on retry.
    existing_result = await db.execute(
        select(Transcript).where(
            Transcript.audio_chunk_id.in_([c.id for c in chunks]),
            Transcript.source == TranscriptSource.LOCAL_ASR,
        )
    )
    for stale in existing_result.scalars().all():
        await db.delete(stale)
    await db.flush()

    recording.processing_status = AudioProcessingStatus.TRANSCRIBING
    await db.commit()

    try:
        created_transcripts: list[Transcript] = []
        hitl_items_created = 0

        azure_available = is_azure_configured()
        for chunk in chunks:
            with track_pipeline_stage("transcribe"):
                chunk_absolute_path = resolve_absolute_path(chunk.storage_path)

                # Per explicit design: Azure runs on EVERY chunk, concurrently
                # with MedASR, regardless of MedASR's eventual quality --
                # not a fallback-only trigger. If Azure isn't configured at
                # all, we skip attempting the call entirely (zero cost),
                # rather than letting it fail per-chunk.
                if azure_available:
                    asr_result, azure_result = await asyncio.gather(
                        transcribe_chunk(chunk_absolute_path),
                        transcribe_chunk_azure(chunk_absolute_path),
                    )
                else:
                    asr_result = await transcribe_chunk(chunk_absolute_path)
                    azure_result = None

                chunk_duration = chunk.end_time_seconds - chunk.start_time_seconds
                quality_report = assess_transcript_quality(
                    text=asr_result.text,
                    mean_confidence=asr_result.confidence_score,
                    min_confidence=asr_result.min_token_confidence,
                    chunk_duration_seconds=chunk_duration,
                )
                TRANSCRIPT_QUALITY_OUTCOME.labels(accepted=str(quality_report.accept).lower()).inc()

                consensus = compare_transcriptions(
                    medasr_text=asr_result.text,
                    medasr_confidence=asr_result.confidence_score,
                    azure_text=azure_result.text if azure_result else "",
                    azure_confidence=azure_result.confidence if azure_result else None,
                    azure_succeeded=azure_result.success if azure_result else False,
                )
                CONSENSUS_OUTCOME.labels(outcome=consensus.outcome.value).inc()

                # Consensus mismatch overrides the Phase 10 quality-only
                # acceptance decision -- even if MedASR's OWN confidence
                # looked fine, disagreeing with an independent cloud
                # transcription is itself a reason for review that Phase 10
                # alone couldn't have known about.
                needs_review = (not quality_report.accept) or (
                    consensus.outcome == ConsensusOutcome.MISMATCH_NEEDS_REVIEW
                )
                transcript_status = TranscriptStatus.FLAGGED_FOR_REVIEW if needs_review else TranscriptStatus.DRAFT

                combined_report = quality_report.to_dict()
                combined_report["consensus"] = {
                    "outcome": consensus.outcome.value,
                    "similarity_ratio": consensus.similarity_ratio,
                    "medasr_confidence": consensus.medasr_confidence,
                    "azure_confidence": consensus.azure_confidence,
                    "azure_text": azure_result.text if azure_result else None,
                    "azure_available": azure_available,
                }

                transcript = Transcript(
                    appointment_id=recording.appointment_id,
                    audio_chunk_id=chunk.id,
                    source=consensus.chosen_source,
                    status=transcript_status,
                    text=consensus.chosen_text,
                    model_name=MODEL_ID if consensus.chosen_source == TranscriptSource.LOCAL_ASR else "azure-speech",
                    model_version=MODEL_VERSION if consensus.chosen_source == TranscriptSource.LOCAL_ASR else None,
                    confidence_score=asr_result.confidence_score,
                    quality_report=combined_report,
                )
                db.add(transcript)
                await db.flush()
                created_transcripts.append(transcript)

                logger.info(
                    "chunk_transcribed",
                    recording_id=str(recording_id),
                    chunk_index=chunk.chunk_index,
                    text_length=len(consensus.chosen_text),
                    accept=quality_report.accept,
                    consensus_outcome=consensus.outcome.value,
                )

                if not quality_report.accept:
                    for flag_reason in quality_report.flags:
                        hitl_item = HitlItem(
                            appointment_id=recording.appointment_id,
                            transcript_id=transcript.id,
                            reason=flag_reason,
                            status=HitlStatus.PENDING,
                            detail=combined_report,
                            user_facing_message=(
                                f"Chunk {chunk.chunk_index} transcript flagged for review "
                                f"({flag_reason.value.replace('_', ' ')}). "
                                f"Speaker: {chunk.speaker_label or 'unknown'}."
                            ),
                        )
                        db.add(hitl_item)
                        HITL_ITEMS_CREATED.labels(reason=flag_reason.value).inc()
                        hitl_items_created += 1

                if consensus.outcome == ConsensusOutcome.MISMATCH_NEEDS_REVIEW:
                    hitl_item = HitlItem(
                        appointment_id=recording.appointment_id,
                        transcript_id=transcript.id,
                        reason=HitlReason.CONSENSUS_MISMATCH,
                        status=HitlStatus.PENDING,
                        detail=combined_report,
                        user_facing_message=(
                            f"Chunk {chunk.chunk_index}: MedASR and Azure transcriptions "
                            f"disagree and neither is clearly more reliable. "
                            f"Speaker: {chunk.speaker_label or 'unknown'}."
                        ),
                    )
                    db.add(hitl_item)
                    HITL_ITEMS_CREATED.labels(reason=HitlReason.CONSENSUS_MISMATCH.value).inc()
                    hitl_items_created += 1

        recording.processing_status = AudioProcessingStatus.TRANSCRIPTION_COMPLETE
        await db.commit()

        for t in created_transcripts:
            await db.refresh(t)

        logger.info(
            "transcription_pipeline_complete",
            recording_id=str(recording_id),
            transcripts_created=len(created_transcripts),
            hitl_items_created=hitl_items_created,
        )
        return created_transcripts

    except Exception as exc:
        recording.processing_status = AudioProcessingStatus.TRANSCRIPTION_FAILED
        await db.commit()
        logger.error("transcription_pipeline_failed", recording_id=str(recording_id), error=str(exc))
        raise