"""Tests for ``app.core.config``."""

from collections.abc import Callable

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from tests.conftest import TEST_ENV


@pytest.fixture()
def make_settings(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Settings]:
    """Build ``Settings`` from the test env plus overrides, bypassing ``.env``.

    Values go through ``monkeypatch.setenv`` so pydantic-settings applies the same
    JSON decoding it uses in production (init kwargs skip that step).
    """

    def _build(**overrides: str) -> Settings:
        for key, value in {**TEST_ENV, **overrides}.items():
            monkeypatch.setenv(key, value)
        return Settings(_env_file=None)  # type: ignore[call-arg]

    return _build


def test_loads_required_values(make_settings: Callable[..., Settings]) -> None:
    s = make_settings()
    assert s.DATABASE_URL == TEST_ENV["DATABASE_URL"]
    assert s.REDIS_URL == TEST_ENV["REDIS_URL"]
    assert s.STORAGE_BUCKET == TEST_ENV["STORAGE_BUCKET"]
    assert s.ENVIRONMENT == "test"
    assert s.is_production is False


def test_allowed_origins_parsed_from_json_and_normalised(
    make_settings: Callable[..., Settings],
) -> None:
    s = make_settings(ALLOWED_ORIGINS='["http://localhost:3000/", "https://app.example.com"]')
    assert s.ALLOWED_ORIGINS == ["http://localhost:3000", "https://app.example.com"]


def test_rejects_invalid_environment(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(ValidationError):
        make_settings(ENVIRONMENT="staging")


def test_rejects_sync_database_driver(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(ValidationError, match="asyncpg"):
        make_settings(DATABASE_URL="postgresql://nextstep:pw@localhost/db")


def test_rejects_short_jwt_secret(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(ValidationError, match="32 characters"):
        make_settings(JWT_SECRET="short")


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
