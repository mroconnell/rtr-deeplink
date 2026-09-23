from app.platforms.townhallstreams import TownHallStreamsAssetFinder

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture

LISBON_URL = "https://townhallstreams.com/stream.php?location_id=94&id=75799"
LISBON_TRANSCRIPT_URL = (
    "https://townhallstreams.com/stream.php?full=1&location_id=94&id=75799"
    "&action=get_transcriptions"
)

OOB_URL = "https://townhallstreams.com/stream.php?location_id=47&id=21880"
OOB_TRANSCRIPT_URL = (
    "https://townhallstreams.com/stream.php?full=1&location_id=47&id=21880"
    "&action=get_transcriptions"
)

NEWBOSTON_URL = "https://townhallstreams.com/stream.php?location_id=108&id=35970"
NEWBOSTON_TRANSCRIPT_URL = (
    "https://townhallstreams.com/stream.php?full=1&location_id=108&id=35970"
    "&action=get_transcriptions"
)

HURLOCK_URL = "https://townhallstreams.com/stream.php?location_id=116&id=36006"
HURLOCK_TRANSCRIPT_URL = (
    "https://townhallstreams.com/stream.php?full=1&location_id=116&id=36006"
    "&action=get_transcriptions"
)

HENNIKER_URL = "https://townhallstreams.com/stream.php?location_id=89&id=75988"
HENNIKER_TRANSCRIPT_URL = (
    "https://townhallstreams.com/stream.php?full=1&location_id=89&id=75988"
    "&action=get_transcriptions"
)


async def test_resolve_real_lisbon_maine_meeting():
    # Real page fetched live 2026-08-20 from a real Lisbon, ME meeting
    # (BACKLOG.md sample #1) -- the real, populated happy path: a slug
    # with a US state abbreviation suffix, a real structured video
    # filename, and the real (always-empty-so-far) transcript endpoint.
    html = load_fixture("townhallstreams", "lisbon_me_stream.html")

    routes = {
        LISBON_URL: FakeResponse(status=200, text=html, url=LISBON_URL),
        LISBON_TRANSCRIPT_URL: FakeResponse(
            status=200, text="", url=LISBON_TRANSCRIPT_URL
        ),
    }

    with mock_session(routes):
        result = await TownHallStreamsAssetFinder().resolve(LISBON_URL)

    assert result.platform == "townhallstreams"
    assert result.external_id == "townhallstreams:94:75799"
    assert result.title == "Town Council Special Meeting"
    assert result.date == "2026-07-28"
    assert result.jurisdiction == "Lisbon, ME"
    assert (
        result.video_url
        == "https://cdn.townhallstreams.com/vod/_definst_/mp4:lisbon_me/"
        "2026-07-28_330055_Town_Council_Special_Meeting.mp4/playlist.m3u8"
    )
    assert result.video_format == "m3u8"
    assert result.segments == []
    assert result.transcript_warnings == ["No captions found for this video."]
    assert result.video_warnings == []


async def test_resolve_declines_jurisdiction_when_slug_has_no_real_word_city():
    # Real page fetched live 2026-08-20 (BACKLOG.md sample #2, Old
    # Orchard Beach, ME -- real slug "oob_maine"). Pins the exact case
    # BACKLOG.md's investigation flagged: "oob" isn't a real word/name, so
    # jurisdiction_enrich.validated_label_extract() must decline rather
    # than guess -- a by-eye decode got this "right" only via outside
    # knowledge of the real town name, which this adapter must not do.
    html = load_fixture("townhallstreams", "oob_maine_stream.html")

    routes = {
        OOB_URL: FakeResponse(status=200, text=html, url=OOB_URL),
        OOB_TRANSCRIPT_URL: FakeResponse(status=200, text="", url=OOB_TRANSCRIPT_URL),
    }

    with mock_session(routes):
        result = await TownHallStreamsAssetFinder().resolve(OOB_URL)

    assert result.jurisdiction is None
    assert result.title == "Interupting Aging"
    assert result.video_format == "m3u8"


