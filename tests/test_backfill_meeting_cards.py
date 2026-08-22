"""scripts/backfill_meeting_cards.py -- the WO-37 driver that sweeps
POST /internal/thumbnails/backfill across the whole Archive, interleaved
across media hosts and paced per host.

Everything here is offline. The sweep is exercised against a fake
in-memory Archive (`FakeArchive` below) rather than aiohttp: what's under
test is the ordering/pacing/resume logic, not HTTP, and this suite's
network-free property is deliberate (see tests/conftest.py's
`_no_real_card_extraction` fixture). The fake reproduces the two real
behaviours the whole design hangs off, both read out of
`crud.list_pages_missing_default_thumbnail()`:

  * a page that gets a frame stored leaves the candidate queue, and
  * a page whose extraction fails does not -- it stays a candidate
    forever.

The pacing itself is tested through the pure `plan_batch()` with a
synthetic clock rather than by letting the sweep really sleep for 30
seconds.
"""

import json
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from backfill_meeting_cards import (  # noqa: E402
    GRANICUS_PACING_KEY,
    State,
    build_parser,
    cooldown_seconds,
    estimate_remaining,
    format_duration,
    host_breakdown,
    interleave_by_host,
    media_host,
    pacing_key,
    plan_batch,
    projected_seconds,
    sweep,
)

# The real production shape, measured 2026-08-21 -- used wherever a test
# needs the mix to be honest rather than convenient.
REAL_LANE_MIX = {
    "granicus.com": 1016,
    "isilive.ca": 188,
    "iqm2.com": 160,
    "azureedge.net": 154,
    "cablecast.tv": 150,
    "champds.com": 18,
    "cloudfront.net": 10,
    "akamaized.net": 9,
}


def _candidates(mix: dict) -> list:
    out = []
    for lane, count in mix.items():
        for i in range(count):
            out.append(
                {
                    "slug": f"{lane.split('.')[0]}-{i}",
                    "video_url": f"https://cdn.{lane}/{i}.mp4",
                }
            )
    return out


# --- hosts and lanes -----------------------------------------------------


def test_media_host_survives_a_junk_video_url():
    assert media_host("https://archive-media.granicus.com/x.mp4") == (
        "archive-media.granicus.com"
    )
    assert media_host(None) == "(none)"
    assert media_host("not a url at all") == "(unparseable)"


def test_host_breakdown_groups_by_cdn():
    counts = host_breakdown(
        [
            {"video_url": "https://archive-media.granicus.com/a.mp4"},
            {"video_url": "https://archive-media.granicus.com/b.mp4"},
            {"video_url": "https://MediaHTTP.IQM2.com/c.mp4"},
        ]
    )
    assert counts["archive-media.granicus.com"] == 2
    # `.hostname` case-folds, which is what we want here: the real stored
    # IQM2 URLs are mixed-case and would otherwise split into two buckets.
    assert counts["mediahttp.iqm2.com"] == 1


def test_pacing_key_collapses_a_providers_subdomains():
    # The two real Granicus media hosts share one upstream and must share
    # one budget -- that upstream is the one the transcription workers
    # are already straining.
    assert pacing_key("archive-stream.granicus.com") == GRANICUS_PACING_KEY
    assert pacing_key("archive-video.granicus.com") == GRANICUS_PACING_KEY
    # ~100 real per-city Cablecast subdomains, one provider.
    assert pacing_key("reflect-vod-salem.cablecast.tv") == "cablecast.tv"
    assert pacing_key("kdol.cablecast.tv") == "cablecast.tv"
    assert pacing_key("localhost") == "localhost"


def test_granicus_gets_its_own_longer_cooldown():
    assert (
        cooldown_seconds(GRANICUS_PACING_KEY, default_seconds=10, granicus_seconds=30)
        == 30
    )
    assert cooldown_seconds("iqm2.com", default_seconds=10, granicus_seconds=30) == 10


# --- interleaving --------------------------------------------------------


