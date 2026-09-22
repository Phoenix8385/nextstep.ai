"""Celery Beat schedule.

Kept in its own module so the schedule can be inspected and unit-tested
without instantiating the Celery app.
"""

from datetime import timedelta
from typing import Any, Final

from app.core.config import settings

INGEST_EVERY: Final[timedelta] = timedelta(minutes=settings.INGEST_INTERVAL_MINUTES)
"""How often every active job source is polled (default: 20 minutes)."""

INGEST_ALL_TASK: Final[str] = "worker.ingest_all_active_sources"

beat_schedule: Final[dict[str, dict[str, Any]]] = {
    "ingest-all-active-sources": {
        "task": INGEST_ALL_TASK,
        "schedule": INGEST_EVERY,
        # If the worker was down, drop runs older than one interval instead of
        # replaying a backlog; the next tick fetches everything anyway.
        "options": {"expires": int(INGEST_EVERY.total_seconds())},
    },
}
