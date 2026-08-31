"""
Patient management endpoints. Create/list/get available to admin AND
nurse (nurses register patients as part of intake). Soft-delete
restricted to admin only, per your website layout ("Admin ... delete
records").
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as DBSession

from app.api.deps import get_current_user, require_admin
from app.core.logging_config import get_logger
from app.db.session import get_db
from app.models.enums import AuditAction
from app.models.patient import Patient
from app.schemas.auth import CurrentUser
from app.schemas.patient import CreatePatientRequest, PatientSummary, UpdatePatientRequest
from app.services.audit_service import write_audit_log

logger = get_logger(__name__)

router = APIRouter(prefix="/patients", tags=["patients"])


@router.post("", response_model=PatientSummary, status_code=status.HTTP_201_CREATED)
async def create_patient(
    payload: CreatePatientRequest,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> PatientSummary:
    existing = await db.execute(select(Patient).where(Patient.mrn == payload.mrn))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A patient with MRN '{payload.mrn}' already exists",
        )

    patient = Patient(
        mrn=payload.mrn,
        full_name=payload.full_name,
        date_of_birth=payload.date_of_birth,
        sex=payload.sex,
        phone_number=payload.phone_number,
        address=payload.address,
        known_allergies=payload.known_allergies,
        created_by_id=current_user.user_id,
    )
    db.add(patient)
    await db.commit()
    await db.refresh(patient)

    await write_audit_log(
        db,
        action=AuditAction.CREATE,
        actor_user_id=current_user.user_id,
        actor_role=current_user.role.value,
        target_entity_type="patient",
        target_entity_id=patient.id,
        ip_address=request.client.host if request.client else None,
        metadata={"mrn": patient.mrn},
    )

    return PatientSummary.model_validate(patient)


@router.get("", response_model=list[PatientSummary])
async def list_patients(
    search: str | None = None,
    current_user: CurrentUser = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[PatientSummary]:
    """
    search: optional case-insensitive partial match against name or MRN
    -- the basic lookup a nurse/doctor needs when starting a new
    appointment for an existing patient.
    """
    query = select(Patient).where(Patient.deleted_at.is_(None))
    if search:
        like_pattern = f"%{search}%"
        query = query.where(
            (Patient.full_name.ilike(like_pattern)) | (Patient.mrn.ilike(like_pattern))
        )
    query = query.order_by(Patient.full_name)

    result = await db.execute(query)
    patients = result.scalars().all()
    return [PatientSummary.model_validate(p) for p in patients]


@router.get("/{patient_id}", response_model=PatientSummary)
async def get_patient(
    patient_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> PatientSummary:
    result = await db.execute(
        select(Patient).where(Patient.id == patient_id, Patient.deleted_at.is_(None))
    )
    patient = result.scalar_one_or_none()
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")
    return PatientSummary.model_validate(patient)


@router.patch("/{patient_id}", response_model=PatientSummary)
async def update_patient(
    patient_id: uuid.UUID,
    payload: UpdatePatientRequest,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> PatientSummary:
    result = await db.execute(
        select(Patient).where(Patient.id == patient_id, Patient.deleted_at.is_(None))
    )
    patient = result.scalar_one_or_none()
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")

    changes: dict = {}
    update_data = payload.model_dump(exclude_unset=True)
    for field, new_value in update_data.items():
        old_value = getattr(patient, field)
        if old_value != new_value:
            changes[field] = {"old": old_value, "new": new_value}
            setattr(patient, field, new_value)

    if changes:
        await db.commit()
        await write_audit_log(
            db,
            action=AuditAction.UPDATE,
            actor_user_id=current_user.user_id,
            actor_role=current_user.role.value,
            target_entity_type="patient",
            target_entity_id=patient.id,
            ip_address=request.client.host if request.client else None,
            metadata={"changes": changes},
        )

    return PatientSummary.model_validate(patient)


@router.delete("/{patient_id}", status_code=status.HTTP_204_NO_CONTENT)
async def soft_delete_patient(
    patient_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser = Depends(require_admin),
    db: DBSession = Depends(get_db),
) -> None:
    from datetime import datetime, timezone

    result = await db.execute(
        select(Patient).where(Patient.id == patient_id, Patient.deleted_at.is_(None))
    )
    patient = result.scalar_one_or_none()
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")

    patient.deleted_at = datetime.now(timezone.utc)
    await db.commit()

    await write_audit_log(
        db,
        action=AuditAction.SOFT_DELETE,
        actor_user_id=current_user.user_id,
        actor_role=current_user.role.value,
        target_entity_type="patient",
        target_entity_id=patient.id,
        ip_address=request.client.host if request.client else None,
        metadata={"mrn": patient.mrn},
    )