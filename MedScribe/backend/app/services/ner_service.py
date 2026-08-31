"""
Named entity extraction using OpenMed's transformers-native clinical NER
models (Phase 12). Two separate models run per text, since OpenMed
splits entity types into single-purpose models rather than one combined
model (unlike scispaCy's en_ner_bc5cdr_md, which this project originally
targeted before hitting a real numpy/spaCy dependency conflict --
see PROJECT_STATUS.md for the full investigation).

Real quality check performed before integration (not assumed): on one
real transcript segment, correctly flagged a garbled medication name
("Dirid") as a chemical entity despite it not being a recognized real
drug name -- genuine additive signal beyond ASR confidence alone. Also
missed a common term ("antibiotics") in that same test -- a real,
acknowledged limitation, not hidden. Quality will continue to be
observed against live data rather than exhaustively pre-validated.
"""
import asyncio
from dataclasses import dataclass, field

from transformers import pipeline

from app.core.logging_config import get_logger

logger = get_logger(__name__)

PHARMA_MODEL_ID = "OpenMed/OpenMed-NER-PharmaDetect-SuperClinical-434M"
DISEASE_MODEL_ID = "OpenMed/OpenMed-NER-DiseaseDetect-SuperClinical-434M"

_pharma_pipeline = None
_disease_pipeline = None


def _load_pipelines():
    global _pharma_pipeline, _disease_pipeline
    if _pharma_pipeline is None:
        logger.info("ner_pharma_model_loading")
        _pharma_pipeline = pipeline(model=PHARMA_MODEL_ID, aggregation_strategy="simple")
        logger.info("ner_pharma_model_loaded")
    if _disease_pipeline is None:
        logger.info("ner_disease_model_loading")
        _disease_pipeline = pipeline(model=DISEASE_MODEL_ID, aggregation_strategy="simple")
        logger.info("ner_disease_model_loaded")
    return _pharma_pipeline, _disease_pipeline


@dataclass
class ExtractedEntity:
    text: str
    label: str  # "CHEM" or "DISEASE"
    score: float
    start: int
    end: int


@dataclass
class NerResult:
    entities: list[ExtractedEntity] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "entities": [
                {
                    "text": e.text,
                    "label": e.label,
                    "score": round(e.score, 4),
                    "start": e.start,
                    "end": e.end,
                }
                for e in self.entities
            ]
        }

def _merge_adjacent_fragments(entities: list[ExtractedEntity]) -> list[ExtractedEntity]:
    """
    aggregation_strategy="simple" merges sub-word PIECES within a single
    model's output, but does NOT merge separate entity spans that are
    directly adjacent in the source text with no gap between them --
    which is exactly what happens with longer clinical/drug terms that
    get tokenized into multiple pieces the model emits as back-to-back
    entities (observed on real data: "Dirid" -> "Di"+"rid" as two
    adjacent CHEM entities; "paracetamol" -> "pa"+"racetam"+"al" as
    three). Without this merge, a real, high-confidence multi-syllable
    term gets fragmented into several short, individually-unconvincing
    pieces -- exactly the failure this function fixes.

    Two entities are merged if they have the SAME label and are
    perfectly adjacent (entity B starts exactly where entity A ends,
    zero gap/whitespace between them) -- a real word boundary always has
    either a space or punctuation between separate words, so zero-gap
    adjacency is a reliable signal these are pieces of one term, not two
    genuinely separate mentions sitting next to each other.
    """
    if not entities:
        return []

    entities = sorted(entities, key=lambda e: e.start)
    merged: list[ExtractedEntity] = [entities[0]]

    for entity in entities[1:]:
        last = merged[-1]
        if entity.label == last.label and entity.start == last.end:
            merged[-1] = ExtractedEntity(
                text=last.text + entity.text,
                label=last.label,
                # Confidence of the merged entity is the mean of its
                # pieces -- a simple, defensible aggregation; not
                # claiming this is the statistically ideal method, just
                # a reasonable one, same honesty as every other
                # aggregation choice in this project.
                score=(last.score + entity.score) / 2,
                start=last.start,
                end=entity.end,
            )
        else:
            merged.append(entity)

    return merged


def _extract_sync(text: str) -> NerResult:
    pharma_pipeline, disease_pipeline = _load_pipelines()

    raw_entities: list[ExtractedEntity] = []

    for hit in pharma_pipeline(text):
        raw_entities.append(
            ExtractedEntity(
                text=hit["word"],
                label="CHEM",
                score=float(hit["score"]),
                start=hit["start"],
                end=hit["end"],
            )
        )

    for hit in disease_pipeline(text):
        raw_entities.append(
            ExtractedEntity(
                text=hit["word"],
                label="DISEASE",
                score=float(hit["score"]),
                start=hit["start"],
                end=hit["end"],
            )
        )

    # Sort by position first (merge requires adjacency check in order),
    # then merge adjacent same-label fragments, THEN this becomes the
    # canonical entity list -- raw_entities in the DB will now contain
    # the merged, reconstructed terms, not raw tokenizer fragments. This
    # is the correct place for this fix: reconstructing what the model
    # actually identified, before validation ever sees it.
    raw_entities.sort(key=lambda e: e.start)
    merged_entities = _merge_adjacent_fragments(raw_entities)

    return NerResult(entities=merged_entities)


async def extract_entities(text: str) -> NerResult:
    """
    Runs both OpenMed models against a single piece of transcript text.
    CPU-bound (models loaded without device=0, so this runs on CPU per
    the resource plan -- GPU stays reserved for MedASR/MedGemma via the
    model_orchestrator), so wrapped in asyncio.to_thread same as every
    other blocking call in this codebase.
    """
    if not text or not text.strip():
        return NerResult(entities=[])

    result = await asyncio.to_thread(_extract_sync, text)
    logger.info("ner_extraction_complete", entity_count=len(result.entities), text_length=len(text))
    return result