"""Unit tests for ``/jobs`` (mocked session) and the filter → SQL translation."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models import Job, User
from app.routers.jobs import _escape_like, apply_job_filters
from app.schemas.job import NEW_JOB_WINDOW, JobFilters, JobPage, is_new

# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #


def _sql(filters: JobFilters) -> str:
    stmt = apply_job_filters(select(Job), filters)
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_no_filters_adds_no_where_clause() -> None:
    assert "WHERE" not in _sql(JobFilters())


def test_text_filters_are_case_insensitive_substring_matches() -> None:
    sql = _sql(JobFilters(role="engineer", company="stripe", location="remote"))
    # The Postgres dialect renders native ILIKE; literal '%' is doubled in compiled output.
    assert "jobs.title ILIKE '%%engineer%%'" in sql
    assert "jobs.company_name ILIKE '%%stripe%%'" in sql
    assert "jobs.location ILIKE '%%remote%%'" in sql


def test_like_wildcards_in_user_input_are_escaped() -> None:
    assert _escape_like("100%_match") == r"100\%\_match"
    assert _escape_like("back\\slash") == "back\\\\slash"
    sql = _sql(JobFilters(role="100%_match"))
    assert "jobs.title ILIKE" in sql
    assert "ESCAPE" in sql


def test_exact_filters_lowercase_both_sides() -> None:
    sql = _sql(JobFilters(work_mode="Remote", experience_level="ENTRY"))
    assert "lower(jobs.work_mode) = 'remote'" in sql
    assert "lower(jobs.experience_level) = 'entry'" in sql


def test_posted_after_and_deadline_filters() -> None:
    sql = _sql(JobFilters(posted_after=datetime(2026, 9, 1, tzinfo=UTC), has_deadline=True))
    assert "jobs.posted_at >= '2026-09-01 00:00:00+00:00'" in sql
    assert "jobs.deadline IS NOT NULL" in sql

    assert "jobs.deadline IS NULL" in _sql(JobFilters(has_deadline=False))
    assert "jobs.deadline IS" not in _sql(JobFilters(has_deadline=None))


def test_naive_posted_after_is_treated_as_utc() -> None:
    filters = JobFilters(posted_after=datetime(2026, 9, 1, 12, 0))
    assert filters.posted_after is not None
    assert filters.posted_after.tzinfo is UTC


def test_offset_math() -> None:
    assert JobFilters(page=1, page_size=20).offset == 0
    assert JobFilters(page=3, page_size=25).offset == 50


def test_is_new_window() -> None:
    now = datetime.now(UTC)
    assert is_new(now, now=now) is True
    assert is_new(now - NEW_JOB_WINDOW + timedelta(seconds=1), now=now) is True
    assert is_new(now - NEW_JOB_WINDOW - timedelta(seconds=1), now=now) is False


def test_job_page_metadata() -> None:
    page = JobPage.build([], filters=JobFilters(page=2, page_size=4), total=10)
    assert (page.total_pages, page.has_next) == (3, True)
    last = JobPage.build([], filters=JobFilters(page=3, page_size=4), total=10)
    assert last.has_next is False
    empty = JobPage.build([], filters=JobFilters(), total=0)
    assert (empty.total_pages, empty.has_next) == (0, False)


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #


def _list_results(total: int, jobs: list[Job]) -> AsyncMock:
    """``session.execute`` returning the COUNT result first, then the page rows."""
    count_result = MagicMock(name="CountResult")
    count_result.scalar_one.return_value = total
    rows_result = MagicMock(name="RowsResult")
    rows_result.scalars.return_value.all.return_value = jobs
    return AsyncMock(side_effect=[count_result, rows_result])


async def test_list_jobs_is_public(client: AsyncClient, mock_session: MagicMock) -> None:
    mock_session.execute = _list_results(total=0, jobs=[])
    resp = await client.get("/jobs")  # no Authorization header
    assert resp.status_code == 200
    assert resp.json()["items"] == []


async def test_list_jobs_returns_page_with_is_new(
    client: AsyncClient,
    mock_session: MagicMock,
    auth_headers: dict[str, str],
    make_job: Callable[..., Job],
) -> None:
    now = datetime.now(UTC)
    fresh = make_job(title="Fresh role", detected_at=now - timedelta(minutes=30))
    stale = make_job(title="Stale role", detected_at=now - timedelta(days=3))
    mock_session.execute = _list_results(total=42, jobs=[fresh, stale])

    resp = await client.get("/jobs", headers=auth_headers, params={"page": 2, "page_size": 2})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["page"] == 2
    assert body["page_size"] == 2
    assert body["total"] == 42
    assert body["total_pages"] == 21
    assert body["has_next"] is True
    assert [item["title"] for item in body["items"]] == ["Fresh role", "Stale role"]
    assert body["items"][0]["is_new"] is True
    assert body["items"][1]["is_new"] is False
    assert "description" not in body["items"][0]  # list view omits long text

    # Both queries went through the session: COUNT(*) then the paged SELECT.
    assert mock_session.execute.await_count == 2
    paged_sql = str(mock_session.execute.await_args_list[1].args[0])
    assert "ORDER BY jobs.detected_at DESC" in paged_sql
    assert "LIMIT" in paged_sql and "OFFSET" in paged_sql


async def test_list_jobs_filters_reach_the_query(
    client: AsyncClient, mock_session: MagicMock, auth_headers: dict[str, str]
) -> None:
    mock_session.execute = _list_results(total=0, jobs=[])

    resp = await client.get(
        "/jobs",
        headers=auth_headers,
        params={"role": "intern", "work_mode": "remote", "has_deadline": "true"},
    )

    assert resp.status_code == 200
    assert resp.json()["items"] == []
    count_sql = str(mock_session.execute.await_args_list[0].args[0])
    assert "jobs.is_active IS true" in count_sql
    assert "lower(jobs.title) LIKE lower(" in count_sql  # generic dialect when str()-ed
    assert "lower(jobs.work_mode) =" in count_sql
    assert "jobs.deadline IS NOT NULL" in count_sql


async def test_list_jobs_validates_query_params(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    assert (
        await client.get("/jobs", headers=auth_headers, params={"page_size": 101})
    ).status_code == 422
    assert (await client.get("/jobs", headers=auth_headers, params={"page": 0})).status_code == 422
    assert (
        await client.get("/jobs", headers=auth_headers, params={"posted_after": "not-a-date"})
    ).status_code == 422


async def test_get_job_detail(
    client: AsyncClient,
    mock_session: MagicMock,
    fake_user: User,
    auth_headers: dict[str, str],
    make_job: Callable[..., Job],
) -> None:
    job = make_job(description="Long description", eligibility="2026 grads")

    async def _get(model: type, key: object, **_: object) -> object:
        return fake_user if model is User else job

    mock_session.get = AsyncMock(side_effect=_get)

    resp = await client.get(f"/jobs/{job.id}", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(job.id)
    assert body["description"] == "Long description"
    assert body["eligibility"] == "2026 grads"
    assert body["source_name"] == "greenhouse"
    assert body["is_new"] is True


async def test_get_job_404(
    client: AsyncClient, mock_session: MagicMock, fake_user: User, auth_headers: dict[str, str]
) -> None:
    async def _get(model: type, key: object, **_: object) -> object:
        return fake_user if model is User else None

    mock_session.get = AsyncMock(side_effect=_get)

    resp = await client.get(f"/jobs/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Job not found"}


async def test_get_job_rejects_non_uuid(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    assert (await client.get("/jobs/not-a-uuid", headers=auth_headers)).status_code == 422
