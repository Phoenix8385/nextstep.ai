"""Password hashing, JWT issuance/verification and the current-user dependency.

Security notes
--------------
* Passwords are hashed with bcrypt (cost 12). bcrypt silently ignores bytes
  after the 72nd, so we reject longer passwords up-front rather than let two
  different passwords collide.
* Access tokens are HS256 JWTs signed with ``settings.JWT_SECRET``. The
  accepted algorithm list is pinned explicitly on decode to rule out
  algorithm-confusion attacks (``alg: none`` or asymmetric-key substitution).
* Tokens carry a ``type`` claim so a future refresh token can never be replayed
  as an access token.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Final, Literal

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.user import User

BCRYPT_ROUNDS: Final[int] = 12
BCRYPT_MAX_PASSWORD_BYTES: Final[int] = 72

TokenType = Literal["access"]

_bearer_scheme = HTTPBearer(auto_error=False, scheme_name="JWT")


class TokenPayload(BaseModel):
    """Validated claims extracted from a decoded access token."""

    sub: uuid.UUID
    exp: datetime
    iat: datetime
    jti: uuid.UUID
    type: TokenType


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    """Return a bcrypt hash of ``password`` suitable for storing in ``users.hashed_password``.

    Raises:
        ValueError: if the UTF-8 encoded password exceeds bcrypt's 72-byte limit.
    """
    encoded = password.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_PASSWORD_BYTES:
        msg = f"Password must be at most {BCRYPT_MAX_PASSWORD_BYTES} bytes when UTF-8 encoded"
        raise ValueError(msg)
    return bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("ascii")


def verify_password(password: str, hashed_password: str) -> bool:
    """Constant-time check of ``password`` against a stored bcrypt hash.

    Returns ``False`` (never raises) for malformed hashes or over-long input so
    callers can treat every failure identically and avoid oracle behaviour.
    """
    encoded = password.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_PASSWORD_BYTES:
        return False
    try:
        return bcrypt.checkpw(encoded, hashed_password.encode("ascii"))
    except ValueError:
        return False


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #
def create_access_token(
    subject: uuid.UUID | str,
    *,
    expires_delta: timedelta | None = None,
) -> str:
    """Issue a signed access token for ``subject`` (the user id).

    Args:
        subject: The user's UUID.
        expires_delta: Override the default lifetime from settings.
    """
    now = datetime.now(UTC)
    lifetime = expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    claims: dict[str, Any] = {
        "sub": str(subject),
        "iat": now,
        "exp": now + lifetime,
        "jti": str(uuid.uuid4()),
        "type": "access",
    }
    return str(jwt.encode(claims, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM))


def decode_access_token(token: str) -> TokenPayload:
    """Verify signature/expiry and return the typed claims.

    Raises:
        ValueError: if the token is invalid, expired, malformed or not an access token.
    """
    try:
        raw_claims: dict[str, Any] = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require_exp": True, "require_iat": True, "require_sub": True},
        )
        payload = TokenPayload.model_validate(raw_claims)
    except (JWTError, ValidationError) as exc:
        # ValidationError also covers a wrong ``type`` claim (TokenPayload pins "access").
        msg = "Invalid or expired token"
        raise ValueError(msg) from exc
    return payload


# --------------------------------------------------------------------------- #
# FastAPI dependencies
# --------------------------------------------------------------------------- #
def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Resolve the authenticated :class:`User` from the ``Authorization: Bearer`` header.

    Raises:
        HTTPException 401: when the header is missing, the token is invalid, or the
            user no longer exists.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized("Not authenticated")

    try:
        payload = decode_access_token(credentials.credentials)
    except ValueError as exc:
        raise _unauthorized(str(exc)) from exc

    user = await db.get(User, payload.sub)
    if user is None:
        raise _unauthorized("User not found")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
"""Type alias for router signatures: ``user: CurrentUser``."""
