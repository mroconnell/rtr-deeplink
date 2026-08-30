from bs4 import BeautifulSoup

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
        "https://napacity.granicus.com/videos/3450/captions.vtt": FakeResponse(
            status=200, raw=captions
        ),
        "https://napacity.granicus.com/AgendaViewer.php?clip_id=3450&embedded=1": FakeResponse(
            status=404
        ),
    }

    with mock_session(routes):
        result = await GranicusAssetFinder().resolve(url)

    assert result.platform == "granicus"
    assert result.external_id == "granicus:napacity.granicus.com:3450"
    assert result.title == "Bicycle and Pedestrian Advisory Commission"
    assert result.segments == []
    assert any("blank" in w.lower() for w in result.transcript_warnings)


async def test_resolve_event_id_meeting_reports_honest_no_video_status():
    # Real Calabasas CA event_id=1525 (fetched live 2026-08-21, both via
    # plain HTTP and a rendered-browser check). Found via BACKLOG.md's
    # Granicus event_id entry: PrimeGov's own video delegation correctly
    # discovers and passes through this URL shape (MediaPlayer.php?
    # event_id=..., the fourth known Granicus URL shape, distinct from
    # clip_id-based ones) for a meeting whose PrimeGov API record shows
    # streamCompleted=False and mediaManagerClipPubliclyAvailable=False --
    # confirmed by fetching the real post-redirect /player/event/{id}
    # page directly: no video-player library loads at all, no video
    # element or media URL anywhere on the page, only Granicus's own
    # real, static `<div id="player-error">` reading "The event you
    # selected is not currently in progress." This meeting genuinely has
    # no video yet, not merely one this scanner failed to find, so the
    # fix here is an honest, specific "no video" result rather than a
    # guessed video URL.
    url = "https://calabasas.granicus.com/MediaPlayer.php?event_id=1525"
    html = load_fixture("granicus", "calabasas_event1525.html")

    routes = {
        url: FakeResponse(status=200, text=html, url=url),
    }

    with mock_session(routes):
        result = await GranicusAssetFinder().resolve(url)

    assert result.title == "City Council Regular Meeting"
    assert result.jurisdiction == "City of Calabasas, CA"
    # "event:" infix keeps this permanently distinct from a real
    # clip_id-based external_id (always a bare number after the netloc) --
    # event_id and clip_id are separate number spaces on the same tenant.
    assert result.external_id == "granicus:calabasas.granicus.com:event:1525"
    assert result.video_url is None
    assert result.video_format is None
    assert result.video_warnings == [
        "The event you selected is not currently in progress."
    ]
    # No clip_id means every clip_id-dependent path (agenda items,
    # minutes-date fallback, video-player-page fallback) is correctly
    # skipped rather than firing against a wrong/coincidentally-colliding
    # number -- implicitly proven here too, since `routes` above mocks
    # only the one request and mock_session raises AssertionError on any
    # other request the code might have (wrongly) made.
    assert result.agenda_items == []
    assert result.agenda_link is None


async def test_resolve_humanizes_valid_city_subdomain_when_no_page_text_jurisdiction(
    caplog,
):
    # No "City/County of X" text anywhere on the page (unlike the Napa
    # fixture reused elsewhere in this file) -- forces the subdomain
    # fallback. "fresno" is a real, unambiguous Census place, so this
    # should still resolve correctly via
    # jurisdiction_enrich.validated_subdomain_extract().
    url = "https://fresno.granicus.com/player/clip/99"
    html = "<html><head><title>Meeting</title></head><body>No jurisdiction text here.</body></html>"

    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        "https://fresno.granicus.com/videos/99/captions.vtt": FakeResponse(status=404),
        "https://fresno.granicus.com/videos/99/player": FakeResponse(status=404),
        "https://fresno.granicus.com/AgendaViewer.php?clip_id=99&embedded=1": FakeResponse(
            status=404
        ),
    }

    with caplog.at_level("WARNING"):
        with mock_session(routes):
            result = await GranicusAssetFinder().resolve(url)

    assert result.jurisdiction == "Fresno, CA"
    # 2026-08-28: a failed agenda fetch used to be silent -- now logged.
    assert any("agenda fetch got HTTP 404" in r.message for r in caplog.records)


async def test_resolve_declines_subdomain_humanization_for_unvalidated_acronym():
    # Real bug found live 2026-08-15: the old bare wordninja-always-guess
    # turned "sfwmd" (South Florida Water Management District) into
    # "S Fw, MD" -- its trailing "md" misread as a Maryland state suffix.
    # "sfwmd" doesn't validate against the Census place/county tables (it's
    # an agency name, not a place), so this should now decline rather than
    # guess, leaving jurisdiction at the generic placeholder.
    url = "https://sfwmd.granicus.com/player/clip/99"
    html = "<html><head><title>Meeting</title></head><body>No jurisdiction text here.</body></html>"

    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        "https://sfwmd.granicus.com/videos/99/captions.vtt": FakeResponse(status=404),
        "https://sfwmd.granicus.com/videos/99/player": FakeResponse(status=404),
        "https://sfwmd.granicus.com/AgendaViewer.php?clip_id=99&embedded=1": FakeResponse(
            status=404
        ),
    }

    with mock_session(routes):
        result = await GranicusAssetFinder().resolve(url)

    assert result.jurisdiction == "Unknown Jurisdiction"


