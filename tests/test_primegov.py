import json
from datetime import datetime

import yt_dlp

from app.platforms.base import register
from app.platforms.granicus import GranicusAssetFinder
from app.platforms.primegov import PrimeGovAssetFinder
from app.platforms.swagit import SwagitAssetFinder
from app.platforms.youtube import YouTubeAssetFinder

from aiohttp_mock import FakeResponse, mock_session


def _register_delegation_targets():
    # resolve() now also delegates to Swagit/Granicus (see the new
    # tenant-API fallback tests below) -- resolve_via_platform-style
    # lookups go through base.py's registry, same pattern test_legistar.py
    # and test_civicplus.py already use for their own Granicus delegation
    # tests.
    register(SwagitAssetFinder())
    register(GranicusAssetFinder())


# No fixture-based tests existed for this adapter before this file (see
# BACKLOG.md's "zero test coverage" note). The `var videoUrl = "..."`
# extraction pattern and the real video id below come from the actual
# Oklahoma City sample resolved live 2026-08-08 -- see BACKLOG.md's
# PrimeGov date/jurisdiction entry -- and the Thousand Oaks video id
# comes from the earlier YouTube-removed/blocked bug entry in
# BACKLOG_DONE.md. YouTubeAssetFinder._extract_info is monkeypatched the
# same way tests/test_youtube.py does it, so these tests exercise
# PrimeGovAssetFinder's own page-scraping/delegation logic without making
# a real yt-dlp call.

PAGE_URL = "https://okc.primegov.com/Portal/Meeting?meetingTemplateId=68482"
REAL_VIDEO_ID = "uNDJRR3ywVo"

# Trimmed real page shape: the actual OKC page is ~790KB, but the only
# part PrimeGovAssetFinder reads is this one <script> variable, right
# next to the iframe_api script tag per the adapter's own docstring.
PAGE_HTML_WITH_VIDEO = f"""
<html><head><title>Meeting</title></head>
<body>
<script src="https://www.youtube.com/iframe_api"></script>
<script>
var videoUrl = "{REAL_VIDEO_ID}";
</script>
</body></html>
"""

PAGE_HTML_NO_VIDEO = (
    "<html><head><title>Meeting</title></head><body>No player here.</body></html>"
)

# Trimmed real page shape for the agenda header, confirmed live 2026-08-09
# against both meetingTemplateId pages -- see BACKLOG_DONE.md's PrimeGov
# date/jurisdiction entry. Real bug this fixes: YouTube's own upload_date
# was one day late for both samples (uploaded the day after the meeting),
# and the uploader channel name gave no usable jurisdiction at all for
# Thousand Oaks ("CTO Meetings").
OKC_HEADER_HTML = """
<table><tbody>
<tr><td><span><strong>THE CITY OF OKLAHOMA CITY</strong></span></td></tr>
<tr><td><span><strong>FORMAL AGENDA</strong></span></td></tr>
<tr><td><span><strong>CITY COUNCIL</strong></span></td></tr>
<tr><td><span><strong>August 4, 2026</strong></span></td></tr>
</tbody></table>
"""

TOAKS_HEADER_HTML = """
<p>POSTED 11:15 AM, 7/3/2026, to move Item No. 15A to Consent Calendar</p>
<span><b>City Council</b><br>
<b>REGULAR MEETING </b></span>
<span><strong>Tuesday, July 07, 2026</strong><br>
<b>Andrew P. Fox City Council Chambers<br>
2100 E. Thousand Oaks Blvd., Thousand Oaks, CA 91362</b></span>
<p>It is the mission of the City of Thousand Oaks that all employees are
treated with respect and dignity.</p>
"""

PAGE_HTML_OKC_FULL = f"""
<html><head><title>Meeting</title></head>
<body>
{OKC_HEADER_HTML}
<script src="https://www.youtube.com/iframe_api"></script>
<script>
var videoUrl = "{REAL_VIDEO_ID}";
</script>
</body></html>
"""

TOAKS_VIDEO_ID = "VNMQYICdQvs"

PAGE_HTML_TOAKS_FULL = f"""
<html><head><title>Meeting</title></head>
<body>
{TOAKS_HEADER_HTML}
<script src="https://www.youtube.com/iframe_api"></script>
<script>
var videoUrl = "{TOAKS_VIDEO_ID}";
</script>
</body></html>
"""


