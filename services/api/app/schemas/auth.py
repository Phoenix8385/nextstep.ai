"""Request/response bodies for ``/auth``."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.security import BCRYPT_MAX_PASSWORD_BYTES

PASSWORD_MIN_LENGTH = 8


class _PasswordMixin(BaseModel):
    """Shared password validation for signup and login bodies."""

    password: str = Field(..., min_length=PASSWORD_MIN_LENGTH, examples=["correct-horse-battery"])

    @field_validator("password")
    @classmethod
    def _fits_bcrypt(cls, value: str) -> str:
        """Reject passwords bcrypt would silently truncate (see ``app.core.security``)."""
        if len(value.encode("utf-8")) > BCRYPT_MAX_PASSWORD_BYTES:
            msg = f"Password must be at most {BCRYPT_MAX_PASSWORD_BYTES} bytes"
            raise ValueError(msg)
        return value


class SignupRequest(_PasswordMixin):
    """Body for ``POST /auth/signup``."""

    email: EmailStr = Field(..., examples=["ada@example.com"])
    full_name: str = Field(..., min_length=1, max_length=255, examples=["Ada Lovelace"])

    @field_validator("full_name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            msg = "full_name must not be blank"
            raise ValueError(msg)
        return stripped


class LoginRequest(_PasswordMixin):
    """Body for ``POST /auth/login``."""

    email: EmailStr


class UserResponse(BaseModel):
    """Public representation of a user; never includes the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    created_at: datetime


class TokenResponse(BaseModel):
    """Returned by signup and login."""

    access_token: str
    token_type: str = "bearer"  # — OAuth2 token type label, not a secret
    expires_in: int = Field(..., description="Seconds until the access token expires")
    user: UserResponse
