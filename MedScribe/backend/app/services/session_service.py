"""
Session lifecycle management. This is the ONLY place in the codebase
that should read/write session data -- centralizing it here means the
Redis key format, TTL policy, and dual-write-to-Postgres logic all live
in one auditable place.

Key design:
- Redis key: "session:{token_hash}" -> JSON blob {user_id, role, ...}
  with a TTL matching session expiry. This is the FAST path, checked on
  every authenticated request.
- Postgres sessions row: durable audit record of the same session,
  written at login, marked revoked_at at logout -- survives Redis
  restarts and gives us historical "who logged in when" queries.
- A second Redis SET ("user_sessions:{user_id}") tracks all active
  session token hashes for a user, so an admin revoking a user's access
  can invalidate ALL of that user's sessions in one operation, not just
  block new logins.
"""
import json
import uuid
from datetime import datetime, timedelta, timezone

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as DBSession

from app.core.config import get_settings
from app.core.logging_config import get_logger
from app.core.security import generate_session_token, hash_token
from app.models.session import UserSession
from app.models.user import User

logger = get_logger(__name__)
settings = get_settings()

SESSION_TTL_SECONDS = 60 * 60 * 8  # 8 hours -- a working shift, reasonable default for clinical staff
SESSION_KEY_PREFIX = "session:"
USER_SESSIONS_SET_PREFIX = "user_sessions:"


async def create_session(
    db: DBSession,
    redis: Redis,
    user: User,
    ip_address: str | None,
    user_agent: str | None,
) -> str:
    """
    Creates a new session: writes to Redis (fast path) AND Postgres
    (durable audit record). Returns the RAW token to give to the client
    -- this is the only moment the raw token exists outside the client's
    own cookie; everywhere else, only its hash is stored.
    """
    raw_token = generate_session_token()
    token_hash = hash_token(raw_token)

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=SESSION_TTL_SECONDS)

    # ---- Redis: fast lookup path ----
    session_payload = {
        "user_id": str(user.id),
        "role": user.role.value,
        "username": user.username,
        "created_at": now.isoformat(),
    }
    redis_key = f"{SESSION_KEY_PREFIX}{token_hash}"
    await redis.set(redis_key, json.dumps(session_payload), ex=SESSION_TTL_SECONDS)

    # Track this session under the user's session set, so we can revoke
    # every session for a user in one pass (Step 4.x, admin deactivation flow).
    user_set_key = f"{USER_SESSIONS_SET_PREFIX}{user.id}"
    await redis.sadd(user_set_key, token_hash)
    await redis.expire(user_set_key, SESSION_TTL_SECONDS)

    # ---- Postgres: durable audit record ----
    db_session = UserSession(
        user_id=user.id,
        session_token_hash=token_hash,
        ip_address=ip_address,
        user_agent=user_agent,
        expires_at=expires_at,
        is_active=True,
    )
    db.add(db_session)
    await db.commit()

    logger.info("session_created", user_id=str(user.id), role=user.role.value)
    return raw_token


async def get_session(redis: Redis, raw_token: str) -> dict | None:
    """
    Fast-path session lookup for every authenticated request. Returns
    None if the session doesn't exist or has expired -- Redis's own TTL
    handles expiry automatically, so an expired session simply isn't
    found here, no manual expiry-checking logic needed.
    """
    token_hash = hash_token(raw_token)
    raw = await redis.get(f"{SESSION_KEY_PREFIX}{token_hash}")
    if raw is None:
        return None
    return json.loads(raw)


async def revoke_session(db: DBSession, redis: Redis, raw_token: str) -> None:
    """Single-session logout: removes the Redis key and marks the Postgres record revoked."""
    token_hash = hash_token(raw_token)

    await redis.delete(f"{SESSION_KEY_PREFIX}{token_hash}")

    result = await db.execute(
        select(UserSession).where(UserSession.session_token_hash == token_hash)
    )
    db_session = result.scalar_one_or_none()
    if db_session is not None:
        db_session.is_active = False
        db_session.revoked_at = datetime.now(timezone.utc)
        await redis.srem(f"{USER_SESSIONS_SET_PREFIX}{db_session.user_id}", token_hash)
        await db.commit()

    logger.info("session_revoked", token_hash=token_hash[:8] + "...")


async def revoke_all_sessions_for_user(db: DBSession, redis: Redis, user_id: uuid.UUID) -> int:
    """
    Revokes EVERY active session for a user -- used when an admin
    deactivates/suspends an account, or a user changes their password.
    Returns the count of sessions revoked, for audit logging.
    """
    user_set_key = f"{USER_SESSIONS_SET_PREFIX}{user_id}"
    token_hashes = await redis.smembers(user_set_key)

    if token_hashes:
        redis_keys = [f"{SESSION_KEY_PREFIX}{th}" for th in token_hashes]
        await redis.delete(*redis_keys)
        await redis.delete(user_set_key)

    result = await db.execute(
        select(UserSession).where(
            UserSession.user_id == user_id,
            UserSession.is_active == True,  # noqa: E712
        )
    )
    active_sessions = result.scalars().all()
    now = datetime.now(timezone.utc)
    for s in active_sessions:
        s.is_active = False
        s.revoked_at = now
    await db.commit()

    logger.info("all_sessions_revoked", user_id=str(user_id), count=len(active_sessions))
    return len(active_sessions)