"""Turn an uploaded resume into structured, *extractive* data.

Everything here reports only what is literally in the document: skills come
from the shared dictionary, CGPA / graduation year from explicit patterns,
and experience / project entries from the text under those section headers.
Nothing is inferred or embellished (see ADR 003).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, Literal

import docx
import pdfplumber

from app.services.ingestion.skill_extractor import extract_skills

ResumeKind = Literal["pdf", "docx"]

MAX_TEXT_CHARS: Final[int] = 200_000  # a resume is a few KB; anything bigger is not one

# ---- Section headers ---------------------------------------------------------
_SECTION_PATTERNS: Final[dict[str, re.Pattern[str]]] = {
    "education": re.compile(r"^\s*(education|academics?|academic background)\s*:?\s*$", re.I),
    "experience": re.compile(
        r"^\s*((work|professional|relevant)\s+)?(experience|employment|internships?)"
        r"(\s+(history|&\s+internships?))?\s*:?\s*$",
        re.I,
    ),
    "projects": re.compile(
        r"^\s*((personal|academic|key|selected|notable)\s+)?projects?\s*:?\s*$", re.I
    ),
    "skills": re.compile(r"^\s*(technical\s+)?skills(\s+&\s+tools)?\s*:?\s*$", re.I),
}
_OTHER_HEADER_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(summary|objective|profile|about( me)?|certifications?|awards?|achievements?|"
    r"publications?|languages?|interests|hobbies|activities|leadership|volunteering|"
    r"references?|contact)\s*:?\s*$",
    re.I,
)

# ---- Education patterns ------------------------------------------------------
_CGPA_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:cgpa|gpa)\s*[:\-]?\s*(\d{1,2}(?:\.\d{1,2})?)(?:\s*/\s*(10|4(?:\.0)?))?"  # "CGPA: 8.5/10"
    r"|(\d{1,2}(?:\.\d{1,2})?)\s*/\s*(10|4(?:\.0)?)\b(?!\s*years)"  # "8.5/10"
    r"|(\d{1,2}(?:\.\d{1,2})?)\s*(?:cgpa|gpa)\b",  # "8.5 CGPA"
    re.I,
)
_YEAR_RE: Final[re.Pattern[str]] = re.compile(r"\b(20\d{2})\b")
_GRAD_HINT_RE: Final[re.Pattern[str]] = re.compile(
    r"(graduat\w*|expected|class of|batch|passing|completion"
    r"|20\d{2}\s*[-\u2013]\s*(20\d{2}|present))",
    re.I,
)
_DEGREE_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(b\.?\s?tech|b\.?\s?e\.?|b\.?\s?sc|b\.?\s?s\.?|b\.?\s?a\.?|bachelor(?:'s)?|"
    r"m\.?\s?tech|m\.?\s?e\.?|m\.?\s?sc|m\.?\s?s\.?|master(?:'s)?|mba|ph\.?\s?d|doctorate|"
    r"diploma|associate(?:'s)?)\b",
    re.I,
)
_INSTITUTION_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(university|institute|college|school|academy|iit|nit|iiit|bits)\b", re.I
)


@dataclass
class ParsedResume:
    """Structured output of :func:`parse_resume`; maps onto ``resume_versions``."""

    raw_text: str
    skills: list[str] = field(default_factory=list)
    education: list[dict[str, Any]] = field(default_factory=list)
    experience: list[dict[str, Any]] = field(default_factory=list)
    projects: list[dict[str, Any]] = field(default_factory=list)

    @property
    def cgpa(self) -> float | None:
        """First CGPA found across education entries, if any."""
        return next((e["cgpa"] for e in self.education if e.get("cgpa") is not None), None)

    @property
    def graduation_year(self) -> int | None:
        """Latest graduation year across education entries, if any."""
        years = [e["graduation_year"] for e in self.education if e.get("graduation_year")]
        return max(years) if years else None


# --------------------------------------------------------------------------- #
# Text extraction
# --------------------------------------------------------------------------- #


def extract_text(data: bytes, kind: ResumeKind) -> str:
    """Plain text from a PDF (pdfplumber) or DOCX (python-docx) file.

    Raises:
        ValueError: if the file cannot be parsed as the declared kind.
    """
    try:
        text = _extract_pdf(data) if kind == "pdf" else _extract_docx(data)
    except ValueError:
        raise
    except Exception as exc:  # library-specific parse errors
        msg = f"could not read {kind.upper()} content: {type(exc).__name__}"
        raise ValueError(msg) from exc
    return _clean(text)[:MAX_TEXT_CHARS]


def _extract_pdf(data: bytes) -> str:
    pages: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    return "\n".join(pages)


def _extract_docx(data: bytes) -> str:
    document = docx.Document(io.BytesIO(data))
    parts = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text.strip() for cell in row.cells if cell.text.strip()))
    return "\n".join(parts)


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    lines = [re.sub(r"[ \t\u00a0]+", " ", line).strip() for line in text.split("\n")]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


# --------------------------------------------------------------------------- #
# Structure
# --------------------------------------------------------------------------- #


def split_sections(text: str) -> dict[str, list[str]]:
    """Group lines under the section header that precedes them.

    Returns ``{"preamble": [...], "education": [...], "experience": [...],
    "projects": [...], "skills": [...], "other": [...]}``; keys may be missing.
    """
    sections: dict[str, list[str]] = {"preamble": []}
    current = "preamble"
    for line in text.split("\n"):
        header = _classify_header(line)
        if header is not None:
            current = header
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return sections


def _classify_header(line: str) -> str | None:
    stripped = line.strip().rstrip(":").strip()
    if not stripped or len(stripped) > 40:
        return None
    for name, pattern in _SECTION_PATTERNS.items():
        if pattern.match(stripped):
            return name
    if _OTHER_HEADER_RE.match(stripped):
        return "other"
    return None


def parse_cgpa(text: str) -> float | None:
    """First CGPA/GPA value in ``text`` (``"8.5/10"``, ``"CGPA: 8.5"``, ``"8.5 CGPA"``).

    Values on a 4-point scale are converted to 10-point so ``user_profiles.cgpa``
    stays comparable; anything outside 0-10 is ignored.
    """
    for match in _CGPA_RE.finditer(text):
        value_str = match.group(1) or match.group(3) or match.group(5)
        scale_str = match.group(2) or match.group(4)
        try:
            value = float(value_str)
        except (TypeError, ValueError):
            continue
        if scale_str and scale_str.startswith("4"):
            value = round(value * 2.5, 2)
        if 0 <= value <= 10:
            return value
    return None


def parse_graduation_year(text: str) -> int | None:
    """A 4-digit ``20xx`` year in ``text``, preferring one near a graduation hint.

    With a ``"2023 - 2027"`` style range the end year wins. Without any hint,
    the latest plausible year is returned.
    """
    now_year = datetime.now(UTC).year
    candidates = [int(y) for y in _YEAR_RE.findall(text) if 2000 <= int(y) <= now_year + 8]
    if not candidates:
        return None
    for line in text.split("\n"):
        if _GRAD_HINT_RE.search(line):
            years = [int(y) for y in _YEAR_RE.findall(line) if 2000 <= int(y) <= now_year + 8]
            if years:
                return max(years)
    return max(candidates)


def parse_education(lines: list[str]) -> list[dict[str, Any]]:
    """One entry per degree/institution block found under the Education header."""
    entries: list[dict[str, Any]] = []
    for block in _blocks(lines):
        text = "\n".join(block)
        entry: dict[str, Any] = {
            "institution": next((ln.strip() for ln in block if _INSTITUTION_RE.search(ln)), None),
            "degree": _first_match(_DEGREE_RE, text),
            "cgpa": parse_cgpa(text),
            "graduation_year": parse_graduation_year(text),
            "raw": text.strip(),
        }
        if any(entry[k] for k in ("institution", "degree", "cgpa", "graduation_year")):
            entries.append(entry)
    return entries


def parse_entries(lines: list[str]) -> list[dict[str, Any]]:
    """Experience / project entries: title line + detail lines per block."""
    entries: list[dict[str, Any]] = []
    for block in _blocks(lines):
        title = block[0].strip()
        details = [ln.strip().lstrip("-•*● ").strip() for ln in block[1:] if ln.strip()]
        years = [int(y) for y in _YEAR_RE.findall("\n".join(block[:2]))]
        entries.append(
            {
                "title": title,
                "details": details,
                "start_year": min(years) if years else None,
                "end_year": max(years) if len(years) > 1 else None,
                "skills": extract_skills(title, "\n".join(details)),
            }
        )
    return entries


def _blocks(lines: list[str]) -> list[list[str]]:
    """Split lines into blocks on blank lines; a bullet run never starts a new block."""
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if not line.strip():
            if current:
                blocks.append(current)
                current = []
            continue
        is_bullet = line.lstrip().startswith(("-", "•", "*", "●"))
        if current and not is_bullet and _looks_like_new_entry(line, current):
            blocks.append(current)
            current = []
        current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _looks_like_new_entry(line: str, current: list[str]) -> bool:
    """A non-bullet line following bullets starts a new entry (title after details)."""
    return current[-1].lstrip().startswith(("-", "•", "*", "●")) and len(line) <= 120


def _first_match(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(0).strip() if match else None


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def parse_resume(text: str) -> ParsedResume:
    """Extract skills, education, experience and projects from resume text."""
    sections = split_sections(text)
    education = parse_education(sections.get("education", []))
    experience = parse_entries(sections.get("experience", []))
    projects = parse_entries(sections.get("projects", []))

    # No explicit Education header: still look for a CGPA / year anywhere.
    if not education:
        cgpa = parse_cgpa(text)
        year = parse_graduation_year("\n".join(sections.get("preamble", [])))
        if cgpa is not None or year is not None:
            education.append(
                {
                    "institution": None,
                    "degree": _first_match(_DEGREE_RE, text),
                    "cgpa": cgpa,
                    "graduation_year": year,
                    "raw": "",
                }
            )

    return ParsedResume(
        raw_text=text,
        skills=extract_skills(text),
        education=education,
        experience=experience,
        projects=projects,
    )
