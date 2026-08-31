"""
Ties together VAD -> diarization -> chunk boundary merge -> physical
extraction -> DB persistence into audio_chunks. This is the single
entry point Phase 8's API endpoint calls; each sub-service stays
independently testable (as we already did step by step).
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as DBSession

from app.core.logging_config import get_logger
from app.models.audio import AudioChunk, AudioRecording
from app.models.enums import AudioProcessingStatus
from app.services.audio_service import AudioValidationError, resolve_absolute_path
from app.services.chunk_extraction_service import extract_chunk_audio
from app.services.chunking_service import build_chunks
from app.services.diarization_service import diarize_audio
from app.services.vad_service import detect_speech_regions

from app.core.metrics_helpers import track_pipeline_stage
from app.core.tracing import bind_appointment_trace


logger = get_logger(__name__)


async def run_chunking_pipeline(recording_id: uuid.UUID, db: DBSession) -> list[AudioChunk]:
    result = await db.execute(select(AudioRecording).where(AudioRecording.id == recording_id))
    recording = result.scalar_one_or_none()
    if recording is None:
        raise AudioValidationError("Audio recording not found")
    bind_appointment_trace(recording.appointment_id)

    if recording.processing_status == AudioProcessingStatus.VALIDATION_FAILED:
        raise AudioValidationError(
            "Cannot chunk a recording that failed validation: "
            f"{recording.validation_failure_reason}"
        )

    # The normalized file follows the fixed convention from Phase 7
    # (same recording id, .wav, in normalized/) -- derived here rather
    # than stored as a separate column, consistent with that design.
    normalized_relative_path = f"normalized/{recording_id}.wav"
    normalized_absolute_path = resolve_absolute_path(normalized_relative_path)

    if not normalized_absolute_path.exists():
        raise AudioValidationError(
            "Normalized audio file not found on disk -- was this recording "
            "successfully normalized in Phase 7's pipeline?"
        )

    # Existing chunks for this recording are cleared before regenerating.
    # CRITICAL FIX (found via real duplicate-data investigation): deleting
    # an AudioChunk sets any Transcript.audio_chunk_id pointing at it to
    # NULL (ondelete="SET NULL", by design -- see transcript.py), NOT a
    # cascade delete. This means re-chunking previously left ORPHANED
    # Transcript rows behind with a NULL chunk reference -- invisible to
    # Phase 9's own idempotency check (which only looks for transcripts
    # tied to the CURRENT chunk IDs), so they silently accumulated across
    # every re-chunk-then-retranscribe cycle. Confirmed via real data:
    # 34 duplicated transcript texts, each with one orphaned (NULL
    # audio_chunk_id) and one live copy, discovered because a real
    # MedGemma prompt was 2x bloated with duplicate content.
    # FIX: explicitly delete any transcripts already orphaned by a
    # PRIOR re-chunk (audio_chunk_id IS NULL for this appointment) before
    # deleting the chunks themselves, so this doesn't keep compounding.
    from app.models.transcript import Transcript

    orphaned_transcripts = await db.execute(
        select(Transcript).where(
            Transcript.appointment_id == select(AudioRecording.appointment_id)
            .where(AudioRecording.id == recording_id)
            .scalar_subquery(),
            Transcript.audio_chunk_id.is_(None),
        )
    )
    for orphan in orphaned_transcripts.scalars().all():
        await db.delete(orphan)

    existing = await db.execute(select(AudioChunk).where(AudioChunk.audio_recording_id == recording_id))
    for stale_chunk in existing.scalars().all():
        await db.delete(stale_chunk)
    await db.flush()
    
    recording.processing_status = AudioProcessingStatus.CHUNKING
    await db.commit()
    
    try:
        with track_pipeline_stage("chunk"):
            speech_regions = await detect_speech_regions(normalized_absolute_path)
            diarized_segments = await diarize_audio(normalized_absolute_path)
            boundaries = build_chunks(speech_regions, diarized_segments)

        if not boundaries:
            raise AudioValidationError(
                "No speech detected in this recording -- nothing to chunk."
            )

        created_chunks: list[AudioChunk] = []
        for boundary in boundaries:
            chunk_relative_path = await extract_chunk_audio(
                recording_id=recording_id,
                chunk_index=boundary.chunk_index,
                source_wav_absolute_path=normalized_absolute_path,
                start_seconds=boundary.start_seconds,
                end_seconds=boundary.end_seconds,
            )

            chunk = AudioChunk(
                audio_recording_id=recording_id,
                chunk_index=boundary.chunk_index,
                start_time_seconds=boundary.start_seconds,
                end_time_seconds=boundary.end_seconds,
                overlap_seconds=boundary.overlap_seconds,
                speaker_label=boundary.speaker_label,
                storage_path=chunk_relative_path,
            )
            db.add(chunk)
            created_chunks.append(chunk)

        recording.processing_status = AudioProcessingStatus.CHUNKING_COMPLETE
        await db.commit()

        for chunk in created_chunks:
            await db.refresh(chunk)

        logger.info(
            "chunking_pipeline_complete",
            recording_id=str(recording_id),
            chunks_created=len(created_chunks),
        )
        return created_chunks

    except AudioValidationError as exc:
        recording.processing_status = AudioProcessingStatus.VALIDATION_FAILED
        recording.validation_failure_reason = str(exc)
        await db.commit()
        raise