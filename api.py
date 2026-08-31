"""
api.py — a small "universal" HTTP wrapper around mask_pii.py

Any application, in any language, can call this middleware over plain
JSON/HTTP. Detection and masking are entirely custom (see detectors.py
and mask_pii.py) — nothing here depends on a third-party anonymization
framework, and nothing calls out to a cloud API.

    POST /v1/mask
      {"payload": {"transcript": "...", "confidence": 0.94},
       "fields": ["transcript"], "session_id": "optional"}
    ->
      {"payload": {"transcript": "[REDACTED_..]...", "confidence": 0.94},
       "session_id": "..."}

    POST /v1/unmask
      {"payload": {"response": "...tokens..."},
       "fields": ["response"], "session_id": "..."}
    ->
      {"payload": {"response": "...real values restored..."}}

Only the named fields are touched — everything else in the payload
(confidence scores, timestamps, language codes, etc.) passes through
completely untouched, since it isn't freeform text and shouldn't be
run through PII detection at all.

The calling app makes its own LLM call in between /mask and /unmask.
This middleware is deliberately decoupled from every LLM provider's
API shape and credentials — it only ever masks and unmasks text.

Run:
    pip install fastapi uvicorn
    export MASKING_API_KEY=some-real-secret
    uvicorn api:app --host 0.0.0.0 --port 8000 --reload

Docs (auto-generated for whoever integrates against this):
    http://localhost:8000/docs
"""

import os
import time
import uuid
from typing import Dict, Optional, Tuple

from fastapi import Cookie, FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from mask_pii import Vault  # our own masking logic — no external dependency

app = FastAPI(title="PII Masking Middleware")

# Allows a browser-based frontend (e.g. the demo UI) to call this API
# directly. Wide open (*) is fine for local/internal demo use —
# tighten this to a specific origin before any real deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)

API_KEY = os.environ.get("MASKING_API_KEY", "dev-only-key")
SESSION_TTL_SECONDS = 30 * 60  # expire idle sessions after 30 min

# session_id -> (Vault, last_used_timestamp)
#
# In-memory and per-process — fine for a single-instance demo. For
# more than that (multiple replicas, restarts), swap this for a
# shared local store (e.g. self-hosted Redis) keyed by session_id
# with the same TTL. Never let this map hit disk or logs unencrypted.
_sessions: Dict[str, Tuple[Vault, float]] = {}


def _mask_payload(vault: Vault, payload: dict, fields: list) -> dict:
    result = dict(payload)  # shallow copy — untouched fields stay exactly as they were
    for field in fields:
        if field in result and isinstance(result[field], str):
            result[field] = vault.mask(result[field])
    return result


def _unmask_payload(vault: Vault, payload: dict, fields: list) -> dict:
    result = dict(payload)
    for field in fields:
        if field in result and isinstance(result[field], str):
            result[field] = vault.unmask(result[field])
    return result


def _check_api_key(x_api_key: Optional[str]) -> None:
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid or missing API key")


def _get_vault(session_id: Optional[str]) -> Tuple[str, Vault]:
    now = time.time()
    for sid, (_, ts) in list(_sessions.items()):
        if now - ts > SESSION_TTL_SECONDS:
            del _sessions[sid]

    if session_id and session_id in _sessions:
        vault, _ = _sessions[session_id]
        _sessions[session_id] = (vault, now)
        return session_id, vault

    new_id = session_id or uuid.uuid4().hex
    vault = Vault()
    _sessions[new_id] = (vault, now)
    return new_id, vault


class MaskRequest(BaseModel):
    payload: Dict
    fields: list
    session_id: Optional[str] = None


class UnmaskRequest(BaseModel):
    payload: Dict
    fields: list
    session_id: Optional[str] = None  # can come from a cookie instead — see below


@app.post("/v1/mask")
def mask(
    req: MaskRequest,
    response: Response,
    x_api_key: Optional[str] = Header(default=None),
    session_cookie: Optional[str] = Cookie(default=None, alias="session_id"),
):
    _check_api_key(x_api_key)
    # explicit session_id in the body always wins (lets a caller
    # deliberately override); otherwise fall back to whatever the
    # client's cookie jar sent back automatically
    incoming_session = req.session_id or session_cookie
    session_id, vault = _get_vault(incoming_session)
    masked_payload = _mask_payload(vault, req.payload, req.fields)
    response.set_cookie(
        key="session_id", value=session_id, httponly=True,
        samesite="lax", max_age=SESSION_TTL_SECONDS,
    )
    return {"payload": masked_payload, "session_id": session_id}


@app.post("/v1/unmask")
def unmask(
    req: UnmaskRequest,
    response: Response,
    x_api_key: Optional[str] = Header(default=None),
    session_cookie: Optional[str] = Cookie(default=None, alias="session_id"),
):
    _check_api_key(x_api_key)
    incoming_session = req.session_id or session_cookie
    if not incoming_session or incoming_session not in _sessions:
        raise HTTPException(status_code=404, detail="unknown or expired session_id")
    vault, _ = _sessions[incoming_session]
    unmasked_payload = _unmask_payload(vault, req.payload, req.fields)
    response.set_cookie(
        key="session_id", value=incoming_session, httponly=True,
        samesite="lax", max_age=SESSION_TTL_SECONDS,
    )
    return {"payload": unmasked_payload}
