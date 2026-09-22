"""``sync_jobs`` / ``run_ingestion_for_source`` against real Postgres."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job, JobChangeLog, JobSource
from app.services.ingestion import pipeline
from app.services.ingestion.greenhouse import JOBS_URL
from app.services.ingestion.pipeline import run_ingestion_for_source, sync_jobs
from app.services.ingestion.schema import NormalizedJob
from tests.conftest import Route, load_fixture

MockHttp = Callable[[dict[str, Route]], httpx.AsyncClient]
T0 = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def posting(ext_id: str, **overrides: object) -> NormalizedJob:
    base: dict[str, object] = {
        "external_job_id": ext_id,
        "source_url": f"https://boards.greenhouse.io/acme/jobs/{ext_id}",
        "company_name": "Acme",
        "title": f"Engineer {ext_id}",
        "location": "NYC",
        "description": f"Body {ext_id}",
        "required_skills": ["Python"],
        "posted_at": T0 - timedelta(days=1),
    }
    base.update(overrides)
    return NormalizedJob(**base)  # type: ignore[arg-type]


async def make_source(db: AsyncSession, name: str = "greenhouse", board: str = "acme") -> JobSource:
    source = JobSource(name=name, board_token=board, company_name="Acme", is_active=True)
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


async def count(db: AsyncSession, model: type[Job] | type[JobChangeLog]) -> int:
    return (await db.scalar(select(func.count()).select_from(model))) or 0


async def test_sync_inserts_then_reports_unchanged(db_session: AsyncSession) -> None:
    source = await make_source(db_session)
    first = await sync_jobs(db_session, source, [posting("1"), posting("2")], now=T0)
    assert (first.inserted, first.updated, first.unchanged, first.failed) == (2, 0, 0, 0)
    assert source.last_fetched_at == T0

    again = await sync_jobs(db_session, source, [posting("1"), posting("2")], now=T0)
    assert (again.inserted, again.updated, again.unchanged) == (0, 0, 2)
    assert await count(db_session, JobChangeLog) == 0


async def test_missing_postings_are_deactivated_then_reactivated(db_session: AsyncSession) -> None:
    source = await make_source(db_session)
    await sync_jobs(db_session, source, [posting("1"), posting("2")], now=T0)

    gone = await sync_jobs(db_session, source, [posting("1")], now=T0 + timedelta(hours=1))
    assert gone.deactivated == 1
    job2 = (await db_session.execute(select(Job).where(Job.external_job_id == "2"))).scalar_one()
    assert job2.is_active is False
    log = (
        await db_session.execute(select(JobChangeLog).where(JobChangeLog.job_id == job2.id))
    ).scalar_one()
    assert (log.field_changed, log.old_value, log.new_value) == ("is_active", "True", "False")

    back = await sync_jobs(
        db_session, source, [posting("1"), posting("2")], now=T0 + timedelta(hours=2)
    )
    assert (back.updated, back.inserted) == (1, 0)  # reactivated in place
    await db_session.refresh(job2)
    assert job2.is_active is True
    assert await count(db_session, Job) == 2


async def test_empty_fetch_does_not_deactivate(db_session: AsyncSession) -> None:
    source = await make_source(db_session)
    await sync_jobs(db_session, source, [posting("1")], now=T0)

    result = await sync_jobs(db_session, source, [], now=T0 + timedelta(hours=1))
    assert result.deactivated == 0
    assert (await db_session.execute(select(Job))).scalar_one().is_active is True
    assert source.last_fetched_at == T0 + timedelta(hours=1)


async def test_cross_source_duplicate_is_skipped(db_session: AsyncSession) -> None:
    greenhouse = await make_source(db_session, "greenhouse", "acme")
    lever = await make_source(db_session, "lever", "acme")
    await sync_jobs(db_session, greenhouse, [posting("gh-1")], now=T0)

    twin = posting(
        "lv-1", title="Engineer gh-1", description="Body gh-1", source_url="https://jobs.lever.co/x"
    )
    assert twin.content_hash == posting("gh-1").content_hash

    result = await sync_jobs(db_session, lever, [twin, posting("lv-2")], now=T0)
    assert (result.inserted, result.duplicates_skipped) == (1, 1)
    assert await count(db_session, Job) == 2


async def test_one_bad_row_does_not_poison_the_batch(db_session: AsyncSession) -> None:
    source = await make_source(db_session)
    real_upsert = pipeline.upsert_job

    async def flaky_upsert(
        db: AsyncSession, source_id: int, job: NormalizedJob, **kw: Any
    ) -> pipeline.UpsertOutcome:
        if job.external_job_id == "bad":
            raise RuntimeError("simulated failure")
        return await real_upsert(db, source_id, job, **kw)

    with patch.object(pipeline, "upsert_job", flaky_upsert):
        result = await sync_jobs(db_session, source, [posting("bad"), posting("ok")], now=T0)

    assert (result.failed, result.inserted) == (1, 1)
    ids = {j.external_job_id for j in (await db_session.execute(select(Job))).scalars()}
    assert ids == {"ok"}  # "bad" rolled back to its savepoint, "ok" committed


async def test_run_ingestion_end_to_end_with_greenhouse_fixture(
    db_session: AsyncSession, mock_http: MockHttp
) -> None:
    source = await make_source(db_session)
    http = mock_http(
        {JOBS_URL.format(board_token="acme"): (200, load_fixture("greenhouse_jobs.json"))}
    )

    stats = await run_ingestion_for_source(db_session, source, http=http)

    assert stats.error is None
    assert (stats.fetched, stats.inserted, stats.failed) == (3, 3, 0)
    rows = (await db_session.execute(select(Job).order_by(Job.external_job_id))).scalars().all()
    assert [r.external_job_id for r in rows] == ["4001", "4002", "4003"]
    assert rows[0].company_name == "Acme"  # from the job_sources row, no board call needed
    assert rows[0].required_skills == ["Python", "Go", "PostgreSQL"]
    assert rows[1].work_mode == "remote"
    assert rows[2].experience_level == "intern"

    # Second run: nothing changed.
    again = await run_ingestion_for_source(db_session, source, http=http)
    assert (again.inserted, again.unchanged, again.deactivated) == (0, 3, 0)
