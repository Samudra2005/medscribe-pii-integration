import uuid

from pydantic import BaseModel


class AudioChunkSummary(BaseModel):
    id: uuid.UUID
    audio_recording_id: uuid.UUID
    chunk_index: int
    start_time_seconds: float
    end_time_seconds: float
    overlap_seconds: float
    speaker_label: str | None
    storage_path: str

    model_config = {"from_attributes": True}