"""Run one ingestion by hand, without Celery.

Examples (from ``services/api`` with the venv active)::

    python -m app.scripts.ingest greenhouse stripe --dry-run
    python -m app.scripts.ingest lever plaid --company Plaid
    python -m app.scripts.ingest ashby notion --create-source
    python -m app.scripts.ingest --source-id 3

``--dry-run`` fetches and prints a summary without touching the database.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from sqlalchemy import select

from app.core.database import AsyncSessionFactory, dispose_engine
from app.models.job import JobSource
from app.services.ingestion.http import FetchError
from app.services.ingestion.pipeline import (
    SOURCES,
    run_ingestion_by_id,
    run_ingestion_for_source,
)

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch a job board and sync it into the database.")
    parser.add_argument("source", nargs="?", choices=sorted(SOURCES), help="ATS name")
    parser.add_argument("board_token", nargs="?", help="company slug on that ATS")
    parser.add_argument("--company", help="display name for jobs.company_name")
    parser.add_argument("--source-id", type=int, help="ingest an existing job_sources row by id")
    parser.add_argument("--dry-run", action="store_true", help="fetch and print; do not write")
    parser.add_argument(
        "--create-source", action="store_true", help="insert the job_sources row if missing"
    )
    parser.add_argument("--limit", type=int, default=10, help="postings to print in --dry-run")
    return parser


async def _dry_run(source: str, token: str, company: str | None, limit: int) -> int:
    adapter = SOURCES[source]
    raws = await adapter.fetch(token, company_name=company)
    postings = [adapter.normalize(raw) for raw in raws]
    print(f"{source}/{token}: {len(postings)} postings")
    for posting in postings[:limit]:
        print(
            f"  [{posting.external_job_id}] {posting.title} | {posting.location} | "
            f"{posting.work_mode} | {posting.experience_level} | "
            f"skills={posting.required_skills[:6]} | posted={posting.posted_at}"
        )
    if len(postings) > limit:
        print(f"  ... {len(postings) - limit} more")
    return 0


async def _sync(source: str, token: str, company: str | None, create: bool) -> int:
    try:
        async with AsyncSessionFactory() as session:
            row = (
                await session.execute(
                    select(JobSource).where(
                        JobSource.name == source, JobSource.board_token == token
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                if not create:
                    print(
                        f"no job_sources row for {source}/{token}; pass --create-source to add it",
                        file=sys.stderr,
                    )
                    return 2
                row = JobSource(
                    name=source, board_token=token, company_name=company, is_active=True
                )
                session.add(row)
                await session.flush()
            elif company and row.company_name != company:
                row.company_name = company
            result = await run_ingestion_for_source(session, row)
    finally:
        await dispose_engine()
    print(result.as_dict())
    return 1 if result.error else 0


async def _main(args: argparse.Namespace) -> int:
    if args.source_id is not None:
        result = await run_ingestion_by_id(args.source_id)
        print(result.as_dict())
        return 1 if result.error else 0
    if not (args.source and args.board_token):
        print("provide SOURCE BOARD_TOKEN or --source-id", file=sys.stderr)
        return 2
    if args.dry_run:
        return await _dry_run(args.source, args.board_token, args.company, args.limit)
    return await _sync(args.source, args.board_token, args.company, args.create_source)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns a process exit code."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(_main(args))
    except FetchError as exc:
        print(f"fetch failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