async def test_resolve_flags_exactly_36000_cues_as_possibly_cut_off():
    # Granicus's own captions.vtt appears to hard-cap at exactly 36,000
    # cues on very long meetings, cutting off mid-sentence with no
    # warning of its own -- confirmed live 2026-08-15 on 3 independent
    # real customers (College Park GA, Coral Gables FL, Marion County
    # FL), see BACKLOG.md. Synthetic VTT here (36,000 real cues would be
    # an unwieldy fixture), reusing the real Napa clip 3450 page shape.
    url = "https://napacity.granicus.com/player/clip/3450"
    html = load_fixture("granicus", "napacity_clip3450.html")
    lines = ["WEBVTT", ""]
    for i in range(36000):
        start_s, end_s = i, i + 1
        start = (
            f"{start_s // 3600:02d}:{(start_s % 3600) // 60:02d}:{start_s % 60:02d}.000"
        )
        end = f"{end_s // 3600:02d}:{(end_s % 3600) // 60:02d}:{end_s % 60:02d}.000"
        lines.append(f"{start} --> {end}")
        lines.append(f"cue {i}")
        lines.append("")
    captions = "\n".join(lines).encode("utf-8")

    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        "https://napacity.granicus.com/videos/3450/captions.vtt": FakeResponse(
            status=200, raw=captions
        ),
        "https://napacity.granicus.com/AgendaViewer.php?clip_id=3450&embedded=1": FakeResponse(
            status=404
        ),
    }

    with mock_session(routes):
        result = await GranicusAssetFinder().resolve(url)

    assert len(result.segments) == 36000
    assert any("36,000" in w for w in result.transcript_warnings)


async def test_agenda_viewer_redirect_to_raw_pdf_surfaces_as_fallback_link():
    # Real Napa City Council clip 3470 (view_id=12), fetched live
    # 2026-08-11 -- AgendaViewer.php redirects straight to a *raw* binary
    # PDF (unlike Berkeley's HTML redirect or Paradise Valley AZ's Google
    # Docs PDF *preview*, both still text-decodable). Real aiohttp raises
    # UnicodeDecodeError from response.text() in this case; previously
    # that was caught by the surrounding blanket `except Exception` and
    # silently discarded the fallback URL along with it instead of
    # putting it in `ResolvedMeeting.agenda_link` (the same structured
    # field generic_fallback.py's own best-effort agenda link uses).
    url = "https://napacity.granicus.com/player/clip/3470?view_id=12"
    html = load_fixture("granicus", "napacity_clip3450.html").replace("3450", "3470")
    pdf_url = (
        "https://napacity.legistar1.com/napacity/meetings/2026/8/"
        "2042_A_CITY_COUNCIL_OF_THE_CITY_OF_NAPA_26-08-04_Regular_Meeting_Agenda.pdf"
    )

    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        "https://napacity.granicus.com/videos/3470/captions.vtt": FakeResponse(
            status=404
        ),
        "https://napacity.granicus.com/AgendaViewer.php?clip_id=3470&embedded=1": FakeResponse(
            status=200,
            url=pdf_url,
            text_raises=UnicodeDecodeError(
                "utf-8", b"\xe2", 0, 1, "invalid continuation byte"
            ),
        ),
    }

    with mock_session(routes):
        result = await GranicusAssetFinder().resolve(url)

    assert result.agenda_items == []
    assert result.agenda_link == pdf_url


async def test_resolve_falls_back_to_docket_pdf_date_when_page_and_rss_have_none():
    # Real Alexandria, VA clip 6490, fetched live 2026-08-09 -- a thin
    # client-rendered shell with no og:title, no h1, under 700 chars of
    # visible body text, and no view_id (so no RSS date either). The only
    # real date signal on the whole page is inside a data-url="...pdf"
    # attribute pointing at a Legistar-style docket filename
    # ("..._25-04-02_Docket.pdf") -- confirmed this is what
    # BACKLOG.md's long-standing "Alexandria VA meeting dates can't be
    # extracted" gap was actually missing, not a genuinely dateless page.
    url = "https://alexandria.granicus.com/player/clip/6490"
    html = load_fixture("granicus", "alexandria_clip6490.html")

    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        "https://alexandria.granicus.com/videos/6490/captions.vtt": FakeResponse(
            status=404
        ),
        "https://alexandria.granicus.com/AgendaViewer.php?clip_id=6490&embedded=1": FakeResponse(
            status=404
        ),
    }

    with mock_session(routes):
        result = await GranicusAssetFinder().resolve(url)

    assert result.date == "2025-04-02"
    assert result.jurisdiction == "City of Alexandria, VA"


