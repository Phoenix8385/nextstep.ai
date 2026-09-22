"""Shared pytest fixtures.

Environment variables are pinned *before* ``app`` is imported so the settings
singleton never depends on a developer's local ``.env``.
"""

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

TEST_ENV: dict[str, str] = {
    "DATABASE_URL": "postgresql+asyncpg://nextstep:localdevpassword@localhost:5432/nextstep_test",
    "REDIS_URL": "redis://localhost:6379/1",
    "JWT_SECRET": "test-secret-that-is-definitely-longer-than-32-chars",
    "ENVIRONMENT": "test",
    "ALLOWED_ORIGINS": '["http://localhost:3000", "http://testclient/"]',
    "STORAGE_BUCKET": "nextstep-resumes-test",
    "ACCESS_TOKEN_EXPIRE_MINUTES": "5",
}
if "TEST_DATABASE_URL" in os.environ:
    TEST_ENV["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ.update(TEST_ENV)

import app.models  # noqa: E402  — register tables on Base.metadata
from app.core.database import (  # noqa: E402
    AsyncSessionFactory,
    Base,
    engine,
    get_db,
    ping_database,
)
from app.core.security import create_access_token  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Job, JobSource, User  # noqa: E402


@pytest.fixture()
def fake_user() -> User:
    """A detached ``User`` instance that never touches the database."""
    return User(
        id=uuid.uuid4(),
        email="test@example.com",
        hashed_password=None,
        full_name="Test User",
        created_at=datetime.now(UTC),
    )


@pytest.fixture()
def mock_session() -> MagicMock:
    """An ``AsyncSession`` stand-in with async ``get``/``execute``/``commit``."""
    session = MagicMock(name="AsyncSession")
    session.get = AsyncMock(return_value=None)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    return session


@pytest.fixture()
async def client(mock_session: MagicMock) -> AsyncIterator[AsyncClient]:
    """HTTP client against the app with ``get_db`` overridden by ``mock_session``.

    The lifespan is intentionally *not* run so no real database is needed.
    """

    async def _override_get_db() -> AsyncIterator[Any]:
        yield mock_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testclient") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_headers(fake_user: User, mock_session: MagicMock) -> dict[str, str]:
    """Bearer header for ``fake_user``; also teaches the mock session to resolve them."""
    mock_session.get = AsyncMock(return_value=fake_user)
    return {"Authorization": f"Bearer {create_access_token(fake_user.id)}"}


@pytest.fixture()
def fake_source() -> JobSource:
    """A detached ``JobSource`` row."""
    return JobSource(id=1, name="greenhouse", board_token="stripe", is_active=True)


@pytest.fixture()
def make_job(fake_source: JobSource) -> Callable[..., Job]:
    """Factory for detached ``Job`` rows with sensible defaults; override any column via kwargs."""

    def _make(**overrides: Any) -> Job:
        now = datetime.now(UTC)
        values: dict[str, Any] = {
            "id": uuid.uuid4(),
            "source_id": fake_source.id,
            "external_job_id": str(uuid.uuid4().int)[:7],
            "source_url": "https://boards.greenhouse.io/stripe/jobs/6100001",
            "company_name": "Stripe",
            "title": "Software Engineer, New Grad",
            "location": "San Francisco, CA",
            "work_mode": "hybrid",
            "experience_level": "entry",
            "description": "Build payment APIs.",
            "requirements": "CS degree.",
            "required_skills": ["python", "sql"],
            "eligibility": None,
            "posted_at": now - timedelta(days=1),
            "detected_at": now,
            "deadline": None,
            "content_hash": "a" * 64,
            "is_active": True,
            "updated_at": now,
        }
        values.update(overrides)
        job = Job(**values)
        job.source = fake_source
        return job

    return _make


# --------------------------------------------------------------------------- #
# Real-database fixtures (opt-in). Tests requesting ``db_session`` / ``db_client``
# run against ``TEST_DATABASE_URL`` (or the CI default) on a freshly created
# schema and are skipped when that database is unreachable.
# --------------------------------------------------------------------------- #


def _database_reachable() -> bool:
    async def _probe() -> bool:
        try:
            return await ping_database()
        except Exception:  # any driver/network error → skip DB-backed tests
            return False
        finally:
            await engine.dispose()

    return asyncio.run(_probe())


@pytest.fixture(scope="session")
def _require_database() -> None:
    if not _database_reachable():
        pytest.skip("test database unreachable (set TEST_DATABASE_URL)")


@pytest.fixture()
async def fresh_schema(_require_database: None) -> AsyncIterator[None]:
    """Recreate every table before the test and drop them afterwards."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        # pytest-asyncio gives each test its own event loop; pooled asyncpg
        # connections are bound to the loop they were created on, so drop them.
        await engine.dispose()


@pytest.fixture()
async def db_session(fresh_schema: None) -> AsyncIterator[AsyncSession]:
    """A real session for arranging and inspecting rows."""
    async with AsyncSessionFactory() as session:
        yield session


@pytest.fixture()
async def db_client(fresh_schema: None) -> AsyncIterator[AsyncClient]:
    """HTTP client whose requests use the real ``get_db`` dependency."""
    app.dependency_overrides.clear()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testclient") as ac:
        yield ac


@pytest.fixture()
async def auth(db_client: AsyncClient) -> dict[str, str]:
    """Register a user through the API and return their bearer header."""
    resp = await db_client.post(
        "/auth/signup",
        json={"email": "it@example.com", "password": "correct-horse-battery", "full_name": "IT"},
    )
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# --------------------------------------------------------------------------- #
# Recorded job-board payloads served through httpx.MockTransport
# --------------------------------------------------------------------------- #

FIXTURES = Path(__file__).resolve().parent / "fixtures"

Route = tuple[int, Any]  # (status_code, JSON body | raw text)


def load_fixture(name: str) -> Any:
    """Parse ``tests/fixtures/<name>``."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture()
def mock_http() -> Callable[[dict[str, Route]], httpx.AsyncClient]:
    """Build an ``AsyncClient`` whose responses come from a ``{url_prefix: (status, body)}`` map.

    Bodies that are ``str`` are returned verbatim (for invalid-JSON cases);
    anything else is JSON-encoded. Unmatched URLs return 404.
    """

    def _build(routes: dict[str, Route]) -> httpx.AsyncClient:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            calls.append(url)
            for prefix, (status, body) in routes.items():
                if url.startswith(prefix):
                    if isinstance(body, str):
                        return httpx.Response(status, text=body)
                    return httpx.Response(status, json=body)
            return httpx.Response(404, json={"error": "no route"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client.calls = calls  # type: ignore[attr-defined]  # exposed for assertions
        return client

    return _build
