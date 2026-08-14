"""Tests for the generic "unknown platform" fallback (built 2026-08-09,
directly from the user's own request: try our best instead of a flat
"we don't support this yet"). Registered under platform_name="unknown",
the exact string detect_platform() returns for anything unmatched.
"""

import pytest
import yt_dlp

from app.platforms.generic_fallback import GenericFallbackAssetFinder
from app.platforms.youtube import YouTubeAssetFinder
from app.utils import url_guard

from aiohttp_mock import FakeResponse, mock_session


@pytest.fixture(autouse=True)
def _fake_public_dns(monkeypatch):
    """Every resolve() call in this file now runs its URL through
    app.utils.url_guard's SSRF check (WO-5), which resolves the hostname
    for real. The domains used throughout this file (crrma.org, etc.) are
    real-looking fixture data, never actually fetched -- mock_session
    intercepts session.get() before any network call happens -- so DNS
    must never really run here either, or the suite stops being hermetic.
    Patches the resolver to return a fixed public IP for any hostname
    that isn't already a literal IP. Tests that exercise the guard's own
    IP-classification logic (private/loopback/link-local rejection, the
    redirect-to-private-IP case) use literal-IP URLs instead and don't
    need this."""
    monkeypatch.setattr(url_guard, "_resolve_hostname", lambda hostname: ["93.184.216.34"])

# Real page shape confirmed live 2026-08-13 across 5 real CRRMA board
# meeting URLs (crrma.org/information/meetings/board/{date}) -- see
# BACKLOG.md's "generic_fallback.py's YouTube-embed branch" entry.
# Trimmed to just the parts _backfill_metadata_from_page() reads.
CRRMA_URL = "https://www.crrma.org/information/meetings/board/2025-11-12"
CRRMA_VIDEO_ID = "dQw4w9WgXcQ"
CRRMA_PAGE_HTML = f"""
<html><head><title>Camino Real Regional Mobility Authority | El Paso, Texas</title></head>
<body>
<iframe src="https://www.youtube.com/embed/{CRRMA_VIDEO_ID}"></iframe>
<h1 id="notice-of-meeting">NOTICE OF MEETING</h1>
<h2 id="november-12-2025-----900am">November 12, 2025 - 9:00am</h2>
<p><strong>A meeting of the CRRMA Board of Directors will be held on Wednesday November 12, 2025,
at 9:00am in the 2nd Floor Main Conference Room of El Paso City Hall, located at 300 N. Campbell,
El Paso, Texas 79901.</strong></p>
</body></html>
"""

PAGE_URL = "https://some-city.example.gov/meetings/council-2026-01-01"
REAL_VIDEO_ID = "dQw4w9WgXcQ"

PAGE_WITH_YOUTUBE_EMBED = f"""
<html><body>
<iframe src="https://www.youtube.com/embed/{REAL_VIDEO_ID}"></iframe>
</body></html>
"""

PAGE_WITH_DIRECT_MEDIA = """
<html><body>
<video src="https://cdn.example.gov/videos/meeting.m3u8"></video>
<a href="https://cdn.example.gov/captions/meeting.vtt">Captions</a>
</body></html>
"""

PAGE_WITH_NOTHING = "<html><body>Agenda: Item 1, Item 2. No video here.</body></html>"

REAL_VTT = """WEBVTT

00:00:00.000 --> 00:00:02.000
Hello and welcome.

00:00:02.000 --> 00:00:04.000
This meeting is now in session.
"""


def _fake_extract_info(video_id):
    return {"title": "Some City Council Meeting", "uploader": "Some City Gov", "upload_date": "20260101"}


