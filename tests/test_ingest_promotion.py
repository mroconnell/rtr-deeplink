"""Real DB integration tests for ingest_resolution()'s promotion/demotion
logic (archive/db/crud.py) -- the general fix for two confirmed real bugs
(see BACKLOG_DONE.md): Dublin, CA's missing-language page (a fresh resolve
finding a real improvement should get promoted over a worse existing
default) and Yountville, CA's stuck stale transcript (an existing default
that's actually just a copy of the agenda should get demoted even when a
fresh resolve finds nothing better either). Against the isolated SQLite
fixture DB, same pattern as tests/test_transcription_jobs.py.
"""

from archive.db import crud


def _payload(
    external_id: str, source_url: str, *, segments=None, agenda_items=None, transcript_language=None
) -> dict:
    return {
        "platform": "granicus",
        "source_url": source_url,
        "external_id": external_id,
        "title": "Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": "City of Test",
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": segments or [],
        "agenda_items": agenda_items or [],
        "transcript_language": transcript_language,
        "transcript_warnings": [],
    }


async def test_dublin_style_promotes_when_language_detected_later():
    url = "https://example.granicus.com/player/clip/promo-dublin"
    external_id = "granicus:promo-dublin"

    # First ingest: real segments, no language detected (pre-fix state).
    await crud.ingest_resolution(
        _payload(external_id, url, segments=[{"start": 0, "end": 1, "text": "hello"}], transcript_language=None),
        url,
    )
    page = await crud.get_page_by_slug((await crud.lookup_page_for_url(url))["slug"])
    assert len(page["versions"]) == 1
    assert page["versions"][0]["language"] is None
    assert page["versions"][0]["is_default"] is True
    old_version_id = page["versions"][0]["id"]

    # Second ingest (a recheck): same segments, but language detection now
    # works -- should create a new version AND promote it over the old one.
    await crud.ingest_resolution(
        _payload(external_id, url, segments=[{"start": 0, "end": 1, "text": "hello"}], transcript_language="en"),
        url,
    )
    page = await crud.get_page_by_slug((await crud.lookup_page_for_url(url))["slug"])
    assert len(page["versions"]) == 2
    default_versions = [v for v in page["versions"] if v["is_default"]]
    assert len(default_versions) == 1
    assert default_versions[0]["language"] == "en"
    assert default_versions[0]["id"] != old_version_id
    # old version still reachable, just demoted
    old = next(v for v in page["versions"] if v["id"] == old_version_id)
    assert old["is_default"] is False


async def test_yountville_style_demotes_stale_agenda_copy_default():
    url = "https://example.granicus.com/player/clip/promo-yountville"
    external_id = "granicus:promo-yountville"
    agenda = [{"start": 0, "end": 30, "text": "Item A"}, {"start": 30, "end": 60, "text": "Item B"}]

    # First ingest: segments that are actually just a copy of the agenda
    # (simulating the legacy since-removed code path's bad output).
    await crud.ingest_resolution(
        _payload(external_id, url, segments=agenda, agenda_items=agenda),
        url,
    )
    page = await crud.get_page_by_slug((await crud.lookup_page_for_url(url))["slug"])
    assert page["versions"][0]["is_default"] is True

    # Recheck: today's correct adapter behavior -- real agenda_items, but
    # NO segments (segments never folded into agenda anymore). No new
    # version can be created, but the stale copied-agenda default should
    # be demoted since it was never a genuine transcript.
    await crud.ingest_resolution(
        _payload(external_id, url, segments=[], agenda_items=agenda),
        url,
    )
    page = await crud.get_page_by_slug((await crud.lookup_page_for_url(url))["slug"])
    assert len(page["versions"]) == 1  # no new version created
    assert page["versions"][0]["is_default"] is False  # but demoted


async def test_no_promotion_when_default_already_has_segments_and_language():
    url = "https://example.granicus.com/player/clip/promo-stable"
    external_id = "granicus:promo-stable"

    await crud.ingest_resolution(
        _payload(external_id, url, segments=[{"start": 0, "end": 1, "text": "hello"}], transcript_language="en"),
        url,
    )
    page = await crud.get_page_by_slug((await crud.lookup_page_for_url(url))["slug"])
    original_id = page["versions"][0]["id"]

    # A recheck with genuinely different (not duplicate) content, still
    # with a language already present -- not confidently "better," so the
    # existing default should NOT get auto-demoted/replaced.
    await crud.ingest_resolution(
        _payload(external_id, url, segments=[{"start": 0, "end": 1, "text": "a different transcript"}], transcript_language="en"),
        url,
    )
    page = await crud.get_page_by_slug((await crud.lookup_page_for_url(url))["slug"])
    default_versions = [v for v in page["versions"] if v["is_default"]]
    assert len(default_versions) == 1
    assert default_versions[0]["id"] == original_id


async def test_no_default_yet_first_ingest_unaffected():
    # Brand-new page: no current_default to promote/demote against --
    # normal first-version-becomes-default behavior, no crash.
    url = "https://example.granicus.com/player/clip/promo-fresh"
    result = await crud.ingest_resolution(
        _payload("granicus:promo-fresh", url, segments=[{"start": 0, "end": 1, "text": "hi"}], transcript_language="en"),
        url,
    )
    page = await crud.get_page_by_slug(result["slug"])
    assert len(page["versions"]) == 1
    assert page["versions"][0]["is_default"] is True


async def test_demotion_not_triggered_when_default_segments_are_not_agenda_copy():
    # A default with real segments that just happen to have no matching
    # agenda -- should NOT be treated as a copied-agenda stale default.
    url = "https://example.granicus.com/player/clip/promo-real-transcript"
    external_id = "granicus:promo-real-transcript"
    agenda = [{"start": 0, "end": 30, "text": "Item A"}]

    await crud.ingest_resolution(
        _payload(external_id, url, segments=[{"start": 0, "end": 1, "text": "a genuine transcript line"}], agenda_items=agenda),
        url,
    )
    page = await crud.get_page_by_slug((await crud.lookup_page_for_url(url))["slug"])
    assert page["versions"][0]["is_default"] is True

    # Recheck: still no new segments, real agenda present -- but the
    # existing default's text doesn't match the agenda, so it should stay
    # the default (a real transcript, not a copied-agenda artifact).
    await crud.ingest_resolution(_payload(external_id, url, segments=[], agenda_items=agenda), url)
    page = await crud.get_page_by_slug((await crud.lookup_page_for_url(url))["slug"])
    assert page["versions"][0]["is_default"] is True
