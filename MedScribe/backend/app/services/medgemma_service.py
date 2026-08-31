"""
MedGemma 1.5 4B-it clinical text drafting service. Loaded through the
shared model_orchestrator so it never coexists in VRAM with MedASR --
genuinely load-bearing here, not just tidy architecture: MedGemma alone
(bf16, ~6.3GB actual measured usage) already partially CPU-offloads on
an 8GB card even by itself, per real testing. There is no VRAM margin
for both models resident simultaneously.

REAL, MEASURED PERFORMANCE (not assumed): ~2.9 tokens/second due to
partial CPU offload from the tight VRAM fit. A ~140-token structured
clinical note took ~49 seconds. Accepted as a known, tracked limitation
(see PROJECT_STATUS.md) rather than solved in this phase -- the
project's existing lack of a background task queue (open since Phase 8)
makes this "more of the same" category of problem, not a new one.

REAL QUALITY VALIDATION PERFORMED: tested against actual project
transcript excerpts + Phase 12's validated entities (diarrhea, tummy
pain, vomiting, gastroenteritis, asthma, Dirid). Output stayed strictly
grounded in provided facts -- no invented symptom durations, dosages,
or additional diagnoses. Model card's own explicit limitation
acknowledged and respected in the prompt design: MedGemma "has not been
evaluated or optimized for multi-turn applications," so this service
deliberately uses ONE single-turn prompt per call, not a conversational
back-and-forth.
"""
import asyncio
from dataclasses import dataclass

import torch
from transformers import AutoModelForImageTextToText, AutoProcessor

from app.core.logging_config import get_logger
from app.services.model_orchestrator import GPUModelSlot, orchestrator

logger = get_logger(__name__)

MODEL_ID = "google/medgemma-1.5-4b-it"
MODEL_VERSION = "1.5.0"  # per the model card's own "Model version" field

# Chosen conservatively given the real measured ~2.9 tok/s -- 400 tokens
# is already ~140s of generation time. Not raising this until the
# background task queue problem (open since Phase 8) is actually solved;
# raising it now would make every single request unpredictably slow.
MAX_NEW_TOKENS = 400


def _load_medgemma_sync() -> tuple[AutoModelForImageTextToText, AutoProcessor]:
    logger.info("medgemma_loading")
    model = AutoModelForImageTextToText.from_pretrained(
        MODEL_ID,
        dtype=torch.bfloat16,
        device_map="auto",
    )
    processor = AutoProcessor.from_pretrained(MODEL_ID)
    logger.info("medgemma_loaded")
    return model, processor


@dataclass
class DraftResult:
    text: str
    input_tokens: int
    output_tokens: int
    generation_seconds: float


def _generate_sync(
    model: AutoModelForImageTextToText, processor: AutoProcessor, prompt_text: str
) -> DraftResult:
    import time

    messages = [{"role": "user", "content": [{"type": "text", "text": prompt_text}]}]

    inputs = processor.apply_chat_template(
        messages, add_generation_prompt=True, tokenize=True,
        return_dict=True, return_tensors="pt",
    ).to(model.device, dtype=torch.bfloat16)

    input_len = inputs["input_ids"].shape[-1]

    start = time.perf_counter()
    with torch.inference_mode():
        # do_sample=False (greedy decoding) -- deliberate, not a default
        # left unconsidered: for a clinical drafting task, deterministic,
        # repeatable output is preferable to sampling-based creativity.
        # This also matches the model card's own Jan 23, 2026 release
        # note, which changed the DEFAULT generation config to greedy
        # decoding specifically.
        generation = model.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS, do_sample=False)
        generation = generation[0][input_len:]
    elapsed = time.perf_counter() - start

    decoded = processor.decode(generation, skip_special_tokens=True)

    return DraftResult(
        text=decoded.strip(),
        input_tokens=input_len,
        output_tokens=len(generation),
        generation_seconds=elapsed,
    )


async def generate_draft(prompt_text: str) -> DraftResult:
    """
    Single-turn only, per the model card's explicit multi-turn
    limitation. Acquires MedGemma from the shared orchestrator --
    unloads MedASR first if it happens to be resident, per the
    orchestrator's mutual-exclusion guarantee.
    """
    model, processor = await orchestrator.get_model(GPUModelSlot.MEDGEMMA, _load_medgemma_sync)
    result = await asyncio.to_thread(_generate_sync, model, processor, prompt_text)

    logger.info(
        "medgemma_draft_complete",
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        generation_seconds=round(result.generation_seconds, 1),
        tokens_per_second=round(result.output_tokens / result.generation_seconds, 2) if result.generation_seconds > 0 else None,
    )
    return result