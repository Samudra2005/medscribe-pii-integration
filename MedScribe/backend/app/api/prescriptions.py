import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession as DBSession

from app.api.deps import get_current_user, require_doctor
from app.db.session import get_db
from app.schemas.auth import CurrentUser
from app.schemas.prescription import PrescriptionSummary, UpdatePrescriptionRequest
from app.services.audio_service import AudioValidationError
from app.services.prescription_service import (
    finalize_prescription,
    get_prescription_or_404,
    update_prescription_draft,
)

router = APIRouter(prefix="/prescriptions", tags=["prescriptions"])


@router.get("/{prescription_id}", response_model=PrescriptionSummary)
async def get_prescription(
    prescription_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> PrescriptionSummary:
    try:
        prescription = await get_prescription_or_404(prescription_id, db)
    except AudioValidationError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return PrescriptionSummary.model_validate(prescription)


@router.patch("/{prescription_id}", response_model=PrescriptionSummary)
async def edit_prescription(
    prescription_id: uuid.UUID,
    payload: UpdatePrescriptionRequest,
    current_user: CurrentUser = Depends(require_doctor),
    db: DBSession = Depends(get_db),
) -> PrescriptionSummary:
    try:
        prescription = await update_prescription_draft(
            prescription_id, payload.form_data, current_user.user_id, db
        )
    except AudioValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return PrescriptionSummary.model_validate(prescription)


@router.post("/{prescription_id}/finalize", response_model=PrescriptionSummary)
async def finalize_prescription_endpoint(
    prescription_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_doctor),
    db: DBSession = Depends(get_db),
) -> PrescriptionSummary:
    try:
        prescription = await finalize_prescription(prescription_id, current_user.user_id, db)
    except AudioValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return PrescriptionSummary.model_validate(prescription)