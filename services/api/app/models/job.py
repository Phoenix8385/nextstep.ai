"""Job source, normalised job posting, change log and saved-job models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import DateTime

from app.core.database import Base
from app.models.base import created_at_column, updated_at_column, uuid_pk

if TYPE_CHECKING:
    from app.models.application import Application
    from app.models.user import User


class JobSource(Base):
    """A job-board API we poll (Greenhouse, Lever, Ashby). ``board_token`` is the company slug."""

    __tablename__ = "job_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    board_token: Mapped[str] = mapped_column(Text, nullable=False)
    # Display name written to jobs.company_name; the board APIs mostly omit it.
    company_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    jobs: Mapped[list[Job]] = relationship(back_populates="source")

    def __repr__(self) -> str:
        return f"<JobSource id={self.id} name={self.name!r} board_token={self.board_token!r}>"


class Job(Base):
    """A normalised posting from any source, deduplicated by ``content_hash``."""

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("job_sources.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    external_job_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    company_name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    work_mode: Mapped[str | None] = mapped_column(Text, nullable=True)
    experience_level: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    required_skills: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}"
    )
    eligibility: Mapped[str | None] = mapped_column(Text, nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detected_at: Mapped[datetime] = created_at_column()
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true", index=True
    )
    updated_at: Mapped[datetime] = updated_at_column()

    source: Mapped[JobSource] = relationship(back_populates="jobs")
    change_logs: Mapped[list[JobChangeLog]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="JobChangeLog.changed_at",
    )
    saved_by: Mapped[list[SavedJob]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
    )
    applications: Mapped[list[Application]] = relationship(back_populates="job")

    __table_args__ = (UniqueConstraint("source_id", "external_job_id"),)

    def __repr__(self) -> str:
        return f"<Job id={self.id} company={self.company_name!r} title={self.title!r}>"


class JobChangeLog(Base):
    """Audit trail of field-level changes detected on re-fetch of a posting."""

    __tablename__ = "job_change_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    field_changed: Mapped[str] = mapped_column(Text, nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    job: Mapped[Job] = relationship(back_populates="change_logs")

    def __repr__(self) -> str:
        return f"<JobChangeLog id={self.id} job_id={self.job_id} field={self.field_changed!r}>"


class SavedJob(Base):
    """A bookmark linking a user to a job; each pair is saved at most once."""

    __tablename__ = "saved_jobs"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="saved_jobs")
    job: Mapped[Job] = relationship(back_populates="saved_by")

    __table_args__ = (UniqueConstraint("user_id", "job_id"),)

    def __repr__(self) -> str:
        return f"<SavedJob id={self.id} user_id={self.user_id} job_id={self.job_id}>"
