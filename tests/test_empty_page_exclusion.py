"""Coverage for the query-time "empty page" exclusion
(archive/db/crud.py's _is_empty_page_condition(), 2026-08-17): a page with
no video, no agenda items/link and no transcript is left out of the default
/meetings browse, /sitemap.xml and /feed.xml, is noindexed on its own /m/
page, but is still *served* and still shows up under an explicit
has_transcript=false filter (that's how gaps get found). Also pins the
"Upcoming"/"Recent" date pills on the listing and the matching notice on
the meeting page.

Real motivation, measured live 2026-08-17: 17 of ~1,200 production pages
were exactly this shape, several of them recent or not-yet-held meetings
whose source will publish captions later -- so the exclusion is a live
predicate, not a stored flag or a delete (see CLAUDE_BACKLOG.md's "Archive
hygiene" section). Seeded rows use unique external_ids/source_urls per
this suite's shared-session-DB convention (tests/conftest.py).
"""

from datetime import date, timedelta

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud

client = TestClient(archive.main.app)

# A jurisdiction no other test seeds, so jurisdiction-scoped listing calls
# below see only this file's rows regardless of what else ran first.
JX = "Emptytest City, CA"


def _payload(external_id: str, **overrides) -> dict:
    payload = {
        "platform": "granicus",
        "source_url": f"https://example.com/emptytest/{external_id}",
        "external_id": external_id,
        "title": f"Emptytest {external_id}",
        "date": "2024-03-05",
        "jurisdiction": JX,
        "video_url": None,
        "video_format": None,
        "segments": [],
        "agenda_items": [],
        "agenda_link": None,
        "transcript_language": None,
        "transcript_warnings": [],
    }
    payload.update(overrides)
    return payload


async def _seed(external_id: str, **overrides) -> str:
    payload = _payload(external_id, **overrides)
    result = await crud.ingest_resolution(payload, payload["source_url"])
    return result["slug"]


async def _listing_slugs(**kwargs) -> set[str]:
    result = await crud.list_pages(jurisdiction=JX, page_size=100, **kwargs)
    return {p["slug"] for p in result["pages"]}


# --- what counts as empty ------------------------------------------------


async def test_empty_page_hidden_from_default_browse_but_visible_under_gap_filter():
    empty = await _seed("empty:plain")
    assert empty not in await _listing_slugs()
    # The explicit gap filter is where these are *supposed* to show up.
    assert empty in await _listing_slugs(has_transcript=False)
    assert empty in await _listing_slugs(has_transcript=False, has_agenda=False)


async def test_video_only_page_is_not_empty():
    slug = await _seed(
        "notempty:video", video_url="https://example.com/v.m3u8", video_format="m3u8"
    )
    assert slug in await _listing_slugs()


async def test_agenda_link_only_page_is_not_empty():
    slug = await _seed("notempty:agendalink", agenda_link="https://example.com/a.pdf")
    assert slug in await _listing_slugs()


async def test_agenda_items_only_page_is_not_empty():
    slug = await _seed(
        "notempty:agenda", agenda_items=[{"start": 0, "text": "Call to order"}]
    )
    assert slug in await _listing_slugs()


async def test_transcript_only_page_is_not_empty():
    slug = await _seed(
        "notempty:transcript",
        segments=[{"start": 0, "end": 1, "text": "hello"}],
        transcript_language="en",
    )
    assert slug in await _listing_slugs()


async def test_empty_page_reappears_once_filled_in():
    """The whole point of a live predicate: no un-hide step. A recheck that
    later pushes real content for the same source URL makes the page show
    up again on its own."""
    slug = await _seed("empty:later-filled")
    assert slug not in await _listing_slugs()
    payload = _payload(
        "empty:later-filled",
        video_url="https://example.com/late.m3u8",
        video_format="m3u8",
    )
    await crud.ingest_resolution(payload, payload["source_url"])
    assert slug in await _listing_slugs()


# --- sitemap / feed / page ----------------------------------------------


async def test_sitemap_and_feed_exclude_empty_pages():
    empty = await _seed("empty:sitemap")
    real = await _seed(
        "notempty:sitemap", video_url="https://example.com/s.m3u8", video_format="m3u8"
    )
    sitemap_slugs = {e["slug"] for e in await crud.list_all_page_slugs()}
    assert real in sitemap_slugs
    assert empty not in sitemap_slugs

    feed_slugs = {
        e["slug"] for e in await crud.list_recent_pages_for_feed(jurisdiction=JX)
    }
    assert real in feed_slugs
    assert empty not in feed_slugs


async def test_empty_page_still_serves_but_is_noindexed():
    empty = await _seed("empty:served")
    response = client.get(f"/m/{empty}")
    assert response.status_code == 200
    assert '<meta name="robots" content="noindex">' in response.text

    real = await _seed(
        "notempty:served", video_url="https://example.com/r.m3u8", video_format="m3u8"
    )
    response = client.get(f"/m/{real}")
    assert response.status_code == 200
    assert 'content="noindex"' not in response.text


# --- Upcoming / Recent pills ---------------------------------------------


async def test_upcoming_and_recent_pills_on_listing_and_page():
    today = date.today()
    upcoming = await _seed(
        "pill:upcoming",
        date=(today + timedelta(days=8)).isoformat(),
        agenda_link="https://example.com/upcoming-agenda.pdf",
    )
    recent = await _seed(
        "pill:recent",
        date=(today - timedelta(days=6)).isoformat(),
        video_url="https://example.com/recent.m3u8",
        video_format="m3u8",
    )
    old_gap = await _seed(
        "pill:old",
        date="2021-01-04",
        video_url="https://example.com/old.m3u8",
        video_format="m3u8",
    )
    recent_with_transcript = await _seed(
        "pill:recent-done",
        date=(today - timedelta(days=6)).isoformat(),
        segments=[{"start": 0, "end": 1, "text": "done"}],
        transcript_language="en",
    )

    rows = {
        p["slug"]: p
        for p in (await crud.list_pages(jurisdiction=JX, page_size=100))["pages"]
    }
    assert rows[upcoming]["date_status"] == "upcoming"
    assert rows[recent]["date_status"] == "recent"
    assert rows[old_gap]["date_status"] is None
    assert rows[recent_with_transcript]["date_status"] is None

    listing = client.get("/meetings", params={"jurisdiction": JX}).text
    assert 'class="date-status-pill"' in listing
    assert ">Upcoming</span>" in listing
    assert ">Recent</span>" in listing

    page = client.get(f"/m/{upcoming}").text
    assert "date-status-upcoming" in page
    assert "hasn&#39;t happened yet" in page or "hasn't happened yet" in page
    page = client.get(f"/m/{recent}").text
    assert "date-status-recent" in page
    page = client.get(f"/m/{old_gap}").text
    assert "date-status-notice" not in page