async def test_resolve_fills_in_state_for_a_real_unambiguous_city():
    # End-to-end: the existing napacity fixture's own body text produces
    # "City of Napa" with no state today -- confirms the enrichment step
    # is actually wired into resolve(), not just unit-tested in isolation.
    url = "https://napacity.granicus.com/player/clip/3450"
    html = load_fixture("granicus", "napacity_clip3450.html")
    captions = load_fixture_bytes("granicus", "napacity_clip3450_captions.vtt")

    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        "https://napacity.granicus.com/videos/3450/captions.vtt": FakeResponse(
            status=200, raw=captions
        ),
        "https://napacity.granicus.com/AgendaViewer.php?clip_id=3450&embedded=1": FakeResponse(
            status=404
        ),
    }

    with mock_session(routes):
        result = await GranicusAssetFinder().resolve(url)

    assert result.jurisdiction == "City of Napa, CA"


def test_extract_date_from_document_links_direct():
    from bs4 import BeautifulSoup

    html = (
        '<a data-url="https://legistar.granicus.com/alexandria/meetings/2025/4/'
        '2616_A_Board_of_Architectural_Review_25-04-02_Docket.pdf">Agenda</a>'
    )
    soup = BeautifulSoup(html, "html.parser")
    assert GranicusAssetFinder._extract_date_from_document_links(soup) == "2025-04-02"


def test_extract_date_from_document_links_returns_none_when_no_match():
    from bs4 import BeautifulSoup

    html = '<a data-url="https://example.com/some-file-with-no-date.pdf">Agenda</a>'
    soup = BeautifulSoup(html, "html.parser")
    assert GranicusAssetFinder._extract_date_from_document_links(soup) is None


async def test_resolve_falls_back_to_player_page_for_video_when_mediaplayer_has_none():
    # Real Fountain Valley CA clip 607 (user-reported 2026-08-08):
    # MediaPlayer.php's HTML embeds only a legacy Flash player object
    # (VideoUrl=...&stream_type=rtmp -- unplayable in any modern browser),
    # zero .m3u8/.mp4 anywhere in that page. The real, working HLS stream
    # only exists on Granicus's newer /videos/{id}/player page for the
    # same clip. Also incidentally the real sample CLAUDE.md already flags
    # for garbled/mislabeled captions -- real WEBVTT structure, but the
    # cue text itself is garbage at the source. Both fixed together since
    # they're the same meeting: this pins the video fallback; the garbled
    # warning assertion guards that separate, already-correct behavior
    # against regressing silently.
    #
    # DELIBERATE ASSERTION CHANGE (WO-34, 2026-08-21): this used to assert
    # transcript_language == "pt" plus a "captions appear to be in 'pt'"
    # warning. That was langdetect's answer to the *first 2000 characters*
    # of this noise, and detect_language_from_texts() no longer works that
    # way -- it votes over the whole transcript, which on this file splits
    # pt 3742 / en 4452 / sl 2504 chars and lands on 'en'. Not a regression
    # being papered over: Fountain Valley CA is an English-language council,
    # so 'pt' was simply wrong, and dropping the language-mismatch warning
    # for a meeting whose only real problem is garbled captions is the
    # better user-facing outcome. The label on pure noise is meaningless
    # either way; what this test should pin is that the garbled warning
    # still fires, which it does.
    url = "https://fountainvalley.granicus.com/MediaPlayer.php?clip_id=607"
    html = load_fixture("granicus", "fountainvalley_clip607_mediaplayer.html")
    player_html = load_fixture("granicus", "fountainvalley_clip607_player.html")
    captions = load_fixture_bytes("granicus", "fountainvalley_clip607_captions.vtt")

    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        "https://fountainvalley.granicus.com/videos/607/captions.vtt": FakeResponse(
            status=200, raw=captions
        ),
        "https://fountainvalley.granicus.com/videos/607/player": FakeResponse(
            status=200, text=player_html
        ),
        "https://fountainvalley.granicus.com/AgendaViewer.php?clip_id=607&embedded=1": FakeResponse(
            status=404
        ),
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
    assert result.transcript_language == "en"
    assert any("garbled" in w.lower() for w in result.transcript_warnings)
    assert not any("appear to be in" in w for w in result.transcript_warnings)


