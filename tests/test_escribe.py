import json

import pytest

from app.platforms.base import NoVideoCandidateFound
from app.platforms.escribe import EscribeAssetFinder
from app.platforms.youtube import YouTubeAssetFinder

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture, load_fixture_bytes

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


async def test_jurisdiction_from_subdomain_no_prefix_allowlist():
    # WO-69 (2026-08-30): tcdsbpublishing.escribemeetings.com is the one
    # confirmed real eScribe tenant with no "pub-" prefix at all
    # (confirmed live: the bare domain returns 200 with real content, the
    # "pub-" prefixed guess times out). "tcdsbpublishing" doesn't itself
    # validate against the Census/StatsCan tables (it's an institutional
    # acronym, not a place name), so this correctly returns None here --
    # jurisdiction_enrich._KNOWN_DOMAINS is what actually supplies
    # "Toronto Catholic District School Board, ON" for this domain, at
    # ingest time (see tests/test_jurisdiction_enrich.py).
    assert (
        EscribeAssetFinder._jurisdiction_from_subdomain(
            "https://tcdsbpublishing.escribemeetings.com/Meeting.aspx?Id=1"
        )
        is None
    )
    # Deliberately narrow: a real, different eScribe tenant that ALSO
    # lacks the "pub-" prefix (confirmed real via
    # scripts/tier3_auto_transcription_queue.txt) must NOT start being
    # subdomain-guessed just because the allowlist exists -- widening
    # `_SUBDOMAIN_RE` generally would also start guessing
    # richmond.escribemeetings.com, a real, separate tenant from
    # pub-richmond.escribemeetings.com that BACKLOG.md's own
    # `[NEEDS-AUDIT]` entry already flags as resolving to the wrong
    # country when guessed. Not in the allowlist, so still None.
    assert (
        EscribeAssetFinder._jurisdiction_from_subdomain(
            "https://richmond.escribemeetings.com/Meeting.aspx?Id=1"
        )
        is None
    )
    # The ordinary "pub-" case must keep working unchanged.
    assert (
        EscribeAssetFinder._jurisdiction_from_subdomain(
            "https://pub-milton.escribemeetings.com/Meeting.aspx?Id=1"
        )
        == "Milton"
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


async def test_resolve_video_present_but_no_caption_file_found(caplog):
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

    with caplog.at_level("WARNING"):
        with mock_session(routes):
            result = await EscribeAssetFinder().resolve(url)

    assert result.video_url is not None
    assert result.segments == []
    assert any(
        "no caption file was found" in w.lower() for w in result.transcript_warnings
    )
    # 2026-08-28: a failed VTT fetch used to be silent -- now logged.
    assert any("VTT fetch got HTTP 404" in r.message for r in caplog.records)


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
        # Real gap found 2026-08-29 auditing archived pages missing a
        # jurisdiction (BACKLOG.md's "StatsCan/Census table completeness
        # gap" entry): these two real Ontario municipalities are stored
        # hyphenated in the table but neither the label's own hyphen
        # ("chatham-kent", stripped by this function's own `.replace("-",
        # "")` before validation) nor a glued/spaced wordninja join ever
        # reconstructed it -- fixed at the shared validator via a new
        # hyphen-joined candidate.
        ("pub-chatham-kent.escribemeetings.com", "Chatham-Kent"),
        ("pub-arranelderslie.escribemeetings.com", "Arran-Elderslie"),
        # Real gap found 2026-08-31 auditing eScribe pages with no
        # jurisdiction (BACKLOG.md's "eScribe hyphen-matcher gap"): unlike
        # Chatham-Kent/Arran-Elderslie above, this real Ontario
        # municipality's subdomain does NOT survive the strip-then-
        # wordninja path at all -- `wordninja.split("strathroycaradoc")`
        # returns `['strath', 'roy', 'cara', 'doc']`, since neither
        # "strathroy" nor "caradoc" is a token wordninja's own dictionary
        # can segment (confirmed live via wordninja itself, not just this
        # function). Fixed by passing the subdomain's own real hyphen
        # through unchanged instead of stripping it first -- the table's
        # own row is spelled with the identical hyphen
        # ("Strathroy-Caradoc, ON"), so `validated_label_extract()`'s tier
        # 1 (a raw-label table check, before wordninja ever runs) now
        # catches it directly.
        ("pub-strathroy-caradoc.escribemeetings.com", "Strathroy-Caradoc"),
    ]
    for netloc, expected in cases:
        assert (
            EscribeAssetFinder._jurisdiction_from_subdomain(f"https://{netloc}/x")
            == expected
        )


