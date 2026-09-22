"""Resume upload and parsed-version models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import created_at_column, uuid_pk

if TYPE_CHECKING:
    from app.models.application import Application
    from app.models.user import User


class Resume(Base):
    """A resume file uploaded by a user. ``file_url`` points at object storage."""

    __tablename__ = "resumes"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_url: Mapped[str] = mapped_column(Text, nullable=False)
    # Upload metadata for the UI; the storage key itself is never exposed.
    file_name: Mapped[str] = mapped_column(Text, nullable=False, server_default="resume")
    content_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="application/octet-stream"
    )
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = created_at_column()

    user: Mapped[User] = relationship(back_populates="resumes")
    versions: Mapped[list[ResumeVersion]] = relationship(
        back_populates="resume",
        cascade="all, delete-orphan",
        order_by="ResumeVersion.version_number",
    )

    def __repr__(self) -> str:
        return f"<Resume id={self.id} user_id={self.user_id}>"


class ResumeVersion(Base):
    """One parse of a resume. Re-parsing (e.g. after a parser upgrade) adds a new version."""

    __tablename__ = "resume_versions"

    id: Mapped[uuid.UUID] = uuid_pk()
    resume_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("resumes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parsed_skills: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}"
    )
    parsed_education: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    parsed_experience: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    parsed_projects: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    version_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    created_at: Mapped[datetime] = created_at_column()

    resume: Mapped[Resume] = relationship(back_populates="versions")
    applications: Mapped[list[Application]] = relationship(back_populates="resume_version")

    def __repr__(self) -> str:
        return f"<ResumeVersion id={self.id} resume_id={self.resume_id} v{self.version_number}>"