# Real page shape, fetched live 2026-08-21
# (bedfordoh.primegov.com/Portal/Meeting?meetingTemplateId=518) --
# BACKLOG.md's PrimeGov/Bedford-Cuyahoga entry: confirmed the letterhead
# is a 3-column table whose middle column carries "Bedford City Council"
# (row 1) directly above "County of Cuyahoga" (row 2), identical styling
# (color:#999999, bold, Times New Roman 10pt) for both. Trimmed of the
# outer <html>/<head> wrapper and the org logo <img>, kept verbatim
# otherwise (including the real address line, "165 Center Road Bedford,
# OH 44146", used elsewhere by the ZIP-address state-fill fallback).
BEDFORD_HEADER_HTML = """
<table style="width:100%">
	<tbody>
		<tr>
			<th style="width:33%">&nbsp;</th>
			<th style="width:33%">&nbsp;</th>
			<th style="width:33%">&nbsp;</th>
		</tr>
		<tr>
			<td><span style="color:#999999;"><strong><span style="font-size:10pt;"><span style="font-family:Times New Roman,Times,serif;">REGULAR MEETING</span></span></strong></span></td>
			<td style="text-align:center"><span style="color:#999999;"><strong><span style="font-family:Times New Roman,Times,serif;"><span style="font-size:10pt;">Bedford City Council</span></span></strong></span></td>
			<td style="text-align:right"><span style="color:#999999;"><span style="font-family:Times New Roman,Times,serif;"><span style="font-size:10pt;"><strong>DATE:&nbsp;December 06, 2021</strong></span></span></span></td>
		</tr>
		<tr>
			<td colspan="3" style="text-align:center"><span style="color:#999999;"><strong><span style="font-size:10pt;"><span style="font-family:Times New Roman,Times,serif;">State of Ohio</span></span></strong></span></td>
		</tr>
		<tr>
			<td><span style="color:#999999;"><strong><span style="font-size:10pt;"><span style="font-family:Times New Roman,Times,serif;">Agenda</span></span></strong></span></td>
			<td style="text-align:center;"><span style="color:#999999;"><strong><span style="font-size:10pt;"><span style="font-family:Times New Roman,Times,serif;">County of Cuyahoga</span></span></strong></span></td>
			<td style="text-align:right;"><span style="color:#999999;"><strong><span style="font-size:10pt;"><span style="font-family:Times New Roman,Times,serif;">TIME: 8:00 PM</span></span></strong></span></td>
		</tr>
		<tr>
			<td colspan="3" style="text-align:center"><span style="color:#999999;"><strong><span style="font-size:10pt;"><span style="font-family:Times New Roman,Times,serif;">165 Center Road Bedford, OH 44146</span></span></strong></span></td>
		</tr>
	</tbody>
</table>
"""

BEDFORD_URL = "https://bedfordoh.primegov.com/Portal/Meeting?meetingTemplateId=518"


def _fake_extract_info(video_id):
    return {
        "title": "Oklahoma City Council Meeting - August 4, 2026",
        "uploader": "cityofokc",
        "upload_date": "20260805",
    }


async def test_resolve_extracts_video_id_and_delegates_to_youtube(monkeypatch):
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    routes = {
        PAGE_URL: FakeResponse(status=200, text=PAGE_HTML_WITH_VIDEO, url=PAGE_URL)
    }

    with mock_session(routes):
        result = await PrimeGovAssetFinder().resolve(PAGE_URL)

    assert (
        result.platform == "youtube"
    )  # delegated finder's own platform name, unchanged
    assert result.video_url == f"https://www.youtube.com/embed/{REAL_VIDEO_ID}"
    assert result.external_id == f"youtube:{REAL_VIDEO_ID}"
    assert result.title == "Oklahoma City Council Meeting - August 4, 2026"


async def test_resolve_keeps_original_primegov_url_as_source_url(monkeypatch):
    # The documented quirk (PrimeGovAssetFinder's own class docstring):
    # unlike Legistar/CivicPlus's delegation, source_url stays the
    # original PrimeGov page, not the delegated platform's URL, so "View
    # original source" keeps pointing back to the real PrimeGov meeting
    # page rather than a bare YouTube link.
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    routes = {
        PAGE_URL: FakeResponse(status=200, text=PAGE_HTML_WITH_VIDEO, url=PAGE_URL)
    }

    with mock_session(routes):
        result = await PrimeGovAssetFinder().resolve(PAGE_URL)

    assert result.source_url == PAGE_URL


async def test_resolve_returns_no_video_warning_when_page_has_no_player():
    # Confirmed live: an agenda-only PrimeGov page (meetingTemplateId with
    # no matching recording) has no videoUrl variable at all -- see the
    # class docstring's LA City sample note.
    routes = {PAGE_URL: FakeResponse(status=200, text=PAGE_HTML_NO_VIDEO, url=PAGE_URL)}

    with mock_session(routes):
        result = await PrimeGovAssetFinder().resolve(PAGE_URL)

    assert result.platform == "primegov"
    assert result.video_url is None
    assert result.segments == []
    assert any("no video found" in w.lower() for w in result.video_warnings)


def test_extract_video_id_matches_real_page_variable_shape():
    assert PrimeGovAssetFinder._extract_video_id(PAGE_HTML_WITH_VIDEO) == REAL_VIDEO_ID


def test_extract_video_id_returns_none_when_absent():
    assert PrimeGovAssetFinder._extract_video_id(PAGE_HTML_NO_VIDEO) is None


def test_extract_date_reads_all_caps_okc_header():
    assert PrimeGovAssetFinder._extract_date(OKC_HEADER_HTML) == "2026-08-04"


def test_extract_date_reads_weekday_prefixed_toaks_header():
    # The "POSTED 11:15 AM, 7/3/2026" line above the real header uses
    # numeric slash format, not a full month name, so it doesn't false-match
    # ahead of the real "Tuesday, July 07, 2026" meeting date.
    assert PrimeGovAssetFinder._extract_date(TOAKS_HEADER_HTML) == "2026-07-07"


def test_extract_date_returns_none_without_a_month_name_date():
    assert PrimeGovAssetFinder._extract_date(PAGE_HTML_NO_VIDEO) is None


def test_extract_jurisdiction_normalizes_all_caps_header():
    # "Oklahoma City" is a real, nationally-unique incorporated place --
    # confirmed via app/utils/jurisdiction_data, so this now also confirms
    # the shared jurisdiction_enrich wiring is reached, not just the
    # header-parsing regex.
    assert (
        PrimeGovAssetFinder._extract_jurisdiction(OKC_HEADER_HTML, PAGE_URL)
        == "City of Oklahoma City, OK"
    )


