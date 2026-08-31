"""
Convenience wrapper so every orchestrator instruments its stage with
identical, low-boilerplate code -- one context manager handles timing,
in-progress gauge tracking, and success/failure labeling consistently,
rather than each orchestrator hand-rolling its own try/except/timing
logic (which would risk inconsistent labeling across stages).
"""
import time
from contextlib import contextmanager

from app.core.metrics import PIPELINE_STAGE_DURATION_SECONDS, PIPELINE_STAGE_IN_PROGRESS


@contextmanager
def track_pipeline_stage(stage_name: str):
    PIPELINE_STAGE_IN_PROGRESS.labels(stage=stage_name).inc()
    start = time.perf_counter()
    outcome = "success"
    try:
        yield
    except Exception:
        outcome = "failure"
        raise
    finally:
        elapsed = time.perf_counter() - start
        PIPELINE_STAGE_DURATION_SECONDS.labels(stage=stage_name, outcome=outcome).observe(elapsed)
        PIPELINE_STAGE_IN_PROGRESS.labels(stage=stage_name).dec()