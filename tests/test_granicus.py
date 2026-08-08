from app.platforms.granicus import GranicusAssetFinder

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture, load_fixture_bytes


async def test_resolve_real_blank_caption_meeting():
    # Real Napa City clip 3450 -- a genuinely blank captions.vtt (the
    # 8-byte "WEBVTT\n\n" placeholder Granicus serves whether or not a
    # meeting was ever captioned), fetched live 2026-08-07.
    url = "https://napacity.granicus.com/player/clip/3450"
    html = load_fixture("granicus", "napacity_clip3450.html")
    captions = load_fixture_bytes("granicus", "napacity_clip3450_captions.vtt")

    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        "https://napacity.granicus.com/videos/3450/captions.vtt":
            FakeResponse(status=200, raw=captions),
        "https://napacity.granicus.com/AgendaViewer.php?clip_id=3450&embedded=1":
            FakeResponse(status=404),
    }

    with mock_session(routes):
        result = await GranicusAssetFinder().resolve(url)

    assert result.platform == "granicus"
    assert result.external_id == "granicus:3450"
    assert result.title == "Bicycle and Pedestrian Advisory Commission"
    assert result.segments == []
    assert any("blank" in w.lower() for w in result.transcript_warnings)


async def test_resolve_falls_back_to_player_page_for_video_when_mediaplayer_has_none():
    # Real Fountain Valley CA clip 607 (user-reported 2026-08-08):
    # MediaPlayer.php's HTML embeds only a legacy Flash player object
    # (VideoUrl=...&stream_type=rtmp -- unplayable in any modern browser),
    # zero .m3u8/.mp4 anywhere in that page. The real, working HLS stream
    # only exists on Granicus's newer /videos/{id}/player page for the
    # same clip. Also incidentally the real sample CLAUDE.md already flags
    # for garbled/mislabeled captions -- real WEBVTT structure, but the
    # cue text itself is garbage at the source, and langdetect calls it
    # 'pt' on that noise. Both fixed together since they're the same
    # meeting: this pins the video fallback; the garbled/pt warnings
    # assertions guard against that separate, already-correct behavior
    # regressing silently.
    url = "https://fountainvalley.granicus.com/MediaPlayer.php?clip_id=607"
    html = load_fixture("granicus", "fountainvalley_clip607_mediaplayer.html")
    player_html = load_fixture("granicus", "fountainvalley_clip607_player.html")
    captions = load_fixture_bytes("granicus", "fountainvalley_clip607_captions.vtt")

    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        "https://fountainvalley.granicus.com/videos/607/captions.vtt":
            FakeResponse(status=200, raw=captions),
        "https://fountainvalley.granicus.com/videos/607/player":
            FakeResponse(status=200, text=player_html),
        "https://fountainvalley.granicus.com/AgendaViewer.php?clip_id=607&embedded=1":
            FakeResponse(status=404),
    }

    with mock_session(routes):
        result = await GranicusAssetFinder().resolve(url)

    assert result.video_url == (
        "https://archive-stream.granicus.com/OnDemand/_definst_/mp4:archive/"
        "fountainvalley/fountainvalley_237a7820-457b-404b-ad93-3eaaec3f0330.mp4/playlist.m3u8"
    )
    assert result.video_format == "m3u8"
    assert result.video_warnings == []
    assert len(result.segments) == 146
    assert result.transcript_language == "pt"
    assert any("garbled" in w.lower() for w in result.transcript_warnings)
    assert any("'pt'" in w for w in result.transcript_warnings)


async def test_resolve_real_meeting_with_spanish_captions():
    # Real Simi Valley clip 2840 -- the exact meeting BACKLOG_DONE.md
    # documents as real Spanish-language content mislabeled srclang="en"
    # on the page. Fetched live 2026-08-07.
    url = "https://simivalley.granicus.com/player/clip/2840"
    html = load_fixture("granicus", "simivalley_clip2840.html")
    captions = load_fixture_bytes("granicus", "simivalley_clip2840_captions.vtt")

    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        "https://simivalley.granicus.com/videos/2840/captions.vtt":
            FakeResponse(status=200, raw=captions),
        "https://simivalley.granicus.com/AgendaViewer.php?clip_id=2840&embedded=1":
            FakeResponse(status=404),
    }

    with mock_session(routes):
        result = await GranicusAssetFinder().resolve(url)

    assert result.external_id == "granicus:2840"
    assert result.date == "2023-12-18"
    assert len(result.segments) > 100
    # Real content is Spanish -- detected from actual text, not any page
    # label (this adapter's whole point per the Simi Valley finding).
    assert result.transcript_language == "es"
    assert any("es" in w for w in result.transcript_warnings)


