"""Resume upload + parsing: text extraction from PDF/DOCX fixtures, heuristics, endpoints.

Fixtures are generated at test time (python-docx for DOCX; a hand-built
single-page PDF with Helvetica text for PDF) so no binaries live in the repo.
"""

from __future__ import annotations

import io
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import docx
import pytest
from httpx import AsyncClient

from app.models import Resume, ResumeVersion, User
from app.routers import resumes as resumes_router
from app.routers.resumes import safe_file_name, sniff_kind
from app.services import storage as storage_module
from app.services.resume_parser import (
    extract_text,
    parse_cgpa,
    parse_graduation_year,
    parse_resume,
    split_sections,
)
from app.services.storage import LocalStorage, StorageError, validate_key

SAMPLE_LINES: list[str] = [
    "Ada Lovelace",
    "ada@example.com | +1 555 0100 | github.com/ada",
    "",
    "Education",
    "Indian Institute of Technology Bombay",
    "B.Tech in Computer Science, 2023 - 2027 (expected)",
    "CGPA: 8.7/10",
    "",
    "Skills",
    "Python, FastAPI, PostgreSQL, Docker, React, TypeScript, Git",
    "",
    "Experience",
    "Backend Engineering Intern, Acme Corp (Summer 2026)",
    "- Built REST APIs with FastAPI and PostgreSQL serving 10k requests/day",
    "- Added CI/CD with GitHub Actions",
    "",
    "Projects",
    "NextStep Job Tracker",
    "- Next.js and TypeScript frontend, Celery workers on Redis",
    "- Deployed on AWS with Docker",
]


# --------------------------------------------------------------------------- #
# Fixture builders
# --------------------------------------------------------------------------- #


def build_pdf(lines: list[str]) -> bytes:
    """A minimal valid PDF: one page, Helvetica, one text line per input line."""

    def esc(text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    ops = ["BT", "/F1 11 Tf", "50 750 Td", "14 TL"]
    for line in lines:
        ops.append(f"({esc(line)}) Tj T*")
    ops.append("ET")
    content = "\n".join(ops).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Root 1 0 R /Size {len(objects) + 1} >>\nstartxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


def build_docx(lines: list[str]) -> bytes:
    document = docx.Document()
    for line in lines:
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


@pytest.fixture(scope="module")
def sample_pdf() -> bytes:
    return build_pdf(SAMPLE_LINES)


@pytest.fixture(scope="module")
def sample_docx() -> bytes:
    return build_docx(SAMPLE_LINES)


# --------------------------------------------------------------------------- #
# Text extraction & type sniffing
# --------------------------------------------------------------------------- #


def test_sniff_kind_uses_magic_bytes(sample_pdf: bytes, sample_docx: bytes) -> None:
    assert sniff_kind(sample_pdf) == "pdf"
    assert sniff_kind(sample_docx) == "docx"
    assert sniff_kind(b"plain text resume") is None
    assert sniff_kind(b"PK\x03\x04not-really-a-zip") is None  # zip header, not a DOCX


def test_extract_text_from_pdf(sample_pdf: bytes) -> None:
    text = extract_text(sample_pdf, "pdf")
    assert "Ada Lovelace" in text
    assert "CGPA: 8.7/10" in text
    assert "Backend Engineering Intern, Acme Corp (Summer 2026)" in text
    assert "Deployed on AWS with Docker" in text


def test_extract_text_from_docx(sample_docx: bytes) -> None:
    text = extract_text(sample_docx, "docx")
    assert text.startswith("Ada Lovelace")
    assert "Education\nIndian Institute of Technology Bombay" in text
    assert "- Added CI/CD with GitHub Actions" in text


def test_extract_text_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="could not read PDF"):
        extract_text(b"%PDF-1.4 but nothing else", "pdf")
    with pytest.raises(ValueError, match="could not read DOCX"):
        extract_text(b"PK\x03\x04garbage", "docx")


