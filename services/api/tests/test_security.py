"""Tests for ``app.core.security``: hashing, JWT and the current-user dependency."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi import APIRouter, Depends
from httpx import AsyncClient
from jose import jwt

from app.core.config import settings
from app.core.security import (
    CurrentUser,
    create_access_token,
    decode_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.main import app
from app.models import User

# --------------------------------------------------------------------------- #
# Password hashing
# --------------------------------------------------------------------------- #


def test_hash_and_verify_roundtrip() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed.startswith("$2b$12$")
    assert verify_password("correct horse battery staple", hashed) is True
    assert verify_password("wrong password", hashed) is False


def test_hashes_are_salted() -> None:
    assert hash_password("same") != hash_password("same")


def test_hash_rejects_password_over_72_bytes() -> None:
    with pytest.raises(ValueError, match="72 bytes"):
        hash_password("x" * 73)


def test_verify_returns_false_for_overlong_or_malformed_input() -> None:
    hashed = hash_password("short")
    assert verify_password("x" * 73, hashed) is False
    assert verify_password("short", "not-a-bcrypt-hash") is False


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #


def test_access_token_roundtrip() -> None:
    user_id = uuid.uuid4()
    token = create_access_token(user_id)
    payload = decode_access_token(token)
    assert payload.sub == user_id
    assert payload.type == "access"
    assert payload.exp > payload.iat


def test_expired_token_is_rejected() -> None:
    token = create_access_token(uuid.uuid4(), expires_delta=timedelta(seconds=-1))
    with pytest.raises(ValueError, match="Invalid or expired"):
        decode_access_token(token)


def test_tampered_signature_is_rejected() -> None:
    token = create_access_token(uuid.uuid4())
    header, payload, _sig = token.split(".")
    with pytest.raises(ValueError):
        decode_access_token(f"{header}.{payload}.AAAA")


def test_token_signed_with_other_secret_is_rejected() -> None:
    forged = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "jti": str(uuid.uuid4()),
            "type": "access",
        },
        "another-secret-that-is-also-32-characters-long",
        algorithm="HS256",
    )
    with pytest.raises(ValueError):
        decode_access_token(forged)


def test_non_access_token_type_is_rejected() -> None:
    now = datetime.now(UTC)
    refresh_like = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "jti": str(uuid.uuid4()),
            "type": "refresh",
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(ValueError):
        decode_access_token(refresh_like)


def test_token_missing_required_claims_is_rejected() -> None:
    now = datetime.now(UTC)
    no_sub = jwt.encode(
        {"iat": now, "exp": now + timedelta(minutes=5), "type": "access"},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(ValueError):
        decode_access_token(no_sub)


# --------------------------------------------------------------------------- #
# get_current_user dependency (via a throwaway protected route)
# --------------------------------------------------------------------------- #

_probe = APIRouter()


@_probe.get("/_test/me")
async def _me(user: CurrentUser) -> dict[str, str]:
    return {"id": str(user.id), "email": user.email}


app.include_router(_probe)


async def test_current_user_missing_header_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/_test/me")
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"] == "Bearer"


async def test_current_user_invalid_token_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/_test/me", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


async def test_current_user_unknown_user_returns_401(
    client: AsyncClient, mock_session: MagicMock
) -> None:
    mock_session.get.return_value = None
    token = create_access_token(uuid.uuid4())
    resp = await client.get("/_test/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "User not found"


async def test_current_user_success(
    client: AsyncClient, mock_session: MagicMock, fake_user: User
) -> None:
    mock_session.get.return_value = fake_user
    token = create_access_token(fake_user.id)
    resp = await client.get("/_test/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == {"id": str(fake_user.id), "email": fake_user.email}
    mock_session.get.assert_awaited_once_with(User, fake_user.id)


def test_dependency_is_exported_for_routers() -> None:
    # Guard against accidental renames breaking every protected router.
    assert callable(get_current_user)
    assert Depends is not None