async def test_resolve_jurisdiction_with_no_state_in_slug_stays_stateless():
    # Real page fetched live 2026-08-20 (BACKLOG.md sample #4, New
    # Boston, NH -- real slug "newboston", carrying ZERO state
    # information). BACKLOG.md's investigation confirmed a human got "NH"
    # right only via outside knowledge of the real town, and that neither
    # the slug itself nor a Census unambiguous-name lookup (New Boston is
    # a real, ambiguous multi-state name) can recover it -- so the correct,
    # honest result is the bare validated city name with no state, not a
    # guess.
    html = load_fixture("townhallstreams", "newboston_stream.html")

    routes = {
        NEWBOSTON_URL: FakeResponse(status=200, text=html, url=NEWBOSTON_URL),
        NEWBOSTON_TRANSCRIPT_URL: FakeResponse(
            status=200, text="", url=NEWBOSTON_TRANSCRIPT_URL
        ),
    }

    with mock_session(routes):
        result = await TownHallStreamsAssetFinder().resolve(NEWBOSTON_URL)

    assert result.jurisdiction == "New Boston"
    assert result.title == "B"
    assert result.date == "2021-03-15"


async def test_resolve_flags_unexpected_non_empty_transcript_response():
    # Synthetic: the real transcript endpoint has returned empty on every
    # one of 7 real meetings checked (see module docstring) -- no real
    # positive example exists yet to build a real parser against. This
    # covers the one still-unconfirmed branch (a genuinely non-empty
    # response) using the same real Lisbon page fixture as the happy-path
    # test above, so only the transcript endpoint's response is synthetic.
    html = load_fixture("townhallstreams", "lisbon_me_stream.html")

    routes = {
        LISBON_URL: FakeResponse(status=200, text=html, url=LISBON_URL),
        LISBON_TRANSCRIPT_URL: FakeResponse(
            status=200,
            text="<div>some real caption text nobody has seen yet</div>",
            url=LISBON_TRANSCRIPT_URL,
        ),
    }

    with mock_session(routes):
        result = await TownHallStreamsAssetFinder().resolve(LISBON_URL)

    assert result.segments == []
    assert len(result.transcript_warnings) == 1
    assert "doesn't yet know how to read" in result.transcript_warnings[0]


async def test_resolve_logs_a_warning_when_the_transcript_check_fails(caplog):
    # Real silent-exception site found live during the 2026-08-28 sweep
    # (BACKLOG.md) -- _check_for_transcript()'s non-200 branch used to
    # return the generic "No captions found" message with no record of
    # why, so a real fetch failure and a genuinely-empty response looked
    # identical in the logs.
    html = load_fixture("townhallstreams", "lisbon_me_stream.html")

    routes = {
        LISBON_URL: FakeResponse(status=200, text=html, url=LISBON_URL),
        LISBON_TRANSCRIPT_URL: FakeResponse(
            status=503, text="", url=LISBON_TRANSCRIPT_URL
        ),
    }

    with mock_session(routes), caplog.at_level("WARNING"):
        result = await TownHallStreamsAssetFinder().resolve(LISBON_URL)

    assert result.transcript_warnings == ["No captions found for this video."]
    assert any(
        "503" in record.message and "94" in record.message for record in caplog.records
    )


async def test_resolve_reads_new_originalFile_variable_shape():
    # Real page fetched live 2026-09-12 (WO-294) from Hurlock, MD --
    # confirms the site-wide embed change found this session: the real
    # video is no longer a direct `file: "..."` literal (what the
    # adapter originally shipped against) but a `var originalFile = "..."`
    # JS variable one line above the jwplayer .setup() call. Before this
    # fix, this exact real page resolved to no video at all -- it was one
    # of the tier-3 queue's 116 "no video_url" lines the BACKLOG.md entry
    # flagged. See the module docstring's 2026-09-12 update.
    html = load_fixture("townhallstreams", "hurlockmd_stream_new_shape.html")

    routes = {
        HURLOCK_URL: FakeResponse(status=200, text=html, url=HURLOCK_URL),
        HURLOCK_TRANSCRIPT_URL: FakeResponse(
            status=200, text="", url=HURLOCK_TRANSCRIPT_URL
        ),
    }

    with mock_session(routes):
        result = await TownHallStreamsAssetFinder().resolve(HURLOCK_URL)

    assert result.external_id == "townhallstreams:116:36006"
    assert result.title == "Work Session February 22 2021"
    assert result.date == "2021-02-22"
    assert result.jurisdiction == "Hurlock, MD"
    assert (
        result.video_url
        == "https://cdn.townhallstreams.com/vod/_definst_/mp4:hurlockmd/"
        "2021-02-22_1481127_Work_Session_February_22_2021.mp4/playlist.m3u8"
    )
    assert result.video_warnings == []


