"""Transparent resume-to-job matching (v1, ADR 003).

Everything in a :class:`MatchResult` is derivable by hand from the inputs:

* ``match_score`` is skill coverage —
  ``|resume_skills ∩ job_skills| / max(1, |job_skills|)`` scaled to 0-100.
* Eligibility compares the user's profile with what the posting states
  (experience level, graduation years, minimum CGPA). When the posting says
  nothing, or the profile is missing, the answer is ``"uncertain"`` — never a
  guess.
* Suggestions are about wording and emphasis of what the resume already
  contains. They never tell the user to claim a skill they do not have.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Final, Literal

from pydantic import BaseModel, Field

from app.models.job import Job
from app.models.user import UserProfile
from app.services.ingestion.skill_extractor import ALIASES, extract_skills

EligibilityStatus = Literal["likely_eligible", "uncertain", "not_eligible"]

MAX_SUGGESTIONS: Final[int] = 5

_YEAR_RE: Final[re.Pattern[str]] = re.compile(r"\b(20\d{2})\b")
_CLASS_OF_RE: Final[re.Pattern[str]] = re.compile(
    r"(class of|graduat\w*|batch of|passing out)[^.\n]{0,60}", re.I
)
_MIN_CGPA_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:cgpa|gpa)[^0-9\n]{0,30}?(\d{1,2}(?:\.\d{1,2})?)(?:\s*/\s*(10|4(?:\.0)?))?|"
    r"(\d{1,2}(?:\.\d{1,2})?)(?:\s*/\s*(10|4(?:\.0)?))?"
    r"\s*(?:\+|or above|and above|minimum)?\s*(?:cgpa|gpa)",
    re.I,
)
_ENTRY_PROFILE_LEVELS: Final[frozenset[str]] = frozenset(
    {"student", "fresher", "entry", "entry_level", "entry-level", "new grad", "graduate", "junior"}
)
_EXPERIENCED_PROFILE_LEVELS: Final[frozenset[str]] = frozenset(
    {"experienced", "mid", "mid_level", "mid-level", "senior", "lead", "staff", "principal"}
)

SOFT_SKILLS: Final[frozenset[str]] = frozenset(
    {
        "agile",
        "analytical thinking",
        "communication",
        "customer support",
        "documentation",
        "kanban",
        "mentoring",
        "problem solving",
        "product management",
        "program management",
        "project management",
        "requirements gathering",
        "roadmapping",
        "scrum",
        "stakeholder management",
        "teamwork",
        "technical leadership",
        "technical writing",
    }
)
"""Skills too generic to discriminate between candidates.

A posting whose only stated requirements are these (common for sales, finance
and support roles) tells us nothing about technical fit, so scoring it would
report a confident 0% where we simply have no signal.
"""


def discriminating_skills(job_skills: list[str]) -> list[str]:
    """``job_skills`` minus the generic soft skills; empty means "no real signal"."""
    return [skill for skill in job_skills if skill.strip().lower() not in SOFT_SKILLS]


class MatchResult(BaseModel):
    """Explainable fit between one resume and one job."""

    match_score: int = Field(ge=0, le=100)
    scoreable: bool = Field(
        default=True,
        description=(
            "False when the posting names no skill specific enough to match on — either none "
            "at all, or only generic ones like Communication. ``match_score`` is then 0 because "
            "there was nothing to match against, not because the resume is a poor fit."
        ),
    )
    matching_skills: list[str]
    missing_skills: list[str]
    eligibility_status: EligibilityStatus
    eligibility_reasons: list[str]
    suggestions: list[str] = Field(
        description="Wording/emphasis advice about content already on the resume; never new claims"
    )


# --------------------------------------------------------------------------- #
# Skills
# --------------------------------------------------------------------------- #


def match_key(skill: str) -> str:
    """Comparison key for a skill name: alias resolved first, then case-folded.

    Both sides of a comparison normally come from :func:`extract_skills` and
    are already canonical, so case folding alone would usually do. It is not
    enough when one side is not canonical — a ``required_skills`` array written
    by an older dictionary, or skills typed by a user — because case folding
    leaves ``Node.js`` and ``nodejs`` as different skills. Resolving through
    the alias table first collapses them onto the same key.
    """
    stripped = skill.strip()
    return ALIASES.get(stripped.lower(), stripped).lower()


def _normalise(skills: list[str]) -> dict[str, str]:
    """``match key -> first seen display form``."""
    out: dict[str, str] = {}
    for skill in skills:
        stripped = skill.strip()
        if not stripped:
            continue
        key = match_key(stripped)
        if key not in out:
            out[key] = stripped
    return out


def job_skill_set(job: Job) -> list[str]:
    """The job's required skills, or skills extracted from its text when none were stored."""
    if job.required_skills:
        return list(job.required_skills)
    return extract_skills(job.title, job.requirements, job.description)


