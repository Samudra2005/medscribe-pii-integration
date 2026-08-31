import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.enums import HitlReason, HitlStatus


class HitlItemSummary(BaseModel):
    id: uuid.UUID
    appointment_id: uuid.UUID
    transcript_id: uuid.UUID | None
    entity_set_id: uuid.UUID | None
    reason: HitlReason
    status: HitlStatus
    user_facing_message: str
    detail: dict | None
    assigned_admin_id: uuid.UUID | None
    resolved_by_id: uuid.UUID | None
    resolution_notes: str | None
    resolved_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ResolveHitlRequest(BaseModel):
    resolution_notes: str
    dismiss: bool = False  # False = mark resolved, True = mark dismissed (false-positive trigger)