"""
Audio ingestion endpoints (Phase 7). Two entry points, matching
InputSource: file upload (multipart/form-data) and live recording
(raw bytes from a browser MediaRecorder blob, e.g. audio/webm).

Both paths converge on the same pipeline: validate real file properties
via ffprobe -> save original -> normalize to 16kHz mono WAV via ffmpeg
-> update AudioRecording.processing_status accordingly. Chunking (VAD/
diarization) is explicitly out of scope here -- Phase 8.
"""
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as DBSession

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.logging_config import get_logger
from app.db.session import get_db
from app.models.appointment import Appointment
from app.models.audio import AudioRecording
from app.models.enums import AudioProcessingStatus, AuditAction, InputSource, RecordingStage
from app.models.audio import AudioChunk
from app.schemas.audio import AudioRecordingSummary
from app.schemas.audio_chunk import AudioChunkSummary
from app.services.chunking_orchestrator import run_chunking_pipeline

from app.models.transcript import Transcript
from app.schemas.transcript import TranscriptSummary
from app.services.transcription_orchestrator import run_transcription_pipeline

from app.models.extracted_entity import ExtractedEntitySet
from app.schemas.extracted_entity import ExtractedEntitySetSummary
from app.services.ner_orchestrator import run_ner_pipeline

from app.api.deps import require_doctor
from app.models.prescription import Prescription
from app.schemas.prescription import PrescriptionSummary
from app.services.prescription_orchestrator import run_prescription_draft_pipeline

from app.schemas.auth import CurrentUser
from app.services.audio_service import (
    AudioValidationError,
    compute_sha256,
    normalize_to_wav,
    probe_audio_file,
    resolve_absolute_path,
    save_original_file,
    validate_probed_audio,
)
from app.services.audit_service import write_audit_log

logger = get_logger(__name__)
settings = get_settings()

router = APIRouter(prefix="/audio", tags=["audio"])


async def _get_valid_appointment(appointment_id: uuid.UUID, db: DBSession) -> Appointment:
    result = await db.execute(
        select(Appointment).where(
            Appointment.id == appointment_id, Appointment.deleted_at.is_(None)
        )
    )
    appointment = result.scalar_one_or_none()
    if appointment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")
    return appointment


def _extension_from_filename(filename: str | None) -> str:
    if filename and "." in filename:
        return filename.rsplit(".", 1)[-1]
    return "bin"


async def _process_and_store(
    *,
    appointment_id: uuid.UUID,
    input_source: InputSource,
    recording_stage=RecordingStage,
    raw_bytes: bytes,
    original_filename: str | None,
    mime_type: str | None,
    request: Request,
    current_user: CurrentUser,
    db: DBSession,
) -> AudioRecordingSummary:
    if len(raw_bytes) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")

    if len(raw_bytes) > settings.MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum size of {settings.MAX_UPLOAD_SIZE_BYTES // (1024*1024)}MB",
        )

    await _get_valid_appointment(appointment_id, db)

    sha256_hash = compute_sha256(raw_bytes)

    # Detect exact-duplicate uploads for the same appointment -- a flaky
    # client retry re-sending the same bytes shouldn't create a second
    # DB row and a second ffmpeg normalization pass.
    existing = await db.execute(
        select(AudioRecording).where(
            AudioRecording.appointment_id == appointment_id,
            AudioRecording.sha256_hash == sha256_hash,
        )
    )
    duplicate = existing.scalar_one_or_none()
    if duplicate is not None:
        logger.info(
            "audio_duplicate_upload_detected",
            appointment_id=str(appointment_id),
            existing_recording_id=str(duplicate.id),
        )
        return AudioRecordingSummary.model_validate(duplicate)

    recording = AudioRecording(
        appointment_id=appointment_id,
        uploaded_by_id=current_user.user_id,
        input_source=input_source,
        recording_stage=recording_stage,
        storage_path="",  # set below once we know the recording's id
        original_filename=original_filename,
        mime_type=mime_type,
        file_size_bytes=len(raw_bytes),
        sha256_hash=sha256_hash,
        processing_status=AudioProcessingStatus.UPLOADED,
    )
    db.add(recording)
    await db.flush()  # assigns recording.id without committing yet

    extension = _extension_from_filename(original_filename)
    original_relative_path = await save_original_file(recording.id, extension, raw_bytes)
    recording.storage_path = original_relative_path
    await db.commit()
    await db.refresh(recording)

    # Validation + normalization. On failure, we keep the DB row (with
    # the original file saved) but mark it VALIDATION_FAILED rather than
    # deleting it -- the clinician/admin should be able to see WHY a
    # recording failed, not have it silently vanish.
    try:
        recording.processing_status = AudioProcessingStatus.VALIDATING
        await db.commit()

        absolute_original_path = resolve_absolute_path(original_relative_path)
        probed = await probe_audio_file(absolute_original_path)
        validate_probed_audio(probed)

        recording.duration_seconds = probed.duration_seconds
        recording.quality_metrics = {
            "probed_sample_rate": probed.sample_rate,
            "probed_channels": probed.channels,
            "probed_codec": probed.codec_name,
        }

        recording.processing_status = AudioProcessingStatus.NORMALIZING
        await db.commit()

        await normalize_to_wav(recording.id, absolute_original_path)

        # Normalized file's path follows a fixed convention (same recording
        # id, .wav extension, in normalized/) so we don't need a second DB
        # column for it right now -- Phase 8/9 will derive it the same way.
        recording.processing_status = AudioProcessingStatus.UPLOADED
        await db.commit()
        await db.refresh(recording)

    except AudioValidationError as exc:
        recording.processing_status = AudioProcessingStatus.VALIDATION_FAILED
        recording.validation_failure_reason = str(exc)
        await db.commit()
        await db.refresh(recording)
        logger.warning(
            "audio_validation_failed",
            recording_id=str(recording.id),
            reason=str(exc),
        )
        # Still return 201 with the recording showing its failed state,
        # rather than a 400 -- the upload itself succeeded (we have the
        # file, we have a DB row), it's the CONTENT that's invalid. This
        # matters for the frontend: it can show "uploaded but failed
        # validation: <reason>" instead of losing the attempt entirely.

    await write_audit_log(
        db,
        action=AuditAction.CREATE,
        actor_user_id=current_user.user_id,
        actor_role=current_user.role.value,
        target_entity_type="audio_recording",
        target_entity_id=recording.id,
        ip_address=request.client.host if request.client else None,
        metadata={
            "appointment_id": str(appointment_id),
            "input_source": input_source.value,
            "processing_status": recording.processing_status.value,
        },
    )

    return AudioRecordingSummary.model_validate(recording)


