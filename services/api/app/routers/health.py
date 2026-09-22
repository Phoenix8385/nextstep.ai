"""Liveness/readiness endpoint."""

import logging

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from app.core.config import settings
from app.core.database import ping_database

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class RootResponse(BaseModel):
    """Shape of ``GET /``: a signpost for people who open the API URL in a browser."""

    name: str
    version: str
    docs: str | None
    health: str


class HealthResponse(BaseModel):
    """Shape of ``GET /health``."""

    status: str
    database: str
    environment: str
    version: str


@router.get("/", response_model=RootResponse, include_in_schema=False)
async def root() -> RootResponse:
    """Identify the service and point at the interactive docs (hidden in production)."""
    return RootResponse(
        name=settings.APP_NAME,
        version=settings.APP_VERSION,
        docs=None if settings.is_production else "/docs",
        health="/health",
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
async def health(response: Response) -> HealthResponse:
    """Report API liveness and whether the database answers ``SELECT 1``.

    Returns 200 when healthy, 503 when the database is unreachable so load
    balancers and uptime monitors can act on it.
    """
    db_status = "ok"
    try:
        if not await ping_database():
            db_status = "error"
    except Exception:  # any driver/network failure means "unreachable"
        logger.exception("Database health check failed")
        db_status = "unreachable"

    overall = "ok" if db_status == "ok" else "degraded"
    if overall != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status=overall,
        database=db_status,
        environment=settings.ENVIRONMENT,
        version=settings.APP_VERSION,
    )