def skill_coverage(
    resume_skills: list[str], job_skills: list[str]
) -> tuple[float, list[str], list[str]]:
    """``(coverage, matching, missing)`` with coverage = |∩| / max(1, |job_skills|)."""
    have = _normalise(resume_skills)
    want = _normalise(job_skills)
    matching = [display for key, display in want.items() if key in have]
    missing = [display for key, display in want.items() if key not in have]
    coverage = len(matching) / max(1, len(want))
    return coverage, matching, missing


# --------------------------------------------------------------------------- #
# Eligibility
# --------------------------------------------------------------------------- #


def _posting_text(job: Job) -> str:
    return "\n".join(part for part in (job.eligibility, job.requirements, job.description) if part)


def _required_graduation_years(job: Job) -> set[int]:
    """Years named next to "class of" / "graduating" phrases in the posting."""
    years: set[int] = set()
    for match in _CLASS_OF_RE.finditer(_posting_text(job)):
        years.update(int(y) for y in _YEAR_RE.findall(match.group(0)))
    return years


def _minimum_cgpa(job: Job) -> float | None:
    """A minimum CGPA stated in the posting, on a 10-point scale."""
    for match in _MIN_CGPA_RE.finditer(_posting_text(job)):
        value_str = match.group(1) or match.group(3)
        scale_str = match.group(2) or match.group(4)
        try:
            value = float(value_str)
        except (TypeError, ValueError):
            continue
        if scale_str and scale_str.startswith("4"):
            value *= 2.5
        if 0 < value <= 10:
            return round(value, 2)
    return None


def assess_eligibility(
    job: Job, profile: UserProfile | None, *, now: datetime | None = None
) -> tuple[EligibilityStatus, list[str]]:
    """Compare the profile with what the posting explicitly states."""
    if profile is None:
        return "uncertain", [
            "Complete your profile (graduation year, experience level, CGPA) "
            "to check eligibility."
        ]

    now = now or datetime.now(UTC)
    positives: list[str] = []
    negatives: list[str] = []
    unknowns: list[str] = []

    level = (profile.experience_level or "").strip().lower()
    grad_year = profile.graduation_year

    # -- Experience level vs. the posting's level -----------------------------
    if job.experience_level == "intern":
        if grad_year is None:
            unknowns.append(
                "Internships usually require current enrolment; add your graduation year."
            )
        elif grad_year >= now.year:
            positives.append(f"Internship role and you graduate in {grad_year}.")
        else:
            negatives.append(
                f"Internships usually require current enrolment, but you graduated in {grad_year}."
            )
    elif job.experience_level == "entry_level":
        if level in _ENTRY_PROFILE_LEVELS or (
            grad_year and now.year - 2 <= grad_year <= now.year + 1
        ):
            positives.append("Entry-level role matching your experience level.")
        elif level in _EXPERIENCED_PROFILE_LEVELS:
            unknowns.append(
                "Entry-level role; your profile indicates more experience than it asks for."
            )
        else:
            unknowns.append("Entry-level role; set your experience level to confirm fit.")
    elif job.experience_level == "experienced":
        if level in _EXPERIENCED_PROFILE_LEVELS:
            positives.append("Role expects prior experience, which matches your profile.")
        elif level in _ENTRY_PROFILE_LEVELS or (grad_year and grad_year >= now.year):
            unknowns.append(
                "This role expects prior professional experience; "
                "the posting does not say how much."
            )
        else:
            unknowns.append(
                "Role expects prior experience; set your experience level to confirm fit."
            )
    else:
        unknowns.append("The posting does not state an experience level.")

    # -- Graduation year constraints -----------------------------------------
    required_years = _required_graduation_years(job)
    if required_years:
        if grad_year is None:
            unknowns.append(
                f"Posting targets graduates of {', '.join(map(str, sorted(required_years)))}; "
                "add your graduation year."
            )
        elif grad_year in required_years:
            positives.append(f"Posting targets {grad_year} graduates, which matches your profile.")
        else:
            negatives.append(
                f"Posting targets graduates of {', '.join(map(str, sorted(required_years)))}; "
                f"your graduation year is {grad_year}."
            )

    # -- Minimum CGPA ---------------------------------------------------------
    min_cgpa = _minimum_cgpa(job)
    if min_cgpa is not None:
        if profile.cgpa is None:
            unknowns.append(
                f"Posting asks for a CGPA of at least {min_cgpa:g}; add yours to check."
            )
        elif float(profile.cgpa) >= min_cgpa:
            positives.append(
                f"Your CGPA ({float(profile.cgpa):g}) meets the stated minimum of {min_cgpa:g}."
            )
        else:
            negatives.append(
                f"Posting asks for a CGPA of at least {min_cgpa:g}; "
                f"your profile says {float(profile.cgpa):g}."
            )

    if negatives:
        return "not_eligible", negatives + positives
    if positives and not unknowns:
        return "likely_eligible", positives
    if positives:
        return "likely_eligible", positives + unknowns
    return "uncertain", unknowns


