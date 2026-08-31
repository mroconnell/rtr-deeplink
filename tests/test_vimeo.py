"""Tests for the Vimeo adapter (app/platforms/vimeo.py), WO-29.

Every fixture here is a real, unmodified live capture taken 2026-08-21
from a real government account -- see vimeo.py's own module docstring for
the full investigation:

- `oembed_salisbury_1212025580.json` -- Salisbury, NC's real 7/21/2026
  City Council meeting (`vimeo.com/channels/coscouncil`). The one city in
  this investigation confirmed, via a real browser, to have populated
  English captions inside the player.
- `oembed_sebastopol_1152708575.json` -- Sebastopol, CA's real 1/6/2026
  council meeting, the privacy-hashed `vimeo.com/{id}/{hash}` shape.
- `oembed_chicago_1210310337.json` -- the video behind Chicago ELMS's own
  2026-07-16 Budget Committee meeting, reached via a showcase URL.
- `showcase_crrma.html` -- one of El Paso, TX's 13 per-body showcases
  (Camino Real Regional Mobility Authority). **Secret-scan note**: this
  fixture contains two copies of a JWT, because Vimeo's own page embeds
  one. It is NOT a credential of ours and never was -- decoded, its claims
  are `scopes: "public"`, `user_id: None`, `team_user_id: None`, Vimeo's
  own `app_id` 58479, and `exp` 1787356800 (2026-08-22), so it is an
  anonymous public-scope token that has since expired. Recorded here so
  nobody has to re-derive it during a future secret scan; leave it in
  place, since the fixture is a real unmodified capture and editing it
  would break that guarantee.
- `channel_coscouncil.html` -- Salisbury, NC's channel listing page.
- `oembed_corvallis_1220285695_domain_blocked.json` -- a real, unmodified
  live capture taken 2026-08-29 of Corvallis, OR's actual meeting video
  (found via the Vimeo direct-dorking sweep, see BACKLOG_DONE.md), whose
  owner has restricted both embedding and metadata to specific domains.
  `player.vimeo.com/video/1220285695` itself 403s with a real "Sorry ...
  privacy settings" page in this state -- confirmed live side by side
  with Salisbury's own sample above, which 401s instead and plays fine
  in a real browser -- so `domain_status_code` is the one reliable
  signal that separates a genuinely broken embed from an oEmbed call
  that merely couldn't reach extra metadata.
- `oembed_corvallis_1220285695_domain_recovered.json` -- the SAME real
  video, re-fetched live 2026-08-30 with `Referer: https://
  www.corvallisoregon.gov/` -- Corvallis's own real domain. Unmodified
  capture: `domain_status_code` is `200` and every metadata field is
  populated (title, author, duration), confirming the domain-allowlist
  Referer fix actually recovers a real blocked video, not just a
  theoretical one (WO-86, see vimeo.py's own docstring for the full
  investigation, including the Harpswell ME case that did NOT recover
  with the expected domain and needed a different real one).

- `player_salisbury_1212025580.html` -- a real, unmodified headless-
  Chromium capture of the player page itself
  (`player.vimeo.com/video/1212025580`), taken live 2026-08-31, carrying
  a genuine signed `<track kind="subtitles" src="https://captions.vimeo
  .com/...">`. `captions_salisbury_314604795.vtt` is the real caption
  file that signed URL pointed to at capture time (~2210 cues, a real
  2h03m meeting) -- both together are the positive example that unlocked
  server-side caption fetching (see vimeo.py's own docstring, "Captions
  ARE server-reachable after all"). `player.vimeo.com/video/{id}/config`
  itself still 403s/PrivacyErrors even from a real headless browser
  (confirmed live) -- the fix was never about reaching `/config`, it was
  reading the same signed URL straight off the rendered player page's DOM
  instead.
"""

from unittest import mock

import aiohttp
import pytest

from app.platforms.base import CalendarPageError, detect_platform
from app.platforms.headless_browser import HeadlessBrowserUnavailable
from app.platforms.vimeo import (
    VimeoAssetFinder,
    embed_url,
    is_vimeo_listing,
    parse_vimeo_video,
)
from app.utils import url_guard

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture


