"""
Combines VAD speech regions + diarization speaker turns into the actual
chunk boundaries written to audio_chunks. Two separate signals are
merged here:

- VAD tells us WHERE speech actually is (vs silence/dead air)
- Diarization tells us WHO is speaking during speech

A "chunk" is a maximal run of consecutive VAD speech regions that share
the same dominant speaker and aren't separated by a long silence gap.
This avoids two bad outcomes: (a) one giant chunk spanning the whole
recording regardless of speaker changes, and (b) hundreds of tiny
sub-second chunks that are useless for ASR context.
"""
from dataclasses import dataclass

from app.core.logging_config import get_logger
from app.services.diarization_service import DiarizedSegment
from app.services.vad_service import SpeechRegion

logger = get_logger(__name__)

# Tunable thresholds -- chosen defaults, not derived from your specific
# data yet. Flagging as the first thing to tune once real chunk output
# is reviewed against real recordings.
MAX_SILENCE_GAP_SECONDS = 2.0     # split into a new chunk if the pause exceeds this
CHUNK_OVERLAP_SECONDS = 0.5       # each chunk overlaps the next by this much
MIN_CHUNK_DURATION_SECONDS = 1.0  # discard/merge chunks shorter than this
MAX_CHUNK_DURATION_SECONDS = 25.0 # force a split if a chunk would exceed this


@dataclass
class ChunkBoundary:
    chunk_index: int
    start_seconds: float
    end_seconds: float
    overlap_seconds: float
    speaker_label: str


def _dominant_speaker(
    region_start: float, region_end: float, diarized_segments: list[DiarizedSegment]
) -> str:
    """
    A VAD region can straddle a diarization boundary (the two models
    don't produce identical boundaries). We assign the speaker whose
    diarized segment has the most temporal OVERLAP with this VAD region,
    rather than just picking whichever segment contains the region's
    start time -- more robust against slight boundary disagreement
    between the two models.
    """
    best_speaker = "UNKNOWN"
    best_overlap = 0.0

    for seg in diarized_segments:
        overlap_start = max(region_start, seg.start_seconds)
        overlap_end = min(region_end, seg.end_seconds)
        overlap = max(0.0, overlap_end - overlap_start)
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = seg.speaker_label

    return best_speaker


def build_chunks(
    speech_regions: list[SpeechRegion],
    diarized_segments: list[DiarizedSegment],
) -> list[ChunkBoundary]:
    if not speech_regions:
        logger.warning("chunking_no_speech_regions")
        return []

    # Tag every VAD region with its dominant speaker first.
    tagged_regions = [
        (region, _dominant_speaker(region.start_seconds, region.end_seconds, diarized_segments))
        for region in speech_regions
    ]

    raw_groups: list[list[SpeechRegion]] = []
    current_group: list[SpeechRegion] = [tagged_regions[0][0]]
    current_speaker = tagged_regions[0][1]

    for (region, speaker) in tagged_regions[1:]:
        gap = region.start_seconds - current_group[-1].end_seconds
        speaker_changed = speaker != current_speaker
        would_exceed_max_duration = (
            region.end_seconds - current_group[0].start_seconds > MAX_CHUNK_DURATION_SECONDS
        )

        if speaker_changed or gap > MAX_SILENCE_GAP_SECONDS or would_exceed_max_duration:
            raw_groups.append(current_group)
            current_group = [region]
            current_speaker = speaker
        else:
            current_group.append(region)

    raw_groups.append(current_group)

    # Convert groups into chunk boundaries, merging any that end up
    # shorter than MIN_CHUNK_DURATION_SECONDS into the next group rather
    # than emitting a near-useless sub-second chunk.
    chunks: list[ChunkBoundary] = []
    chunk_index = 0
    pending_group: list[SpeechRegion] | None = None

    for group in raw_groups:
        merged = (pending_group + group) if pending_group else group
        duration = merged[-1].end_seconds - merged[0].start_seconds

        if duration < MIN_CHUNK_DURATION_SECONDS:
            pending_group = merged
            continue

        pending_group = None
        speaker = _dominant_speaker(merged[0].start_seconds, merged[-1].end_seconds, diarized_segments)
        chunks.append(
            ChunkBoundary(
                chunk_index=chunk_index,
                start_seconds=max(0.0, merged[0].start_seconds - CHUNK_OVERLAP_SECONDS if chunk_index > 0 else merged[0].start_seconds),
                end_seconds=merged[-1].end_seconds + CHUNK_OVERLAP_SECONDS,
                overlap_seconds=CHUNK_OVERLAP_SECONDS,
                speaker_label=speaker,
            )
        )
        chunk_index += 1

    # If a short group never got merged (e.g. it was the very last group),
    # attach it to the final chunk rather than dropping it silently.
    if pending_group and chunks:
        chunks[-1].end_seconds = max(chunks[-1].end_seconds, pending_group[-1].end_seconds + CHUNK_OVERLAP_SECONDS)

    logger.info(
        "chunking_complete",
        speech_regions=len(speech_regions),
        chunks_produced=len(chunks),
    )
    return chunks