from app.platforms.telvue import TelvueAssetFinder

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture

# TelVue -- found 2026-08-16 from generic_fallback.py already having
# resolved 3 real customer meetings under platform="unknown" (2 direct
# videoplayer.telvue.com URLs, 1 reached via a u.peg.tv shortlink). Real
# fixtures below are from a live Ashland, OR Planning Commission meeting
# (media id 1040134) -- the captions fixture is trimmed to its first 30
# real cues (same "trimmed real VTT fixture" convention test_escribe.py
# uses), the page HTML and chapters.vtt are kept in full since both are
# small. See BACKLOG_DONE.md for the full investigation.

PAGE_URL = "https://videoplayer.telvue.com/player/w9sPsSE7vna3XTN_39bs1rEXjVWF0kfP/media/1040134"
CAPTIONS_URL = (
    "https://videoplayer.telvue.com/closed_captions/"
    "W1siZiIsImViNTYzN2IwLTIzNjktMDEzMy1hYTEzLTAwMjU5MGYwMDg1Yy80ZDQ5MTViZS02YTBkLTQ4OTUtYWZkNi1jOTE5ZDA1MDM0YzgvY2xvc2VkX2NhcHRpb25zL3ByaW1hcnktZW4tY2FwdGlvbnMtMTc4NjU2MjgxOS52dHQiXV0"
    "?sha=d8106e3ce75332ff"
)
CHAPTERS_URL = "https://videoplayer.telvue.com/player/media/1040134/chapters.vtt"


async def test_resolve_real_ashland_planning_commission_meeting():
    html = load_fixture("telvue", "ashland_planning_1040134_page.html")
    captions = load_fixture("telvue", "ashland_planning_1040134_captions.vtt")
    chapters = load_fixture("telvue", "ashland_planning_1040134_chapters.vtt")

    routes = {
        PAGE_URL: FakeResponse(status=200, text=html, url=PAGE_URL),
        CAPTIONS_URL: FakeResponse(status=200, text=captions, url=CAPTIONS_URL),
        CHAPTERS_URL: FakeResponse(status=200, text=chapters, url=CHAPTERS_URL),
    }

    with mock_session(routes):
        result = await TelvueAssetFinder().resolve(PAGE_URL)

    assert result.platform == "telvue"
    assert result.title == "Ashland Planning Commission"
    assert result.date == "2026-08-11"
    assert result.jurisdiction == "Ashland"
    assert result.video_url == (
        "https://telvuevod-secure.akamaized.net/vodhls/vod_player/218/media/1040134/1786772089/master.m3u8"
    )
    assert result.video_format == "m3u8"

    # Real bug caught building this adapter: parse_vtt() doesn't strip
    # WebVTT voice tags (<v Speaker N>...</v>) on its own -- without
    # stripping them, cue text would literally contain "<v Speaker
    # 1>Recording in progress.</v>".
    assert len(result.segments) == 30  # the trimmed real VTT fixture's cue count
    assert result.segments[0].text == "Recording in progress."
    assert "<v" not in result.segments[0].text
    # A multi-voice cue (two speakers within one VTT cue block, joined by
    # a newline in the raw file) collapses to a single space-joined line.
    multi_voice = next(s for s in result.segments if "regular meeting" in s.text)
    assert multi_voice.text == "I call the regular. I call the regular meeting"

    # Real per-chapter agenda timestamps, from the separate chapters.vtt
    # track -- "Coming Up..." (the pre-roll placeholder chapter) is
    # deliberately dropped as not a real agenda item.
    assert len(result.agenda_items) == 9
    assert result.agenda_items[0].text == "Call to Order"
    assert result.agenda_items[0].start == 35.0
    assert result.agenda_items[0].end == 70.0
    assert not any(a.text.lower() == "coming up..." for a in result.agenda_items)

    assert result.video_warnings == []
    assert result.transcript_warnings == []


