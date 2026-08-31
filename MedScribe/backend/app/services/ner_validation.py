"""
Confidence-based entity validation (Phase 12). Built directly from real
evidence, not an assumed threshold: on a full real 49-transcript batch,
clean/correct entity catches (diarrhea, vomiting, gastroenteritis,
asthma, paracetamol, Dirid) clustered at confidence 0.85-0.96, while
clear false positives / low-value fragments (bare "kay", "le", "blood"
alone, "gas") clustered at 0.56-0.69, with one exception ("kay" at 0.88
-- flagged below, threshold alone doesn't catch everything).

CRITICAL DESIGN REQUIREMENT (explicit user instruction): rejected/low-
confidence entities are NEVER deleted or dropped from the record. Every
entity either model produced is preserved permanently in
raw_entities (set once, in ner_orchestrator.py, never touched again).
This module only produces a SEPARATE validated_entities view --
raw_entities remains the complete, unfiltered, auditable ground truth
for every extraction pass, supporting future threshold re-tuning
without re-running inference.
"""
from dataclasses import dataclass, field

from app.services.ner_service import ExtractedEntity, NerResult

# Chosen based on the real confidence distribution observed above --
# NOT a large statistically-derived number, one real batch. Flagged as
# the first threshold to revisit once more real recordings are processed.
CONFIDENCE_ACCEPT_THRESHOLD = 0.75

# Very short, low-CONFIDENCE entity text is rejected -- "kay" scored
# 0.88, ABOVE this narrower confidence bar, so it's caught by requiring
# BOTH shortness AND merely-good-not-excellent confidence together, not
# length alone. This is deliberately narrower than the original length-
# only rule: with fragment-merging now fixing the "Dirid"/"paracetamol"
# tokenization-artifact problem at its root (see _merge_adjacent_fragments
# in ner_service.py), a short REAL term with very high confidence (like
# a correctly-merged "Dirid" at ~0.92) should NOT be rejected just for
# being short -- only short AND not-highly-confident should be suspect.
MIN_ENTITY_TEXT_LENGTH = 4
SHORT_ENTITY_CONFIDENCE_FLOOR = 0.90  # short entities need THIS MUCH confidence to survive

@dataclass
class ValidatedEntity:
    text: str
    label: str
    score: float
    start: int
    end: int
    status: str  # "accepted" or "rejected"
    rejection_reason: str | None = None


@dataclass
class ValidationResult:
    entities: list[ValidatedEntity] = field(default_factory=list)
    all_passed: bool = True
    mean_confidence: float | None = None

    def to_dict(self) -> dict:
        return {
            "entities": [
                {
                    "text": e.text,
                    "label": e.label,
                    "score": round(e.score, 4),
                    "start": e.start,
                    "end": e.end,
                    "status": e.status,
                    "rejection_reason": e.rejection_reason,
                }
                for e in self.entities
            ],
            "accepted_count": sum(1 for e in self.entities if e.status == "accepted"),
            "rejected_count": sum(1 for e in self.entities if e.status == "rejected"),
        }


def _validate_entity(entity: ExtractedEntity) -> ValidatedEntity:
    is_short = len(entity.text.strip()) < MIN_ENTITY_TEXT_LENGTH

    if is_short and entity.score < SHORT_ENTITY_CONFIDENCE_FLOOR:
        return ValidatedEntity(
            text=entity.text, label=entity.label, score=entity.score,
            start=entity.start, end=entity.end,
            status="rejected",
            rejection_reason=(
                f"Entity text is short ({len(entity.text.strip())} chars) and confidence "
                f"{entity.score:.3f} does not meet the higher bar ({SHORT_ENTITY_CONFIDENCE_FLOOR}) "
                f"required for short entities"
            ),
        )

    if entity.score < CONFIDENCE_ACCEPT_THRESHOLD:
        return ValidatedEntity(
            text=entity.text, label=entity.label, score=entity.score,
            start=entity.start, end=entity.end,
            status="rejected",
            rejection_reason=f"Confidence {entity.score:.3f} below acceptance threshold {CONFIDENCE_ACCEPT_THRESHOLD}",
        )

    return ValidatedEntity(
        text=entity.text, label=entity.label, score=entity.score,
        start=entity.start, end=entity.end,
        status="accepted",
    )

def build_validated_entities(ner_result: NerResult) -> ValidationResult:
    validated = [_validate_entity(e) for e in ner_result.entities]

    accepted_scores = [e.score for e in validated if e.status == "accepted"]
    mean_confidence = sum(accepted_scores) / len(accepted_scores) if accepted_scores else None

    # all_passed reflects whether every entity that was FOUND is
    # trustworthy, not whether extraction succeeded -- an empty result
    # (no entities found) trivially "passes" since there's nothing to
    # reject; that's a distinct, valid outcome from "found entities and
    # some were rejected."
    all_passed = all(e.status == "accepted" for e in validated)

    return ValidationResult(entities=validated, all_passed=all_passed, mean_confidence=mean_confidence)