@pytest.fixture(autouse=True)
def _fake_public_dns(monkeypatch):
    """See test_generic_fallback.py's identical fixture -- guarded_get()
    resolves hostnames for real unless patched, and this suite is
    network-free."""
    monkeypatch.setattr(
        url_guard, "_resolve_hostname", lambda hostname: ["93.184.216.34"]
    )


@pytest.fixture(autouse=True)
def _no_headless_captions(monkeypatch):
    """The real, additive headless-browser caption fetch added 2026-08-31
    (see vimeo.py's own docstring, "Captions ARE server-reachable after
    all") launches a real Chromium unless mocked -- this autouse fixture
    keeps every other test in this suite exactly as it was (network-free,
    video-only, `_NO_CAPTIONS_WARNING` still set) by simulating the
    browser being unavailable, the same clean failure mode a real
    Playwright-less environment produces.
    `test_resolve_fetches_real_captions_via_headless_browser` below
    overrides this within its own test body to exercise the real positive
    path against a real captured fixture."""

    async def _unavailable(url, **kwargs):
        raise HeadlessBrowserUnavailable("no headless browser in tests")

    monkeypatch.setattr("app.platforms.vimeo.fetch_via_browser", _unavailable)


def _oembed_route(target: str, fixture: str) -> dict:
    from urllib.parse import quote

    url = "https://vimeo.com/api/oembed.json?url=" + quote(target, safe="")
    return {url: FakeResponse(status=200, text=load_fixture("vimeo", fixture), url=url)}


# --- URL-shape parsing. Every input below is a real URL shape observed
# live: three from Chicago ELMS's own `videoLink` field, the rest from
# the five confirmed channel/showcase cities. ---


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://vimeo.com/1212025580", ("1212025580", None)),
        ("https://vimeo.com/channels/coscouncil/1212025580", ("1212025580", None)),
        (
            "https://vimeo.com/1152708575/db9859a2aa?fl=sm&fe=ec",
            ("1152708575", "db9859a2aa"),
        ),
        (
            "https://vimeo.com/showcase/8925576?video=1210310337",
            ("1210310337", None),
        ),
        (
            "https://vimeo.com/showcase/citycouncil?video=1209979957",
            ("1209979957", None),
        ),
        (
            "https://vimeo.com/showcase/6277394/video/456202210",
            ("456202210", None),
        ),
        (
            "https://player.vimeo.com/video/1084319272?h=7ea4b7d5fa",
            ("1084319272", "7ea4b7d5fa"),
        ),
    ],
)
def test_parse_vimeo_video_handles_every_real_url_shape(url, expected):
    assert parse_vimeo_video(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        # A bare user page -- confirmed live to be fully client-rendered
        # with zero video ids in the raw HTML (Rockland, ME), so there's
        # nothing to resolve AND this is the real false-positive shape a
        # "watch us on Vimeo" footer link takes.
        "https://vimeo.com/rocklandmaine",
        # Livestream events are a different id space that
        # player.vimeo.com/video/{id} does not accept.
        "https://vimeo.com/event/1234567",
        "https://vimeo.com/",
        "https://youtube.com/watch?v=1212025580",
    ],
)
def test_parse_vimeo_video_declines_non_video_urls(url):
    assert parse_vimeo_video(url) is None


def test_detect_platform_claims_only_real_vimeo_shapes():
    assert detect_platform("https://vimeo.com/1212025580") == "vimeo"
    assert detect_platform("https://vimeo.com/showcase/crrma") == "vimeo"
    assert detect_platform("https://vimeo.com/channels/coscouncil") == "vimeo"
    # The footer-link false positive that would otherwise let
    # base.find_platform_link() hijack a real meeting page.
    assert detect_platform("https://vimeo.com/rocklandmaine") == "unknown"


