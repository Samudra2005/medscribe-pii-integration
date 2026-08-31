"""
Pydantic schemas for authentication requests/responses. These are
DELIBERATELY separate from the SQLAlchemy User model (app/models/user.py)
-- the API contract (what a client sends/receives) and the database
schema are allowed to diverge, e.g. we NEVER want hashed_password to
accidentally leak into an API response, which is trivially prevented by
having a dedicated response schema that simply doesn't include that field.
"""
import uuid

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import UserRole


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=256)


class LoginResponse(BaseModel):
    user_id: uuid.UUID
    username: str
    full_name: str
    role: UserRole
    must_change_password: bool


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=12, max_length=256)

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """
        Minimum viable password policy: length + character class variety.
        This is intentionally simple in Phase 4 -- a more sophisticated
        policy (breach-database checking via HaveIBeenPwned's k-anonymity
        API, etc.) is a reasonable Phase 16 hardening addition, not core
        to getting auth working now.
        """
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class CurrentUser(BaseModel):
    """
    Represents the authenticated user for the duration of a request --
    this is what our auth dependency (Step 4.6) will inject into route
    handlers via FastAPI's Depends(). Built directly from Redis session
    data, so it doesn't require a DB hit on every single request.
    """
    user_id: uuid.UUID
    username: str
    role: UserRole