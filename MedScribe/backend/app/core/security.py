"""
Core security primitives: password hashing/verification and secure
random token generation. Nothing in this file talks to the database --
it's pure, testable cryptographic utility code.
"""
import secrets
import hashlib

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError

# Parameters per OWASP 2026 guidance for interactive server-side login:
# time_cost=3, memory_cost=64 MiB, parallelism=1 -> ~100ms per verification
# on a modern core. This is deliberately slow -- that's the point: it makes
# brute-forcing stolen hashes computationally expensive.
_ph = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,  # KiB, so this is 64 MiB
    parallelism=1,
)


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password for storage. Never store plain_password anywhere."""
    return _ph.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plaintext password against a stored hash.
    Returns False on ANY failure (wrong password, corrupted hash, etc.)
    rather than raising -- callers should treat verification failure
    uniformly, without needing to catch specific exception types.
    """
    try:
        return _ph.verify(hashed_password, plain_password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(hashed_password: str) -> bool:
    """
    True if the stored hash was created with older/weaker parameters than
    our current settings -- lets us transparently upgrade a user's hash
    to current parameters the next time they successfully log in, without
    ever forcing a password reset. Standard security hygiene practice.
    """
    return _ph.check_needs_rehash(hashed_password)


def generate_session_token() -> str:
    """
    Cryptographically secure random token for a new session -- 256 bits
    of entropy, URL-safe. This is the value given to the client (as a
    cookie); only its HASH is ever stored server-side (see hash_token).
    """
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """
    SHA-256 hash of a session token, for storage. We store only this hash
    (in both Redis key and the Postgres sessions.session_token_hash
    column) so that even a full database/Redis dump doesn't expose usable
    session tokens -- same principle as password hashing, applied to
    session tokens.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_temp_password() -> str:
    """
    Generates a random temporary password for admin-created accounts.
    The user is forced to change it on first login (must_change_password
    flag from the User model) -- so the admin never learns the user's
    real, ongoing password.
    """
    return secrets.token_urlsafe(12)