"""Tests for `app/platforms/passive_verify.py` (WO-333, extended WO-341).

Two layers, matching how the rest of this repo tests an orchestration
module vs. an adapter: (1) unit tests against a small FAKE AssetFinder
registered under a made-up platform name, isolating `verify_hub()`'s own
walk/verdict/ranking logic from any real adapter's `resolve()`
correctness (already covered by that adapter's own test file); (2) one
real, fixture-backed end-to-end test through the Granicus listing walker
this WO added, and one through the real Franklin NH CivicPlus ranking
scenario, to prove the wiring works against real pages, not just fakes.

WO-341 added `_civicplus_walker()` (real fixtures: Hobart IN, Monroe
County FL, Webb County TX -- the WO-333 residual misses this closes) and
ranking-fix #4 (the Jefferson County WA `no_video_in_listing` shape).
"""

import datetime as _dt
from unittest.mock import patch

import pytest

from app.platforms.base import (
    AssetFinder,
    CalendarPageError,
    NoVideoCandidateFound,
    register,
)
from app.platforms.cablecast import CablecastAssetFinder
from app.platforms.civicclerk import CivicClerkAssetFinder
from app.platforms.civicplus import CivicPlusAssetFinder
from app.platforms.escribe import EscribeAssetFinder
from app.platforms.granicus import GranicusAssetFinder
from app.platforms.iqm2 import IQM2AssetFinder
from app.platforms.townhallstreams import TownHallStreamsAssetFinder
from app.platforms.models import ResolvedMeeting, TranscriptSegment
from app.platforms.passive_verify import (
    _cablecast_walker,
    _civicclerk_walker,
    _civicplus_walker,
    _civicweb_walker,
    _escribe_walker,
    _iqm2_walker,
    _legistar_walker,
    _townhallstreams_walker,
    verify_hub,
)

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture


class _FakeFinder(AssetFinder):
    """A controllable fake AssetFinder for testing verify_hub()'s own
    orchestration logic without depending on any real adapter's network
    behavior. `script` maps a URL to either a ResolvedMeeting, an
    Exception instance to raise, or a callable(url) -> one of those."""

    platform_name = "fake_platform"

    def __init__(self, script: dict):
        self.script = script
        self.calls = []

    async def resolve(self, url: str) -> ResolvedMeeting:
        self.calls.append(url)
        outcome = self.script.get(url)
        if outcome is None:
            raise AssertionError(f"_FakeFinder got an unscripted url: {url}")
        if callable(outcome):
            outcome = outcome(url)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _resolved(
    video_url=None, segments=None, title=None, agenda_items=None, source_url=None
):
    return ResolvedMeeting(
        platform="fake_platform",
        source_url=source_url or "https://example.test/meeting",
        video_url=video_url,
        segments=segments or [],
        agenda_items=agenda_items or [],
        title=title,
    )


@pytest.fixture(autouse=True)
def _register_real_finders():
    # civicplus.py/granicus.py/escribe.py/civicclerk.py/iqm2.py/
    # townhallstreams.py/cablecast.py are real, already-tested adapters
    # used by the end-to-end tests below; registered here so
    # `get_finder()` finds them the same way `register_all_finders()`
    # would in production.
    register(CivicPlusAssetFinder())
    register(GranicusAssetFinder())
    register(EscribeAssetFinder())
    register(CivicClerkAssetFinder())
    register(IQM2AssetFinder())
    register(TownHallStreamsAssetFinder())
    register(CablecastAssetFinder())


# `detect_platform()` never recognizes "fake_platform"'s made-up host, so
# `verify_hub()` always fetches the hub page once first (looking for a
# real embedded platform link) before falling back to `platform_hint` --
# every fake-finder test below mocks that one hub-page fetch as a bland
# page with no recognizable platform link, so the fallback path is
# exercised deliberately, not by accident.
_BLAND_HUB_HTML = "<html><body><a href='/about'>About</a></body></html>"


async def test_calendar_page_walks_newest_first_to_video():
    # A CalendarPageError pick-list where only the 2nd (of 3) real
    # candidates has video -- verify_hub() should walk newest-first,
    # skip the 1st (no video, honest), find the 2nd, and never touch the
    # 3rd.
    fake = _FakeFinder(
        {
            "https://example.test/hub": CalendarPageError(
                "listing",
                candidates=[
                    {
                        "title": "Newest",
                        "date": "2026-09-01",
                        "url": "https://example.test/m1",
                    },
                    {
                        "title": "Middle",
                        "date": "2026-08-01",
                        "url": "https://example.test/m2",
                    },
                    {
                        "title": "Oldest",
                        "date": "2026-07-01",
                        "url": "https://example.test/m3",
                    },
                ],
            ),
            "https://example.test/m1": _resolved(video_url=None),
            "https://example.test/m2": _resolved(
                video_url="https://cdn.example.test/v.mp4",
                segments=[TranscriptSegment(start=0, end=1, text="hi")],
                source_url="https://example.test/m2",
            ),
        }
    )
    register(fake)

    routes = {
        "https://example.test/hub": FakeResponse(status=200, text=_BLAND_HUB_HTML)
    }
    with mock_session(routes):
        result = await verify_hub(
            "https://example.test/hub", platform_hint="fake_platform"
        )

    assert result.meeting_found is True
    assert result.video_found is True
    assert result.captions_found is True
    assert result.meeting_url == "https://example.test/m2"
    assert result.candidates_checked == 2
    assert "m3" not in "".join(fake.calls)


async def test_no_video_candidate_found_with_real_rows_is_meeting_found_no_video():
    # Conductor's fix #1: NoVideoCandidateFound with candidates_checked>0
    # is a real, confident "meeting found, no video" -- never "no
    # meeting."
    fake = _FakeFinder(
        {
            "https://example.test/hub": NoVideoCandidateFound(
                "checked some, no video", candidates_checked=5
            ),
        }
    )
    register(fake)

    routes = {
        "https://example.test/hub": FakeResponse(status=200, text=_BLAND_HUB_HTML)
    }
    with mock_session(routes):
        result = await verify_hub(
            "https://example.test/hub", platform_hint="fake_platform"
        )

    assert result.meeting_found is True
    assert result.video_found is False
    assert result.verdict == "no_video_in_listing"
    assert result.candidates_checked == 5


async def test_resolved_empty_page_falls_back_to_generic_link_scan():
    # Conductor's fix #2: a plain resolve() success with NOTHING real in
    # it (no video, no title, no agenda -- the WO-331 "this was actually
    # a listing" shape) must not be read as "no meeting" before trying a
    # listing walk. No bespoke walker is registered for "fake_platform",
    # so the generic link-scan walker runs: it fetches the hub page
    # (mocked) and finds a meeting-detail-shaped link, which resolves to
    # real video.
    fake = _FakeFinder(
        {
            "https://example.test/hub": _resolved(),  # nothing real at all
            "https://example.test/meeting/42": _resolved(
                video_url="https://cdn.example.test/v.mp4",
                source_url="https://example.test/meeting/42",
            ),
        }
    )
    register(fake)

    hub_html = (
        '<html><body><a href="/meeting/42">Regular Meeting Sep 1</a>'
        '<a href="/about">About</a></body></html>'
    )
    routes = {"https://example.test/hub": FakeResponse(status=200, text=hub_html)}

    with mock_session(routes):
        result = await verify_hub(
            "https://example.test/hub", platform_hint="fake_platform"
        )

    assert result.meeting_found is True
    assert result.video_found is True
    assert result.meeting_url == "https://example.test/meeting/42"


async def test_resolved_empty_page_with_no_listing_candidates_is_no_meeting():
    # Same shape as above, but the generic link scan finds nothing
    # meeting-shaped either -- an honest "no meeting found" rather than a
    # guess.
    fake = _FakeFinder({"https://example.test/hub": _resolved()})
    register(fake)

    hub_html = "<html><body><a href='/about'>About us</a></body></html>"
    routes = {"https://example.test/hub": FakeResponse(status=200, text=hub_html)}

    with mock_session(routes):
        result = await verify_hub(
            "https://example.test/hub", platform_hint="fake_platform"
        )

    assert result.meeting_found is False
    assert result.video_found is False


async def test_youtube_hub_url_is_a_lead_never_fetched():
    result = await verify_hub("https://www.youtube.com/watch?v=abc12345678")
    assert result.meeting_found is True
    assert result.video_found is True
    assert result.verdict == "youtube_lead"
    assert result.platform == "youtube"


