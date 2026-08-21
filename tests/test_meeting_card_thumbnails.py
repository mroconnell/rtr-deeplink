"""Meeting-card frames (WO-28): which second of the video gets grabbed,
the storage/serving path behind GET /m/{slug}/card.jpg, and the Clip
endOffset resolution that shares the same Search Console report.

Two kinds of test here, deliberately kept apart:

* `target_offset_seconds()` and `clip_entries()` are pure functions,
  tested directly with real numbers taken from real pages -- the San
  Carlos IQM2 meeting's genuine 15681s duration and its genuine
  982/1056s consent-calendar block, both read off the live production
  page and its source video on 2026-08-21.
* The route/storage tests are synthetic pages built through
  `crud.ingest_resolution()` (the same pattern as
  test_meeting_page_structured_data.py) with the frame bytes stored
  directly rather than extracted, because what's under test is the
  serve/degrade/caching path, not ffmpeg. ffmpeg itself was verified
  against the real San Carlos mp4 live -- see BACKLOG_DONE.md for the
  measured numbers; a test that shelled out to a government CDN would
  break this suite's deliberate network-free property.
"""

import archive.main
from archive.db import crud
from archive.utils.clips import clip_entries
from archive.utils.video_thumbnail import (
    TIMESTAMP_LEAD_SECONDS,
    UNKNOWN_DURATION_OFFSET_SECONDS,
    is_extractable,
    target_offset_seconds,
)
from fastapi.testclient import TestClient

archive_client = TestClient(archive.main.app)

# Real numbers, not invented: ffprobe reported 15681.87s for
# https://MediaHTTP.IQM2.com/SanCarlosCA/1450_480.mp4, the video behind
# /m/san-carlos-ca-2017-11-13-city-council-regular-meeting -- the page
# whose Search Console URL Inspection prompted this work.
_SAN_CARLOS_DURATION = 15681.8662
# A 1x1 JPEG is enough to prove bytes go in and come back out with the
# right headers; the real frames measure ~30KB (also confirmed live).
_TINY_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300ffffffffffffffff"
    "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffc2000b08"
    "000100010101110000ffc40014000100000000000000000000000000000009ffda"
    "0008010100000000013fffd9"
)


# --- targeting tiers -----------------------------------------------------


def test_timestamp_tier_lands_just_after_the_shared_moment():
    # The real consent-calendar block starts at 982s; a share link at that
    # moment should show a frame *inside* the item, not on the transition
    # into it. Confirmed visually against the real video: the frame at
    # 1000s shows "7. CONSENT CALENDAR" on the chamber's own overlay.
    assert target_offset_seconds(timestamp=982) == 1000
    assert target_offset_seconds(timestamp=0) == TIMESTAMP_LEAD_SECONDS


def test_timestamp_bucketing_never_lands_before_the_shared_moment():
    # 20s buckets bound how many distinct frames a crawl over many
    # near-identical deep links can create. The bucket size matches the
    # lead exactly so that bucket(t + 20) always falls in (t, t + 20] --
    # a coarser bucket would sometimes land *before* t, showing a card for
    # a moment the sharer didn't pick.
    for timestamp in range(0, 200):
        offset = target_offset_seconds(timestamp=timestamp)
        assert timestamp < offset <= timestamp + TIMESTAMP_LEAD_SECONDS
        assert offset % 20 == 0


def test_timestamp_tier_beats_a_known_duration():
    assert target_offset_seconds(timestamp=982, duration=_SAN_CARLOS_DURATION) == 1000


def test_default_tier_is_five_minutes_before_the_end():
    # Meetings routinely open with minutes of dead air behind a static
    # placeholder, so an early offset is often a literal blank slate.
    assert target_offset_seconds(duration=_SAN_CARLOS_DURATION) == 15381


def test_short_video_falls_back_to_halfway():
    # 300s before the end of an 8-minute recording would be 3 minutes in
    # -- i.e. right back in the placeholder window the tail rule exists to
    # avoid -- so below the threshold, halfway wins.
    assert target_offset_seconds(duration=480) == 240
    assert target_offset_seconds(duration=600) == 300  # exactly at the threshold


def test_unknown_duration_falls_back_to_a_fixed_offset():
    # "Halfway" isn't computable without a duration, so an unprobeable
    # source gets the documented fixed floor rather than a fabricated one.
    assert target_offset_seconds() == UNKNOWN_DURATION_OFFSET_SECONDS
    assert target_offset_seconds(duration=None) == UNKNOWN_DURATION_OFFSET_SECONDS
    assert target_offset_seconds(duration=0) == UNKNOWN_DURATION_OFFSET_SECONDS


