"""Tests for Chicago's City Clerk ELMS adapter
(app/platforms/chicago_elms.py), WO-29.

Both fixtures are real, unmodified live captures taken 2026-08-21 from
the public, unauthenticated
`api.chicityclerkelms.chicago.gov/meeting-agenda/{meetingId}` endpoint --
see chicago_elms.py's own module docstring for the investigation, and
BACKLOG.md's 2026-08-10/11/12 entries for how the API was found in the
first place (the meeting page's raw HTML has zero mention of Vimeo; the
video is injected client-side from this API).

- `meeting_budget_committee_2026-07-16.json` -- the real "Committee on
  Budget and Government Operations" mid-year budget hearing, whose
  `videoLink` is the numeric-showcase-id shape
  (`vimeo.com/showcase/8925576?video=1210310337`), with an empty
  `agenda.groups` and a real Agenda PDF alongside a `.crdownload`
  Notice file.
- `meeting_city_council_2026-07-15.json` -- the real full City Council
  meeting, whose `videoLink` is the human-slug showcase shape, and whose
  `agenda.groups[0].items` holds 473 real agenda items -- with no
  timestamps of any kind, which is exactly why `agenda_items` stays
  empty (see the dedicated test below).

`transcriptLink` is present in the API schema and empty on both, and on
all five real samples ever checked (2020-2026). Nothing here claims a
caption path.
"""

import json

import pytest

from app.platforms.base import detect_platform
from app.platforms.chicago_elms import ChicagoElmsAssetFinder, extract_meeting_id
from app.utils import url_guard

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture

BUDGET_ID = "B2E99313-3D76-F111-AB0C-001DD80BE073"
COUNCIL_ID = "DF5C52EA-0D6B-F111-A823-001DD8019941"
BUDGET_URL = f"https://chicityclerkelms.chicago.gov/Meeting/?meetingId={BUDGET_ID}"
COUNCIL_URL = f"https://chicityclerkelms.chicago.gov/Meeting/?meetingId={COUNCIL_ID}"
API = "https://api.chicityclerkelms.chicago.gov/meeting-agenda/"


@pytest.fixture(autouse=True)
def _fake_public_dns(monkeypatch):
    """See test_generic_fallback.py's identical fixture -- this suite is
    network-free, so guarded_get()'s real hostname resolution is patched
    out."""
    monkeypatch.setattr(
        url_guard, "_resolve_hostname", lambda hostname: ["93.184.216.34"]
    )


@pytest.fixture(autouse=True)
def _no_headless_captions(monkeypatch):
    """Every `.resolve()` here delegates to `VimeoAssetFinder.
    resolve_video_id()`, which (as of 2026-08-31, see vimeo.py's own
    docstring) unconditionally attempts a real headless-browser caption
    fetch -- see test_vimeo.py's identical fixture for the full
    reasoning. Without this, these tests launch a real Chromium and, in
    at least one real environment, hang indefinitely rather than failing
    fast (confirmed live -- the module-level browser/event-loop reuse in
    `headless_browser.py` doesn't survive a fresh per-test event loop
    cleanly). Keeps this suite exactly as it was before that change:
    network-free, video-only."""
    from app.platforms.headless_browser import HeadlessBrowserUnavailable

    async def _unavailable(url, **kwargs):
        raise HeadlessBrowserUnavailable("no headless browser in tests")

    monkeypatch.setattr("app.platforms.vimeo.fetch_via_browser", _unavailable)


def _routes(meeting_id: str, fixture: str, *, oembed: str = None) -> dict:
    api_url = API + meeting_id
    routes = {
        api_url: FakeResponse(
            status=200, text=load_fixture("chicago_elms", fixture), url=api_url
        )
    }
    if oembed:
        from urllib.parse import quote

        # vimeo.py normalizes a showcase URL to vimeo.com/{id} before
        # asking oEmbed -- a showcase URL 404s there, confirmed live.
        url = "https://vimeo.com/api/oembed.json?url=" + quote(oembed, safe="")
        routes[url] = FakeResponse(
            status=200,
            text=load_fixture("vimeo", "oembed_chicago_1210310337.json"),
            url=url,
        )
    return routes


def test_detect_platform_claims_the_elms_domain():
    assert detect_platform(BUDGET_URL) == "chicago_elms"


def test_extract_meeting_id_is_case_insensitive():
    assert extract_meeting_id(BUDGET_URL) == BUDGET_ID
    assert (
        extract_meeting_id("https://chicityclerkelms.chicago.gov/meeting?MeetingID=abc")
        == "abc"
    )
    assert extract_meeting_id("https://chicityclerkelms.chicago.gov/Meeting/") is None


async def test_resolve_budget_committee_meeting():
    routes = _routes(
        BUDGET_ID,
        "meeting_budget_committee_2026-07-16.json",
        oembed="https://vimeo.com/1210310337",
    )
    with mock_session(routes):
        result = await ChicagoElmsAssetFinder().resolve(BUDGET_URL)

    # Attribution stays with Chicago even though the video came from the
    # Vimeo adapter -- so /coverage and /admin/stats show a real Chicago
    # row rather than folding it into generic Vimeo.
    assert result.platform == "chicago_elms"
    assert result.source_url == BUDGET_URL
    assert result.external_id == f"chicago_elms:{BUDGET_ID}"
    assert result.video_url == "https://player.vimeo.com/video/1210310337"
    assert result.video_format == "vimeo"
    # ELMS's own metadata wins over Vimeo's video title/account name.
    assert result.title == "Committee on Budget and Government Operations"
    assert result.date == "2026-07-16"
    assert result.jurisdiction == "Chicago, IL"
    # The real Agenda-typed PDF, not the sibling Notice file whose stored
    # path really does end in ".crdownload" (a real artifact on Chicago's
    # own blob store).
    assert result.agenda_link.endswith(".pdf")
    assert "1c8eaac8-fe8a-472c-b332-1186bde10593" in result.agenda_link