async def test_resolve_real_meeting_with_spanish_captions():
    # Real Simi Valley clip 2840 -- the exact meeting BACKLOG_DONE.md
    # documents as real Spanish-language content mislabeled srclang="en"
    # on the page. Fetched live 2026-08-07.
    url = "https://simivalley.granicus.com/player/clip/2840"
    html = load_fixture("granicus", "simivalley_clip2840.html")
    captions = load_fixture_bytes("granicus", "simivalley_clip2840_captions.vtt")

    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        "https://simivalley.granicus.com/videos/2840/captions.vtt": FakeResponse(
            status=200, raw=captions
        ),
        "https://simivalley.granicus.com/AgendaViewer.php?clip_id=2840&embedded=1": FakeResponse(
            status=404
        ),
    }

    with mock_session(routes):
        result = await GranicusAssetFinder().resolve(url)

    assert result.external_id == "granicus:simivalley.granicus.com:2840"
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
        "https://example.granicus.com/videos/999/captions.vtt": FakeResponse(
            status=404
        ),
        "https://example.granicus.com/videos/999/player": FakeResponse(status=404),
        "https://example.granicus.com/AgendaViewer.php?clip_id=999&embedded=1": FakeResponse(
            status=404
        ),
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
        "<html><head><title>Council Meeting</title></head><body>"
        '<a href="https://example.granicus.com/captions.sbv">CC</a>'
        "</body></html>"
    )
    sbv_content = (
        "0:00:01.000,0:00:02.000\nHello there.\n\n0:00:02.000,0:00:03.000\nSecond line."
    )

    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        "https://example.granicus.com/videos/42/captions.vtt": FakeResponse(status=404),
        "https://example.granicus.com/videos/42/player": FakeResponse(status=404),
        "https://example.granicus.com/captions.sbv": FakeResponse(
            status=200, text=sbv_content
        ),
        "https://example.granicus.com/AgendaViewer.php?clip_id=42&embedded=1": FakeResponse(
            status=404
        ),
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
        "<html><head><title>Council Meeting</title></head><body>"
        '<a href="https://example.granicus.com/captions.scc">CC</a>'
        "</body></html>"
    )

    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        "https://example.granicus.com/videos/43/captions.vtt": FakeResponse(status=404),
        "https://example.granicus.com/videos/43/player": FakeResponse(status=404),
        "https://example.granicus.com/captions.scc": FakeResponse(
            status=200, text="Scenarist_SCC V1.0\n\n00:00:01:00 9420 9420"
        ),
        "https://example.granicus.com/AgendaViewer.php?clip_id=43&embedded=1": FakeResponse(
            status=404
        ),
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
    assert (
        extract("https://city.granicus.com/MediaPlayer.php?clip_id=789&view_id=1")
        == "789"
    )
    assert extract("https://city.granicus.com/AboutUs.php") is None


def test_extract_clip_id_never_matches_event_id_shape():
    # Real bug this guards against: event_id and clip_id are separate,
    # non-interchangeable number spaces on the same Granicus tenant (see
    # _extract_event_id's docstring) -- _extract_clip_id must never
    # accidentally match the event_id shape and hand back a number that
    # could coincidentally collide with an unrelated real clip.
    extract = GranicusAssetFinder._extract_clip_id
    assert (
        extract("https://calabasas.granicus.com/MediaPlayer.php?event_id=1525") is None
    )
    assert extract("https://calabasas.granicus.com/player/event/1525") is None
    assert (
        extract("https://calabasas.granicus.com/player/event/1525?redirect=true")
        is None
    )


def test_extract_event_id_handles_query_and_path_shapes():
    # Real URLs confirmed live 2026-08-21 across 4 cities discovered via
    # PrimeGov's own video delegation: the query shape is what PrimeGov's
    # ListArchivedMeetings API hands back as `videoUrl`, and it
    # 302-redirects to the path shape (see _fetch_page's docstring for
    # why callers must use the post-redirect final_url).
    extract = GranicusAssetFinder._extract_event_id
    assert (
        extract("https://calabasas.granicus.com/MediaPlayer.php?event_id=1525")
        == "1525"
    )
    assert (
        extract("https://calabasas.granicus.com/player/event/1525?redirect=true")
        == "1525"
    )
    assert (
        extract("https://elkgrove.granicus.com/MediaPlayer.php?event_id=2583") == "2583"
    )
    assert (
        extract("https://emeryville.granicus.com/MediaPlayer.php?event_id=1108")
        == "1108"
    )
    assert (
        extract("https://nassaufl.granicus.com/MediaPlayer.php?event_id=2741") == "2741"
    )
    assert extract("https://city.granicus.com/AboutUs.php") is None
    # Never matches a real clip_id URL, symmetric with the guard above.
    assert extract("https://city.granicus.com/player/clip/1234") is None