async def test_resolve_delegates_to_youtube_when_embed_found(monkeypatch):
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    routes = {PAGE_URL: FakeResponse(status=200, text=PAGE_WITH_YOUTUBE_EMBED, url=PAGE_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(PAGE_URL)

    assert result.platform == "youtube"  # delegated finder's own platform name, unchanged -- real dedup identity
    assert result.video_url == f"https://www.youtube.com/embed/{REAL_VIDEO_ID}"
    assert any("isn't officially supported" in w for w in result.video_warnings)
    # best_effort must be True even though platform says "youtube" -- the
    # frontend can't rely on platform alone to detect this is a fallback
    # result, since this delegated case is the most common real outcome.
    assert result.best_effort is True


async def test_resolve_finds_direct_media_and_captions(monkeypatch):
    routes = {
        PAGE_URL: FakeResponse(status=200, text=PAGE_WITH_DIRECT_MEDIA, url=PAGE_URL),
        "https://cdn.example.gov/captions/meeting.vtt": FakeResponse(status=200, text=REAL_VTT, url="x"),
    }

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(PAGE_URL)

    assert result.platform == "unknown"
    assert result.video_url == "https://cdn.example.gov/videos/meeting.m3u8"
    assert result.video_format == "m3u8"
    assert len(result.segments) == 2
    assert result.segments[0].text == "Hello and welcome."
    assert any("isn't officially supported" in w for w in result.video_warnings)


async def test_resolve_returns_honest_no_video_message_when_nothing_found():
    routes = {PAGE_URL: FakeResponse(status=200, text=PAGE_WITH_NOTHING, url=PAGE_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(PAGE_URL)

    assert result.platform == "unknown"
    assert result.video_url is None
    assert result.segments == []
    assert any("couldn't find a video on this page automatically" in w for w in result.video_warnings)
    assert any("didn't automatically find a transcript" in w for w in result.transcript_warnings)


async def test_resolve_handles_page_fetch_failure_cleanly():
    routes = {PAGE_URL: FakeResponse(status=500, text="", url=PAGE_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(PAGE_URL)

    assert result.platform == "unknown"
    assert result.video_url is None
    assert any("couldn't even load the page" in w for w in result.video_warnings)


async def test_resolve_finds_media_without_captions(monkeypatch):
    page_no_captions = """
    <html><body><video src="https://cdn.example.gov/videos/meeting.mp4"></video></body></html>
    """
    routes = {PAGE_URL: FakeResponse(status=200, text=page_no_captions, url=PAGE_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(PAGE_URL)

    assert result.video_url == "https://cdn.example.gov/videos/meeting.mp4"
    assert result.video_format == "mp4"
    assert result.segments == []
    assert any("didn't automatically find a transcript" in w for w in result.transcript_warnings)


async def test_resolve_surfaces_agenda_pdf_link_alongside_youtube_video(monkeypatch):
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    page = f"""
    <html><body>
    <iframe src="https://www.youtube.com/embed/{REAL_VIDEO_ID}"></iframe>
    <p>Agenda: Item 1, Item 2, Item 3.</p>
    <a href="/docs/2026-01-01-agenda.pdf">View Agenda (PDF)</a>
    <a href="/minutes/2026-01-01.pdf">Minutes</a>
    </body></html>
    """
    routes = {PAGE_URL: FakeResponse(status=200, text=page, url=PAGE_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(PAGE_URL)

    expected_link = "https://some-city.example.gov/docs/2026-01-01-agenda.pdf"
    assert result.agenda_link == expected_link
    # The plain-text "Agenda: Item 1..." paragraph must not be picked up as
    # if it were structured agenda items -- this adapter never populates
    # agenda_items, only a plain link message.
    assert result.agenda_items == []


async def test_resolve_ignores_plain_text_agenda_mention_with_no_link():
    routes = {PAGE_URL: FakeResponse(status=200, text=PAGE_WITH_NOTHING, url=PAGE_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(PAGE_URL)

    assert result.agenda_link is None


async def test_resolve_prefers_pdf_agenda_link_over_html_agenda_page():
    page = """
    <html><body>
    <video src="https://cdn.example.gov/videos/meeting.mp4"></video>
    <a href="/meetings/2026-01-01/agenda">Agenda</a>
    <a href="/docs/2026-01-01-agenda.pdf">Agenda (PDF)</a>
    </body></html>
    """
    routes = {PAGE_URL: FakeResponse(status=200, text=page, url=PAGE_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(PAGE_URL)

    assert "2026-01-01-agenda.pdf" in result.agenda_link


# --- Delegation to an already-supported platform, found as a plain link ---
# Built 2026-08-10 directly from a real user finding: Austin, TX's own
# council meeting pages (austintexas.gov/council/{date}-reg) don't embed
# video at all -- they link out to austintx.swagit.com/play/{id}/0/ as a
# plain <a href>, which SwagitAssetFinder already resolves correctly on its
# own. No reason to guess at a generic media-URL scan when a real, already-
# tested adapter is one link away.

PAGE_WITH_SWAGIT_LINK = """
<html><body>
<a class="edims" href="http://cityname.swagit.com/play/395511/0/">Video</a>
</body></html>
"""


class _FakeSwagitFinder:
    platform_name = "swagit"

    async def resolve(self, url):
        from app.platforms.models import ResolvedMeeting
        return ResolvedMeeting(
            platform="swagit",
            source_url=url,
            video_url="https://archive-stream.granicus.com/OnDemand/fake.mp4/playlist.m3u8",
            video_format="m3u8",
            title="Real City Council Meeting",
            date="2026-08-06",
        )


async def test_resolve_delegates_to_swagit_link_found_on_page(monkeypatch):
    monkeypatch.setattr("app.platforms.base.detect_platform", lambda url: (
        "swagit" if "swagit.com" in url else "unknown"
    ))
    monkeypatch.setattr("app.platforms.generic_fallback.get_finder", lambda platform: _FakeSwagitFinder())
    routes = {PAGE_URL: FakeResponse(status=200, text=PAGE_WITH_SWAGIT_LINK, url=PAGE_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(PAGE_URL)

    assert result.platform == "swagit"  # the delegated finder's own identity, unchanged
    assert result.video_url == "https://archive-stream.granicus.com/OnDemand/fake.mp4/playlist.m3u8"
    assert result.title == "Real City Council Meeting"
    # source_url stays the ORIGINAL page the visitor actually submitted,
    # not the swagit.com URL found on it -- matches how LIMS/PrimeGov
    # already preserve their own source_url through a YouTube delegation.
    assert result.source_url == PAGE_URL
    assert result.best_effort is True
    assert any("trying our best" in w for w in result.video_warnings)


async def test_resolve_does_not_delegate_to_a_bare_youtube_channel_link(monkeypatch):
    # Real false-positive confirmed live: Aurora, CO's footer has a "Watch
    # Us on YouTube" link straight to a channel page, not a specific video
    # -- detect_platform() would call this "youtube" too, but it's
    # deliberately excluded from the delegation scan since the narrower
    # _YOUTUBE_EMBED_RE regex (checked first) already owns real YouTube
    # video links specifically.
    page = """
    <html><body>
    <a href="https://www.youtube.com/user/somecitychannel">Watch Us on YouTube</a>
    </body></html>
    """
    routes = {PAGE_URL: FakeResponse(status=200, text=page, url=PAGE_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(PAGE_URL)

    assert result.platform == "unknown"
    assert result.video_url is None


async def test_resolve_falls_through_when_delegation_raises(monkeypatch):
    class _RaisingFinder:
        async def resolve(self, url):
            raise ValueError("simulated real failure")

    monkeypatch.setattr("app.platforms.base.detect_platform", lambda url: (
        "swagit" if "swagit.com" in url else "unknown"
    ))
    monkeypatch.setattr("app.platforms.generic_fallback.get_finder", lambda platform: _RaisingFinder())
    routes = {PAGE_URL: FakeResponse(status=200, text=PAGE_WITH_SWAGIT_LINK, url=PAGE_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(PAGE_URL)

    # Falls back to the honest "nothing found" outcome rather than crashing.
    assert result.platform == "unknown"
    assert result.video_url is None


async def test_resolve_backfills_title_and_jurisdiction_when_youtube_metadata_blocked(monkeypatch):
    # Real gap confirmed live 2026-08-13 (see BACKLOG.md): when yt-dlp is
    # blocked by YouTube's anti-bot check (the real, documented Render-IP
    # issue), the delegated YouTube result has no title/jurisdiction at
    # all -- this used to surface as a bare "Untitled meeting" even
    # though the page itself has everything needed. CRRMA's own <title>
    # ("Camino Real Regional Mobility Authority | El Paso, Texas") and
    # notice-of-meeting body paragraph ("CRRMA Board of Directors") are
    # both real, present on 5 confirmed real examples.
    def _raise(video_id):
        raise yt_dlp.utils.DownloadError("Sign in to confirm you're not a bot")

    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _raise)
    routes = {CRRMA_URL: FakeResponse(status=200, text=CRRMA_PAGE_HTML, url=CRRMA_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(CRRMA_URL)

    # User's own stated naming preference, 2026-08-13: "I'd expect it to
    # have CRRMA in there somewhere" -- the notice-block phrase wins over
    # the bare <title>-derived org name.
    assert result.title == "CRRMA Board of Directors"
    assert result.jurisdiction == "El Paso, Texas"
    assert result.date == "2025-11-12"
    # Playback itself is unaffected -- this is purely a metadata backfill.
    assert result.video_url == f"https://www.youtube.com/embed/{CRRMA_VIDEO_ID}"


async def test_resolve_does_not_backfill_title_over_a_real_youtube_title(monkeypatch):
    # Title backfill must never override a real title a delegated finder
    # DID find -- only fires when title is still empty.
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    routes = {CRRMA_URL: FakeResponse(status=200, text=CRRMA_PAGE_HTML, url=CRRMA_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(CRRMA_URL)

    assert result.title == "Some City Council Meeting"


async def test_resolve_overrides_youtube_uploader_jurisdiction_even_with_a_real_title(monkeypatch):
    # Real bug found live 2026-08-13, re-resolving the actual CRRMA page
    # (/m/meeting-732f78) once yt-dlp succeeded (unblocked from a
    # residential IP): YouTubeAssetFinder.resolve_video_id() unconditionally
    # sets jurisdiction=info.get("uploader") whenever it succeeds -- a
    # channel name ("Camino Real Regional Mobility Authority" here), not
    # a real jurisdiction, the same class of bug already fixed for
    # PrimeGov. Unlike title, jurisdiction backfill must fire regardless
    # of whether YouTube's own metadata call succeeded, since this
    # branch's only delegate is YouTubeAssetFinder and its uploader field
    # is never a trustworthy jurisdiction.
    def _fake_info(video_id):
        return {
            "title": "November 12, 2025 - CRRMA Board Meeting",
            "uploader": "Camino Real Regional Mobility Authority",
            "upload_date": "20251117",
        }

    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_info)
    routes = {CRRMA_URL: FakeResponse(status=200, text=CRRMA_PAGE_HTML, url=CRRMA_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(CRRMA_URL)

    # Real YouTube title wins (not overridden)...
    assert result.title == "November 12, 2025 - CRRMA Board Meeting"
    # ...but the uploader-derived "jurisdiction" is replaced with the
    # page's own real one.
    assert result.jurisdiction == "El Paso, Texas"


async def test_backfill_falls_back_to_bare_title_tag_org_name_without_a_notice_block():
    from app.platforms.generic_fallback import GenericFallbackAssetFinder as F
    from app.platforms.models import ResolvedMeeting

    html = "<html><head><title>Some Org | Somewhere, ST</title></head><body>No notice block here.</body></html>"
    resolved = ResolvedMeeting(platform="unknown", source_url=CRRMA_URL)

    F._backfill_metadata_from_page(resolved, html, CRRMA_URL)

    assert resolved.title == "Some Org"
    assert resolved.jurisdiction == "Somewhere, ST"


async def test_backfill_is_a_no_op_without_a_pipe_shaped_title():
    from app.platforms.generic_fallback import GenericFallbackAssetFinder as F
    from app.platforms.models import ResolvedMeeting

    html = "<html><head><title>Just A Plain Title</title></head><body>Nothing useful here.</body></html>"
    resolved = ResolvedMeeting(platform="unknown", source_url=CRRMA_URL)

    F._backfill_metadata_from_page(resolved, html, CRRMA_URL)

    assert resolved.title is None
    assert resolved.jurisdiction is None
    # The URL-path date still gets filled in independent of the title shape.
    assert resolved.date == "2025-11-12"


# Real page shape confirmed live 2026-08-13 via WebFetch on
# cityofsebastopol.gov/events/{slug}/ -- a WordPress "The Events
# Calendar" page, a different generic-fallback template family from
# CRRMA's <title>Org | Jurisdiction</title> shape above. Real <title>:
# "City Council Meeting January 6, 2026 - City of Sebastopol,
# California". See BACKLOG.md's "generic_fallback.py's YouTube-embed
# branch" entry.
SEBASTOPOL_URL = "https://www.cityofsebastopol.gov/events/city-council-meeting-january-6-2026/"
SEBASTOPOL_PAGE_HTML = """
<html><head><title>City Council Meeting January 6, 2026 - City of Sebastopol, California</title></head>
<body><p>No YouTube embed on this page -- the real video here is Vimeo, not yet supported.</p></body></html>
"""


async def test_backfill_handles_the_dash_separated_title_shape():
    from app.platforms.generic_fallback import GenericFallbackAssetFinder as F
    from app.platforms.models import ResolvedMeeting

    resolved = ResolvedMeeting(platform="unknown", source_url=SEBASTOPOL_URL)

    F._backfill_metadata_from_page(resolved, SEBASTOPOL_PAGE_HTML, SEBASTOPOL_URL)

    assert resolved.title == "City Council Meeting January 6, 2026"
    assert resolved.jurisdiction == "City of Sebastopol, California"


async def test_resolve_backfills_title_and_jurisdiction_from_dash_separated_title():
    # Full resolve()-level check: Sebastopol has no YouTube embed (the
    # real video is Vimeo, unsupported), so this exercises the plain
    # "no video found" fallback branch, not the YouTube-delegation branch
    # the CRRMA tests above cover.
    routes = {SEBASTOPOL_URL: FakeResponse(status=200, text=SEBASTOPOL_PAGE_HTML, url=SEBASTOPOL_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(SEBASTOPOL_URL)

    assert result.title == "City Council Meeting January 6, 2026"
    assert result.jurisdiction == "City of Sebastopol, California"
    assert result.video_url is None


async def test_backfill_does_not_split_on_a_hyphen_inside_the_meeting_name():
    # An early " - " that isn't the real org/jurisdiction boundary (e.g.
    # a meeting-type qualifier) shouldn't cause a wrong split -- the
    # greedy first group should backtrack to the LAST " - " in the title,
    # which is the one actually followed by a comma-shaped jurisdiction.
    from app.platforms.generic_fallback import GenericFallbackAssetFinder as F
    from app.platforms.models import ResolvedMeeting

    html = (
        "<html><head><title>Special Session - Budget Item - City of Somewhere, ST"
        "</title></head><body></body></html>"
    )
    resolved = ResolvedMeeting(platform="unknown", source_url=SEBASTOPOL_URL)

    F._backfill_metadata_from_page(resolved, html, SEBASTOPOL_URL)

    assert resolved.title == "Special Session - Budget Item"
    assert resolved.jurisdiction == "City of Somewhere, ST"


# Real vendor-generated `title` attribute confirmed live 2026-08-13 on
# Sacramento County's OnBase Agenda Online-family agenda link
# (agendanet.saccounty.gov) -- see BACKLOG.md's "Sacramento County, CA's
# own agenda site" entry. The page's own <title> tag is generic
# ("Sacramento County Board of Supervisors Meetings," no per-meeting
# text), so this is the only real per-meeting signal available.
SACRAMENTO_URL = "https://agendanet.saccounty.gov/BoardofSupervisors/Meetings/ViewMeeting?id=10231&doctype=1"
SACRAMENTO_PAGE_HTML = """
<html><head><title>Sacramento County Board of Supervisors Meetings</title></head>
<body>
<a href="/Documents/Downloadfile/BOARD_OF_SUPERVISORS_10231_Agenda_Packet_8_11_2026_9_30_00_AM.pdf"
   title="View Agenda Packet for BOARD OF SUPERVISORS BOARD OF SUPERVISORS MEETING on 8/11/2026 9:30:00 AM">
   Agenda
</a>
</body></html>
"""


def test_find_agenda_link_returns_the_matched_as_title_attribute():
    from app.platforms.generic_fallback import GenericFallbackAssetFinder as F

    link, title_attr = F._find_agenda_link(SACRAMENTO_PAGE_HTML, SACRAMENTO_URL)

    assert link.endswith("BOARD_OF_SUPERVISORS_10231_Agenda_Packet_8_11_2026_9_30_00_AM.pdf")
    assert title_attr == "View Agenda Packet for BOARD OF SUPERVISORS BOARD OF SUPERVISORS MEETING on 8/11/2026 9:30:00 AM"


async def test_resolve_backfills_title_and_date_from_the_agenda_links_title_attribute():
    routes = {SACRAMENTO_URL: FakeResponse(status=200, text=SACRAMENTO_PAGE_HTML, url=SACRAMENTO_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(SACRAMENTO_URL)

    # Real per-meeting title/date, not "Untitled meeting" -- but no
    # jurisdiction, since the agenda link's own title attribute never
    # names the county and the page's <title> tag is too generic to
    # backfill it from (see the module-level comment on
    # _AGENDA_LINK_TITLE_RE for why this is deliberately title/date only).
    assert result.title == "Board Of Supervisors Board Of Supervisors Meeting"
    assert result.date == "2026-08-11"
    assert result.jurisdiction is None
    assert result.agenda_link.endswith("BOARD_OF_SUPERVISORS_10231_Agenda_Packet_8_11_2026_9_30_00_AM.pdf")


async def test_agenda_link_title_backfill_never_overrides_an_already_found_title():
    # Pair the Sacramento-shaped agenda link with a real CRRMA-shaped
    # <title> tag on the same page -- the pipe-derived title must win,
    # since the agenda-link title/date backfill is guarded per-field by
    # "only fires when still empty," not an all-or-nothing switch. The
    # pipe title carries no date, so `date` legitimately still comes from
    # the agenda link here -- these two backfills aren't mutually
    # exclusive, just independently guarded.
    html = SACRAMENTO_PAGE_HTML.replace(
        "<title>Sacramento County Board of Supervisors Meetings</title>",
        "<title>Some Org | Somewhere, ST</title>",
    )
    routes = {SACRAMENTO_URL: FakeResponse(status=200, text=html, url=SACRAMENTO_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(SACRAMENTO_URL)

    assert result.title == "Some Org"
    assert result.jurisdiction == "Somewhere, ST"
    assert result.date == "2026-08-11"


# --- 2026-08-14 rebuild coverage (Phase 2: diagnose-and-route restructure;
# see BACKLOG_DONE.md). Fixtures are trimmed REAL captures -- source URL
# and capture date in each file's own header comment. ---

from conftest import load_fixture

TARRANT_URL = "https://agendamgmtprod.tarrantcountytx.gov/Meetings/GetHTMLAgenda?meetingId=&dataSource=&id=21849bbe-d099-4637-1560-08ddc611a5e2"
SEATTLE_URL = "https://www.seattlechannel.org/videos?videoid=x189286"
SEATTLE_SRT_URL = "https://www.seattlechannel.org/documents/seattlechannel/closedcaption/2026/council_081126_2022663.srt"
SACRAMENTO_ONBASE_URL = "https://agendanet.saccounty.gov/BoardofSupervisors/Meetings/ViewMeeting?id=10231&doctype=1"
OCFL_URL = "https://netapps.ocfl.net/Mod/meetings/1/2069"
OCFL_VTT_URL = "https://otv.ocfl.net/otv/BCC2026/BCC071626/BCC071626AA.vtt"

# Real cue shape (trimmed) -- enough for parse_captions_by_extension to
# yield real timed segments.
REAL_SRT_SAMPLE = """1
00:00:01,000 --> 00:00:04,000
I'll go ahead and call the meeting to order.

2
00:00:04,500 --> 00:00:07,000
Roll call, please.
"""
REAL_VTT_SAMPLE = """WEBVTT

00:00:01.000 --> 00:00:04.000
Good morning, this meeting of the Board is called to order.

00:00:04.500 --> 00:00:07.000
Thank you, Madam Chair.
"""


async def test_resolve_finds_tarrant_bare_video_id_and_heading_metadata(monkeypatch):
    # Tarrant County's real shape: `const videoId = 'Awrb74sMXyM';` next to
    # the youtube.com/iframe_api loader, with metadata only in <h1>s/<h4>s
    # (its <title> is the generic "Commissioners Court - Archived Agendas
    # and Videos"). yt-dlp mocked as blocked (the documented Render-IP
    # reality) so the page's own backfill is what's exercised.
    def _raise(video_id):
        raise yt_dlp.utils.DownloadError("Sign in to confirm you're not a bot")

    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _raise)
    html = load_fixture("generic_fallback", "tarrant_gethtmlagenda_21849bbe.html")
    routes = {TARRANT_URL: FakeResponse(status=200, text=html, url=TARRANT_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(TARRANT_URL)

    assert result.video_url == "https://www.youtube.com/embed/Awrb74sMXyM"
    assert result.video_format == "youtube"
    assert result.best_effort is True
    # Two sibling <h1>s assembled in document order.
    assert result.title == "Tarrant County Commissioners Court"
    # From the date <h4>; the address-only <h4> before it has no month
    # name and is correctly skipped.
    assert result.date == "2025-08-19"


def test_find_youtube_video_id_requires_iframe_api_corroboration():
    # A bare 11-char videoId assignment on a page that never loads the
    # IFrame Player API must NOT match -- the corroboration gate is the
    # wrong-video guard that makes shipping on one confirmed example
    # (Tarrant) acceptable.
    html = "<script>const videoId = 'Awrb74sMXyM';</script>"
    assert GenericFallbackAssetFinder._find_youtube_video_id(html) is None


def test_find_youtube_video_id_skips_ambiguous_bare_ids():
    html = (
        '<script src="https://www.youtube.com/iframe_api"></script>'
        "<script>var videoId = 'Awrb74sMXyM'; videoId = 'dQw4w9WgXcQ';</script>"
    )
    assert GenericFallbackAssetFinder._find_youtube_video_id(html) is None


def test_find_youtube_video_id_handles_nocookie_and_escaped_watch_urls():
    # Pure URL-shape variants of the already-confirmed patterns -- no
    # government page with either shape confirmed yet (2026-08-14), see
    # the module-level comments.
    assert (
        GenericFallbackAssetFinder._find_youtube_video_id(
            '<iframe src="https://www.youtube-nocookie.com/embed/Awrb74sMXyM"></iframe>'
        )
        == "Awrb74sMXyM"
    )
    assert (
        GenericFallbackAssetFinder._find_youtube_video_id(
            '<a href="https://www.youtube.com/watch?feature=share&amp;v=Awrb74sMXyM">watch</a>'
        )
        == "Awrb74sMXyM"
    )


async def test_resolve_finds_seattle_protocol_relative_mp4_and_relative_srt():
    # Seattle Channel's real /videos?videoid= shape: protocol-relative mp4
    # in the JW sources file:, relative-path srt in tracks file: (also a
    # plain <a href>), machine-readable video_date meta.
    html = load_fixture("generic_fallback", "seattle_videos_x189286.html")
    routes = {
        SEATTLE_URL: FakeResponse(status=200, text=html, url=SEATTLE_URL),
        SEATTLE_SRT_URL: FakeResponse(status=200, text=REAL_SRT_SAMPLE, url=SEATTLE_SRT_URL),
    }

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(SEATTLE_URL)

    assert result.video_url == "https://video.seattle.gov/media/council/council_081126_2022663.mp4"
    assert result.video_format == "mp4"
    assert len(result.segments) == 2
    assert "call the meeting to order" in result.segments[0].text
    assert result.date == "2026-08-11"


async def test_resolve_sacramento_onbase_m3u8_with_decoded_token():
    # End-to-end over the real trimmed capture: the JW playlist file: URL
    # carries &amp;token= in raw HTML; the resolved video_url must carry
    # the DECODED &token= or the CDN sees a bogus `amp;token` param.
    html = load_fixture("generic_fallback", "sacramento_viewmeeting_10231.html")
    routes = {SACRAMENTO_ONBASE_URL: FakeResponse(status=200, text=html, url=SACRAMENTO_ONBASE_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(SACRAMENTO_ONBASE_URL)

    assert result.video_format == "m3u8"
    assert "playlist.m3u8?instance=1&token=" in result.video_url
    assert "&amp;" not in result.video_url
    # The agenda-link title-attribute backfill still wins for title/date.
    assert result.title == "Board Of Supervisors Board Of Supervisors Meeting"
    assert result.date == "2026-08-11"


async def test_resolve_ocfl_multipart_picks_first_part_and_fetches_vtt():
    # OCFL's real video.js playlist: single-quoted src: mp4 parts AA/BB,
    # each with a matching textTracks vtt. Deterministic scan order must
    # pick part AA (document order), and the vtt candidates must be
    # fetched via the caption chain.
    html = load_fixture("generic_fallback", "ocfl_meetings_2069.html")
    routes = {
        OCFL_URL: FakeResponse(status=200, text=html, url=OCFL_URL),
        OCFL_VTT_URL: FakeResponse(status=200, text=REAL_VTT_SAMPLE, url=OCFL_VTT_URL),
    }

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(OCFL_URL)

    assert result.video_url == "https://otv.ocfl.net/otv/BCC2026/BCC071626/BCC071626AA.mp4"
    assert result.video_format == "mp4"
    assert len(result.segments) == 2
    assert "called to order" in result.segments[0].text


async def test_resolve_wayne_fixture_picks_video_link_not_channel_link(monkeypatch):
    # The Wayne County page carries BOTH the real youtu.be video link and
    # a "Subscribe on YouTube" CHANNEL link -- extraction must pick the
    # video. (The live page needs the headless escalation to fetch at all;
    # this exercises the diagnosis layer over the browser-captured HTML.)
    def _raise(video_id):
        raise yt_dlp.utils.DownloadError("blocked")

    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _raise)
    wayne_url = "https://www.waynecountymi.gov/Government/Elected-Officials/Commission/Committees/Full-Commission-Meetings/2026/Wayne-County-Commission-January-8-2026"
    html = load_fixture("generic_fallback", "wayne_county_commission_2026-01-08.html")
    routes = {wayne_url: FakeResponse(status=200, text=html, url=wayne_url)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(wayne_url)

    assert result.video_url == "https://www.youtube.com/embed/RFwXrAzkXR8"
    # og:title beats the h1 and the slug.
    assert result.title == "Wayne County Commission - January 8, 2026"
    # No ISO date anywhere on the page -- the trailing slug date fills in.
    assert result.date == "2026-01-08"
    assert result.agenda_link.endswith("agenda2026-0108.pdf")


# --- 2026-08-14 rebuild coverage (Phase 3: two-tier video pointer -- the
# user's explicit call: "the pointer where the video lives would be a
# GREAT outcome for the fallback page"). ---

SEBASTOPOL_EVENT_URL = "https://www.cityofsebastopol.gov/events/city-council-meeting-january-6-2026/"


async def test_resolve_surfaces_vimeo_pointer_as_recognized_video_link():
    # Sebastopol's real shape: the video is a plain <a href> to a Vimeo
    # page (numeric id + privacy hash, &#038; numeric entity in the query)
    # nothing can play -- must surface as a recognized-host pointer, and
    # NEVER enter video_url (a page URL there breaks the native player).
    html = load_fixture("generic_fallback", "sebastopol_event_page.html")
    routes = {SEBASTOPOL_EVENT_URL: FakeResponse(status=200, text=html, url=SEBASTOPOL_EVENT_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(SEBASTOPOL_EVENT_URL)

    assert result.video_url is None
    assert result.video_link == "https://vimeo.com/1152708575/db9859a2aa?fl=sm&fe=ec"
    assert result.video_link_recognized is True
    assert any("can't play it here yet" in w for w in result.video_warnings)
    # Metadata unaffected by the pointer path.
    assert result.title == "City Council Meeting January 6, 2026"
    assert result.jurisdiction == "City of Sebastopol, California"


def test_video_pointer_ignores_vimeo_channel_links():
    # A footer "watch us on Vimeo" channel link has no numeric video id --
    # the exact false-positive class the curated regex must exclude.
    html = '<a href="https://vimeo.com/cityofsomewhere">Follow us on Vimeo</a>'
    link, recognized = GenericFallbackAssetFinder._find_video_pointer(html, "https://city.gov/page")
    assert link is None


def test_video_pointer_loose_tier_matches_video_shaped_anchor_text():
    # Wayne County's real link text is exactly "Video" -- the shape that
    # motivated the loose tier. (On the real Wayne page the youtu.be href
    # is caught by the YouTube tier first; this synthetic variant uses an
    # unplayable host to exercise the loose tier alone, and the anchored
    # match means a sentence mentioning video never fires.)
    html = (
        '<a href="https://videoplayer.example-cdn.com/meeting/123">Video</a>'
        "<p>Read the video policy update from last video meeting here.</p>"
    )
    link, recognized = GenericFallbackAssetFinder._find_video_pointer(html, "https://city.gov/page")
    assert link == "https://videoplayer.example-cdn.com/meeting/123"
    assert recognized is False


def test_video_pointer_iframe_tier_skips_junk_hosts():
    # GTM iframe is OCFL's real page furniture; a third-party player
    # iframe is the real signal.
    html = (
        '<iframe src="https://www.googletagmanager.com/ns.html?id=GTM-X"></iframe>'
        '<iframe src="https://player.example-vendor.com/embed/456"></iframe>'
    )
    link, recognized = GenericFallbackAssetFinder._find_video_pointer(html, "https://city.gov/page")
    assert link == "https://player.example-vendor.com/embed/456"
    assert recognized is False


async def test_resolve_prefers_playable_video_over_pointer():
    # The pointer is tier 5 -- a page with BOTH a playable m3u8 and a
    # vimeo link must play the m3u8 and leave the pointer empty.
    html = (
        '<video src="https://cdn.city.gov/videos/meeting.m3u8"></video>'
        '<a href="https://vimeo.com/123456789">Watch</a>'
    )
    routes = {PAGE_URL: FakeResponse(status=200, text=html, url=PAGE_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(PAGE_URL)

    assert result.video_url == "https://cdn.city.gov/videos/meeting.m3u8"
    assert result.video_link is None


# --- 2026-08-14 rebuild coverage (Phase 5: headless escalation, env-gated
# OFF by default -- playwright-on-Render is still unverified, see
# render.yaml's own comments). ---

WAYNE_URL = "https://www.waynecountymi.gov/Government/Elected-Officials/Commission/Committees/Full-Commission-Meetings/2026/Wayne-County-Commission-January-8-2026"


async def test_escalation_disabled_by_default_browser_never_called(monkeypatch):
    # With the env var unset (the shipped default), a real Akamai 403 must
    # degrade to today's exact behavior -- and the browser must never be
    # touched.
    monkeypatch.delenv("GENERIC_FALLBACK_HEADLESS", raising=False)
    calls = []

    async def _fake_browser(url):
        calls.append(url)
        return "<html>should never be used</html>"

    monkeypatch.setattr(GenericFallbackAssetFinder, "_try_browser_fetch", staticmethod(_fake_browser))
    akamai_403 = load_fixture("generic_fallback", "wayne_akamai_403.html")
    routes = {WAYNE_URL: FakeResponse(status=403, text=akamai_403, url=WAYNE_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(WAYNE_URL)

    assert calls == []
    assert result.video_url is None
    assert any("couldn't even load the page" in w for w in result.video_warnings)


async def test_escalation_resolves_wayne_county_through_the_browser(monkeypatch):
    # Trigger (a): the real Akamai 403 -> browser fetch -> the real
    # browser-captured Wayne page resolves fully (youtu.be video, agenda
    # pdf, og:title, slug date).
    def _raise(video_id):
        raise yt_dlp.utils.DownloadError("blocked")

    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _raise)
    monkeypatch.setenv("GENERIC_FALLBACK_HEADLESS", "1")
    wayne_html = load_fixture("generic_fallback", "wayne_county_commission_2026-01-08.html")

    async def _fake_browser(url):
        assert url == WAYNE_URL
        return wayne_html

    monkeypatch.setattr(GenericFallbackAssetFinder, "_try_browser_fetch", staticmethod(_fake_browser))
    akamai_403 = load_fixture("generic_fallback", "wayne_akamai_403.html")
    routes = {WAYNE_URL: FakeResponse(status=403, text=akamai_403, url=WAYNE_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(WAYNE_URL)

    assert result.video_url == "https://www.youtube.com/embed/RFwXrAzkXR8"
    assert result.title == "Wayne County Commission - January 8, 2026"
    assert result.date == "2026-01-08"
    assert result.agenda_link.endswith("agenda2026-0108.pdf")


async def test_escalation_degrades_cleanly_when_browser_unavailable(monkeypatch):
    # HeadlessBrowserUnavailable (or any browser failure) must fall back
    # to today's clean unreachable-page message, never a crash -- this is
    # the first caller anywhere that has to survive a missing browser.
    monkeypatch.setenv("GENERIC_FALLBACK_HEADLESS", "1")

    async def _unavailable(url):
        return None  # _try_browser_fetch already swallows the exception

    monkeypatch.setattr(GenericFallbackAssetFinder, "_try_browser_fetch", staticmethod(_unavailable))
    akamai_403 = load_fixture("generic_fallback", "wayne_akamai_403.html")
    routes = {WAYNE_URL: FakeResponse(status=403, text=akamai_403, url=WAYNE_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(WAYNE_URL)

    assert result.video_url is None
    assert any("couldn't even load the page" in w for w in result.video_warnings)


async def test_empty_shell_trigger_fires_on_real_tucson_shape(monkeypatch):
    # Trigger (c): a 200 with zero evidence and near-empty visible text
    # (the real Tucson Hyland client-rendered shell, 153 chars of visible
    # text) -> one browser attempt, whose rendered HTML is re-diagnosed.
    monkeypatch.setenv("GENERIC_FALLBACK_HEADLESS", "1")
    tucson_url = "https://tucsonaz.hylandcloud.com/221agendaonline/Meetings/ViewMeeting?doctype=2&id=1956"
    shell = load_fixture("generic_fallback", "tucson_viewmeeting_1956.html")
    rendered = (
        "<html><head><title>Mayor and Council Regular Meeting - City of Tucson, Arizona"
        "</title></head><body><video src='https://example-cdn.gov/tucson/meeting.mp4'></video></body></html>"
    )

    async def _fake_browser(url):
        return rendered

    monkeypatch.setattr(GenericFallbackAssetFinder, "_try_browser_fetch", staticmethod(_fake_browser))
    routes = {tucson_url: FakeResponse(status=200, text=shell, url=tucson_url)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(tucson_url)

    assert result.video_url == "https://example-cdn.gov/tucson/meeting.mp4"


async def test_empty_shell_trigger_skips_pages_with_real_text(monkeypatch):
    # A normal text-bearing page with no video must NOT pay a browser
    # fetch even with the flag on -- the visible-text gate.
    monkeypatch.setenv("GENERIC_FALLBACK_HEADLESS", "1")
    calls = []

    async def _fake_browser(url):
        calls.append(url)
        return "<html>never</html>"

    monkeypatch.setattr(GenericFallbackAssetFinder, "_try_browser_fetch", staticmethod(_fake_browser))
    texty = "<html><body>" + ("This council discussed real business. " * 30) + "</body></html>"
    routes = {PAGE_URL: FakeResponse(status=200, text=texty, url=PAGE_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(PAGE_URL)

    assert calls == []
    assert result.video_url is None
