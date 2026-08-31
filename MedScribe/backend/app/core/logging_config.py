"""
Centralized structured logging setup.

Design goals:
- Every log line is structured (JSON), not free text -- machine-parseable
  for later log analysis / SIEM ingestion, which matters for a government
  system where "show me every action on patient X" needs to be a log
  query, not a manual grep through prose.
- Logs go to BOTH stdout (so `docker compose logs` and container
  orchestration tooling see them) AND a rotating file on disk (so a
  durable local record exists even if the container's stdout capture
  is misconfigured or rotated away by the platform).
- A request_id is bound to every log line within a request's lifecycle
  (wired up via middleware in Step 3.5), so every log line from a single
  HTTP request can be correlated together -- essential for debugging a
  multi-step pipeline (audio -> ASR -> NER -> validation) where one
  request triggers many internal steps.
"""
import logging
import logging.handlers
import sys
from pathlib import Path

import structlog

from app.core.config import get_settings

settings = get_settings()

LOG_DIR = Path(__file__).resolve().parents[3] / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "medstt_backend.log"


def configure_logging() -> None:
    """
    Call once at application startup. Sets up both the stdlib logging
    backend (which structlog wraps) and structlog's own processor chain.
    """
    # ---- stdlib logging: destinations (handlers) ----
    console_handler = logging.StreamHandler(sys.stdout)

    # RotatingFileHandler caps log file size and keeps N backups, so logs
    # can't silently fill the disk on a long-running deployment -- a real
    # production concern, not a theoretical one.
    file_handler = logging.handlers.RotatingFileHandler(
        filename=str(LOG_FILE),
        maxBytes=20 * 1024 * 1024,  # 20 MB per file
        backupCount=10,             # keep up to 10 rotated files (~200MB total)
        encoding="utf-8",
    )

    logging.basicConfig(
        format="%(message)s",  # structlog renders the actual structured content
        level=logging.INFO if settings.ENVIRONMENT != "development" else logging.DEBUG,
        handlers=[console_handler, file_handler],
    )

    # ---- structlog: processor chain ----
    # Processors run in order, each enriching/transforming the event dict
    # before it's finally rendered. Order matters: context must be added
    # BEFORE rendering to JSON.
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,   # pulls in request_id etc. bound via contextvars
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,       # renders exceptions cleanly, not as raw tracebacks
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),         # final output: one JSON object per log line
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str):
    """
    Use this everywhere in application code instead of the stdlib
    logging.getLogger -- e.g. `logger = get_logger(__name__)`.
    """
    return structlog.get_logger(name)