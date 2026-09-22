"""Registration, login and token issuance.

Security notes
--------------
* Login returns the same 401 for "unknown email" and "wrong password" and
  always runs a bcrypt verification (against a dummy hash when the user does
  not exist) so response timing does not reveal which emails are registered.
* Signup, by contrast, must reveal duplicates (409) — that is inherent to
  email-based registration. Rate-limit this endpoint at the edge.
* Email is normalised to lowercase before lookup/insert so the ``users.email``
  unique constraint is effectively case-insensitive.
"""

import logging

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.auth import LoginRequest, SignupRequest, TokenResponse, UserResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# A genuine bcrypt hash computed once at import. Used to equalise login timing
# when the email is unknown; the comparison result is discarded.
_DUMMY_HASH = hash_password("nextstep-timing-equaliser")

_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid email or password",
    headers={"WWW-Authenticate": "Bearer"},
)


def _token_response(user: User) -> TokenResponse:
    """Build the standard auth response for ``user``."""
    return TokenResponse(
        access_token=create_access_token(user.id),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserResponse.model_validate(user),
    )


async def _get_user_by_email(db: AsyncSession, email: str) -> User | None:
    """Look up a user by normalised email."""
    result = await db.execute(select(User).where(User.email == email.lower()))
    return result.scalar_one_or_none()


@router.post(
    "/signup",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"description": "Email already registered"}},
)
async def signup(body: SignupRequest, db: DbSession) -> TokenResponse:
    """Create an account and return an access token so the client is logged in immediately."""
    email = body.email.lower()

    if await _get_user_by_email(db, email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        email=email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        # Lost a race with a concurrent signup for the same email.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        ) from None
    await db.refresh(user)

    logger.info("User registered: %s", user.id)
    return _token_response(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    responses={status.HTTP_401_UNAUTHORIZED: {"description": "Invalid email or password"}},
)
async def login(body: LoginRequest, db: DbSession) -> TokenResponse:
    """Verify credentials and return an access token."""
    user = await _get_user_by_email(db, body.email)

    if user is None or user.hashed_password is None:
        # Burn the same bcrypt cost as a real check so timing is uniform.
        verify_password(body.password, _DUMMY_HASH)
        raise _INVALID_CREDENTIALS

    if not verify_password(body.password, user.hashed_password):
        raise _INVALID_CREDENTIALS

    return _token_response(user)


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUser) -> UserResponse:
    """Return the authenticated user's public profile."""
    return UserResponse.model_validate(user)
