"""Request/response bodies for ``/profile``."""

import uuid
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ``user_profiles.cgpa`` is NUMERIC(3,2), so the largest storable value is 9.99.
CGPA_MAX = 9.99
GRADUATION_YEAR_MIN = 1950
GRADUATION_YEAR_MAX = 2100
MAX_LIST_ITEMS = 50

Cgpa = Annotated[Decimal, Field(ge=0, le=CGPA_MAX, decimal_places=2)]


def _clean_list(values: list[str]) -> list[str]:
    """Strip, drop blanks and de-duplicate (case-insensitively) while keeping order."""
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in values:
        item = raw.strip()
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            cleaned.append(item)
    return cleaned


class ProfileUpdate(BaseModel):
    """Body for ``PUT /profile``.

    Every field is optional; only fields present in the request are written,
    so a client can update a single preference without resending the rest.
    """

    college: str | None = Field(default=None, max_length=255)
    branch: str | None = Field(default=None, max_length=255)
    cgpa: Cgpa | None = None
    graduation_year: int | None = Field(
        default=None, ge=GRADUATION_YEAR_MIN, le=GRADUATION_YEAR_MAX
    )
    experience_level: str | None = Field(default=None, max_length=50)
    preferred_roles: list[str] | None = Field(default=None, max_length=MAX_LIST_ITEMS)
    preferred_locations: list[str] | None = Field(default=None, max_length=MAX_LIST_ITEMS)
    preferred_work_mode: list[str] | None = Field(default=None, max_length=MAX_LIST_ITEMS)
    skills: list[str] | None = Field(default=None, max_length=MAX_LIST_ITEMS)

    @field_validator("college", "branch", "experience_level")
    @classmethod
    def _strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("preferred_roles", "preferred_locations", "preferred_work_mode", "skills")
    @classmethod
    def _clean_lists(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _clean_list(value)


class ProfileResponse(BaseModel):
    """A user's ``user_profiles`` row."""

    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    college: str | None
    branch: str | None
    cgpa: Decimal | None
    graduation_year: int | None
    experience_level: str | None
    preferred_roles: list[str]
    preferred_locations: list[str]
    preferred_work_mode: list[str]
    skills: list[str]