@pytest.mark.parametrize(
    "title,expected",
    [
        # Salisbury NC, El Paso TX -- the common shape.
        ("7/21/2026 City Council Meeting", "2026-07-21"),
        ("Camino Real Regional Mobility Authority 5/14/2025", "2025-05-14"),
        # Sebastopol CA.
        ("EDITED - City Council Meeting - January 6, 2026", "2026-01-06"),
        # Chicago's own account, year first.
        ("2026 July 16 - Committee on Budget and Government Operations", "2026-07-16"),
        # Salisbury NC again -- the same channel really does mix in a
        # two-digit year on some meetings.
        ("6/2/26 City Council Meeting", "2026-06-02"),
        # No date at all -- must stay None rather than inventing one; the
        # caller falls back to Vimeo's own upload_date.
        ("City Council Meeting", None),
    ],
)
def test_meeting_date_is_read_from_real_title_shapes_only(title, expected):
    from app.platforms.vimeo import _date_from_title

    assert _date_from_title(title) == expected


def test_embed_url_carries_the_privacy_hash():
    assert embed_url("1212025580") == "https://player.vimeo.com/video/1212025580"
    assert (
        embed_url("1152708575", "db9859a2aa")
        == "https://player.vimeo.com/video/1152708575?h=db9859a2aa"
    )


def test_is_vimeo_listing_only_for_showcase_and_channel_roots():
    assert is_vimeo_listing("https://vimeo.com/showcase/crrma")
    assert is_vimeo_listing("https://vimeo.com/channels/coscouncil")
    assert not is_vimeo_listing("https://vimeo.com/showcase/8925576?video=1210310337")
    assert not is_vimeo_listing("https://vimeo.com/channels/coscouncil/1212025580")
    assert not is_vimeo_listing("https://vimeo.com/rocklandmaine")


def test_is_vimeo_listing_accepts_trailing_embed_suffix():
    # Real case (2026-08-28, BACKLOG.md): Birmingham MI's own watch-a-
    # meeting page embeds vimeo.com/showcase/11598114/embed, which this
    # matcher didn't claim before -- confirmed live to be the same real
    # showcase (57/54-play City of Birmingham videos), just server-
    # rendered without the bare URL's JSON-LD.
    assert is_vimeo_listing("https://vimeo.com/showcase/11598114/embed")
    assert is_vimeo_listing("https://vimeo.com/channels/coscouncil/embed")


# --- Single-video resolves, against the three real oEmbed captures. ---


async def test_resolve_salisbury_channel_meeting():
    url = "https://vimeo.com/1212025580"
    with mock_session(_oembed_route(url, "oembed_salisbury_1212025580.json")):
        result = await VimeoAssetFinder().resolve(url)

    assert result.platform == "vimeo"
    assert result.video_url == "https://player.vimeo.com/video/1212025580"
    assert result.video_format == "vimeo"
    assert result.external_id == "vimeo:1212025580"
    assert result.title == "7/21/2026 City Council Meeting"
    # Real meeting date read out of the title, not Vimeo's upload_date
    # ("2026-07-22 10:01:23") -- the meeting was the day before the upload.
    assert result.date == "2026-07-21"
    assert result.segments == []
    assert result.agenda_items == []
    # Honest about the one thing this platform can't do.
    assert any(
        "doesn't hand out caption files" in w for w in result.transcript_warnings
    )
    assert result.video_warnings == []


async def test_resolve_sebastopol_privacy_hashed_video():
    # The privacy hash must survive into the embed URL or the player
    # refuses to load the video at all.
    url = "https://vimeo.com/1152708575/db9859a2aa?fl=sm&fe=ec"
    with mock_session(
        _oembed_route(
            "https://vimeo.com/1152708575/db9859a2aa",
            "oembed_sebastopol_1152708575.json",
        )
    ):
        result = await VimeoAssetFinder().resolve(url)

    assert result.video_url == "https://player.vimeo.com/video/1152708575?h=db9859a2aa"
    assert result.title == "EDITED - City Council Meeting - January 6, 2026"
    assert result.date == "2026-01-06"
    # "City of Sebastopol" is a real Vimeo account name that validates
    # against the Census place table -- and keeps its own casing rather
    # than validated_label_extract()'s title-cased "City Of Sebastopol".
    assert result.jurisdiction == "City of Sebastopol"


