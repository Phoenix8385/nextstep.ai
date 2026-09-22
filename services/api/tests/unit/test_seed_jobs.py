"""Tests for the seed data and content hashing (no database)."""

from datetime import UTC, datetime, timedelta

from app.core.hashing import compute_content_hash
from app.schemas.job import NEW_JOB_WINDOW
from app.scripts.seed_jobs import SEED_JOBS, SEED_SOURCES, build_job_values


def test_content_hash_is_deterministic_and_normalised() -> None:
    base = compute_content_hash(
        company_name="Stripe", title="Backend Engineer", location="Remote, US", description="x"
    )
    same = compute_content_hash(
        company_name="  stripe ",
        title="BACKEND   engineer",
        location="remote,  us",
        description="X",
    )
    different = compute_content_hash(
        company_name="Stripe", title="Backend Engineer II", location="Remote, US", description="x"
    )
    assert base == same
    assert base != different
    assert len(base) == 64
    assert compute_content_hash(company_name="A", title="B", location=None, description=None)


def test_seed_has_ten_jobs_with_unique_keys() -> None:
    assert len(SEED_JOBS) == 10
    keys = {(job.source, job.external_job_id) for job in SEED_JOBS}
    assert len(keys) == 10
    assert len({job.source_url for job in SEED_JOBS}) == 10


def test_every_seed_job_references_a_seed_source() -> None:
    sources = {(s.name, s.board_token) for s in SEED_SOURCES}
    assert {job.source for job in SEED_JOBS} <= sources
    assert {s.name for s in SEED_SOURCES} == {"greenhouse", "lever", "ashby"}


def test_seed_jobs_are_well_formed() -> None:
    for job in SEED_JOBS:
        assert job.source_url.startswith("https://"), job.title
        assert job.required_skills, job.title
        assert job.work_mode in {"remote", "hybrid", "onsite"}, job.title
        assert job.experience_level in {"intern", "entry_level", "experienced"}, job.title
        assert len(job.description) > 80, job.title
        assert job.detected_hours_ago <= job.posted_days_ago * 24 + 1e-9, job.title


def test_seed_covers_filter_dimensions() -> None:
    """The seed should exercise every list filter the API exposes."""
    assert {j.work_mode for j in SEED_JOBS} == {"remote", "hybrid", "onsite"}
    assert {j.experience_level for j in SEED_JOBS} == {"intern", "entry_level", "experienced"}
    assert any(j.deadline_days_ahead for j in SEED_JOBS)
    assert any(j.deadline_days_ahead is None for j in SEED_JOBS)
    fresh = [j for j in SEED_JOBS if timedelta(hours=j.detected_hours_ago) < NEW_JOB_WINDOW]
    assert 2 <= len(fresh) <= 5, "want a mix of is_new true/false"


def test_build_job_values_matches_columns() -> None:
    now = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
    job = SEED_JOBS[0]
    values = build_job_values(job, source_id=7, now=now)

    assert values["source_id"] == 7
    assert values["external_job_id"] == job.external_job_id
    assert values["posted_at"] == now - timedelta(days=job.posted_days_ago)
    assert values["detected_at"] == now - timedelta(hours=job.detected_hours_ago)
    assert values["deadline"] == now + timedelta(days=job.deadline_days_ahead or 0)
    assert values["content_hash"] == compute_content_hash(
        company_name=job.company_name,
        title=job.title,
        location=job.location,
        description=job.description,
    )
    assert values["is_active"] is True
    assert values["required_skills"] == job.required_skills
    assert values["required_skills"] is not job.required_skills  # defensive copy
