"""
Audio file handling: saving uploads to disk, computing content hashes,
inspecting real file properties via ffprobe, and normalizing to 16kHz
mono WAV via ffmpeg. All subprocess-based -- no additional heavy Python
audio libraries needed for Phase 7's scope (format/duration/sample-rate
validation), which keeps this lightweight on your resource-constrained
setup. Deeper audio quality analysis (SNR, clipping %) is deliberately
deferred to Phase 10's quality engine, per the roadmap boundary.
"""
import asyncio
import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)
settings = get_settings()


class AudioValidationError(Exception):
    """Raised when a file fails format/integrity validation. The message
    is safe to show the user directly (mirrors validation_failure_reason
    on the AudioRecording model)."""


@dataclass
class ProbedAudioInfo:
    duration_seconds: float
    sample_rate: int
    channels: int
    codec_name: str


def _ensure_storage_dirs() -> None:
    Path(settings.audio_originals_path).mkdir(parents=True, exist_ok=True)
    Path(settings.audio_normalized_path).mkdir(parents=True, exist_ok=True)


def compute_sha256(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def build_storage_filename(recording_id: uuid.UUID, extension: str) -> str:
    """
    Filename on disk is just the recording's UUID + original extension --
    deliberately NOT the original filename (which could contain PII in
    the filename itself, e.g. "john_smith_visit.mp3", or unsafe path
    characters). The real original_filename is preserved separately in
    the DB column for display purposes only, never used for the actual
    disk path.
    """
    clean_ext = extension.lstrip(".").lower() or "bin"
    return f"{recording_id}.{clean_ext}"


async def save_original_file(recording_id: uuid.UUID, extension: str, file_bytes: bytes) -> str:
    """
    Saves the raw uploaded bytes to storage/audio/originals/. Returns the
    RELATIVE storage path (relative to AUDIO_STORAGE_ROOT) that gets
    stored in AudioRecording.storage_path -- never an absolute path, per
    the model's own docstring design intent.
    """
    _ensure_storage_dirs()
    filename = build_storage_filename(recording_id, extension)
    full_path = Path(settings.audio_originals_path) / filename

    await asyncio.to_thread(full_path.write_bytes, file_bytes)

    relative_path = f"originals/{filename}"
    logger.info(
        "audio_original_saved",
        recording_id=str(recording_id),
        relative_path=relative_path,
        size_bytes=len(file_bytes),
    )
    return relative_path


async def probe_audio_file(absolute_path: Path) -> ProbedAudioInfo:
    """
    Runs ffprobe on the saved file to get its REAL properties, never
    trusting the client-supplied MIME type or file extension alone --
    a client could send a corrupt file, or mislabel a video file as
    audio, and we want to catch that here rather than downstream in
    the ASR pipeline where the failure would be much harder to diagnose.
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration:stream=sample_rate,channels,codec_name",
        "-of", "json",
        str(absolute_path),
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        raise AudioValidationError(
            "The uploaded file could not be read as a valid audio file. "
            "It may be corrupted or in an unsupported format."
        )

    try:
        data = json.loads(stdout)
        stream = data["streams"][0]
        duration = float(data["format"]["duration"])
        sample_rate = int(stream["sample_rate"])
        channels = int(stream["channels"])
        codec_name = stream.get("codec_name", "unknown")
    except (KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
        logger.error("ffprobe_parse_failed", error=str(exc), raw_stdout=stdout.decode(errors="replace"))
        raise AudioValidationError(
            "Could not determine audio properties from the uploaded file."
        ) from exc

    return ProbedAudioInfo(
        duration_seconds=duration,
        sample_rate=sample_rate,
        channels=channels,
        codec_name=codec_name,
    )


def validate_probed_audio(info: ProbedAudioInfo) -> None:
    """
    Basic sanity checks -- deliberately NOT a full quality engine (that's
    Phase 10). This just rejects the obviously-broken cases: empty/near-
    zero duration, absurdly long files (likely a wrong file entirely),
    and a sample rate too low to be usable speech audio.
    """
    if info.duration_seconds < 0.5:
        raise AudioValidationError(
            f"Audio is too short ({info.duration_seconds:.2f}s) to be a valid recording."
        )
    if info.duration_seconds > 4 * 60 * 60:  # 4 hours
        raise AudioValidationError(
            f"Audio duration ({info.duration_seconds / 60:.0f} minutes) exceeds the "
            "maximum expected length for a single consultation recording."
        )
    if info.sample_rate < 8000:
        raise AudioValidationError(
            f"Sample rate ({info.sample_rate}Hz) is too low for reliable speech recognition."
        )


async def normalize_to_wav(recording_id: uuid.UUID, original_absolute_path: Path) -> str:
    """
    Converts the original file to 16kHz mono WAV via ffmpeg -- MedASR's
    expected input format (Phase 9). Returns the RELATIVE storage path
    of the normalized file, same convention as save_original_file.
    """
    _ensure_storage_dirs()
    filename = build_storage_filename(recording_id, "wav")
    full_output_path = Path(settings.audio_normalized_path) / filename

    cmd = [
        "ffmpeg",
        "-y",  # overwrite if re-normalizing
        "-i", str(original_absolute_path),
        "-ar", "16000",   # sample rate
        "-ac", "1",       # mono
        "-c:a", "pcm_s16le",  # standard uncompressed WAV codec
        str(full_output_path),
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()

    if process.returncode != 0:
        logger.error(
            "ffmpeg_normalize_failed",
            recording_id=str(recording_id),
            stderr=stderr.decode(errors="replace")[-1000:],  # last 1000 chars, avoid giant log lines
        )
        raise AudioValidationError("Audio normalization failed. The file may be corrupted.")

    relative_path = f"normalized/{filename}"
    logger.info("audio_normalized", recording_id=str(recording_id), relative_path=relative_path)
    return relative_path


def resolve_absolute_path(relative_path: str) -> Path:
    """
    relative_path is like 'originals/<uuid>.mp3' or 'normalized/<uuid>.wav'
    -- this resolves it against AUDIO_STORAGE_ROOT for actual filesystem
    operations (ffprobe/ffmpeg need real paths, not our DB's relative ones).
    """
    return Path(settings.AUDIO_STORAGE_ROOT) / relative_path