def test_extract_jurisdiction_stops_at_lowercase_word_in_flowing_prose():
    # Real bug this guards against: a naive "city of X" regex run against
    # Thousand Oaks's real page grabbed "Thousand Oaks that all employees
    # are to be treated with respect and dignity" from unrelated mission-
    # statement text elsewhere on the page, since nothing but a lowercase
    # word follows the real city name there.
    prose = "It is the mission of the City of Thousand Oaks that all employees are treated well."
    toaks_url = "https://toaks.primegov.com/Portal/Meeting?meetingTemplateId=9446"
    assert (
        PrimeGovAssetFinder._extract_jurisdiction(prose, toaks_url)
        == "City of Thousand Oaks, CA"
    )


def test_extract_jurisdiction_reads_toaks_header():
    toaks_url = "https://toaks.primegov.com/Portal/Meeting?meetingTemplateId=9446"
    assert (
        PrimeGovAssetFinder._extract_jurisdiction(TOAKS_HEADER_HTML, toaks_url)
        == "City of Thousand Oaks, CA"
    )


def test_extract_jurisdiction_returns_none_when_absent():
    assert (
        PrimeGovAssetFinder._extract_jurisdiction(PAGE_HTML_NO_VIDEO, PAGE_URL) is None
    )


def test_extract_jurisdiction_still_matches_agenda_body_text_when_header_does_not_match():
    # Real, currently-STILL-OPEN gap -- see BACKLOG.md. A same-day window-
    # capping "fix" for exactly this shape (SLC's real header, "SALT LAKE
    # CITY COUNCIL", isn't "City/County/Town of X"-shaped, so an unrelated
    # agenda item mentioning a different city can still win) was reverted
    # after live-checking all three real known examples: the window that
    # would avoid this false positive also broke both of PrimeGov's
    # original, previously-correctly-resolving real cities (OKC and
    # Thousand Oaks both have their own real, correct match sitting
    # thousands of characters into the real page -- nowhere near "early"),
    # a worse regression than reopening this one. This test documents the
    # current, honest (if imperfect) behavior, not a fix -- note
    # "Holladay" is itself a real, nationally-unique place name (per
    # app/utils/jurisdiction_data), so the shared enrichment step now
    # confidently appends its real state (UT) to this wrong city name,
    # which if anything makes the underlying extraction bug read as more
    # authoritative than it did before, not less -- worth keeping in mind
    # for whoever picks up a real fix for the extraction itself.
    html = (
        "<html><body>"
        "<strong>SALT LAKE CITY COUNCIL</strong><br><strong>AGENDA</strong>"
        "<p>Item 12: Central Wasatch Commission - adding the City of Holladay.</p>"
        "</body></html>"
    )
    result = PrimeGovAssetFinder._extract_jurisdiction(
        html, "https://slc.primegov.com/Portal/Meeting?meetingTemplateId=3853"
    )
    assert result == "City of Holladay, UT"


def test_extract_jurisdiction_bedford_council_header_beats_adjacent_county():
    # Real bug fixed 2026-08-21 (4th confirmed PrimeGov jurisdiction-
    # extraction false positive, after OKC/Thousand Oaks/SLC -- see
    # BACKLOG.md/BACKLOG_DONE.md): the real Bedford, OH page's letterhead
    # carries "Bedford City Council" and "County of Cuyahoga" in adjacent,
    # identically-styled cells of the same 3-column table.
    # _JURISDICTION_RE alone only ever matches "County of Cuyahoga" (no
    # "of" precedes "Bedford"), so it used to win via unscoped first-match
    # -- the new `_COUNCIL_HEADER_RE` tier (tried first) now matches
    # "Bedford City Council" instead, and Cuyahoga is never reached.
    # State comes from the real address line via the existing ZIP-address
    # fallback ("165 Center Road Bedford, OH 44146"), not a domain
    # registry entry (bedfordoh.primegov.com isn't registered).
    assert (
        PrimeGovAssetFinder._extract_jurisdiction(BEDFORD_HEADER_HTML, BEDFORD_URL)
        == "City of Bedford, OH"
    )


async def test_resolve_bedford_real_page_beats_adjacent_county(monkeypatch):
    # End-to-end version of the fixture test above, through the real
    # resolve() path (video id extraction + jurisdiction override), same
    # style as test_resolve_overrides_wrong_youtube_date_and_jurisdiction_with_page_header
    # below.
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    html = f"""
<html><head><title>Meeting</title></head>
<body>
{BEDFORD_HEADER_HTML}
<script src="https://www.youtube.com/iframe_api"></script>
<script>
var videoUrl = "{REAL_VIDEO_ID}";
</script>
</body></html>
"""
    routes = {BEDFORD_URL: FakeResponse(status=200, text=html, url=BEDFORD_URL)}

    with mock_session(routes):
        result = await PrimeGovAssetFinder().resolve(BEDFORD_URL)

    assert result.jurisdiction == "City of Bedford, OH"


