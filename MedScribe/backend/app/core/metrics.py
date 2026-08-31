"""
Prometheus metrics definitions -- Phase 15. Centralized here so every
service module imports from one place rather than defining metrics
ad hoc, which would risk duplicate-name registration errors (Prometheus
client raises if you define the same metric name twice).

Metric selection is deliberately targeted at THIS project's known real
pain points, not generic boilerplate: pipeline stage duration exists
because every slow-stage number so far (26min diarization pre-fix,
83.6s MedGemma generation, etc.) has only ever been an anecdotal number
from one manual test -- this gives real, continuous, queryable data.
GPU/VRAM metrics exist because Phase 13 found MedGemma alone nearly
saturating the 8GB card -- this makes that condition observable over
time instead of discovered by chance during a manual nvidia-smi check.
"""
from prometheus_client import Counter, Gauge, Histogram

# ---- Pipeline stage timing ----
# One histogram, labeled by stage name, rather than a separate histogram
# per stage -- lets a single Prometheus query compare all stages at once
# (e.g. "p95 duration by stage") without needing to know every stage
# name in advance.
PIPELINE_STAGE_DURATION_SECONDS = Histogram(
    "medstt_pipeline_stage_duration_seconds",
    "Duration of a pipeline stage (normalize, chunk, transcribe, ner, draft_prescription)",
    labelnames=["stage", "outcome"],  # outcome: success | failure
    buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1800),  # seconds -- wide range given MedGemma alone can take 80s+
)

PIPELINE_STAGE_IN_PROGRESS = Gauge(
    "medstt_pipeline_stage_in_progress",
    "Number of pipeline stage executions currently running",
    labelnames=["stage"],
)

# ---- GPU / VRAM ----
GPU_VRAM_USED_BYTES = Gauge(
    "medstt_gpu_vram_used_bytes",
    "GPU VRAM currently used, as reported by torch.cuda",
)
GPU_VRAM_RESERVED_BYTES = Gauge(
    "medstt_gpu_vram_reserved_bytes",
    "GPU VRAM currently reserved by the torch allocator",
)
GPU_MODEL_SLOT_LOADED = Gauge(
    "medstt_gpu_model_slot_loaded",
    "Which GPU model slot is currently resident (1=loaded, labeled by slot)",
    labelnames=["slot"],
)

# ---- Domain-specific counters ----
# These track outcomes this project has specifically cared about at
# every phase -- HITL flagging rate, consensus mismatches, validation
# rejections -- turning things that were previously only visible by
# manually reading JSON API responses into continuously queryable
# counters.
HITL_ITEMS_CREATED = Counter(
    "medstt_hitl_items_created_total",
    "Total HITL queue items created, labeled by reason",
    labelnames=["reason"],
)
TRANSCRIPT_QUALITY_OUTCOME = Counter(
    "medstt_transcript_quality_outcome_total",
    "Transcript quality engine outcomes",
    labelnames=["accepted"],  # "true" | "false"
)
CONSENSUS_OUTCOME = Counter(
    "medstt_consensus_outcome_total",
    "MedASR/Azure consensus comparison outcomes",
    labelnames=["outcome"],
)
NER_ENTITY_VALIDATION_OUTCOME = Counter(
    "medstt_ner_entity_validation_outcome_total",
    "NER entity validation outcomes, labeled by status and label",
    labelnames=["status", "label"],  # status: accepted|rejected, label: CHEM|DISEASE
)