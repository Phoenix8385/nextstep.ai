"""Resume upload, parsing and listing.

Security notes
--------------
* The file type is decided by **magic bytes**, never by the client's
  ``Content-Type`` or extension: ``%PDF-`` for PDF, and a ZIP container that
  holds ``word/document.xml`` for DOCX. Anything else is rejected with 415.
* Size is capped at ``settings.RESUME_MAX_BYTES`` (5 MB) while streaming the
  upload, so an oversized body is rejected before it is fully buffered.
* Objects are stored under an opaque key (``resumes/<user_id>/<uuid>.<ext>``);
  the original filename is kept only as metadata and never used in the key.
* Every read goes through the owner check; ``file_url`` is never exposed.
* Parsing runs in a worker thread with the file already in memory; the
  parsers never touch the filesystem or follow embedded links.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
import uuid
import zipfile
from typing import Annotated, Final

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession
from app.models.resume import Resume, ResumeVersion
from app.schemas.resume import ResumeResponse, ResumeVersionResponse, ResumeVersionSummary
from app.services.resume_parser import ResumeKind, extract_text, parse_resume
from app.services.storage import StorageError, get_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/resumes", tags=["resumes"])

_CONTENT_TYPES: Final[dict[ResumeKind, str]] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_CHUNK: Final[int] = 64 * 1024
_SAFE_NAME_RE: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9._ -]+")


# --------------------------------------------------------------------------- #
# Validation helpers
# --------------------------------------------------------------------------- #


def sniff_kind(data: bytes) -> ResumeKind | None:
    """Identify PDF or DOCX from content alone; ``None`` for anything else."""
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if "word/document.xml" in archive.namelist():
                    return "docx"
        except zipfile.BadZipFile:
            return None
    return None


def safe_file_name(name: str | None, kind: ResumeKind) -> str:
    """A display name stripped of path components and unusual characters."""
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = _SAFE_NAME_RE.sub("", base).strip() or f"resume.{kind}"
    if not base.lower().endswith(f".{kind}"):
        base = f"{base}.{kind}"
    return base[:120]


async def read_limited(upload: UploadFile, limit: int) -> bytes:
    """Read at most ``limit`` bytes; raise 413 as soon as the body exceeds it."""
    buffer = bytearray()
    while chunk := await upload.read(_CHUNK):
        buffer.extend(chunk)
        if len(buffer) > limit:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds the {limit // (1024 * 1024)} MB limit",
            )
    return bytes(buffer)


async def _owned_resume(db: DbSession, resume_id: uuid.UUID, user_id: uuid.UUID) -> Resume:
    resume = await db.get(Resume, resume_id, options=[selectinload(Resume.versions)])
    if resume is None or resume.user_id != user_id:
        # 404 for both cases so the endpoint does not confirm other users' ids.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")
    return resume


def _to_response(resume: Resume) -> ResumeResponse:
    latest = max(resume.versions, key=lambda v: v.version_number, default=None)
    return ResumeResponse(
        id=resume.id,
        file_name=resume.file_name,
        content_type=resume.content_type,
        size_bytes=resume.size_bytes,
        created_at=resume.created_at,
        latest_version=ResumeVersionSummary.model_validate(latest) if latest else None,
    )


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #


@router.post(
    "",
    response_model=ResumeResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE: {"description": "File larger than 5 MB"},
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {"description": "Not a PDF or DOCX"},
    },
)
async def upload_resume(
    file: Annotated[UploadFile, File(description="PDF or DOCX, max 5 MB")],
    user: CurrentUser,
    db: DbSession,
) -> ResumeResponse:
    """Store a resume file and create its ``resumes`` row (unparsed until ``/parse``)."""
    data = await read_limited(file, settings.RESUME_MAX_BYTES)
    kind = sniff_kind(data)
    if kind is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF and DOCX files are accepted",
        )
    if not data:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Empty file")

    key = f"resumes/{user.id}/{uuid.uuid4()}.{kind}"
    try:
        file_url = await get_storage().put(key, data, content_type=_CONTENT_TYPES[kind])
    except StorageError:
        logger.exception("resume upload failed for user %s", user.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not store the file"
        ) from None

    resume = Resume(
        user_id=user.id,
        file_url=file_url,
        file_name=safe_file_name(file.filename, kind),
        content_type=_CONTENT_TYPES[kind],
        size_bytes=len(data),
    )
    db.add(resume)
    await db.commit()
    await db.refresh(resume, attribute_names=["id", "created_at", "versions"])
    logger.info("resume %s uploaded by user %s (%d bytes, %s)", resume.id, user.id, len(data), kind)
    return _to_response(resume)


@router.post(
    "/{resume_id}/parse",
    response_model=ResumeVersionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_404_NOT_FOUND: {"description": "Resume not found"}},
)
async def parse_resume_file(
    resume_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> ResumeVersionResponse:
    """Download the file, extract text and structure, and store a new ``resume_versions`` row.

    Re-parsing is allowed (e.g. after a parser upgrade); each call adds a
    version with an incremented ``version_number``.
    """
    resume = await _owned_resume(db, resume_id, user.id)
    kind: ResumeKind = "pdf" if resume.content_type == _CONTENT_TYPES["pdf"] else "docx"

    try:
        data = await get_storage().get(resume.file_url)
    except StorageError:
        logger.exception("resume %s: download failed", resume.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not retrieve the file"
        ) from None

    try:
        text = await asyncio.to_thread(extract_text, data, kind)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if not text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No text could be extracted (is the PDF a scanned image?)",
        )

    parsed = await asyncio.to_thread(parse_resume, text)

    next_number = (
        await db.scalar(
            select(func.coalesce(func.max(ResumeVersion.version_number), 0)).where(
                ResumeVersion.resume_id == resume.id
            )
        )
        or 0
    ) + 1
    version = ResumeVersion(
        resume_id=resume.id,
        parsed_skills=parsed.skills,
        parsed_education=parsed.education,
        parsed_experience=parsed.experience,
        parsed_projects=parsed.projects,
        raw_text=parsed.raw_text,
        version_number=next_number,
    )
    db.add(version)
    await db.commit()
    await db.refresh(version)
    logger.info(
        "resume %s parsed as v%d: %d skills, %d education, %d experience, %d projects",
        resume.id,
        version.version_number,
        len(parsed.skills),
        len(parsed.education),
        len(parsed.experience),
        len(parsed.projects),
    )
    return ResumeVersionResponse(
        id=version.id,
        resume_id=version.resume_id,
        version_number=version.version_number,
        parsed_skills=version.parsed_skills,
        parsed_education=version.parsed_education,
        parsed_experience=version.parsed_experience,
        parsed_projects=version.parsed_projects,
        created_at=version.created_at,
        raw_text_chars=len(parsed.raw_text),
    )


@router.get("", response_model=list[ResumeResponse])
async def list_resumes(user: CurrentUser, db: DbSession) -> list[ResumeResponse]:
    """The current user's resumes, newest first, each with its latest parsed version."""
    result = await db.execute(
        select(Resume)
        .options(selectinload(Resume.versions))
        .where(Resume.user_id == user.id)
        .order_by(Resume.created_at.desc(), Resume.id.desc())
    )
    return [_to_response(resume) for resume in result.scalars().all()]