def test_interleave_spreads_the_dominant_host_across_the_whole_run():
    plan = interleave_by_host(_candidates(REAL_LANE_MIX))
    assert len(plan) == sum(REAL_LANE_MIX.values())

    # The failure mode this ordering exists to prevent: a naive
    # round-robin drains the small lanes first and leaves the tail as one
    # unbroken Granicus run. Granicus is 60% of the corpus, so its share
    # of the last tenth should look like its share of the first tenth --
    # not 100%.
    tenth = len(plan) // 10
    first = sum(1 for p in plan[:tenth] if p["lane"] == GRANICUS_PACING_KEY) / tenth
    last = sum(1 for p in plan[-tenth:] if p["lane"] == GRANICUS_PACING_KEY) / tenth
    assert 0.5 < first < 0.7
    assert 0.5 < last < 0.7

    # No long unbroken Granicus run anywhere either. The bound is loose
    # on purpose and worth being honest about: run length here is set by
    # how many *other* lanes happen to be dense in that stretch, and the
    # small lanes' first entries start part-way in (an 18-page lane's
    # stride is ~95 slots), so the opening stretch is thinner than the
    # middle. A handful is fine -- consecutive plan entries from one lane
    # are not consecutive *requests*, because plan_batch() puts at most
    # one page per lane in a batch and then waits out that lane's
    # cooldown. That is the real guarantee; this is the ordering that
    # keeps other work available to fill the wait.
    longest = current = 0
    for item in plan:
        current = current + 1 if item["lane"] == GRANICUS_PACING_KEY else 0
        longest = max(longest, current)
    assert longest <= 6
    # For contrast, unordered input runs to the full 1016.
    assert longest < REAL_LANE_MIX["granicus.com"] / 100


def test_interleave_spreads_a_small_host_end_to_end():
    # 18 champds pages among 1705 must not all land in the first 2% of
    # the run -- they are what fills Granicus's cooldown gaps later on.
    plan = interleave_by_host(_candidates(REAL_LANE_MIX))
    positions = [i for i, p in enumerate(plan) if p["lane"] == "champds.com"]
    assert positions[0] < len(plan) * 0.1
    assert positions[-1] > len(plan) * 0.9


def test_interleave_keeps_newest_first_within_a_host():
    plan = interleave_by_host(
        [
            {"slug": "g-newest", "video_url": "https://a.granicus.com/1.mp4"},
            {"slug": "g-older", "video_url": "https://a.granicus.com/2.mp4"},
            {"slug": "i-newest", "video_url": "https://a.iqm2.com/3.mp4"},
        ]
    )
    granicus = [p["slug"] for p in plan if p["lane"] == GRANICUS_PACING_KEY]
    assert granicus == ["g-newest", "g-older"]
    assert {p["lane"] for p in plan} == {GRANICUS_PACING_KEY, "iqm2.com"}


def test_interleave_is_deterministic():
    candidates = _candidates({"granicus.com": 7, "iqm2.com": 5, "isilive.ca": 5})
    assert [p["slug"] for p in interleave_by_host(candidates)] == [
        p["slug"] for p in interleave_by_host(candidates)
    ]


def test_interleave_of_nothing_is_nothing():
    assert interleave_by_host([]) == []


# --- per-host pacing -----------------------------------------------------


def _pending(lanes: list) -> list:
    return [
        {"slug": f"{lane}-{i}", "lane": lane, "video_url": f"https://cdn.{lane}/x.mp4"}
        for i, lane in enumerate(lanes)
    ]


def _cooldown(default=10.0, granicus=30.0):
    return lambda lane: granicus if lane == GRANICUS_PACING_KEY else default


def test_a_batch_never_holds_two_pages_from_one_host():
    # The endpoint extracts a batch back-to-back with no pacing of its
    # own, so two same-host pages in one request would be two immediate
    # hits however long the cooldown is.
    pending = _pending(["granicus.com"] * 4 + ["iqm2.com"] * 2)
    batch, wait = plan_batch(
        pending, last_hit={}, now=0.0, batch_size=5, cooldown_for=_cooldown()
    )
    assert wait == 0.0
    assert Counter(item["lane"] for item in batch) == {
        GRANICUS_PACING_KEY: 1,
        "iqm2.com": 1,
    }


def test_a_cooling_host_is_skipped_and_a_ready_one_takes_its_place():
    pending = _pending(["granicus.com", "iqm2.com"])
    batch, wait = plan_batch(
        pending,
        last_hit={GRANICUS_PACING_KEY: 100.0},
        now=110.0,  # 10s since the last Granicus hit, cooldown is 30s
        batch_size=5,
        cooldown_for=_cooldown(),
    )
    assert wait == 0.0
    assert [item["lane"] for item in batch] == ["iqm2.com"]


