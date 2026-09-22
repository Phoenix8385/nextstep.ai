"""Application tracker + analyze endpoint against real Postgres.

The key invariant under test: every status change is accompanied by an
``application_events`` row committed in the same transaction.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application, ApplicationEvent, Job, Resume, ResumeVersion, User
from app.scripts.seed_jobs import seed
from app.services.applications import InvalidStatusError, set_status


async def _first_job(db: AsyncSession) -> Job:
    await seed(db)
    return (await db.execute(select(Job).order_by(Job.title).limit(1))).scalar_one()


async def _resume_version(db: AsyncSession, user_email: str, skills: list[str]) -> ResumeVersion:
    user = (await db.execute(select(User).where(User.email == user_email))).scalar_one()
    resume = Resume(
        user_id=user.id,
        file_url="local://resumes/test.pdf",
        file_name="test.pdf",
        content_type="application/pdf",
        size_bytes=1,
    )
    db.add(resume)
    await db.flush()
    version = ResumeVersion(resume_id=resume.id, parsed_skills=skills, version_number=1)
    db.add(version)
    await db.commit()
    await db.refresh(version)
    return version


async def _events(db: AsyncSession, application_id: uuid.UUID) -> list[ApplicationEvent]:
    return list(
        (
            await db.execute(
                select(ApplicationEvent)
                .where(ApplicationEvent.application_id == application_id)
                .order_by(ApplicationEvent.id)
            )
        )
        .scalars()
        .all()
    )


# --------------------------------------------------------------------------- #
# POST /applications
# --------------------------------------------------------------------------- #


async def test_mark_as_applied_creates_application_and_event(
    db_client: AsyncClient, db_session: AsyncSession, auth: dict[str, str]
) -> None:
    job = await _first_job(db_session)

    resp = await db_client.post("/applications", headers=auth, json={"job_id": str(job.id)})

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "applied"
    assert body["applied_at"] is not None
    assert body["job"]["id"] == str(job.id)
    assert body["match_score"] is None  # no resume version supplied
    assert [e["event_type"] for e in body["events"]] == ["created"]
    assert body["events"][0]["details"] == "status=applied"

    assert await db_session.scalar(select(func.count()).select_from(Application)) == 1
    assert await db_session.scalar(select(func.count()).select_from(ApplicationEvent)) == 1


async def test_second_post_updates_instead_of_duplicating(
    db_client: AsyncClient, db_session: AsyncSession, auth: dict[str, str]
) -> None:
    job = await _first_job(db_session)
    first = await db_client.post(
        "/applications", headers=auth, json={"job_id": str(job.id), "status": "saved"}
    )
    assert first.status_code == 201

    second = await db_client.post(
        "/applications", headers=auth, json={"job_id": str(job.id), "status": "applied"}
    )
    assert second.status_code == 200  # existing application moved to a new status
    body = second.json()
    assert body["id"] == first.json()["id"]
    assert body["status"] == "applied"
    assert body["applied_at"] is not None
    assert [e["event_type"] for e in body["events"]] == ["created", "status_changed"]
    assert body["events"][1]["details"] == "saved -> applied"
    assert await db_session.scalar(select(func.count()).select_from(Application)) == 1


async def test_post_with_resume_version_stores_match_score(
    db_client: AsyncClient, db_session: AsyncSession, auth: dict[str, str]
) -> None:
    job = await _first_job(db_session)
    version = await _resume_version(db_session, "it@example.com", list(job.required_skills[:2]))

    resp = await db_client.post(
        "/applications",
        headers=auth,
        json={"job_id": str(job.id), "resume_version_id": str(version.id)},
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    expected = round(100 * 2 / len(job.required_skills))
    assert float(body["match_score"]) == expected
    assert body["resume_version_id"] == str(version.id)


async def test_post_rejects_unknown_job_and_foreign_resume(
    db_client: AsyncClient, db_session: AsyncSession, auth: dict[str, str]
) -> None:
    job = await _first_job(db_session)
    missing = await db_client.post(
        "/applications", headers=auth, json={"job_id": str(uuid.uuid4())}
    )
    assert missing.status_code == 404

    other = await db_client.post(
        "/auth/signup",
        json={"email": "other@example.com", "password": "correct-horse-battery", "full_name": "O"},
    )
    assert other.status_code == 201
    foreign = await _resume_version(db_session, "other@example.com", ["Python"])
    resp = await db_client.post(
        "/applications",
        headers=auth,
        json={"job_id": str(job.id), "resume_version_id": str(foreign.id)},
    )
    assert resp.status_code == 404  # not yours → indistinguishable from missing

    bad_status = await db_client.post(
        "/applications", headers=auth, json={"job_id": str(job.id), "status": "hired"}
    )
    assert bad_status.status_code == 422


# --------------------------------------------------------------------------- #
# PATCH /applications/{id}/status
# --------------------------------------------------------------------------- #


async def test_status_update_writes_event_in_same_transaction(
    db_client: AsyncClient, db_session: AsyncSession, auth: dict[str, str]
) -> None:
    job = await _first_job(db_session)
    created = await db_client.post("/applications", headers=auth, json={"job_id": str(job.id)})
    app_id = created.json()["id"]

    resp = await db_client.patch(
        f"/applications/{app_id}/status",
        headers=auth,
        json={
            "status": "interview",
            "notes": "Phone screen on Friday",
            "follow_up_date": "2026-10-01",
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "interview"
    assert body["notes"] == "Phone screen on Friday"
    assert body["follow_up_date"] == "2026-10-01"
    types = [e["event_type"] for e in body["events"]]
    assert types == ["created", "status_changed", "note_added", "follow_up_set"]

    events = await _events(db_session, uuid.UUID(app_id))
    assert [e.event_type for e in events] == types
    assert events[1].details == "applied -> interview"

    # Same status again: no new status event.
    again = await db_client.patch(
        f"/applications/{app_id}/status", headers=auth, json={"status": "interview"}
    )
    assert again.status_code == 200
    assert len(again.json()["events"]) == 4


async def test_status_update_is_scoped_to_owner(
    db_client: AsyncClient, db_session: AsyncSession, auth: dict[str, str]
) -> None:
    job = await _first_job(db_session)
    app_id = (
        await db_client.post("/applications", headers=auth, json={"job_id": str(job.id)})
    ).json()["id"]

    other = await db_client.post(
        "/auth/signup",
        json={"email": "other@example.com", "password": "correct-horse-battery", "full_name": "O"},
    )
    other_auth = {"Authorization": f"Bearer {other.json()['access_token']}"}
    resp = await db_client.patch(
        f"/applications/{app_id}/status", headers=other_auth, json={"status": "rejected"}
    )
    assert resp.status_code == 404
    assert (await db_client.get("/applications", headers=other_auth)).json() == []


async def test_set_status_service_rejects_unknown_status(db_session: AsyncSession) -> None:
    job = await _first_job(db_session)
    user = User(email="svc@example.com", full_name="Svc")
    db_session.add(user)
    await db_session.flush()
    application = Application(user_id=user.id, job_id=job.id, status="saved")
    db_session.add(application)
    await db_session.flush()

    try:
        set_status(db_session, application, "hired")
    except InvalidStatusError as exc:
        assert "hired" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected InvalidStatusError")

    assert set_status(db_session, application, "saved") is None  # unchanged → no event
    event = set_status(db_session, application, "applied", now=datetime(2026, 1, 1, tzinfo=UTC))
    assert event is not None and event.details == "saved -> applied"
    assert application.applied_at == datetime(2026, 1, 1, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# GET /applications
# --------------------------------------------------------------------------- #


async def test_list_applications_newest_first(
    db_client: AsyncClient, db_session: AsyncSession, auth: dict[str, str]
) -> None:
    await seed(db_session)
    jobs = (await db_session.execute(select(Job).order_by(Job.title).limit(2))).scalars().all()
    for job in jobs:
        assert (
            await db_client.post("/applications", headers=auth, json={"job_id": str(job.id)})
        ).status_code == 201

    resp = await db_client.get("/applications", headers=auth)
    assert resp.status_code == 200
    body = resp.json()
    assert [a["job"]["id"] for a in body] == [str(jobs[1].id), str(jobs[0].id)]
    assert all(a["events"] for a in body)


# --------------------------------------------------------------------------- #
# POST /jobs/{id}/analyze
# --------------------------------------------------------------------------- #


async def test_analyze_returns_match_result_for_own_resume(
    db_client: AsyncClient, db_session: AsyncSession, auth: dict[str, str]
) -> None:
    job = await _first_job(db_session)
    version = await _resume_version(db_session, "it@example.com", [job.required_skills[0]])

    resp = await db_client.post(
        f"/jobs/{job.id}/analyze", headers=auth, json={"resume_version_id": str(version.id)}
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["job_id"] == str(job.id)
    assert body["resume_version_id"] == str(version.id)
    assert body["match_score"] == round(100 / len(job.required_skills))
    assert body["matching_skills"] == [job.required_skills[0]]
    assert set(body["missing_skills"]) == set(job.required_skills[1:])
    assert body["profile_on_file"] is False
    assert body["eligibility_status"] == "uncertain"
    assert body["suggestions"]

    # With a profile, eligibility is assessed.
    await db_client.put(
        "/profile", headers=auth, json={"graduation_year": 2027, "experience_level": "student"}
    )
    with_profile = await db_client.post(
        f"/jobs/{job.id}/analyze", headers=auth, json={"resume_version_id": str(version.id)}
    )
    assert with_profile.json()["profile_on_file"] is True


async def test_analyze_404_for_unknown_job_or_foreign_resume(
    db_client: AsyncClient, db_session: AsyncSession, auth: dict[str, str]
) -> None:
    job = await _first_job(db_session)
    version = await _resume_version(db_session, "it@example.com", ["Python"])
    assert (
        await db_client.post(
            f"/jobs/{uuid.uuid4()}/analyze",
            headers=auth,
            json={"resume_version_id": str(version.id)},
        )
    ).status_code == 404
    assert (
        await db_client.post(
            f"/jobs/{job.id}/analyze", headers=auth, json={"resume_version_id": str(uuid.uuid4())}
        )
    ).status_code == 404
    assert (
        await db_client.post(f"/jobs/{job.id}/analyze", json={"resume_version_id": str(version.id)})
    ).status_code == 401
