"""Tests for the generic "unknown platform" fallback (built 2026-08-09,
directly from the user's own request: try our best instead of a flat
"we don't support this yet"). Registered under platform_name="unknown",
the exact string detect_platform() returns for anything unmatched.
"""

import yt_dlp

from app.platforms.generic_fallback import GenericFallbackAssetFinder
from app.platforms.youtube import YouTubeAssetFinder

from aiohttp_mock import FakeResponse, mock_session

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