def test_when_everything_is_cooling_it_reports_how_long_to_wait():
    pending = _pending(["granicus.com", "iqm2.com"])
    batch, wait = plan_batch(
        pending,
        last_hit={GRANICUS_PACING_KEY: 100.0, "iqm2.com": 105.0},
        now=110.0,
        batch_size=5,
        cooldown_for=_cooldown(),
    )
    # iqm2 frees up first: hit at 105 + 10s cooldown = 115, i.e. 5s away.
    assert batch == []
    assert wait == pytest.approx(5.0)


def test_an_empty_plan_is_not_a_wait():
    batch, wait = plan_batch(
        [], last_hit={}, now=0.0, batch_size=5, cooldown_for=_cooldown()
    )
    assert (batch, wait) == ([], 0.0)


def test_the_projection_is_set_by_the_busiest_lane():
    lanes = Counter(REAL_LANE_MIX)
    projected = projected_seconds(
        lanes,
        batch_size=5,
        sleep_seconds=5,
        cooldown_for=_cooldown(),
        page_seconds=4,
    )
    # 1016 Granicus pages at one per 30s is the floor, and it dominates:
    # ~8.5 hours. That is the deliberate trade -- a slower sweep that
    # leaves the transcription workers alone.
    assert projected == pytest.approx((1016 - 1) * 30.0)
    assert 8 * 3600 < projected < 9 * 3600


def test_the_projection_falls_back_to_throughput_when_cooldowns_are_off():
    lanes = Counter({"a.com": 40, "b.com": 40})
    projected = projected_seconds(
        lanes,
        batch_size=5,
        sleep_seconds=0,
        cooldown_for=lambda _lane: 0.0,
        page_seconds=4,
    )
    assert projected == pytest.approx(16 * (5 * 4))


# --- small pure helpers --------------------------------------------------


def test_format_duration_reads_like_a_clock():
    assert format_duration(9) == "9s"
    assert format_duration(125) == "2m05s"
    assert format_duration(7325) == "2h02m"
    assert format_duration(-5) == "0s"


def test_eta_needs_real_observed_throughput():
    assert estimate_remaining(elapsed_seconds=0, done=0, remaining=100) is None
    assert estimate_remaining(elapsed_seconds=60, done=10, remaining=0) is None
    # 10 pages in 60s, 100 to go -> 10 minutes.
    assert estimate_remaining(elapsed_seconds=60, done=10, remaining=100) == "10m00s"


# --- argument handling ---------------------------------------------------


def test_dry_run_is_the_default():
    args = build_parser().parse_args([])
    assert args.apply is False
    assert build_parser().parse_args(["--apply"]).apply is True


def test_granicus_is_paced_harder_than_everything_else_by_default():
    args = build_parser().parse_args([])
    assert args.granicus_cooldown > args.host_cooldown


def test_pacing_knobs_parse():
    args = build_parser().parse_args(
        [
            "--apply",
            "--batch-size",
            "3",
            "--sleep",
            "0",
            "--host-cooldown",
            "2",
            "--granicus-cooldown",
            "7.5",
            "--max-batches",
            "2",
        ]
    )
    assert (args.batch_size, args.sleep_seconds, args.max_batches) == (3, 0.0, 2)
    assert (args.host_cooldown, args.granicus_cooldown) == (2.0, 7.5)


# --- resume state --------------------------------------------------------


def test_state_round_trips(tmp_path):
    path = tmp_path / "state.json"
    state = State(path, "https://archive.example")
    state.record_failure("stuck-one", "https://cdn.example/a.mp4")
    state.record_failure("stuck-one", "https://cdn.example/a.mp4")
    state.stored_total = 7
    state.save()

    reloaded = State.load(path, "https://archive.example")
    assert set(reloaded.failed) == {"stuck-one"}
    assert reloaded.failed["stuck-one"]["attempts"] == 2
    assert reloaded.failed["stuck-one"]["host"] == "cdn.example"
    assert reloaded.stored_total == 7


def test_state_from_another_archive_is_ignored(tmp_path):
    path = tmp_path / "state.json"
    state = State(path, "https://staging.example")
    state.record_failure("stuck-one", None)
    state.save()
    # Slugs recorded against a different Archive would silently mark real
    # production pages as stuck and skip them forever.
    assert State.load(path, "https://archive.example").failed == {}