# --- WO-938, 2026-09-21: decode-safety (escribe.py raised the same raw
# UnicodeDecodeError shape civicplus.py fixed, WO-285) and the bare-
# tenant-root "listing root -> newest meeting" helper. ---


async def test_resolve_non_utf8_response_degrades_instead_of_raising():
    # WO-225 (2026-09-11) hit `RowError: escribe: resolve raised: 'utf-8'
    # codec can't decode byte 0xe2 in position 10: invalid continuation
    # byte` resolving Ladysmith, BC's real eScribe tenant -- the exact
    # same byte value/position as the civicplus.py bug WO-285 fixed. This
    # is a synthetic test (no real eScribe tenant serving a raw PDF at
    # its own Meeting.aspx URL has been found) but reuses the SAME real,
    # non-UTF8 bytes tests/test_civicplus.py's own decode-safety test
    # uses -- a real PDF fetched live 2026-09-12 from Richmond Hill GA's
    # CivicPlus DocumentCenter, reproducing the identical error text --
    # rather than inventing new ones, per this repo's rule on reusing
    # real byte sequences for a decode-safety test.
    url = "https://pub-ladysmith.escribemeetings.com/Meeting.aspx?Id=1"
    pdf_bytes = load_fixture_bytes("civicplus", "richmondhill_documentcenter_5032.bin")
    routes = {url: FakeResponse(status=200, raw=pdf_bytes, url=url)}

    with mock_session(routes):
        # No crash -- the raw, non-decodable bytes just carry no
        # recognizable eScribe markup, so this degrades to the ordinary
        # "no video integration found" outcome instead of raising.
        result = await EscribeAssetFinder().resolve(url)

    assert result.platform == "escribe"
    assert result.video_url is None


async def test_resolve_bare_tenant_root_discovers_newest_meeting_with_video():
    # WO-128 (2026-09-09): a bare eScribe tenant root -- no
    # Meeting.aspx/ISIStandAlonePlayer.aspx path at all, the shape
    # jurisdiction_coverage.csv's own `domain` column holds for many
    # Canadian eScribe governments (real examples: pub-southdundas.
    # escribemeetings.com, pub-hawkesbury.escribemeetings.com) -- used to
    # "resolve" with zero content instead of finding a real meeting.
    # This confirms the fix: discover the tenant's own newest HasVideo
    # meeting via GetCalendarMeetings and actually resolve it.
    domain = "pub-southdundas.escribemeetings.com"
    tenant_url = f"https://{domain}/"
    calendar_url = f"https://{domain}/MeetingsCalendarView.aspx/GetCalendarMeetings"
    meeting_guid = "981f78d7-8211-4b4b-b066-5f93b4fd5e74"
    meeting_url = f"https://{domain}/Meeting.aspx?Id={meeting_guid}"

    calendar_json = json.dumps(
        {
            "d": [
                {
                    "ID": meeting_guid,
                    "StartDate": "2026-07-15T00:00:00",
                    "MeetingDocumentLink": [{"HasVideo": True}],
                }
            ]
        }
    )
    meeting_html = (
        "<html><head><title>City Council Meeting - July 15, 2026</title></head>"
        "<body>"
        '<div id="isi_player" data-client_id="southdundas" '
        'data-stream_name="clip.mp4"></div>'
        "</body></html>"
    )

    routes = {meeting_url: FakeResponse(status=200, text=meeting_html, url=meeting_url)}
    # _fetch_vtt() tries every KNOWN_LANGUAGE_SUFFIXES entry -- none
    # populated here, this test is only about the discovery+resolve
    # wiring, not captions (already covered by the Bakersfield tests
    # above).
    for suffix in [None, "fr", "es", "zh", "zh-hant", "tl"]:
        vtt_url = (
            "https://video.isilive.ca/southdundas/clip.mp4"
            + (f".{suffix}" if suffix else "")
            + ".vtt"
        )
        routes[vtt_url] = FakeResponse(status=404)
    post_routes = {calendar_url: FakeResponse(status=200, text=calendar_json)}

    with mock_session(routes, post_routes=post_routes):
        result = await EscribeAssetFinder().resolve(tenant_url)

    assert result.source_url == meeting_url
    assert result.title == "City Council Meeting"
    assert result.date == "2026-07-15"
    assert result.video_url is not None


