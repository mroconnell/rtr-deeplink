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
`_proxy_to_archive` call for "coverage". Also covers
get_full_jurisdiction_coverage(), added 2026-08-17 (BACKLOG.md's
"Coverage page -- a public, sortable/filterable table" entry) for the
fuller per-jurisdiction column spec (video/agenda/transcript yes-no
columns, a two-column detail-page/video provider split, an outcome
bucket, a last-verified date) that get_jurisdiction_coverage() above was
never meant to carry.
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
                {
                    "platform": "viebit",
                    "label": "Viebit",
                    "examples": [],
                    "example": None,
                    "page_count": 0,
                },
            ],
            "custom": [
                {
                    "platform": "lims",
                    "label": "Minneapolis LIMS",
                    "examples": [],
                    "example": None,
                    "page_count": 0,
                }
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
    assert "/m/coverage-test-slug" in response.text
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
    await crud.ingest_resolution(
        payload, "https://coverage-test.granicus.com/player/clip/coverage-crud-1"
    )

    coverage = await crud.get_platform_coverage()
    granicus_row = next(
        row for row in coverage["direct"] if row["platform"] == "granicus"
    )
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
    await crud.ingest_resolution(
        payload, "https://lims.minneapolismn.gov/MarkedAgenda/CI/99999"
    )

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
    await crud.ingest_resolution(
        payload, "https://www.youtube.com/watch?v=coverageRawYt1"
    )

    coverage = await crud.get_platform_coverage()
    all_titles = [
        row["example"]["title"]
        for row in coverage["direct"] + coverage["custom"]
        if row["example"] is not None
    ]
    assert "Some Raw YouTube Meeting" not in all_titles


# --- WO-35 regressions, 2026-08-21. All four adapters below shipped
# 2026-08-19..21 and were confirmed missing from the live production
# /coverage page (zero rows each) before this fix: they set their own
# platform_name, produce real pushable rows, and appeared in neither
# DIRECT_PLATFORMS nor CUSTOM_PLATFORMS, so get_platform_coverage()'s
# if/elif chain matched no branch and dropped them silently. The
# structural guard against a fifth recurrence lives in
# tests/test_coverage_platform_registry.py; these four pin the specific
# rows. Payload shapes mirror each adapter's real success return
# (verified by reading its resolve() -- see the per-test notes).


async def test_suiteone_meeting_shows_up_on_coverage():
    # suiteone.py returns platform="suiteone", video_format="mp4" with a
    # direct, unauthenticated S3 mp4 -- a genuinely direct host.
    payload = {
        "platform": "suiteone",
        "source_url": "https://coveragetestut.suiteonemedia.com/event/?id=90001",
        "external_id": "coverage-suiteone-1",
        "title": "Coverage SuiteOne Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": "Coverage Suiteone Test, UT",
        "video_url": "https://example.com/v.mp4",
        "video_format": "mp4",
        "segments": [{"start": 0, "end": 1, "text": "hello"}],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }
    await crud.ingest_resolution(
        payload, "https://coveragetestut.suiteonemedia.com/event/?id=90001"
    )

    coverage = await crud.get_platform_coverage()
    row = next(r for r in coverage["direct"] if r["platform"] == "suiteone")
    assert row["example"] is not None
    assert row["page_count"] >= 1


async def test_castus_meeting_shows_up_on_coverage():
    # castus.py returns platform="castus", video_format="m3u8" pointing at
    # its own global CloudFront CDN -- also a genuinely direct host.
    payload = {
        "platform": "castus",
        "source_url": "https://cloud.castus.tv/vod/coveragetest/video/90002",
        "external_id": "coverage-castus-1",
        "title": "Coverage Castus Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": "Coverage Castus Test, MT",
        "video_url": "https://example.com/out.m3u8",
        "video_format": "m3u8",
        "segments": [{"start": 0, "end": 1, "text": "hello"}],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }
    await crud.ingest_resolution(
        payload, "https://cloud.castus.tv/vod/coveragetest/video/90002"
    )

    coverage = await crud.get_platform_coverage()
    row = next(r for r in coverage["direct"] if r["platform"] == "castus")
    assert row["example"] is not None
    assert row["page_count"] >= 1


async def test_open_media_meeting_shows_up_despite_youtube_platform():
    # The same shape as the LIMS test above, and the reason open_media
    # couldn't just be added to DIRECT_PLATFORMS and left there:
    # openmedia.py delegates to YouTubeAssetFinder.resolve_video_id() and
    # never reassigns `resolved.platform` afterwards (confirmed by reading
    # its resolve() end to end -- it only sets title/jurisdiction/
    # external_id/agenda_link), so a real ingested open.media page is
    # stored as platform="youtube" with its own open.media source_url.
    # Attribution therefore has to come from source_url, which is what
    # _entry_platform_from_source_url()'s new open.media branch does.
    payload = {
        "platform": "youtube",
        "source_url": "https://coveragetest.open.media/sessions/90003/city-council",
        "external_id": "coverage-openmedia-1",
        "title": "Coverage open.media Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": "Coverage Openmedia Test, OR",
        "video_url": "https://example.com/embed/v3",
        "video_format": "youtube",
        "segments": [{"start": 0, "end": 1, "text": "hello"}],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }
    await crud.ingest_resolution(
        payload, "https://coveragetest.open.media/sessions/90003/city-council"
    )

    coverage = await crud.get_platform_coverage()
    row = next(r for r in coverage["direct"] if r["platform"] == "open_media")
    assert row["example"] is not None
    assert row["page_count"] >= 1


async def test_destinyhosted_agenda_only_meeting_shows_up_on_coverage():
    # destinyhosted.py delegates to GenericFallbackAssetFinder and only
    # claims platform="destinyhosted" when the delegate came back
    # "unknown" -- i.e. when this AgendaQuick page IS the terminal
    # identity. That's a real pushable shape (most tenants are
    # agenda-only, per its own docstring and README's platform table), so
    # agenda_items are populated here and segments aren't.
    payload = {
        "platform": "destinyhosted",
        "source_url": "https://public.destinyhosted.com/agenda_publish.cfm?id=90004",
        "external_id": "coverage-destinyhosted-1",
        "title": "Coverage DestinyHosted Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": "Coverage Destiny Test, TX",
        "video_url": None,
        "video_format": None,
        "segments": [],
        "agenda_items": [{"start": 0, "end": 1, "text": "Item 1"}],
        "transcript_language": None,
        "transcript_warnings": [],
    }
    await crud.ingest_resolution(
        payload, "https://public.destinyhosted.com/agenda_publish.cfm?id=90004"
    )

    coverage = await crud.get_platform_coverage()
    row = next(r for r in coverage["direct"] if r["platform"] == "destinyhosted")
    assert row["example"] is not None
    assert row["page_count"] >= 1


async def test_full_jurisdiction_coverage_viebit_cannot_be_audio_transcribed():
    # WO-35 / the WO-29 residual BACKLOG.md flagged as "cheap and safe to
    # fix". Real shape: viebit.py stores `video_url` as the platform's own
    # /embed/vod?v={id} iframe page (deliberately rebuilt as that path on
    # every resolve, see its docstring) with video_format="viebit" -- an
    # HTML page, not a media file, so ffprobe can never read it and
    # on-demand Whisper can never run. Before this fix /coverage claimed
    # the opposite for every Viebit row; confirmed live on the production
    # page 2026-08-21, where the one real Viebit jurisdiction (New York
    # City) showed a checkmark in the "Audio transcript possible" column.
    payload = {
        "platform": "viebit",
        "source_url": "https://coveragetest.viebit.com/vod/?v=COV-90005",
        "external_id": "coverage-viebit-1",
        "title": "Coverage Viebit Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": "Coverage Viebit Test, NY",
        "video_url": "https://coveragetest.viebit.com/embed/vod?v=COV-90005",
        "video_format": "viebit",
        "segments": [{"start": 0, "end": 1, "text": "hello"}],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }
    await crud.ingest_resolution(
        payload, "https://coveragetest.viebit.com/vod/?v=COV-90005"
    )

    rows = await crud.get_full_jurisdiction_coverage()
    row = next(r for r in rows if r["jurisdiction"] == "Coverage Viebit Test, NY")
    assert row["video_embeds"] is True
    assert row["instant_transcript"] is True
    # The whole point: a real, playable video and a real transcript, but
    # still no fetchable media file to run Whisper against.
    assert row["audio_transcript_possible"] is False


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
    await crud.ingest_resolution(
        payload, "https://coverage-jurisdiction-test.granicus.com/player/clip/1"
    )

    jurisdictions = await crud.get_jurisdiction_coverage()
    napa_row = next(
        row for row in jurisdictions if row["jurisdiction"] == "City of Napa, CA"
    )
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
    for suffix, jurisdiction in (
        ("a", "zzz Sort Test City, ZZ"),
        ("b", "aaa Sort Test City, AA"),
    ):
        payload = {
            **payload_base,
            "source_url": f"https://coverage-sort-test.granicus.com/player/clip/{suffix}",
            "external_id": f"coverage-sort-test-{suffix}",
            "title": f"Sort Test Meeting {suffix}",
            "date": "2026-01-01",
            "jurisdiction": jurisdiction,
        }
        await crud.ingest_resolution(payload, payload["source_url"])

    jurisdictions = [
        row["jurisdiction"] for row in await crud.get_jurisdiction_coverage()
    ]
    lower_names = [j.casefold() for j in jurisdictions]
    assert lower_names == sorted(lower_names)


async def test_full_jurisdiction_coverage_reflects_a_direct_platform_meeting():
    # A "direct" platform (Granicus hosts its own video, no delegation) --
    # video/agenda/transcript all real and present, so every yes/no column
    # should read True, and the two-column provider split should collapse
    # to the same "Granicus" label on both sides (no delegation happened,
    # so there's nothing to split).
    payload = {
        "platform": "granicus",
        "source_url": "https://coverage-full-direct-test.granicus.com/player/clip/1",
        "external_id": "coverage-full-direct-1",
        "title": "Full Coverage Direct Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": "Full Coverage Test City, Direct",
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": [{"start": 0, "end": 1, "text": "hello"}],
        "agenda_items": [{"start": 0, "end": 1, "text": "Item 1"}],
        "transcript_language": "en",
        "transcript_warnings": [],
    }
    await crud.ingest_resolution(
        payload, "https://coverage-full-direct-test.granicus.com/player/clip/1"
    )

    rows = await crud.get_full_jurisdiction_coverage()
    row = next(
        r for r in rows if r["jurisdiction"] == "Full Coverage Test City, Direct"
    )
    assert row["video_embeds"] is True
    assert row["agenda_embedded"] is True
    assert row["instant_transcript"] is True
    assert row["audio_transcript_possible"] is True
    assert row["detail_platform"] == "Granicus"
    assert row["video_platform"] == "Granicus"
    assert row["outcome"] == "success"
    assert row["example"]["slug"]
    assert row["page_count"] >= 1


async def test_full_jurisdiction_coverage_splits_lims_wrapper_platform():
    # Synthetic payload, but the shape is real: lims.py's own resolve()
    # (app/platforms/lims.py) calls YouTubeAssetFinder.resolve_video_id()
    # on success, which always returns platform="youtube" while source_url
    # stays the original lims.minneapolismn.gov URL (confirmed by reading
    # both modules directly, not assumed) -- this is the exact real shape
    # that makes the "Detail page" vs "Video platform" split meaningful.
    # jurisdiction is deliberately NOT asserted against a made-up value
    # here: app/utils/jurisdiction_enrich.py's `_KNOWN_DOMAINS` maps
    # lims.minneapolismn.gov straight to the real, confirmed "Minneapolis,
    # MN" (LIMS is single-tenant -- see lims.py's own docstring), and
    # finalize_jurisdiction() applies that override unconditionally on
    # ingest, so whatever this payload's own `jurisdiction` field says
    # gets replaced regardless (confirmed live via a throwaway script
    # before writing this test, not assumed).
    payload = {
        "platform": "youtube",
        "source_url": "https://lims.minneapolismn.gov/MarkedAgenda/CI/88888",
        "external_id": "coverage-full-lims-1",
        "title": "Full Coverage LIMS Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": "Full Coverage Test City, LIMS",
        "video_url": "https://example.com/embed/v1",
        "video_format": "youtube",
        "segments": [{"start": 0, "end": 1, "text": "hello"}],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }
    await crud.ingest_resolution(
        payload, "https://lims.minneapolismn.gov/MarkedAgenda/CI/88888"
    )

    rows = await crud.get_full_jurisdiction_coverage()
    row = next(r for r in rows if r["jurisdiction"] == "Minneapolis, MN")
    assert row["detail_platform"] == "Minneapolis LIMS"
    assert row["video_platform"] == "YouTube"
    # video_format == "youtube" is structurally unprobeable by ffprobe (see
    # app/main.py's _unreadable_media_message()) -- on-demand transcription
    # is never possible for it, regardless of whether video/agenda exist.
    assert row["audio_transcript_possible"] is False


async def test_full_jurisdiction_coverage_splits_primegov_wrapper_platform():
    # Synthetic payload, real shape: primegov.py's own resolve() (app/
    # platforms/primegov.py, confirmed by reading it directly) also calls
    # YouTubeAssetFinder.resolve_video_id() with the original PrimeGov URL
    # preserved as source_url, same pattern as LIMS -- PrimeGov isn't its
    # own DIRECT_PLATFORMS/CUSTOM_PLATFORMS row (get_platform_coverage()
    # doesn't show it anywhere), but get_full_jurisdiction_coverage()'s
    # own _wrapper_detail_label() recovers it from the real *.primegov.com
    # domain regardless, per BACKLOG.md's explicit "PrimeGov embeds a
    # YouTube video" example for this column split.
    payload = {
        "platform": "youtube",
        "source_url": "https://coverage-full-test.primegov.com/Portal/MeetingPreview?id=1",
        "external_id": "coverage-full-primegov-1",
        "title": "Full Coverage PrimeGov Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": "Full Coverage Test City, PrimeGov",
        "video_url": "https://example.com/embed/v2",
        "video_format": "youtube",
        "segments": [],
        "agenda_items": [],
        "transcript_language": None,
        "transcript_warnings": [],
    }
    await crud.ingest_resolution(
        payload,
        "https://coverage-full-test.primegov.com/Portal/MeetingPreview?id=1",
    )

    rows = await crud.get_full_jurisdiction_coverage()
    row = next(
        r for r in rows if r["jurisdiction"] == "Full Coverage Test City, PrimeGov"
    )
    assert row["detail_platform"] == "PrimeGov"
    assert row["video_platform"] == "YouTube"
    # No segments and no agenda_items -> blank_transcript, not no_video
    # (video_url is set).
    assert row["outcome"] == "blank_transcript"
    assert row["instant_transcript"] is False


async def test_full_jurisdiction_coverage_agenda_only_outcome():
    payload = {
        "platform": "civicclerk",
        "source_url": "https://coverage-full-agenda-test.civicclerk.com/Web/Player.aspx?id=1",
        "external_id": "coverage-full-agenda-1",
        "title": "Full Coverage Agenda-Only Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": "Full Coverage Test City, AgendaOnly",
        "video_url": "https://example.com/v.mp4",
        "video_format": "mp4",
        "segments": [],
        "agenda_items": [{"start": 0, "end": 1, "text": "Item 1"}],
        "transcript_language": None,
        "transcript_warnings": [],
    }
    await crud.ingest_resolution(
        payload,
        "https://coverage-full-agenda-test.civicclerk.com/Web/Player.aspx?id=1",
    )

    rows = await crud.get_full_jurisdiction_coverage()
    row = next(
        r for r in rows if r["jurisdiction"] == "Full Coverage Test City, AgendaOnly"
    )
    assert row["outcome"] == "agenda_fallback"
    assert row["agenda_embedded"] is True
    assert row["audio_transcript_possible"] is True


def test_coverage_page_renders_full_jurisdiction_table_headers():
    response = archive_client_.get("/coverage")
    assert "Full jurisdiction detail table" in response.text
    assert "Video embeds" in response.text
    assert "Agenda embedded" in response.text
    assert "Instant transcript" in response.text
    assert "Audio transcript possible" in response.text
    assert "Video platform" in response.text
    assert 'id="fullCoverageTable"' in response.text


async def test_coverage_page_renders_a_real_full_jurisdiction_row():
    payload = {
        "platform": "granicus",
        "source_url": "https://coverage-full-http-test.granicus.com/player/clip/1",
        "external_id": "coverage-full-http-1",
        "title": "Full Coverage HTTP Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": "Full Coverage Test City, HTTP",
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": [{"start": 0, "end": 1, "text": "hello"}],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }
    await crud.ingest_resolution(
        payload, "https://coverage-full-http-test.granicus.com/player/clip/1"
    )

    response = archive_client_.get("/coverage")
    assert "Full Coverage Test City, HTTP" in response.text
    assert "Full Coverage HTTP Test Meeting" in response.text


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
    await crud.ingest_resolution(
        payload, "https://coverage-jurisdiction-http-test.granicus.com/player/clip/1"
    )

    response = archive_client_.get("/coverage")
    assert "Aurora, CO" in response.text
    assert "Aurora City Council Meeting" in response.text


def test_resolver_footer_has_all_four_links():
    response = resolver_client.get("/")
    for href in (
        "/sitemap.xml",
        "/feed.xml",
        "/coverage",
        "mailto:ally@redtaperecordings.com",
    ):
        assert href in response.text


def test_subscribe_page_hides_redundant_prompt_but_keeps_footer_links():
    response = resolver_client.get("/subscribe")
    assert "/sitemap.xml" in response.text
    assert "sign up for updates" not in response.text


def test_archive_footer_has_all_four_links():
    response = archive_client_.get(
        "/this-page-does-not-exist"
    )  # any page renders base.html's footer
    for href in (
        "/sitemap.xml",
        "/feed.xml",
        "/coverage",
        "mailto:ally@redtaperecordings.com",
    ):
        assert href in response.text
