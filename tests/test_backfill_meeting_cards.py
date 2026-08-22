"""scripts/backfill_meeting_cards.py -- the WO-37 driver that sweeps
POST /internal/thumbnails/backfill across the whole Archive.

Everything here is offline. The sweep is exercised against a fake
in-memory Archive (`FakeArchive` below) rather than aiohttp: what's under
test is the batching/frontier/resume logic, not HTTP, and this suite's
network-free property is deliberate (see tests/conftest.py's
`_no_real_card_extraction` fixture). The fake reproduces the two real
behaviours the whole design hangs off, both read out of
`crud.list_pages_missing_default_thumbnail()`:

  * a page that gets a frame stored leaves the candidate queue, and
  * a page whose extraction fails does not -- it stays a candidate
    forever, at the newest-first head of every later response.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from backfill_meeting_cards import (  # noqa: E402
    State,
    build_parser,
    estimate_remaining,
    format_duration,
    host_breakdown,
    leading_known_failures,
    media_host,
    sweep,
)


# --- pure helpers --------------------------------------------------------


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


def test_leading_known_failures_counts_only_the_prefix():
    window = [{"slug": "a"}, {"slug": "b"}, {"slug": "c"}, {"slug": "d"}]
    # The frontier is the first slug that isn't already known stuck --
    # "d" being a known failure further down must NOT be skipped over,
    # because everything after the frontier is real, unattempted work.
    assert leading_known_failures(window, {"a", "b", "d"}) == 2
    assert leading_known_failures(window, set()) == 0
    assert leading_known_failures([], {"a"}) == 0


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
    args = build_parser().parse_args(["--apply"])
    assert args.apply is True


def test_batching_knobs_parse():
    args = build_parser().parse_args(
        ["--apply", "--batch-size", "3", "--sleep", "0", "--max-batches", "2"]
    )
    assert (args.batch_size, args.sleep_seconds, args.max_batches) == (3, 0.0, 2)


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

    def __init__(self, slugs, always_fail=()):
        self.queue = [
            {"slug": s, "video_url": f"https://cdn.example/{s}.mp4"} for s in slugs
        ]
        self.always_fail = set(always_fail)
        self.extraction_attempts = []
        self.probe_calls = 0
        self.batch_calls = []

    async def probe(self, _session, *, offset, limit):
        self.probe_calls += 1
        return self.queue[offset : offset + limit]

    async def run_batch(self, _session, *, offset, limit):
        self.batch_calls.append((offset, limit))
        window = self.queue[offset : offset + limit]
        results = []
        for candidate in window:
            slug = candidate["slug"]
            self.extraction_attempts.append(slug)
            if slug in self.always_fail:
                results.append(
                    {
                        "slug": slug,
                        "video_url": candidate["video_url"],
                        "offset_seconds": None,
                    }
                )
            else:
                results.append(
                    {
                        "slug": slug,
                        "video_url": candidate["video_url"],
                        "offset_seconds": 900,
                    }
                )
                self.queue = [c for c in self.queue if c["slug"] != slug]
        return {"dry_run": False, "offset": offset, "results": results}


@pytest.fixture
def wired(monkeypatch):
    """Point the script's two HTTP calls at a FakeArchive."""

    def _wire(archive):
        import backfill_meeting_cards as script

        monkeypatch.setattr(script, "probe", archive.probe)
        monkeypatch.setattr(script, "run_batch", archive.run_batch)
        monkeypatch.setattr(script, "RETRY_DELAY_SECONDS", 0)
        return archive

    return _wire


async def test_sweep_clears_a_clean_queue_and_stops(tmp_path, wired):
    archive = wired(FakeArchive([f"page-{i}" for i in range(7)]))
    state = State(tmp_path / "s.json", "https://archive.example")

    assert (
        await sweep(None, batch_size=3, sleep_seconds=0, max_batches=None, state=state)
        == 0
    )
    assert archive.queue == []
    # Every page attempted exactly once -- no page is redone, which is the
    # cheap half of resumability (a stored frame leaves the queue).
    assert sorted(archive.extraction_attempts) == sorted(f"page-{i}" for i in range(7))
    assert state.stored_total == 7
    assert state.failed == {}


