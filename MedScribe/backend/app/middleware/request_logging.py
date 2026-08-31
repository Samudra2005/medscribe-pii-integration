"""
Assigns a unique request_id to every incoming request and binds it into
structlog's context, so every log line emitted anywhere during that
request's processing -- including deep inside the ASR/NER pipeline in
later phases -- carries the same request_id. This is what makes it
possible to answer "show me everything that happened for this one
request" from the log file, which is exactly the audit-trail-through-logs
requirement you specified.
"""
import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging_config import get_logger

logger = get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = str(uuid.uuid4())
        start_time = time.perf_counter()

        # Bind request_id (and basic request info) into structlog's
        # contextvars -- automatically merged into every log line emitted
        # during this request, anywhere in the call stack, without having
        # to manually pass request_id into every function.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            client_ip=request.client.host if request.client else None,
        )

        logger.info("request_started")

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.exception("request_failed", duration_ms=duration_ms)
            raise

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        logger.info(
            "request_completed",
            status_code=response.status_code,
            duration_ms=duration_ms,
        )

        # Echo request_id back to the client -- useful for support/debugging:
        # if a nurse reports an error, they (or the frontend) can surface
        # this ID, and we can find the exact log entries instantly.
        response.headers["X-Request-ID"] = request_id
        return response