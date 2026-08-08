from app.platforms.swagit import SwagitAssetFinder

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


async def test_resolve_no_caption_file_falls_through_to_no_transcript_warning():
    html = BASE_HTML.format(captions_tag="")

    routes = {PAGE_URL: FakeResponse(status=200, text=html, url=PAGE_URL)}

    with mock_session(routes):
        result = await SwagitAssetFinder().resolve(PAGE_URL)

    assert result.segments == []
    assert any("no transcript found" in w.lower() for w in result.transcript_warnings)
