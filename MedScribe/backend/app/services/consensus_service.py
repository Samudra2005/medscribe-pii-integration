"""
Compares MedASR (local) and Azure (cloud) transcription results for the
same chunk. Per explicit design: judges QUALITY, not just text
similarity -- a text-similarity-only approach can't tell you WHICH
transcript is more trustworthy when they disagree, only THAT they
disagree. Decision outcomes:

- Azure unavailable/failed -> use MedASR alone, no comparison needed
- Texts closely match -> consensus reached, use MedASR (already have it,
  no reason to prefer Azure when they agree)
- Texts diverge, but one is CLEARLY higher quality (confidence gap
  exceeds a threshold) -> use the better one automatically
- Texts diverge AND quality is ambiguous/similar -> CONSENSUS_MISMATCH,
  send to HITL with both versions, let a human decide

This is NOT algorithmic merging (no ROVER-style word-level voting) --
deliberately avoided per the reasoning that fabricating a third,
unverified "best guess" transcript is worse than clearly presenting two
real candidates to a human when automated resolution isn't confident.
"""
import difflib
from dataclasses import dataclass
from enum import Enum

from app.core.logging_config import get_logger
from app.models.enums import TranscriptSource

logger = get_logger(__name__)

# Chosen thresholds -- same honesty as Phase 10: these are reasonable
# starting defaults, not derived from a large real dataset yet.
TEXT_SIMILARITY_AGREEMENT_THRESHOLD = 0.85  # ratio above this = "they agree"
CLEAR_QUALITY_GAP_THRESHOLD = 0.15  # confidence difference needed to auto-prefer one


class ConsensusOutcome(str, Enum):
    MEDASR_ONLY = "medasr_only"          # Azure unavailable/failed
    CONSENSUS_AGREEMENT = "consensus_agreement"  # texts matched closely
    AUTO_RESOLVED_MEDASR = "auto_resolved_medasr"  # diverged, MedASR clearly better
    AUTO_RESOLVED_AZURE = "auto_resolved_azure"    # diverged, Azure clearly better
    MISMATCH_NEEDS_REVIEW = "mismatch_needs_review"  # diverged, ambiguous -> HITL


@dataclass
class ConsensusResult:
    outcome: ConsensusOutcome
    chosen_source: TranscriptSource
    chosen_text: str
    similarity_ratio: float | None
    medasr_confidence: float | None
    azure_confidence: float | None


def _text_similarity(text_a: str, text_b: str) -> float:
    """
    SequenceMatcher ratio -- a standard, well-understood string
    similarity measure (0.0 = completely different, 1.0 = identical).
    Deliberately simple and explainable over something like embedding-
    based semantic similarity: for comparing two ASR outputs of the
    SAME audio, surface-level word agreement is the right signal --
    semantic similarity could mask real word-level ASR errors that
    happen to preserve overall meaning, which is exactly what we need
    to catch here.
    """
    normalized_a = text_a.strip().lower()
    normalized_b = text_b.strip().lower()
    if not normalized_a and not normalized_b:
        return 1.0
    if not normalized_a or not normalized_b:
        return 0.0
    return difflib.SequenceMatcher(None, normalized_a, normalized_b).ratio()


def compare_transcriptions(
    medasr_text: str,
    medasr_confidence: float | None,
    azure_text: str,
    azure_confidence: float | None,
    azure_succeeded: bool,
) -> ConsensusResult:
    if not azure_succeeded:
        return ConsensusResult(
            outcome=ConsensusOutcome.MEDASR_ONLY,
            chosen_source=TranscriptSource.LOCAL_ASR,
            chosen_text=medasr_text,
            similarity_ratio=None,
            medasr_confidence=medasr_confidence,
            azure_confidence=None,
        )

    similarity = _text_similarity(medasr_text, azure_text)

    if similarity >= TEXT_SIMILARITY_AGREEMENT_THRESHOLD:
        outcome = ConsensusOutcome.CONSENSUS_AGREEMENT
        chosen_source = TranscriptSource.LOCAL_ASR
        chosen_text = medasr_text
    else:
        # They diverge. Only auto-resolve if we have real confidence
        # numbers for BOTH sides and the gap is clearly decisive --
        # otherwise this is exactly the ambiguous case that should go
        # to a human, not get silently guessed at.
        both_confidences_known = medasr_confidence is not None and azure_confidence is not None
        gap = (medasr_confidence - azure_confidence) if both_confidences_known else None

        if both_confidences_known and gap is not None and abs(gap) >= CLEAR_QUALITY_GAP_THRESHOLD:
            if gap > 0:
                outcome = ConsensusOutcome.AUTO_RESOLVED_MEDASR
                chosen_source = TranscriptSource.LOCAL_ASR
                chosen_text = medasr_text
            else:
                outcome = ConsensusOutcome.AUTO_RESOLVED_AZURE
                chosen_source = TranscriptSource.CLOUD_ASR
                chosen_text = azure_text
        else:
            outcome = ConsensusOutcome.MISMATCH_NEEDS_REVIEW
            # Default to MedASR's text as the "primary" record pending
            # review -- it's still the system's baseline source, human
            # review will decide the real final text via HITL resolution.
            chosen_source = TranscriptSource.LOCAL_ASR
            chosen_text = medasr_text

    result = ConsensusResult(
        outcome=outcome,
        chosen_source=chosen_source,
        chosen_text=chosen_text,
        similarity_ratio=similarity,
        medasr_confidence=medasr_confidence,
        azure_confidence=azure_confidence,
    )

    logger.info(
        "consensus_comparison_complete",
        outcome=outcome.value,
        similarity=round(similarity, 3) if similarity is not None else None,
        medasr_confidence=medasr_confidence,
        azure_confidence=azure_confidence,
    )

    return result