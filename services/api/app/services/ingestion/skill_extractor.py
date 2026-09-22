"""Extractive skill matching against the shared skills dictionary.

The vocabulary is ``packages/skills-dictionary/skills.json`` — a flat list of
canonical skill names shared with the web app. Matching is strictly
extractive (see ADR 003): a skill is reported only when its name, or a known
alias, literally occurs in the text. Nothing is inferred.

Matching is case-insensitive except for very short names (``C``, ``R``,
``Go``) and a few words that double as ordinary English (``Rust``, ``Swift``,
``Dart``), which must appear with their canonical capitalisation.
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Final

from app.core.config import settings

logger = logging.getLogger(__name__)

DEFAULT_DICTIONARY_PATH: Final[Path] = (
    Path(__file__).resolve().parents[5] / "packages" / "skills-dictionary" / "skills.json"
)

# Common variants that should resolve to a canonical dictionary entry. Aliases
# whose canonical name is missing from the loaded dictionary are ignored.
ALIASES: Final[dict[str, str]] = {
    "postgres": "PostgreSQL",
    "psql": "PostgreSQL",
    "k8s": "Kubernetes",
    "golang": "Go",
    "js": "JavaScript",
    "ts": "TypeScript",
    "node": "Node.js",
    "nodejs": "Node.js",
    "reactjs": "React",
    "react.js": "React",
    "nextjs": "Next.js",
    "vue": "Vue.js",
    "vuejs": "Vue.js",
    "sklearn": "Scikit-learn",
    "scikit learn": "Scikit-learn",
    "ml": "Machine Learning",
    "nlp": "Natural Language Processing",
    "cv": "Computer Vision",
    "amazon web services": "AWS",
    "google cloud": "GCP",
    "google cloud platform": "GCP",
    "microsoft azure": "Azure",
    "ci cd": "CI/CD",
    "continuous integration": "CI/CD",
    "continuous delivery": "CI/CD",
    "rest": "REST API",
    "rest apis": "REST API",
    "restful": "REST API",
    "restful apis": "REST API",
    "mongo": "MongoDB",
    "cpp": "C++",
    "c sharp": "C#",
    "csharp": "C#",
    "dotnet": ".NET",
    "rails": "Ruby on Rails",
    "spring boot": "Spring Boot",
    "kafka": "Apache Kafka",
    "spark": "Apache Spark",
    "airflow": "Apache Airflow",
    "tailwind": "Tailwind CSS",
    "tailwindcss": "Tailwind CSS",
    "large language models": "LLMs",
    "llm": "LLMs",
    "retrieval augmented generation": "RAG",
    "retrieval-augmented generation": "RAG",
    "tdd": "Test-Driven Development",
    "oop": "Object-Oriented Programming",
    "object oriented programming": "Object-Oriented Programming",
    "sre": "Site Reliability Engineering",
    "iac": "Infrastructure as Code",
    "a11y": "Accessibility",
    "wcag": "Accessibility",
    "ab testing": "A/B Testing",
    "a/b tests": "A/B Testing",
    "dsa": "Data Structures",
    "data structures and algorithms": "Data Structures",
    "unit tests": "Unit Testing",
    "shell scripting": "Bash",
    "shell": "Bash",
    "tcp": "TCP/IP",
}

# Names that are ordinary words in lowercase; require canonical capitalisation.
_CASE_SENSITIVE: Final[frozenset[str]] = frozenset({"Rust", "Swift", "Dart", "Go", "C", "R"})


def load_skills_dictionary(path: Path | None = None) -> list[str]:
    """Read the flat list of canonical skill names from ``skills.json``.

    Resolution order: explicit ``path`` → ``settings.SKILLS_DICTIONARY_PATH`` →
    the in-repo ``packages/skills-dictionary/skills.json``.

    Raises:
        FileNotFoundError: if no dictionary exists at the resolved path.
        ValueError: if the file is not a JSON array of non-empty strings.
    """
    resolved = path or settings.SKILLS_DICTIONARY_PATH or DEFAULT_DICTIONARY_PATH
    if not resolved.exists():
        msg = (
            f"skills dictionary not found at {resolved}; set SKILLS_DICTIONARY_PATH "
            "or restore packages/skills-dictionary/skills.json"
        )
        raise FileNotFoundError(msg)

    data = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(s, str) and s.strip() for s in data):
        msg = f"{resolved} must contain a JSON array of non-empty strings"
        raise ValueError(msg)

    seen: set[str] = set()
    skills: list[str] = []
    for raw in data:
        name = raw.strip()
        key = name.lower()
        if key in seen:
            logger.warning("skills dictionary: duplicate entry %r ignored", name)
            continue
        seen.add(key)
        skills.append(name)
    return skills


def _pattern(term: str, *, case_sensitive: bool) -> re.Pattern[str]:
    """Word-bounded pattern that also works for tokens like ``C++``, ``Node.js`` and ``.NET``.

    Single-letter names (``C``, ``R``) additionally refuse a neighbouring ``-``
    or ``&`` so "C-level" and "R&D" do not count as languages.
    """
    if len(term) == 1:
        body = rf"(?<![\w+#.&-]){re.escape(term)}(?![\w+#&-])"
    else:
        body = rf"(?<![\w+#.]){re.escape(term)}(?![\w+#])"
    return re.compile(body, 0 if case_sensitive else re.IGNORECASE)


@lru_cache(maxsize=1)
def _compiled() -> tuple[tuple[str, re.Pattern[str]], ...]:
    """``(canonical, pattern)`` pairs for every dictionary entry and alias, compiled once."""
    skills = load_skills_dictionary()
    canonical_by_key = {s.lower(): s for s in skills}

    pairs: list[tuple[str, re.Pattern[str]]] = [
        (skill, _pattern(skill, case_sensitive=skill in _CASE_SENSITIVE)) for skill in skills
    ]
    for alias, target in ALIASES.items():
        canonical = canonical_by_key.get(target.lower())
        if canonical is None:
            logger.debug("skills dictionary: alias %r → %r skipped (target missing)", alias, target)
            continue
        pairs.append((canonical, _pattern(alias, case_sensitive=False)))
    return tuple(pairs)


def extract_skills(*texts: str | None) -> list[str]:
    """Return canonical skill names whose name or alias occurs in any of ``texts``.

    Ordered by first occurrence across the concatenated input; each canonical
    skill appears at most once. Empty input yields ``[]``.
    """
    corpus = "\n".join(t for t in texts if t)
    if not corpus:
        return []

    first_seen: dict[str, int] = {}
    for canonical, pattern in _compiled():
        match = pattern.search(corpus)
        if match is None:
            continue
        if canonical not in first_seen or match.start() < first_seen[canonical]:
            first_seen[canonical] = match.start()
    return sorted(first_seen, key=first_seen.__getitem__)


def reload_dictionary() -> None:
    """Drop the compiled cache so the next call re-reads ``skills.json`` (tests, hot edits)."""
    _compiled.cache_clear()
