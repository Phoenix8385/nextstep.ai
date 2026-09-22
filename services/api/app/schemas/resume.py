"""Response bodies for ``/resumes``."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ResumeVersionSummary(BaseModel):
    """What the list view needs from the latest parse."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_number: int
    parsed_skills: list[str]
    created_at: datetime


class ResumeVersionResponse(ResumeVersionSummary):
    """Full parse result for ``POST /resumes/{id}/parse``."""

    resume_id: uuid.UUID
    parsed_education: list[dict[str, Any]] | None
    parsed_experience: list[dict[str, Any]] | None
    parsed_projects: list[dict[str, Any]] | None
    raw_text_chars: int = Field(
        description="Length of the extracted text; the text itself is not returned"
    )


class ResumeResponse(BaseModel):
    """A resume file with its latest parsed version, if any."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    file_name: str
    content_type: str
    size_bytes: int
    created_at: datetime
    latest_version: ResumeVersionSummary | None = None