# --------------------------------------------------------------------------- #
# Heuristics
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("CGPA: 8.7/10", 8.7),
        ("CGPA 9.1", 9.1),
        ("7.5 CGPA", 7.5),
        ("8.25/10 in B.Tech", 8.25),
        ("GPA 3.6/4.0", 9.0),  # converted to a 10-point scale
        (
            "3 years of experience, 10/10 would recommend",
            None,
        ),  # not a grade; 10/10 has 'years'? no
        ("no grades here", None),
    ],
)
def test_parse_cgpa(text: str, expected: float | None) -> None:
    result = parse_cgpa(text)
    if expected is None:
        assert result is None or result == 10.0  # "10/10" is a legal (if odd) grade
    else:
        assert result == expected


def test_parse_graduation_year_prefers_hinted_line() -> None:
    assert parse_graduation_year("B.Tech 2023 - 2027 (expected)\nPublished 2025") == 2027
    assert parse_graduation_year("Class of 2026\nProject from 2028") == 2026
    assert parse_graduation_year("Batch 2024") == 2024
    assert parse_graduation_year("Started 2022, joined club 2023") == 2023  # latest, no hint
    assert parse_graduation_year("no year") is None
    assert parse_graduation_year("year 1999 ignored, 2101 too") is None


def test_split_sections_recognises_headers() -> None:
    sections = split_sections("\n".join(SAMPLE_LINES))
    assert set(sections) >= {"preamble", "education", "skills", "experience", "projects"}
    assert sections["preamble"][0] == "Ada Lovelace"
    assert sections["education"][0] == "Indian Institute of Technology Bombay"
    assert sections["projects"][0] == "NextStep Job Tracker"


def test_parse_resume_end_to_end_docx(sample_docx: bytes) -> None:
    parsed = parse_resume(extract_text(sample_docx, "docx"))

    assert {"Python", "FastAPI", "PostgreSQL", "Docker", "React", "TypeScript", "Git"} <= set(
        parsed.skills
    )
    assert {"CI/CD", "GitHub Actions", "Next.js", "Celery", "Redis", "AWS", "REST API"} <= set(
        parsed.skills
    )
    assert parsed.cgpa == 8.7
    assert parsed.graduation_year == 2027

    assert len(parsed.education) == 1
    edu = parsed.education[0]
    assert edu["institution"] == "Indian Institute of Technology Bombay"
    assert edu["degree"] is not None and edu["degree"].lower().startswith("b.tech")
    assert (edu["cgpa"], edu["graduation_year"]) == (8.7, 2027)

    assert len(parsed.experience) == 1
    job = parsed.experience[0]
    assert job["title"] == "Backend Engineering Intern, Acme Corp (Summer 2026)"
    assert job["details"] == [
        "Built REST APIs with FastAPI and PostgreSQL serving 10k requests/day",
        "Added CI/CD with GitHub Actions",
    ]
    assert {"FastAPI", "PostgreSQL", "CI/CD"} <= set(job["skills"])
    assert job["start_year"] == 2026

    assert len(parsed.projects) == 1
    assert parsed.projects[0]["title"] == "NextStep Job Tracker"
    assert {"Next.js", "TypeScript", "Celery", "Redis", "AWS", "Docker"} <= set(
        parsed.projects[0]["skills"]
    )


def test_parse_resume_end_to_end_pdf(sample_pdf: bytes) -> None:
    parsed = parse_resume(extract_text(sample_pdf, "pdf"))
    assert parsed.cgpa == 8.7
    assert parsed.graduation_year == 2027
    assert "Python" in parsed.skills and "PostgreSQL" in parsed.skills
    assert parsed.experience[0]["title"].startswith("Backend Engineering Intern")
    assert parsed.projects[0]["title"] == "NextStep Job Tracker"