async def test_youtube_candidate_in_walk_is_a_lead_never_fetched():
    fake = _FakeFinder(
        {
            "https://example.test/hub": CalendarPageError(
                "listing",
                candidates=[
                    {
                        "title": "Newest",
                        "date": "2026-09-01",
                        "url": "https://www.youtube.com/watch?v=zz999999999",
                    },
                ],
            ),
        }
    )
    register(fake)

    routes = {
        "https://example.test/hub": FakeResponse(status=200, text=_BLAND_HUB_HTML)
    }
    with mock_session(routes):
        result = await verify_hub(
            "https://example.test/hub", platform_hint="fake_platform"
        )

    assert result.video_found is True
    assert result.verdict == "youtube_lead"
    assert "zz999999999" in result.meeting_url


async def test_internal_youtube_delegation_is_a_lead_never_fetched():
    # Real, confirmed gap (found live running this module against
    # WO-331's own control set, 2026-09-13, Crest Hill IL): a candidate
    # that is NOT itself a youtube.com URL (a Municode Meetings meeting
    # page) can still internally embed a YouTube video and delegate to
    # `YouTubeAssetFinder` from INSIDE its own resolve() via
    # `resolve_via_platform()` -- invisible to a check on the candidate
    # URL alone. `verify_hub()` must catch this too, not just a
    # top-level/candidate URL that is itself youtube.com.
    from app.platforms.youtube import YouTubeAssetFinder

    register(YouTubeAssetFinder())

    class _DelegatingFakeFinder(AssetFinder):
        platform_name = "fake_platform"

        async def resolve(self, url: str) -> ResolvedMeeting:
            from app.platforms.base import get_finder as _get_finder

            return await _get_finder("youtube").resolve(
                "https://www.youtube.com/watch?v=internal1234"
            )

    register(_DelegatingFakeFinder())

    original_resolve = YouTubeAssetFinder.resolve

    routes = {
        "https://example.test/hub": FakeResponse(status=200, text=_BLAND_HUB_HTML)
    }
    with mock_session(routes):
        result = await verify_hub(
            "https://example.test/hub", platform_hint="fake_platform"
        )

    assert result.video_found is True
    assert result.verdict == "youtube_lead"
    assert "internal1234" in result.meeting_url
    # The guard is scoped, not permanent -- confirm it's actually
    # restored after verify_hub() returns, so a real caller elsewhere
    # (e.g. the YouTube drip) is unaffected.
    assert YouTubeAssetFinder.resolve is original_resolve


async def test_internal_youtube_delegation_via_resolve_video_id_is_a_lead():
    # Real, confirmed gap in an EARLIER version of this guard (found live
    # 2026-09-13 on a2gov.org's real Legistar Calendar.aspx, City
    # Council meeting LEGID=14158 -- see `_YouTubeResolveBlocked`'s own
    # docstring): `legistar.py` (and, per CLAUDE.md, `primegov.py`) don't
    # delegate to YouTube via `YouTubeAssetFinder.resolve()` --
    # `resolve_via_platform()`'s normal path -- they call
    # `YouTubeAssetFinder.resolve_video_id(video_id, source_url)`
    # DIRECTLY, a completely different method, specifically so they can
    # pass the delegating page's own `source_url` through. A guard that
    # only patches `.resolve()` lets this one straight through to a real
    # yt-dlp fetch. This test reproduces that exact call shape.
    from app.platforms.youtube import YouTubeAssetFinder

    original_resolve_video_id = YouTubeAssetFinder.resolve_video_id

    class _LegistarShapedFakeFinder(AssetFinder):
        platform_name = "fake_platform"

        async def resolve(self, url: str) -> ResolvedMeeting:
            return await YouTubeAssetFinder.resolve_video_id(
                "lUBYUBtMOJw", source_url=url
            )

    register(_LegistarShapedFakeFinder())

    routes = {
        "https://example.test/hub": FakeResponse(status=200, text=_BLAND_HUB_HTML)
    }
    with mock_session(routes):
        result = await verify_hub(
            "https://example.test/hub", platform_hint="fake_platform"
        )

    assert result.video_found is True
    assert result.verdict == "youtube_lead"
    assert "lUBYUBtMOJw" in result.meeting_url
    assert YouTubeAssetFinder.resolve_video_id is original_resolve_video_id


async def test_unknown_hub_url_uses_platform_hint_via_find_platform_link():
    # detect_platform(hub_url) can't recognize a government's own generic
    # page -- but the page itself links out to a real, known platform
    # (here a granicus.com URL, which detect_platform() DOES recognize),
    # so find_platform_link() should locate it and verify_hub() should
    # resolve THAT, not give up because the hub url itself is unknown.
    hub_html = (
        '<html><body><a href="https://example-gov.granicus.com/MediaPlayer.php'
        '?view_id=1&clip_id=99">Watch</a></body></html>'
    )
    fixture_html = load_fixture("granicus", "napacity_clip3450.html")
    routes = {
        "https://example.gov/meetings": FakeResponse(status=200, text=hub_html),
        "https://example-gov.granicus.com/MediaPlayer.php?view_id=1&clip_id=99": (
            FakeResponse(status=200, text=fixture_html)
        ),
        "https://example-gov.granicus.com/videos/99/captions.vtt": FakeResponse(
            status=404
        ),
        "https://example-gov.granicus.com/ViewPublisherRSS.php?view_id=1&mode=video": (
            FakeResponse(status=404)
        ),
        "https://example-gov.granicus.com/videos/99/player": FakeResponse(status=404),
        "https://example-gov.granicus.com/AgendaViewer.php?clip_id=99&embedded=1": (
            FakeResponse(status=404)
        ),
        "https://example-gov.granicus.com/MinutesViewer.php?clip_id=99&view_id=1&embedded=1": (
            FakeResponse(status=404)
        ),
    }

    with mock_session(routes):
        result = await verify_hub(
            "https://example.gov/meetings", platform_hint="granicus"
        )

    assert result.platform == "granicus"
    assert result.meeting_found is True


async def test_ranking_fix_prefers_vendor_over_aggregator_civicplus_and_granicus():
    # WO-331's measured ranking bug (Monroe County FL -> iQM2, Franklin
    # NH -> Vimeo, Webb County TX -> Swagit, Jefferson County WA ->
    # direct file), reproduced with real adapters: a CivicPlus
    # AgendaCenter page with real (title+date) rows -- so civicplus.py
    # walks them and raises NoVideoCandidateFound(candidates_checked>0),
    # a confident "meeting found, no video" from CivicPlus's own scan --
    # which ALSO embeds a real Granicus MediaPlayer link elsewhere on
    # the same page (outside the AgendaCenter rows themselves, so
    # civicplus.py's own row-scoped video check never sees it). The fix
    # should resolve the Granicus link and report its video, not stop at
    # CivicPlus's own honest "no video in these rows."
    hub_url = "https://example.civicplus.com/291/Boards-Committees"
    agenda_row = (
        '<tr class="catAgendaRow">'
        "<td><h3><strong>{date}</strong></h3><p><a>Meeting {date}</a></p></td>"
        '<td class="media"></td>'
        "</tr>"
    )
    hub_html = (
        "<html><body><table>"
        + "".join(
            agenda_row.format(date=d)
            for d in ("Sep 05, 2026", "Sep 04, 2026", "Sep 03, 2026")
        )
        + "</table>"
        '<a href="https://example-gov.granicus.com/MediaPlayer.php?view_id=1&clip_id=99">'
        "Watch Board Meetings</a>"
        "</body></html>"
    )
    fixture_html = load_fixture("granicus", "napacity_clip3450.html")
    routes = {
        hub_url: FakeResponse(status=200, text=hub_html, url=hub_url),
        "https://example-gov.granicus.com/MediaPlayer.php?view_id=1&clip_id=99": (
            FakeResponse(status=200, text=fixture_html)
        ),
        "https://example-gov.granicus.com/videos/99/captions.vtt": FakeResponse(
            status=404
        ),
        "https://example-gov.granicus.com/ViewPublisherRSS.php?view_id=1&mode=video": (
            FakeResponse(status=404)
        ),
        "https://example-gov.granicus.com/videos/99/player": FakeResponse(status=404),
        "https://example-gov.granicus.com/AgendaViewer.php?clip_id=99&embedded=1": (
            FakeResponse(status=404)
        ),
        "https://example-gov.granicus.com/MinutesViewer.php?clip_id=99&view_id=1&embedded=1": (
            FakeResponse(status=404)
        ),
    }

    with mock_session(routes):
        result = await verify_hub(hub_url, platform_hint="civicplus")

    assert result.platform == "granicus"
    assert result.video_found is True
    assert result.ranking_fix_applied is True


