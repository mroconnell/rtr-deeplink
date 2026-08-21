"""Tests for open.media (app/platforms/openmedia.py), WO-18.

Real pages fetched live 2026-08-21 across 7 real tenant subdomains
(Goodyear AZ, Eugene OR, Cortez CO, Santa Barbara CA, Surprise AZ,
Georgetown CO, Pitkin County CO) -- see openmedia.py's own module
docstring for the full investigation. Fixtures saved from 4 of these
(goodyearaz, eugene, cortez, pitkincounty -- the last one specifically to
pin down a real county-government tenant and its own
`jurisdiction_enrich` interaction, see the dedicated test below); the
other 3 were spot-checked live during development but not saved as
fixtures here (all confirmed the same shape, no new branch of logic to
cover).

open.media fronts requests with a UA-based bot check (a bare/default UA
403s live; a modern desktop Chrome UA gets a clean 200) -- irrelevant to
these tests themselves (mock_session intercepts session.get() before any
network call happens), but is why OpenMediaAssetFinder's own `_fetch()`
sets a modern UA header, mirroring generic_fallback.py's own
cityofsebastopol.gov fix.
"""

import pytest

from app.platforms.base import detect_platform
from app.platforms.openmedia import OpenMediaAssetFinder
from app.platforms.youtube import YouTubeAssetFinder
from app.utils import url_guard

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture


@pytest.fixture(autouse=True)
def _fake_public_dns(monkeypatch):
    """See test_generic_fallback.py's identical fixture for why this is
    needed: OpenMediaAssetFinder._fetch() goes through url_guard's
    guarded_get(), which resolves the hostname for real unless patched --
    the fixture hostnames below are real, but never actually fetched in a
    test (mock_session intercepts session.get() first), so DNS must never
    really run here either."""
    monkeypatch.setattr(
        url_guard, "_resolve_hostname", lambda hostname: ["93.184.216.34"]
    )


GOODYEAR_URL = "https://goodyearaz.open.media/sessions/346555"
EUGENE_URL = (
    "https://eugene.open.media/sessions/344982/city-council-work-session-july-15-2026"
)
CORTEZ_URL = (
    "https://cortez.open.media/sessions/346252/city-council-meeting-august-11-2026"
)

GOODYEAR_VIDEO_ID = "OU-H69iuvLU"
EUGENE_VIDEO_ID = "LBLSy4Rk3GU"
CORTEZ_VIDEO_ID = "6ROsD8-iMk0"


def _fake_extract_info(video_id):
    # Real yt-dlp metadata is deliberately NOT relied on for title here --
    # og:title is the real, page-native signal OpenMediaAssetFinder
    # prefers (see openmedia.py's own docstring) -- but resolve_video_id()
    # still needs *some* info dict back to build segments/date, so this
    # supplies a deliberately-wrong uploader ("Some Channel") to prove the
    # jurisdiction override below is real and not accidental.
    return {
        "title": "some yt-dlp title, should be overridden",
        "uploader": "Some Channel",
        "upload_date": "20260101",
        "release_date": None,
    }


def test_detect_platform_recognizes_open_media_domain():
    assert detect_platform(GOODYEAR_URL) == "open_media"
    assert detect_platform(EUGENE_URL) == "open_media"


async def test_resolve_real_goodyear_meeting(monkeypatch):
    # Real, confirmed live 2026-08-21: the video is NOT present as a
    # server-rendered <iframe src="youtube.com/embed/..."> (the visible
    # player iframe is injected client-side) -- what IS present in the
    # raw HTML is an <meta property="og:video" content="https://
    # www.youtube.com/v/{id}"> tag, which YouTubeAssetFinder's own regex
    # already recognizes via its "v/" alternative.
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    html = load_fixture("openmedia", "goodyearaz_session_346555.html")

    routes = {GOODYEAR_URL: FakeResponse(status=200, text=html, url=GOODYEAR_URL)}
    with mock_session(routes):
        result = await OpenMediaAssetFinder().resolve(GOODYEAR_URL)

    assert result.platform == "youtube"
    assert result.source_url == GOODYEAR_URL
    assert result.external_id == "open_media:goodyearaz.open.media:346555"
    assert result.video_url == f"https://www.youtube.com/embed/{GOODYEAR_VIDEO_ID}"
    # og:title, not yt-dlp's own (possibly-blocked, possibly-noisier) title.
    assert result.title == "Planning & Zoning Commission - 08/19/2026"
    # <title> shape here is "{Jurisdiction} | {Meeting title}" -- the
    # REVERSE order from generic_fallback.py's own CRRMA-shaped
    # _TITLE_TAG_PIPE_RE. Confirms jurisdiction is read from the correct
    # half, not swapped with the title the way it would be if this reused
    # that regex's group assignment.
    assert result.jurisdiction == "City of Goodyear, Arizona"
    # The agenda iframe (id="document") here is a direct link to another
    # already-registered platform (destinyhosted.com AgendaQuick) -- kept
    # as-is, not further resolved.
    assert result.agenda_link == (
        "https://public.destinyhosted.com/agenda_publish.cfm"
        "?id=46639&mt=ALL&get_month=8&get_year=2026&dsp=ag&seq=2286"
    )


