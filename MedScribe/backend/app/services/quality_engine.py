"""
Transcript quality engine (Phase 10). Combines MedASR's real per-token
confidence (validated against known-good/known-flawed examples -- see
PROJECT_STATUS.md) with heuristic checks that don't require a ground-
truth reference: repetition detection and length-vs-duration sanity.

This is NOT true hallucination/omission detection (that would need a
reference transcript to compare against, which we don't have for real
recordings) -- it's heuristic quality flagging. Framed honestly as such
in the resulting quality_report, not oversold as more than it is.

Thresholds below are chosen defaults based on the two real data points
we have so far (chunk_0028: mean=0.80 good, chunk_0001: mean=0.69
fragmented) -- explicitly flagged as needing recalibration once more
real recordings are processed and reviewed.
"""
import re
from dataclasses import dataclass, field

from app.core.logging_config import get_logger
from app.models.enums import HitlReason

logger = get_logger(__name__)

# Chosen thresholds -- see module docstring. First candidates to tune.
LOW_CONFIDENCE_MEAN_THRESHOLD = 0.72
LOW_CONFIDENCE_MIN_THRESHOLD = 0.25
MIN_WORDS_PER_SECOND = 0.5   # below this, suspiciously little text for the audio duration
MAX_WORDS_PER_SECOND = 4.5   # above this, suspiciously dense -- possible repetition/glitch
REPETITION_NGRAM_SIZE = 4    # look for repeated 4-word sequences
REPETITION_MAX_OCCURRENCES = 2  # a 4-word phrase repeating >2x is suspicious


@dataclass
class QualityReport:
    mean_confidence: float | None
    min_confidence: float | None
    word_count: int
    words_per_second: float | None
    repetition_detected: bool
    repeated_phrase: str | None
    flags: list[HitlReason] = field(default_factory=list)
    accept: bool = True  # False if any flag was raised

    def to_dict(self) -> dict:
        return {
            "mean_confidence": self.mean_confidence,
            "min_confidence": self.min_confidence,
            "word_count": self.word_count,
            "words_per_second": self.words_per_second,
            "repetition_detected": self.repetition_detected,
            "repeated_phrase": self.repeated_phrase,
            "flags": [f.value for f in self.flags],
            "accept": self.accept,
        }


def _detect_repetition(text: str) -> tuple[bool, str | None]:
    """
    ASR models are known to sometimes loop/repeat phrases when uncertain
    about audio content (a documented failure mode across ASR systems
    generally, not specific to MedASR). Checks for any N-word phrase
    that repeats more than REPETITION_MAX_OCCURRENCES times.
    """
    words = re.findall(r"\b\w+\b", text.lower())
    if len(words) < REPETITION_NGRAM_SIZE * (REPETITION_MAX_OCCURRENCES + 1):
        return False, None

    ngram_counts: dict[tuple[str, ...], int] = {}
    for i in range(len(words) - REPETITION_NGRAM_SIZE + 1):
        ngram = tuple(words[i : i + REPETITION_NGRAM_SIZE])
        ngram_counts[ngram] = ngram_counts.get(ngram, 0) + 1

    for ngram, count in ngram_counts.items():
        if count > REPETITION_MAX_OCCURRENCES:
            return True, " ".join(ngram)

    return False, None


def assess_transcript_quality(
    text: str,
    mean_confidence: float | None,
    min_confidence: float | None,
    chunk_duration_seconds: float,
) -> QualityReport:
    word_count = len(re.findall(r"\b\w+\b", text))
    words_per_second = word_count / chunk_duration_seconds if chunk_duration_seconds > 0 else None

    repetition_detected, repeated_phrase = _detect_repetition(text)

    flags: list[HitlReason] = []
    
    # Track each signal independently first, THEN decide flags -- this
    # lets us escalate on combinations, not just single-threshold trips.
    low_mean_confidence = mean_confidence is not None and mean_confidence < LOW_CONFIDENCE_MEAN_THRESHOLD
    low_min_confidence = min_confidence is not None and min_confidence < LOW_CONFIDENCE_MIN_THRESHOLD
    # A softer version of the min-confidence check -- a token that's
    # "somewhat uncertain" but not low enough to trip the hard threshold
    # alone. This is what lets us catch the real medication-name-error
    # case (min=0.29, just above the 0.25 hard threshold) WITHOUT
    # lowering the hard threshold itself and risking more false positives
    # -- it only matters in combination with another weak signal below.
    borderline_min_confidence = (
        min_confidence is not None and LOW_CONFIDENCE_MIN_THRESHOLD <= min_confidence < 0.35
    )
    speech_rate_too_dense = words_per_second is not None and words_per_second > MAX_WORDS_PER_SECOND
    speech_rate_too_sparse = words_per_second is not None and words_per_second < MIN_WORDS_PER_SECOND

    if low_mean_confidence or low_min_confidence:
        flags.append(HitlReason.LOW_ASR_CONFIDENCE)
    elif borderline_min_confidence and speech_rate_too_dense:
        # Neither signal alone crossed its hard threshold, but BOTH being
        # simultaneously borderline is a real escalation case -- exactly
        # the pattern in the medication-name example (min=0.29, rate=5.31,
        # both mildly off without either being individually damning).
        flags.append(HitlReason.LOW_ASR_CONFIDENCE)
        logger.info("quality_combined_signal_escalation", min_confidence=min_confidence, words_per_second=words_per_second)

    if repetition_detected:
        flags.append(HitlReason.HALLUCINATION_SUSPECTED)

    if speech_rate_too_sparse:
        flags.append(HitlReason.OMISSION_SUSPECTED)

    if speech_rate_too_dense and HitlReason.LOW_ASR_CONFIDENCE not in flags:
        # Dense speech rate on its own (without a confidence problem) is
        # still worth a lighter flag -- could be legitimate fast speech,
        # but also a known ASR failure signature (garbled/rushed output).
        # Reusing HALLUCINATION_SUSPECTED here since dense, rushed-looking
        # output is closer to that failure mode than a confidence issue.
        flags.append(HitlReason.HALLUCINATION_SUSPECTED)


    report = QualityReport(
        mean_confidence=mean_confidence,
        min_confidence=min_confidence,
        word_count=word_count,
        words_per_second=words_per_second,
        repetition_detected=repetition_detected,
        repeated_phrase=repeated_phrase,
        flags=flags,
        accept=len(flags) == 0,
    )

    logger.info(
        "quality_assessment_complete",
        word_count=word_count,
        words_per_second=round(words_per_second, 2) if words_per_second else None,
        flags=[f.value for f in flags],
        accept=report.accept,
    )

    return report