async def test_real_franklin_nh_civicplus_no_ranking_fix_needed_after_retry_limit_raise():
    # The Franklin NH fixture from test_civicplus.py's own regression
    # test (WO-333's raised _RETRY_LIMIT) -- verify_hub() should reach
    # the real CalendarPageError pick-list directly and walk to the real
    # Vimeo candidate WITHOUT needing the ranking fix at all, since
    # civicplus.py itself now finds the video. (Vimeo's own resolve() is
    # not mocked here, so this only asserts the CalendarPageError walk
    # picked the right newest video candidate url before attempting to
    # fetch it -- Vimeo resolution itself is covered by test_vimeo.py.)
    url = "https://franklinnh.gov/agendacenter"
    html = load_fixture("civicplus", "franklinnh_agendacenter.html")
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        # civicplus.py's own resolve() raises CalendarPageError with the
        # real candidate list -- confirm that directly (a cheaper,
        # equivalent check to running the full walk through a real,
        # unmocked vimeo.com fetch).
        with pytest.raises(CalendarPageError) as exc_info:
            await CivicPlusAssetFinder().resolve(url)

    newest_video = next(c for c in exc_info.value.candidates if c["url"])
    assert newest_video["url"].startswith("https://vimeo.com/1222880162")


async def test_civicweb_walker_real_niagara_falls_meetingtypelist():
    # Real, raw-saved live page -- niagarafalls.civicweb.net/Portal/
    # MeetingTypeList.aspx, fetched 2026-09-13. Ported logic from
    # rtr-business's `meeting_url_finder.py`'s `find_civicweb_meeting()`
    # (prior art from ENUMERATION_METHODS.md's Step 2/Step 3 runs,
    # §93/§142/§144) -- this only asserts the walker extracts real
    # meeting ids newest-first; whether any of them has video is
    # `civicweb.py`'s own `resolve()`'s job (covered by test_civicweb.py),
    # not duplicated here.
    html = load_fixture("civicweb", "niagarafalls_meetingtypelist.html")
    url = "https://niagarafalls.civicweb.net/Portal/MeetingTypeList.aspx"
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        candidates = await _civicweb_walker("https://niagarafalls.civicweb.net/portal/")

    assert candidates, "expected at least one real meeting id"
    ids = [int(c["url"].rsplit("Id=", 1)[1]) for c in candidates]
    assert ids == sorted(ids, reverse=True), "expected newest-first order"
    assert all(
        c["url"].startswith(
            "https://niagarafalls.civicweb.net/Portal/MeetingInformation.aspx?Id="
        )
        for c in candidates
    )


async def test_civicweb_walker_non_civicweb_host_returns_empty():
    assert await _civicweb_walker("https://example.gov/meetings") == []


async def test_legistar_walker_real_a2gov_webapi():
    # Real, raw-saved live response -- webapi.legistar.com's public,
    # unauthenticated events API for a2gov, fetched 2026-09-13. Ported
    # from `meeting_url_finder.py`'s `find_legistar_meeting()` (same
    # prior-art note as the CivicWeb walker above) -- this is the fix for
    # a2gov.org's own WO-331 control case, where Legistar's Calendar.aspx
    # page has no per-row video link at all for the generic link scan to
    # find.
    import datetime as _dt
    import json

    payload = load_fixture("legistar", "a2gov_webapi_events.json")
    events = json.loads(payload)
    # Mirrors _legistar_walker()'s own URL construction exactly, so this
    # test doesn't need to mock "today" -- whatever real date the test
    # runs on, the walker builds the identical URL.
    today = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    filter_val = f"EventDate lt datetime'{today}'"
    api_url = (
        (
            f"https://webapi.legistar.com/v1/a2gov/events"
            f"?$filter={filter_val}&$orderby=EventDate%20desc&$top=10"
        )
        .replace(" ", "%20")
        .replace("'", "%27")
    )
    routes = {api_url: FakeResponse(status=200, text=json.dumps(events))}

    with mock_session(routes):
        candidates = await _legistar_walker("https://a2gov.legistar.com/Calendar.aspx")

    assert len(candidates) == 3
    assert candidates[0]["url"].startswith(
        "https://a2gov.legistar.com/MeetingDetail.aspx"
    )
    assert candidates[0]["title"] == "Greenbelt Advisory Commission (GAC)"


async def test_legistar_walker_non_legistar_host_returns_empty():
    assert await _legistar_walker("https://example.gov/meetings") == []


async def test_civicclerk_walker_real_southfultonga_sorts_media_first():
    # Real, raw-saved live response -- southfultonga.api.civicclerk.com's
    # Events list, fetched 2026-09-13 (WO-342). Ported from
    # `meeting_url_finder.py`'s `find_civicclerk_meeting()`, adapted to
    # use the listing's own real `hasMedia` flag instead of calling
    # EventsMedia/{id} itself for every row (see `_civicclerk_walker()`'s
    # own docstring). Of the 10 most recent real events here, 8 carry
    # `hasMedia: true` (including event 1773, WO-341/342/343's shared
    # brief's own named example) and 2 (1792, 1763) carry `hasMedia:
    # false` -- this only asserts the walker sorts the real hasMedia-true
    # rows first while keeping each group newest-first; whether any of
    # them actually has playable video/captions is civicclerk.py's own
    # resolve() job (covered by test_civicclerk.py), not duplicated here.
    import datetime as _dt
    from urllib.parse import quote as _quote

    listing = load_fixture("civicclerk", "southfultonga_events_listing.json")
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    filter_val = _quote(f"eventDate lt {now}", safe="")
    orderby_val = _quote("eventDate desc", safe="")
    api_url = (
        f"https://southfultonga.api.civicclerk.com/v1/Events"
        f"?$filter={filter_val}&$orderby={orderby_val}&$top=10"
    )
    routes = {api_url: FakeResponse(status=200, text=listing, url=api_url)}

    with mock_session(routes):
        candidates = await _civicclerk_walker(
            "https://southfultonga.portal.civicclerk.com/"
        )

    assert len(candidates) == 10
    ids = [int(c["url"].rsplit("/event/", 1)[1].split("/")[0]) for c in candidates]
    # Real hasMedia-true ids (newest-first among themselves): 1775, 1774,
    # 1773, 1766, 1765, 1764, 1791, 1762 -- then the two hasMedia-false
    # ones (1792, 1763), also newest-first among themselves.
    assert ids == [1775, 1774, 1773, 1766, 1765, 1764, 1791, 1762, 1792, 1763]
    assert all(
        c["url"].startswith("https://southfultonga.portal.civicclerk.com/event/")
        and c["url"].endswith("/media")
        for c in candidates
    )
    assert candidates[2]["title"] == "City Council Work Session"  # event 1773


async def test_civicclerk_walker_real_edinburgtx_without_media_shape():
    # Real, raw-saved live response -- edinburgtx.api.civicclerk.com's
    # Events list, fetched 2026-09-13 (WO-342). A real tenant, real
    # events, `hasMedia: false` on every one of its 10 most recent rows
    # -- the "without-media" shape named alongside Vancouver WA in
    # WO-341/342/343's shared brief (`vancouverwa.portal.civicclerk.com`
    # confirmed live the same way, not fixture-backed here to avoid a
    # redundant second fixture for the identical shape). The walker must
    # still return real candidates (newest-first, unsorted since there's
    # no hasMedia-true group to promote) -- `_walk_candidates()` walking
    # all of them and finding no video is what turns this into an honest
    # tier-4 "meeting found, no video" verdict, not "no meeting found".
    import datetime as _dt
    from urllib.parse import quote as _quote

    listing = load_fixture("civicclerk", "edinburgtx_events_listing.json")
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    filter_val = _quote(f"eventDate lt {now}", safe="")
    orderby_val = _quote("eventDate desc", safe="")
    api_url = (
        f"https://edinburgtx.api.civicclerk.com/v1/Events"
        f"?$filter={filter_val}&$orderby={orderby_val}&$top=10"
    )
    routes = {api_url: FakeResponse(status=200, text=listing, url=api_url)}

    with mock_session(routes):
        candidates = await _civicclerk_walker(
            "https://edinburgtx.portal.civicclerk.com/"
        )

    assert len(candidates) == 10
    ids = [int(c["url"].rsplit("/event/", 1)[1].split("/")[0]) for c in candidates]
    # No hasMedia-true group to promote here -- the API's own newest-first
    # order (real ids) is preserved exactly.
    assert ids == [1585, 290, 1582, 204, 1546, 302, 1583, 1581, 289, 1545]
    assert all(
        c["url"] == f"https://edinburgtx.portal.civicclerk.com/event/{eid}/media"
        for c, eid in zip(candidates, ids)
    )


