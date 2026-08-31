"""
Doctor prescription structured schema -- clinical reasoning and
treatment plan content: problem/diagnosis, symptoms, medications,
advice, follow-ups, existing conditions. This is what MedGemma's
real generated output (Chief Complaint / Symptoms / Relevant History /
Suggested Management) actually maps to -- confirmed via explicit user
correction after the nurse/doctor schema split was initially built
backwards.
"""
from pydantic import BaseModel, Field
from datetime import datetime
from uuid import UUID


class MedicationOrder(BaseModel):
    name: str
    dosage: str | None = None
    frequency: str | None = None
    duration: str | None = None
    instructions: str | None = None


class PrescriptionData(BaseModel):
    problem_summary: str = Field(..., description="The doctor's assessment of the primary problem/chief complaint")
    symptoms: list[str] = Field(default_factory=list)
    existing_conditions: list[str] = Field(default_factory=list, description="Pre-existing conditions relevant to this visit, e.g. asthma")
    medications: list[MedicationOrder] = Field(default_factory=list)
    advice: list[str] = Field(default_factory=list, description="Non-medication guidance -- hydration, rest, dietary, etc.")
    follow_up: list[str] = Field(default_factory=list, description="Follow-up instructions -- when to return, what would warrant urgent reassessment")

    # Same provenance pattern as IntakeFormData -- always present when
    # AI-assisted, never silently presented as doctor-authored when it
    # was a draft. is_final on the parent Prescription model (not this
    # nested schema) is the actual gate for "the doctor reviewed and
    # approved this" -- this ai_generated flag persists even after
    # finalization, as a permanent record of provenance.
    ai_generated: bool = False
    ai_model_name: str | None = None
    ai_model_version: str | None = None
    ai_raw_draft_text: str | None = None


class CreatePrescriptionRequest(BaseModel):
    appointment_id: str
    form_data: PrescriptionData

class UpdatePrescriptionRequest(BaseModel):
    form_data: PrescriptionData

class PrescriptionSummary(BaseModel):
    id: UUID
    appointment_id: UUID
    doctor_id: UUID
    source_entity_set_id: UUID | None
    input_source: str
    form_data: dict
    is_final: bool
    created_at: datetime

    model_config = {"from_attributes": True}