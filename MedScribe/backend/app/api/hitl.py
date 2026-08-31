"""
Admin-facing HITL (human-in-the-loop) queue endpoints. This is the
"pending reviews / where the hitl hits" view from your website layout.
Currently there's nothing to POPULATE this queue yet -- that happens
starting Phase 10 (transcript quality engine) and Phase 12 (NER
validation) -- but the viewing/resolution API is built now so it's
ready the moment the pipeline starts writing to it.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as DBSession

from app.api.deps import require_admin
from app.db.session import get_db
from app.models.enums import AuditAction, HitlStatus
from app.models.hitl import HitlItem
from app.schemas.auth import CurrentUser
from app.schemas.hitl import HitlItemSummary, ResolveHitlRequest
from app.services.audit_service import write_audit_log

router = APIRouter(prefix="/admin/hitl", tags=["admin-hitl"])


@router.get("", response_model=list[HitlItemSummary])
async def list_hitl_items(
    status_filter: HitlStatus | None = None,
    current_user: CurrentUser = Depends(require_admin),
    db: DBSession = Depends(get_db),
) -> list[HitlItemSummary]:
    query = select(HitlItem)
    if status_filter:
        query = query.where(HitlItem.status == status_filter)
    else:
        # Default view: pending + in_review -- the actionable items.
        # Resolved/dismissed items are still queryable via explicit filter,
        # but shouldn't clutter the default "pending reviews" view.
        query = query.where(HitlItem.status.in_([HitlStatus.PENDING, HitlStatus.IN_REVIEW]))
    query = query.order_by(HitlItem.created_at.desc())

    result = await db.execute(query)
    items = result.scalars().all()
    return [HitlItemSummary.model_validate(i) for i in items]


@router.get("/{hitl_id}", response_model=HitlItemSummary)
async def get_hitl_item(
    hitl_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_admin),
    db: DBSession = Depends(get_db),
) -> HitlItemSummary:
    result = await db.execute(select(HitlItem).where(HitlItem.id == hitl_id))
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HITL item not found")
    return HitlItemSummary.model_validate(item)


@router.post("/{hitl_id}/claim", response_model=HitlItemSummary)
async def claim_hitl_item(
    hitl_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_admin),
    db: DBSession = Depends(get_db),
) -> HitlItemSummary:
    """
    Admin claims an item -- moves PENDING -> IN_REVIEW and assigns
    themselves. Prevents two admins from working the same item
    simultaneously without realizing it.
    """
    result = await db.execute(select(HitlItem).where(HitlItem.id == hitl_id))
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HITL item not found")
    if item.status != HitlStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Item is already {item.status.value}, cannot claim",
        )

    item.status = HitlStatus.IN_REVIEW
    item.assigned_admin_id = current_user.user_id
    await db.commit()

    return HitlItemSummary.model_validate(item)


@router.post("/{hitl_id}/resolve", response_model=HitlItemSummary)
async def resolve_hitl_item(
    hitl_id: uuid.UUID,
    payload: ResolveHitlRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_admin),
    db: DBSession = Depends(get_db),
) -> HitlItemSummary:
    result = await db.execute(select(HitlItem).where(HitlItem.id == hitl_id))
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HITL item not found")
    if item.status in (HitlStatus.RESOLVED, HitlStatus.DISMISSED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Item is already {item.status.value}",
        )

    item.status = HitlStatus.DISMISSED if payload.dismiss else HitlStatus.RESOLVED
    item.resolved_by_id = current_user.user_id
    item.resolution_notes = payload.resolution_notes
    item.resolved_at = datetime.now(timezone.utc)
    await db.commit()

    await write_audit_log(
        db,
        action=AuditAction.HITL_RESOLVE,
        actor_user_id=current_user.user_id,
        actor_role=current_user.role.value,
        target_entity_type="hitl_item",
        target_entity_id=item.id,
        ip_address=request.client.host if request.client else None,
        metadata={"reason": item.reason.value, "dismissed": payload.dismiss},
    )

    return HitlItemSummary.model_validate(item)