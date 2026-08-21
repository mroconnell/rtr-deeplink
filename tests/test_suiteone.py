from app.platforms.suiteone import SuiteOneAssetFinder

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture, load_fixture_bytes

PACIFIC_GROVE_URL = "https://pacificgroveca.suiteonemedia.com/event/?id=2099"
PACIFIC_GROVE_HOME = "https://pacificgroveca.suiteonemedia.com/"
PACIFIC_GROVE_CAPTIONS = (
    "https://pacificgroveca.suiteonemedia.com/Event/GetCaptions/?eventId=2099"
)

LORAIN_URL = "https://lorainoh.suiteonemedia.com/event/?id=2794"
LORAIN_HOME = "https://lorainoh.suiteonemedia.com/"

ST_MARYS_URL = "https://stmarysga.suiteonemedia.com/event/?id=1000"
ST_MARYS_HOME = "https://stmarysga.suiteonemedia.com/"

HOLLADAY_URL = "https://holladayut.suiteonemedia.com/event/?id=2652"
HOLLADAY_HOME = "https://holladayut.suiteonemedia.com/"
HOLLADAY_CAPTIONS = (
    "https://holladayut.suiteonemedia.com/Event/GetCaptions/?eventId=2652"
)


async def test_resolve_real_pacific_grove_traffic_safety_commission():
    # Real page fetched live 2026-08-21 from a real Pacific Grove, CA
    # Traffic Safety Commission meeting (id 2099, a prior investigation's
    # already-confirmed sample, re-verified live this session) -- the real,
    # populated happy path: direct S3 mp4, real populated WebVTT captions,
    # and a date recovered from the tenant's home page (never present on
    # the event page itself).
    event_html = load_fixture("suiteone", "pacificgrove_event.html")
    home_html = load_fixture("suiteone", "pacificgrove_home.html")
    captions_vtt = load_fixture("suiteone", "pacificgrove_captions.vtt")

    routes = {
        PACIFIC_GROVE_URL: FakeResponse(
            status=200, text=event_html, url=PACIFIC_GROVE_URL
        ),
        PACIFIC_GROVE_HOME: FakeResponse(status=200, text=home_html),
        PACIFIC_GROVE_CAPTIONS: FakeResponse(status=200, text=captions_vtt),
    }

    with mock_session(routes):
        result = await SuiteOneAssetFinder().resolve(PACIFIC_GROVE_URL)

    assert result.platform == "suiteone"
    assert result.external_id == "suiteone:pacificgroveca:2099"
    assert result.title == "Traffic Safety Commission"
    assert result.date == "2025-05-27"
    assert result.jurisdiction == "Pacific Grove, CA"
    assert (
        result.video_url
        == "https://s3.amazonaws.com/suiteone.pacificgroveca.videofiles/e8a9033c.mp4"
    )
    assert result.video_format == "mp4"
    assert result.video_warnings == []
    assert len(result.segments) == 70
    assert result.segments[0].text == "Certainly, Commissioner David."
    assert result.transcript_language == "en"
    assert result.transcript_warnings == []
    # No GetAgendaFile embed on this particular sampled event.
    assert result.agenda_link is None


async def test_resolve_lorain_video_with_no_captions():
    # Real page fetched live 2026-08-21 from a real Lorain, OH Planning
    # Commission meeting (id 2794, also a prior investigation's already-
    # confirmed sample) -- confirms the real "video but no tracks key at
    # all" shape (not an empty tracks array) degrades to a plain "no
    # captions" warning rather than an error. Also exercises the
    # jurisdiction case where the subdomain's own wordninja split
    # ('lora', 'in', 'oh') only glues into a validating name once its
    # trailing real state code is stripped.
    event_html = load_fixture("suiteone", "lorainoh_event.html")
    home_html = load_fixture("suiteone", "lorainoh_home.html")

    routes = {
        LORAIN_URL: FakeResponse(status=200, text=event_html, url=LORAIN_URL),
        LORAIN_HOME: FakeResponse(status=200, text=home_html),
    }

    with mock_session(routes):
        result = await SuiteOneAssetFinder().resolve(LORAIN_URL)

    assert result.external_id == "suiteone:lorainoh:2794"
    assert result.title == "Planning Commission"
    assert result.date == "2025-01-02"
    assert result.jurisdiction == "Lorain, OH"
    assert (
        result.video_url
        == "https://s3.amazonaws.com/suiteone.lorainoh.videofiles/cc5178da.mp4"
    )
    assert result.video_format == "mp4"
    assert result.segments == []
    assert result.transcript_warnings == ["No captions found for this video."]


