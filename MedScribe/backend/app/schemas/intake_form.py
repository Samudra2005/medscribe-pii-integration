"""
Nurse intake form structured schema -- objective, quantitative, and
procedural data the nurse collects BEFORE the doctor's clinical
assessment: vitals, prior test orders/results. This is deliberately
NOT symptoms/diagnosis/treatment content -- that belongs to the doctor's
Prescription schema (see schemas/prescription.py), per explicit user
correction: "nurse intake form is like bloodpressure, height weight,
etc details of the patient. if tests earlier prescribed did they do
what are results." vs "doctor's prescription is problem symptoms
medications advise followups existing conditions."
"""
from pydantic import BaseModel, Field


class PriorTestResult(BaseModel):
    test_name: str
    was_completed: bool = Field(..., description="Whether the previously ordered/recommended test was actually done")
    result_summary: str | None = Field(default=None, description="Result details, if the test was completed and results are available")


class VitalSigns(BaseModel):
    blood_pressure_systolic: int | None = None
    blood_pressure_diastolic: int | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    temperature_celsius: float | None = None
    pulse_bpm: int | None = None


class IntakeFormData(BaseModel):
    vitals: VitalSigns = Field(default_factory=VitalSigns)
    prior_test_results: list[PriorTestResult] = Field(default_factory=list)

    # Optional, per explicit user decision -- useful context but not
    # part of the core required vitals/tests shape.
    reason_for_visit: str | None = Field(default=None, description="Patient-stated reason for visit, in their own words")
    known_allergies: str | None = None

    # Provenance -- present whenever any part of this form was
    # AI-assisted (e.g. vitals mentioned verbally in the transcript and
    # extracted), so a reviewing nurse can see what was AI-derived vs
    # manually entered. Most intake forms will likely be manual entry
    # (nurse directly measures/records vitals) rather than ASR-derived,
    # per the InputSource enum's own MANUAL_ENTRY option -- this schema
    # supports both, doesn't assume AI involvement.
    ai_generated: bool = False
    ai_model_name: str | None = None
    ai_model_version: str | None = None
    ai_raw_draft_text: str | None = None


class CreateIntakeFormRequest(BaseModel):
    appointment_id: str
    form_data: IntakeFormData


class IntakeFormSummary(BaseModel):
    id: str
    appointment_id: str
    nurse_id: str
    source_entity_set_id: str | None
    input_source: str
    form_data: dict
    is_final: bool
    submitted_at: str | None
    created_at: str

    model_config = {"from_attributes": True}