async def test_resolve_chicago_showcase_video_reads_year_first_title_date():
    # Chicago's own Vimeo account titles its videos year-first ("2026 July
    # 16 - ..."), and its upload_date is the day BEFORE the meeting -- so
    # without the year-first title shape this resolves to the wrong date.
    url = "https://vimeo.com/showcase/8925576?video=1210310337"
    with mock_session(
        _oembed_route("https://vimeo.com/1210310337", "oembed_chicago_1210310337.json")
    ):
        result = await VimeoAssetFinder().resolve(url)

    assert result.video_url == "https://player.vimeo.com/video/1210310337"
    assert result.date == "2026-07-16"
    # "COC" is Chicago's real account name and is meaningless as a
    # jurisdiction -- validated_label_extract() must decline rather than
    # invent one. (The ELMS adapter supplies the real one; see
    # test_chicago_elms.py.)
    assert result.jurisdiction is None


async def test_resolve_declines_a_domain_privacy_blocked_video():
    # Real bug, 2026-08-29: this used to still report a playable
    # video_url and get ingested, producing a genuinely blank live page
    # (no title, no video, no transcript -- see BACKLOG_DONE.md). A
    # `domain_status_code` on the oEmbed body means the embed itself is
    # broken here, not just missing extra metadata -- resolve() must not
    # claim a video_url in that case.
    url = "https://vimeo.com/1220285695"
    with mock_session(
        _oembed_route(url, "oembed_corvallis_1220285695_domain_blocked.json")
    ):
        result = await VimeoAssetFinder().resolve(url)

    assert result.video_url is None
    assert result.title is None
    assert result.jurisdiction is None
    assert any("privacy settings" in w for w in result.video_warnings)


async def test_resolve_video_id_sends_domain_hint_as_referer_header():
    # WO-86: the oEmbed fetch must actually carry `domain_hint` as a
    # Referer header, not just accept the parameter and drop it --
    # that's the one thing a fixture-based response-body assertion can't
    # prove, since the mock returns the same body regardless of headers.
    captured_kwargs = {}

    def fake_get(self, req_url, **kwargs):
        captured_kwargs.update(kwargs)
        return FakeResponse(
            status=200,
            text=load_fixture(
                "vimeo", "oembed_corvallis_1220285695_domain_recovered.json"
            ),
            url=str(req_url),
        )

    with mock.patch.object(aiohttp.ClientSession, "get", fake_get):
        await VimeoAssetFinder.resolve_video_id(
            "1220285695", domain_hint="www.corvallisoregon.gov"
        )

    assert captured_kwargs.get("headers") == {
        "Referer": "https://www.corvallisoregon.gov/"
    }


async def test_resolve_video_id_recovers_a_domain_blocked_video_with_correct_domain_hint():
    # The real, live-verified case this whole feature exists for (WO-86):
    # Corvallis OR's 1220285695 is genuinely privacy-blocked (see the
    # test above this one), but re-fetching with its own real domain as
    # Referer recovers full metadata -- confirmed live 2026-08-30, see
    # oembed_corvallis_1220285695_domain_recovered.json's own comment.
    with mock_session(
        _oembed_route(
            "https://vimeo.com/1220285695",
            "oembed_corvallis_1220285695_domain_recovered.json",
        )
    ):
        result = await VimeoAssetFinder.resolve_video_id(
            "1220285695", domain_hint="www.corvallisoregon.gov"
        )

    assert result.video_url == "https://player.vimeo.com/video/1220285695"
    assert result.title == "08/20/2026 City Council Work Session"
    assert not any("privacy settings" in w for w in result.video_warnings)


async def test_resolve_still_yields_a_playable_embed_when_oembed_is_unreachable():
    # oEmbed is the metadata half only. If Vimeo ever starts refusing this
    # app's server IP there (a real risk -- YouTube already does, see
    # youtube.py), the embed itself still works, because the player
    # fetches its own config in the visitor's browser.
    url = "https://vimeo.com/1212025580"
    with mock_session({}):
        result = await VimeoAssetFinder().resolve(url)

    assert result.video_url == "https://player.vimeo.com/video/1212025580"
    assert result.title is None
    assert any("should still work" in w for w in result.video_warnings)


