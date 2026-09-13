"""Tests for `app/platforms/passive_verify.py` (WO-333).

Two layers, matching how the rest of this repo tests an orchestration
module vs. an adapter: (1) unit tests against a small FAKE AssetFinder
registered under a made-up platform name, isolating `verify_hub()`'s own
walk/verdict/ranking logic from any real adapter's `resolve()`
correctness (already covered by that adapter's own test file); (2) one
real, fixture-backed end-to-end test through the Granicus listing walker
this WO added, and one through the real Franklin NH CivicPlus ranking
scenario, to prove the wiring works against real pages, not just fakes.
"""

import pytest

from app.platforms.base import (
    AssetFinder,
    CalendarPageError,
    NoVideoCandidateFound,
    register,
)
from app.platforms.civicplus import CivicPlusAssetFinder
from app.platforms.granicus import GranicusAssetFinder
from app.platforms.models import ResolvedMeeting, TranscriptSegment
from app.platforms.passive_verify import (
    _civicweb_walker,
    _legistar_walker,
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
    # civicplus.py/granicus.py are real, already-tested adapters used by
    # the end-to-end tests below; registered here so `get_finder()` finds
    # them the same way `register_all_finders()` would in production.
    register(CivicPlusAssetFinder())
    register(GranicusAssetFinder())


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
