"""Privacy boundary for text sent from MedScribe to MedGemma."""
from dataclasses import dataclass

import requests


class PIIMaskingError(RuntimeError):
    """The PII service is unavailable or violated its response contract."""


@dataclass(frozen=True)
class MaskedText:
    text: str
    session_id: str


class PIIMaskingClient:
    def __init__(self, middleware_url: str, api_key: str, timeout_seconds: float = 5.0):
        self.url = middleware_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json", "X-API-Key": api_key})

    def mask_text(self, text: str) -> MaskedText:
        if not text or not text.strip():
            return MaskedText(text=text, session_id="")
        try:
            response = self.session.post(
                f"{self.url}/v1/mask",
                json={"payload": {"text": text}, "fields": ["text"]},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
            return MaskedText(text=data["payload"]["text"], session_id=data["session_id"])
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            raise PIIMaskingError("PII masking service is unavailable or returned an invalid response") from exc

    def unmask_text(self, text: str, session_id: str) -> str:
        if not session_id:
            return text
        try:
            response = self.session.post(
                f"{self.url}/v1/unmask",
                json={"payload": {"text": text}, "fields": ["text"], "session_id": session_id},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            return response.json()["payload"]["text"]
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            raise PIIMaskingError("PII unmasking service is unavailable or returned an invalid response") from exc