@router.post("/upload", response_model=AudioRecordingSummary, status_code=status.HTTP_201_CREATED)
async def upload_audio_file(
    request: Request,
    appointment_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    recording_stage: RecordingStage = Form(default=RecordingStage.DOCTOR_CONSULTATION),
    current_user: CurrentUser = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> AudioRecordingSummary:
    """
    Standard file upload -- multipart/form-data with an appointment_id
    field and a file field. Used for pre-recorded audio files (e.g. a
    clinician uploads an existing recording rather than recording live
    in-browser).
    """
    if file.content_type not in settings.allowed_audio_mime_types_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported file type '{file.content_type}'. "
                f"Allowed types: {', '.join(settings.allowed_audio_mime_types_list)}"
            ),
        )

    raw_bytes = await file.read()

    return await _process_and_store(
        appointment_id=appointment_id,
        input_source=InputSource.UPLOADED_AUDIO,
        recording_stage=recording_stage,
        raw_bytes=raw_bytes,
        original_filename=file.filename,
        mime_type=file.content_type,
        request=request,
        current_user=current_user,
        db=db,
    )


@router.post("/record", response_model=AudioRecordingSummary, status_code=status.HTTP_201_CREATED)
async def upload_live_recording(
    request: Request,
    appointment_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    recording_stage: RecordingStage = Form(default=RecordingStage.DOCTOR_CONSULTATION),
    current_user: CurrentUser = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> AudioRecordingSummary:
    """
    Live-recording upload -- functionally identical processing to
    /upload, but kept as a SEPARATE endpoint (not just a query param)
    because:
    1. input_source needs to be tagged LIVE_RECORDING vs UPLOADED_AUDIO,
       and making that an explicit route rather than a client-supplied
       field means a client can't misreport how the audio was captured
       -- this distinction matters for later quality/trust weighting
       (Phase 10) between a controlled upload and a live browser capture.
    2. The frontend's MediaRecorder flow will POST here as soon as
       recording stops, with a fixed blob mime type (typically
       audio/webm) -- keeping it a separate route makes that call site
       simpler and its intent explicit in server logs/audit entries.
    """
    if file.content_type not in settings.allowed_audio_mime_types_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported recording format '{file.content_type}'. "
                f"Allowed types: {', '.join(settings.allowed_audio_mime_types_list)}"
            ),
        )

    raw_bytes = await file.read()

    return await _process_and_store(
        appointment_id=appointment_id,
        input_source=InputSource.LIVE_RECORDING,
        recording_stage=recording_stage,
        raw_bytes=raw_bytes,
        original_filename=file.filename or "live_recording.webm",
        mime_type=file.content_type,
        request=request,
        current_user=current_user,
        db=db,
    )


