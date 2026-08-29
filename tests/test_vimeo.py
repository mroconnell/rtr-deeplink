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

What is NOT tested here, deliberately, because it does not work: caption
fetching. `player.vimeo.com/video/{id}/config` 403s every non-browser
client, so there is no positive server-side example to build a parser
against (see CLAUDE.md's "don't claim a caption/data path works without a
positive example"). The adapter is video-only and says so in a warning.
"""

import pytest

from app.platforms.base import CalendarPageError, detect_platform
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
