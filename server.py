"""
server.py — the SAME /v1/mask and /v1/unmask contract as api.py, but
built on Python's built-in http.server instead of FastAPI. Zero
third-party dependencies at all (not even a web framework) — use this
version if "from scratch" needs to mean that strictly. api.py (FastAPI)
is the nicer developer experience if a standard web framework is fine.

Accepts a raw JSON payload (e.g. straight from a speech-to-text app)
rather than a single flat string, plus a list of which top-level
fields actually contain freeform text that needs masking. Every other
field in the payload (confidence scores, timestamps, language codes,
etc.) passes through completely untouched.

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
"""

import json
import os
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from mask_pii import Vault

API_KEY = os.environ.get("MASKING_API_KEY", "dev-only-key")
SESSION_TTL_SECONDS = 30 * 60

_sessions = {}  # session_id -> (Vault, last_used_timestamp)


def _mask_payload(vault, payload, fields):
    result = dict(payload)  # shallow copy — untouched fields stay exactly as they were
    for field in fields:
        if field in result and isinstance(result[field], str):
            result[field] = vault.mask(result[field])
    return result


def _unmask_payload(vault, payload, fields):
    result = dict(payload)
    for field in fields:
        if field in result and isinstance(result[field], str):
            result[field] = vault.unmask(result[field])
    return result


def _get_vault(session_id):
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


class Handler(BaseHTTPRequestHandler):
    def _cors_headers(self):
        # Allows a browser-based frontend (e.g. the demo UI) to call
        # this API directly. Wide open (*) is fine for local/internal
        # demo use — tighten this to a specific origin before any real
        # deployment. Note: wildcard origin is deliberately kept here
        # rather than switching to credentialed CORS — browsers refuse
        # to combine "allow any origin" with "allow cookies", so a
        # page like demo.html (loaded from file://, effectively a
        # unique/null origin) keeps using the JSON session_id field
        # instead of cookies. Cookies are for server-to-server clients
        # (see master_app.py), not the browser demo.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key")

    def _get_cookies(self) -> dict:
        raw = self.headers.get("Cookie", "")
        cookies = {}
        for part in raw.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                cookies[k] = v
        return cookies

    def _send_json(self, status, payload, set_session_cookie=None):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors_headers()
        if set_session_cookie:
            self.send_header(
                "Set-Cookie",
                f"session_id={set_session_cookie}; HttpOnly; SameSite=Lax; "
                f"Max-Age={SESSION_TTL_SECONDS}; Path=/",
            )
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        # browsers send this "preflight" request before the real POST,
        # to ask permission — this just has to say yes
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")

        if self.headers.get("X-API-Key") != API_KEY:
            return self._send_json(401, {"detail": "invalid or missing API key"})

        cookies = self._get_cookies()
        # explicit session_id in the request body always wins, so a
        # caller can deliberately override — otherwise fall back to
        # whatever the client's cookie jar sent back automatically
        incoming_session = body.get("session_id") or cookies.get("session_id")

        if self.path == "/v1/mask":
            session_id, vault = _get_vault(incoming_session)
            masked_payload = _mask_payload(vault, body["payload"], body["fields"])
            # Demo-friendly observability without writing any patient content
            # or reversible token/session value to the console.
            print(f"PII middleware: masked {len(body['fields'])} field(s)", flush=True)
            return self._send_json(
                200,
                {"payload": masked_payload, "session_id": session_id},
                set_session_cookie=session_id,
            )

        if self.path == "/v1/unmask":
            if not incoming_session or incoming_session not in _sessions:
                return self._send_json(404, {"detail": "unknown or expired session_id"})
            vault, _ = _sessions[incoming_session]
            unmasked_payload = _unmask_payload(vault, body["payload"], body["fields"])
            print(f"PII middleware: restored {len(body['fields'])} field(s)", flush=True)
            return self._send_json(
                200, {"payload": unmasked_payload}, set_session_cookie=incoming_session
            )

        return self._send_json(404, {"detail": "not found"})

    def log_message(self, format, *args):
        pass  # keep the console output clean during the demo


if __name__ == "__main__":
    # Keep 8000 as the standalone default. When running alongside the
    # MedScribe backend (which uses 8000), set MASKING_PORT=8001.
    port = int(os.environ.get("MASKING_PORT", "8000"))
    print(f"listening on 0.0.0.0:{port} (reachable from other machines on this network)")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
