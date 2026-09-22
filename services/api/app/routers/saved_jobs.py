"""Bookmarks (``saved_jobs``).

Routes span two prefixes — ``/jobs/{id}/save`` for the action and
``/saved-jobs`` for the collection — so this router has no prefix of its own.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, DbSession
from app.models.job import Job, SavedJob
from app.schemas.job import JobSummary, SavedJobResponse

router = APIRouter(tags=["saved-jobs"])


def _to_response(saved: SavedJob, job: Job, *, now: datetime) -> SavedJobResponse:
    return SavedJobResponse(
        id=saved.id,
        saved_at=saved.saved_at,
        job=JobSummary.from_job(job, now=now),
    )


@router.post(
    "/jobs/{job_id}/save",
    response_model=SavedJobResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_200_OK: {"model": SavedJobResponse, "description": "Already saved"},
        status.HTTP_404_NOT_FOUND: {"description": "Job not found"},
    },
)
async def save_job(
    job_id: uuid.UUID, user: CurrentUser, db: DbSession, response: Response
) -> SavedJobResponse:
    """Bookmark a job. Idempotent: saving twice returns the existing row with 200."""
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    existing = await _find_saved(db, user.id, job_id)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return _to_response(existing, job, now=datetime.now(UTC))

    saved = SavedJob(user_id=user.id, job_id=job_id)
    db.add(saved)
    try:
        await db.commit()
    except IntegrityError:
        # Concurrent save of the same job; the unique constraint won — return theirs.
        await db.rollback()
        raced = await _find_saved(db, user.id, job_id)
        if raced is None:  # pragma: no cover — constraint fired, row must exist
            raise
        response.status_code = status.HTTP_200_OK
        return _to_response(raced, job, now=datetime.now(UTC))

    await db.refresh(saved)
    return _to_response(saved, job, now=datetime.now(UTC))


@router.delete(
    "/jobs/{job_id}/save",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={status.HTTP_404_NOT_FOUND: {"description": "Job was not saved"}},
)
async def unsave_job(job_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    """Remove a bookmark."""
    result = await db.execute(
        delete(SavedJob).where(SavedJob.user_id == user.id, SavedJob.job_id == job_id)
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job was not saved")
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/saved-jobs", response_model=list[SavedJobResponse])
async def list_saved_jobs(user: CurrentUser, db: DbSession) -> list[SavedJobResponse]:
    """Return the current user's bookmarks, most recently saved first, with job details."""
    result = await db.execute(
        select(SavedJob)
        .options(selectinload(SavedJob.job))
        .where(SavedJob.user_id == user.id)
        .order_by(SavedJob.saved_at.desc(), SavedJob.id.desc())
    )
    now = datetime.now(UTC)
    return [_to_response(saved, saved.job, now=now) for saved in result.scalars().all()]


async def _find_saved(db: AsyncSession, user_id: uuid.UUID, job_id: uuid.UUID) -> SavedJob | None:
    result = await db.execute(
        select(SavedJob).where(SavedJob.user_id == user_id, SavedJob.job_id == job_id)
    )
    return result.scalar_one_or_none()