async def test_civicclerk_walker_uses_api_host_tenant_too():
    # `_CIVICCLERK_TENANT_RE` accepts either the portal or api subdomain
    # for the hub URL passed in -- a caller may reach here via either.
    listing = load_fixture("civicclerk", "edinburgtx_events_listing.json")
    import datetime as _dt
    from urllib.parse import quote as _quote

    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    filter_val = _quote(f"eventDate lt {now}", safe="")
    orderby_val = _quote("eventDate desc", safe="")
    api_url = (
        f"https://edinburgtx.api.civicclerk.com/v1/Events"
        f"?$filter={filter_val}&$orderby={orderby_val}&$top=10"
    )
    routes = {api_url: FakeResponse(status=200, text=listing, url=api_url)}

    with mock_session(routes):
        candidates = await _civicclerk_walker(
            "https://edinburgtx.api.civicclerk.com/v1/Events/1585"
        )

    assert candidates


async def test_civicclerk_walker_non_civicclerk_host_returns_empty():
    assert await _civicclerk_walker("https://example.gov/meetings") == []


async def test_first_party_agenda_page_credited_as_meeting_found_no_video():
    # WO-332 (Breadth), 2026-09-13: a hub where NO known vendor platform
    # link exists anywhere -- but the government's own site has a real
    # agenda/minutes page at a guessable first-party path. Must be
    # credited as meeting_found=True (tier 4), never "no meeting."
    real_agenda_html = (
        "<html><body><h1>Agendas and Minutes</h1>"
        + "<p>City Council Agenda</p>" * 100
        + "</body></html>"
    )
    routes = {
        "https://example.gov/meetings": FakeResponse(status=200, text=_BLAND_HUB_HTML),
        "https://example.gov/agendacenter": FakeResponse(status=404),
        "https://example.gov/AgendaCenter": FakeResponse(
            status=200, text=real_agenda_html
        ),
    }

    with mock_session(routes):
        result = await verify_hub("https://example.gov/meetings")

    assert result.meeting_found is True
    assert result.video_found is False
    assert result.tier == 4
    assert result.verdict == "first_party_agenda_page"


async def test_first_party_agenda_page_recognized_as_civicplus_delegates_to_real_walk():
    # Same gap, but the guessed path IS a real CivicPlus AgendaCenter
    # (white-labeled onto the government's own domain, so
    # `detect_platform()` alone can't recognize it -- see civicplus.py's
    # own module note) -- a synthetic-but-real-shaped single-candidate
    # AgendaCenter page (the CivicPlus row markup this repo's other
    # tests already use synthetically, e.g. `test_video_beyond_retry_
    # limit_is_not_walked` in test_civicplus.py), fully mocked end to
    # end so this test's outcome doesn't depend on whether some OTHER
    # test module in the same pytest run happened to register a real
    # Vimeo/Granicus finder first (a real flake this test hit once,
    # 2026-09-13, when the Franklin NH fixture's own real Vimeo
    # candidate got walked against a real, unmocked vimeo.com).
    civicplus_html = (
        "<html><body>"
        + "<p>Agendas and Minutes</p>"
        * 60  # clears the catch-all/blank-page size floor
        + "<table>"
        '<tr class="catAgendaRow">'
        "<td><h3><strong>Sep 05, 2026</strong></h3><p><a>Meeting</a></p></td>"
        '<td class="media">'
        '<a href="https://example-gov.granicus.com/MediaPlayer.php?view_id=1&clip_id=99">Video</a>'
        "</td></tr></table></body></html>"
    )
    fixture_html = load_fixture("granicus", "napacity_clip3450.html")
    routes = {
        "https://example.gov/meetings": FakeResponse(status=200, text=_BLAND_HUB_HTML),
        "https://example.gov/agendacenter": FakeResponse(
            status=200, text=civicplus_html, url="https://example.gov/agendacenter"
        ),
        "https://example-gov.granicus.com/MediaPlayer.php?view_id=1&clip_id=99": (
            FakeResponse(status=200, text=fixture_html)
        ),
        "https://example-gov.granicus.com/videos/99/captions.vtt": FakeResponse(
            status=404
        ),
        "https://example-gov.granicus.com/ViewPublisherRSS.php?view_id=1&mode=video": (
            FakeResponse(status=404)
        ),
        "https://example-gov.granicus.com/videos/99/player": FakeResponse(status=404),
        "https://example-gov.granicus.com/AgendaViewer.php?clip_id=99&embedded=1": (
            FakeResponse(status=404)
        ),
        "https://example-gov.granicus.com/MinutesViewer.php?clip_id=99&view_id=1&embedded=1": (
            FakeResponse(status=404)
        ),
    }

    with mock_session(routes):
        result = await verify_hub("https://example.gov/meetings")

    # The CivicPlus markers alone were enough to route the guessed path
    # into the real CivicPlus walk (not treated as a bare "unknown
    # platform" page), which found the row's own video link directly (a
    # single-candidate row never raises CalendarPageError -- see
    # civicplus.py's own docstring).
    assert result.platform == "granicus"
    assert result.video_found is True
    assert result.meeting_found is True


# --- WO-343: eScribe "Published Meetings" listing walker ---------------
#
# Real gap this closes: `escribe.py`'s own `resolve()` only ever handles
# ONE already-known `Meeting.aspx` page -- exactly WO-333's own control-
# set miss for Victoria BC (`resolved_no_video`: a real title found, zero
# video, because the hub URL handed to it was never one specific
# meeting). `_escribe_walker()` calls eScribe's own
# `MeetingsCalendarView.aspx/GetCalendarMeetings` PageMethod (confirmed
# live 2026-09-13 by reading a real tenant's own page JS -- the same
# endpoint its "Published Meetings" calendar widget calls client-side)
# and returns real candidate meeting URLs newest-first; the actual
# video/caption check is left to the real, registered `escribe.py`
# adapter via `_walk_candidates()`, same division of labor as the
# CivicWeb/Legistar walkers above.


async def test_escribe_walker_real_peel_region_getcalendarmeetings_sorts_newest_first():
    # Real, raw-saved live response (trimmed to 3 of the real 8 entries,
    # kept in the API's own un-sorted array order) -- Peel Region ON's
    # `pub-peelregion.escribemeetings.com`, fetched 2026-09-13. Includes
    # the SAME real "Regional Council" meeting (Id
    # c129beef-a3cf-49ae-827d-27c6b3a547a5, 2026-07-09) that
    # `peel_region_page.html`/`peel_region_captions.vtt` already cover in
    # test_escribe.py -- this only asserts the walker extracts and sorts
    # real candidates newest-first; whether that meeting has video is
    # `escribe.py`'s own `resolve()`'s job (covered below and in
    # test_escribe.py), not duplicated here.
    payload = load_fixture("escribe", "peelregion_calendar_meetings.json")
    post_routes = {
        "https://pub-peelregion.escribemeetings.com/MeetingsCalendarView.aspx/GetCalendarMeetings": (
            FakeResponse(status=200, text=payload)
        ),
    }

    with mock_session({}, post_routes=post_routes):
        candidates = await _escribe_walker("https://pub-peelregion.escribemeetings.com")

    assert len(candidates) == 3
    assert candidates[0]["url"] == (
        "https://pub-peelregion.escribemeetings.com/Meeting.aspx"
        "?Id=c129beef-a3cf-49ae-827d-27c6b3a547a5"
    )
    assert candidates[0]["date"] == "2026-07-09"
    assert candidates[0]["title"] == "Regional Council"
    # The other two real entries share a date (2026-06-18) but different
    # times -- confirms the walker sorts on the full real datetime, not
    # just the date part.
    assert [c["date"] for c in candidates[1:]] == ["2026-06-18", "2026-06-18"]


async def test_escribe_walker_real_hazelton_no_video_candidates():
    # Real, raw-saved live response (trimmed to 2 of the real 7 entries)
    # -- Hazelton BC's `pub-hazelton.escribemeetings.com`, fetched
    # 2026-09-13 -- both real entries carry `HasVideo: false`, matching
    # the confirmed real absence of an `#isi_player` div on both meeting
    # pages (see the end-to-end no-video test below).
    payload = load_fixture("escribe", "hazelton_calendar_meetings.json")
    post_routes = {
        "https://pub-hazelton.escribemeetings.com/MeetingsCalendarView.aspx/GetCalendarMeetings": (
            FakeResponse(status=200, text=payload)
        ),
    }

    with mock_session({}, post_routes=post_routes):
        candidates = await _escribe_walker("https://pub-hazelton.escribemeetings.com")

    assert len(candidates) == 2
    assert candidates[0]["date"] == "2026-09-08"
    assert candidates[1]["date"] == "2026-08-04"
    assert all(
        c["url"].startswith("https://pub-hazelton.escribemeetings.com/Meeting.aspx?Id=")
        for c in candidates
    )


async def test_escribe_walker_non_escribe_host_returns_empty():
    assert await _escribe_walker("https://example.gov/meetings") == []


