"""Ashby Job Posting API adapter.

``GET https://api.ashbyhq.com/posting-api/job-board/{board_name}`` returns
``{"jobs": [...]}`` with HTML and plain-text bodies, an ``isRemote`` flag and
an ``isListed`` flag (unlisted postings are excluded from the public board).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Final

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.services.ingestion.http import (
    FetchError,
    describe_validation_error,
    fallback_company_name,
    get_json,
    make_http_client,
)
from app.services.ingestion.schema import NormalizedJob
from app.services.ingestion.skill_extractor import extract_skills
from app.services.ingestion.text import (
    extract_requirements,
    html_to_text,
    infer_experience_level,
    infer_work_mode,
)

logger = logging.getLogger(__name__)

SOURCE_NAME: Final[str] = "ashby"
JOB_BOARD_URL: Final[str] = "https://api.ashbyhq.com/posting-api/job-board/{board}"


class AshbySecondaryLocation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    location: str | None = None


class RawAshbyJob(BaseModel):
    """The subset of an Ashby job posting that we consume (camelCase mapped via aliases)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    title: str
    job_url: str = Field(alias="jobUrl")
    apply_url: str | None = Field(default=None, alias="applyUrl")
    location: str | None = None
    secondary_locations: list[AshbySecondaryLocation] = Field(
        default_factory=list, alias="secondaryLocations"
    )
    is_remote: bool | None = Field(default=None, alias="isRemote")
    is_listed: bool = Field(default=True, alias="isListed")
    employment_type: str | None = Field(default=None, alias="employmentType")
    published_at: datetime | None = Field(default=None, alias="publishedAt")
    description_html: str | None = Field(default=None, alias="descriptionHtml")
    description_plain: str | None = Field(default=None, alias="descriptionPlain")
    company_name: str | None = None  # stamped by fetch_ashby; not in the API payload


class _BoardResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    jobs: list[RawAshbyJob]


async def fetch_ashby(
    board_token: str,
    *,
    company_name: str | None = None,
    http: httpx.AsyncClient | None = None,
) -> list[RawAshbyJob]:
    """Return every *listed* posting on an Ashby board (retries via :func:`get_json`)."""
    owns_client = http is None
    client = http or make_http_client()
    try:
        payload = await get_json(
            client,
            JOB_BOARD_URL.format(board=board_token),
            source=SOURCE_NAME,
            board_token=board_token,
        )
    finally:
        if owns_client:
            await client.aclose()

    try:
        parsed = _BoardResponse.model_validate(payload)
    except ValidationError as exc:
        raise FetchError(SOURCE_NAME, board_token, describe_validation_error(exc)) from exc

    company = company_name or fallback_company_name(board_token)  # Ashby exposes no org name
    listed = [j.model_copy(update={"company_name": company}) for j in parsed.jobs if j.is_listed]
    logger.info(
        "ashby/%s: fetched %d postings (%d unlisted skipped)",
        board_token,
        len(listed),
        len(parsed.jobs) - len(listed),
    )
    return listed


def normalize_ashby(raw: RawAshbyJob) -> NormalizedJob:
    """Map a raw Ashby job onto :class:`NormalizedJob`."""
    # Prefer the HTML body: it preserves list structure the plain variant flattens.
    description = html_to_text(raw.description_html) or raw.description_plain
    location = raw.location or next(
        (loc.location for loc in raw.secondary_locations if loc.location), None
    )
    return NormalizedJob(
        external_job_id=raw.id,
        source_url=raw.job_url,
        company_name=raw.company_name or "",
        title=raw.title,
        location=location,
        work_mode=infer_work_mode(
            location=location,
            title=raw.title,
            description=description,
            hint="remote" if raw.is_remote else None,
        ),
        experience_level=infer_experience_level(title=raw.title, hint=raw.employment_type),
        description=description,
        requirements=extract_requirements(description),
        posted_at=raw.published_at,
        required_skills=extract_skills(raw.title, description),
    )
