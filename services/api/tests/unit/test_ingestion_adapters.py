"""Lever and Ashby adapters, text helpers, field inference, and the source registry."""

from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest

from app.services.ingestion.ashby import JOB_BOARD_URL, fetch_ashby, normalize_ashby
from app.services.ingestion.http import FetchError, fallback_company_name
from app.services.ingestion.lever import POSTINGS_URL, fetch_lever, normalize_lever
from app.services.ingestion.pipeline import SOURCES
from app.services.ingestion.schema import NormalizedJob
from app.services.ingestion.text import (
    extract_requirements,
    html_to_text,
    infer_experience_level,
    infer_work_mode,
)
from tests.conftest import Route, load_fixture

MockHttp = Callable[[dict[str, Route]], httpx.AsyncClient]

LEVER = POSTINGS_URL.format(company="acme")
ASHBY = JOB_BOARD_URL.format(board="acme")


# --------------------------------------------------------------------------- #
# Registry / helpers
# --------------------------------------------------------------------------- #


def test_registry_covers_the_three_sources() -> None:
    assert set(SOURCES) == {"greenhouse", "lever", "ashby"}
    for adapter in SOURCES.values():
        assert callable(adapter.fetch) and callable(adapter.normalize)


def test_fallback_company_name() -> None:
    assert fallback_company_name("stripe") == "Stripe"
    assert fallback_company_name("acme-corp") == "Acme Corp"
    assert fallback_company_name("big_data_co") == "Big Data Co"


# --------------------------------------------------------------------------- #
# Lever
# --------------------------------------------------------------------------- #


async def test_lever_fetch_and_normalize(mock_http: MockHttp) -> None:
    http = mock_http({LEVER: (200, load_fixture("lever_postings.json"))})
    raws = await fetch_lever("acme", company_name="Acme", http=http)
    assert "mode=json" in http.calls[0]  # type: ignore[attr-defined]
    jobs = [normalize_lever(r) for r in raws]
    assert len(jobs) == 2

    ml = jobs[0]
    assert ml.external_job_id == "a1b2c3d4-0000-4000-8000-000000000001"
    assert ml.title == "Machine Learning Engineer"
    assert ml.company_name == "Acme"
    assert ml.location == "New York, NY"
    assert ml.work_mode == "hybrid"  # workplaceType overrides the city
    assert ml.experience_level is None  # no seniority keyword in the title
    assert ml.description is not None
    assert ml.description.startswith("Build fraud models.")
    assert "What you'll bring\n- 3+ years applied ML\n- PyTorch and SQL" in ml.description
    assert ml.description.endswith("We are an equal opportunity employer.")
    assert ml.requirements == "- 3+ years applied ML\n- PyTorch and SQL"
    assert set(ml.required_skills) >= {"Machine Learning", "PyTorch", "SQL", "Apache Kafka"}
    assert ml.posted_at == datetime.fromtimestamp(1757894400, tz=UTC)

    early = jobs[1]
    assert early.work_mode == "remote"  # "unspecified" hint ignored; location says Remote
    assert early.experience_level == "entry_level"  # "Early Career"
    assert early.requirements is None


async def test_lever_company_name_falls_back_to_token(mock_http: MockHttp) -> None:
    http = mock_http({LEVER: (200, load_fixture("lever_postings.json"))})
    raws = await fetch_lever("acme-labs", http=http)
    assert {normalize_lever(r).company_name for r in raws} == {"Acme Labs"}


async def test_lever_wrong_shape_raises_fetch_error(mock_http: MockHttp) -> None:
    http = mock_http({LEVER: (200, {"not": "a list"})})
    with pytest.raises(FetchError, match="unexpected payload shape"):
        await fetch_lever("acme", company_name="Acme", http=http)


# --------------------------------------------------------------------------- #
# Ashby
# --------------------------------------------------------------------------- #


async def test_ashby_fetch_skips_unlisted_and_normalizes(mock_http: MockHttp) -> None:
    http = mock_http({ASHBY: (200, load_fixture("ashby_jobs.json"))})
    raws = await fetch_ashby("acme", company_name="Acme", http=http)
    jobs = [normalize_ashby(r) for r in raws]

    assert [j.title for j in jobs] == [
        "Full Stack Engineer, Growth",
        "Backend Engineer",
        "Engineering Intern (Summer)",
    ]  # "Hidden Role" (isListed=false) excluded

    growth = jobs[0]
    assert growth.location == "San Francisco"
    assert growth.work_mode == "onsite"
    assert growth.requirements == "- 3+ years full-stack\n- PostgreSQL and Redis"
    assert set(growth.required_skills) >= {"TypeScript", "React", "PostgreSQL", "Redis"}
    assert growth.posted_at == datetime(2026, 9, 14, 17, 0, tzinfo=UTC)

    backend = jobs[1]
    assert backend.location == "London, UK"  # secondaryLocations fallback
    assert backend.work_mode == "remote"  # isRemote=true wins over the city
    assert backend.required_skills == ["Go"]

    assert jobs[2].experience_level == "intern"  # employmentType hint


