"""
Pydantic schemas for user management (admin-facing).
"""
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import UserRole, UserStatus


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=100)
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=255)
    role: UserRole


class CreateUserResponse(BaseModel):
    """
    Returned once, at creation time only -- includes the auto-generated
    temporary password so the admin can communicate it to the new user
    out-of-band. This value is NEVER retrievable again after this
    response (we only ever store the hash), which is intentional.
    """
    user_id: uuid.UUID
    username: str
    temporary_password: str


class UserSummary(BaseModel):
    """Used in list views -- deliberately excludes hashed_password and other sensitive internals."""
    id: uuid.UUID
    username: str
    email: str
    full_name: str
    role: UserRole
    status: UserStatus
    is_locked: bool
    created_at: datetime

    model_config = {"from_attributes": True}  # lets us build this directly from an ORM User object


class UpdateUserStatusRequest(BaseModel):
    status: UserStatus