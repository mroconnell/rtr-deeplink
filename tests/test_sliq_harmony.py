"""Tests for Sliq Harmony (app/platforms/sliq_harmony.py) -- WO-921, 2026-09-20.

Every HTML fixture under tests/fixtures/sliq_harmony/ is a REAL page fetched
live on 2026-09-20 from `sg001-harmony.sliq.net` (plain HTTP, honest
User-Agent, 2s between requests), trimmed to the part the adapter reads
(the `<title>` and the server-written `dataModel` block; the caption and
speaker lists are cut to their first 60 and 3 real entries). Tenants:
Arkansas 00284, Colorado 00327, Delaware 00329, Kansas 00287, New Mexico
00293, Oklahoma House 00283, West Virginia Senate 00289 -- see the module
docstring for what was confirmed.

Nothing here is synthetic except where a test says so.
"""

import pytest

from app.platforms.base import CalendarPageError, detect_platform
from app.platforms.sliq_harmony import (
    SliqHarmonyAssetFinder,
    _pick_stream,
    is_sliq_harmony_url,
    parse_event_page,
    parse_listing,
    parse_sliq_url,
)

from conftest import load_fixture

HOST = "sg001-harmony.sliq.net"


def _url(tenant: str, event_id: str, date: str = "20260920") -> str:
    return (
        f"https://{HOST}/{tenant}/Harmony/en/PowerBrowser/PowerBrowserV3/"
        f"{date}/-1/{event_id}"
    )


async def _resolve(monkeypatch, tenant, event_id, fixture):
    html = load_fixture("sliq_harmony", fixture)

    async def fake_fetch(self, session, url):
        assert f"/{tenant}/Harmony/en/" in url
        return html

    monkeypatch.setattr(SliqHarmonyAssetFinder, "_fetch", fake_fetch)
    return await SliqHarmonyAssetFinder().resolve(_url(tenant, event_id))


# --- URL detection ---------------------------------------------------------


def test_detects_event_and_listing_urls():
    assert is_sliq_harmony_url(_url("00287", "22674"))
    assert is_sliq_harmony_url(f"https://{HOST}/00287/Harmony/en/View/RecentEnded/")
    assert detect_platform(_url("00284", "34484")) == "sliq_harmony"


def test_does_not_detect_the_media_hosts_or_other_paths():
    # The HLS host and the vendor's own site are not Harmony pages.
    assert not is_sliq_harmony_url(
        "https://sg002-live.sliq.net/00315-vod/_definst_/2026/09/17/x.mp4/playlist.m3u8"
    )
    assert not is_sliq_harmony_url("https://www.sliq.net/")
    assert not is_sliq_harmony_url(f"https://{HOST}/robots.txt")


def test_parse_sliq_url_pulls_tenant_and_event_id():
    assert parse_sliq_url(_url("00329", "6771")) == (HOST, "00329", "6771")
    assert parse_sliq_url(f"https://{HOST}/00289/Harmony/en/View/") == (
        HOST,
        "00289",
        None,
    )
    assert parse_sliq_url("https://example.com/00289/Harmony/") is None


# --- the pure page parser --------------------------------------------------


def test_parse_event_page_reads_the_datamodel_block():
    page = parse_event_page(
        load_fixture("sliq_harmony", "ar_00284_34484_captions_agenda.html")
    )
    assert page["title"] == "ALC - Occupational Licensing Review Subcommittee"
    assert page["location"] == "Big Mac, Room A [ASR]"
    assert page["status"] == "Adjourned"
    assert page["media_start"] == "2026-09-17T13:30:17"
    assert page["duration"] == 934
    assert page["page_title"].startswith("Arkansas Legislature - ")
    assert set(page["captions"]) == {"en"}
    assert len(page["captions"]["en"]) == 60  # trimmed fixture, real items


def test_pick_stream_rejects_placeholder_and_disabled_streams():
    real = {
        "Enabled": True,
        "IsLive": False,
        "AudioOnly": False,
        "Url": "https://sg002-live.sliq.net/x.mp4/playlist.m3u8",
    }
    assert _pick_stream([real]) == (real, False)
    # Real shapes seen on New Mexico events 81082 ("http://novod.com",
    # Enabled false) and 81083 (empty Url, Enabled false).
    assert _pick_stream([{**real, "Enabled": False, "Url": "http://novod.com"}]) == (
        None,
        False,
    )
    assert _pick_stream([{**real, "Enabled": False, "Url": ""}]) == (None, False)
    # Synthetic: a live stream is not a recording; audio-only is a fallback.
    assert _pick_stream([{**real, "IsLive": True}]) == (None, False)
    audio = {**real, "AudioOnly": True}
    assert _pick_stream([audio, real]) == (real, False)
    assert _pick_stream([audio]) == (audio, True)
    assert _pick_stream(None) == (None, False)


