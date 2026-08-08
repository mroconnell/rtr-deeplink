from app.platforms.media_scan import media_type, scan_media_urls


def test_scan_media_urls_finds_m3u8():
    html = '<video src="https://city.granicus.com/vidcache/abc.m3u8"></video>'
    urls = scan_media_urls(html, "https://city.granicus.com/player/clip/1")
    assert "https://city.granicus.com/vidcache/abc.m3u8" in urls


def test_scan_media_urls_resolves_relative_paths():
    html = '<track src="/videos/5361/captions.vtt">'
    urls = scan_media_urls(html, "https://berkeley.granicus.com/player/clip/5361")
    assert "https://berkeley.granicus.com/videos/5361/captions.vtt" in urls


def test_scan_media_urls_skips_placeholder_and_logo_assets():
    html = (
        '<img src="https://city.granicus.com/img/logo.png">'
        '<video poster="https://city.granicus.com/img/placeholder.mp4">'
    )
    urls = scan_media_urls(html, "https://city.granicus.com/player/clip/1")
    assert urls == []


def test_scan_media_urls_sources_json_branch_was_removed_as_dead_code():
    # The `"sources"` JSON-blob regex this test used to pin down was
    # confirmed dead (see BACKLOG_DONE.md): `[^}]*\]` couldn't span past a
    # nested object's closing `}`, so it never matched any real JWPlayer-
    # style config, and every adapter that calls this function (Granicus,
    # Swagit) already gets its real media URLs from the plain regex
    # patterns tried first -- confirmed live in both adapters' own testing.
    # Deleted rather than fixed: writing a "working" JSON-aware version
    # would still be unverified against any real page, which is exactly
    # the kind of unverified parsing path this project avoids shipping.
    # This input correctly still yields no URLs post-removal, since it was
    # never something the plain regex patterns matched either (no bare
    # `src="..."` attribute, and the JSON value is a scheme-less relative
    # path, not a `https?://...` URL).
    html = (
        'var config = {"sources": [{"src": "/vid/main.mp4", "type": "video/mp4"}]};'
    )
    urls = scan_media_urls(html, "https://example.com/page")
    assert urls == []


def test_media_type_classifies_video_audio_subtitle():
    assert media_type("https://x.com/a.m3u8") == "video"
    assert media_type("https://x.com/a.mp4") == "video"
    assert media_type("https://x.com/a.mp3") == "audio"
    assert media_type("https://x.com/a.vtt") == "subtitle"
    assert media_type("https://x.com/a.srt") == "subtitle"
    assert media_type("https://x.com/a.png") == "unknown"


def test_media_type_classifies_newly_recognized_caption_formats():
    for ext in ("ttml", "dfxp", "itt", "scc", "stl", "sbv", "sub", "smi", "sami"):
        assert media_type(f"https://x.com/a.{ext}") == "subtitle", ext


def test_media_type_gates_xml_and_txt_on_caption_related_path():
    assert media_type("https://x.com/ClosedCaption/07222026-585.srt") == "subtitle"
    assert media_type("https://x.com/captions/foo.xml") == "subtitle"
    assert media_type("https://x.com/transcript.txt") == "subtitle"
    assert media_type("https://x.com/cc_track.xml") == "subtitle"
    # Not caption-related -- must NOT be swept up just for having a .xml/.txt
    # extension (sitemaps, robots.txt-style files, analytics config, etc.).
    assert media_type("https://x.com/sitemap.xml") == "unknown"
    assert media_type("https://x.com/analytics.txt") == "unknown"


def test_scan_media_urls_detects_wider_caption_formats():
    html = (
        '<track src="https://city.example.com/captions.ttml">'
        '<a href="https://city.example.com/subtitles.dfxp">DFXP</a>'
        '<a href="https://city.example.com/ClosedCaption/07222026-585.srt">CC</a>'
        '<a href="https://city.example.com/captions.scc">SCC</a>'
        '<a href="https://city.example.com/transcript.txt">Transcript</a>'
    )
    urls = scan_media_urls(html, "https://city.example.com/page")
    assert "https://city.example.com/captions.ttml" in urls
    assert "https://city.example.com/subtitles.dfxp" in urls
    assert "https://city.example.com/ClosedCaption/07222026-585.srt" in urls
    assert "https://city.example.com/captions.scc" in urls
    assert "https://city.example.com/transcript.txt" in urls


def test_scan_media_urls_does_not_pick_up_unrelated_xml_or_txt():
    html = (
        '<a href="https://city.example.com/sitemap.xml">sitemap</a>'
        '<a href="https://city.example.com/robots.txt">robots</a>'
    )
    urls = scan_media_urls(html, "https://city.example.com/page")
    assert urls == []
