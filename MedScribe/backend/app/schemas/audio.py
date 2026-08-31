import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.enums import AudioProcessingStatus, InputSource


class AudioRecordingSummary(BaseModel):
    id: uuid.UUID
    appointment_id: uuid.UUID
    uploaded_by_id: uuid.UUID
    input_source: InputSource
    original_filename: str | None
    mime_type: str | None
    file_size_bytes: int | None
    duration_seconds: float | None
    processing_status: AudioProcessingStatus
    quality_metrics: dict | None
    validation_failure_reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}