"""Stopping a bulk re-resolve when the far end starts refusing us.

Measured incident, 2026-08-22: `dedupe_rollup_transcripts.py --apply`
hit `HTTP Error 429: Too Many Requests` on ten consecutive
YouTube-backed pages and worked through every one of them. Its
`consecutive_errors` counter *was* incremented on that path -- the
threshold was only ever *checked* inside the `except` branch, which
resolve failures never reach. A retry ten minutes later at 60s spacing
failed identically on its first request, so the block outlives pacing
and every extra request plausibly extends it.

`backfill_archived_pages.py` had no breaker at all.
"""

import pytest

from app.utils.rate_limit import looks_rate_limited
from scripts.dedupe_rollup_transcripts import MAX_CONSECUTIVE_ERRORS, _should_abort


# --- the detector ------------------------------------------------------

# The exact string the 2026-08-22 run produced, twice, ten times each.
_REAL_429 = "resolve failed: HTTP Error 429: Too Many Requests"


@pytest.mark.parametrize(
    "message",
    [
        _REAL_429,
        "HTTP Error 429",
        "Too Many Requests",
        "You are being rate limited",
        "rate-limited",
        # yt-dlp's shape for a YouTube block: prose, no status code.
        "ERROR: Sign in to confirm you're not a bot",
        "This account is temporarily blocked",
    ],
)
def test_recognises_a_refusal(message):
    assert looks_rate_limited(message) is True


@pytest.mark.parametrize(
    "message",
    [
        None,
        "",
        # Every one of these is a real per-page failure seen in the same
        # runs -- they must NOT stop the whole sweep.
        "ffmpeg timed out after 120s",
        "refused: fresh resolve produced no segments",
        "HTTP Error 404: Not Found",
        "HTTP Error 500: Internal Server Error",
        "ingest returned no version_id (no segments?)",
    ],
)
def test_a_broken_page_is_not_a_refusal(message):
    assert looks_rate_limited(message) is False


def test_a_404_is_not_mistaken_for_a_429():
    # Guards the digit match specifically -- "429" must not match inside
    # an unrelated number.
    assert looks_rate_limited("HTTP Error 404: Not Found") is False
    assert looks_rate_limited("processed 14290 segments") is False


# --- the breaker -------------------------------------------------------


def test_one_rate_limit_stops_the_run_immediately():
    # Hair-trigger on purpose: waiting for MAX_CONSECUTIVE_ERRORS would
    # send four more requests into a wall. This is the exact regression
    # -- ten 429s in a row previously aborted nothing.
    assert _should_abort(1, _REAL_429) is True


def test_an_ordinary_failure_does_not_stop_the_run_early():
    assert _should_abort(1, "ffmpeg timed out after 120s") is False
    assert _should_abort(MAX_CONSECUTIVE_ERRORS - 1, "ffmpeg timed out") is False


def test_enough_ordinary_failures_still_stop_the_run():
    assert _should_abort(MAX_CONSECUTIVE_ERRORS, "ffmpeg timed out") is True


def test_the_resolve_failure_path_now_reaches_the_threshold_check():
    # The narrow bug: the else-branch incremented the counter but never
    # tested it. Both failure paths now route through _should_abort, so
    # the same count produces the same verdict either way.
    assert _should_abort(MAX_CONSECUTIVE_ERRORS, "some resolve failure") is True
    assert _should_abort(MAX_CONSECUTIVE_ERRORS, RuntimeError("boom")) is True