@router.get("/{recording_id}", response_model=AudioRecordingSummary)
async def get_audio_recording(
    recording_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> AudioRecordingSummary:
    result = await db.execute(select(AudioRecording).where(AudioRecording.id == recording_id))
    recording = result.scalar_one_or_none()
    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio recording not found")
    return AudioRecordingSummary.model_validate(recording)


@router.get("", response_model=list[AudioRecordingSummary])
async def list_audio_recordings(
    appointment_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[AudioRecordingSummary]:
    result = await db.execute(
        select(AudioRecording)
        .where(AudioRecording.appointment_id == appointment_id)
        .order_by(AudioRecording.created_at.desc())
    )
    recordings = result.scalars().all()
    return [AudioRecordingSummary.model_validate(r) for r in recordings]

@router.post("/{recording_id}/chunk", response_model=list[AudioChunkSummary], status_code=status.HTTP_201_CREATED)
async def chunk_audio_recording(
    recording_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[AudioChunkSummary]:
    """
    Runs the full Phase 8 pipeline (VAD -> diarization -> merge ->
    extract -> persist) for an already-normalized recording. This is a
    SEPARATE, explicitly-triggered step from upload -- not run
    automatically at the end of /audio/upload -- because diarization is
    the heaviest operation in the pipeline so far (multiple minutes even
    on a short recording, per what we measured), and forcing every
    upload request to block on it would make the upload endpoint itself
    unacceptably slow. Chunking is triggered as its own call once a
    recording is confirmed uploaded/normalized successfully.
    """
    try:
        chunks = await run_chunking_pipeline(recording_id, db)
    except AudioValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return [AudioChunkSummary.model_validate(c) for c in chunks]


@router.get("/{recording_id}/chunks", response_model=list[AudioChunkSummary])
async def list_audio_chunks(
    recording_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[AudioChunkSummary]:
    result = await db.execute(
        select(AudioChunk)
        .where(AudioChunk.audio_recording_id == recording_id)
        .order_by(AudioChunk.chunk_index)
    )
    chunks = result.scalars().all()
    return [AudioChunkSummary.model_validate(c) for c in chunks]

@router.post("/{recording_id}/transcribe", response_model=list[TranscriptSummary], status_code=status.HTTP_201_CREATED)
async def transcribe_audio_recording(
    recording_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[TranscriptSummary]:
    """
    Runs MedASR over every chunk of a chunking_complete recording.
    Explicitly separate from chunking (its own POST call), same reasoning
    as chunking being separate from upload: this is a real, non-trivial
    amount of GPU inference time (one model load + N chunk transcriptions),
    and there's no background task queue yet to hide that latency from
    the caller.
    """
    try:
        transcripts = await run_transcription_pipeline(recording_id, db)
    except AudioValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return [TranscriptSummary.model_validate(t) for t in transcripts]


@router.get("/{recording_id}/transcripts", response_model=list[TranscriptSummary])
async def list_transcripts_for_recording(
    recording_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[TranscriptSummary]:
    result = await db.execute(
        select(Transcript)
        .join(AudioChunk, Transcript.audio_chunk_id == AudioChunk.id)
        .where(AudioChunk.audio_recording_id == recording_id)
        .order_by(AudioChunk.chunk_index)
    )
    transcripts = result.scalars().all()
    return [TranscriptSummary.model_validate(t) for t in transcripts]

@router.post("/{recording_id}/extract-entities", response_model=list[ExtractedEntitySetSummary], status_code=status.HTTP_201_CREATED)
async def extract_entities_for_recording(
    recording_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[ExtractedEntitySetSummary]:
    try:
        entity_sets = await run_ner_pipeline(recording_id, db)
    except AudioValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return [ExtractedEntitySetSummary.model_validate(e) for e in entity_sets]


@router.get("/{recording_id}/entities", response_model=list[ExtractedEntitySetSummary])
async def list_entities_for_recording(
    recording_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[ExtractedEntitySetSummary]:
    result = await db.execute(
        select(ExtractedEntitySet)
        .join(Transcript, ExtractedEntitySet.transcript_id == Transcript.id)
        .where(Transcript.appointment_id == select(AudioRecording.appointment_id).where(AudioRecording.id == recording_id).scalar_subquery())
    )
    entity_sets = result.scalars().all()
    return [ExtractedEntitySetSummary.model_validate(e) for e in entity_sets]

@router.post("/appointments/{appointment_id}/draft-prescription", response_model=PrescriptionSummary, status_code=status.HTTP_201_CREATED)
async def draft_prescription(
    appointment_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_doctor),
    db: DBSession = Depends(get_db),
) -> PrescriptionSummary:
    """
    Generates a draft prescription via MedGemma from validated transcript/
    entity data. Doctor-only (require_doctor) -- this creates a DRAFT
    (is_final=False), never a finalized prescription; Phase 14 builds the
    actual doctor review/approve/edit workflow on top of this.

    REAL, MEASURED PERFORMANCE: ~80-90 seconds per real appointment
    (2.75-2.9 tok/s due to partial GPU/CPU offload on an 8GB card, see
    PROJECT_STATUS.md). This is a genuinely slow synchronous request --
    same known limitation as chunking/transcription, not newly introduced.
    """
    try:
        prescription = await run_prescription_draft_pipeline(appointment_id, current_user.user_id, db)
    except AudioValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return PrescriptionSummary.model_validate(prescription)