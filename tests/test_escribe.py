from app.platforms.escribe import EscribeAssetFinder
from app.platforms.youtube import YouTubeAssetFinder

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture

# No fixture-based tests existed for this adapter before this file (see
# BACKLOG.md's "zero test coverage" note). PAGE_URL/VTT_URL below are the
# real Bakersfield, CA meeting this adapter's agenda-timestamp and
# jurisdiction-fallback support were both built against 2026-08-08/09 --
# see BACKLOG_DONE.md.

PAGE_URL = (
    "https://pub-bakersfield.escribemeetings.com/Meeting.aspx"
    "?Id=981f78d7-8211-4b4b-b066-5f93b4fd5e74&Agenda=Agenda&lang=English"
)
VTT_URL = (
    "https://video.isilive.ca/bakersfield/"
    "iSiLIVE%20Encoder%20760_CCM330_2026-07-15-06-04.mp4.vtt"
)


async def test_resolve_real_bakersfield_meeting():
    html = load_fixture("escribe", "bakersfield_ccm330_page.html")
    vtt = load_fixture("escribe", "bakersfield_ccm330_captions.vtt")

    routes = {
        PAGE_URL: FakeResponse(status=200, text=html, url=PAGE_URL),
        VTT_URL: FakeResponse(status=200, text=vtt, url=VTT_URL),
    }

    with mock_session(routes):
        result = await EscribeAssetFinder().resolve(PAGE_URL)

    assert result.platform == "escribe"
    assert result.title == "City Council Meeting 330"
    assert result.date == "2026-07-15"
    # Real bug fixed 2026-08-09: the page body has no "City of X" phrase
    # (just a plain address), so jurisdiction used to silently come back
    # None -- now falls back to the pub-{city}.escribemeetings.com
    # subdomain. State appended 2026-08-12 via the shared
    # jurisdiction_enrich module -- "Bakersfield" is a real, nationally-
    # unique incorporated place name.
    assert result.jurisdiction == "Bakersfield, CA"
    assert result.video_url == (
        "https://cdn1.isilive.ca/vod/_definst_/mp4:bakersfield/"
        "iSiLIVE%20Encoder%20760_CCM330_2026-07-15-06-04.mp4/playlist.m3u8"
    )
    assert result.video_format == "m3u8"
    assert len(result.segments) == 25  # the trimmed real VTT fixture's cue count
    assert (
        result.segments[0].text
        == "The 330 p. m. meeting of the Bakersfield City Council"
    )

    # Real bug fixed 2026-08-09: EscribeAssetFinder never extracted
    # agenda_items at all, despite the real page having exactly the
    # structured markup needed for it (see BACKLOG_DONE.md). Only 4 of
    # the page's 10 real .AgendaItem entries have a matching video.
    # Bookmarks timestamp -- the other 6 (procedural items like "ROLL
    # CALL") are deliberately omitted rather than given a fake time.
    assert len(result.agenda_items) == 4
    assert [item.text for item in result.agenda_items] == [
        "Non-Agenda Item Public Statements",
        "Public Employee Performance Evaluation - City Manager; Closed Session "
        "pursuant to Government Code Section 54957(b)(1) / 54957.6",
        "CLOSED SESSION ACTION",
        "ADJOURNMENT",
    ]
    first = result.agenda_items[0]
    assert first.start == 1753.667
    assert first.end == 2136.595


async def test_jurisdiction_from_subdomain_used_only_as_fallback():
    assert (
        EscribeAssetFinder._jurisdiction_from_subdomain(
            "https://pub-bakersfield.escribemeetings.com/Meeting.aspx?Id=1"
        )
        == "Bakersfield"
    )
    assert (
        EscribeAssetFinder._jurisdiction_from_subdomain(
            "https://pub-simi-valley.escribemeetings.com/Meeting.aspx?Id=1"
        )
        == "Simi Valley"
    )
    assert (
        EscribeAssetFinder._jurisdiction_from_subdomain(
            "https://example.com/Meeting.aspx?Id=1"
        )
        is None
    )


async def test_extract_agenda_items_handles_missing_bookmarks_array():
    html = (
        "<html><body><div class='AgendaItem'><div class='AgendaItemTitle'>"
        '<a href="javascript:SelectItem(1);">Roll Call</a></div></div></body></html>'
    )
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    assert EscribeAssetFinder._extract_agenda_items(soup, html) == []


