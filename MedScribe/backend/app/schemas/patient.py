"""
Pydantic schemas for patient management. Patients can be created by
admin OR nurse (per your workflow: nurse creates intake sessions, which
implies patient registration too) -- so this router will allow both
roles, unlike admin_users.py which is admin-only.
"""
import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class CreatePatientRequest(BaseModel):
    mrn: str = Field(..., min_length=1, max_length=64)
    full_name: str = Field(..., min_length=1, max_length=255)
    date_of_birth: date
    sex: str = Field(..., min_length=1, max_length=20)
    phone_number: str | None = Field(default=None, max_length=32)
    address: str | None = Field(default=None, max_length=512)
    known_allergies: str | None = Field(default=None, max_length=1024)


class UpdatePatientRequest(BaseModel):
    """All fields optional -- partial update (PATCH semantics)."""
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    phone_number: str | None = Field(default=None, max_length=32)
    address: str | None = Field(default=None, max_length=512)
    known_allergies: str | None = Field(default=None, max_length=1024)


class PatientSummary(BaseModel):
    id: uuid.UUID
    mrn: str
    full_name: str
    date_of_birth: date
    sex: str
    phone_number: str | None
    address: str | None
    known_allergies: str | None
    created_at: datetime
    created_by_id: uuid.UUID

    model_config = {"from_attributes": True}