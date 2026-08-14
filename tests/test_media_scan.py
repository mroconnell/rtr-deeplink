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


def test_scan_media_urls_finds_json_escaped_urls():
    # Real bug, confirmed live 2026-08-10 against Aurora, CO's auroratv.org
    # (found via the generic fallback adapter): a real playable .mp4 and a
    # real .vtt caption file were both genuinely on the page, but inside an
    # inline <script> JSON blob (a JW Player config) with every "/" written
    # as a JSON-escaped "\/" -- none of the plain https:// patterns matched
    # that literal backslash. Fixture mirrors the real shape (field names,
    # escaping) rather than a simplified stand-in.
    html = (
        '{"video_caption":"\\/home\\/atowntv\\/public_html\\/sites\\/default\\/files\\/'
        'video-captions-70037.vtt","jw_data":{"caption_file_path":"https:\\/\\/'
        'www.auroratv.org\\/sites\\/default\\/files\\/video-captions-70037.vtt",'
        '"mp4_url":"https:\\/\\/reflect-aurora.cablecast.tv\\/store-4\\/'
        '13040-EDITED-Regular-Meeting-of-v2\\/vod.mp4"}}'
    )
    urls = scan_media_urls(html, "https://www.auroratv.org/video/regular-meeting")
    assert "https://reflect-aurora.cablecast.tv/store-4/13040-EDITED-Regular-Meeting-of-v2/vod.mp4" in urls
    assert "https://www.auroratv.org/sites/default/files/video-captions-70037.vtt" in urls
    # The filesystem path (no scheme, backslash-escaped or not) must never
    # be picked up as if it were a fetchable URL.
    assert not any("/home/atowntv" in u for u in urls)


def test_scan_media_urls_does_not_pick_up_unrelated_xml_or_txt():
    html = (
        '<a href="https://city.example.com/sitemap.xml">sitemap</a>'
        '<a href="https://city.example.com/robots.txt">robots</a>'
    )
    urls = scan_media_urls(html, "https://city.example.com/page")
    assert urls == []


# --- 2026-08-14 rebuild coverage (Phase 1 of the generic-fallback rebuild;
# see BACKLOG_DONE.md). Every URL/shape below is a real one pulled from a
# real page capture in tests/fixtures/generic_fallback/, not invented. ---

SACRAMENTO_M3U8 = (
    "https://d2fdkm9wl77cjf.cloudfront.net/mcvod/mediacache/"
    "amlst:2vxN2KTTsz01k_deoRNbhu/playlist.m3u8?instance=1&token=abc123"
)


def test_media_type_classifies_m3u8_with_query_string_as_video():
    # THE confirmed root cause of Sacramento County's production "no video
    # found": the old check ran endswith(".m3u8") on the full URL, so a
    # query string made a real HLS playlist classify as "unknown".
    assert media_type(SACRAMENTO_M3U8) == "video"


def test_is_hls_url_ignores_query_string():
    from app.platforms.media_scan import is_hls_url

    assert is_hls_url(SACRAMENTO_M3U8)
    assert is_hls_url("https://x.gov/playlist.m3u8")
    assert not is_hls_url("https://x.gov/video.mp4?fmt=m3u8")


def test_scan_media_urls_decodes_html_entities_in_extracted_urls():
    # Real shape from the Sacramento capture: the raw HTML carries
    # `?instance=1&amp;token=...` -- without unescaping, the CDN receives a
    # literal `amp;token` parameter and the real token is lost.
    html = (
        '<script>jwplayer("player").setup({playlist: [{'
        'file: "https://d2fdkm9wl77cjf.cloudfront.net/mcvod/playlist.m3u8?instance=1&amp;token=xyz"'
        "}]});</script>"
    )
    urls = scan_media_urls(html, "https://agendanet.saccounty.gov/ViewMeeting?id=10231")
    assert urls == ["https://d2fdkm9wl77cjf.cloudfront.net/mcvod/playlist.m3u8?instance=1&token=xyz"]


def test_scan_media_urls_file_key_matches_protocol_relative_and_relative_paths():
    # Real shape from the Seattle Channel capture: JW `sources:` uses a
    # protocol-relative mp4 and `tracks:` a relative-path srt; urljoin must
    # resolve both against the page URL.
    html = (
        "playerInstance.setup({sources: [{"
        'file: "//video.seattle.gov/media/council/council_081126_2022663.mp4", label: "Auto"}],'
        'tracks: [{file: "documents/seattlechannel/closedcaption/2026/council_081126_2022663.srt",'
        ' label: "English"}]});'
    )
    urls = scan_media_urls(html, "https://www.seattlechannel.org/videos?videoid=x189286")
    assert "https://video.seattle.gov/media/council/council_081126_2022663.mp4" in urls
    assert (
        "https://www.seattlechannel.org/documents/seattlechannel/closedcaption/2026/"
        "council_081126_2022663.srt"
    ) in urls


def test_scan_media_urls_src_attribute_keeps_query_string():
    # The old src= pattern's terminator class ["'&] rejected any URL with a
    # query string outright.
    html = '<source src="//cdn.example.gov/v/meeting.m3u8?a=1&b=2">'
    urls = scan_media_urls(html, "https://example.gov/page")
    assert urls == ["https://cdn.example.gov/v/meeting.m3u8?a=1&b=2"]


def test_scan_media_urls_returns_document_order_deterministically():
    # Used to return list(set(...)) -- nondeterministic ordering that made
    # "first match wins" callers a per-run coin flip (real risk on OCFL's
    # 8-part meeting, whose parts must come back AA-first).
    html = (
        '<a href="https://otv.ocfl.net/otv/BCC071626AA.mp4">part 1</a>'
        '<a href="https://otv.ocfl.net/otv/BCC071626BB.mp4">part 2</a>'
        '<a href="https://otv.ocfl.net/otv/BCC071626AA.mp4">part 1 again</a>'
    )
    urls = scan_media_urls(html, "https://netapps.ocfl.net/Mod/meetings/1/2069")
    assert urls == [
        "https://otv.ocfl.net/otv/BCC071626AA.mp4",
        "https://otv.ocfl.net/otv/BCC071626BB.mp4",
    ]


def test_scan_media_urls_blocklist_is_segment_aware():
    # "silicon" contains "icon" -- the old substring blocklist dropped it.
    html = (
        '<video src="https://city.gov/media/silicon-valley-update.mp4"></video>'
        '<img src="https://city.gov/img/logo.mp4">'
    )
    urls = scan_media_urls(html, "https://city.gov/page")
    assert urls == ["https://city.gov/media/silicon-valley-update.mp4"]


def test_scan_media_urls_bare_url_stops_at_whitespace_and_markup():
    # The old quote-only termination let an unquoted URL swallow all
    # following text up to the next quote character.
    html = "Watch here: https://x.gov/a/playlist.m3u8 and then more text\n<p>stuff</p>"
    urls = scan_media_urls(html, "https://x.gov/page")
    assert urls == ["https://x.gov/a/playlist.m3u8"]
