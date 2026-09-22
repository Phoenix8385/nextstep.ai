"""Worker wiring: Celery config, beat schedule, and the ``ingest_all_active_sources`` sweep.

No broker or database is touched: the session factory, the ingestion runner
and the Redis lock are patched.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import settings
from app.models.job import JobSource
from app.services.ingestion.pipeline import IngestionStats
from services.worker import tasks
from services.worker.beat_schedule import INGEST_ALL_TASK, INGEST_EVERY, beat_schedule
from services.worker.celery_app import celery_app

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


def test_celery_uses_redis_for_broker_and_backend() -> None:
    assert celery_app.conf.broker_url == settings.REDIS_URL
    assert celery_app.conf.result_backend == settings.REDIS_URL
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.accept_content == ["json"]
    assert celery_app.conf.timezone == "UTC"
    assert celery_app.conf.task_acks_late is True


def test_beat_runs_ingest_all_every_20_minutes() -> None:
    assert INGEST_EVERY == timedelta(minutes=20)
    entry = beat_schedule["ingest-all-active-sources"]
    assert entry["task"] == INGEST_ALL_TASK == "worker.ingest_all_active_sources"
    assert entry["schedule"] == timedelta(minutes=20)
    assert entry["options"]["expires"] == 20 * 60
    assert celery_app.conf.beat_schedule is beat_schedule


def test_task_is_registered_under_its_schedule_name() -> None:
    assert INGEST_ALL_TASK in celery_app.tasks
    # @task returns a lazy proxy, so compare by name rather than identity.
    assert celery_app.tasks[INGEST_ALL_TASK].name == tasks.ingest_all_active_sources.name


# --------------------------------------------------------------------------- #
# ingest_all_active_sources
# --------------------------------------------------------------------------- #


def _sources(*specs: tuple[int, str, str]) -> list[JobSource]:
    return [
        JobSource(id=sid, name=name, board_token=token, company_name=token.title(), is_active=True)
        for sid, name, token in specs
    ]


@pytest.fixture()
def fake_db(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Session factory stand-in; ``execute`` returns whatever is in ``fake_db.sources``."""
    session = MagicMock(name="AsyncSession")
    session.sources = []
    session.rollback = AsyncMock()

    async def execute(_stmt: object) -> MagicMock:
        result = MagicMock(name="Result")
        result.scalars.return_value.all.return_value = session.sources
        return result

    session.execute = execute

    @asynccontextmanager
    async def factory() -> AsyncIterator[MagicMock]:
        yield session

    monkeypatch.setattr(tasks, "AsyncSessionFactory", factory)
    monkeypatch.setattr(tasks, "dispose_engine", AsyncMock())
    monkeypatch.setattr(tasks, "_acquire_lock", lambda: True)
    monkeypatch.setattr(tasks, "_release_lock", lambda: None)
    return session


def _run() -> dict[str, Any]:
    return tasks.ingest_all_active_sources.apply().get()  # type: ignore[no-any-return]


def test_sweep_runs_every_active_source_and_summarises(
    fake_db: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    fake_db.sources = _sources((1, "greenhouse", "stripe"), (2, "ashby", "notion"))
    stats_by_id = {
        1: IngestionStats(source_id=1, fetched=10, inserted=3, updated=2, unchanged=5),
        2: IngestionStats(source_id=2, fetched=4, inserted=0, updated=0, unchanged=3, failed=1),
    }

    async def fake_run(db: object, source: JobSource, **_: object) -> IngestionStats:
        return stats_by_id[source.id]

    with (
        patch.object(tasks, "run_ingestion_for_source", side_effect=fake_run) as runner,
        caplog.at_level("INFO", logger="services.worker.tasks"),
    ):
        summary = _run()

    assert runner.call_count == 2
    assert summary["sources"] == 2
    assert summary["errors"] == 0
    assert summary["totals"] == {
        "fetched": 14,
        "inserted": 3,
        "updated": 2,
        "unchanged": 8,
        "failed": 1,
        "deactivated": 0,
        "duplicates_skipped": 0,
    }
    assert [row["source"] for row in summary["per_source"]] == ["greenhouse/stripe", "ashby/notion"]

    messages = [rec.getMessage() for rec in caplog.records]
    assert "greenhouse/stripe: fetched=10 inserted=3 updated=2 unchanged=5 failed=0" in "\n".join(
        messages
    )
    assert any(m.startswith("ingestion summary: sources=2 fetched=14 inserted=3") for m in messages)


def test_one_crashing_source_does_not_stop_the_sweep(
    fake_db: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    fake_db.sources = _sources((1, "greenhouse", "a"), (2, "lever", "b"), (3, "ashby", "c"))

    async def fake_run(db: object, source: JobSource, **_: object) -> IngestionStats:
        if source.id == 2:
            raise RuntimeError("connection reset")
        return IngestionStats(source_id=source.id, fetched=1, inserted=1)

    with (
        patch.object(tasks, "run_ingestion_for_source", side_effect=fake_run),
        caplog.at_level("WARNING", logger="services.worker.tasks"),
    ):
        summary = _run()

    assert summary["sources"] == 3
    assert summary["errors"] == 1
    assert summary["per_source"][1]["error"] == "RuntimeError: connection reset"
    assert summary["per_source"][2]["inserted"] == 1  # third source still ran
    assert summary["totals"]["inserted"] == 2
    fake_db.rollback.assert_awaited_once()
    assert "lever/b: ingestion crashed" in caplog.text


def test_fetch_errors_are_reported_not_raised(fake_db: MagicMock) -> None:
    fake_db.sources = _sources((1, "lever", "plaid"))

    async def fake_run(db: object, source: JobSource, **_: object) -> IngestionStats:
        return IngestionStats(source_id=1, error="lever/plaid: board not found (HTTP 404)")

    with patch.object(tasks, "run_ingestion_for_source", side_effect=fake_run):
        summary = _run()

    assert summary == {
        "sources": 1,
        "errors": 1,
        "totals": {k: 0 for k in tasks._SUMMED},
        "per_source": [
            {
                "source": "lever/plaid",
                **IngestionStats(
                    source_id=1, error="lever/plaid: board not found (HTTP 404)"
                ).as_dict(),
            }
        ],
    }


def test_no_active_sources_is_a_clean_no_op(fake_db: MagicMock) -> None:
    fake_db.sources = []
    with patch.object(tasks, "run_ingestion_for_source") as runner:
        summary = _run()
    runner.assert_not_called()
    assert summary["sources"] == 0
    assert summary["totals"]["fetched"] == 0


def test_skips_when_previous_run_holds_the_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks, "_acquire_lock", lambda: False)
    release = MagicMock()
    monkeypatch.setattr(tasks, "_release_lock", release)
    with patch.object(tasks, "_ingest_all") as sweep:
        summary = _run()
    sweep.assert_not_called()
    release.assert_not_called()  # we never owned it, so we must not delete it
    assert summary == {"skipped": True, "reason": "previous run still in progress"}


def test_lock_is_released_even_when_the_sweep_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks, "_acquire_lock", lambda: True)
    release = MagicMock()
    monkeypatch.setattr(tasks, "_release_lock", release)

    async def boom() -> dict[str, Any]:
        raise RuntimeError("database down")

    with (
        patch.object(tasks, "_ingest_all", boom),
        pytest.raises(RuntimeError, match="database down"),
    ):
        tasks.ingest_all_active_sources.apply().get()
    release.assert_called_once()
