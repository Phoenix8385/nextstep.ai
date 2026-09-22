"""Unit tests for ``/profile`` (mocked session)."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from httpx import AsyncClient

from app.models import User, UserProfile


def _get_side_effect(user: User, profile: UserProfile | None) -> AsyncMock:
    """``session.get`` that returns the user for ``User`` lookups and ``profile`` otherwise."""

    async def _get(model: type, key: object, **_: object) -> object:
        return user if model is User else profile

    return AsyncMock(side_effect=_get)


async def test_get_profile_requires_auth(client: AsyncClient) -> None:
    assert (await client.get("/profile")).status_code == 401


async def test_get_profile_404_when_missing(
    client: AsyncClient, mock_session: MagicMock, fake_user: User, auth_headers: dict[str, str]
) -> None:
    mock_session.get = _get_side_effect(fake_user, None)

    resp = await client.get("/profile", headers=auth_headers)

    assert resp.status_code == 404
    assert resp.json() == {"detail": "Profile not created yet"}


async def test_get_profile_returns_row(
    client: AsyncClient, mock_session: MagicMock, fake_user: User, auth_headers: dict[str, str]
) -> None:
    profile = UserProfile(
        user_id=fake_user.id,
        college="IIT Bombay",
        branch="CSE",
        cgpa=Decimal("8.75"),
        graduation_year=2026,
        experience_level="entry",
        preferred_roles=["backend"],
        preferred_locations=["Remote"],
        preferred_work_mode=["remote"],
        skills=["python", "sql"],
    )
    mock_session.get = _get_side_effect(fake_user, profile)

    resp = await client.get("/profile", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == str(fake_user.id)
    assert body["cgpa"] == "8.75"
    assert body["skills"] == ["python", "sql"]


async def test_put_creates_profile_with_201(
    client: AsyncClient, mock_session: MagicMock, fake_user: User, auth_headers: dict[str, str]
) -> None:
    mock_session.get = _get_side_effect(fake_user, None)
    mock_session.refresh = AsyncMock()

    resp = await client.put(
        "/profile",
        headers=auth_headers,
        json={
            "college": "  NIT Trichy ",
            "cgpa": "9.10",
            "graduation_year": 2027,
            "skills": ["Python", " python", "", "SQL"],
        },
    )

    assert resp.status_code == 201, resp.text
    created: UserProfile = mock_session.add.call_args.args[0]
    assert created.user_id == fake_user.id
    assert created.college == "NIT Trichy"  # stripped
    assert created.cgpa == Decimal("9.10")
    assert created.graduation_year == 2027
    assert created.skills == ["Python", "SQL"]  # blanks dropped, case-insensitive dedupe
    mock_session.commit.assert_awaited_once()
    body = resp.json()
    assert body["skills"] == ["Python", "SQL"]
    assert body["preferred_roles"] == []  # untouched lists serialise as empty, not null


async def test_put_merges_only_supplied_fields(
    client: AsyncClient, mock_session: MagicMock, fake_user: User, auth_headers: dict[str, str]
) -> None:
    existing = UserProfile(
        user_id=fake_user.id,
        college="IIT Bombay",
        cgpa=Decimal("8.75"),
        graduation_year=2026,
        preferred_roles=["backend"],
        preferred_locations=[],
        preferred_work_mode=[],
        skills=["python"],
    )
    mock_session.get = _get_side_effect(fake_user, existing)
    mock_session.refresh = AsyncMock()

    resp = await client.put(
        "/profile",
        headers=auth_headers,
        json={"preferred_work_mode": ["remote", "hybrid"], "college": None},
    )

    assert resp.status_code == 200, resp.text
    mock_session.add.assert_not_called()
    assert existing.preferred_work_mode == ["remote", "hybrid"]  # updated
    assert existing.college is None  # explicitly cleared
    assert existing.cgpa == Decimal("8.75")  # omitted → untouched
    assert existing.graduation_year == 2026
    assert existing.skills == ["python"]
    mock_session.commit.assert_awaited_once()


async def test_put_rejects_out_of_range_values(
    client: AsyncClient, mock_session: MagicMock, fake_user: User, auth_headers: dict[str, str]
) -> None:
    mock_session.get = _get_side_effect(fake_user, None)

    too_high_cgpa = await client.put("/profile", headers=auth_headers, json={"cgpa": "10.00"})
    assert too_high_cgpa.status_code == 422  # NUMERIC(3,2) cannot store 10.00

    bad_year = await client.put("/profile", headers=auth_headers, json={"graduation_year": 1800})
    assert bad_year.status_code == 422

    too_precise = await client.put("/profile", headers=auth_headers, json={"cgpa": "8.123"})
    assert too_precise.status_code == 422

    mock_session.commit.assert_not_awaited()
