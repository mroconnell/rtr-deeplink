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

import pytest

import archive.main
from app.platforms import media_probe
from archive.db import crud
from archive.utils import video_thumbnail
from archive.utils.clips import clip_entries
from archive.utils.video_thumbnail import (
    TIMESTAMP_LEAD_SECONDS,
    UNKNOWN_DURATION_OFFSET_SECONDS,
    is_extractable,
    target_offset_seconds,
)

# Bound at import time, before conftest's autouse `_no_real_card_extraction`
# fixture replaces the module attribute: the tests below are the only ones
# in the suite that exercise the real extract_and_store(), and they do it
# with media_probe patched so nothing reaches a CDN either way.
from archive.utils.video_thumbnail import extract_and_store as real_extract_and_store
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


async def test_backfill_offset_pages_past_the_head_of_the_queue():
    # WO-37: an extraction that fails stores nothing, so the page stays a
    # candidate forever at the newest-first head. Without `offset` a
    # fixed-`limit` sweep would re-attempt the same stuck pages on every
    # call and never reach another one. Asserted relationally (the whole
    # list vs. the same list from an offset) rather than against absolute
    # positions, because this suite's SQLite file is shared across test
    # modules and other tests add candidate pages of their own.
    for i in range(3):
        await _make_m3u8_page(f"card-backfill-offset-{i}")

    def _slugs(offset: int) -> list:
        response = archive_client.post(
            f"/internal/thumbnails/backfill?limit=500&offset={offset}",
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 200
        assert response.json()["offset"] == offset
        return [c["slug"] for c in response.json()["candidates"]]

    everything = _slugs(0)
    assert len(everything) >= 3
    assert _slugs(2) == everything[2:]
    assert _slugs(len(everything)) == []


async def test_backfill_by_slugs_returns_exactly_those_pages_in_order():
    # WO-37: the real sweep names the pages it wants so it can interleave
    # across media hosts and rate-limit one CDN (Granicus, 59% of the
    # backlog and the same host the transcription workers already time
    # out against) independently of the others. Order matters -- it is
    # the whole point of choosing.
    first = await _make_m3u8_page("card-backfill-slug-a")
    second = await _make_m3u8_page("card-backfill-slug-b")

    response = archive_client.post(
        f"/internal/thumbnails/backfill?slugs={second['slug']}&slugs={first['slug']}",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    assert [c["slug"] for c in response.json()["candidates"]] == [
        second["slug"],
        first["slug"],
    ]


async def test_backfill_by_slugs_still_filters_out_a_page_that_has_a_frame():
    # Naming a slug must not be able to force a duplicate extraction --
    # the "no default thumbnail yet" filter applies either way.
    warmed = await _make_m3u8_page("card-backfill-slug-warmed")
    await crud.store_thumbnail(
        warmed["page_id"],
        offset_seconds=900,
        image_bytes=_TINY_JPEG,
        etag="2" * 64,
        is_default=True,
    )
    cold = await _make_m3u8_page("card-backfill-slug-cold")

    response = archive_client.post(
        f"/internal/thumbnails/backfill?slugs={warmed['slug']}&slugs={cold['slug']}",
        headers={"Authorization": "Bearer test-token"},
    )
    assert [c["slug"] for c in response.json()["candidates"]] == [cold["slug"]]


def test_backfill_by_slugs_ignores_an_unknown_slug():
    response = archive_client.post(
        "/internal/thumbnails/backfill?slugs=no-such-page-anywhere",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    assert response.json()["candidates"] == []


def test_backfill_caps_how_many_slugs_one_call_may_name():
    # The endpoint extracts inline, so a caller asking for hundreds at
    # once is asking for a timeout, not a faster sweep.
    query = "&".join(
        f"slugs=page-{i}" for i in range(archive.main.MAX_BACKFILL_SLUGS + 1)
    )
    response = archive_client.post(
        f"/internal/thumbnails/backfill?{query}",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 400


def test_backfill_is_token_gated():
    # 404 rather than 401/403, same posture as every other /internal/* route.
    assert archive_client.post("/internal/thumbnails/backfill").status_code == 404


async def test_backfill_apply_survives_a_failing_last_page(monkeypatch):
    # Regression, real production 500 on 2026-08-21: the apply loop
    # assigned extract_and_store()'s result to `offset`, shadowing the
    # endpoint's own query parameter of that name. Its FrameOutcome.offset
    # is None whenever an extraction fails, so a batch whose LAST page
    # failed left `offset` as None and the response's `max(0, offset)`
    # raised TypeError -> 500.
    #
    # This is the normal case, not an edge case: these extractions pull
    # from live government CDNs that time out constantly (WO-40 measured
    # 113 real ffmpeg timeouts across production jobs), so a batch ending
    # in a failure is routine. Every pre-existing slugs test asserted on
    # `candidates`, i.e. dry_run only -- nothing exercised the apply path
    # at all, which is how this reached production.
    #
    # extract_and_store is patched rather than run: what's under test is
    # the endpoint's own bookkeeping, and the suite is deliberately
    # network-free (see this module's docstring).
    ok = await _make_m3u8_page("card-backfill-apply-ok")
    doomed = await _make_m3u8_page("card-backfill-apply-doomed")

    async def _fake_extract(*, page_id, video_url, source_page_url):
        # Succeeds for the first page, fails for the one asked for last.
        if page_id == ok["page_id"]:
            return video_thumbnail.FrameOutcome(900.0)
        return video_thumbnail.FrameOutcome(None, "ffmpeg timed out after 45s")

    monkeypatch.setattr(
        archive.main.video_thumbnail, "extract_and_store", _fake_extract
    )

    response = archive_client.post(
        f"/internal/thumbnails/backfill?dry_run=false"
        f"&slugs={ok['slug']}&slugs={doomed['slug']}",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["attempted"] == 2
    assert body["stored"] == 1
    assert [r["offset_seconds"] for r in body["results"]] == [900.0, None]
    # The echoed offset must still be the query parameter, not a leaked
    # extraction result.
    assert body["offset"] == 0


async def test_backfill_apply_survives_every_page_failing(monkeypatch):
    # The shape the real sweep hit hardest: once the in-process failure
    # cooldown kicks in, extract_and_store() returns None immediately for
    # every page in the batch, so batches 2 and 3 of the first real run
    # 500'd in ~2s each rather than after doing any work.
    page = await _make_m3u8_page("card-backfill-apply-all-fail")

    async def _always_fails(*, page_id, video_url, source_page_url):
        return video_thumbnail.FrameOutcome(
            None,
            "skipped: cooling down after an earlier failure (retried after 6h)",
            True,
        )

    monkeypatch.setattr(
        archive.main.video_thumbnail, "extract_and_store", _always_fails
    )

    response = archive_client.post(
        f"/internal/thumbnails/backfill?dry_run=false&slugs={page['slug']}",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    assert response.json()["stored"] == 0


# --- why a frame is missing (WO-42) --------------------------------------
#
# Until this, every failure path in extract_and_store() returned a bare
# None and the reason media_probe.extract_frame() had already computed was
# logged and thrown away. Not a hypothetical gap: the first real
# production sweep finished 2026-08-22 at 973/1152 pages and left 179
# failed slugs whose only recorded signal was their media host.
#
# These are SYNTHETIC in one respect only -- ffmpeg is not run, the same
# way every other route/storage test in this module stands ffmpeg down --
# but the reason strings are not invented. Each is either a literal from
# media_probe.extract_frame()'s own source or real ffmpeg stderr, captured
# 2026-08-22 by pointing real ffmpeg (8.1.2) at a local HTTP server
# returning each status. Production runs ffmpeg 5.1.9 (the version
# /api/health reports on the Archive service), so the exit codes below are
# the locally-observed ones rather than a claim about the deployed build;
# what the bucketing depends on is the *message* text, and this repo has
# already observed a real "Server returned 404" from a real Granicus CDN
# (see tests/conftest.py's _no_real_card_extraction). Still unconfirmed:
# which of these reasons the 179 real failures will actually turn out to
# be -- that is the question this change exists to make answerable, not
# one it answers.

# Real ffmpeg 8.1.2 output, verbatim, for HTTP 403 and 404 -- the shape
# extract_frame() keeps the last 300 characters of. Note it names the
# status twice, in two different phrasings; both are why
# scripts/backfill_meeting_cards.py matches either.
REAL_FFMPEG_403_STDERR_TAIL = (
    "[http @ 0x9f0c0c400] HTTP error 403 Forbidden\n"
    "[in#0 @ 0x9f0c20000] Error opening input: Server returned 403 Forbidden "
    "(access denied)\n"
    "Error opening input file https://archive-stream.granicus.com/x/y.m3u8.\n"
    "Error opening input files: Server returned 403 Forbidden (access denied)"
)
REAL_FFMPEG_404_STDERR_TAIL = (
    "[http @ 0x76740c000] HTTP error 404 Not Found\n"
    "[in#0 @ 0x766804000] Error opening input: Server returned 404 Not Found\n"
    "Error opening input file https://archive-media.granicus.com/a.mp4.\n"
    "Error opening input files: Server returned 404 Not Found"
)

# Every distinct reason extract_frame() can hand back, one per branch of
# its source. A `?t=` timestamp is used throughout so no ffprobe is
# involved at all (tier 1 is pure arithmetic), which keeps these tests to
# the one subprocess boundary they are about.
EXTRACT_FRAME_REASONS = [
    "ffmpeg not found on PATH",
    "ffmpeg timed out after 45s",
    "ffmpeg could not be started: [Errno 12] Cannot allocate memory",
    f"ffmpeg exited 8: {REAL_FFMPEG_403_STDERR_TAIL}",
    f"ffmpeg exited 8: {REAL_FFMPEG_404_STDERR_TAIL}",
    "ffmpeg exited 0 but wrote no frame @ 600s (no stderr)",
]

_GRANICUS_M3U8 = "https://archive-stream.granicus.com/x/y.m3u8"
_GRANICUS_PAGE = "https://example.granicus.com/player/clip/1"


@pytest.fixture
def clean_extraction_state():
    """extract_and_store()'s two module-level dicts are process-wide by
    design (they exist to stop a crawl re-probing a dead source on every
    render), so a test that seeds either must not leak it into the next
    one."""
    video_thumbnail._failed_at.clear()
    video_thumbnail._inflight.clear()
    yield
    video_thumbnail._failed_at.clear()
    video_thumbnail._inflight.clear()


def _extract_frame_returning(result, *, calls=None):
    async def _fake(media_url, *, offset, source_page_url, out_path):
        if calls is not None:
            calls.append((media_url, offset))
        return result

    return _fake


async def _writes_a_frame(media_url, *, offset, source_page_url, out_path):
    out_path.write_bytes(_TINY_JPEG)
    return True, None


@pytest.mark.parametrize("reason", EXTRACT_FRAME_REASONS)
async def test_every_extract_frame_reason_reaches_the_caller(
    monkeypatch, clean_extraction_state, reason
):
    monkeypatch.setattr(
        media_probe, "extract_frame", _extract_frame_returning((False, reason))
    )

    outcome = await real_extract_and_store(
        page_id=910001,
        video_url=_GRANICUS_M3U8,
        source_page_url=_GRANICUS_PAGE,
        timestamp=982,
    )

    assert outcome.offset is None
    assert outcome.stored is False
    # Verbatim, not summarised: the ffmpeg stderr tail is the whole point
    # -- it carries the CDN's own status line.
    assert outcome.reason == reason
    # A real attempt was made against the source. That is what separates
    # this from the skips below, and what makes it worth blacklisting.
    assert outcome.skipped is False


async def test_a_failure_without_a_reason_still_says_something(
    monkeypatch, clean_extraction_state
):
    # Defensive: extract_frame() always supplies a reason today, so this
    # is the one branch here with no real occurrence behind it. It exists
    # because the bare `None` it guards against is exactly the
    # undiagnosable state this change removes -- a future (False, None)
    # must not quietly restore it.
    monkeypatch.setattr(
        media_probe, "extract_frame", _extract_frame_returning((False, None))
    )

    outcome = await real_extract_and_store(
        page_id=910002,
        video_url=_GRANICUS_M3U8,
        source_page_url=_GRANICUS_PAGE,
        timestamp=982,
    )
    assert outcome.reason == video_thumbnail.UNREPORTED_FAILURE
    assert outcome.skipped is False


async def test_the_cooldown_is_reported_as_a_skip_not_a_failure(
    monkeypatch, clean_extraction_state
):
    # The distinction that matters operationally. A cooldown hit means the
    # Archive did *no work at all* on this page -- it declined, on the
    # strength of an earlier failure it remembers in-process. A sweep that
    # recorded that the way it records a real failure would blacklist a
    # page nothing was attempted against, and (because the cooldown dict
    # dies with the dyno) would do so on the strength of a fact that no
    # longer exists after the next deploy.
    calls = []
    monkeypatch.setattr(
        media_probe,
        "extract_frame",
        _extract_frame_returning((False, "ffmpeg timed out after 45s"), calls=calls),
    )
    kwargs = dict(
        page_id=910003,
        video_url=_GRANICUS_M3U8,
        source_page_url=_GRANICUS_PAGE,
        timestamp=982,
    )

    first = await real_extract_and_store(**kwargs)
    assert first.skipped is False
    assert first.reason == "ffmpeg timed out after 45s"

    second = await real_extract_and_store(**kwargs)
    assert second.offset is None
    assert second.skipped is True
    assert "cooling down" in second.reason
    # And the cooldown really did its job: ffmpeg ran once, not twice.
    assert len(calls) == 1
    # The two reasons must not be confusable -- a caller decides whether
    # to blacklist the page on exactly this difference.
    assert second.reason != first.reason


async def test_an_in_flight_duplicate_is_reported_as_a_skip(
    monkeypatch, clean_extraction_state
):
    # N simultaneous requests for the same uncached card cost one ffmpeg
    # run; the other N-1 return here. Nothing was attempted, so it is a
    # skip.
    calls = []
    monkeypatch.setattr(
        media_probe,
        "extract_frame",
        _extract_frame_returning((True, None), calls=calls),
    )
    video_thumbnail._inflight.add((910004, target_offset_seconds(timestamp=982)))

    outcome = await real_extract_and_store(
        page_id=910004,
        video_url=_GRANICUS_M3U8,
        source_page_url=_GRANICUS_PAGE,
        timestamp=982,
    )

    assert outcome == video_thumbnail.FrameOutcome(
        None, video_thumbnail.SKIP_IN_FLIGHT, True
    )
    assert calls == []


async def test_a_full_queue_is_reported_as_a_skip_with_its_depth(
    monkeypatch, clean_extraction_state
):
    calls = []
    monkeypatch.setattr(
        media_probe,
        "extract_frame",
        _extract_frame_returning((True, None), calls=calls),
    )
    for i in range(video_thumbnail._MAX_QUEUED_EXTRACTIONS):
        video_thumbnail._inflight.add((920000 + i, 60))

    outcome = await real_extract_and_store(
        page_id=910005,
        video_url=_GRANICUS_M3U8,
        source_page_url=_GRANICUS_PAGE,
        timestamp=982,
    )

    assert outcome.skipped is True
    assert outcome.reason.startswith(video_thumbnail.SKIP_QUEUE_FULL)
    # The depth is in the string because "the queue was full" and "the
    # queue was full at 40" are different operator signals.
    assert str(video_thumbnail._MAX_QUEUED_EXTRACTIONS) in outcome.reason
    assert calls == []


async def test_a_rejected_store_is_reported_as_a_failure(
    monkeypatch, clean_extraction_state
):
    # store_thumbnail() returns False (never raises) when the page is at
    # MAX_FRAMES_PER_PAGE, when a concurrent writer won, or when the table
    # isn't there. ffmpeg succeeded, so this is not a source problem --
    # and before WO-42 it was indistinguishable from one.
    monkeypatch.setattr(media_probe, "extract_frame", _writes_a_frame)

    async def _rejects(*_args, **_kwargs):
        return False

    monkeypatch.setattr(crud, "store_thumbnail", _rejects)

    outcome = await real_extract_and_store(
        page_id=910006,
        video_url=_GRANICUS_M3U8,
        source_page_url=_GRANICUS_PAGE,
        timestamp=982,
    )

    assert outcome.offset is None
    assert outcome.skipped is False
    assert outcome.reason == video_thumbnail.STORE_REJECTED


async def test_an_unexpected_exception_is_reported_not_swallowed(
    monkeypatch, clean_extraction_state
):
    # The catch-all exists because a thumbnail is decoration and nothing
    # here may escape into a BackgroundTask. It must stay total -- and now
    # also say what happened.
    async def _blows_up(media_url, *, offset, source_page_url, out_path):
        raise RuntimeError("ffprobe subprocess vanished")

    monkeypatch.setattr(media_probe, "extract_frame", _blows_up)

    outcome = await real_extract_and_store(
        page_id=910007,
        video_url=_GRANICUS_M3U8,
        source_page_url=_GRANICUS_PAGE,
        timestamp=982,
    )

    assert outcome.offset is None
    assert outcome.skipped is False
    assert outcome.reason.startswith("extraction raised RuntimeError")
    assert "ffprobe subprocess vanished" in outcome.reason


async def test_a_stored_frame_reports_its_offset_and_no_reason(
    monkeypatch, clean_extraction_state
):
    page = await _make_m3u8_page("card-outcome-success")
    monkeypatch.setattr(media_probe, "extract_frame", _writes_a_frame)

    outcome = await real_extract_and_store(
        page_id=page["page_id"],
        video_url="https://archive-media.granicus.com/OnDemand/x/x.m3u8",
        source_page_url=_GRANICUS_PAGE,
        timestamp=982,
    )

    assert outcome.offset == target_offset_seconds(timestamp=982)
    assert outcome.stored is True
    assert outcome.reason is None
    assert outcome.skipped is False


async def test_backfill_response_carries_the_reason_and_the_skip_flag(monkeypatch):
    # The endpoint half of the same gap: a sweep reads this response, and
    # `offset_seconds: null` on its own is what made the real 179-failure
    # set undiagnosable.
    stored_page = await _make_m3u8_page("card-backfill-reason-stored")
    failed_page = await _make_m3u8_page("card-backfill-reason-failed")
    skipped_page = await _make_m3u8_page("card-backfill-reason-skipped")
    failure_reason = f"ffmpeg exited 8: {REAL_FFMPEG_404_STDERR_TAIL}"

    async def _fake_extract(*, page_id, video_url, source_page_url):
        if page_id == stored_page["page_id"]:
            return video_thumbnail.FrameOutcome(15381)
        if page_id == failed_page["page_id"]:
            return video_thumbnail.FrameOutcome(None, failure_reason)
        return video_thumbnail.FrameOutcome(
            None, f"{video_thumbnail.SKIP_QUEUE_FULL} (40 in flight)", True
        )

    monkeypatch.setattr(
        archive.main.video_thumbnail, "extract_and_store", _fake_extract
    )

    response = archive_client.post(
        "/internal/thumbnails/backfill?dry_run=false"
        f"&slugs={stored_page['slug']}"
        f"&slugs={failed_page['slug']}"
        f"&slugs={skipped_page['slug']}",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["attempted"] == 3
    assert body["stored"] == 1
    # A skip is counted apart from a failure at the top level too, so an
    # operator can tell "the Archive declined 40 pages" from "40 sources
    # are unreachable" without reading every result.
    assert body["skipped"] == 1

    by_slug = {r["slug"]: r for r in body["results"]}
    assert by_slug[stored_page["slug"]]["offset_seconds"] == 15381
    assert by_slug[stored_page["slug"]]["reason"] is None
    assert by_slug[stored_page["slug"]]["skipped"] is False

    assert by_slug[failed_page["slug"]]["offset_seconds"] is None
    assert by_slug[failed_page["slug"]]["reason"] == failure_reason
    assert by_slug[failed_page["slug"]]["skipped"] is False

    assert by_slug[skipped_page["slug"]]["offset_seconds"] is None
    assert by_slug[skipped_page["slug"]]["skipped"] is True
    # video_url is still echoed alongside the reason -- host grouping did
    # not stop being useful, it stopped being the only thing available.
    assert by_slug[failed_page["slug"]]["video_url"]


def test_dry_run_still_reports_only_candidates():
    # The reason/skipped fields belong to a real attempt. A dry run makes
    # none, so it must not start implying it did.
    response = archive_client.post(
        "/internal/thumbnails/backfill?limit=1",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert "results" not in body
    for candidate in body["candidates"]:
        assert set(candidate) == {"slug", "video_url"}
