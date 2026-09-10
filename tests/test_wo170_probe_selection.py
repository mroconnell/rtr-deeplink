"""Tests for WO-170's probe selection rule (2026-09-10).

Ryan's rule, in his own words: "after it rejects the first video, it
would be ideal if the probe selected another video and actually checked
the size of that video file or its duration to ensure that it was at
least 9 minutes long but not longer than 40 minutes. It could check
several videos this way and if all the videos were over 40 minutes, then
select the shortest available video in the list."

Two layers are tested:

1. `app.platforms.queue_probe.select_best_probe_result()` directly, with
   hand-built (SYNTHETIC) `ProbeResult` rows -- the shape is real (every
   field matches what `probe_queue_entry()` actually returns, see that
   module's own docstring), only the specific durations/verdicts here are
   made up, covering the three required cases: an in-window candidate
   beats a longer newer one, every candidate over 40 minutes falls back
   to the shortest, and every candidate dead means no selection at all.
2. `scripts/wo134_confirmed_hits_ingest.resolve_youtube_channel()` end to
   end with `PROBE_SELECT_HOOK` set, the same style
   tests/test_wo169_probe_loop_and_granicus_rss.py already uses for
   `PROBE_HOOK` -- a hand-built two/three-candidate YouTube channel
   listing and a fake finder standing in for a real yt-dlp scan and a
   real YouTubeAssetFinder.resolve() call, since this is about the
   candidate-loop/selection wiring, not YouTube parsing itself (already
   covered by tests/test_youtube_channel.py).
"""

import pytest

import scripts.hub_sweep_wo126 as hs
import scripts.wo134_confirmed_hits_ingest as wo134
from app.platforms import queue_probe as queue_probe_module
from app.platforms import register_all_finders
from app.platforms.models import ResolvedMeeting
from app.platforms.queue_probe import (
    IN_WINDOW_MAX_SECONDS,
    IN_WINDOW_MIN_SECONDS,
    ProbeResult,
    is_plausible,
    select_best_probe_result,
)

register_all_finders()


@pytest.fixture(autouse=True)
def _no_real_sidecar_writes(monkeypatch):
    """_finish_probe_selection() (wo134_confirmed_hits_ingest.py, WO-170)
    calls queue_probe.append_probe_row() for real once a candidate set is
    known -- every test below that exercises the resolve_seed()/
    resolve_youtube_channel() candidate loops goes through that same real
    code path, so without this it would append synthetic test-stub rows
    into the real, committed, shared
    scripts/tier3_auto_transcription_queue_probe.csv sidecar every single
    test run. Real incident this session: exactly that happened before
    this fixture existed, and the polluted rows had to be hand-filtered
    back out of the tracked file."""
    monkeypatch.setattr(queue_probe_module, "append_probe_row", lambda *a, **kw: None)


def _probe(
    url: str, verdict: str, duration_seconds=None, *, reason=None
) -> ProbeResult:
    """SYNTHETIC: a hand-built ProbeResult, matching probe_queue_entry()'s
    own real field shapes exactly (see queue_probe.py's docstring) --
    only the specific url/verdict/duration combinations here are made up,
    standing in for a real probe of several candidate videos."""
    return ProbeResult(
        url=url,
        platform="youtube",
        probe_method="test-stub",
        duration_seconds=duration_seconds,
        date=None,
        size_bytes=None,
        verdict=verdict,
        reason=reason,
        probe_seconds=0.01,
        over_nine_minutes=bool(duration_seconds and duration_seconds > 540),
    )


# --------------------------------------------------------------------------
# select_best_probe_result() -- the selection primitive
# --------------------------------------------------------------------------


def test_is_plausible_accepts_accept_and_flag_long_only():
    assert is_plausible(_probe("u", "accept", 1200))
    assert is_plausible(_probe("u", "flag-long", 30000))
    assert not is_plausible(_probe("u", "reject-dead"))
    assert not is_plausible(_probe("u", "reject-short", 30))


def test_prefers_newest_in_window_candidate_over_a_longer_newer_one():
    """Newest-first input order: the first (newest) candidate is a real
    2-hour meeting (over the 40-minute ceiling), the second (older) one
    is 20 minutes -- squarely in Ryan's 9-40 minute window. The in-window
    candidate must win even though it is NOT the newest."""
    newest_too_long = _probe("https://example/newest", "accept", 2 * 3600)
    older_in_window = _probe("https://example/older", "accept", 20 * 60)
    choice = select_best_probe_result([newest_too_long, older_in_window])
    assert choice is not None
    assert choice.url == "https://example/older"
    assert IN_WINDOW_MIN_SECONDS <= choice.duration_seconds <= IN_WINDOW_MAX_SECONDS


def test_falls_back_to_shortest_when_every_plausible_candidate_is_over_40_minutes():
    """Ryan's own fallback case: three candidates, all over 40 minutes --
    the shortest of the three must be chosen, regardless of newest-first
    order."""
    a = _probe("https://example/a", "accept", 55 * 60)  # newest, 55 min
    b = _probe("https://example/b", "flag-long", 3 * 3600)  # 3 hours
    c = _probe("https://example/c", "accept", 41 * 60)  # oldest, shortest, 41 min
    choice = select_best_probe_result([a, b, c])
    assert choice is not None
    assert choice.url == "https://example/c"
    assert choice.duration_seconds == 41 * 60


