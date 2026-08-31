"""
Nurse intake form service. Manual entry is the PRIMARY path -- a nurse
directly measuring/recording vitals with real equipment (BP cuff,
scale, thermometer) has no reason to route through a transcript at all.
AI-assisted drafting (extracting any vitals mentioned verbally in a
conversation) is a secondary, best-effort path for the narrower case
where vitals genuinely were spoken aloud during the recorded encounter
-- most vitals collection happens via direct measurement, not
conversation, so this is expected to be the LESS common path, not the
primary one, unlike Phase 13's prescription drafting which fits
conversational content naturally.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as DBSession

from app.core.logging_config import get_logger
from app.models.enums import AuditAction, InputSource
from app.models.intake_form import IntakeForm
from app.schemas.intake_form import IntakeFormData
from app.services.audio_service import AudioValidationError
from app.services.audit_service import write_audit_log

logger = get_logger(__name__)


async def create_manual_intake_form(
    appointment_id: uuid.UUID,
    form_data: IntakeFormData,
    nurse_id: uuid.UUID,
    db: DBSession,
) -> IntakeForm:
    form_data.ai_generated = False  # manual entry -- explicit, never inferred
    form_data.ai_model_name = None
    form_data.ai_model_version = None
    form_data.ai_raw_draft_text = None

    intake_form = IntakeForm(
        appointment_id=appointment_id,
        nurse_id=nurse_id,
        source_entity_set_id=None,
        input_source=InputSource.MANUAL_ENTRY,
        form_data=form_data.model_dump(),
        is_final=False,
    )
    db.add(intake_form)
    await db.commit()
    await db.refresh(intake_form)

    await write_audit_log(
        db,
        action=AuditAction.CREATE,
        actor_user_id=nurse_id,
        actor_role="nurse",
        target_entity_type="intake_form",
        target_entity_id=intake_form.id,
        ip_address=None,
        metadata={"appointment_id": str(appointment_id), "input_source": "manual_entry"},
    )
    return intake_form


async def get_intake_form_or_404(intake_form_id: uuid.UUID, db: DBSession) -> IntakeForm:
    result = await db.execute(select(IntakeForm).where(IntakeForm.id == intake_form_id))
    form = result.scalar_one_or_none()
    if form is None:
        raise AudioValidationError("Intake form not found")
    return form


async def update_intake_form(
    intake_form_id: uuid.UUID,
    updated_data: IntakeFormData,
    nurse_id: uuid.UUID,
    db: DBSession,
) -> IntakeForm:
    form = await get_intake_form_or_404(intake_form_id, db)

    if form.is_final:
        raise AudioValidationError(
            "Cannot edit a finalized intake form. A finalized intake form is a "
            "permanent record; corrections require a new intake entry."
        )

    # Same provenance-preservation pattern as Phase 14's prescription
    # editing -- in-place edit, but AI provenance fields (if this form
    # WAS AI-assisted) survive regardless of what the edit payload sends.
    existing = dict(form.form_data)
    new_data = updated_data.model_dump()
    new_data["ai_generated"] = existing.get("ai_generated", False)
    new_data["ai_model_name"] = existing.get("ai_model_name")
    new_data["ai_model_version"] = existing.get("ai_model_version")
    new_data["ai_raw_draft_text"] = existing.get("ai_raw_draft_text")

    form.form_data = new_data
    await db.commit()
    await db.refresh(form)

    await write_audit_log(
        db,
        action=AuditAction.UPDATE,
        actor_user_id=nurse_id,
        actor_role="nurse",
        target_entity_type="intake_form",
        target_entity_id=form.id,
        ip_address=None,
        metadata={"appointment_id": str(form.appointment_id)},
    )
    return form


async def finalize_intake_form(
    intake_form_id: uuid.UUID,
    nurse_id: uuid.UUID,
    db: DBSession,
) -> IntakeForm:
    form = await get_intake_form_or_404(intake_form_id, db)

    if form.is_final:
        raise AudioValidationError("Intake form is already finalized")

    form.is_final = True
    form.submitted_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(form)

    await write_audit_log(
        db,
        action=AuditAction.APPROVE,
        actor_user_id=nurse_id,
        actor_role="nurse",
        target_entity_type="intake_form",
        target_entity_id=form.id,
        ip_address=None,
        metadata={"appointment_id": str(form.appointment_id)},
    )
    return form