"""Celery tasks.

``ingest_all_active_sources`` is the only scheduled task: it sweeps every
``job_sources`` row with ``is_active = true`` and syncs each board through
:func:`app.services.ingestion.pipeline.run_ingestion_for_source`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Final

import redis
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionFactory, dispose_engine
from app.models.job import JobSource
from app.services.ingestion.pipeline import IngestionStats, run_ingestion_for_source
from services.worker.beat_schedule import INGEST_ALL_TASK
from services.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

LOCK_KEY: Final[str] = "nextstep:lock:ingest_all_active_sources"
LOCK_TTL_SECONDS: Final[int] = 18 * 60  # matches task_time_limit; released on completion

_SUMMED: Final[tuple[str, ...]] = (
    "fetched",
    "inserted",
    "updated",
    "unchanged",
    "failed",
    "deactivated",
    "duplicates_skipped",
)


@celery_app.task(name=INGEST_ALL_TASK)
def ingest_all_active_sources() -> dict[str, Any]:
    """Sync every active job source and return a per-source + total summary.

    Overlapping runs are prevented with a Redis lock: if a previous sweep is
    still in progress the task logs that and returns ``{"skipped": True}``.
    """
    if not _acquire_lock():
        logger.warning("ingest_all_active_sources: previous run still in progress; skipping")
        return {"skipped": True, "reason": "previous run still in progress"}
    try:
        return asyncio.run(_ingest_all())
    finally:
        _release_lock()


async def _ingest_all() -> dict[str, Any]:
    per_source: list[dict[str, Any]] = []
    try:
        async with AsyncSessionFactory() as db:
            result = await db.execute(
                select(JobSource).where(JobSource.is_active.is_(True)).order_by(JobSource.id)
            )
            sources = result.scalars().all()
            logger.info("ingest_all_active_sources: %d active sources", len(sources))

            for source in sources:
                label = f"{source.name}/{source.board_token}"
                try:
                    stats = await run_ingestion_for_source(db, source)
                except Exception as exc:  # one broken source must not stop the sweep
                    await db.rollback()
                    logger.exception("%s: ingestion crashed", label)
                    stats = IngestionStats(
                        source_id=source.id, error=f"{type(exc).__name__}: {exc}"
                    )
                _log_source(label, stats)
                per_source.append({"source": label, **stats.as_dict()})
    finally:
        await dispose_engine()

    totals = {key: sum(row[key] for row in per_source) for key in _SUMMED}
    errors = sum(1 for row in per_source if row["error"])
    logger.info(
        "ingestion summary: sources=%d fetched=%d inserted=%d updated=%d unchanged=%d "
        "failed=%d deactivated=%d errors=%d",
        len(per_source),
        totals["fetched"],
        totals["inserted"],
        totals["updated"],
        totals["unchanged"],
        totals["failed"],
        totals["deactivated"],
        errors,
    )
    return {
        "sources": len(per_source),
        "errors": errors,
        "totals": totals,
        "per_source": per_source,
    }


def _log_source(label: str, stats: IngestionStats) -> None:
    if stats.error:
        logger.warning("%s: ERROR %s", label, stats.error)
        return
    logger.info(
        "%s: fetched=%d inserted=%d updated=%d unchanged=%d failed=%d deactivated=%d",
        label,
        stats.fetched,
        stats.inserted,
        stats.updated,
        stats.unchanged,
        stats.failed,
        stats.deactivated,
    )


def _redis() -> redis.Redis:
    client: redis.Redis = redis.Redis.from_url(settings.REDIS_URL)  # type: ignore[no-untyped-call]
    return client


def _acquire_lock() -> bool:
    """``SET NX EX`` on the lock key; ``True`` if this run now owns it."""
    return bool(_redis().set(LOCK_KEY, "1", nx=True, ex=LOCK_TTL_SECONDS))


def _release_lock() -> None:
    _redis().delete(LOCK_KEY)
