import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.enums import UserRole


class ExtractedEntitySetSummary(BaseModel):
    id: uuid.UUID
    appointment_id: uuid.UUID
    transcript_id: uuid.UUID
    target_role: UserRole
    raw_entities: dict
    validated_entities: dict | None
    ner_model_name: str
    ner_model_version: str | None
    validation_passed: bool | None
    confidence_score: float | None
    created_at: datetime

    model_config = {"from_attributes": True}