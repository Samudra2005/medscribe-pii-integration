"""
Admin-facing audit log viewer, with filtering -- your "logs and
analysis" requirement, queryable from the API/frontend rather than
requiring direct DB/psql access for routine review.
"""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as DBSession

from app.api.deps import require_admin
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.enums import AuditAction
from app.schemas.audit import AuditLogEntry
from app.schemas.auth import CurrentUser

router = APIRouter(prefix="/admin/audit-logs", tags=["admin-audit-logs"])


@router.get("", response_model=list[AuditLogEntry])
async def list_audit_logs(
    action: AuditAction | None = None,
    actor_user_id: uuid.UUID | None = None,
    target_entity_type: str | None = None,
    target_entity_id: uuid.UUID | None = None,
    success: bool | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: CurrentUser = Depends(require_admin),
    db: DBSession = Depends(get_db),
) -> list[AuditLogEntry]:
    """
    All filters are optional and combine with AND. limit is capped at
    500 per request -- a government audit reviewer paging through logs
    should use start_date/end_date + offset for large ranges rather than
    us returning unbounded result sets that could exhaust memory/bandwidth.
    """
    query = select(AuditLog)

    if action:
        query = query.where(AuditLog.action == action)
    if actor_user_id:
        query = query.where(AuditLog.actor_user_id == actor_user_id)
    if target_entity_type:
        query = query.where(AuditLog.target_entity_type == target_entity_type)
    if target_entity_id:
        query = query.where(AuditLog.target_entity_id == target_entity_id)
    if success is not None:
        query = query.where(AuditLog.success == success)
    if start_date:
        query = query.where(AuditLog.occurred_at >= start_date)
    if end_date:
        query = query.where(AuditLog.occurred_at <= end_date)

    query = query.order_by(AuditLog.occurred_at.desc()).limit(limit).offset(offset)

    result = await db.execute(query)
    entries = result.scalars().all()
    return [AuditLogEntry.model_validate(e) for e in entries]