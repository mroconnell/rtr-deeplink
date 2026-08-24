"""The rendered shape of one `/meetings` result row (2026-08-24).

Every other search test in this suite checks the *data*
(crud._result_snippet(), tests/test_search_deep_links.py) -- what a
reader actually sees was untested, and this row's two links were
deliberately rearranged on Ryan's call:

* the **headline** now opens the matched second, not the top of the
  video, because the reader typed a topic to get there;
* **"Play from 0:00"** below it is the escape hatch to the whole meeting,
  and is also the row's one plain internal link to the canonical
  `/m/{slug}`;
* the **timestamp is stamped on the front of the quote**, because
  nothing previously tied the excerpt to the "Play from 56:04" three
  lines under it.

The degraded row -- a match that couldn't be tied to a transcript segment
-- is the case most likely to be broken by a later edit, since it shares
one template with the deep-linked one: it must fall back to a plain
headline link and offer no "Play from 0:00" at all (a second copy of the
link the headline already is).
"""

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud

client = TestClient(archive.main.app)

_BASE = "https://example.granicus.com/player/clip/"


def _payload(external_id: str, source_url: str, *, segments, agenda_items=None) -> dict:
    return {
        "platform": "granicus",
        "source_url": source_url,
        "external_id": external_id,
        "title": "Row Markup Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": "City of Rowmarkup Test, CA",
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": segments,
        "agenda_items": agenda_items or [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }


async def _ingest(external_id: str, **kwargs) -> str:
    url = f"{_BASE}{external_id}"
    await crud.ingest_resolution(
        _payload(f"granicus:{external_id}", url, **kwargs), url
    )
    return url


async def test_headline_link_opens_the_matched_second():
    await _ingest(
        "row-markup-hit",
        segments=[
            {"start": 0.0, "end": 5.0, "text": "Call to order, roll call please."},
            # 3364s -> 56:04, the timestamp from Ryan's own example.
            {"start": 3364.0, "end": 3370.0, "text": "opposed to zzyzxrowmark here"},
        ],
    )
    body = client.get("/meetings", params={"q": "zzyzxrowmark"}).text

    # The headline anchor carries both the title and the destination.
    assert 'data-result-link="deep_link"' in body
    assert "?t=3364" in body
    assert "Play from 56:04" in body
    # ...and the timestamp also labels the quote, which is the thing that
    # says "this excerpt is what that link plays".
    assert '<span class="snippet-time">56:04</span>' in body
    # The escape hatch: the plain meeting page, no ?t=.
    assert "Play from 0:00" in body
    assert 'href="/m/' in body


async def test_a_match_without_a_segment_keeps_the_plain_row():
    """An agenda-only hit has no moment to link to, so the row must render
    exactly as it did before deep links existed -- plain headline, and no
    "Play from 0:00" duplicating it."""
    await _ingest(
        "row-markup-agenda",
        segments=[],
        agenda_items=[{"text": "Ordinance regarding zzyzxrowagenda permits"}],
    )
    body = client.get("/meetings", params={"q": "zzyzxrowagenda"}).text

    assert "Row Markup Test Meeting" in body
    assert 'data-result-link="meeting_page"' in body
    assert 'data-result-link="deep_link"' not in body
    assert "Play from 0:00" not in body
    assert "snippet-time" not in body


async def test_bare_browse_listing_offers_no_deep_link_treatment():
    """No keyword means no matched moment for any row -- the whole
    treatment is absent, not rendered with an empty timestamp."""
    await _ingest(
        "row-markup-browse",
        segments=[{"start": 12.0, "end": 15.0, "text": "Ordinary meeting content."}],
    )
    body = client.get("/meetings").text

    assert "Row Markup Test Meeting" in body
    assert 'data-result-link="deep_link"' not in body
    assert "Play from 0:00" not in body