async def test_resolve_fetches_real_captions_via_headless_browser():
    # Real, additive fix (2026-08-31): navigating headless_browser.py's
    # existing Cloudflare-bypass Chromium fetch to the player page itself
    # (not /config, which still fails there -- confirmed live) renders a
    # real `<track kind="subtitles" src="https://captions.vimeo.com/...">`
    # with a genuine signed caption URL. `player_salisbury_1212025580.html`
    # and `captions_salisbury_314604795.vtt` are both real, unmodified
    # captures taken live 2026-08-31 of Salisbury NC's 1212025580 -- the
    # same real 7/21/2026 City Council meeting the oEmbed fixtures above
    # are from, and the one this whole investigation names as having a
    # real, populated English track. The signed URL's own `expires=` query
    # param is a Unix timestamp for 2026-08-31 23:12 UTC (computed via
    # `datetime.utcfromtimestamp`), i.e. it was already expired by the
    # time this test was written -- harmless to keep in the fixture, same
    # reasoning as `showcase_crrma.html`'s own already-expired JWT.
    url = "https://vimeo.com/1212025580"
    player_html = load_fixture("vimeo", "player_salisbury_1212025580.html")
    caption_url = (
        "https://captions.vimeo.com/captions/314604795.vtt"
        "?expires=1788217973&sig=f1ebb8b30fd11e977375b7b4a5de62641846d6fe"
    )
    caption_vtt = load_fixture("vimeo", "captions_salisbury_314604795.vtt")

    async def _fake_fetch_via_browser(fetch_url, **kwargs):
        assert fetch_url == "https://player.vimeo.com/video/1212025580"
        return player_html

    with mock.patch("app.platforms.vimeo.fetch_via_browser", _fake_fetch_via_browser):
        routes = {
            **_oembed_route(url, "oembed_salisbury_1212025580.json"),
            caption_url: FakeResponse(status=200, text=caption_vtt, url=caption_url),
        }
        with mock_session(routes):
            result = await VimeoAssetFinder().resolve(url)

    assert result.video_url == "https://player.vimeo.com/video/1212025580"
    assert len(result.segments) > 2000  # real capture has ~2210 cues
    assert result.segments[0].text == "Talk to her about."
    assert result.transcript_language == "en"
    # The real fix replaces the video-only warning entirely, since a real
    # transcript now exists.
    assert not any(
        "doesn't hand out caption files" in w for w in result.transcript_warnings
    )


async def test_resolve_falls_back_to_video_only_when_headless_browser_unavailable():
    # The default/autouse _no_headless_captions fixture already covers
    # this for every other test -- this one asserts it explicitly so the
    # fallback behavior itself is a named, visible regression test rather
    # than an incidental side effect of the fixture.
    url = "https://vimeo.com/1212025580"
    with mock_session(_oembed_route(url, "oembed_salisbury_1212025580.json")):
        result = await VimeoAssetFinder().resolve(url)

    assert result.segments == []
    assert any(
        "doesn't hand out caption files" in w for w in result.transcript_warnings
    )


async def test_resolve_reports_a_non_video_vimeo_url_honestly():
    result = await VimeoAssetFinder().resolve("https://vimeo.com/rocklandmaine")
    assert result.video_url is None
    assert any("couldn't find a Vimeo video" in w for w in result.video_warnings)


# --- Listing pages -> a real pick-list, not a dead end. ---


async def test_showcase_listing_returns_calendar_candidates():
    url = "https://vimeo.com/showcase/crrma"
    routes = {
        url: FakeResponse(
            status=200, text=load_fixture("vimeo", "showcase_crrma.html"), url=url
        )
    }

    with mock_session(routes):
        with pytest.raises(CalendarPageError) as excinfo:
            await VimeoAssetFinder().resolve(url)

    candidates = excinfo.value.candidates
    assert len(candidates) >= 10
    titles = [c["title"] for c in candidates]
    assert any("Camino Real Regional Mobility Authority" in t for t in titles)
    # Every candidate URL must be re-resolvable by this same adapter, and
    # a showcase's videos carry privacy hashes that have to come along.
    for candidate in candidates:
        assert parse_vimeo_video(candidate["url"]) is not None
    assert any("/" in c["url"].split("vimeo.com/")[1] for c in candidates)
    # Dates come from the real meeting titles ("... 5/14/2025").
    assert all(c["date"] for c in candidates)