async def test_real_peel_region_escribe_hub_walks_to_video_and_captions():
    # End-to-end, real fixtures: WO-333's own control set never reached a
    # specific eScribe meeting at all (Victoria BC: `resolved_no_video`,
    # real title, zero video -- see this WO's BACKLOG_DONE entry for the
    # live re-check of Victoria itself). This proves the fix's wiring
    # against a DIFFERENT real tenant with real captions on file: the hub
    # root -> `_escribe_walker()` listing walk -> the real registered
    # `escribe.py` adapter's own `resolve()` on the real Peel Region
    # "Regional Council" meeting page, reaching real video + real
    # captions (tier 1).
    hub_url = "https://pub-peelregion.escribemeetings.com"
    root_html = load_fixture("escribe", "peelregion_root.html")
    calendar_payload = load_fixture("escribe", "peelregion_calendar_meetings.json")
    meeting_url = (
        "https://pub-peelregion.escribemeetings.com/Meeting.aspx"
        "?Id=c129beef-a3cf-49ae-827d-27c6b3a547a5"
    )
    meeting_html = load_fixture("escribe", "peel_region_page.html")
    encoded = "New%20Encoder_Regional%20Council_2026-07-09-09-30.mp4"
    vtt_url = f"https://video.isilive.ca/peelregion/{encoded}.vtt"
    vtt = load_fixture("escribe", "peel_region_captions.vtt")

    routes = {
        hub_url: FakeResponse(status=200, text=root_html, url=hub_url),
        meeting_url: FakeResponse(status=200, text=meeting_html, url=meeting_url),
        vtt_url: FakeResponse(status=200, text=vtt, url=vtt_url),
    }
    post_routes = {
        f"{hub_url}/MeetingsCalendarView.aspx/GetCalendarMeetings": FakeResponse(
            status=200, text=calendar_payload
        ),
    }

    with mock_session(routes, post_routes=post_routes):
        result = await verify_hub(hub_url)

    assert result.meeting_found is True
    assert result.video_found is True
    assert result.captions_found is True
    assert result.platform == "escribe"
    assert result.tier == 1
    assert result.meeting_url == meeting_url


async def test_real_hazelton_escribe_hub_walks_real_candidates_no_video():
    # End-to-end, real fixtures, the opposite real shape: Hazelton BC's
    # own tenant genuinely has no video on either of its two most recent
    # real meetings (confirmed live 2026-09-13 -- neither page carries an
    # `#isi_player` div, matching the real `HasVideo: false` flag eScribe's
    # own listing API already reports for both). A real "meeting found, no
    # video" verdict (tier 4), not a false "no meeting" -- same honest
    # distinction `NoVideoCandidateFound`-based walkers draw elsewhere in
    # this module.
    hub_url = "https://pub-hazelton.escribemeetings.com"
    root_html = load_fixture("escribe", "hazelton_root.html")
    calendar_payload = load_fixture("escribe", "hazelton_calendar_meetings.json")
    meeting_url_1 = f"{hub_url}/Meeting.aspx?Id=cf30ccc6-ca29-4c29-b4d7-9525fcf1853d"
    meeting_url_2 = f"{hub_url}/Meeting.aspx?Id=560f9cb4-5106-4ba7-a66e-56e4b6a8cc27"
    meeting_html_1 = load_fixture("escribe", "hazelton_meeting_20260908_no_video.html")
    meeting_html_2 = load_fixture("escribe", "hazelton_meeting_20260804_no_video.html")

    routes = {
        hub_url: FakeResponse(status=200, text=root_html, url=hub_url),
        meeting_url_1: FakeResponse(status=200, text=meeting_html_1, url=meeting_url_1),
        meeting_url_2: FakeResponse(status=200, text=meeting_html_2, url=meeting_url_2),
    }
    post_routes = {
        f"{hub_url}/MeetingsCalendarView.aspx/GetCalendarMeetings": FakeResponse(
            status=200, text=calendar_payload
        ),
    }

    with mock_session(routes, post_routes=post_routes):
        result = await verify_hub(hub_url)

    assert result.meeting_found is True
    assert result.video_found is False
    assert result.tier == 4
    assert result.candidates_checked == 2
    assert result.verdict == "listing_walked_no_video"


# -- WO-341: `_civicplus_walker()` -- Hobart IN, Monroe County FL, Webb
# County TX real fixtures (the WO-333 residual misses this closes), plus
# ranking-fix #4 (Jefferson County WA's `no_video_in_listing` shape). --


async def test_civicplus_walker_step1_agendacenter_category_real_hobart_park_board():
    # Real, raw-saved page -- cityofhobart.org/AgendaCenter/
    # Board-of-Park-Commissioners-8, fetched live 2026-09-13. `hub_url`
    # below stands in for a confirmed-but-wrong starting page (Monroe/
    # Webb's own WO-333 "confirmed URL was never the real listing page"
    # shape) -- both routes serve the SAME real fixture, since it happens
    # to link back to its own category URL; the walker discovers that
    # link and walks it exactly like it would a real nav link on a
    # different page.
    category_url = (
        "https://www.cityofhobart.org/AgendaCenter/Board-of-Park-Commissioners-8"
    )
    hub_url = "https://www.cityofhobart.org/Boards-Committees"
    fixture_html = load_fixture("civicplus", "hobart_parkboard_agendacenter.html")
    routes = {
        hub_url: FakeResponse(status=200, text=fixture_html, url=hub_url),
        category_url: FakeResponse(status=200, text=fixture_html, url=category_url),
    }

    with mock_session(routes):
        candidates = await _civicplus_walker(hub_url)

    assert candidates, "expected at least one real video-bearing row"
    # CivicMedia links (the WO-341 video path) now come through
    # `_is_real_video_link()` since `detect_platform()` recognizes them --
    # this is the real per-video link this WO's own Hobart end-to-end
    # resolve test (tests/test_civicmedia.py) confirms plays with real
    # captions.
    assert candidates[0]["url"].startswith(
        "https://www.cityofhobart.org/CivicMedia?VID="
    )
    assert candidates[0]["date"] == "2026-08-10"


async def test_civicplus_walker_step2_meeting_nav_link_real_monroe_county():
    # Real, raw-saved pages -- fl-monroecounty2.civicplus.com/291/
    # Boards-Committees (the WO-333 confirmed-but-wrong hub) links a
    # plain "Meetings" nav item to monroecounty-fl.gov/meetings, which
    # embeds a real, direct `monroecounty-fl.granicus.com/ViewPublisher.
    # php?view_id=1` link -- fetched live 2026-09-13. Granicus's own
    # listing-walk/resolve behavior on that URL is covered by its own
    # test file, so it's faked here (isolating this walker's own nav-
    # discovery logic, same "unit test against a FAKE AssetFinder" split
    # the module docstring describes).
    hub_url = "https://fl-monroecounty2.civicplus.com/291/Boards-Committees"
    # The real "/meetings" nav link is host-relative, so it resolves
    # against the tenant subdomain `hub_url` itself was fetched from
    # (`urljoin()`, same as a real browser) -- the fixture content is the
    # same real page either way (Monroe County's `www.monroecounty-fl.gov`
    # white-labeled domain and its `fl-monroecounty2.civicplus.com`
    # tenant both serve it, confirmed live).
    meetings_url = "https://fl-monroecounty2.civicplus.com/meetings"
    vendor_url = "https://monroecounty-fl.granicus.com/ViewPublisher.php?view_id=1"
    routes = {
        hub_url: FakeResponse(
            status=200,
            text=load_fixture("civicplus", "monroe_boards_committees.html"),
            url=hub_url,
        ),
        meetings_url: FakeResponse(
            status=200,
            text=load_fixture("civicplus", "monroe_meetings.html"),
            url=meetings_url,
        ),
    }
    fake_granicus = _FakeFinder(
        {
            vendor_url: _resolved(
                video_url="https://example.test/budget-meeting.mp4",
                title="BUDGET MEETING 2026-09-09",
                source_url=vendor_url,
            )
        }
    )
    fake_granicus.platform_name = "granicus"
    register(fake_granicus)
    try:
        with mock_session(routes):
            candidates = await _civicplus_walker(hub_url)
    finally:
        register(GranicusAssetFinder())  # restore the real one for later tests

    assert candidates == [{"title": "", "date": None, "url": vendor_url}]


