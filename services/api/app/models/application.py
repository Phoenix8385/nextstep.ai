"""Application tracker models.

Invariant: every change to ``applications.status`` must insert an
``application_events`` row **in the same transaction**. That is enforced in
the service layer (never update ``status`` directly from a router).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import (
    ApplicationStatus,
    created_at_column,
    updated_at_column,
    uuid_pk,
)

if TYPE_CHECKING:
    from app.models.job import Job
    from app.models.resume import ResumeVersion
    from app.models.user import User


class Application(Base):
    """A user's pursuit of one job, from saved through offer/rejection."""

    __tablename__ = "applications"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    resume_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("resume_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=ApplicationStatus.SAVED.value,
        server_default=ApplicationStatus.SAVED.value,
        index=True,
    )
    match_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_up_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    user: Mapped[User] = relationship(back_populates="applications")
    job: Mapped[Job] = relationship(back_populates="applications")
    resume_version: Mapped[ResumeVersion | None] = relationship(back_populates="applications")
    events: Mapped[list[ApplicationEvent]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="ApplicationEvent.event_time",
    )

    def __repr__(self) -> str:
        return f"<Application id={self.id} job_id={self.job_id} status={self.status!r}>"


class ApplicationEvent(Base):
    """Append-only audit row written alongside every application mutation."""

    __tablename__ = "application_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    event_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    details: Mapped[str | None] = mapped_column(Text, nullable=True)

    application: Mapped[Application] = relationship(back_populates="events")

    def __repr__(self) -> str:
        return (
            f"<ApplicationEvent id={self.id} application_id={self.application_id} "
            f"type={self.event_type!r}>"
        )
