"""Greenhouse Job Board API adapter.

``GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true``
returns every live posting with an HTML-escaped ``content`` body. The board's
display name comes from ``GET /v1/boards/{board_token}`` and is only fetched
when the caller does not already know the company name.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Final

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from app.services.ingestion.http import (
    BoardNotFoundError,
    FetchError,
    describe_validation_error,
    fallback_company_name,
    get_json,
    make_http_client,
)
from app.services.ingestion.schema import NormalizedJob
from app.services.ingestion.skill_extractor import extract_skills
from app.services.ingestion.text import extract_requirements, html_to_text

logger = logging.getLogger(__name__)

SOURCE_NAME: Final[str] = "greenhouse"
BOARD_URL: Final[str] = "https://boards-api.greenhouse.io/v1/boards/{board_token}"
JOBS_URL: Final[str] = BOARD_URL + "/jobs"


class GreenhouseLocation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None


class RawGreenhouseJob(BaseModel):
    """The subset of a Greenhouse job object that we consume, as returned by the API.

    ``company_name`` is not part of the API payload; :func:`fetch_greenhouse`
    stamps it on each job so :func:`normalize_greenhouse` needs nothing else.
    """

    model_config = ConfigDict(extra="ignore")

    id: int
    title: str
    absolute_url: str
    content: str | None = None
    location: GreenhouseLocation | None = None
    updated_at: datetime | None = None
    first_published: datetime | None = None
    company_name: str | None = None


class _JobsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    jobs: list[RawGreenhouseJob]


class _Board(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None


async def fetch_greenhouse(
    board_token: str,
    *,
    company_name: str | None = None,
    http: httpx.AsyncClient | None = None,
) -> list[RawGreenhouseJob]:
    """Return every live posting on a Greenhouse board.

    Transient failures (network, 429, 5xx) are retried with exponential
    backoff by :func:`get_json`. A 404 raises :class:`BoardNotFoundError`;
    a payload that does not match the expected shape raises :class:`FetchError`.
    """
    owns_client = http is None
    client = http or make_http_client()
    try:
        company = company_name or await _board_name(client, board_token)
        payload = await get_json(
            client,
            JOBS_URL.format(board_token=board_token),
            source=SOURCE_NAME,
            board_token=board_token,
            params={"content": "true"},
        )
        try:
            parsed = _JobsResponse.model_validate(payload)
        except ValidationError as exc:
            raise FetchError(SOURCE_NAME, board_token, describe_validation_error(exc)) from exc
    finally:
        if owns_client:
            await client.aclose()

    company = company or fallback_company_name(board_token)
    jobs = [job.model_copy(update={"company_name": company}) for job in parsed.jobs]
    logger.info("greenhouse/%s: fetched %d postings", board_token, len(jobs))
    return jobs


async def _board_name(http: httpx.AsyncClient, board_token: str) -> str | None:
    """Board display name, or ``None`` if the metadata call fails (never fatal)."""
    try:
        payload = await get_json(
            http,
            BOARD_URL.format(board_token=board_token),
            source=SOURCE_NAME,
            board_token=board_token,
            retries=0,
        )
        return _Board.model_validate(payload).name
    except BoardNotFoundError:
        raise  # the jobs call would 404 too; fail fast with the clearer error
    except (FetchError, ValidationError):
        logger.warning("greenhouse/%s: could not read board name", board_token, exc_info=True)
        return None


def normalize_greenhouse(raw: RawGreenhouseJob) -> NormalizedJob:
    """Map a raw Greenhouse job onto :class:`NormalizedJob`.

    ``content`` arrives as HTML-escaped HTML; it is decoded and flattened to
    plain text for ``description``. ``work_mode`` / ``experience_level`` are
    inferred by the model from location and title.
    """
    description = html_to_text(raw.content)
    location = raw.location.name if raw.location else None
    return NormalizedJob(
        external_job_id=str(raw.id),
        source_url=raw.absolute_url,
        company_name=raw.company_name or "",
        title=raw.title,
        location=location,
        description=description,
        requirements=extract_requirements(description),
        posted_at=raw.first_published or raw.updated_at,
        required_skills=extract_skills(raw.title, description),
    )
