"""HTTP-level tests for the universal site footer (app/main.py /
archive/main.py base.html) and the real /coverage page (archive/main.py +
archive/db/crud.py's get_platform_coverage()) -- built 2026-08-10 as a
placeholder, replaced 2026-08-12 with a real per-platform table backed by
the Archive's own MeetingPage data, then regrouped 2026-08-12 into
"direct" platforms + a "Custom" group (real bug fix: Minneapolis LIMS/SLC
delegate to YouTubeAssetFinder on success, same as Legistar/CivicPlus/
PrimeGov/CivicWeb, so MeetingPage.platform for a real LIMS/SLC page was
always "youtube" -- a real live Minneapolis page never showed up as an
LIMS example because of this). Also covers get_jurisdiction_coverage(),
added the same day per user request -- a per-government-body table (not
grouped by platform at all) for Ctrl+F discoverability, since "only
software engineers think platform first." Lives on the Archive service
(like /meetings) and is reverse-proxied through the resolver, not
rendered by the resolver directly -- see app/main.py's
`_proxy_to_archive` call for "coverage".
"""

from fastapi.testclient import TestClient

import app.main
import archive.main
from archive.db import crud

resolver_client = TestClient(app.main.app)
archive_client_ = TestClient(archive.main.app)


def test_coverage_page_renders_every_platform_label():
    response = archive_client_.get("/coverage")
    assert response.status_code == 200
    for label in {**crud.DIRECT_PLATFORMS, **crud.CUSTOM_PLATFORMS}.values():
        assert label in response.text


def test_coverage_page_excludes_youtube_as_its_own_row():
    response = archive_client_.get("/coverage")
    assert ">YouTube<" not in response.text


def test_coverage_page_no_longer_placeholder():
    response = archive_client_.get("/coverage")
    assert "Coming soon" not in response.text


def test_coverage_page_mentions_youtube_and_citymeetings_nyc():
    response = archive_client_.get("/coverage")
    assert "YouTube" in response.text  # the footer explanation, not a row
    assert "citymeetings.nyc" in response.text
    assert "Vikram Oberoi" in response.text


def test_coverage_page_renders_example_with_transcript_badge(monkeypatch):
    # get_platform_coverage() itself is exercised for real below (against
    # the shared test DB, which other tests also write "granicus" rows
    # into) -- rendering is tested here against controlled fake data
    # instead of asserting on *which* real row the shared DB happens to
    # pick, since that's not what this test is actually checking.
    async def _fake_coverage():
        return {
            "direct": [
                {
                    "platform": "granicus",
                    "label": "Granicus",
                    "examples": [
                        {
                            "slug": "coverage-test-slug",
                            "title": "Coverage Test Meeting",
                            "jurisdiction": "City of Coverage Test",
                            "has_transcript": True,
                        }
                    ],
                    "example": {
                        "slug": "coverage-test-slug",
                        "title": "Coverage Test Meeting",
                        "jurisdiction": "City of Coverage Test",
                        "has_transcript": True,
                    },
                    "page_count": 1,
                },
                {"platform": "viebit", "label": "Viebit", "examples": [], "example": None, "page_count": 0},
            ],
            "custom": [
                {"platform": "lims", "label": "Minneapolis LIMS", "examples": [], "example": None, "page_count": 0}
            ],
        }

    monkeypatch.setattr(crud, "get_platform_coverage", _fake_coverage)

    response = archive_client_.get("/coverage")
    assert response.status_code == 200
    assert "Coverage Test Meeting" in response.text
    # Rendered through the jurisdiction_display filter -- "City of" is
    # dropped for display (user request 2026-08-12), so the raw stored
    # value should never appear verbatim on this page.
    assert "Coverage Test" in response.text
    assert "City of Coverage Test" not in response.text
    assert '/m/coverage-test-slug' in response.text
    assert "Supported, but no example archived yet" in response.text


