from app.platforms.hyland import (
    _AGENDA_ITEM_NEW_RE,
    _AGENDA_ITEM_RE,
    HylandAssetFinder,
)
from app.platforms.youtube import YouTubeAssetFinder

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture

# Hyland "OnBase Agenda Online" -- confirmed live 2026-08-16 across 3 real
# customers on 3 different hosting domains (see hyland.py's own module
# docstring for the full investigation). Fixtures below are the real,
# unmodified `curl` responses for both the main ViewMeeting page and the
# ViewMeetingAgenda AJAX endpoint, for each customer.

TUCSON_URL = "https://tucsonaz.hylandcloud.com/221agendaonline/Meetings/ViewMeeting?doctype=2&id=1956"
TUCSON_AGENDA_URL = "https://tucsonaz.hylandcloud.com/221agendaonline/Meetings/ViewMeetingAgenda?meetingId=1956&type=2"

MARICOPA_URL = "https://mccobagenda.databankcloud.com/AgendaOnline/Meetings/ViewMeeting?id=4694&doctype=3"
MARICOPA_AGENDA_URL = "https://mccobagenda.databankcloud.com/AgendaOnline/Meetings/ViewMeetingAgenda?meetingId=4694&type=3"

SACRAMENTO_URL = "https://agendanet.saccounty.gov/BoardofSupervisors/Meetings/ViewMeeting?id=10231&doctype=1"
SACRAMENTO_AGENDA_URL = "https://agendanet.saccounty.gov/BoardofSupervisors/Meetings/ViewMeetingAgenda?meetingId=10231&type=1"

# Version B (converted-Word-document UI) -- found 2026-08-16 via a plain
# web search, not enumeration. Both `Meetings/ViewMeetingAgenda` fetches
# below land on the real generic "Error - OnBase Agenda Online" page
# (confirmed live: aiohttp follows the real 302 automatically), which is
# what drives the adapter's fallback to `Documents/ViewAgenda`.
SANTABARBARA_URL = "https://docs.santabarbaraca.gov/OnBaseAgendaOnline/Meetings/ViewMeeting?id=1184&doctype=1"
SANTABARBARA_AGENDA_A_URL = "https://docs.santabarbaraca.gov/OnBaseAgendaOnline/Meetings/ViewMeetingAgenda?meetingId=1184&type=1"
SANTABARBARA_AGENDA_B_URL = "https://docs.santabarbaraca.gov/OnBaseAgendaOnline/Documents/ViewAgenda?meetingId=1184&type=agenda&doctype=1"

CONCORD_URL = "https://stream2.ci.concord.ca.us/OnBaseAgendaOnline/Meetings/ViewMeeting?id=1413&doctype=1"
CONCORD_AGENDA_A_URL = "https://stream2.ci.concord.ca.us/OnBaseAgendaOnline/Meetings/ViewMeetingAgenda?meetingId=1413&type=1"
CONCORD_AGENDA_B_URL = "https://stream2.ci.concord.ca.us/OnBaseAgendaOnline/Documents/ViewAgenda?meetingId=1413&type=agenda&doctype=1"


async def test_resolve_tucson_no_video_ever_falls_back_to_agenda_link():
    # Tucson's OnBase instance never has video (confirmed across 2
    # independent meeting ids) -- but unlike BACKLOG.md's earlier
    # conclusion, title/date ARE real and statically fetchable from the
    # ViewMeetingAgenda AJAX endpoint once the real `type` value
    # (matching `doctype`, not the page's own literal `AGENDATYPEVALUE`
    # JS placeholder) is substituted.
    html = load_fixture("hyland", "tucson_view_meeting.html")
    agenda_html = load_fixture("hyland", "tucson_view_meeting_agenda.html")
    routes = {
        TUCSON_URL: FakeResponse(status=200, text=html, url=TUCSON_URL),
        TUCSON_AGENDA_URL: FakeResponse(
            status=200, text=agenda_html, url=TUCSON_AGENDA_URL
        ),
    }

    with mock_session(routes):
        result = await HylandAssetFinder().resolve(TUCSON_URL)

    assert result.platform == "hyland"
    assert result.title == "REGULAR MEETING"
    assert result.date == "2026-08-05"
    assert result.jurisdiction == "Tucson, AZ"
    assert result.video_url is None
    assert result.video_format is None
    assert result.video_warnings == ["No video found on this page."]
    # No video means no itemEventPoints, so nothing to join agenda items
    # against for *timestamps* -- but the agenda itself is real and fully
    # parseable, and until WO-63 all 27 items were discarded on that
    # basis, leaving a page holding nothing at all. They now come back
    # untimed (start=0), in document order, which is agenda order.
    assert len(result.agenda_items) == 27
    assert all(item.start == 0 for item in result.agenda_items)
    assert all(item.text for item in result.agenda_items)
    # Nulled once real items exist -- hyland.py's pre-existing rule
    # against surfacing a redundant link to the document just parsed.
    assert result.agenda_link is None


