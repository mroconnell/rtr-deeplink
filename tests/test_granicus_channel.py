"""Tests for granicus_channel.py -- matching a Legistar meeting to a
Granicus ViewPublisher RSS item by name+date, for the confirmed real gap
on Kansas City, MO's Legistar instance (see that module's own docstring).

Fixture (tests/fixtures/granicus_channel/kansascity_viewpublisher_rss.xml)
is a real, trimmed excerpt (3 of the feed's real 100 items) fetched live
2026-08-29 via `curl https://kansascity.granicus.com/ViewPublisherRSS.php
?view_id=2&mode=video` -- not invented: real guids, real clip_ids, the
real Aug 11 same-day two-committee case used below to test
disambiguation.
"""

from app.platforms import granicus_channel as gc

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture

RSS_URL = "https://kansascity.granicus.com/ViewPublisherRSS.php?view_id=2&mode=video"


def _routes():
    xml = load_fixture("granicus_channel", "kansascity_viewpublisher_rss.xml")
    return {RSS_URL: FakeResponse(status=200, text=xml)}


def test_has_view_publisher_fallback_recognizes_kansas_city():
    assert gc.has_view_publisher_fallback("kansascity.legistar.com")
    assert gc.has_view_publisher_fallback("KansasCity.Legistar.com")
    assert not gc.has_view_publisher_fallback("maricopa.legistar.com")


async def test_find_view_publisher_match_finds_the_real_council_item():
    with mock_session(_routes()):
        match = await gc.find_view_publisher_match(
            "kansascity.legistar.com", "Council", "2026-08-13"
        )
    assert match is not None
    assert match.clip_url == (
        "https://kansascity.granicus.com/MediaPlayer.php?view_id=2&clip_id=14515"
    )
    assert match.item_body == "Council Legislative Session"


async def test_find_view_publisher_match_disambiguates_same_day_by_body_name():
    # Real confirmed case: two different committees both met 2026-08-11.
    # Each must resolve to its OWN clip, not either one at random.
    with mock_session(_routes()):
        transportation = await gc.find_view_publisher_match(
            "kansascity.legistar.com",
            "Transportation, Infrastructure and Operations Committee",
            "2026-08-11",
        )
        neighborhood = await gc.find_view_publisher_match(
            "kansascity.legistar.com",
            "Neighborhood Planning and Development",
            "2026-08-11",
        )
    assert transportation is not None
    assert "clip_id=14508" in transportation.clip_url
    assert neighborhood is not None
    assert "clip_id=14511" in neighborhood.clip_url


async def test_find_view_publisher_match_normalizes_ampersand_and_comma_wording_drift():
    # Real bug found and fixed live 2026-08-29: Legistar names this real
    # committee "Finance, Governance and Public Safety Committee" (comma,
    # "and"), but Granicus's own RSS titles it "Finance Governance &
    # Public Safety Committee" (no comma, "&") -- and the raw XML title
    # text is HTML-entity-encoded ("&amp;"), so a naive "&"->"and"
    # substitution against the unescaped text silently produces "andamp;"
    # instead, never matching either. Must match despite both the
    # wording drift and the entity-encoding.
    with mock_session(_routes()):
        match = await gc.find_view_publisher_match(
            "kansascity.legistar.com",
            "Finance, Governance and Public Safety Committee",
            "2026-08-18",
        )
    assert match is not None
    assert "clip_id=14518" in match.clip_url
    assert match.item_body == "Finance Governance & Public Safety Committee"


async def test_find_view_publisher_match_returns_none_for_a_wrong_date():
    with mock_session(_routes()):
        match = await gc.find_view_publisher_match(
            "kansascity.legistar.com", "Council", "2026-08-14"
        )
    assert match is None


async def test_find_view_publisher_match_returns_none_for_an_unmatched_body():
    # Real date exists in the feed, but no item's body starts with this
    # -- must decline rather than guess at an unrelated same-day item.
    with mock_session(_routes()):
        match = await gc.find_view_publisher_match(
            "kansascity.legistar.com", "Historic Preservation Commission", "2026-08-13"
        )
    assert match is None


