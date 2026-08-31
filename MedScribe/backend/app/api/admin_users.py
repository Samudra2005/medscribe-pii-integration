"""
Admin-only user management endpoints: create, list, get, and
activate/suspend/deactivate accounts. Every mutating action here writes
an audit log entry -- this router is a good example of the pattern every
future admin-facing router should follow.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as DBSession

from app.api.deps import require_admin
from app.core.logging_config import get_logger
from app.core.security import generate_temp_password, hash_password
from app.db.redis_client import get_redis
from app.db.session import get_db
from app.models.enums import AuditAction, UserStatus
from app.models.user import User
from app.schemas.auth import CurrentUser
from app.schemas.user import CreateUserRequest, CreateUserResponse, UpdateUserStatusRequest, UserSummary
from app.services.audit_service import write_audit_log
from app.services.session_service import revoke_all_sessions_for_user

logger = get_logger(__name__)

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


@router.post("", response_model=CreateUserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: CreateUserRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_admin),
    db: DBSession = Depends(get_db),
) -> CreateUserResponse:
    existing = await db.execute(
        select(User).where((User.username == payload.username) | (User.email == payload.email))
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this username or email already exists",
        )

    temp_password = generate_temp_password()
    new_user = User(
        username=payload.username,
        email=payload.email,
        full_name=payload.full_name,
        role=payload.role,
        hashed_password=hash_password(temp_password),
        created_by_id=current_user.user_id,
        must_change_password=True,  # forces the new user to set their own real password
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    await write_audit_log(
        db,
        action=AuditAction.CREATE,
        actor_user_id=current_user.user_id,
        actor_role=current_user.role.value,
        target_entity_type="user",
        target_entity_id=new_user.id,
        ip_address=request.client.host if request.client else None,
        metadata={"created_username": new_user.username, "role": new_user.role.value},
    )

    logger.info("user_created", by=str(current_user.user_id), new_user_id=str(new_user.id))

    return CreateUserResponse(
        user_id=new_user.id,
        username=new_user.username,
        temporary_password=temp_password,
    )


@router.get("", response_model=list[UserSummary])
async def list_users(
    current_user: CurrentUser = Depends(require_admin),
    db: DBSession = Depends(get_db),
) -> list[UserSummary]:
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return [UserSummary.model_validate(u) for u in users]


@router.get("/{user_id}", response_model=UserSummary)
async def get_user(
    user_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_admin),
    db: DBSession = Depends(get_db),
) -> UserSummary:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserSummary.model_validate(user)


@router.patch("/{user_id}/status", response_model=UserSummary)
async def update_user_status(
    user_id: uuid.UUID,
    payload: UpdateUserStatusRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_admin),
    db: DBSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> UserSummary:
    if user_id == current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admins cannot change their own account status",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    old_status = user.status
    user.status = payload.status

    # Also clear any lockout when an admin explicitly reactivates a user --
    # otherwise a reactivated account would still be stuck locked out.
    if payload.status == UserStatus.ACTIVE:
        user.is_locked = False
        user.failed_login_attempts = 0

    await db.commit()

    # Deactivating/suspending must immediately revoke all active sessions
    # -- otherwise a nurse/doctor whose account was just deactivated could
    # keep using the system until their session naturally expires (up to
    # 8 hours later), which defeats the purpose of deactivating them.
    revoked_count = 0
    if payload.status != UserStatus.ACTIVE:
        revoked_count = await revoke_all_sessions_for_user(db, redis, user.id)

    await write_audit_log(
        db,
        action=AuditAction.UPDATE,
        actor_user_id=current_user.user_id,
        actor_role=current_user.role.value,
        target_entity_type="user",
        target_entity_id=user.id,
        ip_address=request.client.host if request.client else None,
        metadata={
            "field": "status",
            "old_status": old_status.value,
            "new_status": payload.status.value,
            "sessions_revoked": revoked_count,
        },
    )

    logger.info(
        "user_status_changed",
        by=str(current_user.user_id),
        target_user_id=str(user.id),
        new_status=payload.status.value,
    )

    return UserSummary.model_validate(user)