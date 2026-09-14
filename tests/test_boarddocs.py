"""Tests for BoardDocs (app/platforms/boarddocs.py) -- WO-365, 2026-09-14.

Every HTML/JSON fixture under tests/fixtures/boarddocs/ is REAL, fetched
live from the two real tenants named in
docs/investigations/boarddocs_video_adapter.md (Tallahassee FL's City
Commission, `fla/talgov`; Colorado City AZ schools, `az/ccschools`) plus
one negative control (Austin ISD, `tx/austinisd`), one request at a time,
>=1.5s apart, per this WO's house rule -- see BACKLOG_DONE.md's WO-365
entry for the full request log. The two meetings-list JSON fixtures are
trimmed to a handful of real rows (real Unique/Date/Name values, not
invented) rather than the full 967/92-row live responses.

YouTubeAssetFinder._extract_info is monkeypatched in every delegation
test, same pattern tests/test_primegov.py already uses -- this exercises
BoardDocsAssetFinder's own page/API parsing and delegation logic without
making a real yt-dlp call (this repo never fetches youtube.com/youtu.be
from a dev/test machine, see CLAUDE.md's YouTube bullet).
"""

import json

from app.platforms.base import detect_platform
from app.platforms.boarddocs import (
    BoardDocsAssetFinder,
    _extract_meeting_unique,
    _parse_agenda_items,
    _parse_tenant,
    is_boarddocs_tenant_url,
)
from app.platforms.youtube import YouTubeAssetFinder

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture

TALGOV_PUBLIC = "https://go.boarddocs.com/fla/talgov/Board.nsf/Public"
TALGOV_LIST = "https://go.boarddocs.com/fla/talgov/Board.nsf/BD-GETMeetingsListForSEO"
TALGOV_AGENDA = "https://go.boarddocs.com/fla/talgov/Board.nsf/VIDEO-GetAgenda?open"

CCSCHOOLS_PUBLIC = "https://go.boarddocs.com/az/ccschools/Board.nsf/Public"
CCSCHOOLS_LIST = (
    "https://go.boarddocs.com/az/ccschools/Board.nsf/BD-GETMeetingsListForSEO"
)
CCSCHOOLS_AGENDA = (
    "https://go.boarddocs.com/az/ccschools/Board.nsf/VIDEO-GetAgenda?open"
)
CCSCHOOLS_VIDEO_MEETING = (
    "https://go.boarddocs.com/az/ccschools/Board.nsf/goto?open&id=DGTU4S7A4526"
)
CCSCHOOLS_NOVIDEO_MEETING = (
    "https://go.boarddocs.com/az/ccschools/Board.nsf/goto?open&id=DNYMEA5ADC4E"
)

AUSTINISD_PUBLIC = "https://go.boarddocs.com/tx/austinisd/Board.nsf/Public"
AUSTINISD_LIST = (
    "https://go.boarddocs.com/tx/austinisd/Board.nsf/BD-GETMeetingsListForSEO"
)
AUSTINISD_AGENDA = (
    "https://go.boarddocs.com/tx/austinisd/Board.nsf/VIDEO-GetAgenda?open"
)
AUSTINISD_MEETING = (
    "https://go.boarddocs.com/tx/austinisd/Board.nsf/goto?open&id=DVYR9Q6CF0B4"
)


def _fake_extract_info(video_id):
    # Deliberately generic/wrong-looking values -- every test below
    # asserts BoardDocs' own real title/date (from BD-GETMeetingsListForSEO)
    # wins over whatever YouTube's metadata says, the same "this tenant's
    # own signal beats the delegated platform's" choice primegov.py makes
    # for jurisdiction/date.
    return {
        "title": "generic youtube title, should be overridden",
        "uploader": "SomeChannel",
        "upload_date": "20200101",
    }


# --- detect_platform() / URL parsing -------------------------------------


def test_detect_platform_claims_tenant_public_page():
    assert detect_platform(TALGOV_PUBLIC) == "boarddocs"


def test_detect_platform_claims_meeting_level_goto_url():
    assert detect_platform(CCSCHOOLS_VIDEO_MEETING) == "boarddocs"


def test_detect_platform_claims_vpublic_url():
    assert (
        detect_platform("https://go.boarddocs.com/az/ccschools/Board.nsf/vpublic?open")
        == "boarddocs"
    )


def test_detect_platform_does_not_claim_bare_host():
    # No real tenant path -- the bare host alone is never a real per-
    # government page, same reasoning CORPORATE_HOSTS_BY_PLATFORM's own
    # comment gives for other vendor hosts.
    assert detect_platform("https://go.boarddocs.com/") == "unknown"


