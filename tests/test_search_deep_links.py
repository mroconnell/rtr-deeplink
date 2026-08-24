"""`/meetings` search results carry a deep link into the matched moment.

Real-DB integration coverage for crud._result_snippet(), against the
isolated SQLite fixture DB (same pattern as
tests/test_list_pages_search.py).

The behaviour under test: a keyword hit inside a transcript segment
yields that segment's own `start`, so the result can offer "play from
14:30" instead of dropping the reader at the top of a three-hour video.
When the match *can't* be tied to one segment, the row must degrade to
exactly the snippet-only shape it had before deep links existed -- that
fallback is not an edge case (see the phrase-boundary test below), and
it is the thing most likely to be broken by a later refactor.
"""

from archive.db import crud

_BASE = "https://example.granicus.com/player/clip/"


def _payload(external_id: str, source_url: str, *, segments, agenda_items=None) -> dict:
    return {
        "platform": "granicus",
        "source_url": source_url,
        "external_id": external_id,
        "title": "Deep Link Search Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": "City of Deeplink Test, CA",
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


async def _row_for(keyword: str, external_id: str) -> dict:
    """The single result row for a keyword that only this meeting matches."""
    result = await crud.list_pages(keyword=keyword, page_size=50)
    rows = [r for r in result["pages"] if r["slug"]]
    assert rows, f"no results for {keyword!r}"
    return rows[0]


async def test_transcript_match_yields_deep_link_at_that_second():
    await _ingest(
        "deeplink-hit",
        segments=[
            {"start": 0.0, "end": 5.0, "text": "Call to order, roll call please."},
            {"start": 870.0, "end": 875.0, "text": "concerns about zzyzxflockcam here"},
        ],
    )
    row = await _row_for("zzyzxflockcam", "deeplink-hit")

    assert row["start_seconds"] == 870.0
    # Not the top of the video -- the actual moment, and the label a
    # reader sees must agree with the link.
    assert row["deep_link"] == f"/m/{row['slug']}?t=870"
    assert row["timestamp_label"] == "14:30"
    assert "zzyzxflockcam" in row["snippet"]


async def test_quote_widens_past_the_matched_cue():
    """A caption cue is only a few words; quoting it alone would make
    search snippets *shorter* than they were before deep links. The
    neighbouring cues get folded in (SEARCH_CONTEXT_SEGMENTS)."""
    await _ingest(
        "deeplink-context",
        segments=[
            {"start": 10.0, "end": 12.0, "text": "the proposed ordinance would"},
            {"start": 12.0, "end": 14.0, "text": "ban zzyzxwidget entirely"},
            {"start": 14.0, "end": 16.0, "text": "within city limits next year"},
        ],
    )
    row = await _row_for("zzyzxwidget", "deeplink-context")

    assert row["start_seconds"] == 12.0
    # Text from the cues either side of the match, not just the match's own.
    assert "proposed ordinance" in row["snippet"]
    assert "city limits" in row["snippet"]


async def test_phrase_split_across_two_cues_still_gets_a_snippet():
    """The fallback path, and the reason it must keep searching the joined
    transcript text rather than only the per-segment scan.

    find_matching_segment() works one segment at a time, so a quoted
    phrase whose words land either side of a cue boundary matches the
    joined blob and no single segment. Losing the deep link there is
    fine; losing the *snippet* would be a regression.
    """
    await _ingest(
        "deeplink-split",
        segments=[
            {"start": 30.0, "end": 32.0, "text": "we should discuss the zzyzxdata"},
            {"start": 32.0, "end": 34.0, "text": "zentrum proposal tonight"},
        ],
    )
    row = await _row_for('"zzyzxdata zentrum"', "deeplink-split")

    assert row["snippet"] is not None
    assert "zzyzxdata" in row["snippet"]
    # No segment owns the phrase, so there is no honest moment to link to.
    assert row["start_seconds"] is None
    assert row["deep_link"] is None
    assert row["card_url"] is None


async def test_agenda_only_match_has_snippet_but_no_deep_link():
    await _ingest(
        "deeplink-agenda",
        segments=[{"start": 0.0, "end": 3.0, "text": "unrelated opening remarks"}],
        agenda_items=[{"text": "Item 4: zzyzxrezone district boundary change"}],
    )
    row = await _row_for("zzyzxrezone", "deeplink-agenda")

    assert row["snippet"] is not None
    assert "zzyzxrezone" in row["snippet"]
    assert row["start_seconds"] is None
    assert row["deep_link"] is None


async def test_no_card_url_without_a_stored_frame():
    """pages_with_thumbnails() is the existence check -- a card URL that
    would 404 is worse than none (Google's validator and every social
    scraper fetches it). Nothing in this test DB has stored bytes."""
    await _ingest(
        "deeplink-nocard",
        segments=[{"start": 60.0, "end": 62.0, "text": "the zzyzxnocard question"}],
    )
    row = await _row_for("zzyzxnocard", "deeplink-nocard")

    assert row["deep_link"] is not None
    assert row["card_url"] is None


async def test_bare_browse_listing_is_unchanged():
    """No keyword means no snippet, no deep link and no images -- the
    default /meetings stays the compact listing it has always been."""
    await _ingest(
        "deeplink-browse",
        segments=[{"start": 0.0, "end": 2.0, "text": "ordinary meeting content"}],
    )
    result = await crud.list_pages(page_size=5)

    assert result["pages"]
    for row in result["pages"]:
        assert row["snippet"] is None
        assert row["start_seconds"] is None
        assert row["deep_link"] is None
        assert row["card_url"] is None


async def test_context_never_spans_a_gap_in_the_transcript():
    """Neighbouring cues are not necessarily neighbouring moments.

    Found in the browser (2026-08-24): a sparse transcript put "...then we
    will begin" at 0:05 directly beside a sentence spoken at 10:40, and
    joining them quoted a continuous-sounding sentence nobody ever said.
    Widening context must stop at a real gap -- a misleading quote is a
    worse failure than a short one.
    """
    await _ingest(
        "deeplink-gap",
        segments=[
            {"start": 0.0, "end": 5.0, "text": "Roll call, and then we will begin."},
            {"start": 640.0, "end": 646.0, "text": "proposing a zzyzxdatacenter here"},
            {"start": 646.0, "end": 652.0, "text": "north of the interchange tonight"},
        ],
    )
    row = await _row_for("zzyzxdatacenter", "deeplink-gap")

    assert row["start_seconds"] == 640.0
    # The contiguous cue on the right is folded in...
    assert "north of the interchange" in row["snippet"]
    # ...but the one 10 minutes earlier is not.
    assert "then we will begin" not in row["snippet"]


async def test_missing_timings_still_get_context():
    """A cue with no `end` must not lose its context -- timings are
    advisory here, and dropping real words over a missing field would be
    the worse error. See _adjacent()."""
    await _ingest(
        "deeplink-notiming",
        segments=[
            {"start": 20.0, "text": "the council discussed whether"},
            {"start": 24.0, "text": "the zzyzxnotiming proposal should proceed"},
        ],
    )
    row = await _row_for("zzyzxnotiming", "deeplink-notiming")

    assert row["start_seconds"] == 24.0
    assert "council discussed" in row["snippet"]
