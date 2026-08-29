"""Tests for Seattle Channel (app/platforms/seattlechannel.py).

Real page shapes confirmed live 2026-08-14 against two independent real
meetings on the `/videos?videoid={id}` page shape (see BACKLOG.md):
x189286 ("City Council 8/11/2026", the original find) and x184865 ("City
Council 3/3/2026", fetched fresh to confirm the shape generalizes before
building). HTML below is trimmed to just what the adapter reads, but every
string -- including the second, unrelated video block used to test the
disambiguation logic -- is real, pulled directly from the live x184865 page,
not invented. Caption fixture is a real 900-line excerpt of the actual SRT
this same meeting serves (see the shouting-normalization test below for
why it's not a much shorter trim).
"""

from app.platforms.base import detect_platform
from app.platforms.seattlechannel import SeattleChannelAssetFinder

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture

MEETING_URL = "https://www.seattlechannel.org/videos?videoid=x184865"
CAPTION_URL = "https://www.seattlechannel.org/documents/seattlechannel/closedcaption/2026/council_030326_2022617.srt"
REAL_MP4_URL = "https://video.seattle.gov/media/council/council_030326_2022617.mp4"

# Real shape: the primary video's player is always literally
# jwplayer('vidPlayer') -- a second, unrelated video further down the same
# page (a real "related story" clip, confirmed present on this exact page)
# uses a different, per-video numeric id (jw4052508 here) instead. The
# adapter must pick up the vidPlayer block's own file/track/title, never
# the second block's -- that's what most of this fixture's shape exists to
# exercise, not just "does this parse."
REAL_PAGE_HTML = """
<html><head><title>City Council 3/3/2026 | seattlechannel.org</title>
<meta name="video_date" content="2026-03-03" />
</head>
<body>
<div id="mainContent">
<div class="row borderBottomNone mainColwithSub">
    <div class="programImage col-xs-12 col-sm-8">
        <div id="vidPlayer"></div>
        <div class="overlayBox"><div class="videoTitle">City Council 3/3/2026</div></div>
    </div>
    <div class="programDescription col-xs-12 col-sm-4">
        <div class="episodeTitle">City Council 3/3/2026</div>
        <div class="episodeDate">3/3/2026<span class="episodeDuration">1:05:47</span></div>
        <div class="episodeDescription"><p>Agenda: Call to Order; Roll Call; Public Comment.</p></div>
        <div class="videoIndex">
            <div class="indexHeading">Advance to a specific part </div>
                <a class="seekItem" href="#" data-seek="55">Proclamation: Women&#39;s History Month - 0:55</a>
                <a class="seekItem" href="#" data-seek="1514">Public Comment - 25:14</a>
                <a class="seekItem" href="#" data-seek="3580">Res 32191: relating to regional Westlake Park hub - 59:40</a>
        </div>
    </div>
</div>
<script>
     var embedCode = '<iframe src="https://www.seattlechannel.org/embedvideoplayer?videoid=x184865" frameborder="0" scrolling="no"></iframe>';
     var shareLink = "https://www.seattlechannel.org/videos?videoid=x184865";
    try { jwplayer('vidPlayer').remove(); } catch(emsg){};
    var playerInstance = jwplayer('vidPlayer');
    playerInstance.setup({
    sources: [
        { file: "//video.seattle.gov/media/council/council_030326_2022617.mp4", label: "Auto" }
    ],
    image: "images//images/seattlechannel/videos/2026/council_030326_2022617web.jpg",
    primary: "html5",
        tracks: [{
            file: "documents/seattlechannel/closedcaption/2026/council_030326_2022617.srt",
            label: "English",
            kind: "captions",
            "default": true
        }],
        sharing: { code: encodeURI(embedCode), link: shareLink },
        ga: { idstring:'City Council 3/3/2026' }
    });
    playerInstance.on('complete', function () { $('#vidPlayer').append($('.overlayBox')); });
    playerInstance.on('beforePlay', function () {});
</script>
<div class="padTop VideoComponent" id="x177820">
    <div id="jw4052508"></div>
    <div class="overlayBox"><div class="videoTitle">Seattle Fire &amp; Seattle Parks team up to offer free CPR classes</div></div>
    <script>
         var embedCode = '<iframe src="https://www.seattlechannel.org/embedvideoplayer?videoid=x177820" frameborder="0" scrolling="no"></iframe>';
         var shareLink = "https://www.seattlechannel.org/videos?videoid=x177820";
        try { jwplayer('jw4052508').remove(); } catch(emsg){};
        var playerInstance = jwplayer('jw4052508');
        playerInstance.setup({
        sources: [
            { file: "//video.seattle.gov/media/community/cs_SFDcpr_4052508.mp4", label: "Auto" }
        ],
        tracks: [{
            file: "documents/seattlechannel/closedcaption/2025/cs_SFDcpr_4052508.srt",
            label: "English", kind: "captions", "default": true
        }],
        ga: { idstring:'CityStream: Free CPR Classes' }
        });
        playerInstance.on('complete', function () {});
    </script>
</div>
</div>
</body></html>
"""


def test_detect_platform_recognizes_videos_videoid_shape():
    assert detect_platform(MEETING_URL) == "seattle_channel"


