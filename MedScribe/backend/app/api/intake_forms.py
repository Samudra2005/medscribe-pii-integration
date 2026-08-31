import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession as DBSession

from app.api.deps import get_current_user, require_nurse
from app.db.session import get_db
from app.schemas.auth import CurrentUser
from app.schemas.intake_form import CreateIntakeFormRequest, IntakeFormSummary, IntakeFormData
from app.services.audio_service import AudioValidationError
from app.services.intake_form_service import (
    create_manual_intake_form,
    finalize_intake_form,
    get_intake_form_or_404,
    update_intake_form,
)
from app.services.intake_orchestrator import run_intake_draft_pipeline

router = APIRouter(prefix="/intake-forms", tags=["intake-forms"])


@router.post("", response_model=IntakeFormSummary, status_code=status.HTTP_201_CREATED)
async def create_intake_form(
    payload: CreateIntakeFormRequest,
    current_user: CurrentUser = Depends(require_nurse),
    db: DBSession = Depends(get_db),
) -> IntakeFormSummary:
    form = await create_manual_intake_form(
        uuid.UUID(payload.appointment_id), payload.form_data, current_user.user_id, db
    )
    return IntakeFormSummary.model_validate(form)


@router.post("/appointments/{appointment_id}/draft", response_model=IntakeFormSummary, status_code=status.HTTP_201_CREATED)
async def draft_intake_form(
    appointment_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_nurse),
    db: DBSession = Depends(get_db),
) -> IntakeFormSummary:
    """
    AI-assisted vitals extraction from NURSE_INTAKE-stage recordings
    only. Produces raw quoted-extraction text, NOT yet parsed into
    structured fields -- a nurse reviews the raw text and manually
    enters confirmed values via PATCH. See intake_orchestrator.py for
    why structured parsing wasn't built in this pass.
    """
    try:
        form = await run_intake_draft_pipeline(appointment_id, current_user.user_id, db)
    except AudioValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return IntakeFormSummary.model_validate(form)


@router.get("/{intake_form_id}", response_model=IntakeFormSummary)
async def get_intake_form(
    intake_form_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> IntakeFormSummary:
    try:
        form = await get_intake_form_or_404(intake_form_id, db)
    except AudioValidationError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return IntakeFormSummary.model_validate(form)


@router.patch("/{intake_form_id}", response_model=IntakeFormSummary)
async def edit_intake_form(
    intake_form_id: uuid.UUID,
    payload: IntakeFormData,
    current_user: CurrentUser = Depends(require_nurse),
    db: DBSession = Depends(get_db),
) -> IntakeFormSummary:
    try:
        form = await update_intake_form(intake_form_id, payload, current_user.user_id, db)
    except AudioValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return IntakeFormSummary.model_validate(form)


@router.post("/{intake_form_id}/finalize", response_model=IntakeFormSummary)
async def finalize_intake_form_endpoint(
    intake_form_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_nurse),
    db: DBSession = Depends(get_db),
) -> IntakeFormSummary:
    try:
        form = await finalize_intake_form(intake_form_id, current_user.user_id, db)
    except AudioValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return IntakeFormSummary.model_validate(form)