async def test_resolve_no_video_or_captions_found():
    # A page whose URL doesn't match any of Granicus's recognized clip-id
    # shapes (/player/clip/, /videos/, ?clip_id=) -- so no clip id is
    # extracted, no captions.vtt path gets guessed, and (since agenda
    # fetching is itself gated on having a clip id) no AgendaViewer.php
    # call happens either. Exercises the genuine "nothing to find" path,
    # distinct from a guessed captions URL existing but 404ing/blank.
    url = "https://example.granicus.com/some/other/page"
    html = "<html><head><title>Empty Meeting</title></head><body>No media here.</body></html>"

    routes = {
        url: FakeResponse(status=200, text=html, url=url),
    }

    with mock_session(routes):
        result = await GranicusAssetFinder().resolve(url)

    assert result.external_id is None
    assert result.video_url is None
    assert any("no playable video" in w.lower() for w in result.video_warnings)
    assert any("no caption" in w.lower() for w in result.transcript_warnings)


async def test_resolve_guessed_captions_url_404s_treated_as_blank():
    # Different from the above: here a clip id *is* extractable, so a
    # captions.vtt path is guessed and requested per Granicus's own
    # heuristic -- but it 404s (as opposed to the real Napa case above,
    # where the guessed URL exists and returns the real empty-placeholder
    # body). Both end up bucketed as "blank" from the caller's point of
    # view, since `_fetch_vtt` returns None for either a non-200 status or
    # a genuinely empty track, and resolve() doesn't distinguish the two.
    url = "https://example.granicus.com/player/clip/999"
    html = "<html><head><title>Empty Meeting</title></head><body>No media here.</body></html>"

    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        "https://example.granicus.com/videos/999/captions.vtt": FakeResponse(status=404),
        "https://example.granicus.com/videos/999/player": FakeResponse(status=404),
        "https://example.granicus.com/AgendaViewer.php?clip_id=999&embedded=1": FakeResponse(status=404),
    }

    with mock_session(routes):
        result = await GranicusAssetFinder().resolve(url)

    assert result.segments == []
    assert any("blank" in w.lower() for w in result.transcript_warnings)


# --- New caption-format fallback paths (2026-08-08) --------------------
# Synthetic, not real: no Granicus meeting with a non-vtt/srt caption file
# has ever been observed. These exercise the fallback logic itself, not a
# real-world Granicus behavior -- see BACKLOG.md.

async def test_resolve_text_fallback_when_only_unstructured_caption_format_found():
    # A .sbv link embedded in the page (media_scan's wider detection) --
    # the guessed .vtt path 404s (Granicus's usual heuristic finds
    # nothing), so this SBV file is the only real caption source.
    url = "https://example.granicus.com/player/clip/42"
    html = (
        '<html><head><title>Council Meeting</title></head><body>'
        '<a href="https://example.granicus.com/captions.sbv">CC</a>'
        '</body></html>'
    )
    sbv_content = "0:00:01.000,0:00:02.000\nHello there.\n\n0:00:02.000,0:00:03.000\nSecond line."

    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        "https://example.granicus.com/videos/42/captions.vtt": FakeResponse(status=404),
        "https://example.granicus.com/videos/42/player": FakeResponse(status=404),
        "https://example.granicus.com/captions.sbv": FakeResponse(status=200, text=sbv_content),
        "https://example.granicus.com/AgendaViewer.php?clip_id=42&embedded=1": FakeResponse(status=404),
    }

    with mock_session(routes):
        result = await GranicusAssetFinder().resolve(url)

    assert [s.text for s in result.segments] == ["Hello there.", "Second line."]
    assert all(s.start == 0.0 and s.end == 0.0 for s in result.segments)
    assert any("plain text" in w for w in result.transcript_warnings)


async def test_resolve_links_out_when_caption_format_is_unreadable():
    # A .scc link (binary EIA-608) -- nothing can be extracted from it at
    # all, so this should surface as a direct link rather than silence.
    url = "https://example.granicus.com/player/clip/43"
    html = (
        '<html><head><title>Council Meeting</title></head><body>'
        '<a href="https://example.granicus.com/captions.scc">CC</a>'
        '</body></html>'
    )

    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        "https://example.granicus.com/videos/43/captions.vtt": FakeResponse(status=404),
        "https://example.granicus.com/videos/43/player": FakeResponse(status=404),
        "https://example.granicus.com/captions.scc":
            FakeResponse(status=200, text="Scenarist_SCC V1.0\n\n00:00:01:00 9420 9420"),
        "https://example.granicus.com/AgendaViewer.php?clip_id=43&embedded=1": FakeResponse(status=404),
    }

    with mock_session(routes):
        result = await GranicusAssetFinder().resolve(url)

    assert result.segments == []
    assert any(
        "can't read" in w and "captions.scc" in w for w in result.transcript_warnings
    )


def test_extract_clip_id_handles_all_url_shapes():
    extract = GranicusAssetFinder._extract_clip_id
    assert extract("https://city.granicus.com/player/clip/1234") == "1234"
    assert extract("https://city.granicus.com/player/clip/1234?view_id=2") == "1234"
    assert extract("https://city.granicus.com/videos/5361/") == "5361"
    assert extract("https://city.granicus.com/MediaPlayer.php?clip_id=789&view_id=1") == "789"
    assert extract("https://city.granicus.com/AboutUs.php") is None
