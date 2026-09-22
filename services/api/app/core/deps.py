"""Shared FastAPI dependency aliases for router signatures."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import CurrentUser

DbSession = Annotated[AsyncSession, Depends(get_db)]
"""Request-scoped ``AsyncSession``: ``db: DbSession``."""

__all__ = ["CurrentUser", "DbSession"]