async def test_channel_listing_returns_calendar_candidates():
    # A channel page's JSON-LD nests each VideoObject inside a ListItem's
    # `item` key, unlike a showcase's flat ItemList -- the reason
    # _iter_video_objects() walks the whole structure.
    url = "https://vimeo.com/channels/coscouncil"
    routes = {
        url: FakeResponse(
            status=200, text=load_fixture("vimeo", "channel_coscouncil.html"), url=url
        )
    }

    with mock_session(routes):
        with pytest.raises(CalendarPageError) as excinfo:
            await VimeoAssetFinder().resolve(url)

    candidates = excinfo.value.candidates
    assert len(candidates) >= 10
    assert any(c["title"] == "7/21/2026 City Council Meeting" for c in candidates)
    assert any(c["url"] == "https://vimeo.com/1212025580" for c in candidates)
    ids = [parse_vimeo_video(c["url"])[0] for c in candidates]
    assert len(ids) == len(set(ids))


async def test_embed_suffixed_showcase_fetches_the_unsuffixed_url():
    # The /embed variant itself carries zero JSON-LD (confirmed live) --
    # resolve() must fetch the bare showcase URL, not the /embed one, or
    # this would regress to "couldn't read any meetings" despite
    # is_vimeo_listing() now claiming the URL.
    embed_url_in = "https://vimeo.com/showcase/crrma/embed"
    bare_url = "https://vimeo.com/showcase/crrma"
    routes = {
        bare_url: FakeResponse(
            status=200, text=load_fixture("vimeo", "showcase_crrma.html"), url=bare_url
        )
    }

    with mock_session(routes):
        with pytest.raises(CalendarPageError) as excinfo:
            await VimeoAssetFinder().resolve(embed_url_in)

    assert len(excinfo.value.candidates) >= 10


async def test_listing_with_no_readable_meetings_fails_honestly():
    url = "https://vimeo.com/showcase/empty"
    routes = {url: FakeResponse(status=200, text="<html></html>", url=url)}

    with mock_session(routes):
        result = await VimeoAssetFinder().resolve(url)

    assert result.video_url is None
    assert any("couldn't read any meetings" in w for w in result.video_warnings)


async def test_listing_fetch_failure_is_logged(caplog):
    # 2026-08-28: _fetch()'s non-200 branch used to be silent.
    url = "https://vimeo.com/showcase/unreachable"
    routes = {url: FakeResponse(status=503, url=url)}

    with caplog.at_level("WARNING"):
        with mock_session(routes):
            result = await VimeoAssetFinder().resolve(url)

    assert result.video_url is None
    assert any("couldn't read any meetings" in w for w in result.video_warnings)
    assert any("Vimeo fetch got HTTP 503" in r.message for r in caplog.records)


def test_jurisdiction_strips_institutional_suffix_before_validating():
    # Real account names, 2026-08-29 direct-dorking batch (BACKLOG_DONE.md,
    # "22 new real ingests"): each one is an unrecoverable glued phrase as-
    # is (validated_label_extract() correctly declines "Peters Township
    # School District" whole), but a real, unambiguous place name once the
    # trailing institutional phrase is stripped.
    assert (
        VimeoAssetFinder._jurisdiction(
            {"author_name": "Peters Township School District"}
        )
        == "Peters Township"
    )
    assert (
        VimeoAssetFinder._jurisdiction({"author_name": "Hopkins Public Schools"})
        == "Hopkins"
    )
    assert (
        VimeoAssetFinder._jurisdiction({"author_name": "Jefferson Parish Schools"})
        == "Jefferson Parish"
    )
    # "Seekonk, MA" not bare "Seekonk" -- lookup_city_state()'s
    # subdivision-table fallback (added the same day) resolves the state
    # too, since Seekonk is a real, unambiguous MA town missing from
    # places.csv but present in the COUSUB subdivisions table.
    assert (
        VimeoAssetFinder._jurisdiction({"author_name": "Seekonk Public Schools"})
        == "Seekonk, MA"
    )
    assert (
        VimeoAssetFinder._jurisdiction({"author_name": "Mason County District Library"})
        == "Mason County"
    )


