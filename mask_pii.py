"""
mask_pii.py — reversible PII masking layer.

Detection lives entirely in detectors.py (custom regex + dictionary
rules, no third-party anonymization framework, no cloud calls). This
file only handles turning detected spans into reversible tokens.

Flow:
    user_text --> mask()   --> masked_text   (send THIS to the LLM)
    llm_reply --> unmask() --> real_reply    (show THIS to the user)
"""

import uuid
from detectors import detect


class Vault:
    """
    Holds the token -> real value map for ONE user session.
    Keep this in memory only — never write it to logs or a database.
    """

    def __init__(self):
        self.store = {}      # token -> real value
        self._reverse = {}   # real value -> token (keeps repeats consistent)

    def mask(self, text: str) -> str:
        spans = detect(text)
        # replace right-to-left so earlier character offsets stay
        # valid as we edit the string
        for span in sorted(spans, key=lambda s: s.start, reverse=True):
            token = self._reverse.get(span.value)
            if token is None:
                token = f"[REDACTED_{uuid.uuid4().hex[:6]}]"
                self.store[token] = span.value
                self._reverse[span.value] = token
            text = text[: span.start] + token + text[span.end :]
        return text

    def unmask(self, text: str) -> str:
        for token, real_value in self.store.items():
            text = text.replace(token, real_value)
        return text


if __name__ == "__main__":
    vault = Vault()

    user_input = "Hi, I'm Rahul Sharma, male, 34 years old, phone 98765-43210."
    masked = vault.mask(user_input)
    print("-> sent to LLM:  ", masked)

    # stand-in for the real LLM call
    fake_llm_reply = masked.replace("Hi, I'm", "Nice to meet you,")

    print("-> shown to user:", vault.unmask(fake_llm_reply))