def test_council_header_re_does_not_match_okc_all_caps_header():
    # Regression guard: OKC's real header has "CITY COUNCIL" as its own
    # table cell, all-caps, with no name in the same cell -- confirmed via
    # the real page fetched live 2026-08-21
    # (okc.primegov.com/Portal/Meeting?meetingTemplateId=68482). The new
    # tier is deliberately case-sensitive (only matches mixed-case "City/
    # Town/Village Council", the real Bedford/Thousand Oaks shape) and
    # requires the name to sit in the SAME unbroken run of text as
    # "Council" -- neither holds for OKC's all-caps, separately-celled
    # header, so this must still resolve via the old _JURISDICTION_RE tier
    # exactly as before.
    assert (
        PrimeGovAssetFinder._extract_jurisdiction(OKC_HEADER_HTML, PAGE_URL)
        == "City of Oklahoma City, OK"
    )


def test_council_header_re_does_not_match_bare_council_with_no_preceding_name():
    # Regression guard: Thousand Oaks's real header has bare "City
    # Council" (no name at all before it -- confirmed via the real page,
    # toaks.primegov.com/Portal/Meeting?meetingTemplateId=9446) at the very
    # start of its own <span>. The new tier requires 1-3 capitalized words
    # before "City/Town/Village Council", so this must not match here --
    # confirming the real jurisdiction still comes from the (also real)
    # "City of Thousand Oaks" mission-statement mention further down the
    # page, same as before this fix.
    assert (
        PrimeGovAssetFinder._extract_jurisdiction(TOAKS_HEADER_HTML, PAGE_URL)
        == "City of Thousand Oaks, CA"
    )


def test_council_header_re_discards_an_unvalidated_body_mention():
    # A stray "X City Council" mention that ISN'T a real place must not be
    # stored -- e.g. a made-up/placeholder name in agenda body prose.
    # Confirms the validate-or-discard step in
    # _extract_council_header_jurisdiction() actually rejects a bad match
    # rather than blindly trusting the regex, the same protection
    # `extract_jurisdiction_chain()` already relies on for its own
    # generic-regex tiers (see jurisdiction_enrich.py).
    html = (
        "<html><body><p>Please direct correspondence to the Notarealplace "
        "City Council office.</p></body></html>"
    )
    assert PrimeGovAssetFinder._extract_jurisdiction(html, PAGE_URL) is None


def test_council_header_re_keeps_city_as_part_of_the_real_name():
    # Direct unit test of the disambiguation this tier depends on:
    # "Oklahoma City Council" must resolve to "Oklahoma City" (the real,
    # correct proper name), not "Oklahoma" (which would coincidentally
    # collide with a real but totally unrelated place, "Oklahoma borough,
    # PA" -- see jurisdiction_enrich.is_literal_known_place()'s own
    # docstring for that historical bug). Exercised here directly against
    # a bare "Name City Council" shape with no other page structure, so
    # this is really a test of the ambiguity-resolution logic itself, not
    # just OKC's specific real header (already covered above).
    html = "<html><body><p>Oklahoma City Council Regular Session</p></body></html>"
    assert (
        PrimeGovAssetFinder._extract_jurisdiction(html, PAGE_URL)
        == "City of Oklahoma City, OK"
    )


def test_extract_jurisdiction_strips_script_and_style_boilerplate():
    # Boilerplate stripping itself is still real and kept (a <script>
    # block's own text could otherwise be searched) -- just no longer
    # paired with a length cap, see the module-level comment on why.
    boilerplate = (
        "<script>" + ("window.sessionStorage.setItem('x', 'y');" * 60) + "</script>"
    )
    html = f"<html><body>{boilerplate}{OKC_HEADER_HTML}</body></html>"
    assert (
        PrimeGovAssetFinder._extract_jurisdiction(html, PAGE_URL)
        == "City of Oklahoma City, OK"
    )


async def test_resolve_overrides_wrong_youtube_date_and_jurisdiction_with_page_header(
    monkeypatch,
):
    # The real bug: YouTube's upload_date was one day late for both real
    # samples (uploaded the day after the meeting), and Thousand Oaks's
    # uploader ("CTO Meetings") carries no usable city name -- the page's
    # own agenda header is correct for both, confirmed live 2026-08-09.
    monkeypatch.setattr(
        YouTubeAssetFinder,
        "_extract_info",
        lambda video_id: {
            "title": "Oklahoma City Council Meeting - August 4, 2026",
            "uploader": "cityofokc",
            "upload_date": "20260805",  # wrong: one day after the real meeting
        },
    )
    routes = {PAGE_URL: FakeResponse(status=200, text=PAGE_HTML_OKC_FULL, url=PAGE_URL)}

    with mock_session(routes):
        result = await PrimeGovAssetFinder().resolve(PAGE_URL)

    assert result.date == "2026-08-04"
    assert result.jurisdiction == "City of Oklahoma City, OK"


async def test_resolve_overrides_uninformative_youtube_uploader(monkeypatch):
    toaks_url = "https://toaks.primegov.com/Portal/Meeting?meetingTemplateId=9446"
    monkeypatch.setattr(
        YouTubeAssetFinder,
        "_extract_info",
        lambda video_id: {
            "title": "Thousand Oaks City Council Meeting - July 7, 2026",
            "uploader": "CTO Meetings",  # real value: no usable city name
            "upload_date": "20260708",  # wrong: one day after the real meeting
        },
    )
    routes = {
        toaks_url: FakeResponse(status=200, text=PAGE_HTML_TOAKS_FULL, url=toaks_url)
    }

    with mock_session(routes):
        result = await PrimeGovAssetFinder().resolve(toaks_url)

    assert result.date == "2026-07-07"
    assert result.jurisdiction == "City of Thousand Oaks, CA"