async def test_resolve_city_council_meeting_slug_showcase_shape():
    with mock_session(_routes(COUNCIL_ID, "meeting_city_council_2026-07-15.json")):
        result = await ChicagoElmsAssetFinder().resolve(COUNCIL_URL)

    # `vimeo.com/showcase/citycouncil?video=1209979957` -- a human-slug
    # showcase id rather than the numeric one above.
    assert result.video_url == "https://player.vimeo.com/video/1209979957"
    assert result.title == "City Council"
    assert result.date == "2026-07-15"


async def test_rich_but_untimestamped_agenda_never_becomes_agenda_items():
    """The single most important honesty check in this file.

    The City Council fixture carries 473 real agenda items. Not one has a
    time offset of any kind, so there is nothing to join against a video
    position -- populating `agenda_items` would mean inventing timestamps
    and shipping 473 rows that all seek to 0:00. It stays empty; the real
    agenda PDF goes in `agenda_link` instead.
    """
    payload = json.loads(
        load_fixture("chicago_elms", "meeting_city_council_2026-07-15.json")
    )
    items = payload["agenda"]["groups"][0]["items"]
    assert len(items) > 400
    time_ish = {"start", "startTime", "offset", "seconds", "timestamp", "videoTime"}
    assert not any(time_ish & set(item) for item in items)

    with mock_session(_routes(COUNCIL_ID, "meeting_city_council_2026-07-15.json")):
        result = await ChicagoElmsAssetFinder().resolve(COUNCIL_URL)

    assert result.agenda_items == []
    assert result.agenda_link is not None


async def test_transcript_link_is_empty_on_every_real_sample():
    # Schema-verified, never content-verified (see CLAUDE.md's "don't
    # claim a caption/data path works without a positive example"). If
    # Chicago ever populates it, the adapter surfaces it as a warning
    # rather than guessing at a format -- covered below.
    for fixture in (
        "meeting_budget_committee_2026-07-16.json",
        "meeting_city_council_2026-07-15.json",
    ):
        payload = json.loads(load_fixture("chicago_elms", fixture))
        assert not any((v or "").strip() for v in payload.get("transcriptLink") or [])


async def test_populated_transcript_link_is_surfaced_not_parsed():
    # Synthetic: a one-field edit of the real Budget-committee capture, to
    # exercise the branch no real Chicago meeting has ever hit. The URL is
    # the real blob-store host every one of that meeting's real
    # attachments already uses, not an invented one.
    payload = json.loads(
        load_fixture("chicago_elms", "meeting_budget_committee_2026-07-16.json")
    )
    payload["transcriptLink"] = [
        "https://occprodstoragev1.blob.core.usgovcloudapi.net/"
        "meetingattachmentspublic/some-transcript.txt"
    ]
    api_url = API + BUDGET_ID
    routes = {api_url: FakeResponse(status=200, text=json.dumps(payload), url=api_url)}

    with mock_session(routes):
        result = await ChicagoElmsAssetFinder().resolve(BUDGET_URL)

    assert result.segments == []
    assert any("haven't been able to read yet" in w for w in result.transcript_warnings)


async def test_meeting_without_a_video_says_so():
    payload = json.loads(
        load_fixture("chicago_elms", "meeting_budget_committee_2026-07-16.json")
    )
    payload["videoLink"] = [""]
    api_url = API + BUDGET_ID
    routes = {api_url: FakeResponse(status=200, text=json.dumps(payload), url=api_url)}

    with mock_session(routes):
        result = await ChicagoElmsAssetFinder().resolve(BUDGET_URL)

    assert result.video_url is None
    assert any("No video has been posted" in w for w in result.video_warnings)
    # Still a genuinely useful result: real title, date and agenda PDF.
    assert result.title == "Committee on Budget and Government Operations"
    assert result.agenda_link is not None


async def test_url_without_a_meeting_id_fails_honestly():
    result = await ChicagoElmsAssetFinder().resolve(
        "https://chicityclerkelms.chicago.gov/Meetings"
    )
    assert result.video_url is None
    assert any("one specific meeting" in w for w in result.video_warnings)


async def test_meeting_api_fetch_failure_is_logged(caplog):
    # 2026-08-28: _fetch_meeting()'s non-200 branch used to be silent.
    api_url = API + BUDGET_ID
    routes = {api_url: FakeResponse(status=503, url=api_url)}

    with caplog.at_level("WARNING"):
        with mock_session(routes):
            result = await ChicagoElmsAssetFinder().resolve(BUDGET_URL)

    assert result.video_url is None
    assert any("couldn't load this meeting" in w for w in result.video_warnings)
    assert any("meeting fetch got HTTP 503" in r.message for r in caplog.records)


async def test_unreachable_api_degrades_without_raising():
    with mock_session({}):
        result = await ChicagoElmsAssetFinder().resolve(BUDGET_URL)

    assert result.video_url is None
    assert result.external_id == f"chicago_elms:{BUDGET_ID}"
    assert any("temporarily unreachable" in w for w in result.video_warnings)