async def test_ashby_404_raises_fetch_error(mock_http: MockHttp) -> None:
    with pytest.raises(FetchError, match="board not found"):
        await fetch_ashby("nobody", company_name="Nobody", http=mock_http({}))


# --------------------------------------------------------------------------- #
# NormalizedJob inference
# --------------------------------------------------------------------------- #


def test_normalized_job_infers_missing_fields_and_dedupes_skills() -> None:
    job = NormalizedJob(
        external_job_id="1",
        source_url="https://x/1",
        company_name="Acme",
        title="Senior Engineer",
        location="Remote - EU",
        required_skills=["Python", "python ", "SQL"],
        posted_at=datetime(2026, 1, 1, 12, 0),  # naive → UTC
    )
    assert job.work_mode == "remote"
    assert job.experience_level == "experienced"
    assert job.required_skills == ["Python", "SQL"]
    assert job.posted_at == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert len(job.content_hash) == 64


def test_normalized_job_drops_skill_equal_to_company_name() -> None:
    job = NormalizedJob(
        external_job_id="1",
        source_url="https://x/1",
        company_name="Figma",
        title="Product Designer",
        required_skills=["Figma", "Prototyping", "figma"],
    )
    assert job.required_skills == ["Prototyping"]


def test_normalized_job_respects_explicit_values() -> None:
    job = NormalizedJob(
        external_job_id="1",
        source_url="https://x/1",
        company_name="Acme",
        title="Senior Engineer",
        location="Remote",
        work_mode="hybrid",
        experience_level="intern",
    )
    assert (job.work_mode, job.experience_level) == ("hybrid", "intern")


# --------------------------------------------------------------------------- #
# Text helpers
# --------------------------------------------------------------------------- #


def test_html_to_text_blocks_lists_entities_and_scripts() -> None:
    html = (
        "<h2>Role</h2><p>Build &amp; ship.</p><ul><li>One</li><li>Two</li></ul><script>x()</script>"
    )
    assert html_to_text(html) == "Role\n\nBuild & ship.\n\n- One\n- Two"
    assert html_to_text("&lt;p&gt;Hello &amp;amp; bye&lt;/p&gt;") == "Hello & bye"
    assert html_to_text("<p>a \u00a0 \t b</p>") == "a b"
    assert html_to_text("<p></p>") is None
    assert html_to_text(None) is None


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"location": "Remote - US"}, "remote"),
        ({"location": "New York (Hybrid)"}, "hybrid"),
        ({"location": "Austin, TX"}, "onsite"),
        ({"location": None}, None),
        ({"location": "Austin, TX", "title": "Engineer (Remote)"}, "remote"),
        ({"location": "Austin, TX", "hint": "hybrid"}, "hybrid"),
        ({"location": "Remote", "hint": "unspecified"}, "remote"),
        ({"location": None, "description": "We are a remote-first company."}, "remote"),
        ({"location": "Berlin", "description": "Remote work is not offered."}, "onsite"),
    ],
)
def test_infer_work_mode(kwargs: dict[str, str | None], expected: str | None) -> None:
    assert infer_work_mode(**kwargs) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("title", "hint", "expected"),
    [
        ("Software Engineering Intern", None, "intern"),
        ("Engineer", "Intern", "intern"),
        ("Senior Intern", None, "intern"),
        ("Software Engineer, New Grad", None, "entry_level"),
        ("Junior Developer", None, "entry_level"),
        ("Software Engineer I", None, "entry_level"),
        ("Software Engineer II, Payments", None, "experienced"),
        ("Engineer III", None, "experienced"),
        ("Senior Data Engineer", None, "experienced"),
        ("Staff Engineer", None, "experienced"),
        ("Engineering Manager", None, "experienced"),
        ("i am an engineer", None, None),  # lowercase "i" is not level I
        ("IV Therapy Nurse", None, None),  # leading IV is not a level
        ("Backend Engineer", None, None),
    ],
)
def test_infer_experience_level(title: str, hint: str | None, expected: str | None) -> None:
    assert infer_experience_level(title=title, hint=hint) == expected


def test_extract_requirements() -> None:
    text = "About us\n\nWe build.\n\nRequirements:\n\n- Python\n- SQL\n\nBenefits\n\nHealth."
    assert extract_requirements(text) == "- Python\n- SQL"
    assert extract_requirements("What you\u2019ll bring\n- Grit") == "- Grit"
    assert extract_requirements("Nothing here.") is None
    assert extract_requirements(None) is None