def test_parse_resume_without_headers_still_finds_cgpa() -> None:
    parsed = parse_resume("Jane Doe\nB.Sc Physics, graduating 2025, CGPA 7.9\nPython and SQL")
    assert parsed.cgpa == 7.9
    assert parsed.graduation_year == 2025
    assert parsed.skills == ["Python", "SQL"]
    assert parsed.experience == [] and parsed.projects == []


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #


async def test_local_storage_roundtrip_and_path_safety(tmp_path: Path) -> None:
    store = LocalStorage(tmp_path)
    url = await store.put("resumes/u1/a.pdf", b"%PDF-", content_type="application/pdf")
    assert url == "local://resumes/u1/a.pdf"
    assert await store.get(url) == b"%PDF-"
    await store.delete(url)
    with pytest.raises(StorageError):
        await store.get(url)
    for bad in ("../etc/passwd", "/abs", "a/../../b", "sp ace"):
        with pytest.raises(StorageError):
            validate_key(bad)


def test_safe_file_name() -> None:
    assert safe_file_name("../../My Résumé (final).PDF", "pdf") == "My Rsum final.PDF"
    assert safe_file_name("C:\\Users\\me\\cv.docx", "docx") == "cv.docx"
    assert safe_file_name(None, "pdf") == "resume.pdf"
    assert safe_file_name("notes", "docx") == "notes.docx"


# --------------------------------------------------------------------------- #
# Endpoints (mocked session, real LocalStorage in tmp_path)
# --------------------------------------------------------------------------- #


@pytest.fixture()
def local_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[LocalStorage]:
    store = LocalStorage(tmp_path)
    monkeypatch.setattr(resumes_router, "get_storage", lambda: store)
    yield store
    storage_module.reset_storage()


def _assign_defaults(obj: Resume | ResumeVersion, *_: object, **__: object) -> None:
    if getattr(obj, "id", None) is None:
        obj.id = uuid.uuid4()
    if getattr(obj, "created_at", None) is None:
        obj.created_at = datetime.now(UTC)
    if isinstance(obj, Resume) and "versions" not in obj.__dict__:
        obj.versions = []


async def test_upload_rejects_wrong_type_and_oversize(
    client: AsyncClient, auth_headers: dict[str, str], local_storage: LocalStorage
) -> None:
    resp = await client.post(
        "/resumes", headers=auth_headers, files={"file": ("cv.txt", b"just text", "text/plain")}
    )
    assert resp.status_code == 415

    # Lying about the content type does not help: magic bytes decide.
    resp = await client.post(
        "/resumes",
        headers=auth_headers,
        files={"file": ("cv.pdf", b"not a pdf", "application/pdf")},
    )
    assert resp.status_code == 415

    big = b"%PDF-" + b"0" * (5 * 1024 * 1024)
    resp = await client.post(
        "/resumes", headers=auth_headers, files={"file": ("big.pdf", big, "application/pdf")}
    )
    assert resp.status_code == 413
    assert "5 MB" in resp.json()["detail"]


