"""Application settings loaded from environment variables and ``.env``.

All configuration is centralised here so the rest of the codebase never reads
``os.environ`` directly. Values are validated once at startup by Pydantic.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]

# services/api/.env — anchored to the package so scripts, Alembic and uvicorn
# behave the same regardless of the current working directory.
ENV_FILE: Path = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """Strongly-typed application configuration.

    Environment variables take precedence over values in ``.env``. List-valued
    settings such as ``ALLOWED_ORIGINS`` are parsed from a JSON array string,
    e.g. ``ALLOWED_ORIGINS=["http://localhost:3000"]``.
    """

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- Infrastructure -----------------------------------------------------
    DATABASE_URL: str = Field(
        ...,
        description="SQLAlchemy async URL, e.g. postgresql+asyncpg://user:pass@host:5432/db",
    )
    REDIS_URL: str = Field(..., description="Redis URL used by Celery broker/result backend")

    # --- Resume storage -----------------------------------------------------
    STORAGE_BUCKET: str = Field(..., description="S3-compatible bucket for resume uploads")
    STORAGE_BACKEND: Literal["s3", "local"] = Field(
        default="local", description="'s3' for any S3-compatible service, 'local' for dev/tests"
    )
    STORAGE_ENDPOINT_URL: str | None = Field(
        default=None, description="Custom endpoint (R2, MinIO, Supabase); omit for AWS S3"
    )
    STORAGE_REGION: str = "auto"
    STORAGE_ACCESS_KEY: str | None = None
    STORAGE_SECRET_KEY: str | None = None
    STORAGE_LOCAL_DIR: Path = Field(
        default=Path(__file__).resolve().parents[2] / "uploads",
        description="Directory used by the 'local' backend",
    )
    RESUME_MAX_BYTES: int = Field(default=5 * 1024 * 1024, ge=1)

    # --- Auth ---------------------------------------------------------------
    JWT_SECRET: str = Field(..., description="HMAC secret used to sign access tokens")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60, ge=1)

    # --- Runtime ------------------------------------------------------------
    ENVIRONMENT: Environment = "development"
    ALLOWED_ORIGINS: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    APP_NAME: str = "NextStep.ai API"
    APP_VERSION: str = "0.1.0"
    LOG_LEVEL: str = "INFO"

    # --- Ingestion ----------------------------------------------------------
    INGEST_INTERVAL_MINUTES: int = Field(default=20, ge=1)
    HTTP_TIMEOUT_SECONDS: float = Field(default=30.0, gt=0)
    HTTP_RETRIES: int = Field(default=3, ge=0)
    HTTP_RETRY_BACKOFF_SECONDS: float = Field(default=1.0, ge=0)
    HTTP_USER_AGENT: str = "NextStep.ai/0.1 (+https://github.com/Phoenix8385/nextstep.ai)"
    SKILLS_DICTIONARY_PATH: Path | None = Field(
        default=None,
        description="Path to skills.json; defaults to packages/skills-dictionary/skills.json",
    )

    @field_validator("DATABASE_URL")
    @classmethod
    def _require_async_driver(cls, value: str) -> str:
        """Reject sync drivers early; the whole stack assumes asyncpg."""
        if not value.startswith("postgresql+asyncpg://"):
            msg = "DATABASE_URL must use the asyncpg driver (postgresql+asyncpg://...)"
            raise ValueError(msg)
        return value

    @field_validator("JWT_SECRET")
    @classmethod
    def _require_strong_secret(cls, value: str) -> str:
        """Enforce a minimum secret length so HS256 tokens are not trivially forgeable."""
        if len(value) < 32:
            msg = "JWT_SECRET must be at least 32 characters (generate with secrets.token_urlsafe)"
            raise ValueError(msg)
        return value

    @field_validator("ALLOWED_ORIGINS")
    @classmethod
    def _strip_origins(cls, value: list[str]) -> list[str]:
        """Normalise origins so trailing slashes never cause CORS mismatches."""
        return [origin.rstrip("/") for origin in value]

    @property
    def is_production(self) -> bool:
        """True when running with production settings."""
        return self.ENVIRONMENT == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton.

    Cached so ``.env`` is parsed once. Tests can call ``get_settings.cache_clear()``
    after mutating environment variables.
    """
    return Settings()  # required fields are supplied by env / .env


settings: Settings = get_settings()