def test_is_extractable_skips_youtube_and_missing_video():
    assert is_extractable("https://MediaHTTP.IQM2.com/SanCarlosCA/1450_480.mp4", "mp4")
    assert is_extractable("https://archive-stream.granicus.com/x/y.m3u8", "m3u8")
    # A YouTube video_url is an iframe-embed URL, not media ffmpeg could
    # open -- and those pages already have a free i.ytimg.com thumbnail.
    assert not is_extractable("https://www.youtube.com/embed/dQw4w9WgXcQ", "youtube")
    assert not is_extractable("https://www.youtube.com/embed/dQw4w9WgXcQ", None)
    assert not is_extractable(None, "mp4")
    assert not is_extractable("", None)


# --- Clip endOffset resolution ------------------------------------------


def test_shared_start_run_gets_the_next_distinct_start_as_its_end():
    # The real San Carlos case: IQM2 gave one consent-calendar block a
    # single timestamp, so a dozen consecutive items all carry start=982.
    # Each item's own `end` equals its `start`, so the old
    # `item.end > item.start` guard dropped endOffset from all of them --
    # 12 of the 12 non-critical Search Console warnings on that page.
    items = [
        {"start": 982.0, "end": 982.0, "text": f"Consent item {i}"} for i in range(12)
    ]
    items.append({"start": 1056.0, "end": 1300.0, "text": "Public Hearing"})

    entries = clip_entries(items)
    assert [e["end"] for e in entries[:12]] == [1056] * 12
    assert entries[12]["end"] == 1300


def test_real_item_end_wins_over_the_next_start():
    # A genuine 100-200s item followed by a gap ends at 200, not at
    # whenever the next item happens to begin -- the next-distinct-start
    # rule is a fallback, not a replacement.
    entries = clip_entries(
        [
            {"start": 100.0, "end": 200.0, "text": "One"},
            {"start": 500.0, "end": 600.0, "text": "Two"},
        ]
    )
    assert [e["end"] for e in entries] == [200, 600]


def test_final_open_ended_item_has_no_end():
    # Nothing follows it and its source gave it no real end. Emitting a
    # guess here would be inventing data.
    entries = clip_entries(
        [
            {"start": 0.0, "end": 754.0, "text": "Call to Order"},
            {"start": 2130.5, "end": 2130.5, "text": "Adjournment"},
        ]
    )
    assert entries[0]["end"] == 754
    assert entries[1]["end"] is None


def test_items_without_a_usable_start_are_dropped():
    # A Clip claiming a key moment at 0:00 that isn't one is false
    # navigation -- same reasoning as the template's clips_unreliable
    # guard. Skipped rather than coerced.
    entries = clip_entries(
        [
            {"start": None, "text": "No timestamp"},
            {"start": "not a number", "text": "Junk"},
            {"start": 60.0, "end": 120.0, "text": "Real"},
        ]
    )
    assert [e["text"] for e in entries] == ["Real"]


def test_clip_entries_tolerates_empty_and_none():
    assert clip_entries(None) == []
    assert clip_entries([]) == []


# --- the card route ------------------------------------------------------


async def _make_m3u8_page(external_id: str) -> dict:
    url = f"https://example.com/card-route/{external_id}"
    return await crud.ingest_resolution(
        {
            "platform": "granicus",
            "source_url": url,
            "external_id": external_id,
            "title": "Card Route Test Meeting",
            "date": "2026-01-01",
            "jurisdiction": "Fresno, CA",
            "video_url": "https://archive-media.granicus.com/OnDemand/x/x.m3u8",
            "video_format": "m3u8",
            "segments": [],
            "agenda_items": [],
            "transcript_language": None,
            "transcript_warnings": [],
        },
        url,
    )


async def test_card_404s_until_a_frame_exists():
    page = await _make_m3u8_page("card-empty")
    response = archive_client.get(f"/m/{page['slug']}/card.jpg")
    assert response.status_code == 404


async def test_card_serves_stored_bytes_with_cache_headers():
    page = await _make_m3u8_page("card-default")
    assert await crud.store_thumbnail(
        page["page_id"],
        offset_seconds=15381,
        image_bytes=_TINY_JPEG,
        etag="a" * 64,
        is_default=True,
    )

    response = archive_client.get(f"/m/{page['slug']}/card.jpg")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == _TINY_JPEG
    assert response.headers["etag"] == '"' + "a" * 64 + '"'
    assert "max-age=86400" in response.headers["cache-control"]
    assert response.headers["x-card-offset-seconds"] == "15381"

    # A conditional refetch (Googlebot and three social networks all do
    # this) costs a 304, never a re-read of the image bytes.
    conditional = archive_client.get(
        f"/m/{page['slug']}/card.jpg",
        headers={"If-None-Match": '"' + "a" * 64 + '"'},
    )
    assert conditional.status_code == 304
    assert conditional.content == b""