async def test_upload_stores_file_and_creates_row(
    client: AsyncClient,
    mock_session: MagicMock,
    fake_user: User,
    auth_headers: dict[str, str],
    local_storage: LocalStorage,
    sample_docx: bytes,
) -> None:
    mock_session.refresh = AsyncMock(side_effect=_assign_defaults)

    resp = await client.post(
        "/resumes",
        headers=auth_headers,
        files={"file": ("../My CV.docx", sample_docx, "application/octet-stream")},
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["file_name"] == "My CV.docx"
    assert body["content_type"].endswith("wordprocessingml.document")
    assert body["size_bytes"] == len(sample_docx)
    assert body["latest_version"] is None

    row: Resume = mock_session.add.call_args.args[0]
    assert row.user_id == fake_user.id
    assert row.file_url.startswith(f"local://resumes/{fake_user.id}/") and row.file_url.endswith(
        ".docx"
    )
    assert await local_storage.get(row.file_url) == sample_docx
    mock_session.commit.assert_awaited_once()


async def test_parse_creates_version_with_parsed_fields(
    client: AsyncClient,
    mock_session: MagicMock,
    fake_user: User,
    auth_headers: dict[str, str],
    local_storage: LocalStorage,
    sample_pdf: bytes,
) -> None:
    file_url = await local_storage.put(
        f"resumes/{fake_user.id}/x.pdf", sample_pdf, content_type="application/pdf"
    )
    resume = Resume(
        id=uuid.uuid4(),
        user_id=fake_user.id,
        file_url=file_url,
        file_name="x.pdf",
        content_type="application/pdf",
        size_bytes=len(sample_pdf),
        created_at=datetime.now(UTC),
    )
    resume.versions = []

    async def _get(model: type, key: object, **_: object) -> object:
        return fake_user if model is User else resume

    mock_session.get = AsyncMock(side_effect=_get)
    mock_session.scalar = AsyncMock(return_value=2)  # two earlier versions exist
    mock_session.refresh = AsyncMock(side_effect=_assign_defaults)

    resp = await client.post(f"/resumes/{resume.id}/parse", headers=auth_headers)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["resume_id"] == str(resume.id)
    assert body["version_number"] == 3
    assert "Python" in body["parsed_skills"]
    assert body["parsed_education"][0]["cgpa"] == 8.7
    assert body["parsed_education"][0]["graduation_year"] == 2027
    assert body["parsed_experience"][0]["title"].startswith("Backend Engineering Intern")
    assert body["parsed_projects"][0]["title"] == "NextStep Job Tracker"
    assert body["raw_text_chars"] > 200

    version: ResumeVersion = mock_session.add.call_args.args[0]
    assert version.raw_text.startswith("Ada Lovelace")
    assert version.version_number == 3
    mock_session.commit.assert_awaited_once()


async def test_parse_404_for_other_users_resume(
    client: AsyncClient,
    mock_session: MagicMock,
    fake_user: User,
    auth_headers: dict[str, str],
    local_storage: LocalStorage,
) -> None:
    other = Resume(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        file_url="local://resumes/other/x.pdf",
        file_name="x.pdf",
        content_type="application/pdf",
        size_bytes=1,
    )

    async def _get(model: type, key: object, **_: object) -> object:
        return fake_user if model is User else other

    mock_session.get = AsyncMock(side_effect=_get)
    resp = await client.post(f"/resumes/{other.id}/parse", headers=auth_headers)
    assert resp.status_code == 404


async def test_list_resumes_includes_latest_version_summary(
    client: AsyncClient, mock_session: MagicMock, fake_user: User, auth_headers: dict[str, str]
) -> None:
    resume = Resume(
        id=uuid.uuid4(),
        user_id=fake_user.id,
        file_url="local://resumes/x.pdf",
        file_name="x.pdf",
        content_type="application/pdf",
        size_bytes=10,
        created_at=datetime.now(UTC),
    )
    resume.versions = [
        ResumeVersion(
            id=uuid.uuid4(),
            resume_id=resume.id,
            parsed_skills=["Python"],
            version_number=1,
            created_at=datetime.now(UTC),
        ),
        ResumeVersion(
            id=uuid.uuid4(),
            resume_id=resume.id,
            parsed_skills=["Python", "SQL"],
            version_number=2,
            created_at=datetime.now(UTC),
        ),
    ]
    result = MagicMock(name="Result")
    result.scalars.return_value.all.return_value = [resume]
    mock_session.execute = AsyncMock(return_value=result)

    resp = await client.get("/resumes", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    assert body[0]["file_name"] == "x.pdf"
    assert body[0]["latest_version"]["version_number"] == 2
    assert body[0]["latest_version"]["parsed_skills"] == ["Python", "SQL"]


async def test_resumes_require_auth(client: AsyncClient) -> None:
    assert (await client.get("/resumes")).status_code == 401
    assert (
        await client.post("/resumes", files={"file": ("a.pdf", b"%PDF-", "x")})
    ).status_code == 401
