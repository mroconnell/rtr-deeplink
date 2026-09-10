"""Tests for WO-169's three shared-pipeline fixes (2026-09-10):

1. A tier-3 (video, no captions) candidate is now probed INSIDE
   scripts/wo134_confirmed_hits_ingest.py's resolve_seed() candidate
   loops (via the module-level PROBE_HOOK, default None so every
   existing caller is unaffected) -- a probe reject moves to the next
   candidate instead of ending the government's whole attempt. See
   resolve_youtube_channel()'s own tests below for the "next candidate"
   behavior and ProbeRejected for the "only once exhausted" outcome.
2. scripts/hub_sweep_wo126.Skip/RowSkip (wo134's own) now carry
   meeting_url/video_url so a skipped Result/RowResult keeps real URL
   evidence instead of dropping it (WO-151's own finding) -- see
   hs._apply_skip()'s tests below.
3. scripts/wo134_confirmed_hits_ingest.py's granicus_locate_listing()/
   granicus_rss_candidate_rows() try the cheap (~100 KB)
   ViewPublisherRSS.php?mode=video feed before the (up to 8 MB)
   ViewPublisher.php archive table -- see the fixture-backed tests
   below, which reuse the REAL Kansas City, MO RSS feed already saved at
   tests/fixtures/granicus_channel/kansascity_viewpublisher_rss.xml
   (fetched live 2026-08-29 for tests/test_granicus_channel.py -- see
   that file's own docstring for provenance). The "(No Video)"-filter
   test below adds one synthetic <item> to that real feed (clearly
   marked synthetic, reusing the real item shape) since no real closed-
   session placeholder has been captured in a fixture yet.
"""

import aiohttp

import scripts.hub_sweep_wo126 as hs
import scripts.wo134_confirmed_hits_ingest as wo134
from app.platforms import register_all_finders
from app.platforms.models import ResolvedMeeting
from app.platforms.queue_probe import ProbeResult
from tests.aiohttp_mock import FakeResponse, mock_session
from tests.conftest import load_fixture

register_all_finders()

KC_RSS_URL = "https://kansascity.granicus.com/ViewPublisherRSS.php?view_id=2&mode=video"


def _kc_rss_xml() -> str:
    return load_fixture("granicus_channel", "kansascity_viewpublisher_rss.xml")


# --------------------------------------------------------------------------
# Fix 3: Granicus RSS-first listing
# --------------------------------------------------------------------------


def test_granicus_rss_candidate_rows_parses_real_feed_newest_first():
    """The real fixture's own <item> order is Aug 13, Aug 11, Aug 11, Aug
    18 -- NOT date order (WO-157's own pilot finding: feed order can lag
    the true newest clip, docs/BREADTH_SWEEP_BRIEF.md). This must come
    back sorted newest-first regardless."""
    rows = wo134.granicus_rss_candidate_rows(
        _kc_rss_xml(), "https://kansascity.granicus.com/ViewPublisher.php?view_id=2"
    )
    assert [r["date"] for r in rows] == [
        "2026-08-18",
        "2026-08-13",
        "2026-08-11",
        "2026-08-11",
    ]
    newest = rows[0]
    assert newest["title"] == "Finance Governance & Public Safety Committee"
    assert newest["url"] == (
        "https://kansascity.granicus.com/MediaPlayer.php?view_id=2&clip_id=14518"
    )