async def test_resolve_maricopa_real_video_and_timestamped_agenda_items():
    # Maricopa County's page has ZERO static jurisdiction/title text
    # anywhere (confirmed: no meta, no h1, no agenda-link title attribute)
    # -- title/date come entirely from the AJAX agenda endpoint, and
    # jurisdiction entirely from the known-domain registry.
    html = load_fixture("hyland", "maricopa_view_meeting.html")
    agenda_html = load_fixture("hyland", "maricopa_view_meeting_agenda.html")
    routes = {
        MARICOPA_URL: FakeResponse(status=200, text=html, url=MARICOPA_URL),
        MARICOPA_AGENDA_URL: FakeResponse(
            status=200, text=agenda_html, url=MARICOPA_AGENDA_URL
        ),
    }

    with mock_session(routes):
        result = await HylandAssetFinder().resolve(MARICOPA_URL)

    assert result.platform == "hyland"
    assert result.title == "Formal"
    assert result.date == "2026-07-15"
    assert result.jurisdiction == "Maricopa County, AZ"
    # Real JW Player CloudFront HLS URL, with the `&amp;token=` entity
    # correctly decoded (media_scan.scan_media_urls handles this).
    assert result.video_url == (
        "https://d27q9sfkph1oc9.cloudfront.net/mcvod/mediacache/"
        "amlst:bflpMUYBlYu96PbH56n6zUX9NkRlJat1kVQHOaTmXjKegBuoB8Td6xASbeC3xUim/"
        "playlist.m3u8?instance=1&token=l9kpydObE-b8MvjCfLjsgBd3RExAlGmgAU2TfxWdXUGdZMm-ZQ"
    )
    assert result.video_format == "m3u8"
    assert result.video_warnings == []

    # Real, joined agenda outline: item text from the AJAX page's
    # `accessible-item-text` spans, start time from the main page's
    # inline `itemEventPoints` map, joined on the shared numeric item id
    # both pages reference via `loadAgendaItem({id})`.
    assert len(result.agenda_items) == 48
    first = result.agenda_items[0]
    assert first.text == "CHILD SUPPORT AWARENESS PROCLAMATION"
    assert first.start == 355.0
    assert first.end == 824.0
    # Real video means agenda_items covers it -- no need for the weaker
    # link-only fallback.
    assert result.agenda_link is None


async def test_resolve_sacramento_multiline_item_text_is_normalized():
    html = load_fixture("hyland", "sacramento_view_meeting.html")
    agenda_html = load_fixture("hyland", "sacramento_view_meeting_agenda.html")
    routes = {
        SACRAMENTO_URL: FakeResponse(status=200, text=html, url=SACRAMENTO_URL),
        SACRAMENTO_AGENDA_URL: FakeResponse(
            status=200, text=agenda_html, url=SACRAMENTO_AGENDA_URL
        ),
    }

    with mock_session(routes):
        result = await HylandAssetFinder().resolve(SACRAMENTO_URL)

    assert result.platform == "hyland"
    assert result.title == "BOARD OF SUPERVISORS MEETING"
    assert result.date == "2026-08-11"
    assert result.jurisdiction == "Sacramento County, CA"
    assert result.video_format == "m3u8"
    assert result.video_url is not None

    # Real bug caught building this adapter: the source page's own
    # accessible-item-text span carries a raw, un-tagged newline between
    # the item title and its "Supervisorial District(s): ..." line --
    # confirmed via a direct grep of the real fixture, not a parsing
    # artifact -- collapsed to a single space rather than left as a raw
    # "\r\n" in stored/displayed text.
    first = result.agenda_items[0]
    assert "\r" not in first.text and "\n" not in first.text
    assert first.text == (
        "BARK Of Supervisors Adoptable Pet Update (Animal Care Services) "
        "Supervisorial District(s): All"
    )


