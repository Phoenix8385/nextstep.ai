"""Shared column helpers and enumerations used across ORM models."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


def uuid_pk() -> Mapped[uuid.UUID]:
    """A ``uuid`` primary key column defaulting to ``uuid4()`` in Python."""
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def created_at_column() -> Mapped[datetime]:
    """A non-null ``TIMESTAMPTZ`` column defaulting to ``now()`` on the server."""
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def updated_at_column() -> Mapped[datetime]:
    """A ``TIMESTAMPTZ`` column set to ``now()`` on insert and refreshed on every update."""
    return mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ApplicationStatus(StrEnum):
    """Allowed values for ``applications.status``, in funnel order.

    Stored as plain ``text`` so new stages can be added without a migration;
    validated at the service layer, not by the database. Transitions are
    deliberately unconstrained — a user correcting a mistake (offer back to
    interview, rejected back to applied) is normal — but every change is
    logged to ``application_events``.
    """

    SAVED = "saved"
    APPLIED = "applied"
    ASSESSMENT = "assessment"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"


class ApplicationEventType(StrEnum):
    """Allowed values for ``application_events.event_type``."""

    CREATED = "created"
    STATUS_CHANGED = "status_changed"
    NOTE_ADDED = "note_added"
    FOLLOW_UP_SET = "follow_up_set"
    RESUME_ATTACHED = "resume_attached"