def test_granicus_rss_candidate_rows_filters_no_video_placeholder_titles():
    """ "(No Video)" titles are closed-session placeholders (confirmed
    live, WO-157 pilot; docs/BREADTH_SWEEP_BRIEF.md) and must never come
    back as a candidate. SYNTHETIC: no real closed-session item has been
    captured in a fixture yet, so this appends one hand-built <item> to
    the real Kansas City feed, reusing that feed's own real, confirmed
    <item> shape (title suffix, gran:pubDateParts, MediaPlayer.php clip
    link) -- only the specific title/date/clip_id are made up."""
    synthetic_item = (
        "<item>"
        '<guid isPermaLink="false">00000000-0000-0000-0000-000000000000</guid>'
        "<title>Closed Session (No Video) - Aug 20, 2026</title>"
        "<pubDate>Thu, 20 Aug 2026 07:00:00 -0800</pubDate>"
        "<gran:pubDateParts yr='2026' mo='08' day='20' hr='07' min='00' sec='0' tz='7' />"
        "<link>https://kansascity.granicus.com/MediaPlayer.php?view_id=2&amp;clip_id=99999</link>"
        "</item>"
    )
    xml = _kc_rss_xml().replace("</channel>", synthetic_item + "</channel>")
    rows = wo134.granicus_rss_candidate_rows(
        xml, "https://kansascity.granicus.com/ViewPublisher.php?view_id=2"
    )
    # The synthetic Aug 20 item is newer than every real item -- if the
    # filter didn't run, it would sort to rows[0]. It must not appear at
    # all.
    assert all("99999" not in r["url"] for r in rows)
    assert all("no video" not in (r["title"] or "").lower() for r in rows)
    assert len(rows) == 4  # only the 4 real items


async def test_granicus_fetch_rss_candidates_returns_rows_from_a_real_feed():
    with mock_session({KC_RSS_URL: FakeResponse(status=200, text=_kc_rss_xml())}):
        async with aiohttp.ClientSession() as session:
            rows = await wo134.granicus_fetch_rss_candidates(
                session, "kansascity.granicus.com", "2"
            )
    assert len(rows) == 4
    assert rows[0]["date"] == "2026-08-18"


async def test_granicus_fetch_rss_candidates_empty_on_404_style_response():
    # Real Granicus behavior for an invalid view_id: 404, "Page not
    # found." (16 bytes) -- fetch_html() already turns any >=400 status
    # into (None, None), which this must treat as "nothing here", not an
    # error.
    with mock_session(
        {
            "https://kansascity.granicus.com/ViewPublisherRSS.php?view_id=9&mode=video": FakeResponse(
                status=404, text="Page not found."
            )
        }
    ):
        async with aiohttp.ClientSession() as session:
            rows = await wo134.granicus_fetch_rss_candidates(
                session, "kansascity.granicus.com", "9"
            )
    assert rows == []


async def test_granicus_locate_listing_prefers_rss_and_never_fetches_the_big_table():
    """No route is registered for
    https://kansascity.granicus.com/ViewPublisher.php?view_id=1 (the up
    to 8 MB archive table this used to fetch on every call) -- if
    granicus_locate_listing() ever tried it, mock_session's own
    "Unmocked request" AssertionError would fail this test. That silence
    is the actual proof RSS is tried first and, once it succeeds, the
    table walk is skipped entirely."""
    rss_view_1 = (
        "https://kansascity.granicus.com/ViewPublisherRSS.php?view_id=1&mode=video"
    )
    with mock_session({rss_view_1: FakeResponse(status=200, text=_kc_rss_xml())}):
        async with aiohttp.ClientSession() as session:
            seed, reason = await wo134.granicus_locate_listing(
                session, "https://kansascity.granicus.com/some/landing/page"
            )
    assert seed == "https://kansascity.granicus.com/ViewPublisher.php?view_id=1"
    assert reason == ""


async def test_granicus_locate_listing_falls_back_to_the_table_walk_when_rss_is_empty():
    """WO-169 must not regress the pre-existing behavior: when a view_id's
    RSS feed is empty/unreachable, the ViewPublisher.php table walk still
    runs exactly as it did before this WO."""
    rss_view_1 = (
        "https://example.granicus.com/ViewPublisherRSS.php?view_id=1&mode=video"
    )
    table_view_1 = "https://example.granicus.com/ViewPublisher.php?view_id=1"
    with mock_session(
        {
            rss_view_1: FakeResponse(status=404, text="Page not found."),
            table_view_1: FakeResponse(
                status=200,
                text='<html><a href="AgendaViewer.php?view_id=1&clip_id=1">'
                "City Council on 2026-08-01 7:00 PM</a></html>",
            ),
        }
    ):
        async with aiohttp.ClientSession() as session:
            seed, reason = await wo134.granicus_locate_listing(
                session, "https://example.granicus.com/some/landing/page"
            )
    assert seed == table_view_1
    assert reason == ""


