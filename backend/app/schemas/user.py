import uuid
from datetime import datetime
from pydantic import BaseModel, EmailStr, ConfigDict, field_validator


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    first_name: str | None
    last_name: str | None
    role: str
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
    role: str | None = None
    is_active: bool | None = None

    @field_validator("role")
    @classmethod
    def valid_role(cls, v: str | None) -> str | None:
        if v is not None and v not in {"super_admin", "admin", "client"}:
            raise ValueError("role must be super_admin, admin, or client")
        return v