def test_extract_metadata_ignores_previous_meeting_date_reference():
    # Real bug confirmed live 2026-08-10: Memphis, TN clip 9789. The
    # page's own body text has no date for *this* meeting anywhere, but
    # does have "V. APPROVAL OF PREVIOUS MEETING MINUTES (December 5,
    # 2023)" -- a standard agenda item referencing the *prior* meeting's
    # date. Body-text date parsing previously grabbed that as if it were
    # this meeting's own date -- wrong by 14 days (the real date was
    # December 19, 2023, confirmed by the user directly; it isn't present
    # anywhere in this page's own text at all, so the fix here is an
    # honest missing date, not a different guess).
    html = (
        "<html><body><h1>City Council Full Meeting</h1>"
        "<div>V. APPROVAL OF PREVIOUS MEETING MINUTES (December 5, 2023)</div>"
        "</body></html>"
    )
    soup = BeautifulSoup(html, "html.parser")
    metadata = GranicusAssetFinder()._extract_metadata(
        soup, "https://memphis.granicus.com/player/clip/9789", html
    )
    assert metadata["date"] is None


def test_extract_metadata_still_finds_a_real_date_elsewhere_on_the_page():
    # Confirms the previous-meeting exclusion doesn't just blanket-suppress
    # every date on the page -- a real, unrelated date elsewhere should
    # still be found normally.
    html = (
        "<html><body><h1>City Council Full Meeting</h1>"
        "<div>V. APPROVAL OF PREVIOUS MEETING MINUTES (December 5, 2023)</div>"
        "<div>Meeting held on December 19, 2023</div>"
        "</body></html>"
    )
    soup = BeautifulSoup(html, "html.parser")
    metadata = GranicusAssetFinder()._extract_metadata(
        soup, "https://memphis.granicus.com/player/clip/9789", html
    )
    assert metadata["date"] == "2023-12-19"


async def test_resolve_finds_date_from_minutes_viewer_when_nothing_else_has_one():
    # Real gap confirmed live 2026-08-10: Memphis, TN clip 10031 ("Parks &
    # Environment") has no date anywhere on the page itself and none in
    # the RSS feed either, but Granicus's own published Minutes document
    # (MinutesViewer.php) -- a real, plain HTTP-fetchable page, no
    # headless browser needed -- has the real date right at the top:
    # "MINUTES / COUNCIL COMMITTEE MEETING / CITY OF MEMPHIS / July 23,
    # 2024".
    url = "https://memphis.granicus.com/player/clip/10031?view_id=6&redirect=true"
    html = load_fixture("granicus", "napacity_clip3450.html").replace(
        "Bicycle and Pedestrian Advisory Commission", "Parks & Environment"
    )
    minutes_url = "https://memphis.granicus.com/MinutesViewer.php?clip_id=10031&view_id=6&embedded=1"
    minutes_html = (
        "<html><body>MINUTES COUNCIL COMMITTEE MEETING CITY OF MEMPHIS July 23, 2024 "
        "ROLLCALL: Easter-Thomas, Ford</body></html>"
    )

    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        minutes_url: FakeResponse(status=200, text=minutes_html, url=minutes_url),
        "https://memphis.granicus.com/videos/10031/captions.vtt": FakeResponse(
            status=404
        ),
        "https://memphis.granicus.com/AgendaViewer.php?clip_id=10031&embedded=1": FakeResponse(
            status=404
        ),
    }

    with mock_session(routes):
        result = await GranicusAssetFinder().resolve(url)

    assert result.date == "2024-07-23"


async def test_resolve_minutes_viewer_redirect_treated_as_no_minutes_not_crash():
    # Real case confirmed live 2026-08-10: a different real Memphis clip
    # (9789) with no published minutes -- MinutesViewer.php 302-redirects
    # to a raw scanned PDF (binary content) rather than 404ing.
    # allow_redirects=False means this comes back as a 302 to the mock,
    # never actually fetching or trying to parse the PDF as HTML.
    url = "https://memphis.granicus.com/player/clip/9789?view_id=6&redirect=true"
    html = load_fixture("granicus", "napacity_clip3450.html").replace(
        "Bicycle and Pedestrian Advisory Commission", "City Council Full Meeting"
    )
    minutes_url = "https://memphis.granicus.com/MinutesViewer.php?clip_id=9789&view_id=6&embedded=1"

    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        minutes_url: FakeResponse(status=302, text="", url=minutes_url),
        "https://memphis.granicus.com/videos/9789/captions.vtt": FakeResponse(
            status=404
        ),
        "https://memphis.granicus.com/AgendaViewer.php?clip_id=9789&embedded=1": FakeResponse(
            status=404
        ),
    }

    with mock_session(routes):
        result = await GranicusAssetFinder().resolve(url)

    assert result.date is None


