"""Celery application for NextStep.ai background jobs.

Run from the repository root with the API virtualenv active (``app`` must be
importable: ``pip install -e services/api``)::

    celery -A services.worker.celery_app worker --loglevel=info --pool=solo   # Windows
    celery -A services.worker.celery_app worker --loglevel=info               # Linux/macOS
    celery -A services.worker.celery_app beat   --loglevel=info

Redis (``settings.REDIS_URL``) is both the broker and the result backend.
"""

from celery import Celery

from app.core.config import settings
from services.worker.beat_schedule import beat_schedule

celery_app = Celery(
    "nextstep",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["services.worker.tasks"],
)

celery_app.conf.update(
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
