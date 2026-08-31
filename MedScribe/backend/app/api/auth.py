"""
Authentication endpoints: login, logout, change password, and "who am I."
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession as DBSession

from app.api.deps import SESSION_COOKIE_NAME, get_current_user
from app.core.config import get_settings
from app.core.logging_config import get_logger
from app.db.redis_client import get_redis
from app.db.session import get_db
from app.models.enums import AuditAction
from app.schemas.auth import ChangePasswordRequest, CurrentUser, LoginRequest, LoginResponse
from app.services.auth_service import AuthenticationError, authenticate_user, change_password
from app.services.audit_service import write_audit_log
from app.services.session_service import create_session, revoke_session
from sqlalchemy import select
from app.models.user import User
from app.core.security import verify_password
from app.core.rate_limiting import limiter

logger = get_logger(__name__)
settings = get_settings()

router = APIRouter(prefix="/auth", tags=["auth"])

@limiter.limit(get_settings().RATE_LIMIT_LOGIN)

@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DBSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> LoginResponse:
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    try:
        user = await authenticate_user(db, payload.username, payload.password)
    except AuthenticationError as exc:
        await write_audit_log(
            db,
            action=AuditAction.LOGIN_FAILED,
            actor_user_id=None,
            actor_role=None,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"attempted_username": payload.username},
            success=False,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    raw_token = await create_session(db, redis, user, ip_address, user_agent)

    # httponly=True: JavaScript cannot read this cookie (mitigates XSS
    # token theft). secure=False for now because local dev is plain
    # HTTP -- this MUST become True once we're behind HTTPS (Phase 16).
    # samesite="lax": reasonable CSRF baseline for a same-site frontend.
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        max_age=60 * 60 * 8,
    )

    await write_audit_log(
        db,
        action=AuditAction.LOGIN_SUCCESS,
        actor_user_id=user.id,
        actor_role=user.role.value,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return LoginResponse(
        user_id=user.id,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
        must_change_password=user.must_change_password,
    )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    current_user: CurrentUser = Depends(get_current_user),
    db: DBSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_token:
        await revoke_session(db, redis, raw_token)

    response.delete_cookie(SESSION_COOKIE_NAME)

    await write_audit_log(
        db,
        action=AuditAction.LOGOUT,
        actor_user_id=current_user.user_id,
        actor_role=current_user.role.value,
    )

    return {"message": "Logged out successfully"}


@router.get("/me", response_model=LoginResponse)
async def read_current_user(
    current_user: CurrentUser = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> LoginResponse:
    """Returns full current-user details -- used by the frontend on page load to restore session state."""
    result = await db.execute(select(User).where(User.id == current_user.user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return LoginResponse(
        user_id=user.id,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
        must_change_password=user.must_change_password,
    )


@router.post("/change-password")
async def change_password_route(
    payload: ChangePasswordRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: DBSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict:
    result = await db.execute(select(User).where(User.id == current_user.user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    await change_password(db, user, payload.new_password)

    # Changing password invalidates ALL existing sessions for this user,
    # including the one making this request -- forces a fresh login with
    # the new password, standard security practice.
    from app.services.session_service import revoke_all_sessions_for_user
    await revoke_all_sessions_for_user(db, redis, user.id)

    await write_audit_log(
        db,
        action=AuditAction.UPDATE,
        actor_user_id=user.id,
        actor_role=user.role.value,
        target_entity_type="user",
        target_entity_id=user.id,
        metadata={"field": "password"},
    )

    return {"message": "Password changed successfully. Please log in again."}