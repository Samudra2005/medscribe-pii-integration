"""
Minimal appointments API -- added as a Phase 7 prerequisite, since
audio_recordings.appointment_id is a required foreign key and no
endpoint existed yet to create one. Deliberately narrow scope: create,
list, get. Status transitions (intake complete, doctor pickup,
prescription complete) are NOT here -- those belong to the phases that
actually implement those workflows (intake/Phase 7+, doctor review/
Phase 13-14), where the real transition rules will be defined together
rather than guessed at now.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as DBSession

from app.api.deps import get_current_user, require_nurse_or_doctor
from app.core.logging_config import get_logger
from app.db.session import get_db
from app.models.appointment import Appointment
from app.models.enums import AuditAction
from app.models.patient import Patient
from app.schemas.appointment import AppointmentSummary, CreateAppointmentRequest
from app.schemas.auth import CurrentUser
from app.services.audit_service import write_audit_log

logger = get_logger(__name__)

router = APIRouter(prefix="/appointments", tags=["appointments"])


@router.post("", response_model=AppointmentSummary, status_code=status.HTTP_201_CREATED)
async def create_appointment(
    payload: CreateAppointmentRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_nurse_or_doctor),
    db: DBSession = Depends(get_db),
) -> AppointmentSummary:
    # Confirm the patient actually exists (and isn't soft-deleted) before
    # creating an appointment that points at it -- same defensive pattern
    # as the FK relationship itself, just surfaced as a clean 404 instead
    # of a raw DB constraint error.
    result = await db.execute(
        select(Patient).where(Patient.id == payload.patient_id, Patient.deleted_at.is_(None))
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")

    appointment = Appointment(
        patient_id=payload.patient_id,
        nurse_id=current_user.user_id,
        chief_complaint=payload.chief_complaint,
        scheduled_at=payload.scheduled_at,
    )
    db.add(appointment)
    await db.commit()
    await db.refresh(appointment)

    await write_audit_log(
        db,
        action=AuditAction.CREATE,
        actor_user_id=current_user.user_id,
        actor_role=current_user.role.value,
        target_entity_type="appointment",
        target_entity_id=appointment.id,
        ip_address=request.client.host if request.client else None,
        metadata={"patient_id": str(payload.patient_id)},
    )

    return AppointmentSummary.model_validate(appointment)


@router.get("", response_model=list[AppointmentSummary])
async def list_appointments(
    patient_id: uuid.UUID | None = None,
    current_user: CurrentUser = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[AppointmentSummary]:
    query = select(Appointment).where(Appointment.deleted_at.is_(None))
    if patient_id:
        query = query.where(Appointment.patient_id == patient_id)
    query = query.order_by(Appointment.created_at.desc())

    result = await db.execute(query)
    appointments = result.scalars().all()
    return [AppointmentSummary.model_validate(a) for a in appointments]


@router.get("/{appointment_id}", response_model=AppointmentSummary)
async def get_appointment(
    appointment_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> AppointmentSummary:
    result = await db.execute(
        select(Appointment).where(
            Appointment.id == appointment_id, Appointment.deleted_at.is_(None)
        )
    )
    appointment = result.scalar_one_or_none()
    if appointment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")
    return AppointmentSummary.model_validate(appointment)