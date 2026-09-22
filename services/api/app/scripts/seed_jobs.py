"""Seed ten realistic job postings so the API can be exercised before ingestion exists.

Usage (from ``services/api`` with the venv active and Postgres running)::

    python -m app.scripts.seed_jobs

Idempotent: sources are matched on ``(name, board_token)`` and jobs are
inserted with ``ON CONFLICT (source_id, external_job_id) DO NOTHING``, so
re-running never duplicates rows. All postings are synthetic; the URLs follow
each ATS's real URL shape but do not point at real openings.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionFactory, dispose_engine
from app.core.hashing import compute_content_hash
from app.models.job import Job, JobSource

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SeedSource:
    """A job board to register in ``job_sources``."""

    name: str
    board_token: str
    company_name: str


@dataclass(frozen=True)
class SeedJob:
    """One synthetic posting. ``source`` is a ``(name, board_token)`` key into SEED_SOURCES."""

    source: tuple[str, str]
    external_job_id: str
    source_url: str
    company_name: str
    title: str
    location: str
    work_mode: str
    experience_level: str
    description: str
    requirements: str
    required_skills: list[str]
    eligibility: str | None = None
    posted_days_ago: float = 1.0
    detected_hours_ago: float = 0.0
    deadline_days_ahead: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


SEED_SOURCES: tuple[SeedSource, ...] = (
    SeedSource(name="greenhouse", board_token="stripe", company_name="Stripe"),
    SeedSource(name="greenhouse", board_token="figma", company_name="Figma"),
    SeedSource(name="greenhouse", board_token="cloudflare", company_name="Cloudflare"),
    SeedSource(name="lever", board_token="spotify", company_name="Spotify"),
    SeedSource(name="ashby", board_token="plaid", company_name="Plaid"),
    SeedSource(name="ashby", board_token="notion", company_name="Notion"),
    SeedSource(name="ashby", board_token="ramp", company_name="Ramp"),
)

SEED_JOBS: tuple[SeedJob, ...] = (
    SeedJob(
        source=("greenhouse", "stripe"),
        external_job_id="6100001",
        source_url="https://boards.greenhouse.io/stripe/jobs/6100001",
        company_name="Stripe",
        title="Software Engineer, New Grad",
        location="San Francisco, CA",
        work_mode="hybrid",
        experience_level="entry_level",
        description=(
            "Join a product engineering team building the APIs that millions of businesses "
            "rely on to accept payments. New grads rotate through onboarding projects that "
            "ship to production in their first month."
        ),
        requirements=(
            "Bachelor's degree in Computer Science or equivalent, graduating by June 2027. "
            "Strong fundamentals in data structures and distributed systems. Experience with "
            "Ruby, Java, Go or Python."
        ),
        required_skills=["Python", "Java", "Go", "Distributed Systems", "SQL"],
        eligibility="Graduating class of 2026 or 2027",
        posted_days_ago=0.5,
        detected_hours_ago=0.5,
        deadline_days_ahead=45,
    ),
    SeedJob(
        source=("greenhouse", "stripe"),
        external_job_id="6100002",
        source_url="https://boards.greenhouse.io/stripe/jobs/6100002",
        company_name="Stripe",
        title="Backend Engineer, Payments Infrastructure",
        location="Remote, US",
        work_mode="remote",
        experience_level="experienced",
        description=(
            "Own reliability and throughput of the ledger services that settle every Stripe "
            "transaction. You will design idempotent APIs, run migrations on multi-terabyte "
            "Postgres clusters and lead incident reviews."
        ),
        requirements=(
            "3+ years building backend services. Deep PostgreSQL experience, including "
            "partitioning and query tuning. Comfortable with Go or Java and Kubernetes."
        ),
        required_skills=["Go", "Java", "PostgreSQL", "Kubernetes", "AWS"],
        posted_days_ago=6,
        detected_hours_ago=5 * 24,
    ),
    SeedJob(
        source=("greenhouse", "figma"),
        external_job_id="5400301",
        source_url="https://boards.greenhouse.io/figma/jobs/5400301",
        company_name="Figma",
        title="Frontend Engineer, Design Systems",
        location="New York, NY",
        work_mode="hybrid",
        experience_level="experienced",
        description=(
            "Build and maintain the component library used across Figma's web application. "
            "You will collaborate with designers on accessibility, theming and performance of "
            "a React + TypeScript codebase rendered inside a custom WebGL canvas."
        ),
        requirements=(
            "2+ years shipping production React. Strong TypeScript. Familiarity with "
            "accessibility standards (WCAG 2.1) and CSS architecture."
        ),
        required_skills=["React", "TypeScript", "CSS", "Accessibility", "WebGL"],
        posted_days_ago=3,
        detected_hours_ago=2 * 24,
    ),
    SeedJob(
        source=("greenhouse", "figma"),
        external_job_id="5400318",
        source_url="https://boards.greenhouse.io/figma/jobs/5400318",
        company_name="Figma",
        title="Software Engineering Intern, Summer 2027",
        location="San Francisco, CA",
        work_mode="onsite",
        experience_level="intern",
        description=(
            "12-week paid internship on a product team. Interns own a scoped feature end to "
            "end, pair with a dedicated mentor and present their work at the internship demo."
        ),
        requirements=(
            "Currently pursuing a BS/MS in Computer Science or related field. At least one "
            "prior internship or substantial project in JavaScript/TypeScript or C++."
        ),
        required_skills=["JavaScript", "TypeScript", "C++", "Git"],
        eligibility="Must be enrolled in a degree program through December 2027",
        posted_days_ago=1,
        detected_hours_ago=1,
        deadline_days_ahead=30,
    ),
    SeedJob(
        source=("greenhouse", "cloudflare"),
        external_job_id="4990210",
        source_url="https://boards.greenhouse.io/cloudflare/jobs/4990210",
        company_name="Cloudflare",
        title="Systems Engineer, Edge Networking",
        location="Austin, TX",
        work_mode="hybrid",
        experience_level="experienced",
        description=(
            "Work on the software that routes a significant share of global web traffic. "
            "Areas include BGP automation, DDoS mitigation pipelines and eBPF-based packet "
            "processing on the edge fleet."
        ),
        requirements=(
            "5+ years of systems programming in Rust, C or Go. Practical experience with "
            "Linux networking, TCP/IP internals and observability at scale."
        ),
        required_skills=["Rust", "Go", "C", "Linux", "Networking"],
        posted_days_ago=10,
        detected_hours_ago=9 * 24,
    ),
    SeedJob(
        source=("greenhouse", "cloudflare"),
        external_job_id="4990233",
        source_url="https://boards.greenhouse.io/cloudflare/jobs/4990233",
        company_name="Cloudflare",
        title="Data Engineer, Analytics Platform",
        location="Lisbon, Portugal",
        work_mode="remote",
        experience_level="experienced",
        description=(
            "Build the pipelines that turn trillions of daily request logs into the analytics "
            "customers see in the dashboard. Stack: Kafka, ClickHouse, Airflow, Python and Go."
        ),
        requirements=(
            "3+ years in data engineering. Production experience with Kafka and a columnar "
            "store (ClickHouse, BigQuery or Snowflake). Strong SQL and Python."
        ),
        required_skills=["Python", "SQL", "Apache Kafka", "ClickHouse", "Apache Airflow"],
        posted_days_ago=2,
        detected_hours_ago=36,
    ),
    SeedJob(
        source=("ashby", "plaid"),
        external_job_id="a3f0c2d4-7b1e-4f68-9a2c-1d5e8f0b3c71",
        source_url="https://jobs.ashbyhq.com/plaid/a3f0c2d4-7b1e-4f68-9a2c-1d5e8f0b3c71",
        company_name="Plaid",
        title="Software Engineer, Early Career",
        location="Remote, US",
        work_mode="remote",
        experience_level="entry_level",
        description=(
            "Plaid's early-career program places engineers on teams across identity, "
            "payments and data connectivity. Expect a structured 6-month ramp with weekly "
            "learning sessions and a rotation choice at the end."
        ),
        requirements=(
            "0-2 years of professional experience. Solid CS fundamentals and at least one "
            "language among Python, Go, Java or TypeScript. Interest in fintech."
        ),
        required_skills=["Python", "Go", "TypeScript", "REST API", "PostgreSQL"],
        eligibility="Open to 2025 and 2026 graduates",
        posted_days_ago=0.25,
        detected_hours_ago=0.25,
        deadline_days_ahead=21,
    ),
    SeedJob(
        source=("ashby", "plaid"),
        external_job_id="c9e4b1a2-3d5f-4e07-8b6a-2f1c0d9e7a55",
        source_url="https://jobs.ashbyhq.com/plaid/c9e4b1a2-3d5f-4e07-8b6a-2f1c0d9e7a55",
        company_name="Plaid",
        title="Machine Learning Engineer, Fraud",
        location="New York, NY",
        work_mode="hybrid",
        experience_level="experienced",
        description=(
            "Train and deploy models that flag fraudulent account linking in real time. "
            "You will own feature pipelines, online inference services and model monitoring."
        ),
        requirements=(
            "3+ years applied ML in production. Python, PyTorch or scikit-learn, feature "
            "stores and streaming systems. Experience with imbalanced classification."
        ),
        required_skills=["Python", "PyTorch", "Scikit-learn", "SQL", "Apache Kafka", "MLOps"],
        posted_days_ago=4,
        detected_hours_ago=3 * 24,
    ),
    SeedJob(
        source=("ashby", "notion"),
        external_job_id="8f2d6c4e-1a3b-4d5e-9f70-6c8b2a4e1d39",
        source_url="https://jobs.ashbyhq.com/notion/8f2d6c4e-1a3b-4d5e-9f70-6c8b2a4e1d39",
        company_name="Notion",
        title="Full Stack Engineer, Growth",
        location="San Francisco, CA",
        work_mode="onsite",
        experience_level="experienced",
        description=(
            "Run experiments across onboarding, pricing and sharing flows that move "
            "activation and retention. You will ship across the React frontend and the "
            "Node/TypeScript backend, instrumenting everything you build."
        ),
        requirements=(
            "3+ years of full-stack experience with TypeScript. Comfortable designing "
            "experiments and reading the results. Familiarity with PostgreSQL and Redis."
        ),
        required_skills=["TypeScript", "React", "Node.js", "PostgreSQL", "Redis", "A/B Testing"],
        posted_days_ago=7,
        detected_hours_ago=6 * 24,
    ),
    SeedJob(
        source=("ashby", "ramp"),
        external_job_id="2b7e9d0a-5c4f-4a1b-8e3d-9f6a0c2b7d18",
        source_url="https://jobs.ashbyhq.com/ramp/2b7e9d0a-5c4f-4a1b-8e3d-9f6a0c2b7d18",
        company_name="Ramp",
        title="Backend Engineer, New Grad",
        location="New York, NY",
        work_mode="onsite",
        experience_level="entry_level",
        description=(
            "Join Ramp's engineering team straight out of school and ship code to the "
            "platform that automates finance for thousands of companies. Python/FastAPI "
            "services on Postgres, deployed many times a day."
        ),
        requirements=(
            "Graduating in 2026 with a degree in CS or a related field. Strong Python. "
            "Internship or project experience with web services and relational databases."
        ),
        required_skills=["Python", "FastAPI", "PostgreSQL", "Docker", "SQL"],
        eligibility="2026 graduates only",
        posted_days_ago=1.5,
        detected_hours_ago=1.5,
        deadline_days_ahead=60,
    ),
)


async def _ensure_sources(session: AsyncSession) -> dict[tuple[str, str], int]:
    """Insert any missing sources and return ``(name, board_token) -> id``."""
    result = await session.execute(select(JobSource))
    rows = {(s.name, s.board_token): s for s in result.scalars().all()}

    for seed in SEED_SOURCES:
        key = (seed.name, seed.board_token)
        source = rows.get(key)
        if source is None:
            source = JobSource(
                name=seed.name,
                board_token=seed.board_token,
                company_name=seed.company_name,
                is_active=True,
            )
            session.add(source)
            await session.flush()
            rows[key] = source
        elif source.company_name is None:
            source.company_name = seed.company_name
    return {key: source.id for key, source in rows.items()}


def build_job_values(seed: SeedJob, *, source_id: int, now: datetime) -> dict[str, Any]:
    """Translate a :class:`SeedJob` into column values for ``jobs``."""
    return {
        "source_id": source_id,
        "external_job_id": seed.external_job_id,
        "source_url": seed.source_url,
        "company_name": seed.company_name,
        "title": seed.title,
        "location": seed.location,
        "work_mode": seed.work_mode,
        "experience_level": seed.experience_level,
        "description": seed.description,
        "requirements": seed.requirements,
        "required_skills": list(seed.required_skills),
        "eligibility": seed.eligibility,
        "posted_at": now - timedelta(days=seed.posted_days_ago),
        "detected_at": now - timedelta(hours=seed.detected_hours_ago),
        "deadline": (
            now + timedelta(days=seed.deadline_days_ahead)
            if seed.deadline_days_ahead is not None
            else None
        ),
        "content_hash": compute_content_hash(
            company_name=seed.company_name,
            title=seed.title,
            location=seed.location,
            description=seed.description,
        ),
        "is_active": True,
        **seed.extra,
    }


async def seed(session: AsyncSession, *, now: datetime | None = None) -> tuple[int, int]:
    """Seed sources and jobs; commit; return ``(sources_total, jobs_inserted)``."""
    now = now or datetime.now(UTC)
    source_ids = await _ensure_sources(session)

    inserted = 0
    for seed_job in SEED_JOBS:
        values = build_job_values(seed_job, source_id=source_ids[seed_job.source], now=now)
        stmt = (
            pg_insert(Job)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["source_id", "external_job_id"])
        )
        result = await session.execute(stmt)
        inserted += result.rowcount

    await session.commit()
    return len(source_ids), inserted


async def main() -> None:
    """CLI entry point."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    async with AsyncSessionFactory() as session:
        sources, inserted = await seed(session)
    await dispose_engine()
    logger.info(
        "Seed complete: %d sources present, %d of %d jobs inserted (%d already existed)",
        sources,
        inserted,
        len(SEED_JOBS),
        len(SEED_JOBS) - inserted,
    )


if __name__ == "__main__":
    asyncio.run(main())
