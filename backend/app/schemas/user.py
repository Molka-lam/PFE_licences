import uuid
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, EmailStr, ConfigDict, field_validator


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    first_name: str | None
    last_name: str | None
    role: Literal["super_admin", "admin", "client"]
    is_active: bool
    email_verified: bool
    email_opt_in: bool
    in_app_opt_in: bool
    created_at: datetime
    updated_at: datetime


class UserUpdate(BaseModel):
    """Fields a user can update on their own profile."""
    first_name: str | None = None
    last_name: str | None = None
    email_opt_in: bool | None = None
    in_app_opt_in: bool | None = None


class AdminUserUpdate(BaseModel):
    """Fields an admin can update on any user."""
    role: Literal["super_admin", "admin", "client"] | None = None
    is_active: bool | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v