# --------------------------------------------------------------------------
# Fix 1: a probe reject moves to the next candidate
# --------------------------------------------------------------------------

# SYNTHETIC: a hand-built YouTube channel listing and finder, standing in
# for a real yt-dlp channel scan and a real YouTubeAssetFinder.resolve()
# call -- this test is about resolve_youtube_channel()'s own candidate-
# loop/probe-hook wiring, not about YouTube parsing (already covered by
# tests/test_youtube_channel.py). Payload shape (a dict with "id"/
# "title"/"duration", a ResolvedMeeting with a real video_url and no
# segments) reuses the real shapes those modules already use.
_SYNTHETIC_CANDIDATES = [
    {"id": "aaaaaaaaaaa", "title": "City Council Meeting", "duration": 3600},
    {"id": "bbbbbbbbbbb", "title": "City Council Meeting", "duration": 3600},
]


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


def _rejecting_then_accepting_probe_hook(reject_urls: set):
    """A PROBE_HOOK that rejects any url in `reject_urls` and accepts
    everything else -- built from a real ProbeResult verdict (as
    scripts/wo169_probe_rejected_rerun.py's real hook does with
    app.platforms.queue_probe.probe_queue_entry()'s actual return value),
    not just a bare boolean, so this exercises the real accept/reject
    verdict shape."""

    async def hook(result, candidate_url: str) -> bool:
        verdict = "reject-dead" if candidate_url in reject_urls else "accept"
        probe = ProbeResult(
            url=candidate_url,
            platform="youtube",
            probe_method="test-stub",
            duration_seconds=1200.0 if verdict == "accept" else None,
            date=None,
            size_bytes=None,
            verdict=verdict,
            reason=None if verdict == "accept" else "dead link (synthetic)",
            probe_seconds=0.01,
        )
        return probe.verdict not in ("reject-dead", "reject-short")

    return hook


async def test_probe_reject_advances_to_the_next_candidate(monkeypatch):
    """The real bug this WO fixes: a probe reject used to end the
    government's whole attempt at the FIRST candidate with video. With
    PROBE_HOOK set, the first candidate's video is rejected and the
    second (real, accepted) one must still be returned -- not a raised
    exception, not "nothing found"."""
    monkeypatch.setattr(
        wo134, "_list_youtube_channel_entries", lambda url: _SYNTHETIC_CANDIDATES
    )
    first_url = "https://www.youtube.com/watch?v=aaaaaaaaaaa"
    second_url = "https://www.youtube.com/watch?v=bbbbbbbbbbb"
    monkeypatch.setattr(
        wo134,
        "get_finder",
        lambda platform: _FakeYouTubeFinder({first_url, second_url}),
    )
    monkeypatch.setattr(
        wo134, "PROBE_HOOK", _rejecting_then_accepting_probe_hook({first_url})
    )
    try:
        result, video_url, high_risk = await wo134.resolve_youtube_channel(
            session=None, channel_url="https://www.youtube.com/channel/UCxxxx"
        )
    finally:
        wo134.PROBE_HOOK = None
    assert video_url == second_url
    assert result.video_url == second_url


async def test_probe_reject_reports_rejected_by_probe_only_once_every_candidate_is_tried(
    monkeypatch,
):
    """Ryan's rule: report rejected_by_probe only after every candidate
    is exhausted -- both real-video candidates fail the probe here, so
    this must raise ProbeRejected (not a plain RowSkip, and not silently
    accept a rejected candidate), carrying the URL evidence forward."""
    monkeypatch.setattr(
        wo134, "_list_youtube_channel_entries", lambda url: _SYNTHETIC_CANDIDATES
    )
    first_url = "https://www.youtube.com/watch?v=aaaaaaaaaaa"
    second_url = "https://www.youtube.com/watch?v=bbbbbbbbbbb"
    monkeypatch.setattr(
        wo134,
        "get_finder",
        lambda platform: _FakeYouTubeFinder({first_url, second_url}),
    )
    monkeypatch.setattr(
        wo134,
        "PROBE_HOOK",
        _rejecting_then_accepting_probe_hook({first_url, second_url}),
    )
    try:
        try:
            await wo134.resolve_youtube_channel(
                session=None, channel_url="https://www.youtube.com/channel/UCxxxx"
            )
            raised = None
        except wo134.ProbeRejected as e:
            raised = e
    finally:
        wo134.PROBE_HOOK = None
    assert raised is not None
    assert raised.meeting_url == first_url  # the FIRST rejected candidate, kept
    assert raised.video_url == first_url