async def test_resolve_santabarbara_falls_back_to_version_b_document_endpoint():
    # Santa Barbara runs the real second confirmed UI version of this
    # product ("Version B" in hyland.py's module docstring): the old
    # Meetings/ViewMeetingAgenda endpoint redirects to a generic error
    # page (real content, not a synthetic stub), so the adapter must fall
    # back to Documents/ViewAgenda -- and to the main page's own <title>
    # for title/date, since Version B's agenda document carries no date.
    html = load_fixture("hyland", "santabarbara_view_meeting.html")
    notfound_html = load_fixture(
        "hyland", "santabarbara_view_meeting_agenda_notfound.html"
    )
    doc_html = load_fixture("hyland", "santabarbara_view_agenda_document.html")
    routes = {
        SANTABARBARA_URL: FakeResponse(status=200, text=html, url=SANTABARBARA_URL),
        SANTABARBARA_AGENDA_A_URL: FakeResponse(
            status=200, text=notfound_html, url=SANTABARBARA_AGENDA_A_URL
        ),
        SANTABARBARA_AGENDA_B_URL: FakeResponse(
            status=200, text=doc_html, url=SANTABARBARA_AGENDA_B_URL
        ),
    }

    with mock_session(routes):
        result = await HylandAssetFinder().resolve(SANTABARBARA_URL)

    assert result.platform == "hyland"
    assert result.title == "Regular City Council Meeting"
    assert result.date == "2026-08-11"
    assert result.jurisdiction == "Santa Barbara, CA"
    # This customer has no video at all (same as Tucson), so the main page
    # carries no itemEventPoints. That used to mean agenda_items == [] --
    # this very test's old comment noted the items were discarded "even
    # though real item text exists in the document", which is exactly the
    # content WO-63 stopped throwing away. All 18 come back untimed
    # (start=0), which both renderers already present as a plain unlinked
    # outline.
    assert result.video_url is None
    assert len(result.agenda_items) == 18
    assert result.agenda_items[0].text == "REGULAR CITY COUNCIL MEETING - 2:00 P.M."
    assert all(item.start == 0 for item in result.agenda_items)
    # Nulled because the items now carry the content -- hyland.py's
    # existing "don't surface a redundant link to the document we already
    # parsed" rule, unchanged by WO-63.
    assert result.agenda_link is None


async def test_untimed_agenda_still_renders_as_a_real_agenda_not_an_empty_page():
    """The shape WO-63 was built for, asserted directly on the helper.

    Found by measuring, not by reading code: GET /internal/thin-page-audit
    against production reported 16 content-free pages in the archive and
    14 of them were Hyland. The cause was not a parsing failure --
    _build_agenda_items() returned [] the moment `event_points` was empty,
    before the regex ever ran, so a meeting with no video threw away a
    perfectly good agenda and became a page holding nothing.

    Anchorage is one of those 14 live pages; its real agenda document
    fixture carries 34 items.
    """
    agenda_html = load_fixture("hyland", "anchorage_view_agenda_document.html")

    items = HylandAssetFinder._build_agenda_items(agenda_html, {}, _AGENDA_ITEM_NEW_RE)

    assert len(items) == 34
    assert all(item.start == 0 and item.end == 0 for item in items)
    assert all(item.text.strip() for item in items)
    # More than one item sharing a start is precisely the signal both
    # renderers key on to say "this source doesn't provide real per-item
    # timestamps" and drop the clickable links -- so this shape lands in
    # machinery that already exists rather than needing new template work.
    assert len({item.start for item in items}) == 1


async def test_real_timestamps_still_win_when_the_meeting_has_video():
    """The untimed path must not cannibalise the timestamped one: with a
    real itemEventPoints map, items keep their true seek positions and
    stay sorted by them."""
    agenda_html = load_fixture("hyland", "maricopa_view_meeting_agenda.html")
    main_html = load_fixture("hyland", "maricopa_view_meeting.html")
    event_points = HylandAssetFinder._parse_event_points(main_html)
    assert event_points, "fixture must carry a real itemEventPoints map"

    items = HylandAssetFinder._build_agenda_items(
        agenda_html, event_points, _AGENDA_ITEM_RE
    )

    assert len(items) > 1
    assert len({item.start for item in items}) > 1, "real timestamps, not all zero"
    assert items == sorted(items, key=lambda i: i.start)


async def test_agenda_with_no_parseable_items_is_still_empty():
    """Dropping the event_points gate must not turn unparseable HTML into
    a fake agenda -- the empty result has to survive for the case it was
    actually right about."""
    assert (
        HylandAssetFinder._build_agenda_items(
            "<html>no items</html>", {}, _AGENDA_ITEM_RE
        )
        == []
    )
    assert HylandAssetFinder._build_agenda_items(None, {}, _AGENDA_ITEM_RE) == []
    assert HylandAssetFinder._build_agenda_items("", {}, _AGENDA_ITEM_NEW_RE) == []


