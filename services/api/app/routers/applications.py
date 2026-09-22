"""Application tracker (manual status updates, ADR 004).

All writes go through :mod:`app.services.applications`, which guarantees an
``application_events`` row accompanies every status change in the same
transaction. Users apply on the employer's site (ADR 002); this API only
records what they tell us.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, DbSession
from app.models.application import Application
from app.models.base import ApplicationEventType
from app.models.job import Job
from app.models.resume import ResumeVersion
from app.models.user import User, UserProfile
from app.schemas.application import (
    ApplicationCreate,
    ApplicationEventResponse,
    ApplicationResponse,
    ApplicationStatusUpdate,
)
from app.schemas.job import JobSummary
from app.services.applications import (
    create_or_update_application,
    record_event,
    set_status,
)
from app.services.matching import compute_match

router = APIRouter(prefix="/applications", tags=["applications"])


def _to_response(application: Application, *, now: datetime) -> ApplicationResponse:
    return ApplicationResponse(
        id=application.id,
        job=JobSummary.from_job(application.job, now=now),
        status=application.status,
        match_score=application.match_score,
        resume_version_id=application.resume_version_id,
        applied_at=application.applied_at,
        notes=application.notes,
        follow_up_date=application.follow_up_date,
        created_at=application.created_at,
        updated_at=application.updated_at,
        events=[ApplicationEventResponse.model_validate(e) for e in application.events],
    )


async def _load(db: DbSession, application_id: uuid.UUID, user: User) -> Application:
    application = await db.get(
        Application,
        application_id,
        options=[selectinload(Application.job), selectinload(Application.events)],
    )
    if application is None or application.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return application


async def _owned_resume_version(
    db: DbSession, version_id: uuid.UUID | None, user: User
) -> ResumeVersion | None:
    if version_id is None:
        return None
    version = await db.get(ResumeVersion, version_id, options=[selectinload(ResumeVersion.resume)])
    if version is None or version.resume.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Resume version not found"
        )
    return version


@router.post(
    "",
    response_model=ApplicationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_200_OK: {
            "model": ApplicationResponse,
            "description": "Existing application updated",
        },
        status.HTTP_404_NOT_FOUND: {"description": "Job or resume version not found"},
    },
)
async def create_application(
    body: ApplicationCreate, user: CurrentUser, db: DbSession, response: Response
) -> ApplicationResponse:
    """Record that the user applied (or saved) a job.

    Creates the application if none exists for this job (201), otherwise
    moves the existing one to ``status`` (200). When a resume version is
    supplied, the transparent match score is computed and stored with it.
    """
    job = await db.get(Job, body.job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    version = await _owned_resume_version(db, body.resume_version_id, user)

    match_score: Decimal | None = None
    if version is not None:
        profile = await db.get(UserProfile, user.id)
        match_score = Decimal(compute_match(version.parsed_skills, job, profile).match_score)

    now = datetime.now(UTC)
    application, created = await create_or_update_application(
        db,
        user_id=user.id,
        job_id=job.id,
        status=body.status,
        resume_version_id=body.resume_version_id,
        notes=body.notes,
        match_score=match_score,
        now=now,
    )
    await db.commit()
    await db.refresh(application, attribute_names=["job", "events"])
    if not created:
        response.status_code = status.HTTP_200_OK
    return _to_response(application, now=now)


@router.get("", response_model=list[ApplicationResponse])
async def list_applications(user: CurrentUser, db: DbSession) -> list[ApplicationResponse]:
    """The current user's applications, most recently updated first."""
    result = await db.execute(
        select(Application)
        .options(selectinload(Application.job), selectinload(Application.events))
        .where(Application.user_id == user.id)
        .order_by(Application.updated_at.desc(), Application.id.desc())
    )
    now = datetime.now(UTC)
    return [_to_response(a, now=now) for a in result.scalars().all()]


@router.get(
    "/{application_id}",
    response_model=ApplicationResponse,
    responses={status.HTTP_404_NOT_FOUND: {"description": "Application not found"}},
)
async def get_application(
    application_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> ApplicationResponse:
    """One application with its full event history."""
    application = await _load(db, application_id, user)
    return _to_response(application, now=datetime.now(UTC))


@router.patch(
    "/{application_id}/status",
    response_model=ApplicationResponse,
    responses={status.HTTP_404_NOT_FOUND: {"description": "Application not found"}},
)
async def update_status(
    application_id: uuid.UUID,
    body: ApplicationStatusUpdate,
    user: CurrentUser,
    db: DbSession,
) -> ApplicationResponse:
    """Move an application to a new status (and optionally update notes / follow-up date).

    The status change and its ``application_events`` row are committed together.
    """
    application = await _load(db, application_id, user)
    now = datetime.now(UTC)

    set_status(db, application, body.status, now=now)
    if body.notes is not None and body.notes != application.notes:
        application.notes = body.notes
        record_event(
            db, application, ApplicationEventType.NOTE_ADDED, details=body.notes[:500], now=now
        )
    if body.follow_up_date is not None and body.follow_up_date != application.follow_up_date:
        application.follow_up_date = body.follow_up_date
        record_event(
            db,
            application,
            ApplicationEventType.FOLLOW_UP_SET,
            details=body.follow_up_date.isoformat(),
            now=now,
        )
    application.updated_at = now
    await db.commit()
    await db.refresh(application, attribute_names=["job", "events"])
    return _to_response(application, now=now)