def test_extract_metadata_jurisdiction_no_longer_bleeds_into_agenda_text_hercules():
    # WO-14 (BACKLOG.md, 2026-08-16): real fixture, fetched live 2026-08-16
    # from hercules.granicus.com/player/clip/1306. The old bare
    # `re.search(r"\b(City|County|Town) of ([A-Z][A-Za-z .]{1,40})", ...)`
    # produced 'City of Hercules. XIV. PUBLIC COMMUNICATIONS XV. ' character
    # for character on this exact page (re-confirmed against the live fetch
    # before this fix landed) -- no sentence/tag boundary, so it just kept
    # consuming letters/spaces/periods once "City of" matched.
    # extract_jurisdiction_chain() fixes this via its bounded stop-rule
    # extractor, validated against the Census tables.
    html = load_fixture("granicus", "hercules_clip1306.html")
    soup = BeautifulSoup(html, "html.parser")
    metadata = GranicusAssetFinder()._extract_metadata(
        soup, "https://hercules.granicus.com/player/clip/1306", html
    )
    assert metadata["jurisdiction"] == "City of Hercules, CA"


def test_extract_metadata_jurisdiction_bleed_regressions_text_only():
    # WO-14 (BACKLOG.md, 2026-08-16): synthetic page-text reconstructions
    # around 5 of the 9 confirmed-real bled substrings BACKLOG.md quotes
    # (Huntsville/Boston/Fort Worth/Edgewater/Milwaukee, all found live
    # 2026-08-15) -- the surrounding filler text is invented since the full
    # original page text wasn't captured at the time, but the bled fragment
    # itself and the correct city are real, confirmed values, not guesses.
    # A deliberately unrelated subdomain (not the city's own) isolates the
    # fix to extract_jurisdiction_chain()'s text-based tiers alone -- these
    # 5 resolve correctly on text alone, with no help from the subdomain
    # fallback below.
    cases = [
        ("Huntsville.Ordinance No. 2026-01 follows", "Huntsville"),
        (
            "Boston to accept and expend the amount of $500,000 for a grant",
            "Boston",
        ),
        (
            "Fort Worth in Communications with the Texas Department of "
            "Transportation regarding",
            "Fort Worth",
        ),
        (
            "Edgewater and the Florida Department of Transportation entered "
            "into an agreement",
            "Edgewater",
        ),
        ("Milwaukee. Next item on the agenda", "Milwaukee"),
    ]
    for tail, expected_city in cases:
        html = f"<html><body>preamble City of {tail}</body></html>"
        soup = BeautifulSoup(html, "html.parser")
        metadata = GranicusAssetFinder()._extract_metadata(
            soup, "https://example.granicus.com/player/clip/1", html
        )
        assert expected_city in metadata["jurisdiction"], (
            f"expected {expected_city!r} in {metadata['jurisdiction']!r} "
            f"(input tail: {tail!r})"
        )
        assert "Communications" not in metadata["jurisdiction"]
        assert "Department" not in metadata["jurisdiction"]


def test_extract_metadata_jurisdiction_bleed_regressions_via_subdomain_fallback():
    # WO-14 (BACKLOG.md, 2026-08-16): the remaining 4 of 9 confirmed-real
    # cases (Sarasota, Punta Gorda, Castle Rock, Castle Pines). These are
    # NOT fixed by extract_jurisdiction_chain()'s text tiers alone -- the
    # bled tail in each ("Legacy Business PLEDGE OF", "Council is seeking",
    # "Authorizing", "History of Parks and Recreat[ion]") is itself
    # Title-Case/ALL-CAPS prose with no lowercase/digit/roman-numeral
    # signal, so `_looks_like_bleed()`'s trim-repair gate (deliberately
    # conservative -- see its own docstring) declines to trim it, exactly
    # the still-open "Title-Case/ALL-CAPS bleed" gap BACKLOG.md's Census
    # baseline entry already flags for Sarasota/Hollywood/Hampton. What
    # actually recovers the correct city for these 4 in production is
    # Granicus's own subdomain-per-customer convention (confirmed the
    # pattern across every other Granicus example in this codebase, e.g.
    # hercules.granicus.com, memphis.granicus.com) -- the chain's
    # Census-validated subdomain tier catches what the text tiers miss.
    # Uses each city's real, conventional Granicus-style subdomain rather
    # than a generic placeholder, since that convention is what's actually
    # under test here.
    cases = [
        (
            "sarasota",
            "Sarasota Legacy Business PLEDGE OF PUBLIC COMMENT follows",
            "Sarasota",
        ),
        (
            "puntagorda",
            "Punta Gorda Council is seeking the services of a contractor",
            "Punta Gorda",
        ),
        (
            "castlerock",
            "Castle Rock Authorizing the Plum Creek Water Reclamation "
            "Authority contract",
            "Castle Rock",
        ),
        (
            "castlepines",
            "Castle Pines History of Parks and Recreation department report",
            "Castle Pines",
        ),
    ]
    for subdomain, tail, expected_city in cases:
        html = f"<html><body>preamble City of {tail}</body></html>"
        soup = BeautifulSoup(html, "html.parser")
        metadata = GranicusAssetFinder()._extract_metadata(
            soup, f"https://{subdomain}.granicus.com/player/clip/1", html
        )
        assert expected_city in metadata["jurisdiction"], (
            f"expected {expected_city!r} in {metadata['jurisdiction']!r} "
            f"(input tail: {tail!r})"
        )
        assert "Authorizing" not in metadata["jurisdiction"]
        assert "PLEDGE" not in metadata["jurisdiction"]
        assert "Recreation" not in metadata["jurisdiction"]


