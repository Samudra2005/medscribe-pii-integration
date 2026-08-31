"""
Shared FastAPI dependencies for authentication and authorization.
Every protected route depends on get_current_user (or one of the
role-specific variants below) rather than reimplementing auth checks --
this is the single enforcement point for "is this request allowed."
"""
from fastapi import Cookie, Depends, HTTPException, status
from redis.asyncio import Redis

from app.core.logging_config import get_logger
from app.db.redis_client import get_redis
from app.models.enums import UserRole
from app.schemas.auth import CurrentUser
from app.services.session_service import get_session

logger = get_logger(__name__)

SESSION_COOKIE_NAME = "medstt_session"


async def get_current_user(
    medstt_session: str | None = Cookie(default=None),
    redis: Redis = Depends(get_redis),
) -> CurrentUser:
    """
    Reads the session cookie, looks it up in Redis, and returns the
    authenticated user. Raises 401 if missing/invalid/expired -- this
    is intentionally a single, generic error message for all three
    cases, same "don't leak which specific thing was wrong" principle
    as login itself.
    """
    if medstt_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    session_data = await get_session(redis, medstt_session)
    if session_data is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid",
        )

    return CurrentUser(
        user_id=session_data["user_id"],
        username=session_data["username"],
        role=UserRole(session_data["role"]),
    )


def require_role(*allowed_roles: UserRole):
    """
    Factory for a role-gating dependency. Usage on a route:
        @router.get("/admin-only", dependencies=[Depends(require_role(UserRole.ADMIN))])
    or to also get the user object:
        current_user: CurrentUser = Depends(require_role(UserRole.ADMIN, UserRole.DOCTOR))

    Returning 403 (not 404) when authenticated-but-wrong-role is a
    deliberate choice -- confirms the resource exists but access is
    denied, which is the correct HTTP semantic and doesn't meaningfully
    leak anything an authenticated user couldn't already infer.
    """

    async def _checker(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current_user.role not in allowed_roles:
            logger.warning(
                "authorization_denied",
                user_id=str(current_user.user_id),
                role=current_user.role.value,
                required_roles=[r.value for r in allowed_roles],
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource",
            )
        return current_user

    return _checker


# Convenience pre-built dependencies for the common single-role cases,
# used heavily across the admin/nurse/doctor routers in later phases.
require_admin = require_role(UserRole.ADMIN)
require_nurse = require_role(UserRole.NURSE)
require_doctor = require_role(UserRole.DOCTOR)
require_nurse_or_doctor = require_role(UserRole.NURSE, UserRole.DOCTOR)