def test_corrupt_state_is_ignored_not_fatal(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json")
    assert State.load(path, "https://archive.example").failed == {}


def test_a_recovered_page_stops_being_skipped(tmp_path):
    path = tmp_path / "state.json"
    state = State(path, "https://archive.example")
    state.record_failure("was-stuck", None)
    state.record_success("was-stuck")
    assert state.failed == {}


# --- the sweep itself ----------------------------------------------------


class FakeArchive:
    """Stands in for POST /internal/thumbnails/backfill.

    `queue` is the newest-first candidate list. Extraction succeeds unless
    the slug is in `always_fail`; a success removes the page from the
    queue (a stored default frame drops it out of the SQL filter), a
    failure leaves it exactly where it was.
    """

    def __init__(self, candidates, always_fail=(), ignores_slugs=False):
        self.queue = list(candidates)
        self.always_fail = set(always_fail)
        self.ignores_slugs = ignores_slugs
        self.extraction_attempts = []
        self.batches = []

    async def survey_candidates(self, _session):
        return [dict(c) for c in self.queue]

    async def run_batch(self, _session, *, slugs):
        self.batches.append(list(slugs))
        if self.ignores_slugs:
            # A build older than WO-37: FastAPI drops the unknown param
            # and the endpoint falls back to its newest-first window.
            chosen = [c["slug"] for c in self.queue[:10]]
        else:
            chosen = [c["slug"] for c in self.queue if c["slug"] in set(slugs)]
        by_slug = {c["slug"]: c for c in self.queue}
        results = []
        for slug in chosen:
            self.extraction_attempts.append(slug)
            if slug in self.always_fail:
                results.append(
                    {
                        "slug": slug,
                        "video_url": by_slug[slug]["video_url"],
                        "offset_seconds": None,
                    }
                )
            else:
                results.append(
                    {
                        "slug": slug,
                        "video_url": by_slug[slug]["video_url"],
                        "offset_seconds": 900,
                    }
                )
                self.queue = [c for c in self.queue if c["slug"] != slug]
        return {"dry_run": False, "results": results}


@pytest.fixture
def wired(monkeypatch):
    """Point the script's two HTTP calls at a FakeArchive."""

    def _wire(archive):
        import backfill_meeting_cards as script

        monkeypatch.setattr(script, "survey_candidates", archive.survey_candidates)
        monkeypatch.setattr(script, "run_batch", archive.run_batch)
        monkeypatch.setattr(script, "RETRY_DELAY_SECONDS", 0)
        return archive

    return _wire


def _args(*extra):
    # Cooldowns off unless a test says otherwise -- the pacing is covered
    # by plan_batch() above, and a sweep test must never really sleep.
    return build_parser().parse_args(
        [
            "--apply",
            "--sleep",
            "0",
            "--host-cooldown",
            "0",
            "--granicus-cooldown",
            "0",
            *extra,
        ]
    )


async def test_sweep_clears_a_clean_queue_and_stops(tmp_path, wired):
    archive = wired(
        FakeArchive(_candidates({"granicus.com": 4, "iqm2.com": 3, "isilive.ca": 2}))
    )
    state = State(tmp_path / "s.json", "https://archive.example")

    assert await sweep(None, args=_args("--batch-size", "3"), state=state) == 0
    assert archive.queue == []
    # Every page attempted exactly once -- no page is redone, which is the
    # cheap half of resumability (a stored frame leaves the queue).
    assert len(archive.extraction_attempts) == 9
    assert len(set(archive.extraction_attempts)) == 9
    assert state.stored_total == 9
    assert state.failed == {}


async def test_batches_are_composed_across_hosts_not_within_one(tmp_path, wired):
    archive = wired(
        FakeArchive(_candidates({"granicus.com": 6, "iqm2.com": 6, "isilive.ca": 6}))
    )
    state = State(tmp_path / "s.json", "https://archive.example")
    await sweep(None, args=_args("--batch-size", "3"), state=state)

    # Even with cooldowns disabled, the one-page-per-lane rule holds: no
    # request ever asks the Archive for two pages off the same CDN
    # back-to-back.
    for batch in archive.batches:
        lanes = [
            pacing_key(media_host(f"https://cdn.{s.split('-')[0]}.com/x"))
            for s in batch
        ]
        assert len(lanes) == len(set(lanes))


async def test_failures_do_not_stall_the_sweep(tmp_path, wired):
    # The failure mode the old offset-paged design had to work around,
    # and which planning client-side removes entirely: a page that can
    # never be extracted stays in the Archive's queue forever, but it is
    # simply not in the plan a second time.
    candidates = _candidates({"granicus.com": 5, "iqm2.com": 5})
    archive = wired(
        FakeArchive(candidates, always_fail={"granicus-0", "granicus-1", "granicus-2"})
    )
    state = State(tmp_path / "s.json", "https://archive.example")

    assert await sweep(None, args=_args("--batch-size", "2"), state=state) == 0
    assert {c["slug"] for c in archive.queue} == {
        "granicus-0",
        "granicus-1",
        "granicus-2",
    }
    assert state.stored_total == 7
    assert set(state.failed) == {"granicus-0", "granicus-1", "granicus-2"}
    # Each stuck page was tried once this run, not re-attempted.
    assert archive.extraction_attempts.count("granicus-0") == 1


async def test_a_resumed_run_skips_pages_already_known_stuck(tmp_path, wired):
    path = tmp_path / "s.json"
    first = State(path, "https://archive.example")
    for slug in ("granicus-0", "granicus-1"):
        first.record_failure(slug, "https://cdn.granicus.com/x.mp4")
    first.save()

    candidates = _candidates({"granicus.com": 3, "iqm2.com": 2})
    archive = wired(FakeArchive(candidates, always_fail={"granicus-0", "granicus-1"}))
    resumed = State.load(path, "https://archive.example")
    await sweep(None, args=_args("--batch-size", "2"), state=resumed)

    # The two dead sources are never shelled out to again: that's the
    # expensive half of resumability (each retry would cost a fresh
    # ffprobe against an unreachable CDN before anything else).
    assert "granicus-0" not in archive.extraction_attempts
    assert "granicus-1" not in archive.extraction_attempts
    assert sorted(archive.extraction_attempts) == ["granicus-2", "iqm2-0", "iqm2-1"]


async def test_max_batches_bounds_a_first_run(tmp_path, wired):
    archive = wired(FakeArchive(_candidates({"granicus.com": 10, "iqm2.com": 10})))
    state = State(tmp_path / "s.json", "https://archive.example")

    await sweep(
        None, args=_args("--batch-size", "2", "--max-batches", "2"), state=state
    )
    assert len(archive.extraction_attempts) == 4
    assert len(archive.queue) == 16


async def test_state_is_written_as_it_goes_not_only_at_the_end(tmp_path, wired):
    path = tmp_path / "s.json"
    candidates = _candidates({"granicus.com": 2, "iqm2.com": 2})
    archive = wired(FakeArchive(candidates, always_fail={"granicus-0"}))
    state = State(path, "https://archive.example")
    await sweep(
        None, args=_args("--batch-size", "2", "--max-batches", "1"), state=state
    )

    # One batch in, the file already knows the stuck page -- a run killed
    # mid-sweep must not lose what it learned.
    saved = json.loads(path.read_text())
    assert list(saved["failed"]) == ["granicus-0"]
    assert any(c["slug"] == "granicus-0" for c in archive.queue)


async def test_repeated_batch_errors_give_up_nonzero(tmp_path, wired, monkeypatch):
    import backfill_meeting_cards as script

    archive = wired(FakeArchive(_candidates({"granicus.com": 3})))

    async def _boom(_session, *, slugs):
        raise RuntimeError("backfill failed (502): upstream")

    monkeypatch.setattr(script, "run_batch", _boom)
    state = State(tmp_path / "s.json", "https://archive.example")

    assert await sweep(None, args=_args(), state=state) == 1
    # It stopped rather than hammering the Archive forever, and it did so
    # without recording any page as stuck (the pages are fine; the call
    # wasn't).
    assert state.failed == {}
    assert archive.extraction_attempts == []


async def test_an_archive_that_ignores_slugs_is_detected_not_obeyed(tmp_path, wired):
    # A build older than WO-37 drops the `slugs` param and extracts its
    # own newest-first window instead. Every pacing guarantee depends on
    # choosing the pages, so this must stop rather than quietly turn into
    # an unpaced sweep.
    archive = wired(
        FakeArchive(_candidates({"granicus.com": 6, "iqm2.com": 6}), ignores_slugs=True)
    )
    state = State(tmp_path / "s.json", "https://archive.example")

    assert await sweep(None, args=_args("--batch-size", "2"), state=state) == 1
    assert len(archive.batches) == 1
