"""Query parameters and response bodies for ``/jobs`` and ``/saved-jobs``."""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.job import Job
from app.services.matching import MatchResult

NEW_JOB_WINDOW: Final[timedelta] = timedelta(hours=2)
"""A job is flagged ``is_new`` when it was detected within this window."""

DEFAULT_PAGE_SIZE: Final[int] = 20
MAX_PAGE_SIZE: Final[int] = 100


class JobFilters(BaseModel):
    """Query parameters accepted by ``GET /jobs``.

    Text filters are case-insensitive substring matches; ``work_mode`` and
    ``experience_level`` are case-insensitive exact matches.
    """

    role: str | None = Field(default=None, min_length=1, max_length=200)
    company: str | None = Field(default=None, min_length=1, max_length=200)
    location: str | None = Field(default=None, min_length=1, max_length=200)
    work_mode: str | None = Field(default=None, min_length=1, max_length=50)
    experience_level: str | None = Field(default=None, min_length=1, max_length=50)
    posted_after: datetime | None = None
    has_deadline: bool | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)

    @field_validator("posted_after")
    @classmethod
    def _ensure_timezone(cls, value: datetime | None) -> datetime | None:
        """Treat naive timestamps as UTC so they compare cleanly with TIMESTAMPTZ."""
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    @property
    def offset(self) -> int:
        """Row offset for the requested page."""
        return (self.page - 1) * self.page_size


class JobSummary(BaseModel):
    """List-view representation of a job (no long-text fields)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_name: str
    title: str
    location: str | None
    work_mode: str | None
    experience_level: str | None
    required_skills: list[str]
    source_url: str
    posted_at: datetime | None
    detected_at: datetime
    deadline: datetime | None
    is_active: bool
    is_new: bool = Field(description=f"Detected within the last {NEW_JOB_WINDOW}")

    @classmethod
    def from_job(cls, job: Job, *, now: datetime) -> JobSummary:
        """Build from an ORM row, computing ``is_new`` relative to ``now``."""
        return cls(
            id=job.id,
            company_name=job.company_name,
            title=job.title,
            location=job.location,
            work_mode=job.work_mode,
            experience_level=job.experience_level,
            required_skills=list(job.required_skills),
            source_url=job.source_url,
            posted_at=job.posted_at,
            detected_at=job.detected_at,
            deadline=job.deadline,
            is_active=job.is_active,
            is_new=is_new(job.detected_at, now=now),
        )


class JobDetail(JobSummary):
    """Full job record for ``GET /jobs/{id}``."""

    external_job_id: str
    source_name: str
    description: str | None
    requirements: str | None
    eligibility: str | None
    updated_at: datetime

    @classmethod
    def from_job(cls, job: Job, *, now: datetime) -> JobDetail:
        """Build from an ORM row; ``job.source`` must already be loaded."""
        summary = JobSummary.from_job(job, now=now)
        return cls(
            **summary.model_dump(),
            external_job_id=job.external_job_id,
            source_name=job.source.name,
            description=job.description,
            requirements=job.requirements,
            eligibility=job.eligibility,
            updated_at=job.updated_at,
        )


class JobPage(BaseModel):
    """Paginated ``GET /jobs`` response."""

    items: list[JobSummary]
    page: int
    page_size: int
    total: int
    total_pages: int
    has_next: bool

    @classmethod
    def build(cls, items: list[JobSummary], *, filters: JobFilters, total: int) -> JobPage:
        """Compute pagination metadata from the applied filters and total row count."""
        total_pages = math.ceil(total / filters.page_size) if total else 0
        return cls(
            items=items,
            page=filters.page,
            page_size=filters.page_size,
            total=total,
            total_pages=total_pages,
            has_next=filters.page < total_pages,
        )


class SavedJobResponse(BaseModel):
    """A bookmark with its job embedded."""

    id: uuid.UUID
    saved_at: datetime
    job: JobSummary


def is_new(detected_at: datetime, *, now: datetime) -> bool:
    """True when ``detected_at`` falls within :data:`NEW_JOB_WINDOW` of ``now``."""
    return detected_at >= now - NEW_JOB_WINDOW


class AnalyzeRequest(BaseModel):
    """Body for ``POST /jobs/{id}/analyze``."""

    resume_version_id: uuid.UUID


class AnalyzeResponse(MatchResult):
    """A :class:`MatchResult` plus the ids it was computed from."""

    job_id: uuid.UUID
    resume_version_id: uuid.UUID
    profile_on_file: bool = Field(
        description="False when eligibility could not be assessed because the user has no profile"
    )
