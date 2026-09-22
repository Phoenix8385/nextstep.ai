"""Celery application for NextStep.ai background jobs.

Run from the repository root with the API virtualenv active (``app`` must be
importable: ``pip install -e services/api``)::

    celery -A services.worker.celery_app worker --loglevel=info
    celery -A services.worker.celery_app beat   --loglevel=info

The worker pool defaults to ``solo`` on Windows and ``prefork`` elsewhere, so
the same command works on both; pass ``--pool=`` to override.

Redis (``settings.REDIS_URL``) is both the broker and the result backend.
"""

import sys

from celery import Celery

from app.core.config import settings
from services.worker.beat_schedule import beat_schedule

# Celery's default prefork pool needs fork(), which Windows does not provide;
# billiard's spawn fallback dies with WinError 5/6 as soon as a pool process
# starts. Default to the solo pool there so the plain `celery ... worker`
# command works. An explicit --pool=... on the command line still wins.
DEFAULT_POOL: str = "solo" if sys.platform == "win32" else "prefork"

celery_app = Celery(
    "nextstep",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["services.worker.tasks"],
)

celery_app.conf.update(
    worker_pool=DEFAULT_POOL,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Re-queue a task if the worker dies mid-run; one task per slot at a time.
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # A full sweep of every board must finish well inside one beat interval.
    task_soft_time_limit=15 * 60,
    task_time_limit=18 * 60,
    result_expires=24 * 60 * 60,
    broker_connection_retry_on_startup=True,
    beat_schedule=beat_schedule,
)
