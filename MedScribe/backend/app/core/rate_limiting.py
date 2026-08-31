"""
Rate limiting (Phase 16 hardening) -- backed by the same Redis instance
already used for sessions, so multi-process deployments share limit
state correctly (an in-memory limiter would not). Limits by client IP
(get_remote_address), the standard approach for public-facing auth
endpoints.

RELATIONSHIP TO PHASE 4's ACCOUNT LOCKOUT: these are deliberately
different, complementary protections, not redundant. Account lockout
(5 failed attempts -> is_locked) protects ONE SPECIFIC ACCOUNT from
being brute-forced regardless of source IP. Rate limiting here protects
the ENDPOINT ITSELF from being hammered across MANY different accounts/
usernames from one source, which account lockout alone doesn't address.
RATE_LIMIT_LOGIN (10/minute) is deliberately looser than the 5-attempt
lockout threshold -- it's a backstop against abuse, not the primary
brute-force defense, which remains the account lockout logic.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings

settings = get_settings()

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.REDIS_URL,
    default_limits=[settings.RATE_LIMIT_DEFAULT],
)