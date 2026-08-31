"""
Azure AI Speech transcription -- runs on EVERY chunk alongside MedASR,
per explicit user decision (not a fallback-only trigger). This is a
deliberate cost/robustness trade-off: every chunk gets two independent
transcriptions, always, regardless of MedASR's quality or speed.

Uses Azure's synchronous "recognize once" API (appropriate for short,
already-segmented chunk files, not the long-running continuous
recognition API meant for streaming/live audio).
"""
import asyncio
from dataclasses import dataclass
from pathlib import Path

import azure.cognitiveservices.speech as speechsdk

from app.core.config import get_settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)
settings = get_settings()

def is_azure_configured() -> bool:
    """
    Explicit availability check -- lets calling code skip Azure entirely
    (no API call attempted at all, zero cost) when credentials aren't
    set, rather than attempting a call that's guaranteed to fail. Also
    gives us a clean way to fully disable Azure later (e.g. cost
    control) without touching the calling code's logic.
    """
    return bool(settings.AZURE_SPEECH_KEY and settings.AZURE_SPEECH_REGION)

@dataclass
class AzureTranscriptionResult:
    text: str
    confidence: float | None
    success: bool
    error_message: str | None = None


def _transcribe_sync(audio_path: Path) -> AzureTranscriptionResult:
    try:
        speech_config = speechsdk.SpeechConfig(
            subscription=settings.AZURE_SPEECH_KEY,
            region=settings.AZURE_SPEECH_REGION,
        )
        speech_config.output_format = speechsdk.OutputFormat.Detailed

        audio_config = speechsdk.audio.AudioConfig(filename=str(audio_path))
        recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)

        result = recognizer.recognize_once()

        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            confidence = None
            try:
                import json

                detailed = json.loads(result.json)
                best = detailed.get("NBest", [{}])[0]
                confidence = best.get("Confidence")
            except (KeyError, IndexError, ValueError) as exc:
                logger.warning("azure_confidence_parse_failed", error=str(exc))

            return AzureTranscriptionResult(text=result.text, confidence=confidence, success=True)

        elif result.reason == speechsdk.ResultReason.NoMatch:
            return AzureTranscriptionResult(
                text="", confidence=None, success=True,
                error_message="No speech could be recognized",
            )
        else:
            cancellation = speechsdk.CancellationDetails(result)
            error_msg = f"{cancellation.reason}: {cancellation.error_details}"
            logger.warning("azure_transcription_cancelled", error=error_msg)
            return AzureTranscriptionResult(text="", confidence=None, success=False, error_message=error_msg)

    except Exception as exc:
        # Deliberately broad catch, by design, not laziness: this covers
        # auth failures (bad/expired key), network errors, quota/billing
        # exhaustion, region misconfiguration, and any SDK-internal error
        # we haven't specifically anticipated. Azure is a PAID, EXTERNAL,
        # SUPPLEMENTARY service in this architecture -- MedASR is the
        # real, always-available local engine. Any Azure failure must
        # degrade to "no cloud result this time," never take down the
        # whole transcription pipeline or block a chunk from being
        # processed. This is the single most important reliability
        # property of this service.
        logger.warning("azure_transcription_error", error=str(exc), error_type=type(exc).__name__)
        return AzureTranscriptionResult(
            text="", confidence=None, success=False, error_message=str(exc)
        )
    # Request detailed output so we get a real confidence score, not
    # just the plain-text best guess -- needed for genuine quality
    # comparison against MedASR's confidence, not just text similarity.
    speech_config.output_format = speechsdk.OutputFormat.Detailed

    audio_config = speechsdk.audio.AudioConfig(filename=str(audio_path))
    recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)

    result = recognizer.recognize_once()

    if result.reason == speechsdk.ResultReason.RecognizedSpeech:
        confidence = None
        try:
            import json

            detailed = json.loads(result.json)
            # NBest[0] is Azure's top hypothesis with its confidence score
            best = detailed.get("NBest", [{}])[0]
            confidence = best.get("Confidence")
        except (KeyError, IndexError, ValueError) as exc:
            logger.warning("azure_confidence_parse_failed", error=str(exc))

        return AzureTranscriptionResult(text=result.text, confidence=confidence, success=True)

    elif result.reason == speechsdk.ResultReason.NoMatch:
        return AzureTranscriptionResult(
            text="", confidence=None, success=True,
            error_message="No speech could be recognized",
        )
    else:
        cancellation = speechsdk.CancellationDetails(result)
        error_msg = f"{cancellation.reason}: {cancellation.error_details}"
        logger.error("azure_transcription_failed", error=error_msg)
        return AzureTranscriptionResult(text="", confidence=None, success=False, error_message=error_msg)


async def transcribe_chunk_azure(audio_path: Path) -> AzureTranscriptionResult:
    """
    audio_path should be a 16kHz mono WAV -- same chunk file MedASR
    transcribes. Azure's SDK is synchronous/blocking (not natively
    async), so this runs in a thread to avoid stalling the event loop --
    same reasoning as every other blocking call in this codebase (ffmpeg,
    ffprobe, MedASR inference).
    """
    result = await asyncio.to_thread(_transcribe_sync, audio_path)
    logger.info(
        "azure_transcription_complete",
        audio_path=str(audio_path),
        success=result.success,
        confidence=result.confidence,
        text_length=len(result.text),
    )
    return result