async def test_resolve_prefers_real_meeting_over_audience_pip_camera():
    # Real page fetched live 2026-09-12 (WO-294) from Henniker, NH.
    # Confirms the second, more serious bug found this session: every one
    # of the tier-3 queue probe's real "accept" verdicts for this
    # platform was actually resolving to a small secondary audience/PIP
    # camera feed (still wired up with the old direct `file: "..."`
    # literal shape) instead of the real meeting video (in
    # `var originalFile`) -- confirmed live on this exact page, which
    # used to resolve to
    # ".../Henniker_Community_Room_Audience_pip_20260803_180000.mp4/..."
    # with title/date/jurisdiction all None, instead of the real meeting
    # below. See the module docstring's 2026-09-12 update.
    html = load_fixture("townhallstreams", "henniker_nh_stream_pip.html")

    routes = {
        HENNIKER_URL: FakeResponse(status=200, text=html, url=HENNIKER_URL),
        HENNIKER_TRANSCRIPT_URL: FakeResponse(
            status=200, text="", url=HENNIKER_TRANSCRIPT_URL
        ),
    }

    with mock_session(routes):
        result = await TownHallStreamsAssetFinder().resolve(HENNIKER_URL)

    assert (
        result.video_url
        == "https://cdn.townhallstreams.com/vod/_definst_/mp4:henniker_nh/"
        "2026-08-03_8620011_Board_of_Selectmen_Meeting_Rte_114_Listening_"
        "Session.mp4/playlist.m3u8"
    )
    assert "pip" not in result.video_url.lower()
    assert result.title == "Board of Selectmen Meeting Rte 114 Listening Session"
    assert result.date == "2026-08-03"
    assert result.jurisdiction == "Henniker, NH"


def test_find_video_url_ignores_a_pip_only_page_in_the_fallback_path():
    # Synthetic (no real page checked lacks `var originalFile` entirely
    # -- see module docstring): pins that the defensive fallback branch
    # never returns a PIP camera URL even when it's the only literal
    # `file:` match on the page, rather than silently accepting a wrong
    # video the way the pre-fix regex did.
    html = (
        '<script>jwplayer("myElement1").setup({file: '
        '"https://cdn.townhallstreams.com/vod/_definst_/mp4:someplace/'
        'Someplace_Audience_pip_20260101_120000.mp4/playlist.m3u8"});</script>'
    )

    assert TownHallStreamsAssetFinder._find_video_url(html) is None


async def test_resolve_missing_video_config_returns_warning_not_crash():
    url = "https://townhallstreams.com/stream.php?location_id=1&id=2"
    html = "<html><body>Not the right shape.</body></html>"

    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await TownHallStreamsAssetFinder().resolve(url)

    assert result.video_url is None
    assert result.video_warnings == [
        "Could not find Town Hall Streams' video configuration on this page."
    ]


