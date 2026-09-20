# NextStep.ai

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
git clone https://github.com/<your-org>/nextstep-ai.git && cd nextstep-ai

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

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for
details.