# --------------------------------------------------------------------------
# Fix 2: a skipped Result/RowResult keeps its URLs
# --------------------------------------------------------------------------


def test_apply_skip_keeps_meeting_and_video_url():
    res = hs.Result(hub_kind="test")
    e = hs.Skip(
        "no-video-found",
        "detail text",
        meeting_url="https://city.example.gov/agenda/1",
        video_url="",
    )
    out = hs._apply_skip(res, e)
    assert out.outcome == "skipped"
    assert out.reject_reason == "no-video-found"
    assert out.meeting_url == "https://city.example.gov/agenda/1"


def test_apply_skip_tags_video_without_meeting_per_wo164():
    # A real video existed (video_url set) but no meeting/listing
    # evidence did (meeting_url blank) -- WO-164's rule 1
    # (~/Documents/rtr-business/research/wo164_retag_rules.md).
    res = hs.Result(hub_kind="test")
    e = hs.Skip(
        "no-video-found",
        "detail text",
        meeting_url="",
        video_url="https://www.youtube.com/watch?v=abc12345678",
    )
    out = hs._apply_skip(res, e)
    assert out.reject_reason == "video-without-meeting"
    assert out.video_url == "https://www.youtube.com/watch?v=abc12345678"


def test_apply_skip_gives_proberejected_its_own_outcome():
    res = hs.Result(hub_kind="test")
    e = hs.ProbeRejected(
        "no-video-found",
        "probe verdict=reject-dead",
        meeting_url="https://city.example.gov/agenda/1",
        video_url="https://www.youtube.com/watch?v=abc12345678",
    )
    out = hs._apply_skip(res, e)
    assert out.outcome == "rejected_by_probe"
    assert out.meeting_url == "https://city.example.gov/agenda/1"
    assert out.video_url == "https://www.youtube.com/watch?v=abc12345678"


async def test_process_row_final_skip_keeps_meeting_and_video_url(monkeypatch):
    """wo134_confirmed_hits_ingest.process_row()'s own catch-all skip (no
    platform hit produced content) used to drop every URL it had seen --
    the exact WO-151 finding. Real seed/video URLs surfaced along the way
    must survive onto the final RowResult even when nothing was ever
    ingestable."""
    row = {
        "gov_id": "test:0001",
        "unit_name": "Test City, ST",
        "homepage": "",
        "hop2_urls": "",
        "hit_source_urls": "granicus=https://example.granicus.com/somepage",
    }

    async def fake_locate_platform_url(session, platform, hit_url, hop2_urls, homepage):
        return "https://example.granicus.com/ViewPublisher.php?view_id=1", ""

    async def fake_resolve_seed(session, platform, seed_url):
        raise wo134.RowSkip(
            "granicus: checked 3 candidate(s) from ViewPublisher.php, none had video",
            meeting_url="https://example.granicus.com/ViewPublisher.php?view_id=1",
            video_url="",
        )

    monkeypatch.setattr(wo134, "locate_platform_url", fake_locate_platform_url)
    monkeypatch.setattr(wo134, "resolve_seed", fake_resolve_seed)

    result = await wo134.process_row(
        session=None, row=row, covered_gov_ids=set(), source_tag="test"
    )
    assert result.outcome == "skipped"
    assert result.seed_url == "https://example.granicus.com/ViewPublisher.php?view_id=1"
    assert result.video_url == ""
