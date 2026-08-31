import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.enums import AuditAction


class AuditLogEntry(BaseModel):
    id: uuid.UUID
    occurred_at: datetime
    actor_user_id: uuid.UUID | None
    actor_role: str | None
    action: AuditAction
    target_entity_type: str | None
    target_entity_id: uuid.UUID | None
    ip_address: str | None
    metadata_json: dict | None
    success: bool

    model_config = {"from_attributes": True}