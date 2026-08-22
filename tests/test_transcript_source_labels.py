"""`TranscriptVersion.source` as both provenance and the version picker's
display label (user's call, 2026-08-22 -- see models.py's docstring).

What's under test is the *fallback* shape of the two places that used to
allowlist `source == "scraped"`:

  * meeting_page.html's non-AI disclaimer branch
  * crud.py's `has_scraped_transcript` coverage predicate

Both silently excluded any new source value. Adding "deduped"
(scripts/dedupe_rollup_transcripts.py) would have rendered 23 real pages
with no third-party disclaimer at all. Removing duplicated caption lines
does not make a third-party transcript reviewed, so the disclaimer must
survive a re-label.

Synthetic pages via crud.ingest_resolution(), same pattern and payload
shape as test_meeting_page_structured_data.py -- what's exercised is
template branching and one SQL predicate, not adapter parsing. The
segment shape is the real {start, end, text} every adapter produces.
"""

import pytest
from fastapi.testclient import TestClient

import archive.main
from archive.db import crud

archive_client = TestClient(archive.main.app)

_AI_DISCLAIMER = "AI TRANSCRIPT"
_NON_AI_MARKER = "sourceDisclaimerPointer"

_SEGMENTS = [
    {"start": 0.0, "end": 5.0, "text": "Good evening, we're going to begin."},
    {"start": 5.0, "end": 10.0, "text": "Please stand for the pledge."},
]


async def _make_page(
    external_id: str, source: str | None, jurisdiction: str = "Fresno, CA"
) -> str:
    url = f"https://example.com/source-label/{external_id}"
    payload = {
        "platform": "granicus",
        "source_url": url,
        "external_id": external_id,
        "title": "Source Label Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": jurisdiction,
        "video_url": "https://example.granicus.com/video.m3u8",
        "video_format": "m3u8",
        "segments": _SEGMENTS,
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }
    if source is not None:
        payload["source"] = source
    result = await crud.ingest_resolution(payload, url)
    return result["slug"]


# --- the disclaimer must survive a re-label -----------------------------


@pytest.mark.parametrize("source", [None, "scraped", "deduped"])
async def test_every_non_ai_source_still_gets_the_third_party_disclaimer(source):
    # `None` exercises the ingest default. "deduped" is the value that
    # broke the old allowlist. Any future value lands here too, which is
    # the entire point of the `{% else %}` fallback.
    slug = await _make_page(f"non-ai-{source or 'default'}", source)
    html = archive_client.get(f"/m/{slug}").text
    assert _NON_AI_MARKER in html, source
    assert _AI_DISCLAIMER not in html, source


async def test_transcribed_still_gets_the_ai_disclaimer_and_not_the_other():
    # The one value that must NOT fall through to the fallback branch --
    # an AI transcript needs the stronger "never actually said" warning.
    slug = await _make_page("ai", "transcribed")
    html = archive_client.get(f"/m/{slug}").text
    assert _AI_DISCLAIMER in html
    assert _NON_AI_MARKER not in html


# --- the picker label -------------------------------------------------


def test_source_label_maps_every_internal_token_a_reader_can_reach():
    label = archive.main.templates.env.filters["source_label"]
    # "scraped" is an internal token the user has never wanted shown --
    # confirmed 2026-08-22 that it reaches no template except through
    # this filter.
    assert label("scraped") == "sourced"
    # Distinct from "sourced" on purpose: the picker's option text is
    # language + source, so two same-language versions of one meeting
    # would otherwise both read "English (sourced)".
    assert label("deduped") == "de-duplicated"
    assert label("scraped") != label("deduped")


def test_source_label_falls_through_for_an_unmapped_token():
    # Documents current behaviour rather than blessing it: an unmapped
    # token leaks verbatim to a reader. Guarded by models.py's docstring
    # ("add it to _SOURCE_LABELS") rather than by a raise, so a typo
    # degrades to ugly instead of 500ing a real meeting page.
    label = archive.main.templates.env.filters["source_label"]
    assert label("something_new") == "something_new"


# --- the coverage predicate -------------------------------------------


@pytest.mark.parametrize("source", ["scraped", "deduped"])
async def test_any_non_ai_source_counts_as_an_instant_source_transcript(source):
    # crud.py's has_scraped_transcript used to require source == "scraped"
    # exactly, so re-labeling a page's only version would have quietly
    # flipped /coverage's "Instant transcript" column to No for it.
    # A distinct jurisdiction per case because the coverage index is one
    # row per jurisdiction, with columns computed across all its pages --
    # sharing one would let the other case's page satisfy the assertion.
    jurisdiction = f"Sourcelabel {source.title()}, CA"
    slug = await _make_page(f"coverage-{source}", source, jurisdiction=jurisdiction)
    rows = await crud.get_full_jurisdiction_coverage()
    row = next((r for r in rows if r["jurisdiction"] == jurisdiction), None)
    assert row is not None, f"{slug} produced no coverage row"
    assert row["instant_transcript"] is True, source
