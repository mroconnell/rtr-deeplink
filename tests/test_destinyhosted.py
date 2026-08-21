"""Tests for Destiny AgendaQuick (app/platforms/destinyhosted.py).

Real shapes confirmed live 2026-08-21 across 61 real destinyhosted.com
tenants (enumerated via Wayback CDX -- see BACKLOG_DONE.md): it's a pure
agenda/minutes CMS, not a video host -- video, when present, is almost
always an already-supported platform (mostly Swagit) linked via
`onclick="swagitPlay('https://...')"`, never a literal href.
"""

from app.platforms.base import register
from app.platforms.destinyhosted import DestinyHostedAssetFinder
from app.platforms.swagit import SwagitAssetFinder

from aiohttp_mock import FakeResponse, mock_session


def _register_swagit():
    # resolve_via_platform()/find_platform_link() delegation looks up the
    # registered finder by platform name -- register the real
    # SwagitAssetFinder so delegation exercises real parsing, not a stub.
    register(SwagitAssetFinder())


PAGE_URL = (
    "https://public.destinyhosted.com/agenda_publish.cfm"
    "?id=96635&mt=ALL&get_month=8&get_year=2026&dsp=ag&seq=4147"
)
SWAGIT_URL = "https://woodlandstx.new.swagit.com/videos/396312"

# Real shape (The Woodlands Township, TX, id=96635): the video link is a
# `href="#"` paired with an onclick handler, never a plain href.
PAGE_HTML = (
    "<html><body>"
    '<a href="https://public.destinyhosted.com/agenda_publish.cfm?id=96635&get_month=7">'
    "Prev month</a>"
    '<a href="#" aria-label="Play video" '
    f"onclick=\"swagitPlay('{SWAGIT_URL}'); return false;\">Video</a>"
    "</body></html>"
)

SWAGIT_HTML = (
    "<html><head><title>Aug 17, 2026 Budget Workshop #1 - The Woodlands Township, TX</title></head>"
    "<body>"
    '<script>var playlist = [{"file": "https://archive-stream.granicus.com/x/playlist.m3u8"}];</script>'
    "</body></html>"
)


async def test_resolve_delegates_through_onclick_swagit_link():
    _register_swagit()
    routes = {
        PAGE_URL: FakeResponse(status=200, text=PAGE_HTML, url=PAGE_URL),
        SWAGIT_URL: FakeResponse(status=200, text=SWAGIT_HTML, url=SWAGIT_URL),
    }

    with mock_session(routes):
        result = await DestinyHostedAssetFinder().resolve(PAGE_URL)

    # A successful inner delegation's own platform identity ("swagit")
    # must survive -- never masked by this wrapper's own "destinyhosted".
    assert result.platform == "swagit"
    assert result.video_url == "https://archive-stream.granicus.com/x/playlist.m3u8"


async def test_resolve_reports_its_own_platform_when_no_video_found():
    # A real, honest per-tenant negative (e.g. Knox County TN, Roswell NM)
    # -- no video link on the page at all, same-platform pagination link
    # aside.
    html = (
        "<html><body>"
        '<a href="https://public.destinyhosted.com/agenda_publish.cfm?id=56691&get_month=7">'
        "Prev month</a>"
        "</body></html>"
    )
    url = "https://public.destinyhosted.com/agenda_publish.cfm?id=56691"
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await DestinyHostedAssetFinder().resolve(url)

    assert result.platform == "destinyhosted"
    assert result.video_url is None