# --- Town listing pages (2026-09-23) ------------------------------------
#
# A `/towns/{slug}` listing page is not one meeting -- resolve() used to
# fail on it outright. Found hand-checking CivicPlus governments whose
# homepage links to a separate video platform (Hollis/Chichester/
# Moultonborough NH). Reuses the existing `_townhallstreams_walker()`
# (app/platforms/passive_verify.py, WO-344) rather than a second,
# hand-rolled listing parser -- that walker already has its own test
# coverage for parsing correctness; these tests cover only the NEW
# integration: resolve() delegating to it and trying more than one
# candidate when the newest doesn't pan out.
#
# Dates deliberately fixed in the safely-distant past (2020) rather than
# reusing a "recent" fixture -- a date-sensitive fixture broke live
# 2026-09-23 (see `_resolve_town_listing()`'s own docstring): a listing
# page's "newest" candidate can be a same-day meeting with no video
# posted yet, which is exactly the bounded-retry behavior the second test
# below exercises on purpose, not something to avoid triggering by
# accident here.
TOWN_LISTING_URL = "https://townhallstreams.com/towns/testville_me"
NEWEST_STREAM_URL = "https://townhallstreams.com/stream.php?location_id=200&id=900"
NEWEST_TRANSCRIPT_URL = (
    "https://townhallstreams.com/stream.php?full=1&location_id=200&id=900"
    "&action=get_transcriptions"
)
OLDER_STREAM_URL = "https://townhallstreams.com/stream.php?location_id=200&id=899"
OLDER_TRANSCRIPT_URL = (
    "https://townhallstreams.com/stream.php?full=1&location_id=200&id=899"
    "&action=get_transcriptions"
)

TOWN_LISTING_HTML = """
<html><body>
<a href="/stream.php?location_id=200&id=900">Select Board January 15, 2020 - 06:00 pm to 09:00 pm (EST)</a>
<a href="/stream.php?location_id=200&id=899">Planning Board January 8, 2020 - 07:00 pm to 09:00 pm (EST)</a>
</body></html>
"""

NEWEST_NO_VIDEO_HTML = "<html><body>Meeting page with no video posted yet.</body></html>"

OLDER_WITH_VIDEO_HTML = (
    '<script>var originalFile = '
    '"https://cdn.townhallstreams.com/vod/_definst_/mp4:testville_me/'
    '2020-01-08_555_Planning_Board.mp4/playlist.m3u8";</script>'
)


async def test_resolve_town_listing_delegates_to_newest_candidate():
    routes = {
        TOWN_LISTING_URL: FakeResponse(status=200, text=TOWN_LISTING_HTML, url=TOWN_LISTING_URL),
        NEWEST_STREAM_URL: FakeResponse(status=200, text=OLDER_WITH_VIDEO_HTML, url=NEWEST_STREAM_URL),
        NEWEST_TRANSCRIPT_URL: FakeResponse(status=200, text="", url=NEWEST_TRANSCRIPT_URL),
    }

    with mock_session(routes):
        result = await TownHallStreamsAssetFinder().resolve(TOWN_LISTING_URL)

    assert result.video_url is not None
    assert result.source_url == NEWEST_STREAM_URL


async def test_resolve_town_listing_tries_next_candidate_when_newest_has_no_video():
    # Real gap found live 2026-09-23 on Moultonborough NH: the listing's
    # own newest-dated candidate (a same-day meeting) had no video posted
    # yet, while the next candidate right behind it did -- picking only
    # the single newest and stopping there would wrongly report "no
    # video" for a town that genuinely has one.
    routes = {
        TOWN_LISTING_URL: FakeResponse(status=200, text=TOWN_LISTING_HTML, url=TOWN_LISTING_URL),
        NEWEST_STREAM_URL: FakeResponse(status=200, text=NEWEST_NO_VIDEO_HTML, url=NEWEST_STREAM_URL),
        OLDER_STREAM_URL: FakeResponse(status=200, text=OLDER_WITH_VIDEO_HTML, url=OLDER_STREAM_URL),
        OLDER_TRANSCRIPT_URL: FakeResponse(status=200, text="", url=OLDER_TRANSCRIPT_URL),
    }

    with mock_session(routes):
        result = await TownHallStreamsAssetFinder().resolve(TOWN_LISTING_URL)

    assert result.video_url is not None
    assert result.source_url == OLDER_STREAM_URL


async def test_resolve_town_listing_reports_cleanly_when_nothing_found():
    routes = {
        TOWN_LISTING_URL: FakeResponse(
            status=200, text="<html><body>No meetings.</body></html>", url=TOWN_LISTING_URL
        ),
    }

    with mock_session(routes):
        result = await TownHallStreamsAssetFinder().resolve(TOWN_LISTING_URL)

    assert result.video_url is None
    assert "no past meeting found" in result.video_warnings[0].lower()