def test_no_selection_when_every_candidate_is_dead_or_too_short():
    """Every candidate either dead or under the 60-second floor -- never
    accept either shape (the standing floor and dead-link rule), so this
    must return None and let the caller report rejected_by_probe."""
    dead = _probe("https://example/dead", "reject-dead")
    short = _probe("https://example/short", "reject-short", 12.0)
    assert select_best_probe_result([dead, short]) is None


def test_empty_candidate_list_returns_none():
    assert select_best_probe_result([]) is None


def test_select_best_probe_result_returns_the_probe_result_itself():
    """The choice returned is the ProbeResult, keyed by its own `.url`
    field -- every probe_queue_entry() call already sets `.url` to the
    address it was asked to probe, so a caller doesn't need a separate
    url alongside it."""
    p1 = _probe("u1", "accept", 20 * 60)
    p2 = _probe("u2", "reject-dead")
    choice = select_best_probe_result([p1, p2])
    assert choice is p1
    assert choice.url == "u1"


# --------------------------------------------------------------------------
# End to end: resolve_youtube_channel() with PROBE_SELECT_HOOK
# --------------------------------------------------------------------------

# SYNTHETIC: a hand-built 3-video YouTube channel listing, standing in for
# a real yt-dlp channel scan -- same style as
# tests/test_wo169_probe_loop_and_granicus_rss.py's own
# _SYNTHETIC_CANDIDATES, extended to three entries so a middle candidate
# can be the one the selection actually picks.
_THREE_CANDIDATES = [
    {"id": "aaaaaaaaaaa", "title": "City Council Meeting", "duration": 7200},
    {"id": "bbbbbbbbbbb", "title": "City Council Meeting", "duration": 1200},
    {"id": "ccccccccccc", "title": "City Council Meeting", "duration": 2500},
]

_URL_A = "https://www.youtube.com/watch?v=aaaaaaaaaaa"
_URL_B = "https://www.youtube.com/watch?v=bbbbbbbbbbb"
_URL_C = "https://www.youtube.com/watch?v=ccccccccccc"


class _FakeYouTubeFinder:
    def __init__(self, video_urls_with_video: set):
        self._with_video = video_urls_with_video

    async def resolve(self, video_url: str) -> ResolvedMeeting:
        return ResolvedMeeting(
            platform="youtube",
            source_url=video_url,
            video_url=video_url if video_url in self._with_video else None,
            title="City Council Meeting",
        )


def _durations_by_url() -> dict:
    return {
        _URL_A: 7200.0,  # 2h -- too long
        _URL_B: 1200.0,  # 20 min -- in window
        _URL_C: 2500.0,  # ~41.7 min -- too long, but shorter than A
    }


def _select_hook_from(durations: dict, dead: set = frozenset()):
    """A PROBE_SELECT_HOOK returning real ProbeResult shapes (SYNTHETIC
    durations/verdicts) keyed on the candidate url, standing in for a
    real app.platforms.queue_probe.probe_queue_entry() call."""

    async def hook(result, candidate_url: str) -> ProbeResult:
        if candidate_url in dead:
            return _probe(candidate_url, "reject-dead")
        duration = durations[candidate_url]
        verdict = "flag-long" if duration > 6 * 3600 else "accept"
        return _probe(candidate_url, verdict, duration)

    return hook


async def test_probe_select_hook_prefers_in_window_candidate_end_to_end(monkeypatch):
    """The newest candidate (A, 2 hours) is out of window; the SECOND
    candidate (B, 20 minutes) is in Ryan's 9-40 minute window and must be
    chosen even though a third, older candidate (C) was never even
    needed -- resolve_youtube_channel() stops probing once it finds a
    newest-first in-window match."""
    monkeypatch.setattr(
        wo134, "_list_youtube_channel_entries", lambda url: _THREE_CANDIDATES
    )
    monkeypatch.setattr(
        wo134,
        "get_finder",
        lambda platform: _FakeYouTubeFinder({_URL_A, _URL_B, _URL_C}),
    )
    monkeypatch.setattr(
        wo134, "PROBE_SELECT_HOOK", _select_hook_from(_durations_by_url())
    )
    try:
        result, video_url, high_risk = await wo134.resolve_youtube_channel(
            session=None, channel_url="https://www.youtube.com/channel/UCxxxx"
        )
    finally:
        wo134.PROBE_SELECT_HOOK = None
    assert video_url == _URL_B
    assert result.video_url == _URL_B


