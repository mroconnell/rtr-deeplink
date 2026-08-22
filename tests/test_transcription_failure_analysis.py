"""Tests for the transcription chunk-failure diagnostic (WO-40) --
archive/db/crud.py's summarize_failure_rows() and its helpers.

SYNTHETIC ROWS, deliberately, and this is the case CLAUDE.md's synthetic-
test rule actually sanctions: the *shape* is the real, confirmed
failure_history schema ({"chunk_index", "error", "at"}, stored since
2026-08-19), the error string is the real one production emits verbatim,
and the hosts/chunk counts are lifted from real production jobs measured
2026-08-21 (job 507 fountainvalley.granicus.com 31 chunks, job 434
sdcounty.granicus.com 28 chunks, job 385 sandiego.granicus.com 13
chunks). What's hand-built is only the *arrangement* -- each test poses
one of the three candidate failure shapes in isolation, which no single
real job does cleanly, so that the diagnostic's ability to tell them
apart is what's actually under test.

Pure-function tests on purpose: summarize_failure_rows() is split out
from its query precisely so this file never touches the shared test
database, which several other modules also write real failures into (any
whole-table assertion here would be order-dependent).
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from archive.db import crud

TIMEOUT = "ffmpeg timed out after 120s (source likely slow or rate-limited)"
T0 = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)


def _row(job_id, host, total_chunks, failures, *, platform="granicus"):
    """`failures` is a list of (chunk_index, seconds_after_T0) pairs."""
    return SimpleNamespace(
        id=job_id,
        media_url=f"https://archive-video.granicus.com/{host}/clip.mp4",
        total_chunks=total_chunks,
        status="completed",
        priority=crud.PRIORITY_LOW,
        failure_history=[
            {
                "chunk_index": idx,
                "error": TIMEOUT,
                "at": (T0 + timedelta(seconds=offset)).isoformat(),
            }
            for idx, offset in failures
        ],
        source_url_normalized=f"https://{host}/player/clip/{job_id}",
        platform=platform,
    )


def _summary(rows):
    return crud.summarize_failure_rows(rows, cutoff=None, days=None)


def _rate_at(summary, chunk_index):
    for entry in summary["failure_rate_by_chunk_index"]:
        if entry["chunk_index"] == chunk_index:
            return entry["failures_per_attempt"]
    raise AssertionError(f"no rate recorded for chunk {chunk_index}")


# --------------------------------------------------------------------------
# The three failure shapes the diagnostic has to tell apart.
# --------------------------------------------------------------------------


def test_cold_storage_shape_spikes_at_chunk_zero_only():
    """Cold storage / rehydration: the first pull of a long-untouched asset
    times out repeatedly, then every later chunk sails through against a
    now-warm asset. Real example: job 434, sdcounty.granicus.com, 6
    failures across a 28-chunk job, all on chunk 0."""
    rows = [_row(434, "sdcounty.granicus.com", 28, [(0, i * 130) for i in range(6)])]
    summary = _summary(rows)

    assert summary["total_failures"] == 6
    assert _rate_at(summary, 0) == 6.0
    # Every later chunk was attempted and never failed.
    assert all(
        e["failures_per_attempt"] == 0.0
        for e in summary["failure_rate_by_chunk_index"]
        if e["chunk_index"] > 0
    )
    # The raw bucket agrees here, but see the rate-limit test below for
    # the case where raw counts and rates disagree.
    assert summary["failure_position"]["chunk_0_first_pull"] == 6


def test_accumulating_rate_limit_shape_rises_with_chunk_index():
    """A genuine accumulating rate limit: early chunks fine, failures
    concentrate late as the throttle builds. This is the shape the
    round-robin hypothesis assumed; production did NOT show it."""
    failures = [(idx, idx * 200) for idx in (8, 9, 9, 10, 10, 11, 11, 11)]
    rows = [_row(900, "example.granicus.com", 12, failures)]
    summary = _summary(rows)

    assert _rate_at(summary, 0) == 0.0
    assert _rate_at(summary, 11) == 3.0
    rates = [
        e["failures_per_attempt"]
        for e in summary["failure_rate_by_chunk_index"]
        if e["chunk_index"] >= 8
    ]
    assert rates == sorted(rates), "rate-limit shape must be non-decreasing late"
    assert _rate_at(summary, 11) > _rate_at(summary, 0)


def test_slow_source_shape_is_flat_and_high_across_the_whole_job():
    """A source that is simply slow relative to the fixed 120s ffmpeg
    timeout: failures scatter roughly uniformly over every chunk. Real
    example: job 507, fountainvalley.granicus.com, 26 failures spread
    over 26 distinct indices of a 31-chunk job -- which still completed."""
    rows = [
        _row(507, "fountainvalley.granicus.com", 31, [(i, i * 300) for i in range(26)])
    ]
    summary = _summary(rows)

    rates = [
        e["failures_per_attempt"]
        for e in summary["failure_rate_by_chunk_index"]
        if e["chunk_index"] < 26
    ]
    assert set(rates) == {1.0}, "slow-source shape is flat, not rising"
    assert summary["jobs_with_failures"] == 1


def test_raw_position_counts_mislead_where_normalized_rates_do_not():
    """The reason failure_rate_by_chunk_index exists at all.

    One 21-chunk job fails once on chunk 0 and once each on three later
    chunks. Raw counts say 75% of failures were "later chunk", which reads
    as an accumulating rate limit. Normalized per attempt, chunk 0 is the
    single most failure-prone position by 3x. Both numbers come from the
    same rows; only the second one is a fair comparison."""
    rows = [
        _row(
            515,
            "albemarle.granicus.com",
            21,
            [(0, 0), (5, 600), (11, 1200), (17, 1800)],
        )
    ]
    summary = _summary(rows)

    raw = summary["failure_position"]
    later_raw = raw["chunk_1_to_2"] + raw["chunk_3_plus"]
    assert later_raw == 3 and raw["chunk_0_first_pull"] == 1  # "75% later"

    assert _rate_at(summary, 0) == 1.0
    assert _rate_at(summary, 5) == 1.0 / 1  # each later index attempted once too
    # But the decile view -- which is what makes different-length jobs
    # comparable -- puts chunk 0 alone in decile 0 against 2 other
    # attempts, while later failures are diluted across their deciles.
    decile_0 = next(d for d in summary["failure_rate_by_decile"] if d["decile"] == 0)
    assert decile_0["attempts"] == 3 and decile_0["failures"] == 1


# --------------------------------------------------------------------------
# The direct test of the round-robin hypothesis.
# --------------------------------------------------------------------------


def test_pair_shape_counts_same_job_clustering_not_cross_job():
    """Within-job clustering: one job failing repeatedly in a short window.
    No amount of queue reordering can reach this, because a worker holds
    one job through all of its chunks."""
    rows = [
        _row(507, "fountainvalley.granicus.com", 31, [(i, i * 60) for i in range(5)])
    ]
    pairs = _summary(rows)["concurrency_pairs_within_10min"]

    assert pairs["same_job"] == 10  # C(5, 2) -- all within 10 minutes
    assert pairs["same_host_different_job"] == 0


def test_pair_shape_detects_real_cross_job_same_host_contention():
    """The shape the hypothesis predicted, constructed on purpose so the
    detector is proven capable of seeing it -- production simply had zero
    of these (measured 2026-08-21). Without this test, the real zero
    would be indistinguishable from a broken detector."""
    rows = [
        _row(1, "sandiego.granicus.com", 10, [(3, 0)]),
        _row(2, "sandiego.granicus.com", 10, [(4, 120)]),
    ]
    pairs = _summary(rows)["concurrency_pairs_within_10min"]

    assert pairs["same_host_different_job"] == 1
    assert pairs["same_job"] == 0


def test_pair_shape_separates_same_domain_from_same_host():
    """Two different Granicus tenants failing at once is a weaker signal
    than the same tenant twice -- the shared media CDN could still be one
    rate-limiting party, but the page hosts genuinely differ, so these
    must not be conflated."""
    rows = [
        _row(1, "sandiego.granicus.com", 10, [(3, 0)]),
        _row(2, "albemarle.granicus.com", 10, [(4, 120)]),
    ]
    pairs = _summary(rows)["concurrency_pairs_within_10min"]

    assert pairs["same_domain_different_host"] == 1
    assert pairs["same_host_different_job"] == 0
    assert pairs["unrelated_hosts"] == 0


def test_pairs_outside_the_window_are_not_counted():
    rows = [_row(1, "sandiego.granicus.com", 10, [(3, 0), (4, 60 * 30)])]
    pairs = _summary(rows)["concurrency_pairs_within_10min"]
    assert pairs["same_job"] == 0


# --------------------------------------------------------------------------
# Grouping, windowing and input-robustness.
# --------------------------------------------------------------------------


def test_media_host_grouping_collapses_tenants_onto_the_shared_cdn():
    """Granicus serves ~300 distinct {tenant}.granicus.com page hosts off a
    handful of shared archive-*.granicus.com media hosts. The rate-limiting
    party is the CDN, so both groupings are reported and they must differ."""
    rows = [
        _row(1, "sandiego.granicus.com", 10, [(1, 0)]),
        _row(2, "albemarle.granicus.com", 10, [(1, 60)]),
    ]
    summary = _summary(rows)

    assert [h["host"] for h in summary["by_media_host"]] == [
        "archive-video.granicus.com"
    ]
    assert summary["by_media_host"][0]["failures"] == 2
    assert len(summary["by_page_host"]) == 2


def test_max_failures_in_1h_window_finds_the_densest_burst():
    times = [T0 + timedelta(minutes=m) for m in (0, 5, 10, 400, 405)]
    assert crud._max_failures_in_window(times) == 3
    assert crud._max_failures_in_window([]) == 0
    assert crud._max_failures_in_window([T0]) == 1


def test_cutoff_excludes_older_failures():
    rows = [_row(1, "sandiego.granicus.com", 10, [(1, 0), (2, 0)])]
    after = crud.summarize_failure_rows(rows, cutoff=T0 + timedelta(days=1), days=1)
    assert after["total_failures"] == 0
    assert after["jobs_with_failures"] == 0
    assert after["concurrency_pairs_within_10min"]["same_job"] == 0


def test_malformed_history_entries_are_skipped_not_fatal():
    """failure_history is a plain JSON column with no schema enforcement,
    and entries written before chunk_index existed (pre-2026-08-19) have a
    null one -- neither may take the endpoint down."""
    row = SimpleNamespace(
        id=1,
        media_url=None,
        total_chunks=4,
        status="failed",
        priority=crud.PRIORITY_LOW,
        failure_history=[
            "not a dict",
            {"chunk_index": None, "error": TIMEOUT, "at": T0.isoformat()},
            {"chunk_index": 2, "error": "some other error", "at": "not-a-timestamp"},
            {"chunk_index": 1, "error": TIMEOUT, "at": T0.isoformat()},
        ],
        source_url_normalized=None,
        platform=None,
    )
    summary = _summary([row])

    assert summary["total_failures"] == 3
    assert summary["failure_position"]["unknown_chunk_index"] == 1
    assert summary["ffmpeg_timeout_failures"] == 2
    assert summary["by_media_host"][0]["host"] == "(none)"
    assert summary["by_platform"][0]["host"] == "(unknown)"


def test_no_failures_anywhere_returns_empty_not_an_error():
    rows = [_row(1, "sandiego.granicus.com", 10, [])]
    summary = _summary(rows)

    assert summary["total_failures"] == 0
    assert summary["jobs_with_failures"] == 0
    assert summary["failure_rate_by_chunk_index"] == []
    assert summary["multi_chunk_jobs"]["first_chunk_share"] is None