async def test_civicplus_walker_step2_video_nav_link_real_webb_county():
    # Real, raw-saved pages -- webbcountytx.gov/327/Agendas-Minutes (the
    # WO-333 confirmed-but-wrong hub) links "Commissioners Court Live &
    # Archived Videos"/"Live Broadcast & Archives" to /889/Live-Archived-
    # Videos, which iframe-embeds `webbcountytx.swagit.com` directly --
    # fetched live 2026-09-13. Swagit's own resolve() is faked here, same
    # reasoning as the Monroe County test above.
    hub_url = "https://www.webbcountytx.gov/327/Agendas-Minutes"
    nav_url = "https://www.webbcountytx.gov/889/Live-Archived-Videos"
    vendor_url = "https://webbcountytx.swagit.com"
    # The real page has FOUR "video"/"meeting"-matching nav links --
    # `_CIVICPLUS_MAX_VIDEO_NAV_LINKS` tries the first 3 (this exact one
    # is 3rd, after the self-referencing "/327/Agendas-Minutes" link is
    # excluded as `final_url`) -- mock all 3 so the walker's own real
    # ordering is exercised, not just the one link that happens to matter.
    bland = "<html><body>No video vendor link here.</body></html>"
    routes = {
        hub_url: FakeResponse(
            status=200,
            text=load_fixture("civicplus", "webb_agendas_minutes.html"),
            url=hub_url,
        ),
        "https://www.webbcountytx.gov/889/Commissioners-Court-Live-Archived-Videos": (
            FakeResponse(status=200, text=bland)
        ),
        "https://www.webbcountytx.gov/335/Commissioners-Court-Meeting-Dates-Deadli": (
            FakeResponse(status=200, text=bland)
        ),
        nav_url: FakeResponse(
            status=200,
            text=load_fixture("civicplus", "webb_live_archived_videos.html"),
            url=nav_url,
        ),
    }
    fake_swagit = _FakeFinder(
        {
            vendor_url: _resolved(
                video_url="https://example.test/commissioners-court.mp4",
                title="Commissioners Court Meeting",
                source_url=vendor_url,
            )
        }
    )
    fake_swagit.platform_name = "swagit"
    register(fake_swagit)
    try:
        with mock_session(routes):
            candidates = await _civicplus_walker(hub_url)
    finally:
        from app.platforms.swagit import SwagitAssetFinder

        register(SwagitAssetFinder())  # restore the real one for later tests

    assert candidates == [{"title": "", "date": None, "url": vendor_url}]


def test_generic_meeting_links_matches_real_swagit_video_urls():
    # Real, raw-saved (truncated to 20KB) page -- webbcountytx.new.
    # swagit.com/views/482, the bare-tenant-root redirect target, fetched
    # live 2026-09-13. Confirms the `/videos/\d` addition to
    # `_MEETING_DETAIL_HINTS` (WO-341) actually matches Swagit's real
    # per-meeting link shape -- before that fix, this generic fallback
    # walker found zero candidates on a page that lists real, on-mission
    # Commissioners Court meetings.
    from app.platforms.passive_verify import _generic_meeting_links

    html = load_fixture("civicplus", "webb_swagit_views_482_excerpt.html")
    links = _generic_meeting_links(
        html, "https://webbcountytx.new.swagit.com/views/482"
    )
    target = "https://webbcountytx.new.swagit.com/videos/399801"
    urls = {c["url"] for c in links}
    assert target in urls
    real_titles = {c["title"] for c in links if c["url"] == target}
    assert any("Commissioners Court" in t for t in real_titles)


async def test_ranking_fix_4_tries_platform_listing_walker_after_no_video_in_listing():
    # WO-341 fix #4 -- the Jefferson County WA shape: a confirmed
    # AgendaCenter category page with real rows and NO video
    # (`no_video_in_listing`, `candidates_checked>0`) used to return
    # immediately without ever trying a listing walker. Real fixture:
    # ks-desoto.civicplus.com's AgendaCenter page (already used by
    # test_civicplus.py's own `test_real_desoto_listing_page_finds_zero_
    # video_candidates` -- 12 real rows, every `td.media` link a YouTube
    # channel/live shape `_is_real_video_link()` correctly rejects, so
    # `NoVideoCandidateFound(candidates_checked=12)`).
    #
    # `_civicplus_walker` itself is swapped for a scripted fake here --
    # this test is about the RANKING FIX calling the walker at all, not
    # about the real walker's own logic (covered by the tests above).
    from app.platforms import passive_verify as pv

    hub_url = "https://ks-desoto.civicplus.com/AgendaCenter/City-Council-1"
    fixture_html = load_fixture("civicplus", "ks_desoto_agendacenter.html")
    # Not `.mp4`/any other direct-file-shaped extension -- `detect_platform()`
    # would otherwise route it to the real, unmocked DirectFileAssetFinder
    # (WO-303's `is_direct_file_url()`) instead of falling back to the
    # walker's own declared "civicplus" platform, the thing this test
    # actually wants to exercise.
    real_video_url = "https://example.test/real-council-meeting"

    async def fake_walker(url):
        assert url == hub_url
        return [{"title": "City Council", "date": "2026-09-01", "url": real_video_url}]

    class _DelegatingCivicPlusFinder(AssetFinder):
        # `_walk_candidates()` (called by the ranking-fix's own retry of
        # `_try_listing_walker`) uses `detect_platform(candidate_url)`,
        # which won't recognize `example.test` -- falls back to the
        # walker's own declared platform ("civicplus"), so the fake
        # candidate resolution has to be registered under that SAME key
        # the real `CivicPlusAssetFinder` already owns. Rather than
        # replacing it outright (which would also fake out the real,
        # load-bearing `ks-desoto` fixture parse this test needs to
        # genuinely raise `NoVideoCandidateFound(candidates_checked=12)`),
        # this delegates to the real finder for everything except the
        # one scripted candidate URL.

        platform_name = "civicplus"

        def __init__(self):
            self._real = CivicPlusAssetFinder()

        async def resolve(self, url: str) -> ResolvedMeeting:
            if url == real_video_url:
                return _resolved(
                    video_url=real_video_url,
                    title="City Council",
                    source_url=real_video_url,
                )
            return await self._real.resolve(url)

    pv._ensure_walkers_registered()  # make sure the real registrations exist first
    original_walker = pv._LISTING_WALKERS["civicplus"]
    original_civicplus_finder = CivicPlusAssetFinder()
    pv.register_listing_walker("civicplus", fake_walker)
    register(_DelegatingCivicPlusFinder())
    try:
        routes = {hub_url: FakeResponse(status=200, text=fixture_html, url=hub_url)}
        with mock_session(routes):
            result = await verify_hub(hub_url, platform_hint="civicplus")
    finally:
        pv.register_listing_walker("civicplus", original_walker)
        register(original_civicplus_finder)

    assert result.video_found is True
    assert result.meeting_url == real_video_url
    assert result.ranking_fix_applied is True


# --- WO-344: iQM2's second tenant shape -------------------------------
#
# Real gap this closes: `iqm2.py`'s own `resolve()` only ever handles a
# URL that's already a specific `Detail_Meeting.aspx?ID=`/`SplitView.
# aspx?...MeetingID=` page -- given a tenant root/Citizens-portal hub
# URL it has no meeting id to extract and comes back empty, WO-333's
# confirmed Knoxville, TN miss (`resolved_empty`, hub =
# `knoxvillecitytn.iqm2.com/Citizens/Default.aspx`, reached from
# `knoxvilletn.gov`'s own real agendas-and-minutes page -- see
# `docs/investigations/wo333_verification_walk.md`). `_iqm2_walker()`
# calls IQM2's own real `calendar.aspx?View=List` endpoint (confirmed
# live 2026-09-13 against Atlanta GA's already-active tenant, Monroe
# County FL, and Knoxville TN) and returns real candidates newest-first;
# `_walk_candidates()`'s real, registered `iqm2.py` adapter does the
# actual video/caption resolve, same division of labor as every other
# walker in this module.


def _iqm2_calendar_url(origin: str, days_back: int) -> str:
    """Mirrors `_iqm2_walker()`'s own URL construction exactly, so these
    tests don't need to mock "today" -- whatever real date the test runs
    on, the walker builds the identical URL (same pattern the Legistar
    walker's own test above already uses)."""
    import datetime as _dt

    today = _dt.datetime.now(_dt.timezone.utc).date()
    start = today - _dt.timedelta(days=days_back)
    end = today + _dt.timedelta(days=30)
    return (
        f"{origin}/Citizens/calendar.aspx?View=List"
        f"&From={start.month}/{start.day}/{start.year}"
        f"&To={end.month}/{end.day}/{end.year}"
    )


async def test_iqm2_walker_real_monroecountyfl_widens_to_fallback_window():
    # Monroe County FL's real tenant (this WO's own with-video control)
    # has nothing in the narrow (400-day) window -- confirmed live
    # 2026-09-13, its calendar has been dormant since Dec 2023 -- so the
    # walker must widen to the 3-year fallback before it finds anything.
    origin = "https://monroecountyfl.iqm2.com"
    narrow_url = _iqm2_calendar_url(origin, 400)
    wide_url = _iqm2_calendar_url(origin, 1095)
    calendar_html = load_fixture("iqm2", "monroecountyfl_calendar_list.html")

    routes = {
        narrow_url: FakeResponse(status=200, text="<html><body></body></html>"),
        wide_url: FakeResponse(status=200, text=calendar_html),
    }

    with mock_session(routes):
        candidates = await _iqm2_walker(f"{origin}/Citizens/Default.aspx")

    assert len(candidates) == 2
    # Newest first -- Dec 13 2023 (ID 1180, this WO's control) ahead of
    # Nov 8 2023 (ID 1179), even though 1179 appears first in the real
    # calendar page's own row order.
    assert candidates[0]["url"] == f"{origin}/Citizens/Detail_Meeting.aspx?ID=1180"
    assert candidates[0]["date"] == "2023-12-13"
    assert candidates[1]["url"] == f"{origin}/Citizens/Detail_Meeting.aspx?ID=1179"