def test_detect_platform_does_not_claim_unrelated_host():
    assert (
        detect_platform("https://example.com/fla/talgov/Board.nsf/Public") == "unknown"
    )


def test_is_boarddocs_tenant_url_lowercases_host():
    assert is_boarddocs_tenant_url(
        "https://GO.BOARDDOCS.COM/fla/talgov/Board.nsf/Public"
    )


def test_parse_tenant_extracts_state_and_slug():
    assert _parse_tenant(TALGOV_PUBLIC) == ("fla", "talgov")
    assert _parse_tenant(CCSCHOOLS_VIDEO_MEETING) == ("az", "ccschools")


def test_extract_meeting_unique_from_goto_url():
    # The real query string is "open&id={Unique}" -- no "=" on the first
    # token, which parse_qs already drops rather than raising on.
    assert _extract_meeting_unique(CCSCHOOLS_VIDEO_MEETING) == "DGTU4S7A4526"


def test_extract_meeting_unique_none_on_tenant_level_url():
    assert _extract_meeting_unique(TALGOV_PUBLIC) is None


# --- _parse_agenda_items(): real VIDEO-GetAgenda fragments ----------------


def test_parse_agenda_items_real_talgov_video_fragment():
    fragment = load_fixture("boarddocs", "talgov_video_getagenda.html")
    items = _parse_agenda_items(fragment)
    assert len(items) == 27
    first = items[0]
    assert first.start == 12.0
    assert first.end == 37.0
    assert first.text.startswith("1. CALL TO ORDER --")


def test_parse_agenda_items_real_ccschools_video_fragment():
    fragment = load_fixture("boarddocs", "ccschools_video_getagenda.html")
    items = _parse_agenda_items(fragment)
    assert len(items) == 10
    assert all(items[i].start <= items[i + 1].start for i in range(len(items) - 1))


def test_parse_agenda_items_empty_for_novideo_fragment():
    # Real, confirmed-live shape: a meeting with no video still returns
    # category headings but NO timed <li class="item"> rows at all.
    fragment = load_fixture("boarddocs", "ccschools_novideo_getagenda.html")
    assert _parse_agenda_items(fragment) == []


# --- BoardDocsAssetFinder._extract_org_name(): real tenant pages ---------


def test_extract_org_name_prefers_sitetitle2_when_not_address_shaped():
    # Real shape: Tallahassee's SiteTitle2 is a clean org name.
    html = load_fixture("boarddocs", "talgov_public.html")
    assert BoardDocsAssetFinder._extract_org_name(html) == "City of Tallahassee"


def test_extract_org_name_falls_back_to_title_tag_when_sitetitle2_is_an_address():
    # Real, confirmed-live gap: Colorado City schools' SiteTitle2 is "PO
    # Box 309 Colorado City, AZ 86021" -- an address, not an org name --
    # so this must fall back to the <title> tag ("Colorado City Unified
    # School District BoardDocs® LT") with the BoardDocs suffix stripped.
    html = load_fixture("boarddocs", "ccschools_public.html")
    assert (
        BoardDocsAssetFinder._extract_org_name(html)
        == "Colorado City Unified School District"
    )


def test_extract_org_name_falls_back_for_austinisd_address_too():
    html = load_fixture("boarddocs", "austinisd_public.html")
    assert (
        BoardDocsAssetFinder._extract_org_name(html)
        == "Austin Independent School District"
    )


def test_extract_video_service_reads_real_flag():
    talgov_html = load_fixture("boarddocs", "talgov_public.html")
    austin_html = load_fixture("boarddocs", "austinisd_public.html")
    assert BoardDocsAssetFinder._extract_video_service(talgov_html) == "1"
    assert BoardDocsAssetFinder._extract_video_service(austin_html) == "2"


# --- full resolve(): real fixtures, mocked HTTP ---------------------------


async def test_resolve_tenant_level_talgov_finds_newest_video(monkeypatch):
    # Real case: the newest Tallahassee meeting already has a video (6 of
    # 6 checked live do), so the tenant-level walk needs exactly one POST.
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    routes = {
        TALGOV_PUBLIC: FakeResponse(
            200, text=load_fixture("boarddocs", "talgov_public.html"), url=TALGOV_PUBLIC
        ),
        TALGOV_LIST: FakeResponse(
            200,
            text=load_fixture("boarddocs", "talgov_meetings_list.json"),
            url=TALGOV_LIST,
        ),
    }
    post_routes = {
        TALGOV_AGENDA: FakeResponse(
            200,
            text=load_fixture("boarddocs", "talgov_video_getagenda.html"),
            url=TALGOV_AGENDA,
        ),
    }

    with mock_session(routes, post_routes=post_routes):
        result = await BoardDocsAssetFinder().resolve(TALGOV_PUBLIC)

    assert result.platform == "youtube"  # delegated finder's own name, unchanged
    assert result.video_url == "https://www.youtube.com/embed/IwHZSEpgwDw"
    assert result.external_id == "youtube:IwHZSEpgwDw"
    assert (
        result.source_url
        == "https://go.boarddocs.com/fla/talgov/Board.nsf/goto?open&id=DU8S8U718044"
    )
    assert result.jurisdiction == "City of Tallahassee, FL"
    assert result.title == "City Commission Meeting"
    assert result.date == "2026-09-09"
    assert len(result.agenda_items) == 27
    assert result.origin_host == "go.boarddocs.com"


