import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import AppointmentStatus


class CreateAppointmentRequest(BaseModel):
    patient_id: uuid.UUID
    chief_complaint: str | None = Field(default=None, max_length=512)
    scheduled_at: datetime | None = None


class AppointmentSummary(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    nurse_id: uuid.UUID
    doctor_id: uuid.UUID | None
    status: AppointmentStatus
    chief_complaint: str | None
    scheduled_at: datetime | None
    intake_completed_at: datetime | None
    prescription_completed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}