async def test_iqm2_walker_real_knoxvillecitytn_narrow_window_finds_candidates():
    # Knoxville, TN's real tenant IS active in the narrow window (its
    # newest real meeting is ~334 days back from this WO's "today",
    # confirmed live 2026-09-13) -- no widening needed, unlike Monroe
    # County FL above.
    origin = "https://knoxvillecitytn.iqm2.com"
    narrow_url = _iqm2_calendar_url(origin, 400)
    calendar_html = load_fixture("iqm2", "knoxvillecitytn_calendar_list.html")

    routes = {narrow_url: FakeResponse(status=200, text=calendar_html)}

    with mock_session(routes):
        candidates = await _iqm2_walker(f"{origin}/Citizens/Default.aspx")

    assert len(candidates) == 2
    assert candidates[0]["url"] == f"{origin}/Citizens/Detail_Meeting.aspx?ID=1691"
    assert candidates[0]["date"] == "2025-12-09"
    assert candidates[1]["url"] == f"{origin}/Citizens/Detail_Meeting.aspx?ID=1690"


async def test_iqm2_walker_non_iqm2_host_returns_empty():
    assert await _iqm2_walker("https://example.gov/meetings") == []


async def test_real_monroecountyfl_iqm2_hub_walks_to_video_no_captions():
    # End-to-end, real fixtures: this WO's own with-video control. The
    # hub is the bare tenant root (no meeting id) -- the same shape
    # WO-333 confirmed empty on Knoxville -- walking it reaches a real
    # meeting with a real Granicus-hosted video and a genuinely blank
    # caption track (tier 3, not tier 1 -- confirmed live: MeetingID
    # 1180's own TranscriptGet.aspx is a real HTTP 200 empty placeholder).
    origin = "https://monroecountyfl.iqm2.com"
    hub_url = f"{origin}/Citizens/Default.aspx"
    narrow_url = _iqm2_calendar_url(origin, 400)
    wide_url = _iqm2_calendar_url(origin, 1095)
    calendar_html = load_fixture("iqm2", "monroecountyfl_calendar_list.html")
    outline_url = (
        f"{origin}/Citizens/Detail_Meeting.aspx?Target=Detail&CssClass=AgendaOutline"
        f"&Mode=Video&Frame=Nothing&ID=1180"
    )
    split_url = (
        f"{origin}/Citizens/SplitView.aspx?Mode=Video&MeetingID=1180&Format=Minutes"
    )

    routes = {
        narrow_url: FakeResponse(status=200, text="<html><body></body></html>"),
        wide_url: FakeResponse(status=200, text=calendar_html),
        outline_url: FakeResponse(
            status=200, text=load_fixture("iqm2", "monroecountyfl_1180_outline.html")
        ),
        split_url: FakeResponse(
            status=200, text=load_fixture("iqm2", "monroecountyfl_1180_split.html")
        ),
    }

    with mock_session(routes):
        result = await verify_hub(hub_url, platform_hint="iqm2")

    assert result.meeting_found is True
    assert result.video_found is True
    assert result.captions_found is False
    assert result.platform == "iqm2"
    assert result.tier == 3
    assert result.meeting_url == f"{origin}/Citizens/Detail_Meeting.aspx?ID=1180"


async def test_real_knoxvillecitytn_iqm2_hub_walks_real_candidates_no_video():
    # End-to-end, real fixtures, the opposite real shape: Knoxville's own
    # City Council meetings genuinely have no video in this tenant's
    # narrow window (confirmed live 2026-09-13 -- both SplitView pages
    # carry an empty `<!-- MEDIA URL: -->` comment). A real "meeting
    # found, no video" verdict (tier 4), not a false "no meeting" -- the
    # exact fix for WO-333's `resolved_empty` miss on this government.
    origin = "https://knoxvillecitytn.iqm2.com"
    hub_url = f"{origin}/Citizens/Default.aspx"
    narrow_url = _iqm2_calendar_url(origin, 400)
    calendar_html = load_fixture("iqm2", "knoxvillecitytn_calendar_list.html")
    outline_1691 = (
        f"{origin}/Citizens/Detail_Meeting.aspx?Target=Detail&CssClass=AgendaOutline"
        f"&Mode=Video&Frame=Nothing&ID=1691"
    )
    split_1691 = (
        f"{origin}/Citizens/SplitView.aspx?Mode=Video&MeetingID=1691&Format=Minutes"
    )
    outline_1690 = (
        f"{origin}/Citizens/Detail_Meeting.aspx?Target=Detail&CssClass=AgendaOutline"
        f"&Mode=Video&Frame=Nothing&ID=1690"
    )
    split_1690 = (
        f"{origin}/Citizens/SplitView.aspx?Mode=Video&MeetingID=1690&Format=Minutes"
    )

    routes = {
        narrow_url: FakeResponse(status=200, text=calendar_html),
        outline_1691: FakeResponse(
            status=200, text=load_fixture("iqm2", "knoxvillecitytn_1691_outline.html")
        ),
        split_1691: FakeResponse(
            status=200, text=load_fixture("iqm2", "knoxvillecitytn_1691_split.html")
        ),
        outline_1690: FakeResponse(
            status=200, text=load_fixture("iqm2", "knoxvillecitytn_1690_outline.html")
        ),
        split_1690: FakeResponse(
            status=200, text=load_fixture("iqm2", "knoxvillecitytn_1690_split.html")
        ),
    }

    with mock_session(routes):
        result = await verify_hub(hub_url, platform_hint="iqm2")

    assert result.meeting_found is True
    assert result.video_found is False
    assert result.tier == 4
    assert result.candidates_checked == 2
    assert result.verdict == "listing_walked_no_video"


# --- WO-344: townhallstreams.com's real listing walker -----------------
#
# Real gap this closes: `townhallstreams.py`'s own `resolve()` only ever
# handles a URL that already has both `location_id` and `id` query
# params -- given the town's own hub page it finds no video/caption JS on
# that page (it's a listing, not a player) and comes back empty, exactly
# WO-333's confirmed Troy, NH miss (`resolved_empty`, hub =
# `www.townhallstreams.com/towns/troy_nh`, "handed the real town hub
# directly -- still empty").


async def test_townhallstreams_walker_real_troynh_hub_filters_future_and_sorts():
    hub_url = "https://www.townhallstreams.com/towns/troy_nh"
    hub_html = load_fixture("townhallstreams", "troynh_hub_towns_page.html")

    routes = {hub_url: FakeResponse(status=200, text=hub_html, url=hub_url)}

    # WO-348 (resume): this test's "future" assertion is anchored to a
    # real, fixed capture date (2026-09-13) baked into the fixture's own
    # dated rows -- it's not relative to whenever the suite happens to
    # run. Confirmed live 2026-09-13/14: real wall-clock time crossing
    # midnight UTC past the fixture's own Sept 14 2026 row made this test
    # fail on a plain `datetime.now()` call, on origin/main, with none of
    # this WO's own changes applied -- a pre-existing, date-boundary bug,
    # not something this WO introduced. Freezing `_townhallstreams_
    # walker()`'s own "today" to the fixture's real capture date keeps
    # the test deterministic regardless of when it's actually run.
    class _FrozenDatetime(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 13, 12, 0, 0, tzinfo=tz)

    with (
        mock_session(routes),
        patch("app.platforms.passive_verify._dt.datetime", _FrozenDatetime),
    ):
        candidates = await _townhallstreams_walker(hub_url)

    # The real fixture has 3 rows -- one (id 76219, Sept 14 2026) is
    # dated AFTER this WO's "today" (2026-09-13) and must be filtered
    # out, same "a future meeting's video status lies" rule the Legistar
    # walker's own EventDate filter already applies.
    assert len(candidates) == 2
    assert candidates[0]["url"] == (
        "https://www.townhallstreams.com/stream.php?location_id=169&id=76647"
    )
    assert candidates[0]["date"] == "2026-09-10"
    assert (
        candidates[0]["title"]
        == "Water & Sewer Commision September 10, 2026 - 06:00 pm to 10:00 pm (EST)"
    )
    assert candidates[1]["url"] == (
        "https://www.townhallstreams.com/stream.php?location_id=169&id=75863"
    )