async def test_resolve_concord_version_b_multiline_item_text_not_truncated():
    # Real bug caught building Version B support: real item text can span
    # multiple sibling <span> tags inside one <a href="javascript:
    # loadAgendaItem(...)"> -- capturing only the first span (as Version
    # A's regex does) truncates real content down to just "Considering"
    # instead of the full sentence. Confirmed via this exact real fixture.
    html = load_fixture("hyland", "concord_view_meeting.html")
    notfound_html = load_fixture("hyland", "concord_view_meeting_agenda_notfound.html")
    doc_html = load_fixture("hyland", "concord_view_agenda_document.html")
    routes = {
        CONCORD_URL: FakeResponse(status=200, text=html, url=CONCORD_URL),
        CONCORD_AGENDA_A_URL: FakeResponse(
            status=200, text=notfound_html, url=CONCORD_AGENDA_A_URL
        ),
        CONCORD_AGENDA_B_URL: FakeResponse(
            status=200, text=doc_html, url=CONCORD_AGENDA_B_URL
        ),
    }

    with mock_session(routes):
        result = await HylandAssetFinder().resolve(CONCORD_URL)

    assert result.platform == "hyland"
    assert result.title == "Regular Meeting"
    assert result.date == "2026-02-10"
    assert result.jurisdiction == "Concord, CA"
    assert result.video_format == "m3u8"
    assert result.video_url is not None

    assert len(result.agenda_items) == 3
    first = result.agenda_items[0]
    assert first.start == 1093.52
    assert first.end == 2266.52
    assert first.text == (
        "Presentation – to Karen Sakata, Diablo Japanese American Club, proclaiming "
        'February 19, 2026, as "Japanese American Incarceration During World War II '
        'Day" in the City of Concord. Presentation by Mayor Nakamura .'
    )
    # Real video + real agenda_items means no need for the link-only
    # fallback.
    assert result.agenda_link is None


async def test_resolve_delegates_to_youtube_when_no_direct_media_file(monkeypatch):
    # Real gap found 2026-08-16 on a live Municipality of Anchorage, AK
    # meeting: this vendor's own player template supports either a JW
    # Player config (every other confirmed customer) or a plain YouTube
    # iframe embed ("JWPlayer.cshtml or YoutubePlayer.cshtml", per the
    # page's own JS comment) -- media_scan.scan_media_urls only recognizes
    # direct media-file URLs, so this used to come back with no video at
    # all despite a real, playable YouTube embed being right there.
    url = (
        "https://meetings.muni.org/AgendaOnline/Meetings/ViewMeeting?id=6500&doctype=1"
    )
    agenda_a_url = "https://meetings.muni.org/AgendaOnline/Meetings/ViewMeetingAgenda?meetingId=6500&type=1"
    agenda_b_url = "https://meetings.muni.org/AgendaOnline/Documents/ViewAgenda?meetingId=6500&type=agenda&doctype=1"
    html = load_fixture("hyland", "anchorage_view_meeting_youtube.html")
    notfound_html = load_fixture(
        "hyland", "anchorage_view_meeting_agenda_notfound.html"
    )
    doc_html = load_fixture("hyland", "anchorage_view_agenda_document.html")
    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        agenda_a_url: FakeResponse(status=200, text=notfound_html, url=agenda_a_url),
        agenda_b_url: FakeResponse(status=200, text=doc_html, url=agenda_b_url),
    }

    monkeypatch.setattr(
        YouTubeAssetFinder,
        "_extract_info",
        lambda video_id: {
            "title": "Anchorage Platting Board",
            "uploader": "MuniOfAnchorage",
            "upload_date": "20260701",
            "_chosen_track": (
                "WEBVTT\n\n00:00:02.001 --> 00:00:22.555\n♪\n".encode("utf-8"),
                "en",
                True,
            ),
        },
    )

    with mock_session(routes):
        result = await HylandAssetFinder().resolve(url)

    assert result.platform == "hyland"
    # Real title/date/jurisdiction still come from this adapter's own
    # extraction, not YouTube's own metadata -- delegation is for video +
    # transcript only, matching every other delegator in this codebase.
    assert result.title == "Platting Board - July 1, 2026"
    assert result.jurisdiction == "Anchorage, AK"
    assert result.video_url == "https://www.youtube.com/embed/92SgT7nRbKw"
    assert result.video_format == "youtube"
    assert result.video_warnings == []
    # Real bonus: a YouTube-backed customer gets a real transcript, a
    # capability no JW-Player customer on this platform has at all.
    assert len(result.segments) == 1
    assert result.segments[0].text == "♪"
    assert result.transcript_language == "en"
    # Real timestamped agenda outline still works independent of which
    # video source was used.
    assert len(result.agenda_items) == 3


async def test_resolve_no_meeting_id_skips_agenda_fetch_gracefully():
    url = "https://tucsonaz.hylandcloud.com/221agendaonline/Meetings/ViewMeeting"
    html = "<html><head></head><body>No query string at all.</body></html>"
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await HylandAssetFinder().resolve(url)

    assert result.platform == "hyland"
    assert result.title is None
    assert result.agenda_items == []
    assert result.agenda_link is None
    assert result.video_url is None
