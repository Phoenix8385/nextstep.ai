"""Text normalisation and heuristic field inference shared by every fetcher.

Everything here is deterministic and conservative: when a signal is absent the
function returns ``None`` rather than guessing, so the ``jobs`` table never
claims something the posting did not say.
"""

import html
import re
from html.parser import HTMLParser
from typing import Final

from app.services.ingestion.schema import ExperienceLevel, WorkMode

_BLOCK_TAGS: Final[frozenset[str]] = frozenset(
    {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section"}
)
_LIST_ITEM_PREFIX: Final[str] = "- "


class _TextExtractor(HTMLParser):
    """Collect text from HTML, emitting newlines at block boundaries and bullets for ``<li>``."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0  # inside <script>/<style>

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._skip_depth += 1
        elif tag == "li":
            self._parts.append("\n" + _LIST_ITEM_PREFIX)
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS and tag != "li":  # the next <li> supplies its own newline
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def html_to_text(value: str | None) -> str | None:
    """Convert an HTML fragment to readable plain text.

    Handles Greenhouse's double-escaped payloads (``&lt;p&gt;``) by unescaping
    once when the string contains entities but no raw tags. Collapses runs of
    whitespace and blank lines; returns ``None`` for empty input.
    """
    if value is None:
        return None
    raw = value
    if "<" not in raw and "&lt;" in raw:
        raw = html.unescape(raw)

    parser = _TextExtractor()
    parser.feed(raw)
    parser.close()

    lines = [re.sub(r"[ \t\r\f\v\u00a0]+", " ", line).strip() for line in parser.text().split("\n")]
    collapsed: list[str] = []
    for line in lines:
        if line or (collapsed and collapsed[-1]):
            collapsed.append(line)
    text = "\n".join(collapsed).strip()
    return text or None


# --------------------------------------------------------------------------- #
# Work mode
# --------------------------------------------------------------------------- #
_REMOTE_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(remote|work[- ]from[- ]anywhere|distributed|wfh)\b", re.IGNORECASE
)
_HYBRID_RE: Final[re.Pattern[str]] = re.compile(r"\bhybrid\b", re.IGNORECASE)
_ONSITE_RE: Final[re.Pattern[str]] = re.compile(r"\b(on[- ]?site|in[- ]office)\b", re.IGNORECASE)
_HINT_MAP: Final[dict[str, WorkMode]] = {
    "remote": "remote",
    "hybrid": "hybrid",
    "onsite": "onsite",
    "on-site": "onsite",
    "on_site": "onsite",
}


def infer_work_mode(
    *,
    location: str | None,
    title: str | None = None,
    description: str | None = None,
    hint: str | None = None,
) -> WorkMode | None:
    """Derive ``work_mode`` from an explicit ATS hint, then location, title, description.

    A structured ``hint`` (Lever ``workplaceType``, Ashby ``isRemote``) always
    wins. Free text is only consulted for explicit words; a bare city name
    with no other signal yields ``"onsite"``, and no signal at all yields ``None``.
    """
    if hint:
        mapped = _HINT_MAP.get(hint.strip().lower())
        if mapped:
            return mapped

    for field_text in (location, title):
        if not field_text:
            continue
        if _HYBRID_RE.search(field_text):
            return "hybrid"
        if _REMOTE_RE.search(field_text):
            return "remote"
        if _ONSITE_RE.search(field_text):
            return "onsite"

    if description:
        head = description[:1500]  # the work-mode sentence is almost always near the top
        if _HYBRID_RE.search(head):
            return "hybrid"
        if re.search(r"\b(fully|100%)[- ]remote\b|\bremote[- ]first\b", head, re.IGNORECASE):
            return "remote"

    return "onsite" if location else None


# --------------------------------------------------------------------------- #
# Experience level
# --------------------------------------------------------------------------- #
_INTERN_RE: Final[re.Pattern[str]] = re.compile(r"\b(intern|internship|co-?op)\b", re.IGNORECASE)
# Roman-numeral levels ("Engineer I/II/III") are matched case-sensitively via (?-i:...)
# so the pronoun "i" or words like "iv" never trigger them.
_ENTRY_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(new[- ]grad(uate)?|early[- ]career|entry[- ]level|junior|graduate|associate|apprentice"
    r"|university|campus)\b"
    r"|(?<=\s)(?-i:I)(?=\s*$|[,\s(/-])",
    re.IGNORECASE,
)
_EXPERIENCED_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|architect|distinguished|manager|director|head|"
    r"mid[- ]level|experienced)\b"
    r"|(?<=\s)(?-i:II|III|IV|V)(?=\s*$|[,\s(/-])",
    re.IGNORECASE,
)


def infer_experience_level(*, title: str, hint: str | None = None) -> ExperienceLevel | None:
    """Derive ``experience_level`` from title keywords.

    ``intern`` beats everything ("Senior Intern" is still an internship);
    seniority words and level suffixes (II+) mean ``experienced``; new-grad /
    junior / level-I wording means ``entry_level``. ``hint`` accepts ATS
    employment types (e.g. Ashby ``"Intern"``). No signal → ``None``.
    """
    if hint and hint.strip().lower() in {"intern", "internship"}:
        return "intern"
    if _INTERN_RE.search(title):
        return "intern"
    if _EXPERIENCED_RE.search(title):
        return "experienced"
    if _ENTRY_RE.search(title):
        return "entry_level"
    return None


# --------------------------------------------------------------------------- #
# Requirements section
# --------------------------------------------------------------------------- #
_REQ_HEADING_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:minimum |basic |preferred )?"
    r"(requirements?|qualifications?|what (?:we(?:'|\u2019)re|we are) looking for|"
    r"what you(?:'|\u2019)ll bring|what you bring|about you|who you are|you have|"
    r"you (?:should|must) have|skills?(?: and experience)?)\s*:?\s*$",
    re.IGNORECASE,
)
_MAX_HEADING_LEN: Final[int] = 60


def _looks_like_heading(line: str) -> bool:
    return (
        0 < len(line) <= _MAX_HEADING_LEN
        and not line.endswith((".", ",", ";"))
        and not (line.startswith(_LIST_ITEM_PREFIX))
    )


def extract_requirements(text: str | None) -> str | None:
    """Return the block under a "Requirements"-style heading in plain text, if present.

    Collects lines after the first matching heading until the next heading-like
    line or the end. Returns ``None`` when no such section exists.
    """
    if not text:
        return None
    lines = text.split("\n")
    for idx, line in enumerate(lines):
        if not _REQ_HEADING_RE.match(line.strip()):
            continue
        body: list[str] = []
        for candidate in lines[idx + 1 :]:
            stripped = candidate.strip()
            if body and _looks_like_heading(stripped) and not stripped[0].islower():
                break
            body.append(stripped)
        section = "\n".join(body).strip()
        return section or None
    return None
