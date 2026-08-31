"""
Cross-request tracing (Phase 15). Phase 3's request_id middleware
already correlates log lines WITHIN one HTTP request -- this adds a
SEPARATE, longer-lived correlation id scoped to an appointment's entire
journey across the five independent pipeline-stage requests (upload,
chunk, transcribe, extract-entities, draft-prescription), which
request_id alone can't do since each of those is its own HTTP request
with its own fresh request_id.

Usage: call bind_appointment_trace(appointment_id) near the start of
each orchestrator's pipeline function. Every subsequent structlog call
within that same async context automatically includes appointment_id,
letting a log search for one appointment_id show its full multi-stage
history across however many separate requests it took, even hours or
days apart.
"""
import structlog


def bind_appointment_trace(appointment_id) -> None:
    structlog.contextvars.bind_contextvars(appointment_id=str(appointment_id))