async def test_resolve_clears_jurisdiction_when_page_has_no_header(monkeypatch):
    # Real bug fixed 2026-08-12, reported by the user on a real
    # slc.primegov.com meeting whose header didn't match _JURISDICTION_RE
    # at all: this used to silently leave YouTube's own `uploader` value
    # in place ("SLC Live Meetings" in that real case) -- a channel name,
    # not a jurisdiction. Now cleared to None instead, an honest "we
    # don't know" rather than a wrong-looking answer. `date` is unaffected
    # -- that field's own fallback-preservation behavior wasn't part of
    # this bug and isn't changed.
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    routes = {
        PAGE_URL: FakeResponse(status=200, text=PAGE_HTML_WITH_VIDEO, url=PAGE_URL)
    }

    with mock_session(routes):
        result = await PrimeGovAssetFinder().resolve(PAGE_URL)

    assert result.date == "2026-08-05"
    assert result.jurisdiction is None


async def test_resolve_uses_known_domain_override_when_page_has_no_header(monkeypatch):
    # Real bug reported live 2026-08-13: on slc.primegov.com specifically,
    # a page with no matching header used to fall all the way through to
    # None (the case above) -- but every real slc.primegov.com meeting is
    # confirmed to actually be Salt Lake City, so this domain now gets a
    # known-domain override instead, applied *before* the unreliable
    # text-based extraction. See jurisdiction_enrich._KNOWN_DOMAINS.
    slc_url = "https://slc.primegov.com/Portal/Meeting?meetingTemplateId=3948"
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    routes = {slc_url: FakeResponse(status=200, text=PAGE_HTML_WITH_VIDEO, url=slc_url)}

    with mock_session(routes):
        result = await PrimeGovAssetFinder().resolve(slc_url)

    assert result.jurisdiction == "City of Salt Lake City, UT"


async def test_resolve_known_domain_override_beats_a_false_positive_body_match(
    monkeypatch,
):
    # The other half of the same bug: a real slc.primegov.com page whose
    # agenda body mentions an unrelated "City of Holladay" used to win
    # over the real header (see
    # test_extract_jurisdiction_still_matches_agenda_body_text_when_header_does_not_match
    # above, which still documents _extract_jurisdiction()'s own raw
    # behavior in isolation) -- but at the resolve() level, the domain
    # override now wins before that text search ever runs.
    slc_url = "https://slc.primegov.com/Portal/Meeting?meetingTemplateId=3853"
    html = (
        PAGE_HTML_WITH_VIDEO
        + "<p>Item 12: Central Wasatch Commission - adding the City of Holladay.</p>"
    )
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    routes = {slc_url: FakeResponse(status=200, text=html, url=slc_url)}

    with mock_session(routes):
        result = await PrimeGovAssetFinder().resolve(slc_url)

    assert result.jurisdiction == "City of Salt Lake City, UT"


def test_extract_title_reads_the_real_inner_title_tag():
    # Real shape confirmed live 2026-08-13 across 3 independent real
    # PrimeGov customers (OKC, Thousand Oaks, a real LA City Council
    # meeting) -- every Portal/Meeting page carries an outer, useless
    # "<title>Meeting</title>" followed by a real one further into the
    # response.
    html = "<html><head><title>Meeting</title></head><body><title>City Council - 8/4/2026 1:30:00 PM</title></body></html>"
    assert (
        PrimeGovAssetFinder._extract_title(html) == "City Council - 8/4/2026 1:30:00 PM"
    )


def test_extract_title_returns_none_when_only_the_generic_title_exists():
    assert PrimeGovAssetFinder._extract_title(PAGE_HTML_WITH_VIDEO) is None


async def test_resolve_backfills_title_from_the_real_inner_title_tag_when_youtube_has_none(
    monkeypatch,
):
    # Real gap found live 2026-08-13 on a real LA City Council meeting:
    # when yt-dlp is blocked (Render's documented IP block, see
    # youtube.py), this page used to come through with no title at all,
    # even though the page has a perfectly good one sitting right there.
    def _raise(video_id):
        raise yt_dlp.utils.DownloadError("Sign in to confirm you're not a bot")

    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _raise)
    html = PAGE_HTML_WITH_VIDEO.replace(
        "<title>Meeting</title>",
        "<title>Meeting</title><title>City Council Meeting - 8/12/2026 5:00:00 PM</title>",
    )
    routes = {PAGE_URL: FakeResponse(status=200, text=html, url=PAGE_URL)}

    with mock_session(routes):
        result = await PrimeGovAssetFinder().resolve(PAGE_URL)

    assert result.title == "City Council Meeting - 8/12/2026 5:00:00 PM"


async def test_resolve_does_not_backfill_title_over_a_real_youtube_title(monkeypatch):
    html = PAGE_HTML_WITH_VIDEO.replace(
        "<title>Meeting</title>",
        "<title>Meeting</title><title>City Council Meeting - 8/12/2026 5:00:00 PM</title>",
    )
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    routes = {PAGE_URL: FakeResponse(status=200, text=html, url=PAGE_URL)}

    with mock_session(routes):
        result = await PrimeGovAssetFinder().resolve(PAGE_URL)

    assert result.title == "Oklahoma City Council Meeting - August 4, 2026"