async def test_resolve_meeting_level_ccschools_video(monkeypatch):
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    routes = {
        CCSCHOOLS_PUBLIC: FakeResponse(
            200,
            text=load_fixture("boarddocs", "ccschools_public.html"),
            url=CCSCHOOLS_PUBLIC,
        ),
        CCSCHOOLS_LIST: FakeResponse(
            200,
            text=load_fixture("boarddocs", "ccschools_meetings_list.json"),
            url=CCSCHOOLS_LIST,
        ),
    }
    post_routes = {
        CCSCHOOLS_AGENDA: FakeResponse(
            200,
            text=load_fixture("boarddocs", "ccschools_video_getagenda.html"),
            url=CCSCHOOLS_AGENDA,
        ),
    }

    with mock_session(routes, post_routes=post_routes):
        result = await BoardDocsAssetFinder().resolve(CCSCHOOLS_VIDEO_MEETING)

    assert result.platform == "youtube"
    assert result.external_id == "youtube:jbnk6tAyhlw"
    assert result.source_url == CCSCHOOLS_VIDEO_MEETING
    assert result.jurisdiction == "Colorado City Unified School District, AZ"
    assert result.date == "2025-06-09"
    assert len(result.agenda_items) == 10


async def test_resolve_ccschools_meeting_with_no_video_is_clean_not_an_error():
    routes = {
        CCSCHOOLS_PUBLIC: FakeResponse(
            200,
            text=load_fixture("boarddocs", "ccschools_public.html"),
            url=CCSCHOOLS_PUBLIC,
        ),
        CCSCHOOLS_LIST: FakeResponse(
            200,
            text=load_fixture("boarddocs", "ccschools_meetings_list.json"),
            url=CCSCHOOLS_LIST,
        ),
    }
    post_routes = {
        CCSCHOOLS_AGENDA: FakeResponse(
            200,
            text=load_fixture("boarddocs", "ccschools_novideo_getagenda.html"),
            url=CCSCHOOLS_AGENDA,
        ),
    }

    with mock_session(routes, post_routes=post_routes):
        result = await BoardDocsAssetFinder().resolve(CCSCHOOLS_NOVIDEO_MEETING)

    assert result.platform == "boarddocs"  # no delegation attempted
    assert result.video_url is None
    assert result.video_warnings == ["No video for this BoardDocs meeting."]
    assert result.agenda_items == []


async def test_resolve_negative_control_austinisd_is_clean_not_an_error():
    # Austin ISD: videoservice=2 (Vimeo), confirmed live 0 of 40 recent
    # meetings have a real video id -- the mechanism must degrade cleanly
    # for a specific meeting on this tenant too, not error or accidentally
    # delegate to Vimeo with an empty id.
    routes = {
        AUSTINISD_PUBLIC: FakeResponse(
            200,
            text=load_fixture("boarddocs", "austinisd_public.html"),
            url=AUSTINISD_PUBLIC,
        ),
        AUSTINISD_LIST: FakeResponse(
            200,
            text=load_fixture("boarddocs", "austinisd_meetings_list.json"),
            url=AUSTINISD_LIST,
        ),
    }
    post_routes = {
        AUSTINISD_AGENDA: FakeResponse(
            200,
            text=load_fixture("boarddocs", "austinisd_video_getagenda.html"),
            url=AUSTINISD_AGENDA,
        ),
    }

    with mock_session(routes, post_routes=post_routes):
        result = await BoardDocsAssetFinder().resolve(AUSTINISD_MEETING)

    assert result.platform == "boarddocs"
    assert result.video_url is None
    assert result.video_warnings == ["No video for this BoardDocs meeting."]