async def test_resolve_retypes_county_from_page_meta_description():
    # Real Albemarle County, VA clip 1452 (fetched live 2026-08-23). The
    # page's only jurisdiction text is "for Albemarle County" inside
    # <meta name="description">; the subdomain label "albemarle" ALSO
    # validates as the unrelated city of Albemarle, NC, which is exactly
    # what production stored ("Albemarle, NC" -- a Virginia county's
    # Board of Supervisors meeting filed under a North Carolina city).
    # The chain's subdomain tier must retype the bare label as a county
    # when the page's own text says so -- see
    # jurisdiction_enrich._county_retype_from_page_text().
    url = "https://albemarle.granicus.com/player/clip/1452"
    html = load_fixture("granicus", "albemarle_clip1452.html")

    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        "https://albemarle.granicus.com/videos/1452/captions.vtt": FakeResponse(
            status=404
        ),
        "https://albemarle.granicus.com/AgendaViewer.php?clip_id=1452&embedded=1": FakeResponse(
            status=404
        ),
    }

    with mock_session(routes):
        result = await GranicusAssetFinder().resolve(url)

    assert result.jurisdiction == "Albemarle County, VA"
    assert result.date == "2026-03-04"  # from the page's own title


async def test_resolve_body_text_date_scan_rejects_future_dates():
    # Real Mission Viejo, CA clip 2515 (fetched live 2026-08-23). The
    # page carries no meeting date anywhere -- no meta, none in the
    # title, no view_id for an RSS lookup -- but agenda item 16 reads
    # "Calling for a General Municipal Election on November 3, 2026",
    # and the body-text last-resort scan stored that future election
    # date as the meeting's own date in production. A recorded clip's
    # meeting date is never meaningfully in the future, so the body scan
    # must skip future matches and come through honestly dateless.
    url = "https://missionviejo.granicus.com/player/clip/2515"
    html = load_fixture("granicus", "missionviejo_clip2515.html")

    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        "https://missionviejo.granicus.com/videos/2515/captions.vtt": FakeResponse(
            status=404
        ),
        "https://missionviejo.granicus.com/AgendaViewer.php?clip_id=2515&embedded=1": FakeResponse(
            status=404
        ),
        "https://missionviejo.granicus.com/MinutesViewer.php?clip_id=2515&embedded=1": FakeResponse(
            status=404
        ),
    }

    with mock_session(routes):
        result = await GranicusAssetFinder().resolve(url)

    assert result.jurisdiction == "City of Mission Viejo, CA"
    assert result.date is None


async def test_resolve_prefers_rss_item_date_over_body_text_guess():
    # Real Tulsa, OK clip 7694 (page and RSS feed both fetched live
    # 2026-08-23; the RSS fixture is the real feed trimmed to the
    # channel header plus clip 7694's own <item>). The page's body text
    # contains "current term expires December 31, 2026" in an
    # appointment agenda item, which production stored as the meeting
    # date; the feed's <gran:pubDateParts yr='2026' mo='08' day='05'>
    # has the real one. Structured RSS beats a body-text guess (and the
    # future-date rejection independently discards 12/31 anyway -- this
    # test pins the priority so a PAST wrong body date would also lose).
    url = "https://tulsa-ok.granicus.com/player/clip/7694?redirect=true&view_id=4"
    html = load_fixture("granicus", "tulsa_clip7694.html")
    rss = load_fixture("granicus", "tulsa_view4_rss_clip7694.xml")

    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        "https://tulsa-ok.granicus.com/ViewPublisherRSS.php?view_id=4&mode=video": FakeResponse(
            status=200, text=rss
        ),
        "https://tulsa-ok.granicus.com/videos/7694/captions.vtt": FakeResponse(
            status=404
        ),
        "https://tulsa-ok.granicus.com/AgendaViewer.php?clip_id=7694&embedded=1": FakeResponse(
            status=404
        ),
    }

    with mock_session(routes):
        result = await GranicusAssetFinder().resolve(url)

    assert result.date == "2026-08-05"
    assert result.jurisdiction == "City of Tulsa, OK"