# --- Tenant-API delegation to Swagit/Granicus (real, confirmed-live gap) ---
#
# Real, confirmed-live gap found 2026-08-19: some PrimeGov tenants'
# meetings have their real video hosted on Swagit or Granicus, not
# YouTube -- the page itself never surfaces this (no `var videoUrl = ...`
# at all), but PrimeGov's own per-tenant JSON API does:
#   GET https://{tenant}.primegov.com/api/v2/PublicPortal/ListArchivedMeetings?year={YYYY}
# returns each archived meeting, and a meeting whose `documentList[].
# templateId` matches this page's own `meetingTemplateId` carries the
# real video location in its own `videoUrl` field. Confirmed live via a
# real `curl` against cambridgema.primegov.com and cross-checked against
# ~/Documents/rtr-business/research/primegov_swagit_granicus_undetected.txt
# (53 real meetings sourced the same way; 47/53 now resolve a real video
# with this fix -- the remaining 6 are either a separate, not-yet-fixed
# Granicus URL-shape gap (`MediaPlayer.php?event_id=...`, distinct from
# the `clip_id`/`/videos/{id}` shapes GranicusAssetFinder already
# recognizes) or genuine source-side issues unrelated to this adapter
# (a stale/blocked Swagit link, a Granicus clip redirecting to its own
# PermissionDenied.php) -- see BACKLOG.md).
#
# The JSON payload shapes below are real, trimmed API responses captured
# live 2026-08-19 (not invented field structures) -- meeting id 428,
# templateId 2163, and videoUrl "https://cambridgema.v3.swagit.com/
# events/43940" all come directly from a real
# `curl https://cambridgema.primegov.com/api/v2/PublicPortal/
# ListArchivedMeetings?year=2026` response; brookhavenga/clip_id=76 comes
# from the same research file's confirmed real finding. The Swagit/
# Granicus page HTML each meeting delegates to, however, IS synthetic
# (same convention test_swagit.py/test_granicus.py already use for their
# own minimal fixtures) -- only enough markup for those adapters' own
# already-tested parsing to find a title/video, not a captured real page.

CURRENT_YEAR = datetime.now().year

# Real confirmed finding (see
# ~/Documents/rtr-business/research/primegov_swagit_granicus_undetected.txt):
# baycountyfl's real video is a `/videos/{id}` Swagit URL -- the shape
# SwagitAssetFinder was actually built and tested against, unlike the
# `/events/{id}` shape covered separately below.
BAYCOUNTY_URL = "https://baycountyfl.primegov.com/Portal/Meeting?meetingTemplateId=1847"
BAYCOUNTY_API_URL = (
    f"https://baycountyfl.primegov.com/api/v2/PublicPortal/"
    f"ListArchivedMeetings?year={CURRENT_YEAR}"
)
# Real (trimmed) response shape, captured live 2026-08-19 -- see comment
# block above.
BAYCOUNTY_API_RESPONSE = json.dumps(
    [
        {
            "id": 383,
            "documentList": [{"id": 1, "templateId": 1847, "templateName": "Agenda"}],
            "videoUrl": "https://baycountyfl.new.swagit.com/videos/371216",
            "swagitId": "videos/371216",
            "title": "BOCC Regular Meeting",
            "date": "Jan 06, 2026",
        },
        {
            "id": 384,
            "documentList": [{"id": 2, "templateId": 1900, "templateName": "Agenda"}],
            "videoUrl": None,
            "title": "Other Meeting",
        },
    ]
)

SWAGIT_URL = "https://baycountyfl.new.swagit.com/videos/371216"
# Synthetic (see comment block above) -- same minimal shape
# tests/test_swagit.py's own BASE_HTML fixture uses.
SWAGIT_HTML = (
    "<html><head><title>Jan 06, 2026 BOCC Regular Meeting - "
    "Panama City, FL</title></head>"
    '<body><script>var playlist = [{"file": '
    '"https://archive-stream.granicus.com/x/playlist.m3u8"}];</script></body></html>'
)


async def test_resolve_delegates_to_swagit_via_tenant_api_when_no_youtube_video():
    _register_delegation_targets()
    routes = {
        BAYCOUNTY_URL: FakeResponse(
            status=200, text=PAGE_HTML_NO_VIDEO, url=BAYCOUNTY_URL
        ),
        BAYCOUNTY_API_URL: FakeResponse(status=200, text=BAYCOUNTY_API_RESPONSE),
        SWAGIT_URL: FakeResponse(status=200, text=SWAGIT_HTML, url=SWAGIT_URL),
    }

    with mock_session(routes):
        result = await PrimeGovAssetFinder().resolve(BAYCOUNTY_URL)

    assert result.platform == "swagit"  # delegated finder's own platform name
    assert result.video_url == "https://archive-stream.granicus.com/x/playlist.m3u8"
    # Same source_url-preserving choice as the YouTube delegation path --
    # "View original source" keeps pointing at the real PrimeGov page, not
    # the swagit.com URL discovered behind the scenes via the tenant API.
    assert result.source_url == BAYCOUNTY_URL


CAMBRIDGE_URL = "https://cambridgema.primegov.com/Portal/Meeting?meetingTemplateId=2163"
CAMBRIDGE_API_URL = (
    f"https://cambridgema.primegov.com/api/v2/PublicPortal/"
    f"ListArchivedMeetings?year={CURRENT_YEAR}"
)
# Real (trimmed) response shape, captured live 2026-08-19.
CAMBRIDGE_API_RESPONSE = json.dumps(
    [
        {
            "id": 428,
            "documentList": [
                {"id": 15809, "templateId": 2163, "templateName": "Minutes"}
            ],
            "videoUrl": "https://cambridgema.v3.swagit.com/events/43940",
            "swagitId": "events/43940",
            "title": "Regular City Council Meeting",
            "date": "Jan 12, 2026",
        }
    ]
)


