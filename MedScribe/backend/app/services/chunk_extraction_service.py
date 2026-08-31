"""
Extracts each computed chunk boundary into its own physical audio file
on disk, via ffmpeg -ss/-to slicing of the normalized WAV. Same
async subprocess pattern as Phase 7's normalize_to_wav -- never blocks
the event loop.
"""
import asyncio
import uuid
from pathlib import Path

from app.core.config import get_settings
from app.core.logging_config import get_logger
from app.services.audio_service import AudioValidationError

logger = get_logger(__name__)
settings = get_settings()


def _chunks_dir_for_recording(recording_id: uuid.UUID) -> Path:
    # Chunks live under storage/audio/chunks/<recording_id>/ -- grouped
    # per-recording rather than flat, since a single recording can
    # produce dozens of chunk files and we don't want one giant flat
    # directory across every recording in the system.
    return Path(settings.AUDIO_STORAGE_ROOT) / "chunks" / str(recording_id)


async def extract_chunk_audio(
    recording_id: uuid.UUID,
    chunk_index: int,
    source_wav_absolute_path: Path,
    start_seconds: float,
    end_seconds: float,
) -> str:
    """
    Returns the RELATIVE storage path (relative to AUDIO_STORAGE_ROOT),
    matching the convention used throughout Phase 7.
    """
    chunks_dir = _chunks_dir_for_recording(recording_id)
    await asyncio.to_thread(chunks_dir.mkdir, parents=True, exist_ok=True)

    filename = f"chunk_{chunk_index:04d}.wav"
    output_path = chunks_dir / filename
    duration = end_seconds - start_seconds

    cmd = [
        "ffmpeg",
        "-y",
        "-ss", f"{start_seconds:.3f}",
        "-i", str(source_wav_absolute_path),
        "-t", f"{duration:.3f}",
        "-c", "copy",  # no re-encoding needed, source is already 16kHz mono WAV
        str(output_path),
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()

    if process.returncode != 0:
        logger.error(
            "chunk_extraction_failed",
            recording_id=str(recording_id),
            chunk_index=chunk_index,
            stderr=stderr.decode(errors="replace")[-500:],
        )
        raise AudioValidationError(f"Failed to extract chunk {chunk_index}")

    relative_path = f"chunks/{recording_id}/{filename}"
    return relative_path