async def test_resolve_real_eugene_meeting_unwraps_pdfjs_agenda_link(monkeypatch):
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    html = load_fixture("openmedia", "eugene_session_344982.html")

    routes = {EUGENE_URL: FakeResponse(status=200, text=html, url=EUGENE_URL)}
    with mock_session(routes):
        result = await OpenMediaAssetFinder().resolve(EUGENE_URL)

    assert result.video_url == f"https://www.youtube.com/embed/{EUGENE_VIDEO_ID}"
    assert result.title == "City Council Work Session: July 15, 2026"
    # "Eugene, OR" already carries a state suffix from the page's own
    # <title> tag -- enrich_jurisdiction_text() leaves an already-comma'd
    # jurisdiction untouched.
    assert result.jurisdiction == "Eugene, OR"
    # Eugene's agenda iframe (id="document") is this tenant's own pdf.js
    # viewer wrapping a direct S3 PDF as its ?file= query param -- the raw
    # PDF URL is unwrapped, not the pdf.js viewer page itself.
    assert result.agenda_link == (
        "https://ompnetwork.s3-us-west-2.amazonaws.com/sites/134/documents/"
        "cc_agenda_packet_260715_ws_-_post_amended.pdf"
        "?NtSM8czQVdI8T8k7CKSMTtTyjJlBvawf"
    )


async def test_resolve_falls_back_to_subdomain_when_title_is_vendor_default(
    monkeypatch,
):
    # Real, confirmed live 2026-08-21: cortez.open.media has never
    # customized its <title> tag away from the vendor's own default
    # ("Cortez Open.Media Software | ..."), unlike every other tenant
    # checked -- using the pre-pipe half here as a jurisdiction the way
    # Goodyear/Eugene's title does would store "Cortez Open.Media
    # Software", not a real jurisdiction. Falls back to the validated
    # tenant-subdomain extraction (same mechanism eScribe/Granicus already
    # use) instead.
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    html = load_fixture("openmedia", "cortez_session_346252.html")

    routes = {CORTEZ_URL: FakeResponse(status=200, text=html, url=CORTEZ_URL)}
    with mock_session(routes):
        result = await OpenMediaAssetFinder().resolve(CORTEZ_URL)

    assert result.video_url == f"https://www.youtube.com/embed/{CORTEZ_VIDEO_ID}"
    assert result.title == "City Council Meeting August 11, 2026"
    assert result.jurisdiction == "Cortez, CO"


async def test_resolve_real_pitkin_county_meeting_customized_title_avoids_subdomain_gap(
    monkeypatch,
):
    # Real, confirmed live 2026-08-21: Pitkin County, CO is a real county
    # government tenant whose bare subdomain label ("pitkincounty") is the
    # one case, among every known tenant subdomain, where
    # jurisdiction_enrich.validated_label_extract() fails to validate (it
    # only strips a LEADING "county"/"town"/etc. connector word, not a
    # trailing one). That gap turns out not to matter here: Pitkin
    # County's real session pages carry a properly customized <title>
    # ("Pitkin County | {meeting title}"), so the subdomain fallback is
    # never actually reached -- this pins that down with a real fixture
    # rather than leaving it as an assumption.
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    url = "https://pitkincounty.open.media/sessions/334458"
    html = load_fixture("openmedia", "pitkincounty_session_334458.html")

    routes = {url: FakeResponse(status=200, text=html, url=url)}
    with mock_session(routes):
        result = await OpenMediaAssetFinder().resolve(url)

    assert result.video_url == "https://www.youtube.com/embed/IA0WzfUItOs"
    assert result.title == "City Council Work Session February 10, 2026"
    assert result.jurisdiction == "Pitkin County, CO"


async def test_resolve_reports_no_video_when_none_found():
    url = "https://example-town.open.media/sessions/1"
    html = "<html><head><title>Example Town | Some Meeting</title></head><body></body></html>"

    routes = {url: FakeResponse(status=200, text=html, url=url)}
    with mock_session(routes):
        result = await OpenMediaAssetFinder().resolve(url)

    assert result.platform == "open_media"
    assert result.video_url is None
    assert result.video_warnings == ["No video found for this open.media session."]


async def test_resolve_reports_load_failure():
    url = "https://example-town.open.media/sessions/1"
    routes = {url: FakeResponse(status=403, text="blocked", url=url)}

    with mock_session(routes):
        result = await OpenMediaAssetFinder().resolve(url)

    assert result.platform == "open_media"
    assert result.video_warnings == [
        "Could not load this open.media page -- it may be temporarily unreachable."
    ]


def test_find_agenda_link_ignores_empty_interactive_html_iframe():
    html = (
        '<html><body><div id="region-agenda">'
        '<iframe id="document" src="https://public.destinyhosted.com/x.cfm?id=1"></iframe>'
        '<iframe id="interactive-html-agenda" src="" style="display:none"></iframe>'
        "</div></body></html>"
    )
    assert OpenMediaAssetFinder._find_agenda_link(
        html, "https://x.open.media/sessions/1"
    ) == ("https://public.destinyhosted.com/x.cfm?id=1")


def test_find_agenda_link_returns_none_when_no_document_iframe():
    html = "<html><body>No agenda here.</body></html>"
    assert (
        OpenMediaAssetFinder._find_agenda_link(html, "https://x.open.media/sessions/1")
        is None
    )
