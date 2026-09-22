"""HTTP plumbing shared by the job-board adapters: client factory, retries, errors."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Final

import httpx
from pydantic import ValidationError

from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_RETRY_DELAY_SECONDS: Final[float] = 60.0
_RETRYABLE_STATUS: Final[frozenset[int]] = frozenset({429, 500, 502, 503, 504})


class FetchError(RuntimeError):
    """A board could not be fetched or its payload could not be parsed."""

    def __init__(self, source: str, board_token: str, reason: str) -> None:
        self.source = source
        self.board_token = board_token
        self.reason = reason
        super().__init__(f"{source}/{board_token}: {reason}")


class BoardNotFoundError(FetchError):
    """The ATS answered 404: the board token is wrong or the company left the platform."""

    def __init__(self, source: str, board_token: str) -> None:
        super().__init__(source, board_token, "board not found (HTTP 404)")


def make_http_client() -> httpx.AsyncClient:
    """An ``AsyncClient`` configured with the project's timeout and User-Agent."""
    return httpx.AsyncClient(
        timeout=httpx.Timeout(settings.HTTP_TIMEOUT_SECONDS),
        headers={"User-Agent": settings.HTTP_USER_AGENT, "Accept": "application/json"},
        follow_redirects=True,
    )


def fallback_company_name(board_token: str) -> str:
    """Best-effort display name from a board slug: ``"acme-corp"`` → ``"Acme Corp"``."""
    return " ".join(part.capitalize() for part in board_token.replace("_", "-").split("-"))


def describe_validation_error(exc: ValidationError) -> str:
    """One-line summary of the first schema violation, for ``FetchError`` messages."""
    errors = exc.errors()
    if not errors:
        return "unexpected payload shape"
    loc = ".".join(str(part) for part in errors[0]["loc"])
    return f"unexpected payload shape at '{loc}': {errors[0]['msg']}"


def _retry_delay(response: httpx.Response | None, attempt: int, backoff: float) -> float:
    """Honour ``Retry-After`` on 429s; otherwise exponential backoff (1x, 2x, 4x ...)."""
    if response is not None and response.status_code == 429:
        header = response.headers.get("Retry-After")
        if header and header.isdigit():
            return min(float(header), MAX_RETRY_DELAY_SECONDS)
    return float(min(backoff * (2**attempt), MAX_RETRY_DELAY_SECONDS))


async def get_json(
    http: httpx.AsyncClient,
    url: str,
    *,
    source: str,
    board_token: str,
    params: dict[str, str] | None = None,
    retries: int | None = None,
    backoff: float | None = None,
) -> Any:
    """GET ``url`` and return decoded JSON, retrying transient failures.

    Retries (default ``settings.HTTP_RETRIES``, exponential backoff from
    ``settings.HTTP_RETRY_BACKOFF_SECONDS``) apply to network errors, 429 and
    5xx responses. A 404 raises :class:`BoardNotFoundError` immediately; other
    4xx responses and invalid JSON raise :class:`FetchError` without retrying.
    """
    max_retries = settings.HTTP_RETRIES if retries is None else retries
    base_backoff = settings.HTTP_RETRY_BACKOFF_SECONDS if backoff is None else backoff

    for attempt in range(max_retries + 1):
        response: httpx.Response | None = None
        try:
            response = await http.get(url, params=params)
        except httpx.HTTPError as exc:
            failure = FetchError(source, board_token, f"{type(exc).__name__}: {exc}")
        else:
            if response.status_code == 404:
                raise BoardNotFoundError(source, board_token)
            if response.status_code in _RETRYABLE_STATUS:
                failure = FetchError(source, board_token, f"HTTP {response.status_code} from {url}")
            elif response.status_code >= 400:
                raise FetchError(source, board_token, f"HTTP {response.status_code} from {url}")
            else:
                try:
                    return response.json()
                except ValueError as exc:
                    raise FetchError(source, board_token, f"invalid JSON from {url}") from exc

        if attempt == max_retries:
            raise failure
        delay = _retry_delay(response, attempt, base_backoff)
        logger.warning(
            "%s/%s: %s — retry %d/%d in %.1fs",
            source,
            board_token,
            failure.reason,
            attempt + 1,
            max_retries,
            delay,
        )
        await asyncio.sleep(delay)

    raise AssertionError("unreachable")  # pragma: no cover
