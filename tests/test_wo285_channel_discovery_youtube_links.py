"""WO-285 (2026-09-12): WO-271's own 34-government "front-page YouTube
mention, no channel classified" list (rtr-business/research/
wo271_discovery.csv, front_page_youtube_link=True and blank
channel_urls). The entry guessed the likely cause was a youtube-
nocookie.com embed the classifier couldn't see -- checked 12 real
governments from that list building this fix: none had an actual
youtube-nocookie.com link anywhere (every "youtube-nocookie" mention was
the youtube-embed-plus WordPress plugin's own generic boilerplate JS,
never a populated embed). The REAL, confirmed, common shape across 6 of
the 12: a real youtube.com/youtu.be URL sitting inside an inline
<script> JSON config (a video-embed plugin's per-post settings),
JSON-escaped (`https:\\/\\/...`) and HTML-entity-escaped (`&quot;`) --
never inside any <a>/<iframe>/<video>/<source> tag `find_youtube_links()`
scanned before this fix.

Fixtures below are the real front pages fetched live 2026-09-12:
McCracken County, KY (a bare `youtu.be` URL) and South Connellsville
borough, PA (both a `watch?v=` and an `embed/` URL for the same video).
Same fix applied identically to all three duplicate copies of
`find_youtube_links()`/`classify_youtube_url()`
(scripts/wo235_channel_pilot.py, scripts/wo247_channel_band.py,
scripts/wo252_channel_band.py) -- this test parametrizes over all three
to confirm none were missed.
"""

import importlib

import pytest

from conftest import load_fixture

MODULE_NAMES = [
    "scripts.wo235_channel_pilot",
    "scripts.wo247_channel_band",
    "scripts.wo252_channel_band",
]


@pytest.mark.parametrize("module_name", MODULE_NAMES)
def test_finds_real_youtu_be_url_hidden_in_json_escaped_script_config(module_name):
    mod = importlib.import_module(module_name)
    html = load_fixture("wo285_channel_discovery", "mccrackencountyky.html")

    links = mod.find_youtube_links(html, "https://mccrackencountyky.gov")

    assert links == [("video", "https://youtu.be/7w68XqgThU8")]


@pytest.mark.parametrize("module_name", MODULE_NAMES)
def test_finds_real_watch_and_embed_urls_hidden_in_json_escaped_script_config(
    module_name,
):
    mod = importlib.import_module(module_name)
    html = load_fixture("wo285_channel_discovery", "southconnellsvilleboroughpa.html")

    links = mod.find_youtube_links(html, "https://www.southconnellsvilleboroughpa.com")

    assert (
        "video",
        "https://www.youtube.com/watch?v=9uOETcuFjbE",
    ) in links
    assert any(
        kind == "video" and url.startswith("https://www.youtube.com/embed/9uOETcuFjbE")
        for kind, url in links
    )


@pytest.mark.parametrize("module_name", MODULE_NAMES)
def test_classify_youtube_url_accepts_nocookie_domain(module_name):
    # WO-271's own original hypothesis -- unconfirmed on any of the 12
    # real pages checked, but cheap and safe to accept for defense in
    # depth (see find_youtube_links()'s own module-level comment).
    mod = importlib.import_module(module_name)

    assert (
        mod.classify_youtube_url("https://www.youtube-nocookie.com/embed/abc12345678")
        == "video"
    )
    assert (
        mod.classify_youtube_url("https://www.youtube-nocookie.com/channel/UCabc123")
        == "channel"
    )


@pytest.mark.parametrize("module_name", MODULE_NAMES)
def test_classify_youtube_url_accepts_plain_embed_shape_too(module_name):
    # Real gap independent of nocookie: no pattern here matched a plain
    # youtube.com `/embed/{id}` URL before this fix either.
    mod = importlib.import_module(module_name)

    assert (
        mod.classify_youtube_url("https://www.youtube.com/embed/dQw4w9WgXcQ") == "video"
    )


@pytest.mark.parametrize("module_name", MODULE_NAMES)
def test_plugin_boilerplate_js_is_not_misread_as_a_real_link(module_name):
    # The negative control this fix must not break: the youtube-embed-plus
    # WordPress plugin's own generic script mentions both domains as
    # config defaults -- but always as a fragment of ITS OWN asset path
    # on the government's own domain, never a real youtube.com/youtu.be
    # URL. Confirmed real on McCracken County, KY's fixture above: this
    # plugin boilerplate sits right next to the one real youtu.be link,
    # and must not itself produce a second, spurious link.
    mod = importlib.import_module(module_name)
    html = load_fixture("wo285_channel_discovery", "mccrackencountyky.html")

    links = mod.find_youtube_links(html, "https://mccrackencountyky.gov")

    assert len(links) == 1
