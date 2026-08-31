import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.enums import TranscriptSource, TranscriptStatus


class TranscriptSummary(BaseModel):
    id: uuid.UUID
    appointment_id: uuid.UUID
    audio_chunk_id: uuid.UUID | None
    source: TranscriptSource
    status: TranscriptStatus
    text: str
    model_name: str
    model_version: str | None
    confidence_score: float | None
    quality_report: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}