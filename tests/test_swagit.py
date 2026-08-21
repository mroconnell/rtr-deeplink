from bs4 import BeautifulSoup

from app.platforms.models import TranscriptSegment
from app.platforms.swagit import (
    SwagitAssetFinder,
    _group_word_fragments,
    _is_swagit_events_template_dead_candidate,
    _parse_swagit_transcript_download,
)

from aiohttp_mock import FakeResponse, mock_session

# No fixture-based tests existed for this adapter before this file (see
# BACKLOG_DONE.md's "Not yet covered" note) -- scoped here to the new
# caption-file fallback logic only (Swagit previously only ever tried
# #transcript-fragments, a DOM mechanism, never a caption *file*).
# Synthetic HTML, not a live fixture -- no real Swagit meeting has ever
# been observed with a caption file at all (see BACKLOG.md).

PAGE_URL = "https://example.new.swagit.com/videos/1"

BASE_HTML = (
    "<html><head><title>Jul 21, 2026 Town Council Regular Meeting - Example, CA</title></head>"
    "<body>"
    '<script>var playlist = [{{"file": "https://archive-stream.granicus.com/x/playlist.m3u8"}}];</script>'
    "{captions_tag}"
    "</body></html>"
)


async def test_resolve_falls_back_to_caption_file_when_no_transcript_fragments():
    html = BASE_HTML.format(
        captions_tag='<a href="https://example.new.swagit.com/captions.sbv">CC</a>'
    )
    sbv_content = "0:00:01.000,0:00:02.000\nHello there."

    routes = {
        PAGE_URL: FakeResponse(status=200, text=html, url=PAGE_URL),
        "https://example.new.swagit.com/captions.sbv": FakeResponse(
            status=200, text=sbv_content
        ),
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
        "<html><head><title>Jan 13, 2026 City Council - Example, CA</title></head><body>"
        '<script>var playlist = [{"file": "https://archive-stream.granicus.com/x/playlist.m3u8"}];</script>'
        f'<div id="transcript-fragments">{fragments}</div>'
        "</body></html>"
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


async def test_resolve_falls_back_to_extraction_chain_when_title_has_no_city_state_shape():
    # Real gap this session's audit found (2026-08-15, "Swagit
    # blank-jurisdiction gap" in BACKLOG.md): _extract_metadata() only
    # ever sets jurisdiction from a "... - City, ST"-shaped <title>. A
    # school-district/authority-style title with no such shape used to
    # leave jurisdiction blank even when the page body plainly names a
    # real city -- now the shared chain (jurisdiction_enrich.
    # extract_jurisdiction_chain) gets a shot at it.
    url = "https://hercules.new.swagit.com/videos/1"
    html = (
        "<html><head><title>Special Meeting</title></head><body>"
        '<script>var playlist = [{"file": "https://archive-stream.granicus.com/x/playlist.m3u8"}];</script>'
        "<p>Notice of a special meeting of the City of Hercules. XIV. PUBLIC COMMUNICATIONS XV.</p>"
        "</body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await SwagitAssetFinder().resolve(url)

    assert result.title == "Special Meeting"
    assert result.jurisdiction == "City of Hercules, CA"


async def test_resolve_falls_back_to_validated_subdomain_when_body_has_no_city_phrase():
    # No "City/County/Town of" phrase anywhere on the page and no
    # ", ST"-shaped <title> -- only the validated-subdomain tier can find
    # anything here. Galesburg is nationally ambiguous (IL/KS/MI/ND all
    # have a real Galesburg), so this also confirms the chain doesn't
    # fabricate a state it can't confirm.
    url = "https://galesburg.new.swagit.com/videos/1"
    html = (
        "<html><head><title>Regular Meeting</title></head><body>"
        '<script>var playlist = [{"file": "https://archive-stream.granicus.com/x/playlist.m3u8"}];</script>'
        "</body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await SwagitAssetFinder().resolve(url)

    assert result.jurisdiction == "Galesburg"


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
    assert (
        " ".join(g.text for g in grouped) == "3, 2, 1. GOOD EVENING AND HAPPY NEW YEAR"
    )
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


async def test_resolve_normalizes_all_caps_transcript_fragments():
    # Real bug (2026-08-08): the same Dublin, CA meeting's
    # #transcript-fragments text is genuinely ALL CAPS at the source
    # ("GOOD EVENING AND HAPPY NEW YEAR..."), which reads as shouting once
    # grouped into real lines. Reuses vtt_parser.normalize_shouting_caption
    # (already used by Granicus's VTT parsing for the identical real
    # problem on San Francisco's captions) rather than a second casing
    # standard -- pins that it actually gets called for this DOM path too.
    words = (
        "GOOD EVENING AND HAPPY NEW YEAR TO EVERYONE TODAY IS TUESDAY "
        "JANUARY THIRTEENTH WE WILL NOW CALL THIS REGULAR MEETING TO "
        "ORDER AND BEGIN WITH THE PLEDGE OF ALLEGIANCE TO THE FLAG"
    ).split()
    fragments = "".join(f'<a data-ts="{i}">{w}</a>' for i, w in enumerate(words))
    html = (
        "<html><head><title>Jan 13, 2026 City Council - Example, CA</title></head><body>"
        '<script>var playlist = [{"file": "https://archive-stream.granicus.com/x/playlist.m3u8"}];</script>'
        f'<div id="transcript-fragments">{fragments}</div>'
        "</body></html>"
    )

    routes = {PAGE_URL: FakeResponse(status=200, text=html, url=PAGE_URL)}

    with mock_session(routes):
        result = await SwagitAssetFinder().resolve(PAGE_URL)

    full_text = " ".join(s.text for s in result.segments)
    assert full_text != full_text.upper(), (
        "transcript should no longer be all-uppercase"
    )
    assert "good" in full_text.lower()  # content preserved, just re-cased


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


def test_extract_metadata_plain_title():
    soup = BeautifulSoup(
        "<html><head><title>Jul 28, 2026 Regular Meetings - League City, TX</title></head></html>",
        "html.parser",
    )
    title, date, jurisdiction = SwagitAssetFinder._extract_metadata(soup)
    assert title == "Jul 28, 2026 Regular Meetings"
    assert date == "2026-07-28"
    assert jurisdiction == "League City, TX"


def test_extract_metadata_strips_a_revised_marker_from_jurisdiction():
    # Real bug found live 2026-08-13 (longbeachca.new.swagit.com): a lazy
    # title-part match let a "- Revised -" marker's own text get swallowed
    # into the jurisdiction group, since it has no comma to stop the
    # match early -- resolved to "Revised - Long Beach, CA" instead of
    # "Long Beach, CA".
    soup = BeautifulSoup(
        "<html><head><title>Aug 04, 2026 City Council Special Meeting - Revised - Long Beach, CA</title></head></html>",
        "html.parser",
    )
    title, date, jurisdiction = SwagitAssetFinder._extract_metadata(soup)
    assert title == "Aug 04, 2026 City Council Special Meeting - Revised"
    assert jurisdiction == "Long Beach, CA"


# Real bug found live 2026-08-18: pasting a Swagit `/videos/{id}/transcript`
# URL (a real, purpose-built transcript download distinct from the
# `/videos/{id}` page -- see swagit.py's class docstring and
# `_parse_swagit_transcript_download`) into this app resolved to "no video
# at all", since that endpoint is a plain-text file with no video markup or
# #transcript-fragments DOM for the old code to find. Confirmed live against
# three real customers (huberheightsoh clip 267352, allentx clip 189248,
# amarillotx clip 317100) that this endpoint is `Content-Type: text/plain`
# with `Content-Disposition: attachment`, not another HTML page.

# Real transcript text, fetched live 2026-08-18 from
# http://huberheightsoh.new.swagit.com/videos/267352/transcript
# (verbatim, not fabricated or trimmed -- the whole real download is short).
REAL_HUBER_TRANSCRIPT_DOWNLOAD_TEXT = """\
* This transcript was created by voice-to-text technology. The transcript has not been edited for errors or omissions, it is for reference only and is not the official minutes of the meeting.
          OKAY, WE READY?
          [00:00:01]
MARK, LIKE THOSE OLD WET WIPES THAT YOU FOUND OUT THE ROOM.
          GOOD EVENING.
          AND THIS IS THE CITY HEBREW HEIGHTS CITY COUNCIL WORK SESSION DATED JULY 19TH, 2023.
          WE'RE GETTING STARTED AT 5 31.
          UH, THIS MEETING IS OFFICIALLY
          [1. Call Meeting To Order/Roll Call]
CALLED TO ORDER.
          SO TONY, WOULD YOU CALL THE ROLE PLEASE? MR. SHAW? HERE.
          MS. BAKER? HERE.
* This transcript was created by voice-to-text technology. The transcript has not been edited for errors or omissions, it is for reference only and is not the official minutes of the meeting.
"""


def test_parse_swagit_transcript_download_real_huber_example():
    segments, notes = _parse_swagit_transcript_download(
        REAL_HUBER_TRANSCRIPT_DOWNLOAD_TEXT
    )

    # Text before the first [HH:MM:SS] anchor stays at 0.0.
    assert segments[0].start == 0.0
    assert segments[0].text == "OKAY, WE READY?"
    # The [00:00:01] anchor becomes the next segment's real start second --
    # the inline "[1. Call Meeting To Order/Roll Call]" agenda marker is
    # skipped (not duplicated from the DOM-derived agenda_items), but its
    # surrounding prose lines are joined into one block.
    assert segments[1].start == 1.0
    assert "MARK, LIKE THOSE OLD WET WIPES" in segments[1].text
    assert "CALLED TO ORDER." in segments[1].text
    assert "[1. Call Meeting To Order" not in segments[1].text
    # The repeated disclaimer line (top and bottom, identical text) is
    # deduped into a single source note, not treated as transcript prose.
    assert notes == [
        "This transcript was created by voice-to-text technology. The "
        "transcript has not been edited for errors or omissions, it is "
        "for reference only and is not the official minutes of the meeting."
    ]
    assert all("This transcript was created" not in s.text for s in segments)


TRANSCRIPT_VARIANT_URL = "https://example.new.swagit.com/videos/1/transcript"
TRANSCRIPT_VARIANT_BASE_URL = "https://example.new.swagit.com/videos/1"

TRANSCRIPT_VARIANT_BASE_HTML = (
    "<html><head><title>Jul 21, 2026 Town Council Regular Meeting - Example, CA</title></head>"
    "<body>"
    '<script>var playlist = [{"file": "https://archive-stream.granicus.com/x/playlist.m3u8"}];</script>'
    '<a href="/videos/1/transcript">Transcript</a>'
    "</body></html>"
)

SHORT_REAL_TRANSCRIPT_TEXT = "          [00:00:01]\nHELLO AND WELCOME TO THE MEETING.\n"


async def test_resolve_finds_video_when_given_the_transcript_url_directly():
    # This is the exact real-world shape of the reported bug: a user
    # pastes the `/transcript` URL, not the base `/videos/{id}` page.
    routes = {
        TRANSCRIPT_VARIANT_BASE_URL: FakeResponse(
            status=200,
            text=TRANSCRIPT_VARIANT_BASE_HTML,
            url=TRANSCRIPT_VARIANT_BASE_URL,
        ),
        TRANSCRIPT_VARIANT_URL: FakeResponse(
            status=200, text=SHORT_REAL_TRANSCRIPT_TEXT, url=TRANSCRIPT_VARIANT_URL
        ),
    }

    with mock_session(routes):
        result = await SwagitAssetFinder().resolve(TRANSCRIPT_VARIANT_URL)

    # Before the fix this was None with "No playable video found on this
    # page." -- the `/transcript` URL was fetched directly as if it were
    # the HTML video page.
    assert result.video_url == "https://archive-stream.granicus.com/x/playlist.m3u8"
    assert not result.video_warnings
    assert [s.text for s in result.segments] == ["HELLO AND WELCOME TO THE MEETING."]
    # The URL the caller actually pasted is preserved as source_url.
    assert result.source_url == TRANSCRIPT_VARIANT_URL


async def test_resolve_fetches_transcript_download_from_base_video_page_link():
    # The more common real shape: the caller pastes the ordinary
    # `/videos/{id}` page, which itself links to the transcript download.
    routes = {
        TRANSCRIPT_VARIANT_BASE_URL: FakeResponse(
            status=200,
            text=TRANSCRIPT_VARIANT_BASE_HTML,
            url=TRANSCRIPT_VARIANT_BASE_URL,
        ),
        TRANSCRIPT_VARIANT_URL: FakeResponse(
            status=200, text=SHORT_REAL_TRANSCRIPT_TEXT, url=TRANSCRIPT_VARIANT_URL
        ),
    }

    with mock_session(routes):
        result = await SwagitAssetFinder().resolve(TRANSCRIPT_VARIANT_BASE_URL)

    assert result.video_url == "https://archive-stream.granicus.com/x/playlist.m3u8"
    assert [s.text for s in result.segments] == ["HELLO AND WELCOME TO THE MEETING."]


async def test_resolve_does_not_mistake_the_in_page_anchor_for_a_real_transcript_link():
    # Real distinction confirmed live 2026-08-18: every Swagit page has an
    # unrelated `href="#transcript"` in-page anchor even when no generated
    # transcript exists for that meeting (confirmed on a real
    # collincountytx meeting) -- only a real `href="/videos/{id}/transcript"`
    # download link means one exists. This must not be treated as one.
    html = (
        "<html><head><title>Jul 21, 2026 Town Council Regular Meeting - Example, CA</title></head>"
        "<body>"
        '<script>var playlist = [{"file": "https://archive-stream.granicus.com/x/playlist.m3u8"}];</script>'
        '<a href="#transcript">Transcript</a>'
        "</body></html>"
    )
    routes = {PAGE_URL: FakeResponse(status=200, text=html, url=PAGE_URL)}

    with mock_session(routes):
        result = await SwagitAssetFinder().resolve(PAGE_URL)

    assert result.segments == []
    assert any("no transcript found" in w.lower() for w in result.transcript_warnings)


def test_extract_metadata_strips_a_closed_session_marker_from_jurisdiction():
    soup = BeautifulSoup(
        "<html><head><title>Aug 04, 2026 City Council Special Meeting - Closed Session - Long Beach, CA</title></head></html>",
        "html.parser",
    )
    title, date, jurisdiction = SwagitAssetFinder._extract_metadata(soup)
    assert jurisdiction == "Long Beach, CA"


# Real, confirmed-live bug (BACKLOG.md's "[HIGH PRIORITY] Swagit adapter
# serves a wrong, bogus video for /events/{id} URLs" entry, root-caused and
# fixed 2026-08-21). Fixture content below is a trimmed, verbatim excerpt
# of the real `<script>` block independently `curl`-fetched live from all
# 5 real tenants confirmed to match this exact pattern: petalumaca.new.
# swagit.com/events/43607 (Jan 1, 2026 "Airport Commission Meeting -
# Canceled"), norwalkca.new.swagit.com/events/44163 (Jan 14, 2026
# "Planning Commission Special Meeting"), westjordan.new.swagit.com/
# events/43963 (Jan 5, 2026 "Oath of Office Ceremony"), cambridgema.v3.
# swagit.com/events/43940 (Jan 12, 2026 "Regular City Council Meeting"),
# and solvangca.v3.swagit.com/events/43961 (Jan 5, 2026 "Planning
# Commission Regular Meeting") -- the last two only matched via PrimeGov's
# API before this session, independently curl-verified live here too.
# Every one of the 5 embeds this exact byte-identical pair of
# `player.src(...)` lines: a dead, JS-commented-out reference to a generic
# Swagit demo/QA recording (tenant "abilenetx"), immediately followed by
# the real (uncommented) line pointing at this tenant's own live-channel
# stream. `https://edge-f.swagit.com/live/petalumaca/live-1-a/playlist.m3u8`
# (and each other tenant's equivalent) was independently curl-verified
# live to 404 -- confirming it's a live-broadcast-only URL, dead for any
# meeting that already happened, not a second real archived-video
# candidate. Real chapter markers (`a.playerControl[data-ts][data-title]`)
# are present on this page template too (confirmed on the real Norwalk
# page, 28 of them) but every one has a blank `data-ts=""` -- there's no
# recording to offset into -- so the existing `if not ts: continue` guard
# already (and correctly) excludes them from agenda_items, exercised below
# too since it was a previously-unconfirmed real content shape.
REAL_EVENTS_TEMPLATE_SCRIPT = """
      player.on('error', function() {
        if (player.error().code == 4) {
          // $(".embed-responsive-item").html('<div class="text"><p>Our live stream is not currently active. Please check back during a regularly scheduled meeting or view our on-demand content for previously run meetings.</p></div>');
        }
      });
      // player.src({type: "application/x-mpegURL", src: "https://stream.us-central1-b.swagit.com/on-demand/_definst_/mp4:vault01/abilenetx/59d7e173-684b-4da4-9433-50d6e22555f1.mp4/playlist.m3u8"});
      player.src({type: "application/x-mpegURL", src: "https://edge-f.swagit.com/live/petalumaca/live-1-a/playlist.m3u8"});
"""

EVENTS_URL = "https://petalumaca.new.swagit.com/events/43607"

EVENTS_TEMPLATE_HTML = (
    "<html><head><title>Jan 01, 2026 Airport Commission Meeting - Canceled - "
    "Petaluma, CA</title></head><body>"
    f"<script>{REAL_EVENTS_TEMPLATE_SCRIPT}</script>"
    '<a class="playerControl" data-id="1" data-ts="" data-end-ts="16:00" '
    'data-title="CALL TO ORDER" href="/play/43607/">Call to Order</a>'
    "</body></html>"
)


async def test_resolve_declines_the_bogus_events_template_placeholder_video():
    routes = {
        EVENTS_URL: FakeResponse(status=200, text=EVENTS_TEMPLATE_HTML, url=EVENTS_URL)
    }

    with mock_session(routes):
        result = await SwagitAssetFinder().resolve(EVENTS_URL)

    # Before the fix, document-order scanning picked the dead
    # JS-commented "abilenetx" placeholder as video_url with NO warning at
    # all -- the worst failure mode (a wrong, plausible-looking video),
    # not just a missing one.
    assert result.video_url is None
    assert not any("abilenetx" in (w or "") for w in result.video_warnings)
    assert any(
        "live-event page" in w and "/events/" in w for w in result.video_warnings
    )
    # Real chapter markers exist on this page template but all carry a
    # blank data-ts (no recording to offset into) -- correctly excluded,
    # not fabricated with a fake 0.0 offset.
    assert result.agenda_items == []
    # Metadata extraction (title/date/jurisdiction) is unaffected -- the
    # <title> tag follows the same shape as /videos/{id} pages.
    assert result.jurisdiction == "Petaluma, CA"
    assert result.date == "2026-01-01"


def test_is_swagit_events_template_dead_candidate_matches_real_placeholder_and_live_urls():
    # The exact bogus URL confirmed byte-identical across all 5 real
    # /events/{id} tenants.
    assert _is_swagit_events_template_dead_candidate(
        "https://stream.us-central1-b.swagit.com/on-demand/_definst_/"
        "mp4:vault01/abilenetx/59d7e173-684b-4da4-9433-50d6e22555f1.mp4/"
        "playlist.m3u8"
    )
    # Real per-tenant live-stream URLs, both path shapes confirmed live
    # (petalumaca/westjordan/solvangca use "/live/", norwalkca/cambridgema
    # use "/live-edge/").
    assert _is_swagit_events_template_dead_candidate(
        "https://edge-f.swagit.com/live/petalumaca/live-1-a/playlist.m3u8"
    )
    assert _is_swagit_events_template_dead_candidate(
        "https://edge-f.swagit.com/live-edge/norwalkca/live-1-a/playlist.m3u8"
    )
    # A real archived /videos/{id} page's genuine video URL must not be
    # caught by this filter.
    assert not _is_swagit_events_template_dead_candidate(
        "https://archive-stream.granicus.com/x/playlist.m3u8"
    )
