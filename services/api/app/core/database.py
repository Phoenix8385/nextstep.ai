"""Async SQLAlchemy engine, session factory and declarative base.

Alembic migrations are the source of truth for the schema in every deployed
environment; :func:`create_tables` exists only for local experiments and tests.
"""

from collections.abc import AsyncGenerator

from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

# Deterministic constraint names make Alembic autogenerate diffs stable and
# allow constraints to be dropped by name in later migrations.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a request-scoped session.

    The session is rolled back if the request raises and always closed. Callers
    are responsible for calling ``await session.commit()`` explicitly so that
    multi-step writes (e.g. application status + application_events) share one
    transaction.
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def ping_database() -> bool:
    """Return ``True`` if a trivial query succeeds against the configured database."""
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        return bool(result.scalar_one() == 1)


async def create_tables() -> None:
    """Create all tables from ORM metadata.

    Development/test convenience only. Never call this in production — use
    ``alembic upgrade head`` so schema changes are versioned and reversible.
    """
    if settings.is_production:
        msg = "create_tables() is disabled in production; run Alembic migrations instead"
        raise RuntimeError(msg)

    # Importing the models package registers every table on Base.metadata.
    import app.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    """Close all pooled connections; called from the FastAPI lifespan on shutdown."""
    await engine.dispose()