async def test_extract_agenda_items_handles_malformed_bookmarks_json():
    html = (
        '<script>var video = { Bookmarks : [{"AgendaItemId":1,not-json},'
        "</script>"
        "<div class='AgendaItem'><div class='AgendaItemTitle'>"
        '<a href="javascript:SelectItem(1);">Roll Call</a></div></div>'
    )
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    assert EscribeAssetFinder._extract_agenda_items(soup, html) == []


async def test_extract_agenda_items_skips_items_without_a_matching_bookmark():
    html = (
        '<script>var video = { Bookmarks : [{"AgendaItemId":2,"TimeStart":1000,"TimeEnd":2000}],'
        "</script>"
        "<div class='AgendaItem'><div class='AgendaItemTitle'>"
        '<a href="javascript:SelectItem(1);">Roll Call</a></div></div>'
        "<div class='AgendaItem'><div class='AgendaItemTitle'>"
        '<a href="javascript:SelectItem(2);">Public Comment</a></div></div>'
    )
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    items = EscribeAssetFinder._extract_agenda_items(soup, html)
    assert len(items) == 1
    assert items[0].text == "Public Comment"
    assert items[0].start == 1.0
    assert items[0].end == 2.0


async def test_resolve_no_video_integration_returns_warning_not_crash():
    url = "https://pub-example.escribemeetings.com/Meeting.aspx?Id=2"
    html = "<html><head><title>Untitled - January 1, 2026</title></head><body>No player here.</body></html>"

    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await EscribeAssetFinder().resolve(url)

    assert result.platform == "escribe"
    assert result.video_url is None
    # "example" isn't a real place -- _jurisdiction_from_subdomain() now
    # declines instead of guessing (2026-08-18 gating fix, see that
    # function's own docstring), so this correctly comes back None rather
    # than a title-cased guess.
    assert result.jurisdiction is None
    assert any("no video integration found" in w.lower() for w in result.video_warnings)