async def test_sweep_steps_over_failures_instead_of_stalling(tmp_path, wired):
    # The failure mode this script exists to avoid: the 3 newest pages
    # can never be extracted, so with a fixed limit and no offset they
    # would be the *only* thing every call ever returned.
    archive = wired(
        FakeArchive(
            [f"page-{i}" for i in range(9)],
            always_fail={"page-0", "page-1", "page-2"},
        )
    )
    state = State(tmp_path / "s.json", "https://archive.example")

    assert (
        await sweep(None, batch_size=3, sleep_seconds=0, max_batches=None, state=state)
        == 0
    )
    assert [c["slug"] for c in archive.queue] == ["page-0", "page-1", "page-2"]
    assert state.stored_total == 6
    assert set(state.failed) == {"page-0", "page-1", "page-2"}
    # Each stuck page was tried once and then skipped by slug, not
    # re-attempted on every later round.
    assert archive.extraction_attempts.count("page-0") == 1


async def test_a_resumed_run_skips_pages_already_known_stuck(tmp_path, wired):
    path = tmp_path / "s.json"
    first = State(path, "https://archive.example")
    for slug in ("page-0", "page-1"):
        first.record_failure(slug, "https://cdn.example/x.mp4")
    first.save()

    archive = wired(
        FakeArchive([f"page-{i}" for i in range(5)], always_fail={"page-0", "page-1"})
    )
    resumed = State.load(path, "https://archive.example")
    await sweep(None, batch_size=2, sleep_seconds=0, max_batches=None, state=resumed)

    # The two dead sources are never shelled out to again: that's the
    # expensive half of resumability (each retry would cost a fresh
    # ffprobe against an unreachable CDN before anything else).
    assert "page-0" not in archive.extraction_attempts
    assert "page-1" not in archive.extraction_attempts
    assert sorted(archive.extraction_attempts) == ["page-2", "page-3", "page-4"]


async def test_max_batches_bounds_a_first_run(tmp_path, wired):
    archive = wired(FakeArchive([f"page-{i}" for i in range(20)]))
    state = State(tmp_path / "s.json", "https://archive.example")

    await sweep(None, batch_size=4, sleep_seconds=0, max_batches=2, state=state)
    assert len(archive.extraction_attempts) == 8
    assert len(archive.queue) == 12


async def test_state_is_written_as_it_goes_not_only_at_the_end(tmp_path, wired):
    path = tmp_path / "s.json"
    archive = wired(FakeArchive(["a", "b", "c"], always_fail={"a"}))
    state = State(path, "https://archive.example")
    await sweep(None, batch_size=1, sleep_seconds=0, max_batches=1, state=state)

    # One batch in, the file already knows "a" is stuck -- a run killed
    # mid-sweep must not lose what it learned.
    saved = json.loads(path.read_text())
    assert list(saved["failed"]) == ["a"]
    assert archive.queue[0]["slug"] == "a"


async def test_repeated_batch_errors_give_up_nonzero(tmp_path, wired, monkeypatch):
    import backfill_meeting_cards as script

    archive = wired(FakeArchive(["a", "b", "c"]))

    async def _boom(_session, *, offset, limit):
        raise RuntimeError("backfill failed (502): upstream")

    monkeypatch.setattr(script, "run_batch", _boom)
    state = State(tmp_path / "s.json", "https://archive.example")

    assert (
        await sweep(None, batch_size=1, sleep_seconds=0, max_batches=None, state=state)
        == 1
    )
    # It stopped rather than hammering the Archive forever, and it did so
    # without recording any page as stuck (the pages are fine; the call
    # wasn't).
    assert state.failed == {}
    assert archive.extraction_attempts == []


async def test_an_archive_that_ignores_offset_is_detected_not_looped_on(
    tmp_path, wired, monkeypatch
):
    import backfill_meeting_cards as script

    archive = wired(FakeArchive(["a", "b", "c"], always_fail={"a"}))

    async def _ignores_offset(_session, *, offset, limit):
        # What an Archive deployed before WO-37 does: FastAPI silently
        # drops the unknown `offset` query param, so every call returns
        # the same head -- and the head is a page that can never succeed.
        return archive.queue[:limit]

    monkeypatch.setattr(script, "probe", _ignores_offset)
    state = State(tmp_path / "s.json", "https://archive.example")
    state.record_failure("a", None)

    assert (
        await sweep(None, batch_size=1, sleep_seconds=0, max_batches=None, state=state)
        == 1
    )
    assert archive.extraction_attempts == []
