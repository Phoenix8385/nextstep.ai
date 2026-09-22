"""Pin environment variables before the worker modules import ``app``."""

import os

TEST_ENV: dict[str, str] = {
    "DATABASE_URL": "postgresql+asyncpg://nextstep:localdevpassword@localhost:5432/nextstep_test",
    "REDIS_URL": "redis://localhost:6379/1",
    "JWT_SECRET": "test-secret-that-is-definitely-longer-than-32-chars",
    "ENVIRONMENT": "test",
    "ALLOWED_ORIGINS": '["http://localhost:3000"]',
    "STORAGE_BUCKET": "nextstep-resumes-test",
    "INGEST_INTERVAL_MINUTES": "20",
}
os.environ.update(TEST_ENV)
