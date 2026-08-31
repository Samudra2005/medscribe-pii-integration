"""
Global JSON request body size limit (Phase 16 hardening). Phase 7
already caps audio file uploads at MAX_UPLOAD_SIZE_BYTES, but that only
applies to the multipart audio endpoints -- every other JSON endpoint
(login, patient creation, prescription edits, etc.) had NO body size
limit at all, meaning an arbitrarily large payload could be sent before
Pydantic validation even runs, consuming memory/bandwidth for free.
This is a coarse, cheap first line of defense applied globally, not a
replacement for per-field validation (which Pydantic already handles).
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# 1MB is generous for any real JSON payload this API sends/receives --
# even the largest realistic body (e.g. a full PrescriptionData edit
# with many medications/advice items) is a few KB of text. Audio
# uploads are explicitly EXCLUDED below since they're multipart, not
# JSON, and already have their own, much larger, dedicated limit.
MAX_JSON_BODY_BYTES = 1 * 1024 * 1024


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Audio upload/record endpoints use multipart/form-data with
        # their own dedicated, much larger limit (Phase 7's
        # MAX_UPLOAD_SIZE_BYTES) -- explicitly excluded here rather than
        # this middleware fighting that endpoint's own correct handling.
        if request.url.path in ("/audio/upload", "/audio/record"):
            return await call_next(request)

        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_JSON_BODY_BYTES:
            return JSONResponse(
                status_code=413,
                content={"detail": f"Request body exceeds maximum allowed size of {MAX_JSON_BODY_BYTES} bytes"},
            )

        return await call_next(request)