async def test_resolve_declines_to_delegate_to_a_swagit_events_url():
    # Real, confirmed-live bug found 2026-08-19 while verifying this fix
    # (see the module-level comment on `_resolve_via_tenant_video_url`):
    # a real `/events/{id}` Swagit URl -- cambridgema's own confirmed
    # videoUrl -- serves a bogus placeholder video (the same
    # "vault01/abilenetx/..." CDN path independently confirmed on 3 other
    # real tenants) instead of the real meeting, when fetched the same
    # way `/videos/{id}` pages are. Delegating would silently hand back a
    # wrong-but-plausible video with no warning -- worse than the honest
    # "no video found" this must fall back to instead. No SWAGIT_URL route
    # is mocked here on purpose: if this guard were ever removed/broken,
    # mock_session would raise a loud AssertionError (unmocked request)
    # rather than this test silently passing on the wrong behavior.
    routes = {
        CAMBRIDGE_URL: FakeResponse(
            status=200, text=PAGE_HTML_NO_VIDEO, url=CAMBRIDGE_URL
        ),
        CAMBRIDGE_API_URL: FakeResponse(status=200, text=CAMBRIDGE_API_RESPONSE),
    }

    with mock_session(routes):
        result = await PrimeGovAssetFinder().resolve(CAMBRIDGE_URL)

    assert result.platform == "primegov"
    assert result.video_url is None
    assert any("no video found" in w.lower() for w in result.video_warnings)


BROOKHAVEN_URL = (
    "https://brookhavenga.primegov.com/Portal/Meeting?meetingTemplateId=593"
)
BROOKHAVEN_API_URL = (
    f"https://brookhavenga.primegov.com/api/v2/PublicPortal/"
    f"ListArchivedMeetings?year={CURRENT_YEAR}"
)
# Real confirmed finding (see
# ~/Documents/rtr-business/research/primegov_swagit_granicus_undetected.txt):
# brookhavenga's real video is a protocol-relative Granicus MediaPlayer.php
# URL -- kept protocol-relative here on purpose to also cover the
# urljoin() normalization step, not just the already-absolute case the
# Swagit test above covers.
BROOKHAVEN_API_RESPONSE = json.dumps(
    [
        {
            "id": 1,
            "documentList": [{"id": 1, "templateId": 593, "templateName": "Agenda"}],
            "videoUrl": "//brookhavenga.granicus.com/MediaPlayer.php?clip_id=76",
        }
    ]
)

GRANICUS_URL = "https://brookhavenga.granicus.com/MediaPlayer.php?clip_id=76"
# Synthetic minimal Granicus page (see comment block above) -- enough for
# GranicusAssetFinder's own already-tested parsing to find a title/video;
# not a captured real page.
GRANICUS_HTML = (
    "<html><head><title>City Council Special Called Meeting</title></head>"
    '<body><script>var url = "https://archive-stream.granicus.com/y/'
    'playlist.m3u8";</script></body></html>'
)


async def test_resolve_delegates_to_granicus_via_tenant_api_when_no_youtube_video():
    _register_delegation_targets()
    routes = {
        BROOKHAVEN_URL: FakeResponse(
            status=200, text=PAGE_HTML_NO_VIDEO, url=BROOKHAVEN_URL
        ),
        BROOKHAVEN_API_URL: FakeResponse(status=200, text=BROOKHAVEN_API_RESPONSE),
        GRANICUS_URL: FakeResponse(status=200, text=GRANICUS_HTML, url=GRANICUS_URL),
        "https://brookhavenga.granicus.com/AgendaViewer.php?clip_id=76&embedded=1": FakeResponse(
            status=404
        ),
    }

    with mock_session(routes):
        result = await PrimeGovAssetFinder().resolve(BROOKHAVEN_URL)

    assert result.platform == "granicus"
    assert result.video_url == "https://archive-stream.granicus.com/y/playlist.m3u8"
    assert result.source_url == BROOKHAVEN_URL


async def test_resolve_falls_back_to_honest_no_video_when_tenant_api_has_no_match():
    # A meetingTemplateId genuinely not found in either of the two
    # guessed-year archives, or in any other year the tenant has ever
    # archived -- a real agenda-only page with no video anywhere, not a
    # bug. GetArchivedMeetingYears returning [] here means the current/
    # prior-year misses below are the only two requests made before
    # giving up -- confirms the fallback doesn't loop forever.
    url = "https://okc.primegov.com/Portal/Meeting?meetingTemplateId=99999"
    api_url_current = (
        f"https://okc.primegov.com/api/v2/PublicPortal/"
        f"ListArchivedMeetings?year={CURRENT_YEAR}"
    )
    api_url_prior = (
        f"https://okc.primegov.com/api/v2/PublicPortal/"
        f"ListArchivedMeetings?year={CURRENT_YEAR - 1}"
    )
    years_url = "https://okc.primegov.com/api/v2/PublicPortal/GetArchivedMeetingYears"
    routes = {
        url: FakeResponse(status=200, text=PAGE_HTML_NO_VIDEO, url=url),
        api_url_current: FakeResponse(status=200, text="[]"),
        api_url_prior: FakeResponse(status=200, text="[]"),
        years_url: FakeResponse(status=200, text="[]"),
    }

    with mock_session(routes):
        result = await PrimeGovAssetFinder().resolve(url)

    assert result.platform == "primegov"
    assert result.video_url is None
    assert any("no video found" in w.lower() for w in result.video_warnings)