async def test_card_with_timestamp_serves_the_matching_frame():
    page = await _make_m3u8_page("card-timestamped")
    assert await crud.store_thumbnail(
        page["page_id"],
        offset_seconds=15381,
        image_bytes=_TINY_JPEG,
        etag="d" * 64,
        is_default=True,
    )
    per_timestamp = _TINY_JPEG + b"\x00"
    assert await crud.store_thumbnail(
        page["page_id"],
        offset_seconds=1000,  # what ?t=982 resolves to
        image_bytes=per_timestamp,
        etag="e" * 64,
        is_default=False,
    )

    response = archive_client.get(f"/m/{page['slug']}/card.jpg?t=982")
    assert response.status_code == 200
    assert response.content == per_timestamp
    assert response.headers["x-card-offset-seconds"] == "1000"

    # ...and a timestamp with no frame stored yet degrades to the default
    # frame rather than 404ing, so a scraper always gets a real image.
    fallback = archive_client.get(f"/m/{page['slug']}/card.jpg?t=9999")
    assert fallback.status_code == 200
    assert fallback.content == _TINY_JPEG
    assert fallback.headers["x-card-offset-seconds"] == "15381"


async def test_card_redirects_youtube_pages_to_ytimg():
    url = "https://example.com/card-route/card-youtube"
    page = await crud.ingest_resolution(
        {
            "platform": "youtube",
            "source_url": url,
            "external_id": "card-youtube",
            "title": "YouTube Card Test",
            "date": "2026-01-01",
            "jurisdiction": "Fresno, CA",
            "video_url": "https://www.youtube.com/embed/dQw4w9WgXcQ",
            "video_format": "youtube",
            "segments": [],
            "agenda_items": [],
            "transcript_language": None,
            "transcript_warnings": [],
        },
        url,
    )
    response = archive_client.get(f"/m/{page['slug']}/card.jpg", follow_redirects=False)
    assert response.status_code == 302
    assert (
        response.headers["location"]
        == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
    )


async def test_card_404s_for_an_unknown_slug():
    assert archive_client.get("/m/no-such-meeting-at-all/card.jpg").status_code == 404


async def test_store_thumbnail_keeps_one_default_per_page():
    page = await _make_m3u8_page("card-one-default")
    await crud.store_thumbnail(
        page["page_id"],
        offset_seconds=100,
        image_bytes=_TINY_JPEG,
        etag="b" * 64,
        is_default=True,
    )
    await crud.store_thumbnail(
        page["page_id"],
        offset_seconds=200,
        image_bytes=_TINY_JPEG,
        etag="c" * 64,
        is_default=True,
    )
    meta = await crud.get_thumbnail_meta(page["page_id"])
    assert meta["offset_seconds"] == 200
    assert await crud.count_thumbnails(page["page_id"]) == 2


async def test_store_thumbnail_refuses_a_duplicate_offset():
    page = await _make_m3u8_page("card-dupe-offset")
    assert await crud.store_thumbnail(
        page["page_id"],
        offset_seconds=300,
        image_bytes=_TINY_JPEG,
        etag="f" * 64,
        is_default=True,
    )
    # Two background warms racing on the same (page, offset): the second
    # stops rather than piling up a duplicate row.
    assert not await crud.store_thumbnail(
        page["page_id"],
        offset_seconds=300,
        image_bytes=_TINY_JPEG,
        etag="0" * 64,
        is_default=True,
    )


async def test_backfill_lists_only_extractable_pages_without_a_default():
    warmed = await _make_m3u8_page("card-backfill-warmed")
    await crud.store_thumbnail(
        warmed["page_id"],
        offset_seconds=900,
        image_bytes=_TINY_JPEG,
        etag="1" * 64,
        is_default=True,
    )
    cold = await _make_m3u8_page("card-backfill-cold")

    response = archive_client.post(
        "/internal/thumbnails/backfill?limit=50",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    slugs = {c["slug"] for c in body["candidates"]}
    assert cold["slug"] in slugs
    assert warmed["slug"] not in slugs
    # YouTube-backed pages are excluded in SQL -- they already have a free
    # thumbnail and their video_url isn't media ffmpeg could open.
    assert not any(s.endswith("youtube-card-test") for s in slugs)


def test_backfill_is_token_gated():
    # 404 rather than 401/403, same posture as every other /internal/* route.
    assert archive_client.post("/internal/thumbnails/backfill").status_code == 404
