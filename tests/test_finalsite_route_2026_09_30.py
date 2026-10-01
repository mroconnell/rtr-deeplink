"""Finalsite routing (2026-09-30): challenge page detection, Wayback
fallback, hop ranking on opaque `/fs/pages/N` paths, and site-builder tag.

Fixtures are real pages fetched 2026-09-30 (tests/fixtures/finalsite/README.md).
"""

from __future__ import annotations

import json

from aiohttp import web
from aiohttp.test_utils import TestServer

from app.platforms.meeting_finder import fetch as fetch_module
from app.platforms.meeting_finder.fetch import Fetcher, FetchResult
from app.platforms.meeting_finder.hop import rank_hops
from scripts.challenge_markers import is_challenge
from scripts.cms_fingerprint import classify
from tests.conftest import load_fixture

CHALLENGE = load_fixture("finalsite", "client_challenge_nassau_k12_fl_us.html")
HOME = load_fixture("finalsite", "home_isd623_org.html")
BASE = "https://www.exampleusd.org/"


def _page(html: str, url: str = BASE) -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        status=200,
        html=html,
        access_mode="plain",
        outcome=None,
        challenge=False,
        wayback_timestamp=None,
        links_only=False,
        elapsed_ms=0,
    )


# ---- (a) challenge detection and fallback ------------------------------


def test_real_client_challenge_page_is_a_challenge():
    assert is_challenge(CHALLENGE)


def test_real_finalsite_homepage_is_not_a_challenge():
    assert not is_challenge(HOME)


def test_plain_page_titled_client_challenge_text_alone_is_not_enough():
    assert not is_challenge("<p>Our Client Challenge program</p>")


async def test_finalsite_challenge_falls_back_to_wayback_links_only(monkeypatch):
    async def gated(request):
        return web.Response(text=CHALLENGE, status=200, content_type="text/html")

    app = web.Application()
    app.router.add_get("/", gated)
    server = TestServer(app)
    await server.start_server()

    class _Cdx:
        text = json.dumps(
            [["original", "timestamp"], ["https://x.example/", "20260501000000"]]
        )

    monkeypatch.setattr(fetch_module, "cdx_get", lambda url: _Cdx())
    monkeypatch.setattr(
        fetch_module,
        "wayback_id_read",
        lambda url, ts: b'<a href="/fs/pages/688">Board of Education</a>',
    )
    fetcher = Fetcher(per_host_delay_s=0)
    try:
        result = await fetcher.fetch(str(server.make_url("/")))
    finally:
        await fetcher.aclose()
        await server.close()
    assert result.challenge is True
    assert result.access_mode == "wayback"
    assert result.links_only is True
    assert "/fs/pages/688" in (result.html or "")


async def test_wayback_skips_a_capture_that_is_itself_the_challenge_page(monkeypatch):
    class _Cdx:
        text = json.dumps(
            [
                ["original", "timestamp"],
                ["https://x.example/", "20260601000000"],
                ["https://x.example/", "20260401000000"],
            ]
        )

    reads = []

    def fake_read(url, ts):
        reads.append(ts)
        if ts == "20260601000000":
            return CHALLENGE.encode()
        return b'<a href="/fs/pages/688">Board of Education</a>'

    monkeypatch.setattr(fetch_module, "cdx_get", lambda url: _Cdx())
    monkeypatch.setattr(fetch_module, "wayback_id_read", fake_read)
    fetcher = Fetcher(per_host_delay_s=0)
    try:
        html, ts = await fetcher._wayback_latest("https://x.example/")
    finally:
        await fetcher.aclose()
    assert reads == ["20260601000000", "20260401000000"]
    assert ts == "20260401000000"
    assert "/fs/pages/688" in html


# ---- (b) hop ranking on Finalsite shapes -------------------------------


def _urls(html: str, **kw) -> list[str]:
    return [h.url for h in rank_hops(_page(html), limit=50, school=True, **kw)]


def test_fs_pages_anchor_only_links_are_rescued_and_ranked():
    html = """<nav><a href="/fs/pages/2">About</a>
    <a href="/fs/pages/688">Board of Education</a>
    <a href="/fs/pages/690">Board Meetings</a>
    <a href="/fs/pages/691">Watch Meeting Recordings</a>
    <a href="/fs/pages/5">Lunch Menus</a></nav>"""
    urls = _urls(html)
    for n in ("688", "690", "691"):
        assert BASE + f"fs/pages/{n}" in urls
    assert urls.index(BASE + "fs/pages/690") < urls.index(BASE + "fs/pages/688")
    assert BASE + "fs/pages/5" not in urls[:3]


def test_finalsite_subsite_path_with_anchor_text_is_ranked():
    html = """<a href="/district/exampleusd/board-docs-17">Board Meetings</a>
    <a href="/district/exampleusd/lunch-9">Lunch</a>"""
    assert _urls(html)[0] == BASE + "district/exampleusd/board-docs-17"


def test_resources_finalsite_net_links_are_never_candidates():
    files = [
        "https://resources.finalsite.net/images/v1/site/abc/board-meetings.jpg",
        "https://resources.finalsite.net/images/f_auto,q_auto/v1/site/abc/meeting",
        "https://resources.finalsite.net/videos/t_video_mp4_1080/v1/site/x/board-meeting.mp4",
        "https://resources.finalsite.net/documents/v1/site/agenda-and-minutes",
    ]
    html = (
        "".join(f'<a href="{u}">Board Meetings Agenda and Minutes</a>' for u in files)
        + "".join(f'<img src="{u}">' for u in files)
        + f'<video><source src="{files[2]}"></video>'
        + '<a href="/fs/pages/9">Board Meetings</a>'
    )
    urls = _urls(html)
    assert not [u for u in urls if "finalsite.net" in u]
    assert BASE + "fs/pages/9" in urls


def test_real_finalsite_homepage_ranks_board_meetings_and_no_resource_links():
    url = "https://www.isd623.org/"
    hops = rank_hops(_page(HOME, url), limit=8, school=True)
    assert hops
    assert not [h for h in hops if "finalsite.net" in h.url]
    assert any("school-board" in h.url for h in hops[:3])


# ---- site-builder tag ---------------------------------------------------


def test_real_finalsite_homepage_is_tagged_finalsite():
    result = classify(HOME, url="https://www.isd623.org/")
    assert result.family == "finalsite"


def test_challenge_page_is_not_tagged_finalsite():
    # Unverified which builder is behind it (nassau's archived copy was Apptegy).
    assert classify(CHALLENGE, url="https://www.nassau.k12.fl.us/").family == "unknown"


def test_fs_pages_path_alone_tags_finalsite():
    assert classify('<a href="/fs/pages/688">x</a>').family == "finalsite"