async def test_resolve_video_present_but_no_caption_file_found():
    url = "https://pub-example.escribemeetings.com/Meeting.aspx?Id=3"
    html = (
        "<html><head><title>Meeting - January 1, 2026</title></head><body>"
        '<div id="isi_player" data-client_id="example" data-stream_name="clip.mp4"></div>'
        "</body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}
    for suffix in [None, "fr", "es", "zh", "zh-hant", "tl"]:
        vtt_url = (
            "https://video.isilive.ca/example/clip.mp4"
            + (f".{suffix}" if suffix else "")
            + ".vtt"
        )
        routes[vtt_url] = FakeResponse(status=404)

    with mock_session(routes):
        result = await EscribeAssetFinder().resolve(url)

    assert result.video_url is not None
    assert result.segments == []
    assert any(
        "no caption file was found" in w.lower() for w in result.transcript_warnings
    )


# --- 2026-08-14 rebuild coverage (Phase 4: the opt-in generic-scan
# backstop -- eScribe is the first adapter wired in, chosen because "no
# video integration" is its documented common real outcome and its pages
# are per-meeting, so wrong-video risk is low). ---


async def test_backstop_finds_youtube_embed_when_no_isi_player(monkeypatch):
    # Real shape, confirmed live 2026-08-16 across 51 real eScribe pages
    # (see BACKLOG_DONE.md) -- back when this test was written the shape
    # itself was synthetic; it's since been confirmed on many real cities
    # (e.g. pub-beaumontab, pub-brant, pub-cambridge.escribemeetings.com).
    # Real gap found the same day: this backstop used to stop at the raw
    # embed URL without ever fetching captions -- every real
    # YouTube-embedded eScribe meeting sat with segments=[] regardless of
    # whether captions actually existed. Now delegates to
    # YouTubeAssetFinder.resolve_video_id() the same way primegov.py/
    # civicweb.py/clerkbase.py already do.
    monkeypatch.setattr(
        YouTubeAssetFinder,
        "_extract_info",
        lambda video_id: {
            "title": "City of Example — YouTube channel upload",
            "uploader": "cityofexample",
            "upload_date": "20260102",
            "_chosen_track": (
                ("WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nCall to order.\n").encode(
                    "utf-8"
                ),
                "en",
                True,
            ),
        },
    )
    url = "https://pub-example.escribemeetings.com/Meeting.aspx?Id=9"
    html = (
        "<html><head><title>Council Meeting - January 1, 2026</title></head><body>"
        '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>'
        "</body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await EscribeAssetFinder().resolve(url)

    # platform stays "escribe", not "youtube" -- same reasoning as
    # primegov.py's delegation: the caller pasted an eScribe URL, "View
    # original source" should keep pointing there.
    assert result.platform == "escribe"
    assert result.video_url == "https://www.youtube.com/embed/dQw4w9WgXcQ"
    assert result.video_format == "youtube"
    assert len(result.segments) == 1
    assert result.segments[0].text == "Call to order."
    assert result.transcript_language == "en"
    # A backstop hit is best-effort by definition, with a provenance
    # warning -- the video came from a generic scan, not eScribe's own
    # structure.
    assert result.best_effort is True
    assert any("general scan of the page" in w for w in result.video_warnings)
    # eScribe's own metadata is preferred over YouTube's channel-upload title.
    assert result.title == "Council Meeting"
    assert result.date == "2026-01-01"


async def test_backstop_youtube_falls_back_to_page_metadata_when_missing(monkeypatch):
    # Mirror of primegov.py's own override-only-when-empty test: if
    # eScribe's own page has no usable title/date, YouTube's real values
    # should still come through rather than leaving both None.
    monkeypatch.setattr(
        YouTubeAssetFinder,
        "_extract_info",
        lambda video_id: {
            "title": "Real YouTube Title",
            "uploader": "cityofexample",
            "upload_date": "20260102",
            "_chosen_track": None,
        },
    )
    url = "https://pub-example.escribemeetings.com/Meeting.aspx?Id=10"
    html = (
        "<html><head><title></title></head><body>"
        '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>'
        "</body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await EscribeAssetFinder().resolve(url)

    assert result.title == "Real YouTube Title"
    assert result.date == "2026-01-02"
    assert result.segments == []


async def test_backstop_surfaces_vimeo_pointer_for_perry_ga_shape(monkeypatch):
    # Perry, GA is the CONFIRMED real beneficiary shape (this adapter's
    # own 2026-08-06 docstring): no iSiLIVE integration at all, just a
    # plain link to a live Vimeo stream. Synthetic reconstruction of that
    # confirmed shape (the original page wasn't captured).
    url = "https://pub-perryga.escribemeetings.com/Meeting.aspx?Id=4"
    html = (
        "<html><head><title>Council Meeting - January 1, 2026</title></head><body>"
        '<a href="https://vimeo.com/123456789">Watch the live stream</a>'
        "</body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await EscribeAssetFinder().resolve(url)

    assert result.video_url is None
    assert result.video_link == "https://vimeo.com/123456789"
    assert result.video_link_recognized is True
    assert result.best_effort is True


async def test_backstop_leaves_true_no_video_result_unchanged():
    # A page with genuinely nothing video-shaped keeps the original honest
    # warning, no best_effort flag, no pointer.
    url = "https://pub-example.escribemeetings.com/Meeting.aspx?Id=2"
    html = "<html><head><title>Untitled - January 1, 2026</title></head><body>No player here.</body></html>"
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await EscribeAssetFinder().resolve(url)

    assert result.video_url is None
    assert result.video_link is None
    assert result.best_effort is False
    assert any("no video integration found" in w.lower() for w in result.video_warnings)


def test_extract_metadata_jurisdiction_no_longer_bleeds_into_agenda_text():
    # WO-14 (BACKLOG.md, 2026-08-16): synthetic page-text reconstructions
    # around the exact bled substrings BACKLOG.md quotes as confirmed real
    # on 6 live eScribe customers, found 2026-08-15 -- the surrounding
    # filler text is invented since the full original page text wasn't
    # captured at the time, but the bled fragment, real subdomain, and
    # correct city are real, confirmed values, not guesses. The old bare
    # `re.search(r"City of ([A-Za-z .]+)", page_text)` had no sentence/tag
    # boundary and would have kept the whole tail as the jurisdiction.
    from bs4 import BeautifulSoup

    cases = [
        (
            "pub-cityofgainesville.escribemeetings.com",
            "Gainesville General Policy Committee Meeting AGENDA Thursday, ",
            "Gainesville",
        ),
        (
            "pub-delta.escribemeetings.com",
            "Delta Housing Accelerator Fund Initiatives Summary.pdf Recommendation ",
            "Delta",
        ),
        (
            "pub-mississauga.escribemeetings.com",
            "Mississauga as being part of the Treaty and Traditional "
            "Territory of the Mississaugas of the Credit First Nation, "
            "we thank",
            "Mississauga",
        ),
        (
            "pub-oshawa.escribemeetings.com",
            "Oshawa is situated on lands within the traditional and treaty "
            "territory of the Michi Saagiig",
            "Oshawa",
        ),
        (
            "pub-portmoody.escribemeetings.com",
            "Port Moody Strategic Priorities Committee Agenda Tuesday, ",
            "Port Moody",
        ),
        (
            "pub-thunderbay.escribemeetings.com",
            "Thunder Bay be approved in accordance with Table 1 of the report",
            "Thunder Bay",
        ),
    ]
    for subdomain, tail, expected_city in cases:
        html = (
            f"<html><title>Meeting - January 1, 2026</title>"
            f"<body>City of {tail}</body></html>"
        )
        soup = BeautifulSoup(html, "html.parser")
        _title, _date, jurisdiction = EscribeAssetFinder._extract_metadata(
            soup, f"https://{subdomain}/x", html
        )
        # Substring, not exact equality -- a stored jurisdiction can
        # legitimately keep a "City of "/"Town of " prefix (stripped only
        # at display time by format_jurisdiction_display(), see WO-14's
        # own BACKLOG_DONE.md entry) depending on which tier of
        # extract_jurisdiction_chain() actually resolved it; WO-16
        # (BACKLOG.md, 2026-08-16) confirmed real "Oshawa" collides with a
        # genuine, obscure Oshawa Township, MN (Census-real, added to
        # county_subdivisions.csv) -- validates through the primary
        # stop-rule tier now instead of falling back to the bare-name
        # subdomain path, changing the exact string shape but not the
        # correctness of the identified city.
        assert expected_city in jurisdiction, (
            f"expected {expected_city!r} in {jurisdiction!r} (input tail: {tail!r})"
        )


# --- 2026-08-19: second real iSiLIVE page shape (Players/ISIStandAlonePlayer.aspx,
# `data-file_name` instead of `data-stream_name`) -- see EscribeAssetFinder's own
# class docstring and the comment above where `player` is selected in resolve().


async def test_resolve_real_caledon_isistandaloneplayer_page():
    # Real, live-confirmed 2026-08-19: pub-caledon.escribemeetings.com's
    # Players/ISIStandAlonePlayer.aspx?Id=74f36aec-87b7-4596-953d-f21174b1a13a
    # -- a genuinely different real page from the Meeting.aspx shape the rest
    # of this file covers (that same meeting Id's own Meeting.aspx page still
    # uses data-stream_name, confirmed separately). eSCRIBE's own
    # video.isilive.ca/cdn/isi_player.js source (fetched live) treats
    # data-file_name as a "legacy" synonym assigned straight into the same
    # stream_name variable used for URL construction, and a real fetch of
    # both cdn1.isilive.ca's playlist.m3u8 and video.isilive.ca's .vtt for
    # this exact value returned 200 with real, populated captions --
    # confirming the same URL-construction pattern applies unchanged.
    url = (
        "https://pub-caledon.escribemeetings.com/Players/ISIStandAlonePlayer.aspx"
        "?Id=74f36aec-87b7-4596-953d-f21174b1a13a"
    )
    html = load_fixture("escribe", "caledon_isistandaloneplayer_page.html")
    encoded = (
        "Compact%20Encoder%201105_Planning%20and%20Development%20Committee_"
        "2026-06-16-02-28.mp4"
    )
    vtt_url = f"https://video.isilive.ca/caledon/{encoded}.vtt"
    vtt = load_fixture("escribe", "caledon_isistandaloneplayer_captions.vtt")

    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        vtt_url: FakeResponse(status=200, text=vtt, url=vtt_url),
    }

    with mock_session(routes):
        result = await EscribeAssetFinder().resolve(url)

    assert result.platform == "escribe"
    assert result.video_url == (
        f"https://cdn1.isilive.ca/vod/_definst_/mp4:caledon/{encoded}/playlist.m3u8"
    )
    assert result.video_format == "m3u8"
    assert len(result.segments) == 19  # the trimmed real VTT fixture's cue count
    assert result.segments[0].text == (
        "Good afternoon, members of Council, staff members and members of"
    )
    # ISIStandAlonePlayer.aspx is a video-only page -- no title/agenda markup
    # at all (confirmed live: its own <title> tag is empty) -- so title/date
    # come back None and jurisdiction falls back to the subdomain, exactly
    # like the "no video integration" case's fallback path.
    assert result.title is None
    assert result.date is None
    assert result.jurisdiction == "Caledon, ON"
    assert result.agenda_items == []


# --- 2026-08-21: eScribe's first-ever confirmed populated-caption example
# (BACKLOG.md/BACKLOG_DONE.md) -- also the real page that surfaced the
# "two-tier regional site" jurisdiction bug the chain-level subdomain
# cross-check now fixes (app/utils/jurisdiction_enrich.py).


async def test_resolve_real_peel_region_meeting_gets_regional_jurisdiction_not_caledon():
    # Real, live-confirmed 2026-08-18/21:
    # pub-peelregion.escribemeetings.com/Meeting.aspx?Id=c129beef-a3cf-49ae-
    # 827d-27c6b3a547a5 -- a real Peel Region, ON "Regional Council"
    # meeting. Fixture is trimmed from the real ~225KB page (title,
    # #isi_player div, and the real clerk-signature agenda-item line kept
    # verbatim -- the rest of the page's ~90 unrelated agenda items
    # dropped): `Kevin Klingenberg, Municipal Clerk, Town of Caledon` is
    # the real text `_stoprule_extract()`/`_capitalization_walk_extract()`
    # both find and validate FIRST on the real page (confirmed directly,
    # not assumed) -- Caledon is a real constituent lower-tier town within
    # Peel Region's own agenda, not the meeting's own jurisdiction.
    #
    # Before the subdomain cross-check fix, this resolved as "Caledon, ON"
    # -- now the `peelregion` subdomain's own validated identity (resolvable
    # since scripts/build_jurisdiction_data.py added Ontario's real Durham/
    # Peel/Waterloo regional municipalities) wins instead.
    #
    # Video/captions must keep resolving exactly as before -- this bug's
    # fix must not regress the very page that closed the "no eScribe
    # example with populated captions" gap. VTT is trimmed to its first 20
    # real cues (same convention as the Caledon fixture above).
    url = (
        "https://pub-peelregion.escribemeetings.com/Meeting.aspx"
        "?Id=c129beef-a3cf-49ae-827d-27c6b3a547a5&Agenda=Agenda&lang=English"
    )
    html = load_fixture("escribe", "peel_region_page.html")
    encoded = "New%20Encoder_Regional%20Council_2026-07-09-09-30.mp4"
    vtt_url = f"https://video.isilive.ca/peelregion/{encoded}.vtt"
    vtt = load_fixture("escribe", "peel_region_captions.vtt")

    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        vtt_url: FakeResponse(status=200, text=vtt, url=vtt_url),
    }

    with mock_session(routes):
        result = await EscribeAssetFinder().resolve(url)

    assert result.platform == "escribe"
    assert result.title == "Regional Council"
    assert result.date == "2026-07-09"
    assert result.jurisdiction == "Peel Region, ON"
    assert result.video_url == (
        f"https://cdn1.isilive.ca/vod/_definst_/mp4:peelregion/{encoded}/playlist.m3u8"
    )
    assert result.video_format == "m3u8"
    assert len(result.segments) == 20  # the trimmed real VTT fixture's cue count
    assert result.segments[0].text == (
        "Good morning everyone and welcome. We are at the appointed"
    )
    assert not result.transcript_warnings


def test_jurisdiction_from_subdomain_splits_concatenated_multiword_names():
    # WO-14 (BACKLOG.md, 2026-08-16): this fallback used to be a bare
    # `.replace("-", " ").title()`, which only helps a subdomain with
    # literal hyphens -- real eScribe customers use one concatenated word
    # ("portmoody", "thunderbay" -- confirmed live), which collapsed into
    # "Portmoody"/"Thunderbay" instead of "Port Moody"/"Thunder Bay".
    cases = [
        ("pub-cityofgainesville.escribemeetings.com", "Gainesville"),
        ("pub-portmoody.escribemeetings.com", "Port Moody"),
        ("pub-thunderbay.escribemeetings.com", "Thunder Bay"),
        ("pub-delta.escribemeetings.com", "Delta"),
    ]
    for netloc, expected in cases:
        assert (
            EscribeAssetFinder._jurisdiction_from_subdomain(f"https://{netloc}/x")
            == expected
        )
