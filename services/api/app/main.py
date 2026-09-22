"""FastAPI application factory and ASGI entry point.

Run locally with::

    uvicorn app.main:app --reload
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.database import dispose_engine, ping_database
from app.routers import (
    analytics,
    applications,
    auth,
    health,
    jobs,
    profile,
    resumes,
    saved_jobs,
)

logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Verify database connectivity on startup and release the pool on shutdown.

    A failed ping raises so the process exits non-zero and the orchestrator
    restarts it, instead of serving requests that will all fail.
    """
    logger.info("Starting %s (%s)", settings.APP_NAME, settings.ENVIRONMENT)
    await ping_database()
    logger.info("Database connection verified")
    try:
        yield
    finally:
        await dispose_engine()
        logger.info("Database engine disposed")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        lifespan=lifespan,
        # Hide interactive docs in production; they leak the full schema.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(profile.router)
    app.include_router(jobs.router)
    app.include_router(saved_jobs.router)
    app.include_router(resumes.router)
    app.include_router(applications.router)
    app.include_router(analytics.router)

    _register_exception_handlers(app)
    return app


def _register_exception_handlers(app: FastAPI) -> None:
    """Attach handlers that give every error a consistent JSON body."""

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            # Error contexts can hold Decimal/datetime bounds; encode them first.
            content={"detail": jsonable_encoder(exc.errors())},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        # Log the traceback server-side; never echo internals to the client.
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )


app: FastAPI = create_app()