async def test_resolve_skips_tenant_api_entirely_when_url_has_no_meeting_template_id():
    # No meetingTemplateId in the URL at all -- _extract_meeting_template_id
    # returns None before any API request would be built, so this must
    # resolve straight to the honest "no video" response with ZERO extra
    # HTTP calls. mock_session's routes dict below deliberately contains
    # only the page fetch itself -- an unmocked request raises
    # AssertionError, so this test would fail loudly if the tenant-API
    # fallback were ever (wrongly) attempted here.
    url = "https://okc.primegov.com/Portal/Meeting?compiledMeetingDocumentFileId=123"
    routes = {url: FakeResponse(status=200, text=PAGE_HTML_NO_VIDEO, url=url)}

    with mock_session(routes):
        result = await PrimeGovAssetFinder().resolve(url)

    assert result.platform == "primegov"
    assert result.video_url is None


async def test_resolve_falls_back_to_archived_years_list_for_an_older_meeting():
    # Real gap confirmed live 2026-08-19 on two real meetings
    # (liveoakcity, sanjoseca) from Jan 2024: the current/prior-year guess
    # misses a meeting old enough to no longer be "recent," so this checks
    # the GetArchivedMeetingYears fallback actually reaches and matches an
    # older year once the guessed years both come back empty. Years below
    # are all computed relative to CURRENT_YEAR (not hardcoded) so this
    # test stays correct regardless of which real year it's run in --
    # OLD_YEAR is deliberately 2 years further back than the
    # already-tried CURRENT_YEAR-1, so it's genuinely new territory for
    # the fallback loop, not accidentally already covered.
    old_year = CURRENT_YEAR - 2
    url = "https://oldtenant.primegov.com/Portal/Meeting?meetingTemplateId=42"
    api_url_current = (
        f"https://oldtenant.primegov.com/api/v2/PublicPortal/"
        f"ListArchivedMeetings?year={CURRENT_YEAR}"
    )
    api_url_prior = (
        f"https://oldtenant.primegov.com/api/v2/PublicPortal/"
        f"ListArchivedMeetings?year={CURRENT_YEAR - 1}"
    )
    years_url = (
        "https://oldtenant.primegov.com/api/v2/PublicPortal/GetArchivedMeetingYears"
    )
    api_url_old_year = (
        f"https://oldtenant.primegov.com/api/v2/PublicPortal/"
        f"ListArchivedMeetings?year={old_year}"
    )
    old_meeting_response = json.dumps(
        [
            {
                "id": 7,
                "documentList": [{"id": 1, "templateId": 42, "templateName": "Agenda"}],
                "videoUrl": "https://oldtenant.new.swagit.com/videos/1",
            }
        ]
    )
    routes = {
        url: FakeResponse(status=200, text=PAGE_HTML_NO_VIDEO, url=url),
        api_url_current: FakeResponse(status=200, text="[]"),
        api_url_prior: FakeResponse(status=200, text="[]"),
        # CURRENT_YEAR-1 is skipped by the fallback loop -- already
        # covered by api_url_prior above -- so only old_year (the real
        # match, in this synthetic scenario) needs its own route.
        years_url: FakeResponse(
            status=200,
            text=json.dumps([CURRENT_YEAR - 1, old_year, old_year - 1]),
        ),
        api_url_old_year: FakeResponse(status=200, text=old_meeting_response),
        "https://oldtenant.new.swagit.com/videos/1": FakeResponse(
            status=200,
            text="<html><head><title>Old Meeting - Old Tenant, ST</title></head>"
            '<body><script>var playlist = [{"file": '
            '"https://archive-stream.granicus.com/z/playlist.m3u8"}];</script>'
            "</body></html>",
            url="https://oldtenant.new.swagit.com/videos/1",
        ),
    }
    _register_delegation_targets()

    with mock_session(routes):
        result = await PrimeGovAssetFinder().resolve(url)

    assert result.platform == "swagit"
    assert result.video_url == "https://archive-stream.granicus.com/z/playlist.m3u8"


def test_extract_meeting_template_id_reads_the_query_param():
    assert (
        PrimeGovAssetFinder._extract_meeting_template_id(
            "https://okc.primegov.com/Portal/Meeting?meetingTemplateId=68482"
        )
        == "68482"
    )


def test_extract_meeting_template_id_returns_none_when_absent():
    assert (
        PrimeGovAssetFinder._extract_meeting_template_id(
            "https://okc.primegov.com/Portal/Meeting?compiledMeetingDocumentFileId=123"
        )
        is None
    )


def test_candidate_years_prioritizes_the_page_date_year():
    assert PrimeGovAssetFinder._candidate_years("2024-01-17") == [
        2024,
        CURRENT_YEAR,
        CURRENT_YEAR - 1,
    ]


def test_candidate_years_without_a_page_date_falls_back_to_recent_years():
    assert PrimeGovAssetFinder._candidate_years(None) == [
        CURRENT_YEAR,
        CURRENT_YEAR - 1,
    ]
