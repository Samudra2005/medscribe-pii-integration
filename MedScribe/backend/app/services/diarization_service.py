"""
Speaker diarization using pyannote.audio. Runs CPU-only (never moved to
.to(cuda)) to keep GPU free for MedASR/MedGemma per the resource plan.
num_speakers is hardcoded to 2 -- every recording is a nurse/doctor +
patient conversation, never more, so we don't ask pyannote to guess
speaker count, which simplifies and speeds up its clustering step.
"""
import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

import torch
from pyannote.audio import Pipeline

from app.core.config import get_settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)
settings = get_settings()

# CPU thread contention is a well-documented cause of severe slowdowns in
# pyannote 3.1's CPU pipeline (multiple public reports of 7-10 minute
# recordings taking 20-30+ minutes to diarize on CPU). torch defaults to
# spawning threads equal to all visible CPU cores, which inside WSL2's
# virtualized CPU topology can cause oversubscription/contention rather
# than real speedup. Pinning explicitly is the first, cheapest fix to
# try before assuming the hardware itself is the bottleneck.
torch.set_num_threads(max(1, os.cpu_count() or 4))

_diarization_pipeline: Pipeline | None = None


def _load_pipeline() -> Pipeline:
    global _diarization_pipeline

    if _diarization_pipeline is None:
        logger.info("pyannote_pipeline_loading")

        _diarization_pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-community-1",
            token=settings.HUGGINGFACE_TOKEN,
        )

        # CPU-only deliberately: keep GPU available for MedASR/MedGemma.
        logger.info("pyannote_pipeline_loaded")

    return _diarization_pipeline

@dataclass
class DiarizedSegment:
    start_seconds: float
    end_seconds: float
    speaker_label: str  # pyannote's raw label, e.g. "SPEAKER_00" / "SPEAKER_01"


def _run_diarization_sync(
    absolute_wav_path: Path,
) -> list[DiarizedSegment]:
    pipeline = _load_pipeline()

    output = pipeline(
        str(absolute_wav_path),
        num_speakers=2,
    )

    diarization = output.speaker_diarization

    segments = []

    for turn, _, speaker in diarization.itertracks(yield_label=True):
        segments.append(
            DiarizedSegment(
                start_seconds=turn.start,
                end_seconds=turn.end,
                speaker_label=speaker,
            )
        )

    return segments


async def diarize_audio(absolute_wav_path: Path) -> list[DiarizedSegment]:
    """
    Expects a 16kHz mono WAV (the normalized Phase 7 output). Returns
    diarized segments in chronological order. This is the heaviest
    single operation in the pipeline so far -- expect this to take
    noticeably longer than VAD, proportional to recording length.
    """
    segments = await asyncio.to_thread(_run_diarization_sync, absolute_wav_path)
    logger.info(
        "diarization_complete",
        file=str(absolute_wav_path),
        segments_found=len(segments),
    )
    return segments