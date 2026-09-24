"""WO-1034: fixes found by calibration run A (2026-09-23).

1. 34 of 200 governments left no Verdict row: an unhandled
   `ClientResponseError` (a site honouring `Accept-Encoding: br`, e.g.
   Oxnard, CA) escaped `run_one()`.
2. `try_next` and `requests_total` were computed but never written to the
   CSV (the writer lists fields by hand).
3. Fetcher offered Brotli, which aiohttp can't decode without an optional
   package.

Synthetic stubs for the runner (no network), per CLAUDE.md."""

import asyncio
import csv
from pathlib import Path

from app.platforms.meeting_finder import runner
from app.platforms.meeting_finder.fetch import Fetcher
from app.platforms.meeting_finder.models import OUTCOME_ERROR, FinderInput, VerdictRow
from app.platforms.meeting_finder.verdict import append_verdict


def test_csv_writes_try_next_and_requests_total(tmp_path: Path):
    out = tmp_path / "v.csv"
    append_verdict(
        out,
        VerdictRow(
            run_id="t",
            input_url="essex.ca",
            entry_phase="start",
            outcome="youtube-lead-only",
            requests_total=17,
            try_next="YouTube only: send to the drip",
        ),
    )
    row = next(csv.DictReader(out.open()))
    assert row["try_next"] == "YouTube only: send to the drip"
    assert row["requests_total"] == "17"


def test_an_unexpected_error_becomes_a_row_not_a_missing_government(
    monkeypatch, tmp_path: Path
):
    async def boom(finder_input, **kwargs):
        if finder_input.url == "oxnard.gov":
            raise RuntimeError(
                "400, message='Can not decode content-encoding: brotli (br)'"
            )
        return VerdictRow(run_id="t", input_url=finder_input.url, entry_phase="start")

    monkeypatch.setattr(runner, "run_one", boom)
    out = tmp_path / "v.csv"
    rows = asyncio.run(
        runner.run_inputs(
            [FinderInput(url="oxnard.gov"), FinderInput(url="dublin.ca.gov")],
            out,
            concurrency=4,
        )
    )
    assert len(rows) == 2
    written = {r["input_url"]: r for r in csv.DictReader(out.open())}
    assert set(written) == {"oxnard.gov", "dublin.ca.gov"}
    assert written["oxnard.gov"]["outcome"] == OUTCOME_ERROR
    assert "brotli" in written["oxnard.gov"]["note"]
    assert written["oxnard.gov"]["try_next"]


def test_fetcher_never_offers_brotli():
    f = Fetcher(max_fetches=1)
    for browser in (False, True):
        headers = {k.lower(): v for k, v in f._headers(browser=browser).items()}
        assert "br" not in headers.get("accept-encoding", "").split(", ")