async def test_get_platform_coverage_reflects_a_real_ingested_meeting():
    payload = {
        "platform": "granicus",
        "source_url": "https://coverage-test.granicus.com/player/clip/coverage-crud-1",
        "external_id": "coverage-crud-1",
        "title": "Coverage CRUD Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": "City of Coverage Test",
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": [{"start": 0, "end": 1, "text": "hello"}],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }
    await crud.ingest_resolution(payload, "https://coverage-test.granicus.com/player/clip/coverage-crud-1")

    coverage = await crud.get_platform_coverage()
    granicus_row = next(row for row in coverage["direct"] if row["platform"] == "granicus")
    assert granicus_row["example"] is not None
    assert granicus_row["example"]["has_transcript"] is True
    assert granicus_row["page_count"] >= 1


async def test_lims_sourced_meeting_shows_up_under_custom_despite_youtube_platform():
    # Real bug fix: lims.py's resolve() returns YouTubeAssetFinder's own
    # ResolvedMeeting on success (see its docstring), so a real Minneapolis
    # LIMS page's MeetingPage.platform is "youtube", not "lims" -- this
    # reproduces that exact shape and confirms get_platform_coverage()
    # still attributes it to the "lims" custom row via source_url, not the
    # (uninformative, and intentionally-excluded) "youtube" platform.
    payload = {
        "platform": "youtube",
        "source_url": "https://lims.minneapolismn.gov/MarkedAgenda/CI/99999",
        "external_id": "coverage-lims-yt-1",
        "title": "Minneapolis City Council",
        "date": "2026-01-01",
        "jurisdiction": "Minneapolis, MN",
        "video_url": "https://example.com/v.m3u8",
        "video_format": "youtube",
        "segments": [{"start": 0, "end": 1, "text": "hello"}],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }
    await crud.ingest_resolution(payload, "https://lims.minneapolismn.gov/MarkedAgenda/CI/99999")

    coverage = await crud.get_platform_coverage()
    lims_row = next(row for row in coverage["custom"] if row["platform"] == "lims")
    assert lims_row["example"] is not None
    assert lims_row["page_count"] >= 1


async def test_raw_youtube_paste_does_not_show_up_anywhere_on_coverage():
    payload = {
        "platform": "youtube",
        "source_url": "https://www.youtube.com/watch?v=coverageRawYt1",
        "external_id": "coverage-raw-yt-1",
        "title": "Some Raw YouTube Meeting",
        "date": "2026-01-01",
        "jurisdiction": "Nowhere Special",
        "video_url": "https://example.com/v.m3u8",
        "video_format": "youtube",
        "segments": [{"start": 0, "end": 1, "text": "hello"}],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }
    await crud.ingest_resolution(payload, "https://www.youtube.com/watch?v=coverageRawYt1")

    coverage = await crud.get_platform_coverage()
    all_titles = [
        row["example"]["title"]
        for row in coverage["direct"] + coverage["custom"]
        if row["example"] is not None
    ]
    assert "Some Raw YouTube Meeting" not in all_titles


async def test_get_jurisdiction_coverage_lists_a_real_ingested_meeting():
    payload = {
        "platform": "granicus",
        "source_url": "https://coverage-jurisdiction-test.granicus.com/player/clip/1",
        "external_id": "coverage-jurisdiction-test-1",
        "title": "Napa City Council Regular Meeting",
        "date": "2026-01-01",
        "jurisdiction": "City of Napa, CA",
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": [{"start": 0, "end": 1, "text": "hello"}],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }
    await crud.ingest_resolution(payload, "https://coverage-jurisdiction-test.granicus.com/player/clip/1")

    jurisdictions = await crud.get_jurisdiction_coverage()
    napa_row = next(row for row in jurisdictions if row["jurisdiction"] == "City of Napa, CA")
    assert napa_row["example"]["title"] == "Napa City Council Regular Meeting"
    assert napa_row["example"]["has_transcript"] is True
    assert napa_row["page_count"] >= 1


async def test_jurisdiction_coverage_sorted_case_insensitively():
    payload_base = {
        "platform": "granicus",
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": [],
        "agenda_items": [],
        "transcript_language": None,
        "transcript_warnings": [],
    }
    for suffix, jurisdiction in (("a", "zzz Sort Test City, ZZ"), ("b", "aaa Sort Test City, AA")):
        payload = {
            **payload_base,
            "source_url": f"https://coverage-sort-test.granicus.com/player/clip/{suffix}",
            "external_id": f"coverage-sort-test-{suffix}",
            "title": f"Sort Test Meeting {suffix}",
            "date": "2026-01-01",
            "jurisdiction": jurisdiction,
        }
        await crud.ingest_resolution(payload, payload["source_url"])

    jurisdictions = [row["jurisdiction"] for row in await crud.get_jurisdiction_coverage()]
    lower_names = [j.casefold() for j in jurisdictions]
    assert lower_names == sorted(lower_names)


def test_coverage_page_renders_jurisdiction_table_headers():
    response = archive_client_.get("/coverage")
    assert "Government" in response.text
    assert "Example meeting" in response.text


async def test_coverage_page_renders_a_real_jurisdiction_row():
    payload = {
        "platform": "granicus",
        "source_url": "https://coverage-jurisdiction-http-test.granicus.com/player/clip/1",
        "external_id": "coverage-jurisdiction-http-test-1",
        "title": "Aurora City Council Meeting",
        "date": "2026-01-01",
        "jurisdiction": "Aurora, CO",
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": [{"start": 0, "end": 1, "text": "hello"}],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }
    await crud.ingest_resolution(payload, "https://coverage-jurisdiction-http-test.granicus.com/player/clip/1")

    response = archive_client_.get("/coverage")
    assert "Aurora, CO" in response.text
    assert "Aurora City Council Meeting" in response.text


def test_resolver_footer_has_all_four_links():
    response = resolver_client.get("/")
    for href in ("/sitemap.xml", "/feed.xml", "/coverage", "mailto:ally@redtaperecordings.com"):
        assert href in response.text


def test_subscribe_page_hides_redundant_prompt_but_keeps_footer_links():
    response = resolver_client.get("/subscribe")
    assert "/sitemap.xml" in response.text
    assert "sign up for updates" not in response.text


def test_archive_footer_has_all_four_links():
    response = archive_client_.get("/this-page-does-not-exist")  # any page renders base.html's footer
    for href in ("/sitemap.xml", "/feed.xml", "/coverage", "mailto:ally@redtaperecordings.com"):
        assert href in response.text