# --- full resolve(): real fixtures ----------------------------------------


async def test_arkansas_video_captions_and_agenda(monkeypatch):
    r = await _resolve(
        monkeypatch, "00284", "34484", "ar_00284_34484_captions_agenda.html"
    )
    assert r.platform == "sliq_harmony"
    assert r.title == "ALC - Occupational Licensing Review Subcommittee"
    assert r.meeting_body == r.title
    assert r.date == "2026-09-17"
    assert r.jurisdiction == "Arkansas State Legislature"
    assert r.meeting_location == "Big Mac, Room A [ASR]"
    assert r.external_id == f"sliq_harmony:{HOST}:00284:34484"
    # A stable URL built from the MEETING's date, not the link's date.
    assert r.source_url == _url("00284", "34484", "20260917")
    assert r.video_format == "m3u8"
    assert r.video_url.endswith("_34484_186.mp4/playlist.m3u8")
    assert r.video_url.startswith("https://sg002-live.sliq.net/")
    assert r.video_warnings == []
    assert r.transcript_warnings == []
    assert r.transcript_language == "en"
    # First real caption: 13:30:34.873 against a 13:30:17 media start.
    first = r.segments[0]
    assert first.text == "it was signed on September"
    assert first.start == pytest.approx(17.873, abs=0.001)
    assert [s.start for s in r.segments] == sorted(s.start for s in r.segments)
    # Agenda: nested children are flattened, offsets are into the video.
    assert r.agenda_items[0].text == "A. Call to Order"
    assert r.agenda_items[0].start == pytest.approx(10.563, abs=0.001)
    assert any(
        a.text.startswith("1. Arkansas State Plant Board") for a in r.agenda_items
    )


async def test_colorado_captions_and_agenda(monkeypatch):
    r = await _resolve(
        monkeypatch, "00327", "18959", "co_00327_18959_captions_agenda.html"
    )
    assert r.jurisdiction == "Colorado General Assembly"
    # Colorado bakes the date into the title; the body name drops it.
    assert r.title == "Capitol Building Advisory Committee [Sep 17, 2026]"
    assert r.meeting_body == "Capitol Building Advisory Committee"
    assert r.video_url and r.video_format == "m3u8"
    assert r.segments and r.agenda_items
    assert r.date == "2026-09-17"


async def test_oklahoma_house_captions_without_agenda(monkeypatch):
    r = await _resolve(
        monkeypatch, "00283", "56259", "ok_00283_56259_captions_no_agenda.html"
    )
    assert r.jurisdiction == "Oklahoma House of Representatives"
    assert r.video_url and r.segments
    assert r.agenda_items == []


async def test_west_virginia_speakers_are_not_turned_into_agenda(monkeypatch):
    r = await _resolve(
        monkeypatch, "00289", "59078", "wv_00289_59078_captions_agenda_speakers.html"
    )
    assert r.jurisdiction == "West Virginia Legislature"
    assert r.video_url and r.segments
    # 3 real agenda items on this event; the (trimmed) speaker turns stay out.
    assert len(r.agenda_items) == 3
    assert not any(a.text.startswith("- ") for a in r.agenda_items)


async def test_delaware_captions_no_agenda(monkeypatch):
    r = await _resolve(monkeypatch, "00329", "6771", "de_00329_6771_captions.html")
    assert r.jurisdiction == "Delaware General Assembly"
    assert r.video_url and r.segments and r.agenda_items == []


async def test_new_mexico_caption_key_named_lang_still_reads(monkeypatch):
    # Real: event 81080's captions sit under the key "lang", not "en".
    r = await _resolve(
        monkeypatch, "00293", "81080", "nm_00293_81080_captions_lang_key.html"
    )
    assert r.jurisdiction == "New Mexico Legislature"
    assert r.segments
    assert r.transcript_language == "en"


async def test_kansas_video_without_captions_says_so(monkeypatch):
    # Real: none of the six recent Kansas meetings read had captions.
    r = await _resolve(monkeypatch, "00287", "22674", "ks_00287_22674_video_only.html")
    assert r.video_url and r.video_format == "m3u8"
    assert r.segments == []
    assert r.transcript_language is None
    assert len(r.transcript_warnings) == 1
    assert "no captions" in r.transcript_warnings[0]


async def test_arkansas_video_only_meeting_keeps_its_agenda(monkeypatch):
    # Real: event 34474 has 9 agenda items and an empty ccItems.
    r = await _resolve(
        monkeypatch, "00284", "34474", "ar_00284_34474_video_only_agenda.html"
    )
    assert r.video_url and r.segments == []
    assert len(r.agenda_items) >= 5
    assert r.transcript_warnings


