from app.platforms.models import TranscriptSegment
from app.platforms.swagit import SwagitAssetFinder, _group_word_fragments

from aiohttp_mock import FakeResponse, mock_session

# No fixture-based tests existed for this adapter before this file (see
# BACKLOG_DONE.md's "Not yet covered" note) -- scoped here to the new
# caption-file fallback logic only (Swagit previously only ever tried
# #transcript-fragments, a DOM mechanism, never a caption *file*).
# Synthetic HTML, not a live fixture -- no real Swagit meeting has ever
# been observed with a caption file at all (see BACKLOG.md).

PAGE_URL = "https://example.new.swagit.com/videos/1"

BASE_HTML = (
    '<html><head><title>Jul 21, 2026 Town Council Regular Meeting - Example, CA</title></head>'
    '<body>'
    '<script>var playlist = [{{"file": "https://archive-stream.granicus.com/x/playlist.m3u8"}}];</script>'
    '{captions_tag}'
    '</body></html>'
)


async def test_resolve_falls_back_to_caption_file_when_no_transcript_fragments():
    html = BASE_HTML.format(
        captions_tag='<a href="https://example.new.swagit.com/captions.sbv">CC</a>'
    )
    sbv_content = "0:00:01.000,0:00:02.000\nHello there."

    routes = {
        PAGE_URL: FakeResponse(status=200, text=html, url=PAGE_URL),
        "https://example.new.swagit.com/captions.sbv": FakeResponse(status=200, text=sbv_content),
    }

    with mock_session(routes):
        result = await SwagitAssetFinder().resolve(PAGE_URL)

    assert result.video_url == "https://archive-stream.granicus.com/x/playlist.m3u8"
    assert [s.text for s in result.segments] == ["Hello there."]
    assert any("plain text" in w for w in result.transcript_warnings)


async def test_resolve_detects_language_from_transcript_fragments():
    # Real bug (2026-08-08): SwagitAssetFinder never called language
    # detection at all, so /meetings' "· en" listing indicator was always
    # blank even for a real Dublin CA meeting (clip 372020) with a genuine
    # 36k-segment English #transcript-fragments transcript -- see
    # BACKLOG_DONE.md. Synthetic here (real fixture is too large to check
    # in for this); pins that detect_language_from_texts actually gets
    # called and wired through to ResolvedMeeting.transcript_language.
    words = (
        "good evening and happy new year to everyone today is tuesday "
        "january thirteenth we will now call this regular meeting to "
        "order and begin with the pledge of allegiance to the flag"
    ).split()
    fragments = "".join(f'<a data-ts="{i}">{w}</a>' for i, w in enumerate(words))
    html = (
        '<html><head><title>Jan 13, 2026 City Council - Example, CA</title></head><body>'
        '<script>var playlist = [{"file": "https://archive-stream.granicus.com/x/playlist.m3u8"}];</script>'
        f'<div id="transcript-fragments">{fragments}</div>'
        '</body></html>'
    )

    routes = {PAGE_URL: FakeResponse(status=200, text=html, url=PAGE_URL)}

    with mock_session(routes):
        result = await SwagitAssetFinder().resolve(PAGE_URL)

    # Word-level fragments (one per second here) get grouped into
    # multi-word lines (see _group_word_fragments's own tests below) --
    # fewer segments than words, but every word still present somewhere.
    assert 0 < len(result.segments) < len(words)
    assert " ".join(s.text for s in result.segments).split() == words
    assert result.transcript_language == "en"


def test_group_word_fragments_merges_real_dublin_example():
    # Real bug (2026-08-08): Swagit's #transcript-fragments emits one
    # TranscriptSegment per word with start == end (a true instant) --
    # confirmed live on a real Dublin, CA meeting: "GOOD"/"EVENING"/
    # "AND"/"HAPPY"/"NEW"/"YEAR" each rendered as a separate clickable
    # line a fraction of a second apart. These are that meeting's real
    # timestamps (see BACKLOG.md), not synthetic.
    words = [
        TranscriptSegment(start=0.295, end=0.295, text="3, 2, 1."),
        TranscriptSegment(start=4.065, end=4.065, text="GOOD"),
        TranscriptSegment(start=4.355, end=4.355, text="EVENING"),
        TranscriptSegment(start=4.935, end=4.935, text="AND"),
        TranscriptSegment(start=5.155, end=5.155, text="HAPPY"),
        TranscriptSegment(start=5.535, end=5.535, text="NEW"),
        TranscriptSegment(start=5.755, end=5.755, text="YEAR"),
    ]
    grouped = _group_word_fragments(words, window_seconds=4.0)

    assert len(grouped) < len(words)
    assert " ".join(g.text for g in grouped) == "3, 2, 1. GOOD EVENING AND HAPPY NEW YEAR"
    # Each group's start is its first word's timestamp, not a later one.
    assert grouped[0].start == 0.295
    # Each group's end is its last word's timestamp, not start == end.
    assert grouped[-1].end == 5.755


def test_group_word_fragments_empty_input():
    assert _group_word_fragments([]) == []


def test_group_word_fragments_single_word():
    words = [TranscriptSegment(start=1.0, end=1.0, text="Hello")]
    grouped = _group_word_fragments(words)
    assert len(grouped) == 1
    assert grouped[0].text == "Hello"
    assert grouped[0].start == 1.0
    assert grouped[0].end == 1.0


def test_group_word_fragments_respects_window_boundary():
    # A gap larger than the window starts a new line even mid-otherwise-
    # continuous speech.
    words = [
        TranscriptSegment(start=0.0, end=0.0, text="one"),
        TranscriptSegment(start=1.0, end=1.0, text="two"),
        TranscriptSegment(start=10.0, end=10.0, text="three"),
    ]
    grouped = _group_word_fragments(words, window_seconds=4.0)
    assert [g.text for g in grouped] == ["one two", "three"]


async def test_resolve_no_caption_file_falls_through_to_no_transcript_warning():
    html = BASE_HTML.format(captions_tag="")

    routes = {PAGE_URL: FakeResponse(status=200, text=html, url=PAGE_URL)}

    with mock_session(routes):
        result = await SwagitAssetFinder().resolve(PAGE_URL)

    assert result.segments == []
    assert any("no transcript found" in w.lower() for w in result.transcript_warnings)
