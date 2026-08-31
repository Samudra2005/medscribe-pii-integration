"""
master_app.py — a reference "master program" showing exactly how a
real application integrates with the PII masking middleware.

This simulates the pipeline described throughout the project:

    speech-to-text app -> [MASK] -> LLM -> [UNMASK] -> final answer

Two pieces are mocked here, clearly marked, since this demo has no
network access to real cloud services:

  - simulate_stt()  stands in for a real speech-to-text engine
  - call_llm()      stands in for a real LLM API call

Everything else — the HTTP calls to the middleware — is real. Run the
middleware first (python3 server.py, or the FastAPI equivalent), then
run this script against it.

Usage:
    python3 master_app.py
    python3 master_app.py --text "Hi, I'm Neha Verma, calling from Wipro."
    python3 master_app.py --url http://192.168.1.50:8000  (middleware on another machine)
"""

import argparse
import sys
import uuid

import requests

MIDDLEWARE_URL = "http://127.0.0.1:8000"
API_KEY = "dev-only-key"  # must match MASKING_API_KEY on the middleware


# ---------------------------------------------------------------------
# MOCK: stands in for a real speech-to-text engine (e.g. Google Speech-
# to-Text, Azure Speech, Whisper). Swap this for a real SDK call later
# — the rest of the pipeline doesn't need to change, since it only
# cares about getting back a dict with a "transcript" field.
# ---------------------------------------------------------------------

def simulate_stt(text: str) -> dict:
    return {
        "transcript": text,
        "confidence": 0.95,
        "language": "en-IN",
        "duration_seconds": round(len(text) / 15, 1),  # fake, just for realism
    }


# ---------------------------------------------------------------------
# MOCK: stands in for a real LLM call. Real integration example (using
# the Anthropic SDK) is shown at the bottom of this file — swap the
# body of this function for that when you have a real API key.
# ---------------------------------------------------------------------

def call_llm(masked_transcript: str) -> str:
    # a deliberately dumb "response" so it's obvious this is a stand-in,
    # while still echoing the tokens back — exactly like a real LLM
    # would if asked to summarize or respond to the message
    return f"Got it, thanks. Summary: {masked_transcript}"


# ---------------------------------------------------------------------
# REAL: the actual middleware client. This is the part every "master
# program" needs, regardless of language — a thin HTTP wrapper.
# ---------------------------------------------------------------------

class MiddlewareClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        # requests.Session() keeps a cookie jar automatically — the
        # session_id cookie the middleware sets on /mask gets stored
        # here and re-sent on /unmask without any code to track it.
        # A bare requests.post() call would NOT do this on its own.
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json", "X-API-Key": api_key})

    def mask(self, payload: dict, fields: list) -> dict:
        body = {"payload": payload, "fields": fields}
        r = self.session.post(f"{self.base_url}/v1/mask", json=body)
        r.raise_for_status()
        return r.json()

    def unmask(self, payload: dict, fields: list) -> dict:
        # no session_id passed here at all — the cookie jar handles it
        body = {"payload": payload, "fields": fields}
        r = self.session.post(f"{self.base_url}/v1/unmask", json=body)
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------
# The actual pipeline
# ---------------------------------------------------------------------

def run_pipeline(text: str, middleware_url: str):
    client = MiddlewareClient(middleware_url, API_KEY)

    print("=" * 70)
    print("STEP 1 — Speech-to-text output (simulated)")
    print("=" * 70)
    stt_output = simulate_stt(text)
    print(stt_output)

    print("\n" + "=" * 70)
    print("STEP 2 — Master program calls middleware: POST /v1/mask")
    print("=" * 70)
    mask_result = client.mask(payload=stt_output, fields=["transcript"])
    print(mask_result)
    masked_transcript = mask_result["payload"]["transcript"]

    print("\n" + "=" * 70)
    print("STEP 3 — Master program calls the LLM (mocked) with MASKED text only")
    print("=" * 70)
    llm_reply = call_llm(masked_transcript)
    print(f"LLM sees only: {masked_transcript}")
    print(f"LLM replies:   {llm_reply}")

    print("\n" + "=" * 70)
    print("STEP 4 — Master program calls middleware: POST /v1/unmask")
    print("(note: no session_id passed here — the cookie jar carries it)")
    print("=" * 70)
    unmask_result = client.unmask(payload={"response": llm_reply}, fields=["response"])
    print(unmask_result)

    print("\n" + "=" * 70)
    print("FINAL ANSWER shown to the user (real PII restored)")
    print("=" * 70)
    print(unmask_result["payload"]["response"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Demo master program using the PII masking middleware")
    parser.add_argument(
        "--text",
        default="Hi, I am Neha Verma, female, 41, calling from Wipro Limited, phone 91234-56789.",
        help="Text to simulate as speech-to-text output",
    )
    parser.add_argument("--url", default=MIDDLEWARE_URL, help="Middleware base URL")
    args = parser.parse_args()

    try:
        run_pipeline(args.text, args.url)
    except requests.exceptions.ConnectionError:
        print(f"\nCouldn't reach the middleware at {args.url}")
        print("Make sure it's running first: python3 server.py (or uvicorn api:app ...)")
        sys.exit(1)


# ---------------------------------------------------------------------
# REAL LLM integration example — replace call_llm()'s body with this
# once you have a real Anthropic API key:
#
#   import anthropic
#   client = anthropic.Anthropic(api_key="your-key-here")
#
#   def call_llm(masked_transcript: str) -> str:
#       response = client.messages.create(
#           model="claude-sonnet-4-6",
#           max_tokens=500,
#           messages=[{"role": "user", "content": masked_transcript}],
#       )
#       return response.content[0].text
#
# Notice the middleware doesn't change at all — it never sees this
# code, never needs your API key, and doesn't care which LLM you use.
# ---------------------------------------------------------------------
