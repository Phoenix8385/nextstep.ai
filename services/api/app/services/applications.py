"""Application tracker mutations.

Invariant (see ADR 004 and the architecture notes): **every status change
inserts an ``application_events`` row in the same transaction** as the
``applications`` update. Routers call these helpers and commit once; they
never set ``Application.status`` directly.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import Application, ApplicationEvent
from app.models.base import ApplicationEventType, ApplicationStatus

VALID_STATUSES: frozenset[str] = frozenset(s.value for s in ApplicationStatus)
APPLIED_STATUSES: frozenset[str] = frozenset(
    {ApplicationStatus.APPLIED.value, ApplicationStatus.APPLIED_PENDING_CONFIRMATION.value}
)


class InvalidStatusError(ValueError):
    """``status`` is not one of :class:`ApplicationStatus`."""


def validate_status(value: str) -> str:
    """Return ``value`` if it is a known status, else raise :class:`InvalidStatusError`."""
    if value not in VALID_STATUSES:
        msg = f"unknown status {value!r}; expected one of {sorted(VALID_STATUSES)}"
        raise InvalidStatusError(msg)
    return value


async def get_application_for_job(
    db: AsyncSession, user_id: uuid.UUID, job_id: uuid.UUID
) -> Application | None:
    """The user's application for ``job_id``, if one exists."""
    return (
        await db.execute(
            select(Application).where(Application.user_id == user_id, Application.job_id == job_id)
        )
    ).scalar_one_or_none()


def record_event(
    db: AsyncSession,
    application: Application,
    event_type: ApplicationEventType,
    *,
    details: str | None = None,
    now: datetime | None = None,
) -> ApplicationEvent:
    """Append an audit row to the *current* transaction (no commit)."""
    event = ApplicationEvent(
        application=application,
        event_type=event_type.value,
        event_time=now or datetime.now(UTC),
        details=details,
    )
    db.add(event)
    return event


def set_status(
    db: AsyncSession,
    application: Application,
    new_status: str,
    *,
    details: str | None = None,
    now: datetime | None = None,
) -> ApplicationEvent | None:
    """Change ``application.status`` and log it; returns the event, or ``None`` if unchanged.

    Sets ``applied_at`` the first time the application reaches an applied status.
    """
    validate_status(new_status)
    now = now or datetime.now(UTC)
    if application.status == new_status:
        return None
    old = application.status
    application.status = new_status
    application.updated_at = now
    if new_status in APPLIED_STATUSES and application.applied_at is None:
        application.applied_at = now
    return record_event(
        db,
        application,
        ApplicationEventType.STATUS_CHANGED,
        details=details or f"{old} -> {new_status}",
        now=now,
    )


async def create_or_update_application(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    status: str,
    resume_version_id: uuid.UUID | None = None,
    notes: str | None = None,
    match_score: Decimal | None = None,
    now: datetime | None = None,
) -> tuple[Application, bool]:
    """Create the user's application for ``job_id`` or move the existing one to ``status``.

    Returns ``(application, created)``. Both paths write their events in the
    same transaction; the caller commits.
    """
    validate_status(status)
    now = now or datetime.now(UTC)
    application = await get_application_for_job(db, user_id, job_id)

    if application is None:
        application = Application(
            user_id=user_id,
            job_id=job_id,
            resume_version_id=resume_version_id,
            status=status,
            match_score=match_score,
            notes=notes,
            applied_at=now if status in APPLIED_STATUSES else None,
            created_at=now,
            updated_at=now,
        )
        db.add(application)
        record_event(
            db, application, ApplicationEventType.CREATED, details=f"status={status}", now=now
        )
        await db.flush()
        return application, True

    set_status(db, application, status, now=now)
    if resume_version_id is not None and application.resume_version_id != resume_version_id:
        application.resume_version_id = resume_version_id
        record_event(
            db,
            application,
            ApplicationEventType.RESUME_ATTACHED,
            details=str(resume_version_id),
            now=now,
        )
    if match_score is not None:
        application.match_score = match_score
    if notes is not None and notes != application.notes:
        application.notes = notes
        record_event(db, application, ApplicationEventType.NOTE_ADDED, details=notes[:500], now=now)
    application.updated_at = now
    await db.flush()
    return application, False
