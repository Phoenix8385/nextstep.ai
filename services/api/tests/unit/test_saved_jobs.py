"""Unit tests for saved-job endpoints (mocked session)."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError

from app.models import Job, SavedJob, User


def _get_for(user: User, job: Job | None) -> AsyncMock:
    async def _get(model: type, key: object, **_: object) -> object:
        return user if model is User else job

    return AsyncMock(side_effect=_get)


def _scalar_result(value: object) -> MagicMock:
    result = MagicMock(name="Result")
    result.scalar_one_or_none.return_value = value
    return result


def _assign_defaults(saved: SavedJob) -> None:
    saved.id = saved.id or uuid.uuid4()
    saved.saved_at = saved.saved_at or datetime.now(UTC)


async def test_save_requires_auth(client: AsyncClient) -> None:
    assert (await client.post(f"/jobs/{uuid.uuid4()}/save")).status_code == 401


async def test_save_unknown_job_404(
    client: AsyncClient, mock_session: MagicMock, fake_user: User, auth_headers: dict[str, str]
) -> None:
    mock_session.get = _get_for(fake_user, None)

    resp = await client.post(f"/jobs/{uuid.uuid4()}/save", headers=auth_headers)

    assert resp.status_code == 404
    mock_session.add.assert_not_called()


async def test_save_creates_row_201(
    client: AsyncClient,
    mock_session: MagicMock,
    fake_user: User,
    auth_headers: dict[str, str],
    make_job: Callable[..., Job],
) -> None:
    job = make_job()
    mock_session.get = _get_for(fake_user, job)
    mock_session.execute = AsyncMock(return_value=_scalar_result(None))  # not saved yet
    mock_session.refresh = AsyncMock(side_effect=_assign_defaults)

    resp = await client.post(f"/jobs/{job.id}/save", headers=auth_headers)

    assert resp.status_code == 201, resp.text
    added: SavedJob = mock_session.add.call_args.args[0]
    assert (added.user_id, added.job_id) == (fake_user.id, job.id)
    mock_session.commit.assert_awaited_once()
    body = resp.json()
    assert body["job"]["id"] == str(job.id)
    assert body["job"]["is_new"] is True
    assert body["saved_at"]


async def test_save_is_idempotent_200(
    client: AsyncClient,
    mock_session: MagicMock,
    fake_user: User,
    auth_headers: dict[str, str],
    make_job: Callable[..., Job],
) -> None:
    job = make_job()
    existing = SavedJob(
        id=uuid.uuid4(), user_id=fake_user.id, job_id=job.id, saved_at=datetime.now(UTC)
    )
    mock_session.get = _get_for(fake_user, job)
    mock_session.execute = AsyncMock(return_value=_scalar_result(existing))

    resp = await client.post(f"/jobs/{job.id}/save", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["id"] == str(existing.id)
    mock_session.add.assert_not_called()
    mock_session.commit.assert_not_awaited()


async def test_save_handles_unique_violation_race(
    client: AsyncClient,
    mock_session: MagicMock,
    fake_user: User,
    auth_headers: dict[str, str],
    make_job: Callable[..., Job],
) -> None:
    job = make_job()
    winner = SavedJob(
        id=uuid.uuid4(), user_id=fake_user.id, job_id=job.id, saved_at=datetime.now(UTC)
    )
    mock_session.get = _get_for(fake_user, job)
    # First lookup: nothing; after the constraint fires, the concurrent row is there.
    mock_session.execute = AsyncMock(side_effect=[_scalar_result(None), _scalar_result(winner)])
    mock_session.commit = AsyncMock(side_effect=IntegrityError("INSERT", {}, Exception("dup")))

    resp = await client.post(f"/jobs/{job.id}/save", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["id"] == str(winner.id)
    mock_session.rollback.assert_awaited_once()


async def test_unsave_204_and_404(
    client: AsyncClient, mock_session: MagicMock, auth_headers: dict[str, str]
) -> None:
    deleted = MagicMock(rowcount=1)
    mock_session.execute = AsyncMock(return_value=deleted)
    resp = await client.delete(f"/jobs/{uuid.uuid4()}/save", headers=auth_headers)
    assert resp.status_code == 204
    assert resp.content == b""
    mock_session.commit.assert_awaited_once()

    mock_session.execute = AsyncMock(return_value=MagicMock(rowcount=0))
    resp = await client.delete(f"/jobs/{uuid.uuid4()}/save", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Job was not saved"}


async def test_list_saved_jobs(
    client: AsyncClient,
    mock_session: MagicMock,
    fake_user: User,
    auth_headers: dict[str, str],
    make_job: Callable[..., Job],
) -> None:
    now = datetime.now(UTC)
    old_job = make_job(title="Old", detected_at=now - timedelta(days=5))
    new_job = make_job(title="New", detected_at=now)
    rows = [
        SavedJob(id=uuid.uuid4(), user_id=fake_user.id, job_id=new_job.id, saved_at=now),
        SavedJob(
            id=uuid.uuid4(),
            user_id=fake_user.id,
            job_id=old_job.id,
            saved_at=now - timedelta(hours=1),
        ),
    ]
    rows[0].job = new_job
    rows[1].job = old_job
    result = MagicMock(name="Result")
    result.scalars.return_value.all.return_value = rows
    mock_session.execute = AsyncMock(return_value=result)

    resp = await client.get("/saved-jobs", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [item["job"]["title"] for item in body] == ["New", "Old"]
    assert [item["job"]["is_new"] for item in body] == [True, False]
    sql = str(mock_session.execute.await_args.args[0])
    assert "saved_jobs.user_id = " in sql
    assert "ORDER BY saved_jobs.saved_at DESC" in sql
