"""Lever Postings API adapter.

``GET https://api.lever.co/v0/postings/{company}?mode=json`` returns a JSON
array of postings. Each carries the body as both HTML and plain text, plus a
``lists`` array of titled sections (e.g. "Requirements") that fills
``requirements`` precisely instead of guessing from headings.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Final

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from app.services.ingestion.http import (
    FetchError,
    describe_validation_error,
    fallback_company_name,
    get_json,
    make_http_client,
)
from app.services.ingestion.schema import NormalizedJob
from app.services.ingestion.skill_extractor import extract_skills
from app.services.ingestion.text import html_to_text, infer_experience_level, infer_work_mode

logger = logging.getLogger(__name__)

SOURCE_NAME: Final[str] = "lever"
POSTINGS_URL: Final[str] = "https://api.lever.co/v0/postings/{company}"

_REQUIREMENTS_LIST_RE: Final[re.Pattern[str]] = re.compile(
    r"requirement|qualification|what you(?:'|\u2019)ll bring|about you|who you are|looking for",
    re.IGNORECASE,
)


class LeverCategories(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    location: str | None = None
    team: str | None = None
    commitment: str | None = None
    all_locations: list[str] = Field(default_factory=list, alias="allLocations")


class LeverList(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str
    content: str  # HTML fragment of <li> elements


class RawLeverPosting(BaseModel):
    """The subset of a Lever posting that we consume (camelCase mapped via aliases)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    text: str  # the title
    hosted_url: str = Field(alias="hostedUrl")
    apply_url: str | None = Field(default=None, alias="applyUrl")
    created_at: int | None = Field(default=None, alias="createdAt")  # epoch milliseconds
    categories: LeverCategories = Field(default_factory=LeverCategories)
    description: str | None = None
    description_plain: str | None = Field(default=None, alias="descriptionPlain")
    lists: list[LeverList] = Field(default_factory=list)
    additional: str | None = None
    additional_plain: str | None = Field(default=None, alias="additionalPlain")
    workplace_type: str | None = Field(default=None, alias="workplaceType")
    company_name: str | None = None  # stamped by fetch_lever; not in the API payload


_POSTINGS = TypeAdapter(list[RawLeverPosting])


async def fetch_lever(
    board_token: str,
    *,
    company_name: str | None = None,
    http: httpx.AsyncClient | None = None,
) -> list[RawLeverPosting]:
    """Return every live posting for a Lever company slug (retries via :func:`get_json`)."""
    owns_client = http is None
    client = http or make_http_client()
    try:
        payload = await get_json(
            client,
            POSTINGS_URL.format(company=board_token),
            source=SOURCE_NAME,
            board_token=board_token,
            params={"mode": "json"},
        )
    finally:
        if owns_client:
            await client.aclose()

    try:
        postings = _POSTINGS.validate_python(payload)
    except ValidationError as exc:
        raise FetchError(SOURCE_NAME, board_token, describe_validation_error(exc)) from exc

    company = company_name or fallback_company_name(board_token)  # Lever exposes no org name
    result = [p.model_copy(update={"company_name": company}) for p in postings]
    logger.info("lever/%s: fetched %d postings", board_token, len(result))
    return result


def normalize_lever(raw: RawLeverPosting) -> NormalizedJob:
    """Map a raw Lever posting onto :class:`NormalizedJob`.

    The description is assembled from the intro, every titled list, and the
    closing text; the first list whose title looks like "Requirements" also
    populates ``requirements``.
    """
    sections: list[str] = []
    requirements: str | None = None

    intro = raw.description_plain or html_to_text(raw.description)
    if intro:
        sections.append(intro)
    for item in raw.lists:
        body = html_to_text(f"<ul>{item.content}</ul>")
        if not body:
            continue
        sections.append(f"{item.text}\n{body}")
        if requirements is None and _REQUIREMENTS_LIST_RE.search(item.text):
            requirements = body
    outro = raw.additional_plain or html_to_text(raw.additional)
    if outro:
        sections.append(outro)
    description = "\n\n".join(sections) or None

    location = raw.categories.location or (
        raw.categories.all_locations[0] if raw.categories.all_locations else None
    )
    posted_at = (
        datetime.fromtimestamp(raw.created_at / 1000, tz=UTC)
        if raw.created_at is not None
        else None
    )
    return NormalizedJob(
        external_job_id=raw.id,
        source_url=raw.hosted_url,
        company_name=raw.company_name or "",
        title=raw.text,
        location=location,
        work_mode=infer_work_mode(
            location=location, title=raw.text, description=description, hint=raw.workplace_type
        ),
        experience_level=infer_experience_level(title=raw.text, hint=raw.categories.commitment),
        description=description,
        requirements=requirements,
        posted_at=posted_at,
        required_skills=extract_skills(raw.text, description),
    )