# --- negative controls -----------------------------------------------------


async def test_new_mexico_recording_never_published_has_no_video(monkeypatch):
    # Real: event 81082, stream Enabled false with Url "http://novod.com".
    r = await _resolve(
        monkeypatch, "00293", "81082", "nm_00293_81082_recording_never_published.html"
    )
    assert r.video_url is None and r.video_format is None
    assert r.segments == []
    assert any("not published a recording" in w for w in r.video_warnings)
    # No video means no "no captions" claim either.
    assert r.transcript_warnings == []


async def test_future_meeting_has_no_video_and_says_it_has_not_happened(monkeypatch):
    # Real: Kansas event 22647, status "Not Started", scheduled 2026-09-24.
    r = await _resolve(
        monkeypatch, "00287", "22647", "ks_00287_22647_not_started_future.html"
    )
    assert r.video_url is None
    assert r.segments == [] and r.agenda_items == []
    assert any("has not happened yet" in w for w in r.video_warnings)
    assert r.date == "2026-09-24"


# --- listing pages ---------------------------------------------------------


def test_parse_listing_reads_real_ended_events_and_skips_the_template():
    events = parse_listing(
        load_fixture("sliq_harmony", "ks_00287_recent_ended_listing.html")
    )
    assert events, "expected real events"
    assert all(e["id"].isdigit() for e in events)
    assert not any("{" in e["title"] for e in events)
    ids = [int(e["id"]) for e in events]
    assert ids == sorted(ids, reverse=True)
    assert all(e["status"] for e in events)


async def test_listing_url_raises_a_pick_list(monkeypatch):
    html = load_fixture("sliq_harmony", "ks_00287_recent_ended_listing.html")

    async def fake_fetch(self, session, url):
        assert url.endswith("/00287/Harmony/en/View/RecentEnded/")
        return html

    monkeypatch.setattr(SliqHarmonyAssetFinder, "_fetch", fake_fetch)
    with pytest.raises(CalendarPageError) as err:
        await SliqHarmonyAssetFinder().resolve(f"https://{HOST}/00287/Harmony/en/View/")
    candidates = err.value.candidates
    assert candidates
    assert all(
        "/00287/Harmony/en/PowerBrowser/PowerBrowserV3/" in c["url"] for c in candidates
    )
    assert all(c["title"] and c["date"] for c in candidates)


# --- identity: one pin per tenant path, never the shared host ---------------

TENANT_GOV_IDS = {
    "00284": "us:state:05",  # Arkansas
    "00327": "us:state:08",  # Colorado
    "00329": "us:state:10",  # Delaware
    "00287": "us:state:20",  # Kansas
    "00293": "us:state:35",  # New Mexico
    "00283": "us:state:40",  # Oklahoma (House)
    "00289": "us:state:54",  # West Virginia (Senate)
    # WO-1067: the seven WO-1006 tenants, pinned after a live re-check.
    "00281": "us:state:23",  # Maine
    "00282": "us:state:40",  # Oklahoma (Senate)
    "00285": "us:state:19",  # Iowa
    "00304": "us:state:51",  # Virginia
    "00324": "us:state:32",  # Nevada
    "00325": "us:state:29",  # Missouri
    "00328": "us:state:42",  # Pennsylvania (House)
}


def test_every_known_tenant_is_pinned():
    from app.platforms.sliq_harmony import TENANT_JURISDICTIONS

    assert set(TENANT_GOV_IDS) == set(TENANT_JURISDICTIONS)


@pytest.mark.parametrize("tenant,gov_id", sorted(TENANT_GOV_IDS.items()))
def test_each_tenant_path_is_pinned_to_its_own_state(tenant, gov_id):
    from app.utils.gov_registry.resolver import resolve_government

    match = resolve_government(
        None,
        tenant_host=HOST,
        path=f"/{tenant}/Harmony/en/PowerBrowser/PowerBrowserV3/20260920/-1/1",
    )
    assert match.gov_id == gov_id


def test_an_unlisted_tenant_on_the_shared_host_is_not_keyed_to_any_state():
    from app.utils.gov_registry.registry import is_multi_gov_host
    from app.utils.gov_registry.resolver import resolve_government

    assert is_multi_gov_host(HOST)
    match = resolve_government(
        None,
        tenant_host=HOST,
        path="/00999/Harmony/en/PowerBrowser/PowerBrowserV3/20260920/-1/1",
    )
    assert match.gov_id not in set(TENANT_GOV_IDS.values())
