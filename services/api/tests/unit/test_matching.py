"""``compute_match``: coverage formula, eligibility rules, and suggestion hygiene."""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.models import Job, UserProfile
from app.services.matching import (
    MatchResult,
    assess_eligibility,
    compute_match,
    skill_coverage,
)

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


def _profile(**overrides: object) -> UserProfile:
    base: dict[str, object] = {
        "college": "IIT Bombay",
        "cgpa": Decimal("8.70"),
        "graduation_year": 2027,
        "experience_level": "student",
        "preferred_roles": [],
        "preferred_locations": [],
        "preferred_work_mode": [],
        "skills": [],
    }
    base.update(overrides)
    return UserProfile(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Formula
# --------------------------------------------------------------------------- #


def test_skill_coverage_formula() -> None:
    coverage, matching, missing = skill_coverage(
        ["python", "PostgreSQL", "Docker"], ["Python", "postgresql", "Kubernetes", "AWS"]
    )
    assert coverage == 2 / 4
    assert matching == ["Python", "postgresql"]  # job's spelling, in job order
    assert missing == ["Kubernetes", "AWS"]
    assert skill_coverage([], [])[0] == 0.0  # max(1, 0) guards the division


def test_compute_match_score_is_rounded_coverage(make_job: Callable[..., Job]) -> None:
    job = make_job(required_skills=["Python", "SQL", "Docker"])
    result = compute_match(["python", "sql"], job, None, now=NOW)
    assert isinstance(result, MatchResult)
    assert result.match_score == 67  # round(100 * 2/3)
    assert result.matching_skills == ["Python", "SQL"]
    assert result.missing_skills == ["Docker"]


def test_compute_match_falls_back_to_text_when_no_required_skills(
    make_job: Callable[..., Job],
) -> None:
    job = make_job(required_skills=[], description="You will write Go services on Kubernetes.")
    result = compute_match(["Go"], job, None, now=NOW)
    assert result.matching_skills == ["Go"]
    assert result.missing_skills == ["Kubernetes"]
    assert result.match_score == 50


# --------------------------------------------------------------------------- #
# Eligibility
# --------------------------------------------------------------------------- #


def test_no_profile_is_uncertain(make_job: Callable[..., Job]) -> None:
    status, reasons = assess_eligibility(make_job(), None, now=NOW)
    assert status == "uncertain"
    assert "Complete your profile" in reasons[0]


def test_intern_role_with_current_student(make_job: Callable[..., Job]) -> None:
    job = make_job(experience_level="intern")
    status, reasons = assess_eligibility(job, _profile(graduation_year=2027), now=NOW)
    assert status == "likely_eligible"
    assert "graduate in 2027" in reasons[0]


def test_intern_role_after_graduation_is_not_eligible(make_job: Callable[..., Job]) -> None:
    job = make_job(experience_level="intern")
    status, reasons = assess_eligibility(job, _profile(graduation_year=2023), now=NOW)
    assert status == "not_eligible"
    assert "graduated in 2023" in reasons[0]


def test_class_of_constraint_from_posting_text(make_job: Callable[..., Job]) -> None:
    job = make_job(
        experience_level="entry_level",
        eligibility="Open to the class of 2026 or 2027 graduates.",
    )
    ok, _ = assess_eligibility(job, _profile(graduation_year=2027), now=NOW)
    no, reasons = assess_eligibility(job, _profile(graduation_year=2029), now=NOW)
    assert ok == "likely_eligible"
    assert no == "not_eligible"
    assert "2026, 2027" in reasons[0] and "2029" in reasons[0]


def test_minimum_cgpa_from_posting(make_job: Callable[..., Job]) -> None:
    job = make_job(experience_level="entry_level", requirements="Minimum CGPA of 8.0/10 required.")
    ok, ok_reasons = assess_eligibility(job, _profile(cgpa=Decimal("8.70")), now=NOW)
    no, no_reasons = assess_eligibility(job, _profile(cgpa=Decimal("7.20")), now=NOW)
    unknown, unknown_reasons = assess_eligibility(job, _profile(cgpa=None), now=NOW)
    assert ok == "likely_eligible" and "meets the stated minimum of 8" in ok_reasons[-1]
    assert no == "not_eligible" and "your profile says 7.2" in no_reasons[0]
    assert unknown == "likely_eligible"  # entry-level matched; CGPA unknown is only a caveat
    assert any("add yours" in r for r in unknown_reasons)


def test_experienced_role_with_student_profile_is_uncertain(make_job: Callable[..., Job]) -> None:
    job = make_job(experience_level="experienced")
    status, reasons = assess_eligibility(job, _profile(experience_level="student"), now=NOW)
    assert status == "uncertain"
    assert "prior professional experience" in reasons[0]

    status, _ = assess_eligibility(job, _profile(experience_level="senior"), now=NOW)
    assert status == "likely_eligible"


def test_posting_without_level_is_uncertain(make_job: Callable[..., Job]) -> None:
    job = make_job(experience_level=None)
    status, reasons = assess_eligibility(job, _profile(), now=NOW)
    assert status == "uncertain"
    assert reasons == ["The posting does not state an experience level."]


# --------------------------------------------------------------------------- #
# Suggestions never fabricate
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "resume_skills",
    [["Python"], ["Python", "SQL", "Docker"], []],
)
def test_suggestions_are_wording_only(
    make_job: Callable[..., Job], resume_skills: list[str]
) -> None:
    job = make_job(title="Python Engineer", required_skills=["Python", "SQL", "Kubernetes"])
    result = compute_match(resume_skills, job, _profile(), now=NOW)

    assert 1 <= len(result.suggestions) <= 5
    joined = " ".join(result.suggestions).lower()
    # Missing skills may be named, but only conditionally and never as a claim to add.
    for missing in result.missing_skills:
        if missing.lower() in joined:
            assert "if you have used" in joined
            assert "if not, leave them out" in joined
    for forbidden in ("add kubernetes", "claim", "pretend", "include kubernetes"):
        assert forbidden not in joined


def test_title_skill_suggestion_only_for_matching_skills(make_job: Callable[..., Job]) -> None:
    job = make_job(title="Senior Go Engineer", required_skills=["Go", "gRPC"])
    with_go = compute_match(["Go"], job, None, now=NOW)
    without_go = compute_match(["gRPC"], job, None, now=NOW)
    assert any("Go appears in the job title" in s for s in with_go.suggestions)
    assert not any("appears in the job title" in s for s in without_go.suggestions)