async def test_probe_select_hook_falls_back_to_shortest_when_all_over_40_minutes(
    monkeypatch,
):
    """Every candidate is over 40 minutes (A: 2h, C: ~41.7min) -- once B
    is removed from the listing, the shortest of the two remaining
    candidates (C) must be chosen, matching Ryan's own fallback rule."""
    monkeypatch.setattr(
        wo134,
        "_list_youtube_channel_entries",
        lambda url: [_THREE_CANDIDATES[0], _THREE_CANDIDATES[2]],
    )
    monkeypatch.setattr(
        wo134, "get_finder", lambda platform: _FakeYouTubeFinder({_URL_A, _URL_C})
    )
    monkeypatch.setattr(
        wo134, "PROBE_SELECT_HOOK", _select_hook_from(_durations_by_url())
    )
    try:
        result, video_url, high_risk = await wo134.resolve_youtube_channel(
            session=None, channel_url="https://www.youtube.com/channel/UCxxxx"
        )
    finally:
        wo134.PROBE_SELECT_HOOK = None
    assert video_url == _URL_C
    assert result.video_url == _URL_C


async def test_probe_select_hook_reports_rejected_by_probe_when_all_dead(monkeypatch):
    """Every candidate is dead -- resolve_youtube_channel() must raise
    ProbeRejected (Ryan's "only once every candidate is exhausted" rule,
    unchanged from WO-169), never silently accept a dead link."""
    monkeypatch.setattr(
        wo134, "_list_youtube_channel_entries", lambda url: _THREE_CANDIDATES
    )
    monkeypatch.setattr(
        wo134,
        "get_finder",
        lambda platform: _FakeYouTubeFinder({_URL_A, _URL_B, _URL_C}),
    )
    monkeypatch.setattr(
        wo134,
        "PROBE_SELECT_HOOK",
        _select_hook_from(_durations_by_url(), dead={_URL_A, _URL_B, _URL_C}),
    )
    try:
        raised = None
        try:
            await wo134.resolve_youtube_channel(
                session=None, channel_url="https://www.youtube.com/channel/UCxxxx"
            )
        except wo134.ProbeRejected as e:
            raised = e
    finally:
        wo134.PROBE_SELECT_HOOK = None
    assert raised is not None


# --------------------------------------------------------------------------
# resolve_seed()'s own single-candidate (non-listing) path -- a real gap
# found running this WO's own 44-government re-run: this bottom branch
# used to consult ONLY the older PROBE_HOOK (via _candidate_passes_probe),
# so a caller that sets PROBE_SELECT_HOOK but never sets PROBE_HOOK saw a
# single already-known video (the single most common real shape --
# 37 of WO-170's own 44 rows were exactly this, one bare YouTube video,
# not a listing) sail through with NO probe at all.
# --------------------------------------------------------------------------


class _FakeSingleFinder:
    def __init__(self, result: ResolvedMeeting):
        self._result = result

    async def resolve(self, url: str) -> ResolvedMeeting:
        return self._result


async def test_resolve_seed_probes_a_single_non_listing_candidate_under_select_hook(
    monkeypatch,
):
    """A plain https://youtu.be/xxx watch link is not a channel/listing,
    so resolve_seed() resolves it directly at the bottom of the
    function -- PROBE_SELECT_HOOK must still be consulted there, not
    skipped just because there's nothing to select AMONG."""
    seed_url = "https://www.youtube.com/watch?v=deaddeaddea"
    result = ResolvedMeeting(
        platform="youtube", source_url=seed_url, video_url=seed_url, title="Council"
    )
    monkeypatch.setattr(wo134, "get_finder", lambda platform: _FakeSingleFinder(result))
    monkeypatch.setattr(
        wo134, "PROBE_SELECT_HOOK", _select_hook_from({}, dead={seed_url})
    )
    try:
        raised = None
        try:
            await wo134.resolve_seed(
                session=None, platform="youtube", seed_url=seed_url
            )
        except wo134.ProbeRejected as e:
            raised = e
    finally:
        wo134.PROBE_SELECT_HOOK = None
    assert raised is not None


async def test_resolve_seed_accepts_a_single_in_window_candidate_under_select_hook(
    monkeypatch,
):
    seed_url = "https://www.youtube.com/watch?v=goodgoodgood"
    result = ResolvedMeeting(
        platform="youtube", source_url=seed_url, video_url=seed_url, title="Council"
    )
    monkeypatch.setattr(wo134, "get_finder", lambda platform: _FakeSingleFinder(result))
    monkeypatch.setattr(
        wo134, "PROBE_SELECT_HOOK", _select_hook_from({seed_url: 1200.0})
    )
    try:
        out_result, final_seed, high_risk = await wo134.resolve_seed(
            session=None, platform="youtube", seed_url=seed_url
        )
    finally:
        wo134.PROBE_SELECT_HOOK = None
    assert final_seed == seed_url
    assert out_result is result


# --------------------------------------------------------------------------
# hub_sweep_wo126._default_probe_hook() -- the single-candidate degenerate
# case (see that function's own docstring: this module has no multi-row
# depth search yet, so selection there degenerates to "accept if
# plausible").
# --------------------------------------------------------------------------


def test_hub_sweep_probe_hook_is_none_by_default():
    """main() wires _default_probe_hook() in; importing this module (as
    every test/driver does) must not itself turn probing on -- backward
    compatible with every caller that never calls main()."""
    assert hs.PROBE_HOOK is None
