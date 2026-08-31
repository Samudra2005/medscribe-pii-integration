"""
Authentication business logic: login attempt handling, account lockout,
password change. This layer sits between the API route (thin, HTTP
concerns only) and the ORM models -- keeps route handlers simple and
makes this logic independently testable.
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as DBSession

from app.core.logging_config import get_logger
from app.core.security import hash_password, needs_rehash, verify_password
from app.models.user import User

logger = get_logger(__name__)

MAX_FAILED_ATTEMPTS = 5


class AuthenticationError(Exception):
    """Raised for any login failure -- route layer catches this and returns a generic 401."""


async def authenticate_user(db: DBSession, username: str, password: str) -> User:
    """
    Validates credentials and enforces account lockout policy.
    Deliberately returns the SAME error message/type for "user doesn't
    exist" and "wrong password" -- distinguishing these to the client
    would let an attacker enumerate valid usernames, a well-known
    information-leak vulnerability.
    """
    result = await db.execute(select(User).where(User.username == username))
    
    user = result.scalar_one_or_none()

    if user is None:
        logger.warning("login_failed_no_such_user", username=username)
        raise AuthenticationError("Invalid username or password")

    if user.is_locked:
        logger.warning("login_failed_account_locked", user_id=str(user.id))
        raise AuthenticationError("Account is locked. Contact an administrator.")

    if user.status.value != "active":
        logger.warning("login_failed_inactive_account", user_id=str(user.id), status=user.status.value)
        raise AuthenticationError("Account is not active. Contact an administrator.")

    if not verify_password(password, user.hashed_password):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
            user.is_locked = True
            logger.warning("account_locked_after_failed_attempts", user_id=str(user.id))
        await db.commit()
        logger.warning(
            "login_failed_wrong_password",
            user_id=str(user.id),
            attempts=user.failed_login_attempts,
        )
        raise AuthenticationError("Invalid username or password")

    # ---- Successful login: reset failure counter, opportunistically rehash ----
    user.failed_login_attempts = 0
    if needs_rehash(user.hashed_password):
        user.hashed_password = hash_password(password)
        logger.info("password_rehashed", user_id=str(user.id))
    await db.commit()

    logger.info("login_succeeded", user_id=str(user.id), role=user.role.value)
    return user


async def change_password(db: DBSession, user: User, new_password: str) -> None:
    user.hashed_password = hash_password(new_password)
    user.must_change_password = False
    await db.commit()
    logger.info("password_changed", user_id=str(user.id))