def test_strip_meeting_access_tail_real_titles():
    # All five garbage tails are real production titles found 2026-08-23
    # (see BACKLOG_DONE.md's jurisdiction/data-quality entry) -- one of
    # them carried a live Zoom passcode into Google's crawl.
    from app.platforms.granicus import _strip_meeting_access_tail

    cases = [
        (
            "BOARD OF SUPERVISORS on 2026-08-11 9:00 AM - "
            "https://smcgov.zoom.us/j/85158697628",
            "BOARD OF SUPERVISORS on 2026-08-11 9:00 AM",
        ),
        (
            "City Council on 2024-05-14 6:00 PM - CLOSED SESSION - 6:00 P.M., "
            "REGULAR MEETING - 7:00 P.M.In-Person in Council Chambers or to "
            "Listen only: Zoom ID: 853 6598 5956Zoom Passcode: 123456",
            "City Council on 2024-05-14 6:00 PM - CLOSED SESSION - 6:00 P.M., "
            "REGULAR MEETING - 7:00 P.M.",
        ),
        (
            "Commission Workshop  on 2025-02-11 6:30 PM - Live stream via "
            "https://zoom.us/join\nZoom Meeting ID:  870 2043 1217",
            "Commission Workshop  on 2025-02-11 6:30 PM",
        ),
        (
            "Committee of the Whole on 2024-04-02 1:30 PM - "
            "Meeting ID: 895 1103 3332 Passcode: 193069",
            "Committee of the Whole on 2024-04-02 1:30 PM",
        ),
        # Negative controls: ordinary titles must come through untouched.
        ("Regular City Council Meeting", "Regular City Council Meeting"),
        (
            "Board of Supervisors on 2026-03-04 1:00 PM - Regular First Meeting",
            "Board of Supervisors on 2026-03-04 1:00 PM - Regular First Meeting",
        ),
    ]
    for raw, expected in cases:
        assert _strip_meeting_access_tail(raw) == expected


async def test_resolve_populates_meeting_body_from_rss_channel_title():
    # Synthetic RSS reusing the exact confirmed channel-title schema
    # ("{Jurisdiction}: {Body} (Videos Feed)" -- confirmed across 6 real
    # cities 2026-08-06, see _fetch_channel_info's docstring; "City of
    # San Diego: City Council Meetings" is that docstring's own real
    # example). Synthetic because the real Tulsa fixture's channel body
    # ("TGOV - Tulsa Government Access Television") legitimately carries
    # no governing-body keyword and correctly produces meeting_body=None.
    url = "https://sandiego.granicus.com/player/clip/99?view_id=3"
    html = (
        "<html><head><meta property='og:title' content='Budget Hearing on "
        "2024-05-06 2:00 PM'/></head><body>City of San Diego</body></html>"
    )
    rss = (
        "<rss><channel><title>City of San Diego: City Council Meetings "
        "(Videos Feed)</title></channel></rss>"
    )
    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        "https://sandiego.granicus.com/ViewPublisherRSS.php?view_id=3&mode=video": FakeResponse(
            status=200, text=rss
        ),
        "https://sandiego.granicus.com/videos/99/captions.vtt": FakeResponse(
            status=404
        ),
        "https://sandiego.granicus.com/videos/99/player": FakeResponse(status=404),
        "https://sandiego.granicus.com/AgendaViewer.php?clip_id=99&embedded=1": FakeResponse(
            status=404
        ),
    }

    with mock_session(routes):
        result = await GranicusAssetFinder().resolve(url)

    assert result.meeting_body == "City Council Meetings"
    assert result.jurisdiction == "City of San Diego, CA"


async def test_resolve_rejects_a_domain_shaped_rss_channel_title():
    # Real bug, confirmed live 2026-08-29 auditing archived pages:
    # lcd.granicus.com's own real RSS <title> is literally
    # "lcd.granicus.com: Oregon LCD View (Videos Feed)" -- a misconfigured
    # customer echoing their own hostname instead of a real jurisdiction
    # name -- which flowed straight through as the stored jurisdiction
    # with no validation at all, unlike every other tier. A domain-shaped
    # string (has a dot, no spaces) must be rejected rather than trusted.
    url = "https://lcd.granicus.com/player/clip/106?view_id=1"
    html = "<html><body>Oregon LCD View</body></html>"
    rss = (
        "<rss><channel><title>lcd.granicus.com: Oregon LCD View "
        "(Videos Feed)</title></channel></rss>"
    )
    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        "https://lcd.granicus.com/ViewPublisherRSS.php?view_id=1&mode=video": FakeResponse(
            status=200, text=rss
        ),
        "https://lcd.granicus.com/videos/106/captions.vtt": FakeResponse(status=404),
        "https://lcd.granicus.com/videos/106/player": FakeResponse(status=404),
        "https://lcd.granicus.com/AgendaViewer.php?clip_id=106&embedded=1": FakeResponse(
            status=404
        ),
    }

    with mock_session(routes):
        result = await GranicusAssetFinder().resolve(url)

    assert result.jurisdiction == "Unknown Jurisdiction"
