"""Unit tests for ``/auth`` endpoints.

The database session is a mock (see ``tests/conftest.py``), so these exercise
request validation, hashing, token issuance and error mapping without Postgres.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from httpx import AsyncClient

from app.core.security import decode_access_token, hash_password
from app.models import User

SIGNUP_BODY = {"email": "Ada@Example.com", "password": "correct-horse-battery", "full_name": "Ada"}


def _execute_returning(user: User | None) -> AsyncMock:
    """Make ``session.execute`` yield a result whose ``scalar_one_or_none`` is ``user``."""
    result = MagicMock(name="Result")
    result.scalar_one_or_none.return_value = user
    return AsyncMock(return_value=result)


def _assign_db_defaults(user: User) -> None:
    """Stand in for ``session.refresh``: populate server/ORM defaults."""
    if user.id is None:
        user.id = uuid.uuid4()
    if user.created_at is None:
        user.created_at = datetime.now(UTC)


async def test_signup_success(client: AsyncClient, mock_session: MagicMock) -> None:
    mock_session.execute = _execute_returning(None)
    mock_session.refresh = AsyncMock(side_effect=_assign_db_defaults)

    resp = await client.post("/auth/signup", json=SIGNUP_BODY)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 5 * 60  # ACCESS_TOKEN_EXPIRE_MINUTES from test env
    assert body["user"]["email"] == "ada@example.com"  # normalised to lowercase
    assert body["user"]["full_name"] == "Ada"
    assert "hashed_password" not in body["user"]

    # The persisted object has a bcrypt hash, never the plaintext.
    added: User = mock_session.add.call_args.args[0]
    assert added.hashed_password is not None
    assert added.hashed_password.startswith("$2b$")
    assert "correct-horse-battery" not in added.hashed_password
    mock_session.commit.assert_awaited_once()

    # The token is valid and bound to the new user.
    assert decode_access_token(body["access_token"]).sub == uuid.UUID(body["user"]["id"])


async def test_signup_duplicate_email(
    client: AsyncClient, mock_session: MagicMock, fake_user: User
) -> None:
    mock_session.execute = _execute_returning(fake_user)

    resp = await client.post("/auth/signup", json=SIGNUP_BODY)

    assert resp.status_code == 409
    assert resp.json() == {"detail": "Email already registered"}
    mock_session.add.assert_not_called()
    mock_session.commit.assert_not_awaited()


async def test_login_wrong_password(
    client: AsyncClient, mock_session: MagicMock, fake_user: User
) -> None:
    fake_user.hashed_password = hash_password("right-password")
    mock_session.execute = _execute_returning(fake_user)

    resp = await client.post(
        "/auth/login", json={"email": fake_user.email, "password": "wrong-password"}
    )

    assert resp.status_code == 401
    assert resp.json() == {"detail": "Invalid email or password"}
    assert resp.headers["WWW-Authenticate"] == "Bearer"


async def test_login_valid(client: AsyncClient, mock_session: MagicMock, fake_user: User) -> None:
    fake_user.hashed_password = hash_password("right-password")
    mock_session.execute = _execute_returning(fake_user)

    resp = await client.post(
        "/auth/login", json={"email": fake_user.email, "password": "right-password"}
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["id"] == str(fake_user.id)
    assert decode_access_token(body["access_token"]).sub == fake_user.id


async def test_me_without_token(client: AsyncClient) -> None:
    resp = await client.get("/auth/me")

    assert resp.status_code == 401
    assert resp.json() == {"detail": "Not authenticated"}
    assert resp.headers["WWW-Authenticate"] == "Bearer"


async def test_me_with_valid_token(
    client: AsyncClient, mock_session: MagicMock, fake_user: User
) -> None:
    fake_user.hashed_password = hash_password("right-password")
    mock_session.execute = _execute_returning(fake_user)
    mock_session.get = AsyncMock(return_value=fake_user)

    login = await client.post(
        "/auth/login", json={"email": fake_user.email, "password": "right-password"}
    )
    token = login.json()["access_token"]

    resp = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "id": str(fake_user.id),
        "email": fake_user.email,
        "full_name": fake_user.full_name,
        "created_at": fake_user.created_at.isoformat().replace("+00:00", "Z"),
    }
    mock_session.get.assert_awaited_once_with(User, fake_user.id)
