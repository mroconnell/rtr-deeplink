"""Tests for WO-904: `run_access_ladder()` (scripts/wo147_access_ladder_
sweep.py) no longer stops the moment `find_platform_link()` finds ANY
vendor-shaped link on a homepage -- it now checks whether that hit looks
decorative (`_is_decorative_hit()`, a URL-parameter/filename signature)
and, if so, keeps climbing (a hop link, then headless) instead of
accepting it, the same rungs it already climbs when no link is found at
all. See BACKLOG_DONE.md's WO-904 entry (originally BACKLOG.md's
"run_access_ladder() stops climbing" entry, WO-361/WO-364/WO-368) for the
full incident history this fixes.

Real, live-confirmed incidents this is fixing (named in that entry):
Garfield city NJ's "City of Garfield 2024" (a production-company reel),
a "Welcome To Liberty"/"Town of Warrenton" town intro reel, Inverness
County NS's "Canada's Musical Coast" tourism-board video, a Stantec
engineering firm's own "Port Wing Restoration Site" project video, a
"Clean Water: A Long Journey from the Source to Our Tap" documentary, and
an "Around MIAMI Township with Eric Ferry" local-interest series episode
-- WO-364 confirmed every one of these by its real oEmbed title, which is
exactly why they carry NO recognizable URL signature (a title is not
visible in a URL) and are used below as the "no signature, correctly not
guessed" case, not the "has a signature" one.

Per CLAUDE.md's synthetic-test rule, every HTML fixture below is
hand-built (SYNTHETIC), not fetched from a real page -- but built two
ways depending on what's actually independently checkable from this
repo:

- `test_decorative_hit_with_no_url_signature_*` names the real government
  (Garfield city, NJ) and its real, confirmed oEmbed title ("City of
  Garfield 2024" -- see scripts/wo364_handread.py's own docstring, which
  quotes it) but constructs the surrounding page/domain, since the real
  captured HTML lives in `~/Documents/rtr-business/research/` and isn't
  reachable from here. The one fact this test actually depends on -- a
  bare `vimeo.com/<id>` URL with no query string and no decorative
  filename token -- is independently verifiable against
  `_is_decorative_hit()`'s own logic in this repo, not invented.
- The other decorative fixtures (a hero-background Vimeo embed with
  `background=1&loop=1&muted=1`, a `site-hero-banner.mp4`-shaped direct
  file) use a placeholder town rather than one of the six real named
  governments above, because BACKLOG.md's own text establishes all six
  were the OTHER kind (no URL signature, oEmbed-title-only) -- claiming
  one of them carried a URL signature it didn't have would misrepresent
  the real incident. The SIGNATURE ITSELF is real and independently
  confirmed: `background=1`/`loop=1&muted=1` is the exact Vimeo
  homepage-hero-embed shape BACKLOG.md's WO-355/WO-361 entries confirm
  live on 20 real government tenants (see this repo's own
  `_is_decorative_hit()` comment).
- `test_real_mcleansboro_*` and `test_real_youtube_channel_hit_*` use
  REAL, live-fetched fixtures already checked into
  `tests/fixtures/wo228_hub_ranking/` (see `tests/test_hub_link_ranking.py`
  for their original capture provenance) -- no invention at all. Probing
  `mcleansboro_vimeo_home.html` while building this WO turned up a real,
  previously-unnoticed case of exactly the bug this WO fixes: its
  homepage's `find_platform_link()` hit is `direct_file` pointing at
  `mcl-header-bkg.m4v` ("header background") -- a decorative homepage
  video with no `_is_decorative_hit()`-recognizable signature (no
  `background=1`/`loop=1&muted=1`, and "header"/"bkg" aren't tokens the
  existing filename regex matches) and no oEmbed of its own (a raw media
  file). That is precisely BACKLOG.md's WO-364 "3 more had no title
  signal available at all (a direct media file with no oEmbed...)"
  bucket, confirmed on a real, already-in-repo page rather than invented
  here.
"""

