"""Job discovery: filtered, paginated listing and detail view.

These endpoints are public — anyone can browse postings. Anything that ties a
job to a user (saving, applying, match scores) lives behind ``CurrentUser``.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import Select, func, select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, DbSession
from app.models.job import Job
from app.models.resume import ResumeVersion
from app.models.user import UserProfile
from app.schemas.job import (
    AnalyzeRequest,
    AnalyzeResponse,
    JobDetail,
    JobFilters,
    JobPage,
    JobSummary,
)
from app.services.matching import compute_match

router = APIRouter(prefix="/jobs", tags=["jobs"])


def apply_job_filters(stmt: Select[tuple[Job]], filters: JobFilters) -> Select[tuple[Job]]:
    """Append WHERE clauses for every filter the client supplied.

    Kept separate from the endpoint so the generated SQL can be unit-tested
    without a database.
    """
    if filters.role:
        stmt = stmt.where(Job.title.ilike(f"%{_escape_like(filters.role)}%", escape="\\"))
    if filters.company:
        stmt = stmt.where(Job.company_name.ilike(f"%{_escape_like(filters.company)}%", escape="\\"))
    if filters.location:
        stmt = stmt.where(Job.location.ilike(f"%{_escape_like(filters.location)}%", escape="\\"))
    if filters.work_mode:
        stmt = stmt.where(func.lower(Job.work_mode) == filters.work_mode.lower())
    if filters.experience_level:
        stmt = stmt.where(func.lower(Job.experience_level) == filters.experience_level.lower())
    if filters.posted_after is not None:
        stmt = stmt.where(Job.posted_at >= filters.posted_after)
    if filters.has_deadline is True:
        stmt = stmt.where(Job.deadline.is_not(None))
    elif filters.has_deadline is False:
        stmt = stmt.where(Job.deadline.is_(None))
    return stmt


def _escape_like(value: str) -> str:
    """Escape LIKE wildcards so user input matches literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("", response_model=JobPage)
async def list_jobs(filters: Annotated[JobFilters, Query()], db: DbSession) -> JobPage:
    """Return active jobs matching the filters, newest-detected first."""
    base = apply_job_filters(select(Job).where(Job.is_active.is_(True)), filters)

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()

    rows = await db.execute(
        base.order_by(Job.detected_at.desc(), Job.id.desc())
        .offset(filters.offset)
        .limit(filters.page_size)
    )
    now = datetime.now(UTC)
    items = [JobSummary.from_job(job, now=now) for job in rows.scalars().all()]
    return JobPage.build(items, filters=filters, total=total)


@router.get(
    "/{job_id}",
    response_model=JobDetail,
    responses={status.HTTP_404_NOT_FOUND: {"description": "Job not found"}},
)
async def get_job(job_id: uuid.UUID, db: DbSession) -> JobDetail:
    """Return the full record for one job (inactive jobs included, flagged by ``is_active``)."""
    job = await db.get(Job, job_id, options=[selectinload(Job.source)])
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return JobDetail.from_job(job, now=datetime.now(UTC))


@router.post(
    "/{job_id}/analyze",
    response_model=AnalyzeResponse,
    responses={status.HTTP_404_NOT_FOUND: {"description": "Job or resume version not found"}},
)
async def analyze_job(
    job_id: uuid.UUID, body: AnalyzeRequest, user: CurrentUser, db: DbSession
) -> AnalyzeResponse:
    """Score the user's parsed resume against this job (transparent skill overlap, ADR 003).

    Nothing is persisted; the same computation runs again when the user
    records an application with this resume version.
    """
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    version = await db.get(
        ResumeVersion, body.resume_version_id, options=[selectinload(ResumeVersion.resume)]
    )
    if version is None or version.resume.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Resume version not found"
        )

    profile = await db.get(UserProfile, user.id)
    result = compute_match(version.parsed_skills, job, profile, now=datetime.now(UTC))
    return AnalyzeResponse(
        job_id=job.id,
        resume_version_id=version.id,
        profile_on_file=profile is not None,
        **result.model_dump(),
    )
