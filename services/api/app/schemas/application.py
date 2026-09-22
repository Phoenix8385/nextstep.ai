"""Request/response bodies for ``/applications``."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.base import ApplicationStatus
from app.schemas.job import JobSummary

STATUS_VALUES = tuple(s.value for s in ApplicationStatus)


def _validate_status(value: str) -> str:
    if value not in STATUS_VALUES:
        msg = f"status must be one of {', '.join(STATUS_VALUES)}"
        raise ValueError(msg)
    return value


class ApplicationCreate(BaseModel):
    """Body for ``POST /applications``: create, or move an existing application to ``status``."""

    job_id: uuid.UUID
    resume_version_id: uuid.UUID | None = None
    status: str = Field(default=ApplicationStatus.APPLIED.value, examples=["applied"])
    notes: str | None = Field(default=None, max_length=5000)

    _check_status = field_validator("status")(_validate_status)


class ApplicationStatusUpdate(BaseModel):
    """Body for ``PATCH /applications/{id}/status``."""

    status: str = Field(..., examples=["interview"])
    notes: str | None = Field(default=None, max_length=5000)
    follow_up_date: date | None = None

    _check_status = field_validator("status")(_validate_status)


class ApplicationEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    event_time: datetime
    details: str | None


class ApplicationResponse(BaseModel):
    """An application with its job and full event history."""

    id: uuid.UUID
    job: JobSummary
    status: str
    match_score: Decimal | None
    resume_version_id: uuid.UUID | None
    applied_at: datetime | None
    notes: str | None
    follow_up_date: date | None
    created_at: datetime
    updated_at: datetime
    events: list[ApplicationEventResponse]