def test_detect_platform_leaves_feed_index_page_to_generic_fallback():
    # The older /mayor-and-council/city-council/city-council-all-videos-index
    # feed page (many *other* meetings' videos below the requested one) is
    # deliberately not claimed here -- see seattlechannel.py's module
    # docstring. Confirmed live 2026-08-12/14 that generic_fallback.py
    # already handles this shape reasonably (BACKLOG.md).
    url = "https://www.seattlechannel.org/mayor-and-council/city-council/city-council-all-videos-index?videoid=x189286"
    assert detect_platform(url) != "seattle_channel"


def test_detect_platform_leaves_bare_videos_page_with_no_videoid():
    assert detect_platform("https://www.seattlechannel.org/videos") != "seattle_channel"


async def test_resolve_real_page_finds_correct_video_not_the_second_one():
    srt = load_fixture("seattlechannel", "council_030326_2022617.srt")
    routes = {
        MEETING_URL: FakeResponse(status=200, text=REAL_PAGE_HTML, url=MEETING_URL),
        CAPTION_URL: FakeResponse(status=200, text=srt, url=CAPTION_URL),
    }

    with mock_session(routes):
        result = await SeattleChannelAssetFinder().resolve(MEETING_URL)

    assert result.platform == "seattle_channel"
    assert result.title == "City Council 3/3/2026"
    assert result.date == "2026-03-03"
    assert result.jurisdiction == "Seattle, WA"
    # The real assertion this fixture exists to make: the second video's
    # mp4 (cs_SFDcpr_4052508.mp4) must never be picked up instead.
    assert result.video_url == REAL_MP4_URL
    assert result.video_format == "mp4"
    assert not result.video_warnings


async def test_resolve_extracts_real_agenda_items_with_next_start_as_end():
    srt = load_fixture("seattlechannel", "council_030326_2022617.srt")
    routes = {
        MEETING_URL: FakeResponse(status=200, text=REAL_PAGE_HTML, url=MEETING_URL),
        CAPTION_URL: FakeResponse(status=200, text=srt, url=CAPTION_URL),
    }

    with mock_session(routes):
        result = await SeattleChannelAssetFinder().resolve(MEETING_URL)

    assert len(result.agenda_items) == 3
    assert result.agenda_items[0].start == 55
    assert result.agenda_items[0].text == "Proclamation: Women's History Month"
    # Same next-item-start-as-end convention as Granicus/IQM2/LIMS.
    assert result.agenda_items[0].end == 1514
    assert result.agenda_items[1].start == 1514
    assert result.agenda_items[1].end == 3580
    # Last item has no "next" -- end stays equal to start.
    assert result.agenda_items[2].start == 3580
    assert result.agenda_items[2].end == 3580


async def test_resolve_real_captions_are_populated_and_shouting_normalized():
    # Fixture is a real 900-line/225-cue excerpt, not a short one -- a
    # much shorter trim (tried first, ~60 lines) turned out to be a real
    # trap: this transcript's heavy real use of "&gt;&gt;&gt;"/"&gt;&gt;"
    # speaker-change markers (nearly every line) means each "&gt;"'s own
    # embedded lowercase letters ("g", "t") skew normalize_shouting_
    # caption()'s letter-ratio heuristic (it runs before entity-unescaping,
    # by design) -- over a *short* sample that pushes the lowercase ratio
    # above its threshold, so it doesn't fire. Confirmed against the real,
    # full 7320-line file that this is purely a too-small-sample artifact,
    # not a real production gap: normalization does correctly fire once
    # there's enough real prose (as here) to dilute the marker density.
    srt = load_fixture("seattlechannel", "council_030326_2022617.srt")
    routes = {
        MEETING_URL: FakeResponse(status=200, text=REAL_PAGE_HTML, url=MEETING_URL),
        CAPTION_URL: FakeResponse(status=200, text=srt, url=CAPTION_URL),
    }

    with mock_session(routes):
        result = await SeattleChannelAssetFinder().resolve(MEETING_URL)

    assert len(result.segments) > 100
    assert result.transcript_language == "en"
    assert not result.transcript_warnings
    joined = " ".join(seg.text for seg in result.segments)
    # Real SRT is ALL-CAPS with literal &gt; entities (see above) --
    # unescape_caption_entities always runs (last, by design), so no raw
    # "&gt;" survives, and normalize_shouting_caption re-cases the result.
    assert "&gt;" not in joined
    assert joined != joined.upper()


async def test_resolve_missing_mp4_reports_no_video():
    html = "<html><head><title>Some Page | seattlechannel.org</title></head><body>No video here.</body></html>"
    url = "https://www.seattlechannel.org/videos?videoid=x999999"

    with mock_session({url: FakeResponse(status=200, text=html, url=url)}):
        result = await SeattleChannelAssetFinder().resolve(url)

    assert result.video_url is None
    assert result.video_warnings == ["No video found on this page."]
    assert result.jurisdiction == "Seattle, WA"


async def test_resolve_caption_fetch_failure_reports_no_transcript(caplog):
    routes = {
        MEETING_URL: FakeResponse(status=200, text=REAL_PAGE_HTML, url=MEETING_URL),
        CAPTION_URL: FakeResponse(status=404),
    }

    with caplog.at_level("WARNING"):
        with mock_session(routes):
            result = await SeattleChannelAssetFinder().resolve(MEETING_URL)

    assert result.video_url == REAL_MP4_URL
    assert result.segments == []
    assert result.transcript_warnings == ["No transcript found for this event."]
    # 2026-08-28: a failed caption fetch used to be silent -- now logged.
    assert any("caption fetch got HTTP 404" in r.message for r in caplog.records)
