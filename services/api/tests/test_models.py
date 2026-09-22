"""Schema-level tests for the ORM models.

These run without a database: they inspect ``Base.metadata`` to assert the
tables, columns, types and constraints match the agreed schema, and that every
``relationship()`` resolves (a broken ``back_populates`` fails at configure time).
"""

import uuid

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import configure_mappers

import app.models  # noqa: F401
from app.core.database import Base
from app.models import Application, ApplicationStatus, Job, User

EXPECTED_TABLES: set[str] = {
    "users",
    "user_profiles",
    "resumes",
    "resume_versions",
    "job_sources",
    "jobs",
    "job_change_log",
    "saved_jobs",
    "applications",
    "application_events",
}


def _table(name: str):  # type: ignore[no-untyped-def]  # sqlalchemy.Table is fine
    return Base.metadata.tables[name]


def _unique_constraints(name: str) -> set[tuple[str, ...]]:
    return {
        tuple(col.name for col in c.columns)
        for c in _table(name).constraints
        if isinstance(c, UniqueConstraint)
    }


def test_all_mappers_configure() -> None:
    configure_mappers()


def test_all_tables_present() -> None:
    assert EXPECTED_TABLES <= set(Base.metadata.tables)


def test_uuid_primary_keys_default_to_uuid4() -> None:
    for name in ("users", "resumes", "resume_versions", "jobs", "saved_jobs", "applications"):
        pk = _table(name).primary_key.columns
        assert [c.name for c in pk] == ["id"], name
        col = pk["id"]
        assert isinstance(col.type, UUID), name
        # SQLAlchemy wraps zero-arg callables in a context-taking adapter, so call it.
        assert col.default is not None and col.default.is_callable, name
        assert isinstance(col.default.arg(None), uuid.UUID), name  # type: ignore[union-attr]


def test_serial_primary_keys() -> None:
    for name in ("job_sources", "job_change_log", "application_events"):
        col = _table(name).primary_key.columns["id"]
        assert isinstance(col.type, Integer), name
        assert col.autoincrement in (True, "auto"), name


def test_timestamps_are_timezone_aware() -> None:
    checks = {
        "users": ["created_at"],
        "resumes": ["created_at"],
        "resume_versions": ["created_at"],
        "job_sources": ["last_fetched_at"],
        "jobs": ["posted_at", "detected_at", "deadline", "updated_at"],
        "job_change_log": ["changed_at"],
        "saved_jobs": ["saved_at"],
        "applications": ["applied_at", "created_at", "updated_at"],
        "application_events": ["event_time"],
    }
    for table, columns in checks.items():
        for column in columns:
            col_type = _table(table).columns[column].type
            assert isinstance(col_type, DateTime) and col_type.timezone, f"{table}.{column}"


def test_users_schema() -> None:
    t = _table("users")
    assert t.columns["email"].unique is True
    assert t.columns["hashed_password"].nullable is True
    assert t.columns["full_name"].nullable is False


def test_user_profiles_schema() -> None:
    t = _table("user_profiles")
    assert [c.name for c in t.primary_key.columns] == ["user_id"]
    fk = next(iter(t.columns["user_id"].foreign_keys))
    assert fk.target_fullname == "users.id"
    assert isinstance(t.columns["cgpa"].type, Numeric)
    assert (t.columns["cgpa"].type.precision, t.columns["cgpa"].type.scale) == (3, 2)
    assert isinstance(t.columns["graduation_year"].type, Integer)
    for arr in ("preferred_roles", "preferred_locations", "preferred_work_mode", "skills"):
        assert isinstance(t.columns[arr].type, ARRAY), arr
        assert isinstance(t.columns[arr].type.item_type, Text), arr


def test_resume_versions_schema() -> None:
    t = _table("resume_versions")
    assert isinstance(t.columns["parsed_skills"].type, ARRAY)
    for j in ("parsed_education", "parsed_experience", "parsed_projects"):
        assert isinstance(t.columns[j].type, JSONB), j
    assert t.columns["version_number"].default.arg == 1  # type: ignore[union-attr]
    fk = next(iter(t.columns["resume_id"].foreign_keys))
    assert fk.target_fullname == "resumes.id"


def test_job_sources_schema() -> None:
    t = _table("job_sources")
    assert isinstance(t.columns["is_active"].type, Boolean)
    assert t.columns["is_active"].default.arg is True  # type: ignore[union-attr]


def test_jobs_schema_and_dedupe_constraints() -> None:
    t = _table("jobs")
    assert ("source_id", "external_job_id") in _unique_constraints("jobs")
    assert isinstance(t.columns["required_skills"].type, ARRAY)
    assert t.columns["content_hash"].nullable is False
    assert any(
        [c.name for c in ix.columns] == ["content_hash"] for ix in t.indexes
    ), "content_hash must be indexed for dedupe lookups"
    assert t.columns["detected_at"].server_default is not None
    assert t.columns["updated_at"].server_default is not None
    assert t.columns["updated_at"].onupdate is not None
    fk = next(iter(t.columns["source_id"].foreign_keys))
    assert fk.target_fullname == "job_sources.id"


def test_job_change_log_schema() -> None:
    t = _table("job_change_log")
    fk = next(iter(t.columns["job_id"].foreign_keys))
    assert fk.target_fullname == "jobs.id"
    assert t.columns["changed_at"].server_default is not None


def test_saved_jobs_unique_per_user_and_job() -> None:
    assert ("user_id", "job_id") in _unique_constraints("saved_jobs")


def test_applications_schema() -> None:
    t = _table("applications")
    assert t.columns["status"].default.arg == "saved"  # type: ignore[union-attr]
    assert t.columns["resume_version_id"].nullable is True
    fk = next(iter(t.columns["resume_version_id"].foreign_keys))
    assert fk.target_fullname == "resume_versions.id"
    score = t.columns["match_score"]
    assert isinstance(score.type, Numeric) and score.nullable
    assert (score.type.precision, score.type.scale) == (5, 2)
    assert isinstance(t.columns["follow_up_date"].type, Date)
    assert t.columns["applied_at"].nullable is True
    assert t.columns["updated_at"].onupdate is not None


def test_application_events_schema() -> None:
    t = _table("application_events")
    fk = next(iter(t.columns["application_id"].foreign_keys))
    assert fk.target_fullname == "applications.id"
    assert t.columns["event_type"].nullable is False
    assert t.columns["event_time"].server_default is not None


def test_relationship_wiring() -> None:
    assert User.profile.property.back_populates == "user"
    assert User.applications.property.mapper.class_ is Application
    assert Job.applications.property.back_populates == "job"
    assert Application.events.property.cascade.delete_orphan is True
    assert Application.resume_version.property.back_populates == "applications"


def test_application_status_enum_default_matches_column() -> None:
    assert ApplicationStatus.SAVED.value == "saved"
    assert "applied_pending_confirmation" in {s.value for s in ApplicationStatus}
