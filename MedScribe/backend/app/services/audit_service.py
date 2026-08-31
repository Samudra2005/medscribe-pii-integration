"""
Writes to the audit_logs table. This is the single write path for audit
records -- called explicitly at every significant action (login,
logout, create/edit/delete on clinical records, HITL resolution, PDF
export, etc.) throughout the codebase, rather than trying to infer
"significant actions" generically from middleware, which tends to
either miss things or create noisy, low-value log spam.
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession as DBSession

from app.core.logging_config import get_logger
from app.models.audit_log import AuditLog
from app.models.enums import AuditAction

logger = get_logger(__name__)


async def write_audit_log(
    db: DBSession,
    *,
    action: AuditAction,
    actor_user_id: uuid.UUID | None,
    actor_role: str | None,
    target_entity_type: str | None = None,
    target_entity_id: uuid.UUID | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict | None = None,
    success: bool = True,
) -> None:
    """
    Writes one audit record. Commits independently of the caller's own
    transaction state where possible -- audit logging failing should
    never silently swallow the fact that it failed, but a failure here
    also shouldn't be allowed to corrupt an otherwise-successful business
    operation's transaction. We commit explicitly right here.
    """
    entry = AuditLog(
        action=action,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        target_entity_type=target_entity_type,
        target_entity_id=target_entity_id,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata_json=metadata,
        success=success,
    )
    db.add(entry)
    await db.commit()

    logger.info(
        "audit_log_written",
        action=action.value,
        actor_user_id=str(actor_user_id) if actor_user_id else None,
        target_entity_type=target_entity_type,
        success=success,
    )