async def test_resolve_bare_tenant_root_raises_when_no_video_meeting_found():
    # No real HasVideo meeting in the lookback window -- a genuine,
    # confident negative (the same typed signal civicplus.py's own
    # listing-page case already raises), not a silent empty success.
    domain = "pub-quietcounty.escribemeetings.com"
    tenant_url = f"https://{domain}/"
    calendar_url = f"https://{domain}/MeetingsCalendarView.aspx/GetCalendarMeetings"
    post_routes = {calendar_url: FakeResponse(status=200, text=json.dumps({"d": []}))}

    with mock_session({}, post_routes=post_routes):
        with pytest.raises(NoVideoCandidateFound):
            await EscribeAssetFinder().resolve(tenant_url)


# --- WO-1048 (2026-09-24): one county tenant, one name -------------------
# Both pages are real, fetched live 2026-09-24 from McHenry County, IL's
# tenant. Before this fix the County Board page (whose text says "County
# of McHenry") gave "County of McHenry, IL", and the Staff Plat Review
# page (which doesn't) fell back to the subdomain and gave "Mchenry, IL"
# -- the name of a separate real city, McHenry, IL.
MCHENRY_BASE = (
    "https://pub-countyofmchenry.escribemeetings.com/Meeting.aspx"
    "?Agenda=Agenda&lang=English&Id="
)


@pytest.mark.parametrize(
    "fixture_name, meeting_id",
    [
        (
            "mchenry_county_board_2026-09-15.html",
            "6c0b14f1-de9b-4e42-969f-05e359fd5a56",
        ),
        (
            "mchenry_staff_plat_review_2026-03-18.html",
            "ff14891d-8792-4210-9ae0-4d45544d76f8",
        ),
    ],
)
def test_county_of_tenant_gets_one_county_name_on_every_page(fixture_name, meeting_id):
    from bs4 import BeautifulSoup

    html = load_fixture("escribe", fixture_name)
    soup = BeautifulSoup(html, "html.parser")
    _title, _date, jurisdiction = EscribeAssetFinder._extract_metadata(
        soup, MCHENRY_BASE + meeting_id, html
    )
    assert jurisdiction == "McHenry County, IL"


def test_county_of_tenant_name_leaves_other_tenants_alone():
    # A city tenant, and a Canadian "County of" tenant (the county table
    # knows Simcoe County, ON, but the rule is US-only until a Canadian
    # tenant is checked), both pass through unchanged.
    assert (
        EscribeAssetFinder._county_of_tenant_name(
            "https://pub-bakersfield.escribemeetings.com/Meeting.aspx?Id=x",
            "Bakersfield, CA",
        )
        == "Bakersfield, CA"
    )
    assert (
        EscribeAssetFinder._county_of_tenant_name(
            "https://pub-countyofsimcoe.escribemeetings.com/Meeting.aspx?Id=x",
            "County of Simcoe, ON",
        )
        == "County of Simcoe, ON"
    )
    # No state settled yet: nothing to scope the county lookup by.
    assert (
        EscribeAssetFinder._county_of_tenant_name(
            MCHENRY_BASE + "x", "County of McHenry"
        )
        == "County of McHenry"
    )
