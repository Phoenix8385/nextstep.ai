"""Content hashing used to deduplicate job postings across sources."""

import hashlib
from typing import Final

_FIELD_SEPARATOR: Final[str] = "\x1f"  # ASCII unit separator: cannot appear in normalised text

DESCRIPTION_HASH_CHARS: Final[int] = 500
"""Only this many leading description characters feed the hash, so edits to
trailing boilerplate (EEO statements, benefits) do not register as new postings."""


def _normalise(value: str | None) -> str:
    """Lower-case and collapse whitespace so cosmetic edits do not change the hash."""
    return " ".join((value or "").lower().split())


def compute_content_hash(
    *,
    title: str,
    company_name: str,
    location: str | None,
    description: str | None,
) -> str:
    """Return a stable SHA-256 hex digest identifying a posting's content.

    Input is ``title + company_name + location + description[:500]``, each
    lower-cased with whitespace collapsed. The same role reposted under a new
    external id (or on a second board) yields the same hash, which is what the
    ingestion dedupe step keys on.
    """
    payload = _FIELD_SEPARATOR.join(
        _normalise(part)
        for part in (
            title,
            company_name,
            location,
            (description or "")[:DESCRIPTION_HASH_CHARS],
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
