from app.platforms.ca_legislature import CaliforniaLegislatureAssetFinder

from aiohttp_mock import FakeResponse, mock_session

# No fixture-based tests existed for this adapter before this file (see
# BACKLOG_DONE.md's "Not yet covered" note) -- scoped here to just the new
# caption-format-fallback logic added alongside Granicus/CivicClerk/Swagit,
# not full adapter coverage. Synthetic HTML matching the real page shapes
# documented in ca_legislature.py's own docstrings (Senate's combined
# "Title, Weekday, Month D, YYYY" <h2>), not a live-fetched fixture.

PAGE_URL = "https://www.senate.ca.gov/media/9999"

BASE_HTML = (
    '<html><body>'
    '<h1>Media on Demand</h1>'
    '<h2>Joint Hearing on Housing, Monday, August 3, 2026</h2>'
    '<video src="https://stream.senate.ca.gov/vod/_definst_/mp4:x/playlist.m3u8"></video>'
    '{captions_tag}'
    '</body></html>'
)


async def test_resolve_text_fallback_when_caption_format_is_unstructured():
    html = BASE_HTML.format(
        captions_tag='<track src="https://vod.senate.ca.gov/captions.sbv">'
    )
    sbv_content = "0:00:01.000,0:00:02.000\nHello there."

    routes = {
        PAGE_URL: FakeResponse(status=200, text=html, url=PAGE_URL),
        "https://vod.senate.ca.gov/captions.sbv": FakeResponse(status=200, text=sbv_content),
    }

    with mock_session(routes):
        result = await CaliforniaLegislatureAssetFinder().resolve(PAGE_URL)

    assert result.title == "Joint Hearing on Housing"
    assert result.date == "2026-08-03"
    assert [s.text for s in result.segments] == ["Hello there."]
    assert any("plain text" in w for w in result.transcript_warnings)


async def test_resolve_links_out_when_caption_format_is_unreadable():
    html = BASE_HTML.format(
        captions_tag='<track src="https://vod.senate.ca.gov/captions.scc">'
    )

    routes = {
        PAGE_URL: FakeResponse(status=200, text=html, url=PAGE_URL),
        "https://vod.senate.ca.gov/captions.scc":
            FakeResponse(status=200, text="Scenarist_SCC V1.0\n\n00:00:01:00 9420"),
    }

    with mock_session(routes):
        result = await CaliforniaLegislatureAssetFinder().resolve(PAGE_URL)

    assert result.segments == []
    assert any("can't read" in w and "captions.scc" in w for w in result.transcript_warnings)


async def test_resolve_detects_language_from_real_captions():
    # Real bug (2026-08-08): CaliforniaLegislatureAssetFinder never called
    # language detection at all, so /meetings' "· en" listing indicator
    # was always blank even for a real Senate floor session (2026-08-06)
    # with a genuine 3,084-cue English transcript -- see BACKLOG_DONE.md.
    vtt = (
        "WEBVTT\n\n"
        "00:00:32.000 --> 00:00:34.000\nSecretary will call the roll.\n\n"
        "00:01:11.000 --> 00:01:14.000\nA quorum is present with the members and our guests.\n\n"
        "00:01:16.000 --> 00:01:19.000\nPlease rise for the pledge of allegiance to the flag.\n"
    )
    html = BASE_HTML.format(
        captions_tag='<track src="https://vod.senate.ca.gov/captions.vtt">'
    )

    routes = {
        PAGE_URL: FakeResponse(status=200, text=html, url=PAGE_URL),
        "https://vod.senate.ca.gov/captions.vtt": FakeResponse(status=200, text=vtt),
    }

    with mock_session(routes):
        result = await CaliforniaLegislatureAssetFinder().resolve(PAGE_URL)

    assert len(result.segments) == 3
    assert result.transcript_language == "en"


async def test_resolve_excludes_thumbnail_sprite_vtt_even_with_wider_detection():
    # Real trap documented in the class docstring: a masterVTT.vtt under
    # /thumbnails/ is a scrubber sprite sheet, not a transcript -- must
    # stay excluded regardless of the wider extension list.
    html = BASE_HTML.format(
        captions_tag='<track src="https://vod.senate.ca.gov/thumbnails/masterVTT.vtt">'
    )

    routes = {
        PAGE_URL: FakeResponse(status=200, text=html, url=PAGE_URL),
    }

    with mock_session(routes):
        result = await CaliforniaLegislatureAssetFinder().resolve(PAGE_URL)

    assert result.segments == []
    assert any("no caption file found" in w.lower() for w in result.transcript_warnings)