async def test_resolve_returns_no_video_immediately_when_videoservice_is_zero():
    # Synthetic, minimal tenant-page HTML -- only `bd.videoservice = "0";`
    # matters here. The real shape (a tenant page with this exact flag
    # value) is confirmed live on three real negative controls named in
    # docs/investigations/boarddocs_video_adapter.md (Seat Pleasant MD,
    # San Bernardino USD CA, Vista USD CA) -- not re-fetched this WO to
    # stay within the politeness cap (2 real tenants + 4 negative
    # controls already fetched). This test's only job is to prove the
    # adapter makes NO further requests (no list, no POST) once the flag
    # says there's no video service at all -- enforced by mock_session
    # itself (an unmocked GET/POST raises AssertionError).
    url = "https://go.boarddocs.com/md/cospmd/Board.nsf/Public"
    html = """
    <html><head><title>Town of Seat Pleasant BoardDocs® LT</title></head>
    <body><script>
    bd.videoservice = "0";
    </script>
    <div id="SiteTitle2">Town of Seat Pleasant</div>
    </body></html>
    """
    routes = {url: FakeResponse(200, text=html, url=url)}

    with mock_session(routes):
        result = await BoardDocsAssetFinder().resolve(url)

    assert result.platform == "boarddocs"
    assert result.video_url is None
    assert result.video_warnings == [
        "This BoardDocs tenant has no video service enabled."
    ]
    assert result.jurisdiction == "Town of Seat Pleasant, MD"


async def test_resolve_unknown_url_shape_returns_warning_not_error():
    result = await BoardDocsAssetFinder().resolve("https://go.boarddocs.com/nonsense")
    assert result.video_warnings == ["Could not read a BoardDocs tenant from this URL."]


# --- newest-past-meetings walk / cap --------------------------------------


def test_newest_past_meetings_filters_future_dates_and_caps_at_40():
    import datetime

    today = datetime.date.today()
    future = (today + datetime.timedelta(days=30)).isoformat() + "T00:00:00Z"
    past = (today - datetime.timedelta(days=1)).isoformat() + "T00:00:00Z"
    meetings = [{"Unique": "FUTURE", "Date": future}] + [
        {"Unique": f"M{i}", "Date": past} for i in range(50)
    ]
    result = BoardDocsAssetFinder._newest_past_meetings(meetings)
    assert all(m["Unique"] != "FUTURE" for m in result)
    assert len(result) == 40


async def test_resolve_tenant_level_walks_past_a_no_video_meeting(monkeypatch):
    # Real case: Colorado City's own newest meeting has no video (the
    # 2025-06-09 one, further down the list, does). This exercises the
    # multi-candidate walk directly -- _fetch_video_id is monkeypatched
    # per-candidate since aiohttp_mock's session mock can't return
    # different bodies for repeated calls to the same POST URL (id lives
    # in the body, not the URL).
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    calls = []

    async def fake_fetch_video_id(self, session, st, slug, headers, unique):
        calls.append(unique)
        if unique == "DGTU4S7A4526":
            return "jbnk6tAyhlw", load_fixture(
                "boarddocs", "ccschools_video_getagenda.html"
            )
        return None, load_fixture("boarddocs", "ccschools_novideo_getagenda.html")

    monkeypatch.setattr(BoardDocsAssetFinder, "_fetch_video_id", fake_fetch_video_id)

    routes = {
        CCSCHOOLS_PUBLIC: FakeResponse(
            200,
            text=load_fixture("boarddocs", "ccschools_public.html"),
            url=CCSCHOOLS_PUBLIC,
        ),
        CCSCHOOLS_LIST: FakeResponse(
            200,
            text=load_fixture("boarddocs", "ccschools_meetings_list.json"),
            url=CCSCHOOLS_LIST,
        ),
    }

    with mock_session(routes):
        result = await BoardDocsAssetFinder().resolve(CCSCHOOLS_PUBLIC)

    assert calls[0] != "DGTU4S7A4526"  # walked past at least one no-video meeting
    assert "DGTU4S7A4526" in calls
    assert result.platform == "youtube"
    assert result.external_id == "youtube:jbnk6tAyhlw"


def test_meetings_list_fixtures_are_real_and_well_formed():
    # Guards the fixtures themselves against an accidental hand-edit that
    # breaks their "real data, trimmed" property.
    for name, expected_unique in [
        ("talgov_meetings_list.json", "DU8S8U718044"),
        ("ccschools_meetings_list.json", "DGTU4S7A4526"),
        ("austinisd_meetings_list.json", None),
    ]:
        data = json.loads(load_fixture("boarddocs", name))
        assert isinstance(data, list) and data
        for row in data:
            assert {"Name", "Description", "Unique", "Date"} <= row.keys()
        if expected_unique:
            assert any(row["Unique"] == expected_unique for row in data)
