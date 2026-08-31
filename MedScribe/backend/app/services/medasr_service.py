"""
MedASR transcription service. Loads through the shared ModelOrchestrator
(model_orchestrator.py) so it never coexists in VRAM with MedGemma
(Phase 13). Uses the AutoProcessor + AutoModelForCTC pattern from
MedASR's own model card, not the high-level pipeline() wrapper -- direct
control over device placement and decoding is worth the extra few lines,
and keeps this consistent with how we'll likely need to call MedGemma
later (direct model calls, not pipeline() abstraction).
"""
from dataclasses import dataclass
from pathlib import Path

import librosa
import torch
from transformers import AutoModelForCTC, AutoProcessor

from app.core.logging_config import get_logger
from app.services.model_orchestrator import GPUModelSlot, orchestrator

logger = get_logger(__name__)

MODEL_ID = "google/medasr"


def _load_medasr_sync() -> tuple[AutoModelForCTC, AutoProcessor]:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info("medasr_loading", device=device)
    processor = AutoProcessor.from_pretrained(MODEL_ID)
    model = AutoModelForCTC.from_pretrained(MODEL_ID).to(device)
    model.eval()  # inference mode -- disables dropout etc.
    logger.info("medasr_loaded", device=device)
    return model, processor


@dataclass
class TranscriptionResult:
    text: str
    device_used: str
    confidence_score: float | None  # mean per-token probability of the chosen token
    min_token_confidence: float | None  # weakest single token -- useful for flagging
    token_count: int


def _transcribe_sync(
    model: AutoModelForCTC, processor: AutoProcessor, audio_path: Path
) -> TranscriptionResult:
    device = next(model.parameters()).device
    speech, sample_rate = librosa.load(str(audio_path), sr=16000)

    inputs = processor(speech, sampling_rate=sample_rate, return_tensors="pt", padding=True)
    inputs = inputs.to(device)

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            output_scores=True,
            return_dict_in_generate=True,
        )

    decoded_text = processor.batch_decode(outputs.sequences, skip_special_tokens=True)[0].strip()

    confidence_score = None
    min_token_confidence = None
    token_count = 0

    # outputs.logits: [1, seq_len, vocab_size], aligned 1:1 with
    # outputs.sequences: [1, seq_len] -- confirmed by direct inspection
    # (Step 10.2), not assumed. Real per-token confidence: softmax each
    # position's logits, take the probability the model assigned to the
    # token it actually chose there.
    if outputs.logits is not None:
        token_ids = outputs.sequences[0]
        logits = outputs.logits[0]  # [seq_len, vocab_size]
        probs = torch.softmax(logits, dim=-1)  # [seq_len, vocab_size]

        # Exclude special/padding tokens from the confidence calculation --
        # their "confidence" isn't a meaningful signal about transcription
        # quality, it would just dilute the real per-word confidence.
        special_ids = set(processor.tokenizer.all_special_ids) if hasattr(processor, "tokenizer") else set()

        token_confidences = []
        for position in range(len(token_ids)):
            token_id = token_ids[position].item()
            if token_id in special_ids:
                continue
            token_prob = probs[position, token_id].item()
            token_confidences.append(token_prob)

        if token_confidences:
            confidence_score = sum(token_confidences) / len(token_confidences)
            min_token_confidence = min(token_confidences)
            token_count = len(token_confidences)

    return TranscriptionResult(
        text=decoded_text,
        device_used=str(device),
        confidence_score=confidence_score,
        min_token_confidence=min_token_confidence,
        token_count=token_count,
    )

async def transcribe_chunk(audio_path: Path) -> TranscriptionResult:
    """
    audio_path should be a 16kHz mono WAV -- i.e. one of Phase 8's
    extracted chunk files. Acquires MedASR from the shared orchestrator
    (unloading MedGemma first if it happened to be resident -- not
    possible yet in Phase 9 since MedGemma doesn't exist, but this is
    the exact mechanism that will matter starting Phase 13).
    """
    import asyncio

    model, processor = await orchestrator.get_model(GPUModelSlot.MEDASR, _load_medasr_sync)
    result = await asyncio.to_thread(_transcribe_sync, model, processor, audio_path)

    logger.info(
        "medasr_transcription_complete",
        audio_path=str(audio_path),
        device=result.device_used,
        confidence=round(result.confidence_score, 4) if result.confidence_score is not None else None,
        min_token_confidence=round(result.min_token_confidence, 4) if result.min_token_confidence is not None else None,
    )

    return result