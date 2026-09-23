"""Integration tests: seed script, job filters, saved jobs and profile against real Postgres."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job, JobSource, SavedJob, UserProfile
from app.scripts.seed_jobs import (
    SEED_JOBS,
    SEED_SOURCES,
    RealJobsPresentError,
    has_ingested_jobs,
    seed,
)

# --------------------------------------------------------------------------- #
# Seed script
# --------------------------------------------------------------------------- #


async def test_seed_inserts_ten_jobs_and_is_idempotent(db_session: AsyncSession) -> None:
    sources, inserted = await seed(db_session)
    assert (sources, inserted) == (len(SEED_SOURCES), 10)

    sources_again, inserted_again = await seed(db_session)
    assert (sources_again, inserted_again) == (len(SEED_SOURCES), 0)

    assert await db_session.scalar(select(func.count()).select_from(Job)) == 10
    assert await db_session.scalar(select(func.count()).select_from(JobSource)) == len(SEED_SOURCES)


async def test_seed_refuses_once_real_jobs_are_ingested(db_session: AsyncSession) -> None:
    """Seeding an already-ingested database floats synthetic rows above real ones.

    Seed ``detected_at`` values are back-dated into the "just posted" window,
    and ``GET /jobs`` orders by ``detected_at`` — so a late seed takes over
    page 1 and badges fakes as new. The guard is what stops that.
    """
    source = JobSource(name="greenhouse", board_token="acme", company_name="Acme", is_active=True)
    db_session.add(source)
    await db_session.flush()
    db_session.add(
        Job(
            source_id=source.id,
            external_job_id="real-1",
            source_url="https://boards.greenhouse.io/acme/jobs/real-1",
            company_name="Acme",
            title="Real Ingested Engineer",
            description="Body",
            required_skills=["Python"],
            content_hash="deadbeef",
            detected_at=datetime.now(UTC) - timedelta(hours=6),
            is_active=True,
        )
    )
    await db_session.commit()

    assert await has_ingested_jobs(db_session) is True
    with pytest.raises(RealJobsPresentError, match="already holds ingested postings"):
        await seed(db_session)

    # Nothing was written: the real posting is still the only row.
    assert await db_session.scalar(select(func.count()).select_from(Job)) == 1

    # --force is the documented escape hatch and still works.
    _, inserted = await seed(db_session, force=True)
    assert inserted == len(SEED_JOBS)


async def test_has_ingested_jobs_ignores_the_seed_rows_themselves(
    db_session: AsyncSession,
) -> None:
    """Re-running the seed must stay idempotent, not trip its own guard."""
    await seed(db_session)
    assert await has_ingested_jobs(db_session) is False

    _, again = await seed(db_session)
    assert again == 0


# --------------------------------------------------------------------------- #
# GET /jobs
# --------------------------------------------------------------------------- #


async def test_list_jobs_paginates_newest_first(
    db_client: AsyncClient, db_session: AsyncSession, auth: dict[str, str]
) -> None:
    await seed(db_session)

    page1 = await db_client.get("/jobs", headers=auth, params={"page_size": 4})
    assert page1.status_code == 200, page1.text
    body = page1.json()
    assert (body["total"], body["total_pages"], body["has_next"]) == (10, 3, True)
    assert len(body["items"]) == 4
    detected = [item["detected_at"] for item in body["items"]]
    assert detected == sorted(detected, reverse=True)

    page3 = (await db_client.get("/jobs", headers=auth, params={"page_size": 4, "page": 3})).json()
    assert len(page3["items"]) == 2
    assert page3["has_next"] is False

    all_ids = {
        item["id"]
        for page in (1, 2, 3)
        for item in (
            await db_client.get("/jobs", headers=auth, params={"page_size": 4, "page": page})
        ).json()["items"]
    }
    assert len(all_ids) == 10  # no duplicates or gaps across pages


async def test_is_new_reflects_detected_at(
    db_client: AsyncClient, db_session: AsyncSession, auth: dict[str, str]
) -> None:
    await seed(db_session)
    fresh_titles = {j.title for j in SEED_JOBS if j.detected_hours_ago < 2}

    items = (await db_client.get("/jobs", headers=auth, params={"page_size": 100})).json()["items"]
    assert {i["title"] for i in items if i["is_new"]} == fresh_titles


async def test_filters_match_seed_data(
    db_client: AsyncClient, db_session: AsyncSession, auth: dict[str, str]
) -> None:
    await seed(db_session)

    async def titles(**params: object) -> set[str]:
        resp = await db_client.get("/jobs", headers=auth, params={"page_size": 100, **params})
        assert resp.status_code == 200, resp.text
        return {item["title"] for item in resp.json()["items"]}

    expected_remote = {j.title for j in SEED_JOBS if j.work_mode == "remote"}
    assert await titles(work_mode="REMOTE") == expected_remote

    expected_entry = {j.title for j in SEED_JOBS if j.experience_level == "entry_level"}
    assert await titles(experience_level="entry_level") == expected_entry

    assert await titles(role="new grad") == {j.title for j in SEED_JOBS if "New Grad" in j.title}
    assert await titles(company="plaid") == {
        j.title for j in SEED_JOBS if j.company_name == "Plaid"
    }
    assert await titles(location="new york") == {
        j.title for j in SEED_JOBS if "New York" in j.location
    }

    with_deadline = {j.title for j in SEED_JOBS if j.deadline_days_ahead is not None}
    assert await titles(has_deadline="true") == with_deadline
    assert await titles(has_deadline="false") == {j.title for j in SEED_JOBS} - with_deadline

    cutoff = datetime.now(UTC) - timedelta(days=2)
    recent = {j.title for j in SEED_JOBS if j.posted_days_ago < 2}
    assert await titles(posted_after=cutoff.isoformat()) == recent

    # Filters combine with AND.
    assert await titles(work_mode="remote", experience_level="entry_level") == (
        expected_remote & expected_entry
    )

    # LIKE wildcards in input are literal, not wildcards.
    assert await titles(role="%") == set()


async def test_inactive_jobs_hidden_from_list_but_visible_in_detail(
    db_client: AsyncClient, db_session: AsyncSession, auth: dict[str, str]
) -> None:
    await seed(db_session)
    job = (await db_session.execute(select(Job).limit(1))).scalar_one()
    job.is_active = False
    await db_session.commit()

    listed = (await db_client.get("/jobs", headers=auth, params={"page_size": 100})).json()
    assert listed["total"] == 9
    assert str(job.id) not in {i["id"] for i in listed["items"]}

    detail = await db_client.get(f"/jobs/{job.id}", headers=auth)
    assert detail.status_code == 200
    assert detail.json()["is_active"] is False
    assert detail.json()["source_name"] in {"greenhouse", "lever", "ashby"}
    assert detail.json()["description"]


# --------------------------------------------------------------------------- #
# Saved jobs
# --------------------------------------------------------------------------- #


async def test_save_list_unsave_roundtrip(
    db_client: AsyncClient, db_session: AsyncSession, auth: dict[str, str]
) -> None:
    await seed(db_session)
    jobs = (await db_session.execute(select(Job).order_by(Job.title).limit(2))).scalars().all()
    first, second = jobs

    assert (await db_client.post(f"/jobs/{first.id}/save", headers=auth)).status_code == 201
    assert (await db_client.post(f"/jobs/{second.id}/save", headers=auth)).status_code == 201
    # Idempotent re-save hits the unique constraint path and returns 200.
    again = await db_client.post(f"/jobs/{first.id}/save", headers=auth)
    assert again.status_code == 200
    assert await db_session.scalar(select(func.count()).select_from(SavedJob)) == 2

    listed = await db_client.get("/saved-jobs", headers=auth)
    assert listed.status_code == 200
    body = listed.json()
    assert [item["job"]["id"] for item in body] == [str(second.id), str(first.id)]  # newest first
    assert body[0]["job"]["title"] == second.title

    assert (await db_client.delete(f"/jobs/{first.id}/save", headers=auth)).status_code == 204
    assert (await db_client.delete(f"/jobs/{first.id}/save", headers=auth)).status_code == 404
    remaining = (await db_client.get("/saved-jobs", headers=auth)).json()
    assert [item["job"]["id"] for item in remaining] == [str(second.id)]


async def test_saved_jobs_are_scoped_per_user(
    db_client: AsyncClient, db_session: AsyncSession, auth: dict[str, str]
) -> None:
    await seed(db_session)
    job = (await db_session.execute(select(Job).limit(1))).scalar_one()
    await db_client.post(f"/jobs/{job.id}/save", headers=auth)

    other = await db_client.post(
        "/auth/signup",
        json={"email": "other@example.com", "password": "correct-horse-battery", "full_name": "O"},
    )
    other_auth = {"Authorization": f"Bearer {other.json()['access_token']}"}
    assert (await db_client.get("/saved-jobs", headers=other_auth)).json() == []
    assert (await db_client.delete(f"/jobs/{job.id}/save", headers=other_auth)).status_code == 404


# --------------------------------------------------------------------------- #
# Profile
# --------------------------------------------------------------------------- #


async def test_profile_upsert_roundtrip(
    db_client: AsyncClient, db_session: AsyncSession, auth: dict[str, str]
) -> None:
    assert (await db_client.get("/profile", headers=auth)).status_code == 404

    created = await db_client.put(
        "/profile",
        headers=auth,
        json={"college": "IIT Madras", "cgpa": "8.90", "skills": ["Python", "FastAPI"]},
    )
    assert created.status_code == 201, created.text
    assert created.json()["skills"] == ["Python", "FastAPI"]
    assert created.json()["preferred_roles"] == []

    updated = await db_client.put(
        "/profile", headers=auth, json={"preferred_roles": ["backend"], "graduation_year": 2026}
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["college"] == "IIT Madras"  # untouched
    assert body["cgpa"] == "8.90"
    assert body["preferred_roles"] == ["backend"]
    assert body["graduation_year"] == 2026

    fetched = (await db_client.get("/profile", headers=auth)).json()
    assert fetched == body
    assert await db_session.scalar(select(func.count()).select_from(UserProfile)) == 1
