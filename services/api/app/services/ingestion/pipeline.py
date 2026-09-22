"""Fetch → normalise → upsert, with change logging and deactivation.

Rules (see ADR 001):

* A posting is identified within its source by ``(source_id, external_job_id)``.
* ``content_hash`` (``title + company_name + location + description[:500]``)
  is the fast path: an unchanged hash **and** no differences in the other
  tracked fields means no-op. Fields outside the hash (``deadline``,
  ``required_skills``, ``posted_at`` …) are diffed explicitly, so a changed
  deadline is still detected and logged.
* A new posting whose ``content_hash`` is already active under a different
  source is a cross-board duplicate and is skipped.
* Every field change appends a ``job_change_log`` row. For ``description``
  only the fact that it changed is recorded, not the text.
* Active postings absent from a non-empty fetch are deactivated; an empty
  fetch is treated as an upstream fault and deactivates nothing.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal, Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionFactory, dispose_engine
from app.models.job import Job, JobChangeLog, JobSource
from app.services.ingestion import ashby, greenhouse, lever
from app.services.ingestion.http import FetchError
from app.services.ingestion.schema import NormalizedJob

logger = logging.getLogger(__name__)

UpsertOutcome = Literal["inserted", "updated", "unchanged"]

TRACKED_FIELDS: Final[tuple[str, ...]] = (
    "title",
    "location",
    "work_mode",
    "experience_level",
    "description",
    "requirements",
    "required_skills",
    "eligibility",
    "posted_at",
    "deadline",
    "source_url",
)
"""``jobs`` columns compared on re-fetch; a difference in any of them is logged."""

DESCRIPTION_CHANGED_MARKER: Final[str] = "changed"


class FetchFn(Protocol):
    """Signature shared by ``fetch_<source>`` functions."""

    def __call__(
        self,
        board_token: str,
        *,
        company_name: str | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> Awaitable[Sequence[Any]]: ...


@dataclass(frozen=True)
class SourceAdapter:
    """The fetch/normalise pair for one ATS."""

    fetch: FetchFn
    normalize: Callable[[Any], NormalizedJob]


SOURCES: Final[dict[str, SourceAdapter]] = {
    greenhouse.SOURCE_NAME: SourceAdapter(
        greenhouse.fetch_greenhouse, greenhouse.normalize_greenhouse
    ),
    lever.SOURCE_NAME: SourceAdapter(lever.fetch_lever, lever.normalize_lever),
    ashby.SOURCE_NAME: SourceAdapter(ashby.fetch_ashby, ashby.normalize_ashby),
}
"""``job_sources.name`` → adapter. Register new ATS integrations here."""


@dataclass
class IngestionStats:
    """Counts from one :func:`run_ingestion_for_source` run."""

    source_id: int
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    failed: int = 0
    deactivated: int = 0
    duplicates_skipped: int = 0
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """JSON-friendly form for Celery results and CLI output."""
        return asdict(self)


class SourceNotFoundError(LookupError):
    """``job_sources`` has no row with the requested id."""


# --------------------------------------------------------------------------- #
# Hashing / diffing
# --------------------------------------------------------------------------- #


def compute_content_hash(job: NormalizedJob) -> str:
    """SHA-256 of ``title + company_name + location + description[:500]``."""
    return job.content_hash


def stringify(value: Any) -> str | None:
    """Render a column value for ``job_change_log``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def _comparable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    if isinstance(value, list):
        return list(value)
    return value


def diff_fields(existing: Job, job: NormalizedJob) -> list[tuple[str, str | None, str | None]]:
    """``(field, old, new)`` for every tracked field that differs.

    ``description`` is reported as ``(None, "changed")`` rather than the text.
    """
    changes: list[tuple[str, str | None, str | None]] = []
    for field in TRACKED_FIELDS:
        old = getattr(existing, field)
        new = getattr(job, field)
        if _comparable(old) == _comparable(new):
            continue
        if field == "description":
            changes.append((field, None, DESCRIPTION_CHANGED_MARKER))
        else:
            changes.append((field, stringify(old), stringify(new)))
    return changes


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #


async def upsert_job(
    db: AsyncSession,
    source_id: int,
    job: NormalizedJob,
    *,
    now: datetime | None = None,
) -> UpsertOutcome:
    """Insert or update one posting; flushes but does not commit.

    Returns ``"inserted"`` for a new row, ``"unchanged"`` when the stored row
    already matches, and ``"updated"`` when fields changed (each change is
    written to ``job_change_log`` in the same transaction). A row that was
    inactive and reappears is reactivated and counts as ``"updated"``.
    """
    now = now or datetime.now(UTC)
    content_hash = compute_content_hash(job)

    existing = (
        await db.execute(
            select(Job).where(
                Job.source_id == source_id, Job.external_job_id == job.external_job_id
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        db.add(_new_row(source_id, job, content_hash, now))
        await db.flush()
        return "inserted"

    changes = diff_fields(existing, job)
    if existing.content_hash == content_hash and not changes and existing.is_active:
        return "unchanged"

    if not existing.is_active:
        existing.is_active = True
        changes.append(("is_active", "False", "True"))

    for field in TRACKED_FIELDS:
        value = getattr(job, field)
        setattr(existing, field, list(value) if isinstance(value, list) else value)
    existing.company_name = job.company_name
    existing.content_hash = content_hash
    existing.updated_at = now

    for field, old, new in changes:
        db.add(
            JobChangeLog(
                job=existing, field_changed=field, old_value=old, new_value=new, changed_at=now
            )
        )
    await db.flush()
    return "updated"


def _new_row(source_id: int, job: NormalizedJob, content_hash: str, now: datetime) -> Job:
    return Job(
        source_id=source_id,
        external_job_id=job.external_job_id,
        source_url=job.source_url,
        company_name=job.company_name,
        title=job.title,
        location=job.location,
        work_mode=job.work_mode,
        experience_level=job.experience_level,
        description=job.description,
        requirements=job.requirements,
        required_skills=list(job.required_skills),
        eligibility=job.eligibility,
        posted_at=job.posted_at,
        detected_at=now,
        deadline=job.deadline,
        content_hash=content_hash,
        is_active=True,
        updated_at=now,
    )


async def _is_cross_source_duplicate(db: AsyncSession, source_id: int, content_hash: str) -> bool:
    stmt = (
        select(Job.id)
        .where(
            Job.content_hash == content_hash, Job.source_id != source_id, Job.is_active.is_(True)
        )
        .limit(1)
    )
    return (await db.execute(stmt)).first() is not None


async def sync_jobs(
    db: AsyncSession,
    source: JobSource,
    jobs: Sequence[NormalizedJob],
    *,
    stats: IngestionStats | None = None,
    now: datetime | None = None,
) -> IngestionStats:
    """Upsert every posting for ``source``, deactivate the missing ones, and commit.

    Each upsert runs in a savepoint so one bad row cannot poison the batch;
    failures are counted in ``stats.failed`` and logged.
    """
    now = now or datetime.now(UTC)
    stats = stats or IngestionStats(source_id=source.id, fetched=len(jobs))

    existing_ids = set(
        (await db.execute(select(Job.external_job_id).where(Job.source_id == source.id)))
        .scalars()
        .all()
    )

    seen: set[str] = set()
    for job in jobs:
        if job.external_job_id in seen:
            continue  # duplicate within one payload; first occurrence wins
        seen.add(job.external_job_id)
        try:
            async with db.begin_nested():
                is_new = job.external_job_id not in existing_ids
                if is_new and await _is_cross_source_duplicate(db, source.id, job.content_hash):
                    stats.duplicates_skipped += 1
                    continue
                outcome = await upsert_job(db, source.id, job, now=now)
        except Exception:
            stats.failed += 1
            logger.exception(
                "%s/%s: failed to upsert %s", source.name, source.board_token, job.external_job_id
            )
            continue
        setattr(stats, outcome, getattr(stats, outcome) + 1)

    stats.deactivated = await _deactivate_missing(db, source, seen, now)
    source.last_fetched_at = now
    await db.commit()
    logger.info("%s/%s: %s", source.name, source.board_token, stats.as_dict())
    return stats


async def _deactivate_missing(
    db: AsyncSession, source: JobSource, seen: set[str], now: datetime
) -> int:
    active = (
        (await db.execute(select(Job).where(Job.source_id == source.id, Job.is_active.is_(True))))
        .scalars()
        .all()
    )
    missing = [job for job in active if job.external_job_id not in seen]
    if missing and not seen:
        # An empty payload almost always means an upstream outage, not 0 open roles.
        logger.warning(
            "%s/%s: empty fetch with %d active jobs — skipping deactivation",
            source.name,
            source.board_token,
            len(missing),
        )
        return 0
    for job in missing:
        job.is_active = False
        job.updated_at = now
        db.add(
            JobChangeLog(
                job=job,
                field_changed="is_active",
                old_value="True",
                new_value="False",
                changed_at=now,
            )
        )
    return len(missing)


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


async def run_ingestion_for_source(
    db: AsyncSession,
    source: JobSource,
    *,
    http: httpx.AsyncClient | None = None,
) -> IngestionStats:
    """Fetch ``source``'s board, normalise every posting and sync it.

    Never raises for upstream problems: a failed fetch (after retries) or a
    malformed payload is reported in ``stats.error`` and the database is left
    untouched; individual postings that fail to normalise are counted in
    ``stats.failed`` and skipped.
    """
    stats = IngestionStats(source_id=source.id)
    adapter = SOURCES.get(source.name.lower())
    if adapter is None:
        stats.error = f"unknown job source {source.name!r}; known: {sorted(SOURCES)}"
        logger.error(stats.error)
        return stats

    try:
        raws = await adapter.fetch(source.board_token, company_name=source.company_name, http=http)
    except FetchError as exc:
        stats.error = str(exc)
        logger.warning("%s/%s: fetch failed: %s", source.name, source.board_token, exc.reason)
        return stats
    stats.fetched = len(raws)

    jobs: list[NormalizedJob] = []
    for raw in raws:
        try:
            jobs.append(adapter.normalize(raw))
        except Exception:
            stats.failed += 1
            logger.exception(
                "%s/%s: could not normalise a posting", source.name, source.board_token
            )

    return await sync_jobs(db, source, jobs, stats=stats)


async def run_ingestion_by_id(source_id: int) -> IngestionStats:
    """Ingest one ``job_sources`` row by id on a fresh session; releases the pool afterwards.

    Designed for ``asyncio.run()`` inside a Celery task: each call runs on its
    own event loop, so the engine is disposed to avoid reusing connections
    bound to a closed loop.
    """
    try:
        async with AsyncSessionFactory() as db:
            source = await db.get(JobSource, source_id)
            if source is None:
                raise SourceNotFoundError(f"job_sources.id={source_id} does not exist")
            return await run_ingestion_for_source(db, source)
    finally:
        await dispose_engine()


async def list_active_source_ids() -> list[int]:
    """Ids of every ``job_sources`` row with ``is_active = true``."""
    try:
        async with AsyncSessionFactory() as db:
            rows = await db.execute(
                select(JobSource.id).where(JobSource.is_active.is_(True)).order_by(JobSource.id)
            )
            return [row[0] for row in rows.all()]
    finally:
        await dispose_engine()
