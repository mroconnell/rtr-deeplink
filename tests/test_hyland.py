from app.platforms.hyland import HylandAssetFinder

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture

# Hyland "OnBase Agenda Online" -- confirmed live 2026-08-16 across 3 real
# customers on 3 different hosting domains (see hyland.py's own module
# docstring for the full investigation). Fixtures below are the real,
# unmodified `curl` responses for both the main ViewMeeting page and the
# ViewMeetingAgenda AJAX endpoint, for each customer.

TUCSON_URL = "https://tucsonaz.hylandcloud.com/221agendaonline/Meetings/ViewMeeting?doctype=2&id=1956"
TUCSON_AGENDA_URL = (
    "https://tucsonaz.hylandcloud.com/221agendaonline/Meetings/ViewMeetingAgenda?meetingId=1956&type=2"
)

MARICOPA_URL = "https://mccobagenda.databankcloud.com/AgendaOnline/Meetings/ViewMeeting?id=4694&doctype=3"
MARICOPA_AGENDA_URL = (
    "https://mccobagenda.databankcloud.com/AgendaOnline/Meetings/ViewMeetingAgenda?meetingId=4694&type=3"
)

SACRAMENTO_URL = "https://agendanet.saccounty.gov/BoardofSupervisors/Meetings/ViewMeeting?id=10231&doctype=1"
SACRAMENTO_AGENDA_URL = (
    "https://agendanet.saccounty.gov/BoardofSupervisors/Meetings/ViewMeetingAgenda?meetingId=10231&type=1"
)

# Version B (converted-Word-document UI) -- found 2026-08-16 via a plain
# web search, not enumeration. Both `Meetings/ViewMeetingAgenda` fetches
# below land on the real generic "Error - OnBase Agenda Online" page
# (confirmed live: aiohttp follows the real 302 automatically), which is
# what drives the adapter's fallback to `Documents/ViewAgenda`.
SANTABARBARA_URL = "https://docs.santabarbaraca.gov/OnBaseAgendaOnline/Meetings/ViewMeeting?id=1184&doctype=1"
SANTABARBARA_AGENDA_A_URL = (
    "https://docs.santabarbaraca.gov/OnBaseAgendaOnline/Meetings/ViewMeetingAgenda?meetingId=1184&type=1"
)
SANTABARBARA_AGENDA_B_URL = (
    "https://docs.santabarbaraca.gov/OnBaseAgendaOnline/Documents/ViewAgenda?meetingId=1184&type=agenda&doctype=1"
)

CONCORD_URL = "https://stream2.ci.concord.ca.us/OnBaseAgendaOnline/Meetings/ViewMeeting?id=1413&doctype=1"
CONCORD_AGENDA_A_URL = (
    "https://stream2.ci.concord.ca.us/OnBaseAgendaOnline/Meetings/ViewMeetingAgenda?meetingId=1413&type=1"
)
CONCORD_AGENDA_B_URL = (
    "https://stream2.ci.concord.ca.us/OnBaseAgendaOnline/Documents/ViewAgenda?meetingId=1413&type=agenda&doctype=1"
)


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
        TUCSON_AGENDA_URL: FakeResponse(status=200, text=agenda_html, url=TUCSON_AGENDA_URL),
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
    # No video means no itemEventPoints to join against -- agenda_items
    # (a timestamped list) must stay empty; the real per-meeting agenda
    # URL is offered instead, not the OnBase site root a generic scan
    # would fall back to.
    assert result.agenda_items == []
    assert result.agenda_link == TUCSON_AGENDA_URL


async def test_resolve_maricopa_real_video_and_timestamped_agenda_items():
    # Maricopa County's page has ZERO static jurisdiction/title text
    # anywhere (confirmed: no meta, no h1, no agenda-link title attribute)
    # -- title/date come entirely from the AJAX agenda endpoint, and
    # jurisdiction entirely from the known-domain registry.
    html = load_fixture("hyland", "maricopa_view_meeting.html")
    agenda_html = load_fixture("hyland", "maricopa_view_meeting_agenda.html")
    routes = {
        MARICOPA_URL: FakeResponse(status=200, text=html, url=MARICOPA_URL),
        MARICOPA_AGENDA_URL: FakeResponse(status=200, text=agenda_html, url=MARICOPA_AGENDA_URL),
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
        SACRAMENTO_AGENDA_URL: FakeResponse(status=200, text=agenda_html, url=SACRAMENTO_AGENDA_URL),
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
    notfound_html = load_fixture("hyland", "santabarbara_view_meeting_agenda_notfound.html")
    doc_html = load_fixture("hyland", "santabarbara_view_agenda_document.html")
    routes = {
        SANTABARBARA_URL: FakeResponse(status=200, text=html, url=SANTABARBARA_URL),
        SANTABARBARA_AGENDA_A_URL: FakeResponse(status=200, text=notfound_html, url=SANTABARBARA_AGENDA_A_URL),
        SANTABARBARA_AGENDA_B_URL: FakeResponse(status=200, text=doc_html, url=SANTABARBARA_AGENDA_B_URL),
    }

    with mock_session(routes):
        result = await HylandAssetFinder().resolve(SANTABARBARA_URL)

    assert result.platform == "hyland"
    assert result.title == "Regular City Council Meeting"
    assert result.date == "2026-08-11"
    assert result.jurisdiction == "Santa Barbara, CA"
    # This customer has no video at all (same as Tucson) -- no
    # itemEventPoints on the main page, so no timestamps to join agenda
    # items against even though real item text exists in the document.
    assert result.video_url is None
    assert result.agenda_items == []
    assert result.agenda_link == SANTABARBARA_AGENDA_B_URL


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
        CONCORD_AGENDA_A_URL: FakeResponse(status=200, text=notfound_html, url=CONCORD_AGENDA_A_URL),
        CONCORD_AGENDA_B_URL: FakeResponse(status=200, text=doc_html, url=CONCORD_AGENDA_B_URL),
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
        'Presentation – to Karen Sakata, Diablo Japanese American Club, proclaiming '
        'February 19, 2026, as "Japanese American Incarceration During World War II '
        'Day" in the City of Concord. Presentation by Mayor Nakamura .'
    )
    # Real video + real agenda_items means no need for the link-only
    # fallback.
    assert result.agenda_link is None


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
