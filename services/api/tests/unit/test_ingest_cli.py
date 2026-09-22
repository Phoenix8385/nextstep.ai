"""The ``app.scripts.ingest`` CLI (no network, no database)."""

from collections.abc import Callable
from unittest.mock import patch

import httpx
import pytest

from app.scripts import ingest as ingest_cli
from app.services.ingestion.lever import POSTINGS_URL
from app.services.ingestion.pipeline import SOURCES, SourceAdapter
from tests.conftest import Route, load_fixture

MockHttp = Callable[[dict[str, Route]], httpx.AsyncClient]


def test_cli_requires_source_and_token(capsys: pytest.CaptureFixture[str]) -> None:
    assert ingest_cli.main([]) == 2
    assert "provide SOURCE BOARD_TOKEN" in capsys.readouterr().err


def test_cli_dry_run_prints_summary_without_database(
    mock_http: MockHttp, capsys: pytest.CaptureFixture[str]
) -> None:
    http = mock_http(
        {POSTINGS_URL.format(company="acme"): (200, load_fixture("lever_postings.json"))}
    )
    lever = SOURCES["lever"]

    async def fetch_with_mock(board_token: str, *, company_name: str | None = None, **_: object):  # type: ignore[no-untyped-def]
        return await lever.fetch(board_token, company_name=company_name, http=http)

    with patch.dict(SOURCES, {"lever": SourceAdapter(fetch_with_mock, lever.normalize)}):
        code = ingest_cli.main(["lever", "acme", "--dry-run", "--company", "Acme", "--limit", "1"])

    out = capsys.readouterr().out
    assert code == 0
    assert "lever/acme: 2 postings" in out
    assert "Machine Learning Engineer" in out
    assert "... 1 more" in out


def test_cli_reports_fetch_failure_with_exit_code_1(
    mock_http: MockHttp, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.services.ingestion.http.settings.HTTP_RETRY_BACKOFF_SECONDS", 0.0)
    http = mock_http({POSTINGS_URL.format(company="acme"): (500, {"error": "x"})})
    lever = SOURCES["lever"]

    async def fetch_with_mock(board_token: str, *, company_name: str | None = None, **_: object):  # type: ignore[no-untyped-def]
        return await lever.fetch(board_token, company_name=company_name, http=http)

    with patch.dict(SOURCES, {"lever": SourceAdapter(fetch_with_mock, lever.normalize)}):
        code = ingest_cli.main(["lever", "acme", "--dry-run"])
    assert code == 1
    assert "fetch failed: lever/acme: HTTP 500" in capsys.readouterr().err