async def test_resolve_st_marys_ga_no_video_yet_and_resolves_glued_jurisdiction():
    # Real page fetched live 2026-08-21 -- St Marys, GA event id 1000
    # ("Orange Hall Management Committee") is a real, confirmed case of
    # the SAME page shape served with `var src = '';` -- this vendor's own
    # signal for "no recording yet", not a parse failure.
    #
    # Also the regression test for the residual jurisdiction gap this
    # adapter originally shipped with, closed 2026-08-21 (WO-22) in the
    # shared module: "stmarysga" wordninja-splits to ['st','mary','sga'],
    # whose last token isn't a real 2-letter state code and whose
    # glued/spaced remainders don't validate either (the real state
    # letters get absorbed into the non-word "sga" chunk), so this used to
    # produce jurisdiction=None. `jurisdiction_enrich`'s new tier-5 raw-
    # label state strip ("stmarysga" -> "stmarys" -> "St Marys") resolves
    # the name, and this adapter now asks that module for the code it
    # stripped ("GA") rather than re-deriving it -- giving the real,
    # confirmed-correct "St Marys, GA".
    event_html = load_fixture("suiteone", "stmarysga_event.html")

    routes = {
        ST_MARYS_URL: FakeResponse(status=200, text=event_html, url=ST_MARYS_URL),
        ST_MARYS_HOME: FakeResponse(status=404, text=""),
    }

    with mock_session(routes):
        result = await SuiteOneAssetFinder().resolve(ST_MARYS_URL)

    assert result.title == "Orange Hall Management Committee"
    assert result.video_url is None
    assert result.video_format is None
    assert result.video_warnings == ["No playable video found for this event."]
    # Home page fetch 404s -- date degrades to None rather than raising.
    assert result.date is None
    # Was None until the WO-22 shared-module fix -- see docstring above.
    assert result.jurisdiction == "St Marys, GA"


async def test_resolve_holladay_ut_agenda_link_and_real_captions():
    # Real page fetched live 2026-08-21 -- Holladay, UT City Council
    # Meeting (id 2652), a fresh CDX-derived candidate confirmed live this
    # session (not one of the two pre-confirmed samples). Confirms the
    # real `/event/GetAgendaFile/Agenda?aid=N` object-embed shape
    # (distinct from the general `/event/GetDocumentFile/{title}?did=N`
    # endpoint seen on Pacific Grove) is surfaced as `agenda_link`, and
    # that real populated captions exist on a SECOND independent tenant,
    # not just Pacific Grove.
    event_html = load_fixture("suiteone", "holladayut_event.html")
    home_html = load_fixture("suiteone", "holladayut_home.html")
    captions_vtt = load_fixture("suiteone", "holladayut_captions.vtt")

    routes = {
        HOLLADAY_URL: FakeResponse(status=200, text=event_html, url=HOLLADAY_URL),
        HOLLADAY_HOME: FakeResponse(status=200, text=home_html),
        HOLLADAY_CAPTIONS: FakeResponse(status=200, text=captions_vtt),
    }

    with mock_session(routes):
        result = await SuiteOneAssetFinder().resolve(HOLLADAY_URL)

    assert result.external_id == "suiteone:holladayut:2652"
    assert result.title == "City Council Meeting"
    assert result.date == "2025-02-06"
    assert result.jurisdiction == "Holladay, UT"
    assert (
        result.agenda_link
        == "https://holladayut.suiteonemedia.com/event/GetAgendaFile/Agenda"
        "?aid=3284#page=1&zoom=100,0,0"
    )
    assert len(result.segments) > 1000
    assert result.transcript_language == "en"


async def test_resolve_degrades_to_no_date_when_event_missing_from_home_listing():
    # Synthetic-shaped home page (a real fixture's own structure, just
    # with the target event id absent from every row) -- covers the
    # "event paginated off the currently-visible home listing" branch the
    # module docstring flags as unconfirmed-how-common. Reuses Pacific
    # Grove's real event/captions fixtures unchanged; only the home page
    # response is swapped for one with no matching row.
    event_html = load_fixture("suiteone", "pacificgrove_event.html")
    captions_vtt = load_fixture("suiteone", "pacificgrove_captions.vtt")

    routes = {
        PACIFIC_GROVE_URL: FakeResponse(
            status=200, text=event_html, url=PACIFIC_GROVE_URL
        ),
        PACIFIC_GROVE_HOME: FakeResponse(
            status=200,
            text="<html><body><table><tbody>"
            '<tr><td><a href="/event/?id=999999">Some Other Meeting</a></td>'
            '<td class="text-nowrap" data-sort="0">Jan 01, 2020 | 09:00 AM</td>'
            "</tr></tbody></table></body></html>",
        ),
        PACIFIC_GROVE_CAPTIONS: FakeResponse(status=200, text=captions_vtt),
    }

    with mock_session(routes):
        result = await SuiteOneAssetFinder().resolve(PACIFIC_GROVE_URL)

    assert result.date is None
    assert result.title == "Traffic Safety Commission"


async def test_resolve_missing_ids_raises_value_error():
    import pytest

    with pytest.raises(ValueError):
        await SuiteOneAssetFinder().resolve("https://suiteonemedia.com/")


def test_captions_vtt_fixture_is_real_and_non_empty():
    # Guards against a future accidental truncation of the fixture --
    # this app's own convention is "don't claim a data path works without
    # a positive example," so this pins the fixture as genuinely
    # containing real cue text, not a placeholder.
    raw = load_fixture_bytes("suiteone", "pacificgrove_captions.vtt")
    assert raw.startswith(b"WEBVTT")
    assert len(raw) > 1000
