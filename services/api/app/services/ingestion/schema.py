"""The single normalised posting shape every job-board adapter emits.

``normalize_<source>()`` functions translate each ATS's raw JSON into
:class:`NormalizedJob`; the pipeline only ever sees this type, so adding a
fourth source never touches persistence. ``work_mode`` and
``experience_level`` are inferred automatically when an adapter leaves them
unset, using the location text and title keywords respectively.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from app.core.hashing import compute_content_hash

WorkMode = Literal["remote", "hybrid", "onsite"]
ExperienceLevel = Literal["intern", "entry_level", "experienced"]


class NormalizedJob(BaseModel):
    """A posting in the shape of the ``jobs`` table, before persistence."""

    model_config = ConfigDict(frozen=True)

    external_job_id: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    company_name: str = Field(min_length=1)
    title: str = Field(min_length=1)
    location: str | None = None
    work_mode: WorkMode | None = None
    experience_level: ExperienceLevel | None = None
    description: str | None = None
    requirements: str | None = None
    posted_at: datetime | None = None
    deadline: datetime | None = None
    required_skills: list[str] = Field(default_factory=list)
    eligibility: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _infer_missing(cls, data: Any) -> Any:
        """Fill ``work_mode`` from location text and ``experience_level`` from the title."""
        if not isinstance(data, dict):
            return data
        # Local import: text.py imports the Literal types defined above.
        from app.services.ingestion.text import infer_experience_level, infer_work_mode

        filled = dict(data)
        title = filled.get("title")
        if filled.get("work_mode") is None:
            filled["work_mode"] = infer_work_mode(
                location=filled.get("location"),
                title=title if isinstance(title, str) else None,
                description=filled.get("description"),
            )
        if filled.get("experience_level") is None and isinstance(title, str):
            filled["experience_level"] = infer_experience_level(title=title)
        return filled

    @field_validator("title", "company_name", "external_job_id")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("location", "description", "requirements", "eligibility")
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("posted_at", "deadline")
    @classmethod
    def _ensure_utc(cls, value: datetime | None) -> datetime | None:
        """Boards report timestamps with mixed offsets; store everything as aware UTC."""
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @field_validator("required_skills")
    @classmethod
    def _dedupe_skills(cls, value: list[str], info: ValidationInfo) -> list[str]:
        """De-duplicate case-insensitively and drop a skill that is just the employer's name.

        A design tool called "Figma" is a real skill, but every Figma posting
        mentioning its own company is not evidence the role requires it.
        """
        company = str(info.data.get("company_name") or "").strip().lower()
        seen: set[str] = set()
        out: list[str] = []
        for skill in value:
            key = skill.strip().lower()
            if key and key != company and key not in seen:
                seen.add(key)
                out.append(skill.strip())
        return out

    @property
    def content_hash(self) -> str:
        """Dedupe key, identical to the persisted ``jobs.content_hash`` column."""
        return compute_content_hash(
            title=self.title,
            company_name=self.company_name,
            location=self.location,
            description=self.description,
        )
