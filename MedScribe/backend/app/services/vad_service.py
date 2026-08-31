"""
Voice Activity Detection using Silero VAD. Runs BEFORE diarization --
identifies which regions of an audio file actually contain speech, so
we don't waste diarization compute (and RAM) on silence/dead air. This
is a separate, lighter first pass rather than relying on pyannote's own
internal VAD stage, per the two-stage design discussed for Phase 8.

Silero VAD is a small (~1-2MB) PyTorch model -- CPU-only here, consistent
with keeping the GPU free for MedASR/MedGemma (Phase 9).
"""
import asyncio
from dataclasses import dataclass
from pathlib import Path

from silero_vad import get_speech_timestamps, load_silero_vad, read_audio

from app.core.logging_config import get_logger

logger = get_logger(__name__)

# Model is loaded once per process and reused -- Silero VAD is small
# enough that keeping it resident in memory isn't a concern the way
# MedASR/MedGemma's GPU load/unload lifecycle is. This is a genuine
# exception to the "load on demand, unload after" pattern: that pattern
# exists specifically to manage GPU VRAM contention between MedASR and
# MedGemma, which doesn't apply here since Silero never touches the GPU
# and its footprint is negligible on system RAM.
_vad_model = None


def _load_model():
    global _vad_model

    if _vad_model is None:
        logger.info("silero_vad_loading")
        _vad_model = load_silero_vad()
        logger.info("silero_vad_loaded")

    return _vad_model


@dataclass
class SpeechRegion:
    start_seconds: float
    end_seconds: float


def _run_vad_sync(absolute_wav_path: Path) -> list[SpeechRegion]:
    """
    Synchronous VAD inference -- wrapped by an async caller below via
    asyncio.to_thread, since torch inference is CPU-blocking and would
    otherwise stall the event loop.
    """
    model = _load_model()

    wav = read_audio(
        str(absolute_wav_path),
        sampling_rate=16000,
    )

    timestamps = get_speech_timestamps(
        wav,
        model,
        sampling_rate=16000,
        return_seconds=True,
    )

    return [
        SpeechRegion(
            start_seconds=t["start"],
            end_seconds=t["end"],
        )
        for t in timestamps
    ]


async def detect_speech_regions(absolute_wav_path: Path) -> list[SpeechRegion]:
    """
    Expects a 16kHz mono WAV -- i.e. the NORMALIZED file from Phase 7's
    pipeline, not the original upload. Returns a list of speech regions
    in chronological order; gaps between them are silence/non-speech.
    """
    regions = await asyncio.to_thread(_run_vad_sync, absolute_wav_path)
    logger.info(
        "vad_complete",
        file=str(absolute_wav_path),
        regions_found=len(regions),
    )
    return regions

