# NextStep.ai

[![CI](https://github.com/Phoenix8385/nextstep.ai/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Phoenix8385/nextstep.ai/actions/workflows/ci.yml)
[![Deploy Frontend](https://github.com/Phoenix8385/nextstep.ai/actions/workflows/deploy-frontend.yml/badge.svg)](https://github.com/Phoenix8385/nextstep.ai/actions/workflows/deploy-frontend.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

AI-powered job discovery, resume matching, and application tracking platform.

NextStep.ai polls public job-board APIs (Greenhouse, Lever, Ashby), normalizes
every posting into a single `jobs` table deduplicated by `content_hash`, scores
your resume against each posting with a **transparent keyword/skill-overlap
model** (no fabricated skills, ever), and tracks every application end-to-end
with a full audit trail.

## Pipeline

```
 ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
 │  Job Sources │──▶│  Ingestion   │──▶│    Dedupe    │──▶│  Dashboard   │
 │  Greenhouse  │   │  Celery beat │   │ content_hash │   │  Next.js 14  │
 │  Lever       │   │  normalize   │   │  upsert      │   │  filters     │
 │  Ashby       │   │  to jobs     │   │              │   │  search      │
 └──────────────┘   └──────────────┘   └──────────────┘   └──────┬───────┘
                                                                 │
                                                                 ▼
 ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
 │  Analytics   │◀──│   Tracker    │◀──│    Apply     │◀──│ Resume Match │
 │  funnel      │   │  status →    │   │  application │   │  spaCy +     │
 │  response    │   │  application │   │  row +       │   │  keyword     │
 │  rates       │   │  _events     │   │  first event │   │  overlap     │
 └──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘
```

Every application status change writes an `application_events` row in the
**same transaction** as the status update, so the tracker and analytics views
are always consistent.

## Tech Stack

| Layer          | Technology                                                      |
| -------------- | --------------------------------------------------------------- |
| Frontend       | Next.js 14 (App Router), TypeScript, Tailwind CSS, Zustand      |
| Auth           | NextAuth.js + JWT                                               |
| Backend API    | Python 3.11, FastAPI, Pydantic v2                               |
| ORM / DB       | SQLAlchemy 2 (async), Alembic, PostgreSQL 16 (Supabase/Railway) |
| Background     | Celery + Redis 7                                                |
| Resume Scoring | spaCy + keyword/skill overlap (v1)                              |
| File Storage   | S3-compatible object storage                                    |
| Job Sources    | Greenhouse → Lever → Ashby public APIs                          |
| Tooling        | pnpm workspaces, ruff, mypy, pytest, ESLint, TypeScript strict  |
| Hosting        | Vercel (frontend), Railway/Render (API, worker, DB, Redis)      |

## Repository Layout

```
nextstep-ai/
├── apps/
│   └── web/            # Next.js 14 frontend
├── services/
│   ├── api/            # FastAPI application
│   └── worker/         # Celery worker + beat (ingestion, matching)
├── packages/
│   └── shared/         # Shared TypeScript types / utilities
├── docker-compose.yml  # Local Postgres, Redis, API
└── pnpm-workspace.yaml
```

## Quick Start

```bash
# 1. Clone and enter the repo
git clone https://github.com/Phoenix8385/nextstep.ai.git && cd nextstep.ai

# 2. Configure environment
cp .env.example .env

# 3. Start Postgres, Redis, and the API
docker compose up -d

# 4. Run database migrations
docker compose exec api alembic upgrade head

# 5. Install and start the frontend
pnpm install && pnpm --filter web dev
```

The frontend is available at http://localhost:3000 and the API docs at
http://localhost:8000/docs.

## Backend Development (without the API container)

All commands run from `services/api` with the virtualenv active.

```bash
cd services/api

# Windows — PowerShell:  venv\Scripts\Activate.ps1
# Windows — Git Bash:    source venv/Scripts/activate
# macOS / Linux:         source venv/bin/activate

pip install -r requirements.txt
pip install -e .                       # registers the `app` package (no deps)
pip install -r ../worker/requirements.txt   # worker shares this venv

docker compose -f ../../docker-compose.yml up -d postgres redis
alembic upgrade head

python -m app.scripts.seed_jobs        # 10 sample jobs; safe to re-run
uvicorn app.main:app --reload --port 8000
```

Job discovery (`GET /jobs`, `GET /jobs/{id}`) is public. Everything tied to a
user — saved jobs, profile, resumes, applications — needs a Bearer token from
`POST /auth/signup` or `POST /auth/login` (use the **Authorize** button in
`/docs`).

Always run scripts as modules (`python -m app.scripts.<name>`), never by file
path (`python app/scripts/<name>.py`): running by path puts the script's own
directory on `sys.path` instead of `services/api`, so `import app` fails.

### Ingestion (Greenhouse / Lever / Ashby)

Register a board and pull it once, without Celery:

```bash
python -m app.scripts.ingest greenhouse stripe --dry-run          # fetch + print, no DB writes
python -m app.scripts.ingest ashby notion --company Notion --create-source
python -m app.scripts.ingest --source-id 5                         # re-sync an existing row
```

Run the worker and scheduler from the **repository root**, in the same
virtualenv; beat sweeps every active `job_sources` row every
`INGEST_INTERVAL_MINUTES` (default 20). `-A services.worker.celery_app` is a
Python import path resolved against the current directory, so running these
from `services/api` fails with `ModuleNotFoundError: No module named 'services'`:

```bash
cd /path/to/nextstep.ai            # the repository root, not services/api
celery -A services.worker.celery_app worker --loglevel=info
celery -A services.worker.celery_app beat   --loglevel=info
celery -A services.worker.celery_app call worker.ingest_all_active_sources   # sweep now
```

The rows created by `seed_jobs` are synthetic; register real boards with
`--create-source` (each ATS's public API needs only the company slug).

Checks:

```bash
ruff check . && ruff format --check . && mypy app && pytest
```

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for
details.
