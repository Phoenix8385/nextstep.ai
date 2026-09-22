"""User account and profile models."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import created_at_column, uuid_pk

if TYPE_CHECKING:
    from app.models.application import Application
    from app.models.job import SavedJob
    from app.models.resume import Resume


class User(Base):
    """An account holder. ``hashed_password`` is null for OAuth-only sign-ins."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = created_at_column()

    profile: Mapped[UserProfile | None] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    resumes: Mapped[list[Resume]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    saved_jobs: Mapped[list[SavedJob]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    applications: Mapped[list[Application]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"


class UserProfile(Base):
    """Career preferences and academic background; one row per user."""

    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    college: Mapped[str | None] = mapped_column(Text, nullable=True)
    branch: Mapped[str | None] = mapped_column(Text, nullable=True)
    cgpa: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    graduation_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    experience_level: Mapped[str | None] = mapped_column(Text, nullable=True)
    preferred_roles: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}"
    )
    preferred_locations: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}"
    )
    preferred_work_mode: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}"
    )
    skills: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}"
    )

    user: Mapped[User] = relationship(back_populates="profile")

    def __repr__(self) -> str:
        return f"<UserProfile user_id={self.user_id}>"