# --------------------------------------------------------------------------- #
# Suggestions (wording only)
# --------------------------------------------------------------------------- #


def build_suggestions(
    matching: list[str], missing: list[str], job: Job, resume_skills: list[str]
) -> list[str]:
    """Advice on presenting skills the resume already has; never invents new ones."""
    suggestions: list[str] = []
    if matching:
        lead = ", ".join(matching[:3])
        suggestions.append(
            f"Lead with {lead} in your summary or skills section; "
            "the posting lists them as required."
        )
    if missing:
        sample = ", ".join(missing[:3])
        suggestions.append(
            f"The posting also asks for {sample}. If you have used any of these, name them "
            "explicitly with the same spelling; if not, leave them out."
        )
    title_terms = [
        s for s in extract_skills(job.title) if s.lower() in {m.lower() for m in matching}
    ]
    if title_terms:
        suggestions.append(
            f"{title_terms[0]} appears in the job title; mirror that term in your headline or most "
            "recent role."
        )
    if len(resume_skills) > 25:
        suggestions.append(
            "Your resume lists many skills; move the ones this posting requires to the top so a "
            "recruiter sees them first."
        )
    if not matching and not missing:
        suggestions.append(
            "This posting lists no identifiable skills, so the score is not meaningful; judge fit "
            "from the description."
        )
    return suggestions[:MAX_SUGGESTIONS]


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def compute_match(
    resume_skills: list[str],
    job: Job,
    profile: UserProfile | None,
    *,
    now: datetime | None = None,
) -> MatchResult:
    """Score a resume against a job.

    ``match_score = round(100 * |resume_skills ∩ job_skills| / max(1, |job_skills|))``
    where ``job_skills`` is ``job.required_skills`` (or skills extracted from the
    posting text when that list is empty).

    When ``job_skills`` is empty the division has nothing to divide, so the
    score is 0 for every resume. The same is true when the posting names only
    generic skills (Communication, Teamwork …): the 0 carries no information.
    ``scoreable`` is False in both cases so callers can say "this posting does
    not list specific skills" instead of "0% match".
    """
    job_skills = job_skill_set(job)
    coverage, matching, missing = skill_coverage(resume_skills, job_skills)
    status, reasons = assess_eligibility(job, profile, now=now)
    return MatchResult(
        match_score=round(100 * coverage),
        # Nothing specific to match against is not the same as matching nothing.
        scoreable=bool(discriminating_skills(job_skills)),
        matching_skills=matching,
        missing_skills=missing,
        eligibility_status=status,
        eligibility_reasons=reasons,
        suggestions=build_suggestions(matching, missing, job, resume_skills),
    )