async def test_resolve_no_video_returns_warning_not_crash():
    url = "https://videoplayer.telvue.com/player/exampleorg/media/999999"
    html = (
        "<html><head><title>No Player</title></head><body>Nothing here.</body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await TelvueAssetFinder().resolve(url)

    assert result.platform == "telvue"
    assert result.video_url is None
    assert result.segments == []
    assert any("no video found" in w.lower() for w in result.video_warnings)


async def test_resolve_falls_back_to_known_org_token_jurisdiction():
    # Real case, confirmed 2026-08-18: this org token's real title is a
    # bare "City Council Meeting 11-27-23" (no city-name prefix at all,
    # same shape as the Fitchburg bug above) -- _guess_jurisdiction() and
    # enrich_jurisdiction_text() both correctly return None, so the only
    # way to land on the real jurisdiction is the per-org-token map
    # (_KNOWN_ORG_TOKEN_JURISDICTIONS), built from real corroborating
    # evidence found on the same org token's other playlist entries (see
    # that map's own comment in app/platforms/telvue.py) -- not a guess.
    # HTML shape below is synthetic (hand-built, not fetched), but reuses
    # the real Player.setupData['playlist'] JSON structure the Ashland
    # fixture above already confirms, and the org token/jurisdiction pair
    # itself is the real, confirmed one.
    url = "https://videoplayer.telvue.com/player/cT30AQ_xtOBQF0oJM2gIVCDX9kjgfWZb/playlists/8520/media/838708"
    html = (
        "<html><head><title>City Council Meeting 11-27-23</title></head><body>"
        "<script>Player.setupData['playlist'] = ["
        '{"title": "City Council Meeting 11-27-23", "file": null, "tracks": []}'
        "];</script></body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await TelvueAssetFinder().resolve(url)

    assert result.jurisdiction == "Everett, MA"


async def test_resolve_unknown_org_token_has_no_jurisdiction():
    url = "https://videoplayer.telvue.com/player/someOtherOrgToken123/media/1"
    html = (
        "<html><head><title>City Council Meeting 1-1-24</title></head><body>"
        "<script>Player.setupData['playlist'] = ["
        '{"title": "City Council Meeting 1-1-24", "file": null, "tracks": []}'
        "];</script></body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await TelvueAssetFinder().resolve(url)

    assert result.jurisdiction is None


async def test_split_title_date_handles_missing_date():
    title, date = TelvueAssetFinder._split_title_date("Untitled Meeting")
    assert title == "Untitled Meeting"
    assert date is None


async def test_split_title_date_parses_real_shape():
    title, date = TelvueAssetFinder._split_title_date(
        "Ashland City Council - August 19, 2025"
    )
    assert title == "Ashland City Council"
    assert date == "2025-08-19"


async def test_guess_jurisdiction_matches_known_body_suffixes():
    assert (
        TelvueAssetFinder._guess_jurisdiction("Ashland Planning Commission")
        == "Ashland"
    )
    assert TelvueAssetFinder._guess_jurisdiction("Medford City Council") == "Medford"
    assert TelvueAssetFinder._guess_jurisdiction("Board of Water Commissioners") is None
    assert TelvueAssetFinder._guess_jurisdiction(None) is None


def test_guess_jurisdiction_handles_select_board():
    # Real bug, confirmed live 2026-08-18: Natick, MA's real title has no
    # dash-separated date ("Natick Select Board June 10, 2026"), so
    # _guess_jurisdiction() runs against the whole string -- the bare
    # "Board" alternative matched first and produced "Natick Select"
    # instead of "Natick".
    assert (
        TelvueAssetFinder._guess_jurisdiction("Natick Select Board June 10, 2026")
        == "Natick"
    )


def test_guess_jurisdiction_rejects_generic_placeholder_words():
    # Real bug, confirmed live 2026-08-16: Fitchburg, MA's real title is a
    # bare "City Council - 5.6.2025" with no actual city name prefix --
    # matched the body-suffix regex with group(1)="City", producing the
    # bogus jurisdiction "City" (then "City, MA" after state enrichment).
    assert TelvueAssetFinder._guess_jurisdiction("City Council - 5.6.2025") is None
    assert TelvueAssetFinder._guess_jurisdiction("Town Council") is None
    assert TelvueAssetFinder._guess_jurisdiction("Village Board") is None
    assert TelvueAssetFinder._guess_jurisdiction("Township Committee") is None
