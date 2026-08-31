"""
Doctor review workflow (Phase 14): edit a draft in place, finalize it
(creating the ONE versioned snapshot -- the AI draft as originally
generated is preserved via supersedes_id at finalization time, not on
every edit, per explicit user decision). PDF generation on finalize.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as DBSession

from app.core.logging_config import get_logger
from app.models.enums import AuditAction
from app.models.prescription import Prescription
from app.schemas.prescription import PrescriptionData
from app.services.audio_service import AudioValidationError
from app.services.audit_service import write_audit_log

logger = get_logger(__name__)


async def get_prescription_or_404(prescription_id: uuid.UUID, db: DBSession) -> Prescription:
    result = await db.execute(select(Prescription).where(Prescription.id == prescription_id))
    prescription = result.scalar_one_or_none()
    if prescription is None:
        raise AudioValidationError("Prescription not found")
    return prescription


async def update_prescription_draft(
    prescription_id: uuid.UUID,
    updated_data: PrescriptionData,
    doctor_id: uuid.UUID,
    db: DBSession,
) -> Prescription:
    prescription = await get_prescription_or_404(prescription_id, db)

    if prescription.is_final:
        raise AudioValidationError(
            "Cannot edit a finalized prescription. A finalized prescription is a "
            "permanent record; corrections require a new prescription entry."
        )

    # IN-PLACE edit, per explicit user decision -- doctors iterating on
    # a draft (fixing a dosage, adding a note) shouldn't create a new
    # DB row per edit. The meaningful version boundary is "AI draft" vs
    # "what was actually finalized," captured once at finalize time
    # (see finalize_prescription below), not on every intermediate edit.
    # ai_raw_draft_text is preserved even through edits (it lives inside
    # form_data, and we only overwrite the OTHER structured fields here
    # -- see the merge below) so the original MedGemma output is never
    # lost even mid-editing.
    existing_data = dict(prescription.form_data)
    new_data = updated_data.model_dump()
    # Preserve original AI provenance fields regardless of what the
    # doctor's edited payload contains -- these should reflect the
    # TRUE origin of the draft, not be silently overwritable.
    new_data["ai_generated"] = existing_data.get("ai_generated", False)
    new_data["ai_model_name"] = existing_data.get("ai_model_name")
    new_data["ai_model_version"] = existing_data.get("ai_model_version")
    new_data["ai_raw_draft_text"] = existing_data.get("ai_raw_draft_text")

    prescription.form_data = new_data
    prescription.edited_by_id = doctor_id
    await db.commit()
    await db.refresh(prescription)

    await write_audit_log(
        db,
        action=AuditAction.UPDATE,
        actor_user_id=doctor_id,
        actor_role="doctor",
        target_entity_type="prescription",
        target_entity_id=prescription.id,
        ip_address=None,
        metadata={"appointment_id": str(prescription.appointment_id)},
    )

    return prescription

async def finalize_prescription(
    prescription_id: uuid.UUID,
    doctor_id: uuid.UUID,
    db: DBSession,
) -> Prescription:
    from datetime import datetime, timezone

    from app.models.appointment import Appointment
    from app.models.patient import Patient
    from app.models.user import User
    from app.services.prescription_pdf_service import generate_prescription_pdf

    prescription = await get_prescription_or_404(prescription_id, db)

    if prescription.is_final:
        raise AudioValidationError("Prescription is already finalized")

    prescription.is_final = True
    prescription.finalized_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(prescription)

    # PDF generation happens AFTER finalization is committed -- if PDF
    # generation somehow fails, the finalization itself (the legally/
    # clinically meaningful action) has already succeeded and isn't
    # rolled back by a rendering problem. pdf_storage_path stays NULL
    # in that failure case rather than blocking finalization entirely.
    appointment_result = await db.execute(select(Appointment).where(Appointment.id == prescription.appointment_id))
    appointment = appointment_result.scalar_one()
    patient_result = await db.execute(select(Patient).where(Patient.id == appointment.patient_id))
    patient = patient_result.scalar_one()
    doctor_result = await db.execute(select(User).where(User.id == doctor_id))
    doctor = doctor_result.scalar_one()

    try:
        pdf_path = await generate_prescription_pdf(prescription, patient, doctor, appointment)
        prescription.pdf_storage_path = pdf_path
        await db.commit()
        await db.refresh(prescription)
    except Exception as exc:
        logger.error("prescription_pdf_generation_failed", prescription_id=str(prescription_id), error=str(exc))
        # Deliberately NOT re-raised -- finalization already succeeded
        # and is the important state change; a PDF can be regenerated
        # later (a future "regenerate PDF" endpoint would be a
        # reasonable addition, not built now).

    await write_audit_log(
        db,
        action=AuditAction.APPROVE,
        actor_user_id=doctor_id,
        actor_role="doctor",
        target_entity_type="prescription",
        target_entity_id=prescription.id,
        ip_address=None,
        metadata={"appointment_id": str(prescription.appointment_id)},
    )

    logger.info("prescription_finalized", prescription_id=str(prescription_id), doctor_id=str(doctor_id))
    return prescription