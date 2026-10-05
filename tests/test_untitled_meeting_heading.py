"""WO-1176: a meeting page with no title reads "<government> meeting", not
"Untitled meeting"; "Untitled meeting" stays only when there is no
government either.

Synthetic pages via crud.ingest_resolution(), same pattern as
test_meeting_page_structured_data.py. "Fresno, CA" is a real, confirmed-
unambiguous city. Synthetic because the thing under test is template
fallback logic, not adapter parsing.
"""

import re

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud

archive_client = TestClient(archive.main.app)


async def _page(external_id: str, **overrides) -> str:
    url = f"https://example.com/wo1176/{external_id}"
    payload = {
        "platform": "direct_file",
        "source_url": url,
        "external_id": external_id,
        "title": None,
        "date": "2026-01-01",
        "jurisdiction": "Fresno, CA",
        "video_url": "https://example.com/wo1176/video.mp4",
        "video_format": "mp4",
        "segments": [],
        "agenda_items": [],
        "transcript_language": None,
        "transcript_warnings": [],
    }
    payload.update(overrides)
    result = await crud.ingest_resolution(payload, url)
    return result["slug"]


def _h1(html: str) -> str:
    m = re.search(r"<h1>(.*?)</h1>", html, re.DOTALL)
    assert m
    return re.sub(r"<button.*?</button>", "", m.group(1), flags=re.DOTALL).strip()


async def test_untitled_page_with_a_government_reads_government_meeting():
    slug = await _page("untitled-with-gov")
    html = archive_client.get(f"/m/{slug}").text
    assert "Untitled meeting" not in html
    assert _h1(html).endswith(" meeting")
    assert "Fresno" in _h1(html)
    # The browser tab keeps "Meeting — <government>": the government is
    # already after the dash, so repeating it before reads as a stutter.
    title = re.search(r"<title>([^<]*)</title>", html).group(1)
    assert title.startswith("Meeting — ") and title.count("Fresno") == 1


async def test_titled_page_keeps_its_own_title():
    slug = await _page("titled", title="Regular City Council Meeting")
    assert _h1(archive_client.get(f"/m/{slug}").text) == "Regular City Council Meeting"


async def test_search_meetings_list_row_reads_government_meeting():
    """The /meetings list row (archive/templates/meeting_list.html) uses the
    same fallback as the page heading -- it was missed in the first pass
    because it formats the government with the jurisdiction_display filter,
    not a page field."""
    slug = await _page(
        "list-row", segments=[{"start": 0.0, "end": 5.0, "text": "Call to order."}]
    )
    html = archive_client.get("/meetings").text
    m = re.search(
        rf'href="/m/{slug}"[^>]*>\s*<span class="result-title-text">([^<]*)</span>',
        html,
    )
    assert m, "the untitled page should be listed"
    assert m.group(1).endswith(" meeting") and "Fresno" in m.group(1)
