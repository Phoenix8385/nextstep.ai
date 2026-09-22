"""Unit tests for the ingestion pipeline: normalisation, fetching, skills and upserts.

The Greenhouse API is served from recorded fixtures through ``httpx.MockTransport``.
The three ``upsert_job`` tests need real Postgres semantics (unique constraints,
ARRAY columns) and use the ``db_session`` fixture, which skips when no test
database is reachable.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.hashing import DESCRIPTION_HASH_CHARS
from app.models import Job, JobChangeLog, JobSource
from app.services.ingestion.greenhouse import (
    BOARD_URL,
    JOBS_URL,
    RawGreenhouseJob,
    fetch_greenhouse,
    normalize_greenhouse,
)
from app.services.ingestion.http import BoardNotFoundError, FetchError
from app.services.ingestion.pipeline import (
    IngestionStats,
    compute_content_hash,
    run_ingestion_for_source,
    upsert_job,
)
from app.services.ingestion.schema import NormalizedJob
from app.services.ingestion.skill_extractor import extract_skills
from tests.conftest import Route, load_fixture

MockHttp = Callable[[dict[str, Route]], httpx.AsyncClient]

GH_JOBS = JOBS_URL.format(board_token="acme")
GH_BOARD = BOARD_URL.format(board_token="acme")
T0 = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def _job(**overrides: object) -> NormalizedJob:
    base: dict[str, object] = {
        "external_job_id": "4001",
        "source_url": "https://boards.greenhouse.io/acme/jobs/4001",
        "company_name": "Acme",
        "title": "Software Engineer, New Grad",
        "location": "San Francisco, CA",
        "description": "Build payments. " * 10,
        "required_skills": ["Python", "SQL"],
        "posted_at": T0 - timedelta(days=2),
        "deadline": T0 + timedelta(days=30),
    }
    base.update(overrides)
    return NormalizedJob(**base)  # type: ignore[arg-type]


async def _source(db: AsyncSession) -> JobSource:
    source = JobSource(name="greenhouse", board_token="acme", company_name="Acme", is_active=True)
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


# --------------------------------------------------------------------------- #
# 1. normalize_greenhouse: field mapping, HTML stripping, inference
# --------------------------------------------------------------------------- #


def test_normalize_greenhouse_maps_fields_and_strips_html() -> None:
    raw = RawGreenhouseJob.model_validate(load_fixture("greenhouse_jobs.json")["jobs"][0])
    raw = raw.model_copy(update={"company_name": "Acme Corp"})

    job = normalize_greenhouse(raw)

    assert job.external_job_id == "4001"
    assert job.source_url == "https://boards.greenhouse.io/acme/jobs/4001"
    assert job.company_name == "Acme Corp"
    assert job.title == "Software Engineer, New Grad"
    assert job.location == "San Francisco, CA"
    assert job.work_mode == "onsite"  # inferred from a plain city location
    assert job.experience_level == "entry_level"  # inferred from "New Grad"
    # Double-escaped HTML decoded, entities resolved, lists rendered as bullets, no tags left.
    assert job.description is not None
    assert job.description.startswith("Join Acme's platform team.")
    assert "- Python or Go" in job.description
    assert "<" not in job.description and "&lt;" not in job.description
    assert job.requirements == "- Python or Go\n- PostgreSQL"
    assert job.required_skills == ["Python", "Go", "PostgreSQL"]
    assert job.posted_at == datetime(2026, 9, 10, 13, 30, tzinfo=UTC)  # first_published → UTC
    assert job.deadline is None  # Greenhouse exposes no deadline


# --------------------------------------------------------------------------- #
# 2. extract_skills: case-insensitive, canonical names, deduplicated
# --------------------------------------------------------------------------- #


def test_extract_skills_is_case_insensitive_canonical_and_deduped() -> None:
    text = (
        "Strong PYTHON and postgres. React + react.js experience; k8s and Kubernetes. "
        "We go to market fast, but Go services are a plus. node.js and .NET welcome."
    )
    assert extract_skills(text) == [
        "Python",
        "PostgreSQL",
        "React",
        "Kubernetes",
        "Go",
        "Node.js",
        ".NET",
    ]
    assert extract_skills("go to the store; c is a letter") == []  # short tokens need capitals
    assert extract_skills("C-level stakeholders and R&D budgets") == []  # not the languages
    assert extract_skills("Systems work in C and R.") == ["C", "R"]
    assert extract_skills(None, "") == []


# --------------------------------------------------------------------------- #
# 3. fetch_greenhouse: rate limit → retry with backoff → success
# --------------------------------------------------------------------------- #


async def test_fetch_greenhouse_retries_rate_limit_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(str(request.url))
        if len(attempts) <= 2:
            return httpx.Response(429, headers={"Retry-After": "2"}, json={"error": "slow down"})
        return httpx.Response(200, json=load_fixture("greenhouse_jobs.json"))

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("app.services.ingestion.http.asyncio.sleep", fake_sleep)
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    jobs = await fetch_greenhouse("acme", company_name="Acme", http=http)

    assert len(jobs) == 3
    assert {j.company_name for j in jobs} == {"Acme"}
    assert len(attempts) == 3 and all("content=true" in url for url in attempts)
    assert sleeps == [2.0, 2.0]  # Retry-After honoured on both 429s


# --------------------------------------------------------------------------- #
# 4. fetch_greenhouse: 404 is not retried; 5xx gives up after 3 retries
# --------------------------------------------------------------------------- #


async def test_fetch_greenhouse_404_and_persistent_5xx(
    mock_http: MockHttp, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.services.ingestion.http.settings.HTTP_RETRY_BACKOFF_SECONDS", 0.0)

    missing = mock_http({GH_BOARD: (404, {"error": "no board"})})
    with pytest.raises(BoardNotFoundError, match="board not found"):
        await fetch_greenhouse("acme", http=missing)
    assert len(missing.calls) == 1  # type: ignore[attr-defined]  # no retry on 404

    down = mock_http({GH_JOBS: (503, {"error": "down"})})
    with pytest.raises(FetchError, match="HTTP 503"):
        await fetch_greenhouse("acme", company_name="Acme", http=down)
    assert len(down.calls) == 4  # type: ignore[attr-defined]  # 1 attempt + 3 retries


# --------------------------------------------------------------------------- #
# 5. run_ingestion_for_source: malformed API response never crashes
# --------------------------------------------------------------------------- #


async def test_run_ingestion_handles_malformed_response_without_crashing(
    mock_http: MockHttp,
) -> None:
    source = JobSource(id=1, name="greenhouse", board_token="acme", company_name="Acme")
    db = MagicMock(name="AsyncSession")

    for payload in ({"jobs": [{"id": "not-an-int", "title": "x"}]}, {"unexpected": True}, "<html>"):
        stats = await run_ingestion_for_source(
            db, source, http=mock_http({GH_JOBS: (200, payload)})
        )
        assert isinstance(stats, IngestionStats)
        assert stats.error is not None and stats.error.startswith("greenhouse/acme:")
        assert (stats.fetched, stats.inserted, stats.updated) == (0, 0, 0)

    db.commit.assert_not_called()  # nothing touched the database
    db.add.assert_not_called()


# --------------------------------------------------------------------------- #
# 6. upsert_job: insert a new job
# --------------------------------------------------------------------------- #


async def test_upsert_inserts_new_job(db_session: AsyncSession) -> None:
    source = await _source(db_session)
    job = _job()

    outcome = await upsert_job(db_session, source.id, job, now=T0)
    await db_session.commit()

    assert outcome == "inserted"
    row = (await db_session.execute(select(Job))).scalar_one()
    assert (row.source_id, row.external_job_id) == (source.id, "4001")
    assert row.detected_at == T0
    assert row.content_hash == compute_content_hash(job)
    assert row.required_skills == ["Python", "SQL"]
    assert row.deadline == T0 + timedelta(days=30)
    assert row.is_active is True
    assert await db_session.scalar(select(func.count()).select_from(JobChangeLog)) == 0


# --------------------------------------------------------------------------- #
# 7. upsert_job: identical re-fetch is a no-op
# --------------------------------------------------------------------------- #


async def test_upsert_skips_unchanged_duplicate(db_session: AsyncSession) -> None:
    source = await _source(db_session)
    await upsert_job(db_session, source.id, _job(), now=T0)
    await db_session.commit()

    outcome = await upsert_job(db_session, source.id, _job(), now=T0 + timedelta(hours=1))
    await db_session.commit()

    assert outcome == "unchanged"
    row = (await db_session.execute(select(Job))).scalar_one()
    assert row.updated_at == T0  # untouched
    assert await db_session.scalar(select(func.count()).select_from(JobChangeLog)) == 0

    # A change beyond the first 500 description chars keeps the hash stable,
    # but the tracked-field diff still notices it.
    long_tail = _job(description="x" * DESCRIPTION_HASH_CHARS + " original")
    edited = _job(description="x" * DESCRIPTION_HASH_CHARS + " edited")
    assert compute_content_hash(long_tail) == compute_content_hash(edited)


# --------------------------------------------------------------------------- #
# 8. upsert_job: a changed deadline is detected and logged
# --------------------------------------------------------------------------- #


async def test_upsert_detects_and_logs_changed_deadline(db_session: AsyncSession) -> None:
    source = await _source(db_session)
    await upsert_job(db_session, source.id, _job(), now=T0)
    await db_session.commit()

    later = T0 + timedelta(hours=3)
    new_deadline = T0 + timedelta(days=45)
    outcome = await upsert_job(db_session, source.id, _job(deadline=new_deadline), now=later)
    await db_session.commit()

    assert outcome == "updated"
    row = (await db_session.execute(select(Job))).scalar_one()
    assert row.deadline == new_deadline
    assert row.updated_at == later
    assert row.detected_at == T0  # first-seen time preserved
    assert row.content_hash == compute_content_hash(_job())  # deadline is not hashed

    log = (await db_session.execute(select(JobChangeLog))).scalar_one()
    assert log.job_id == row.id
    assert log.field_changed == "deadline"
    assert log.old_value == (T0 + timedelta(days=30)).isoformat()
    assert log.new_value == new_deadline.isoformat()
    assert log.changed_at == later