def test_jurisdiction_still_declines_a_name_with_no_real_place_in_it():
    # "District 113 Media" (Highland Park/Deerfield IL's District 113
    # schools) has no institutional suffix this file strips and no place
    # name for validated_label_extract() to find either way -- must stay
    # None rather than guess "District 113".
    assert VimeoAssetFinder._jurisdiction({"author_name": "District 113 Media"}) is None


def test_jurisdiction_strips_community_media_suffixes():
    # More real account names from the same 2026-08-29 batch
    # (BACKLOG_DONE.md) -- community-media suffixes, not K-12/library
    # ones, but the identical shape: a real place name plus a trailing
    # organizational phrase validated_label_extract() correctly declines
    # to guess as one glued unit.
    assert (
        VimeoAssetFinder._jurisdiction(
            {"author_name": "Willits Community Television Inc"}
        )
        == "Willits, CA"
    )
    assert (
        VimeoAssetFinder._jurisdiction({"author_name": "Morrilton Community Channel 6"})
        == "Morrilton, AR"
    )
    assert (
        VimeoAssetFinder._jurisdiction({"author_name": "Peters Township Community TV"})
        == "Peters Township"
    )
    assert (
        VimeoAssetFinder._jurisdiction({"author_name": "Town of Penfield Television"})
        == "Town of Penfield"
    )


def test_jurisdiction_known_account_map_covers_glued_abbreviations():
    # "UMTownship" and "SHCTV15" are real 2026-08-29 batch accounts whose
    # names are glued abbreviations (Upper Merion Township PA, South
    # Hadley MA) with no generic split/validate path to the real name --
    # corroborated by this project's own BACKLOG_DONE.md writeup of the
    # same batch, which already names both cities, plus each account's
    # own video content ("Board of Supervisors Meeting" for a PA
    # township; "Selectboard" for a New England town) and, for South
    # Hadley, a second real channel handle on the same meeting
    # ("shselectboard").
    assert (
        VimeoAssetFinder._jurisdiction({"author_name": "UMTownship"})
        == "Upper Merion Township, PA"
    )
    assert (
        VimeoAssetFinder._jurisdiction({"author_name": "SHCTV15"}) == "South Hadley, MA"
    )


def test_jurisdiction_resolves_an_already_state_shaped_ambiguous_name():
    # Real account, confirmed live 2026-08-30 (vimeo.com/user23531710,
    # "City of Medina, Minnesota's Videos on Vimeo") -- BACKLOG.md's
    # "[NEEDS-AUDIT] A name that's already 'X, State'-shaped..." entry,
    # fixed here (WO-70). "Medina" alone is real in 6 states (MN, ND, OH,
    # TN, WA, NY per places.csv), so a bare lookup would stay ambiguous,
    # but the account name already names its own state directly -- Vimeo
    # had no comma-handling at all before this fix, so this used to fall
    # through to the glued-label path (not built for spaces/commas) and
    # decline outright.
    assert (
        VimeoAssetFinder._jurisdiction({"author_name": "City of Medina, Minnesota"})
        == "City of Medina, Minnesota"
    )


def test_jurisdiction_declines_an_ambiguous_name_with_an_incorrect_claimed_state():
    # "Medina" is not a real INCORPORATED PLACE in Texas at all (confirmed
    # via places.csv -- only Medina COUNTY is real in Texas, per
    # counties.csv). A "City of"-prefixed claim must be checked against
    # the place table, not the county one, so this stays declined rather
    # than false-accepting off the back of the same-named county -- the
    # exact cross-type false accept `resolve_claimed_state()`'s own
    # docstring calls out.
    assert (
        VimeoAssetFinder._jurisdiction({"author_name": "City of Medina, Texas"}) is None
    )


def test_jurisdiction_still_resolves_an_unambiguous_state_shaped_name():
    # No-regression check: an already-"X, State"-shaped name that was
    # ALREADY unambiguous on its own (no fix needed here) must still
    # resolve the same way after this change -- "Sebastopol" alone is
    # nationally unambiguous, so this exercises the pre-existing
    # `lookup_city_state(base)` branch of the comma-check, not the new
    # `resolve_claimed_state()` one.
    assert (
        VimeoAssetFinder._jurisdiction(
            {"author_name": "City of Sebastopol, California"}
        )
        == "City of Sebastopol, California"
    )