async def test_find_view_publisher_match_returns_none_for_unknown_tenant():
    match = await gc.find_view_publisher_match(
        "maricopa.legistar.com", "Council", "2026-08-13"
    )
    assert match is None


async def test_find_view_publisher_match_returns_none_without_meeting_date():
    match = await gc.find_view_publisher_match(
        "kansascity.legistar.com", "Council", None
    )
    assert match is None


async def test_find_view_publisher_match_returns_none_on_fetch_failure():
    with mock_session({RSS_URL: FakeResponse(status=500)}):
        match = await gc.find_view_publisher_match(
            "kansascity.legistar.com", "Council", "2026-08-13"
        )
    assert match is None


# Second real tenant, confirmed live 2026-09-10 (WO-145). Fixture
# (tests/fixtures/granicus_channel/yonkersny_viewpublisher_rss.xml) is a
# real, trimmed excerpt (5 of the feed's real 13 items) fetched live
# 2026-09-10 via `curl https://yonkersny.granicus.com/ViewPublisherRSS.php
# ?view_id=1&mode=video` -- real guids and clip_ids, including a genuine
# same-date multi-body case (City Council / Legislation and Codes both met
# 2024-10-08) and two (of the real feed's five) same-date-and-body
# duplicate "City Council of Yonkers Stated Meeting on 2024-04-09" items,
# each a distinct real clip_id -- Granicus's own feed genuinely has this
# double-booking, not a fixture-authoring mistake; two of the five is kept
# here since that's already enough to exercise the len(candidates) != 1
# decline below.
_YONKERS_RSS_URL = (
    "https://yonkersny.granicus.com/ViewPublisherRSS.php?view_id=1&mode=video"
)


def _yonkers_routes():
    xml = load_fixture("granicus_channel", "yonkersny_viewpublisher_rss.xml")
    return {_YONKERS_RSS_URL: FakeResponse(status=200, text=xml)}


def test_has_view_publisher_fallback_recognizes_yonkers():
    assert gc.has_view_publisher_fallback("yonkersny.legistar.com")
    assert gc.has_view_publisher_fallback("YonkersNY.Legistar.com")


async def test_find_view_publisher_match_finds_the_real_yonkers_council_item():
    with mock_session(_yonkers_routes()):
        match = await gc.find_view_publisher_match(
            "yonkersny.legistar.com",
            "City Council of Yonkers Stated Meeting",
            "2024-10-08",
        )
    assert match is not None
    assert match.clip_url == (
        "https://yonkersny.granicus.com/MediaPlayer.php?view_id=1&clip_id=53"
    )


async def test_find_view_publisher_match_disambiguates_yonkers_same_day_by_body_name():
    # Real confirmed case: "City Council of Yonkers Stated Meeting" and
    # "Legislation and Codes" both met 2024-10-08 -- each body name must
    # resolve to its own clip.
    with mock_session(_yonkers_routes()):
        council = await gc.find_view_publisher_match(
            "yonkersny.legistar.com",
            "City Council of Yonkers Stated Meeting",
            "2024-10-08",
        )
        codes = await gc.find_view_publisher_match(
            "yonkersny.legistar.com", "Legislation and Codes", "2024-10-08"
        )
    assert council is not None
    assert "clip_id=53" in council.clip_url
    assert codes is not None
    assert "clip_id=52" in codes.clip_url


async def test_find_view_publisher_match_declines_yonkers_real_duplicate_items():
    # Real, confirmed-live gap: this tenant's feed carries multiple
    # distinct clip_ids (five in the real feed, two kept in this trimmed
    # fixture) under the exact same body name and the exact same date
    # (2024-04-09) -- a genuine same-day double-booking in Granicus's own
    # data, not a hypothetical. len(candidates) != 1 must decline rather
    # than guess at one of them.
    with mock_session(_yonkers_routes()):
        match = await gc.find_view_publisher_match(
            "yonkersny.legistar.com",
            "City Council of Yonkers Stated Meeting",
            "2024-04-09",
        )
    assert match is None
