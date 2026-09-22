"""Tests for ``GET /health`` and the app-level exception handlers."""

from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.main import app
from app.routers import health as health_module


async def test_health_ok_when_database_pings(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health_module, "ping_database", AsyncMock(return_value=True))
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["environment"] == "test"
    assert body["version"]


async def test_health_503_when_database_raises(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        health_module, "ping_database", AsyncMock(side_effect=ConnectionError("refused"))
    )
    resp = await client.get("/health")
    assert resp.status_code == 503
    assert resp.json() == {
        "status": "degraded",
        "database": "unreachable",
        "environment": "test",
        "version": resp.json()["version"],
    }


async def test_health_503_when_select_1_is_wrong(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health_module, "ping_database", AsyncMock(return_value=False))
    resp = await client.get("/health")
    assert resp.status_code == 503
    assert resp.json()["database"] == "error"


async def test_cors_allows_configured_origin(client: AsyncClient) -> None:
    resp = await client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"


async def test_cors_blocks_unknown_origin(client: AsyncClient) -> None:
    resp = await client.options(
        "/health",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in resp.headers


async def test_unhandled_exception_returns_generic_500(client: AsyncClient) -> None:
    @app.get("/_test/boom")
    async def _boom() -> None:
        msg = "secret internal detail"
        raise RuntimeError(msg)

    # Starlette's TestClient would re-raise; httpx ASGITransport lets the handler run.
    resp = await client.get("/_test/boom")
    assert resp.status_code == 500
    assert resp.json() == {"detail": "Internal server error"}
    assert "secret internal detail" not in resp.text


async def test_root_signposts_docs_and_health(client: AsyncClient) -> None:
    resp = await client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "NextStep.ai API"
    assert body["docs"] == "/docs"
    assert body["health"] == "/health"


def test_all_routers_registered() -> None:
    prefixes = {route.path for route in app.routes}  # type: ignore[attr-defined]
    assert "/health" in prefixes
    # Placeholder routers have no endpoints yet, so check the OpenAPI tags instead.
    tag_names = {
        tag
        for route in app.routes
        for tag in getattr(route, "tags", [])  # type: ignore[attr-defined]
    }
    assert "health" in tag_names
