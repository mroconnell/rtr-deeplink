"""Event JSON-LD block on /m/{slug}: `description` and `image` fields.

Google Search Console flagged a real "Events structured data issues" alert
(8 issues, 2026-08-21) for two real, cheap gaps in the `Event` block in
`archive/templates/meeting_page.html`:

- `description` was only emitted in an `{% else %}` branch mutually
  exclusive with `url` -- since `public_base_url` is set in production,
  `description` never actually rendered in practice.
- `image` had no field at all, despite `thumbnail_url` already being
  computed in scope for `og:image`/`VideoObject.thumbnailUrl`.

See BACKLOG_DONE.md's 2026-08-21 entry for the full write-up. This test
follows the same synthetic-page pattern as
test_meeting_page_structured_data.py (crud.ingest_resolution() with a
real resolver-shaped payload) -- the thing under test is template
rendering, not adapter parsing.
"""

import json
import re

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud

archive_client = TestClient(archive.main.app)

_JSON_LD_RE = re.compile(
    r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>', re.DOTALL
)


def _payload(external_id: str, source_url: str, **overrides) -> dict:
    payload = {
        "platform": "youtube",
        "source_url": source_url,
        "external_id": external_id,
        "title": "Event JSON-LD Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": "Fresno, CA",
        "video_url": "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "video_format": "youtube",
        "segments": [],
        "agenda_items": [],
        "transcript_language": None,
        "transcript_warnings": [],
    }
    payload.update(overrides)
    return payload


async def _make_page(external_id: str, **overrides) -> str:
    url = f"https://example.com/event-jsonld/{external_id}"
    result = await crud.ingest_resolution(_payload(external_id, url, **overrides), url)
    return result["slug"]


def _get_event_json_ld(html: str) -> dict:
    blocks = [json.loads(m) for m in _JSON_LD_RE.findall(html)]
    events = [b for b in blocks if b.get("@type") == "Event"]
    assert len(events) == 1, "expected exactly one Event JSON-LD block"
    return events[0]


async def test_event_block_has_description_and_image_with_base_url(monkeypatch):
    monkeypatch.setitem(
        archive.main.templates.env.globals, "public_base_url", "https://example.org"
    )
    slug = await _make_page("ev-with-base-url")

    response = archive_client.get(f"/m/{slug}")
    assert response.status_code == 200

    event = _get_event_json_ld(response.text)
    assert event["url"] == f"https://example.org/m/{slug}"
    assert "Event JSON-LD Test Meeting" in event["description"]
    assert event["image"] == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
    # Deliberately not asserted present -- see the template's own comment
    # on why eventStatus/eventAttendanceMode/offers are omitted.
    assert "eventStatus" not in event


async def test_event_block_has_description_without_base_url(monkeypatch):
    # Locally (no PUBLIC_BASE_URL) there's no absolute URL for "url", but
    # description must still render -- it's no longer gated behind the
    # public_base_url either/or.
    monkeypatch.setitem(archive.main.templates.env.globals, "public_base_url", "")
    slug = await _make_page("ev-no-base-url")

    response = archive_client.get(f"/m/{slug}")
    event = _get_event_json_ld(response.text)
    assert "url" not in event
    assert "Event JSON-LD Test Meeting" in event["description"]


async def test_event_block_omits_image_for_non_youtube_video(monkeypatch):
    monkeypatch.setitem(
        archive.main.templates.env.globals, "public_base_url", "https://example.org"
    )
    slug = await _make_page(
        "ev-m3u8-page",
        platform="granicus",
        video_url="https://archive-media.granicus.com/OnDemand/x/x.m3u8",
        video_format="m3u8",
    )

    response = archive_client.get(f"/m/{slug}")
    event = _get_event_json_ld(response.text)
    assert "image" not in event
    assert "Event JSON-LD Test Meeting" in event["description"]