from __future__ import annotations

import os

from scripts.wo147_access_ladder_sweep import (
    BROWSER_HEADERS,
    HONEST_HEADERS,
    FetchResult,
    _is_decorative_hit,
    find_hop_links,
    find_platform_link,
    run_access_ladder,
)
import scripts.wo147_access_ladder_sweep as ladder_module

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "wo228_hub_ranking")


def _load_real_fixture(name: str) -> str:
    with open(os.path.join(FIXTURE_DIR, name), encoding="utf-8", errors="replace") as f:
        return f.read()


class _FakeSession:
    """Placeholder aiohttp session -- `fetch_one`/`fetch_headless` are
    monkeypatched per test below, so nothing here ever issues a real
    request or reads this object at all."""


def _patch_ladder(monkeypatch, responses, headless_result=None):
    """Patches `wo147_access_ladder_sweep`'s network calls for one test.

    `responses` maps an exact URL to the `FetchResult` it should get;
    requesting an unscripted URL fails loudly (a wrong assumption about
    which URLs the ladder would fetch should fail the test, not silently
    return nothing). `headless_result` is the `(html, url, error)` tuple
    `fetch_headless()` returns; the default (never scripted) means a test
    that reaches headless without setting this fails loudly too, rather
    than quietly falling through the "playwright not installed" path.
    `HOST_DELAY_SECONDS` is zeroed so tests run instantly instead of
    paying the real 2s/request politeness delay.
    """

    async def fake_fetch_one(session, url, headers):
        if url not in responses:
            raise AssertionError(
                f"unexpected fetch_one({url!r}) -- scripted URLs: {sorted(responses)}"
            )
        return responses[url]

    async def fake_fetch_headless(url):
        if headless_result is None:
            raise AssertionError(f"unexpected fetch_headless({url!r}) -- not scripted")
        return headless_result

    monkeypatch.setattr(ladder_module, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(ladder_module, "fetch_headless", fake_fetch_headless)
    monkeypatch.setattr(ladder_module, "HOST_DELAY_SECONDS", 0)


# --- _is_decorative_hit() itself: the real, independently-confirmed
# signatures (BACKLOG.md's WO-355/WO-361 entries), unchanged by this WO's
# relocation -- a basic regression check that moving it out of
# wo361_find_hub.py didn't change its behavior. ---


def test_is_decorative_hit_matches_the_real_confirmed_vimeo_hero_embed_shape():
    # background=1 alone, and loop=1+muted=1 together -- both real,
    # confirmed on 20 tenants per BACKLOG.md's WO-355 entry.
    assert _is_decorative_hit("https://vimeo.com/12345?background=1") is True
    assert _is_decorative_hit("https://vimeo.com/12345?loop=1&muted=1") is True
    # loop alone, or muted alone, is not the confirmed signature.
    assert _is_decorative_hit("https://vimeo.com/12345?loop=1") is False
    assert _is_decorative_hit("https://vimeo.com/12345") is False


def test_is_decorative_hit_matches_decorative_filename_tokens():
    assert _is_decorative_hit("https://cdn.example.gov/videos/welcome-reel.mp4") is True
    assert (
        _is_decorative_hit("https://cdn.example.gov/videos/tourism-board.mp4") is True
    )
    assert (
        _is_decorative_hit("https://cdn.example.gov/videos/council-2026-09-01.mp4")
        is False
    )


# --- Scenario 1: a decorative hit WITH a URL signature falls through and
# finds the real hop-link hub (BACKLOG.md's "keep climbing" fix). ---

_HOMEPAGE_WITH_DECORATIVE_HERO_AND_REAL_HOP_LINK = """
<html><head><title>Town of Liberty</title></head>
<body>
  <div class="hero">
    <iframe src="https://player.vimeo.com/video/778899001?background=1&amp;loop=1&amp;muted=1"
            width="100%" height="480"></iframe>
  </div>
  <nav>
    <a href="/about">About</a>
    <a href="https://libertytown.example.gov/agendas-and-minutes">Agendas &amp; Minutes</a>
    <a href="/contact">Contact</a>
  </nav>
</body></html>
"""

_AGENDA_PAGE_WITH_REAL_GRANICUS_LINK = """
<html><body>
  <h1>Agendas and Minutes</h1>
  <a href="https://libertytown.granicus.com/ViewPublisher.php?view_id=2">Meeting Videos</a>
</body></html>
"""


async def test_decorative_hero_embed_falls_through_to_real_hop_link_hit(monkeypatch):
    homepage_url = "https://libertytown.example.gov"
    agenda_url = "https://libertytown.example.gov/agendas-and-minutes"
    _patch_ladder(
        monkeypatch,
        {
            homepage_url: FetchResult(
                status=200,
                final_url=homepage_url,
                html=_HOMEPAGE_WITH_DECORATIVE_HERO_AND_REAL_HOP_LINK,
            ),
            agenda_url: FetchResult(
                status=200,
                final_url=agenda_url,
                html=_AGENDA_PAGE_WITH_REAL_GRANICUS_LINK,
            ),
        },
    )
    result = await run_access_ladder(
        _FakeSession(), "Town of Liberty", "VA", "libertytown.example.gov", ""
    )
    # The real hub, not the decorative hero embed, wins.
    assert result.platform == "granicus"
    assert (
        result.hit_url == "https://libertytown.granicus.com/ViewPublisher.php?view_id=2"
    )
    assert "778899001" not in (result.hit_url or "")
    # The skip is visible in the note, for anyone reading the sweep report.
    assert "skipped decorative homepage hit" in result.note
    assert "778899001" in result.note


# --- Scenario 2: a decorative hit WITH a URL signature, but nothing else
# on the page at all -- falls through, headless also finds nothing, and
# the ladder correctly reports "no platform link found" rather than the
# decorative one. ---

_HOMEPAGE_WITH_ONLY_A_DECORATIVE_BACKGROUND_VIDEO = """
<html><body>
<video autoplay muted loop>
  <source src="https://cdn.libertytown.example.gov/assets/site-hero-banner.mp4" type="video/mp4">
</video>
<nav><a href="/about">About</a><a href="/contact">Contact</a><a href="/jobs">Employment</a></nav>
</body></html>
"""


async def test_decorative_hit_with_nothing_else_on_page_reports_no_link_found(
    monkeypatch,
):
    homepage_url = "https://libertytown.example.gov"
    hit = find_platform_link(
        _HOMEPAGE_WITH_ONLY_A_DECORATIVE_BACKGROUND_VIDEO, homepage_url
    )
    assert hit is not None and _is_decorative_hit(hit[1])
    assert (
        find_hop_links(_HOMEPAGE_WITH_ONLY_A_DECORATIVE_BACKGROUND_VIDEO, homepage_url)
        == []
    )

    _patch_ladder(
        monkeypatch,
        {
            homepage_url: FetchResult(
                status=200,
                final_url=homepage_url,
                html=_HOMEPAGE_WITH_ONLY_A_DECORATIVE_BACKGROUND_VIDEO,
            ),
        },
        # Headless reaches the SAME homepage (JS-rendered) and genuinely
        # finds nothing else either -- a real, if last-resort, "no hub
        # here" outcome, not a headless failure.
        headless_result=(
            "<html><body><p>Nothing else here.</p></body></html>",
            homepage_url,
            None,
        ),
    )
    result = await run_access_ladder(
        _FakeSession(), "Town of Liberty", "VA", "libertytown.example.gov", ""
    )
    assert result.platform is None
    assert result.hit_url is None
    assert "skipped decorative homepage hit" in result.note
    assert "headless reached the page, no platform link found" in result.note


async def test_decorative_hit_still_decorative_after_headless_also_reports_no_link_found(
    monkeypatch,
):
    """Headless renders the SAME homepage (JS-executed) and the only
    thing it ALSO turns up is a (further) decorative embed -- headless is
    the last rung, so there is nowhere left to climb, and the ladder must
    still not credit it as a real hub."""
    homepage_url = "https://libertytown.example.gov"
    _patch_ladder(
        monkeypatch,
        {
            homepage_url: FetchResult(
                status=200,
                final_url=homepage_url,
                html=_HOMEPAGE_WITH_ONLY_A_DECORATIVE_BACKGROUND_VIDEO,
            ),
        },
        headless_result=(
            '<html><body><iframe src="https://vimeo.com/778899001?background=1">'
            "</iframe></body></html>",
            homepage_url,
            None,
        ),
    )
    result = await run_access_ladder(
        _FakeSession(), "Town of Liberty", "VA", "libertytown.example.gov", ""
    )
    assert result.platform is None
    assert result.hit_url is None
    assert "skipped decorative homepage hit (" in result.note
    assert "skipped decorative headless hit (" in result.note
    assert "headless reached the page, no platform link found" in result.note


# --- Scenario 3: the SAME decorative check applies to the 403 ->
# browser-headers retry path, since that's still "the homepage's own
# body," just fetched under different headers. ---

_HOMEPAGE_403_BROWSER_HEADERS_BODY = """
<html><body>
  <iframe src="https://vimeo.com/445566001?background=1"></iframe>
  <a href="https://smalltown.example.gov/agendas-and-minutes">Council Agendas and Minutes</a>
</body></html>
"""

_AGENDA_PAGE_FOR_403_CASE = """
<html><body>
  <a href="https://smalltown.granicus.com/ViewPublisher.php?view_id=1">Meeting Videos</a>
</body></html>
"""


async def test_decorative_hit_under_403_browser_headers_retry_also_falls_through(
    monkeypatch,
):
    homepage_url = "https://smalltown.example.gov"
    agenda_url = "https://smalltown.example.gov/agendas-and-minutes"

    async def fake_fetch_one(session, url, headers):
        if url == homepage_url and headers is HONEST_HEADERS:
            return FetchResult(status=403, final_url=url, html="<html>Forbidden</html>")
        if url == homepage_url and headers is BROWSER_HEADERS:
            return FetchResult(
                status=200, final_url=url, html=_HOMEPAGE_403_BROWSER_HEADERS_BODY
            )
        if url == agenda_url:
            return FetchResult(
                status=200, final_url=url, html=_AGENDA_PAGE_FOR_403_CASE
            )
        raise AssertionError(f"unexpected fetch_one({url!r}, headers={headers!r})")

    monkeypatch.setattr(ladder_module, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(ladder_module, "HOST_DELAY_SECONDS", 0)

    result = await run_access_ladder(
        _FakeSession(), "Small Town", "OH", "smalltown.example.gov", ""
    )
    assert result.platform == "granicus"
    assert (
        result.hit_url == "https://smalltown.granicus.com/ViewPublisher.php?view_id=1"
    )
    assert "skipped decorative homepage hit under browser headers" in result.note
    assert "445566001" in result.note


# --- Scenario 4: a decorative video with NO URL signature -- the real
# WO-364 Garfield NJ case -- cannot be told apart by this module (it does
# not fetch oEmbed titles), so it is correctly NOT rejected: forcing a
# guess with no real signal would be worse than accepting it, per
# CLAUDE.md's "reports report, they never guess" rule. ---

_GARFIELD_NJ_HOMEPAGE_WITH_UNSIGNED_VIMEO_LINK = """
<html><head><title>City of Garfield</title></head>
<body>
  <div class="sidebar">
    <a href="https://vimeo.com/998877001">Watch: City of Garfield 2024</a>
  </div>
</body></html>
"""


async def test_decorative_hit_with_no_url_signature_is_not_guessed_garfield_nj(
    monkeypatch,
):
    # The real fact this depends on: a bare vimeo.com/<id> URL (no query
    # string, no decorative filename token) does not match
    # _is_decorative_hit()'s URL-shape check -- confirmed directly here,
    # not assumed.
    assert _is_decorative_hit("https://vimeo.com/998877001") is False

    homepage_url = "https://garfieldnj.example.gov"
    _patch_ladder(
        monkeypatch,
        {
            homepage_url: FetchResult(
                status=200,
                final_url=homepage_url,
                html=_GARFIELD_NJ_HOMEPAGE_WITH_UNSIGNED_VIMEO_LINK,
            ),
        },
    )
    result = await run_access_ladder(
        _FakeSession(), "City of Garfield", "NJ", "garfieldnj.example.gov", ""
    )
    # Accepted at face value -- the ladder has no oEmbed-title capability
    # of its own and correctly does not invent a rejection it can't back
    # up. The real oEmbed title ("City of Garfield 2024" -- see
    # scripts/wo364_handread.py's docstring) is what a later, heavier
    # step would need to catch this one, not this module.
    assert result.platform == "vimeo"
    assert result.hit_url == "https://vimeo.com/998877001"
    assert result.note == ""


# --- Scenario 5: real, already-in-repo fixtures (no invention at all). ---


async def test_real_mcleansboro_direct_file_hit_has_no_signature_and_is_accepted(
    monkeypatch,
):
    """mcleansboro_vimeo_home.html (real, live-fetched 2026-09-11, see
    tests/test_hub_link_ranking.py) turned up a real, previously-unnoticed
    instance of this exact bug class while building this WO:
    find_platform_link() hits `mcl-header-bkg.m4v` ("header background")
    directly on the raw homepage -- a decorative homepage video with no
    _is_decorative_hit()-recognizable signature and no oEmbed of its own
    (a raw media file), matching BACKLOG.md's WO-364 "3 more had no title
    signal available at all (a direct media file with no oEmbed...)"
    bucket exactly. This module correctly cannot tell and does not guess;
    it passes the hit through unchanged, same as before this WO."""
    html = _load_real_fixture("mcleansboro_vimeo_home.html")
    homepage_url = "https://mcleansboro.us/"

    hit = find_platform_link(html, homepage_url)
    assert hit == (
        "direct_file",
        "https://mcleansboro.us/app/themes/bd-basetheme-2023/video/mcl-header-bkg.m4v",
    )
    assert _is_decorative_hit(hit[1]) is False

    _patch_ladder(
        monkeypatch,
        {homepage_url: FetchResult(status=200, final_url=homepage_url, html=html)},
    )
    result = await run_access_ladder(
        _FakeSession(), "McLeansboro", "IL", "mcleansboro.us", homepage_url
    )
    assert result.platform == "direct_file"
    assert result.hit_url == hit[1]
    assert result.note == ""


async def test_real_youtube_channel_hit_is_unaffected_regression(monkeypatch):
    """zoar_youtube_home.html (real, live-fetched, see
    tests/test_hub_link_ranking.py's own
    test_zoar_and_sidney_youtube_links_are_caught_by_find_platform_link_directly)
    -- a genuinely real, non-decorative hit found directly on the
    homepage. This is the "existing non-decorative-hit path" regression
    case: WO-904's change must not affect it at all."""
    html = _load_real_fixture("zoar_youtube_home.html")
    homepage_url = "https://historiczoarvillage.com/"

    hit = find_platform_link(html, homepage_url)
    assert hit is not None and hit[0] == "youtube"
    assert _is_decorative_hit(hit[1]) is False

    _patch_ladder(
        monkeypatch,
        {homepage_url: FetchResult(status=200, final_url=homepage_url, html=html)},
    )
    result = await run_access_ladder(
        _FakeSession(), "Zoar", "OH", "historiczoarvillage.com", homepage_url
    )
    assert result.platform == "youtube"
    assert result.hit_url == hit[1]
    assert result.access_mode == "plain"
    assert result.note == ""
