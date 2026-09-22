"""Job-board ingestion: fetch → normalise → upsert.

Each ATS lives in its own module exposing ``fetch_<source>()`` (raw API
objects) and ``normalize_<source>()`` (→ :class:`NormalizedJob`). The
pipeline dispatches on ``job_sources.name`` via :data:`SOURCES`.
"""

from app.services.ingestion.http import BoardNotFoundError, FetchError, make_http_client
from app.services.ingestion.pipeline import (
    SOURCES,
    IngestionStats,
    SourceAdapter,
    compute_content_hash,
    run_ingestion_by_id,
    run_ingestion_for_source,
    sync_jobs,
    upsert_job,
)
from app.services.ingestion.schema import NormalizedJob
from app.services.ingestion.skill_extractor import extract_skills, load_skills_dictionary

__all__ = [
    "SOURCES",
    "BoardNotFoundError",
    "FetchError",
    "IngestionStats",
    "NormalizedJob",
    "SourceAdapter",
    "compute_content_hash",
    "extract_skills",
    "load_skills_dictionary",
    "make_http_client",
    "run_ingestion_by_id",
    "run_ingestion_for_source",
    "sync_jobs",
    "upsert_job",
]