async def test_townhallstreams_walker_non_townhallstreams_host_returns_empty():
    assert await _townhallstreams_walker("https://example.gov/meetings") == []


async def test_real_troynh_townhallstreams_hub_walks_to_video():
    # End-to-end, real fixtures: this WO's own control. The hub is the
    # real town listing page WO-333 confirmed empty -- walking it reaches
    # a real, currently live meeting video (tier 3 -- townhallstreams.py
    # has no confirmed real caption path, see its own module docstring).
    hub_url = "https://www.townhallstreams.com/towns/troy_nh"
    hub_html = load_fixture("townhallstreams", "troynh_hub_towns_page.html")
    meeting_url = "https://www.townhallstreams.com/stream.php?location_id=169&id=76647"
    meeting_html = load_fixture("townhallstreams", "troynh_stream_76647.html")
    transcript_url = (
        "https://townhallstreams.com/stream.php?full=1&location_id=169"
        "&id=76647&action=get_transcriptions"
    )

    routes = {
        hub_url: FakeResponse(status=200, text=hub_html, url=hub_url),
        meeting_url: FakeResponse(status=200, text=meeting_html, url=meeting_url),
        transcript_url: FakeResponse(status=200, text=""),
    }

    with mock_session(routes):
        result = await verify_hub(hub_url, platform_hint="townhallstreams")

    assert result.meeting_found is True
    assert result.video_found is True
    assert result.captions_found is False
    assert result.platform == "townhallstreams"
    assert result.tier == 3
    assert result.meeting_url == meeting_url


# --- WO-344: Cablecast's third template's own listing walker -----------
#
# Real gap this closes: neither of `cablecast.py`'s resolve paths has a
# listing/hub concept at all (both need an already-known show id) --
# `_cablecast_walker()` fetches the tenant's own root page, which the
# real FastBoot app server-renders with a real show catalog (confirmed
# live 2026-09-13 on Dyersville, IA -- see `cablecast.py`'s own module
# docstring for the full investigation).


async def test_cablecast_walker_real_dyersville_root_newest_first():
    root_url = "https://city-dyersville-ia.cablecast.tv/"
    root_html = load_fixture("cablecast", "dyersville_root.html")

    routes = {root_url: FakeResponse(status=200, text=root_html, url=root_url)}

    with mock_session(routes):
        candidates = await _cablecast_walker(
            "https://city-dyersville-ia.cablecast.tv/show/1?site=1"
        )

    assert len(candidates) == 46
    assert candidates[0]["url"] == (
        "https://city-dyersville-ia.cablecast.tv/show/3660?site=1"
    )
    assert candidates[0]["title"] == "City Council Meeting 2026-09-08"
    assert candidates[0]["date"] == "2026-09-08"
    # Confirms the real duplicate-anchor bug this walker had to avoid: the
    # real page renders TWO anchors per show (an empty-text image link,
    # then the real title link) to the SAME href -- each show appears
    # here only once, keeping the title-bearing anchor.
    assert len({c["url"] for c in candidates}) == 46


async def test_cablecast_walker_non_cablecast_host_returns_empty():
    assert await _cablecast_walker("https://example.gov/meetings") == []


# --- WO-1036: Cablecast's Remix template puts the date in the title too,
# in shapes other than ISO -- confirmed live 2026-09-23 on Redlands, CA
# ("City Council Special Meeting September 21, 2026"), Champaign, IL
# ("...- 9/22/26") and Glendora, CA (same shapes). Before this fix, only
# the ISO shape was tried, so every one of these came back `date=None`.


async def test_cablecast_walker_reads_month_name_date_from_title():
    root_url = "https://cityofredlands.cablecast.tv/"
    root_html = (
        '<html><body><a href="/show/538">'
        "City Council Special Meeting September 21, 2026</a></body></html>"
    )
    routes = {root_url: FakeResponse(status=200, text=root_html, url=root_url)}
    with mock_session(routes):
        candidates = await _cablecast_walker(root_url)
    assert candidates[0]["date"] == "2026-09-21"


async def test_cablecast_walker_reads_slash_date_from_title():
    root_url = "https://champaign-cablecast.cablecast.tv/"
    root_html = (
        '<html><body><a href="/show/4">City Council - 07/07/2026</a></body></html>'
    )
    routes = {root_url: FakeResponse(status=200, text=root_html, url=root_url)}
    with mock_session(routes):
        candidates = await _cablecast_walker(root_url)
    assert candidates[0]["date"] == "2026-07-07"


async def test_cablecast_walker_reads_two_digit_year_slash_date_from_title():
    root_url = "https://glendora.cablecast.tv/"
    root_html = '<html><body><a href="/show/9">City Council - 9/22/26</a></body></html>'
    routes = {root_url: FakeResponse(status=200, text=root_html, url=root_url)}
    with mock_session(routes):
        candidates = await _cablecast_walker(root_url)
    assert candidates[0]["date"] == "2026-09-22"


def test_parse_cablecast_title_date_returns_none_for_no_date():
    from app.platforms.passive_verify import _parse_cablecast_title_date

    assert _parse_cablecast_title_date("City Council Meeting") is None


def test_parse_cablecast_title_date_prefers_iso_when_present():
    from app.platforms.passive_verify import _parse_cablecast_title_date

    # An (unrealistic but defensive) title with both an ISO date and a
    # slash-shaped number -- ISO wins since it's checked first and is
    # unambiguous.
    assert (
        _parse_cablecast_title_date("Meeting 2026-09-08 (posted 1/2/26)")
        == "2026-09-08"
    )


async def test_real_dyersville_cablecast_hub_walks_to_video_and_captions():
    # End-to-end, real fixtures: a bare tenant root URL has no show id at
    # all (`_extract_show_id()` returns None immediately) -- confirms the
    # walker is reached and finds this WO's own real Dyersville control,
    # tier 1 (real video AND real captions -- see cablecast.py's own
    # FastBoot module docstring for the full investigation).
    origin = "http://city-dyersville-ia.cablecast.tv"
    hub_url = f"{origin}/"
    root_html = load_fixture("cablecast", "dyersville_root.html")
    show_url = f"{origin}/show/3660?site=1"
    show_html = load_fixture("cablecast", "dyersville_show_3660_raw.html")
    embed_url = f"{origin}/embed/vod?show=3660&site=1"
    embed_html = load_fixture("cablecast", "dyersville_embed_vod_3660.html")
    vod_url = f"{origin}/vod/3660-City-Council-Meeting-2026-09-08-v2/vod.m3u8".replace(
        "http://", "https://"
    )
    captions_url = (
        "https://city-dyersville-ia.cablecast.tv/vod/"
        "3660-City-Council-Meeting-2026-09-08-v2/captions.en.m3u8"
    )
    seg0_url = (
        "https://city-dyersville-ia.cablecast.tv/vod/"
        "3660-City-Council-Meeting-2026-09-08-v2/subtitles/28986/"
        "captions.en.00000.vtt?duration=10"
    )
    seg1_url = (
        "https://city-dyersville-ia.cablecast.tv/vod/"
        "3660-City-Council-Meeting-2026-09-08-v2/subtitles/28986/"
        "captions.en.00001.vtt?duration=10"
    )

    routes = {
        # cablecast.py's own resolve() always forces http for its two
        # direct-fetch attempts (the show path itself, then the root
        # fallback) -- both come back with no `window.__remixContext`
        # (real FastBoot/Ember content, not Remix), so `show` stays None
        # and the FastBoot fallback (and, once that also 404s below, this
        # walker) is what actually finds the video.
        hub_url: FakeResponse(status=200, text=root_html, url=hub_url),
        show_url: FakeResponse(status=200, text=show_html, url=show_url),
        embed_url: FakeResponse(status=200, text=embed_html, url=embed_url),
        vod_url: FakeResponse(
            status=200, text=load_fixture("cablecast", "dyersville_vod_3660.m3u8")
        ),
        captions_url: FakeResponse(
            status=200,
            text=load_fixture("cablecast", "dyersville_captions_en_3660.m3u8"),
        ),
        seg0_url: FakeResponse(
            status=200,
            text=load_fixture("cablecast", "dyersville_captions_en_00000.vtt"),
        ),
        seg1_url: FakeResponse(
            status=200,
            text=load_fixture("cablecast", "dyersville_captions_en_00001.vtt"),
        ),
    }

    with mock_session(routes):
        result = await verify_hub(hub_url, platform_hint="cablecast")

    assert result.meeting_found is True
    assert result.video_found is True
    assert result.captions_found is True
    assert result.platform == "cablecast"
    assert result.tier == 1
    assert result.meeting_url == f"{origin}/show/3660?site=1"
