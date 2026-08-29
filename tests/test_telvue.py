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
    # "Ashland" alone is nationally ambiguous; the state fill comes from
    # _KNOWN_ORG_TOKEN_JURISDICTIONS (2026-08-28, BACKLOG_DONE.md) --
    # this org's own real page carries "Rogue Valley Community
    # Television," an unambiguous southern-Oregon regional identity.
    assert result.jurisdiction == "Ashland, OR"
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


async def test_resolve_vtt_fetch_failure_is_logged(caplog):
    # 2026-08-28: _fetch_vtt()'s non-200 branch used to be silent.
    html = load_fixture("telvue", "ashland_planning_1040134_page.html")
    chapters = load_fixture("telvue", "ashland_planning_1040134_chapters.vtt")
    routes = {
        PAGE_URL: FakeResponse(status=200, text=html, url=PAGE_URL),
        CAPTIONS_URL: FakeResponse(status=404, url=CAPTIONS_URL),
        CHAPTERS_URL: FakeResponse(status=200, text=chapters, url=CHAPTERS_URL),
    }

    with caplog.at_level("WARNING"):
        with mock_session(routes):
            result = await TelvueAssetFinder().resolve(PAGE_URL)

    assert result.segments == []
    assert any("VTT fetch got HTTP 404" in r.message for r in caplog.records)


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


async def test_resolve_known_org_token_fills_missing_state_not_just_total_miss():
    # 2026-08-28 widening: the registry used to only fire when the title
    # guess found NOTHING at all (the Everett case above). This is the
    # other real shape (Ashland): the guess already correctly finds a
    # bare, nationally-ambiguous name -- the registry should fill in just
    # the state, not be skipped because "jurisdiction" was already truthy.
    url = (
        "https://videoplayer.telvue.com/player/w9sPsSE7vna3XTN_39bs1rEXjVWF0kfP/media/1"
    )
    html = (
        "<html><head><title>Ashland City Council Meeting 1-1-24</title></head><body>"
        "<script>Player.setupData['playlist'] = ["
        '{"title": "Ashland City Council Meeting 1-1-24", "file": null, "tracks": []}'
        "];</script></body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await TelvueAssetFinder().resolve(url)

    assert result.jurisdiction == "Ashland, OR"


async def test_resolve_known_org_token_never_overrides_a_different_real_guess():
    # Guard for the same widening: a real, DIFFERENT city correctly
    # guessed under Ashland's own org token (e.g. a multi-city TelVue
    # customer, or a mis-scoped token) must never be silently replaced by
    # this registry's "Ashland, OR" -- only an exact bare-name match gets
    # the state fill.
    url = (
        "https://videoplayer.telvue.com/player/w9sPsSE7vna3XTN_39bs1rEXjVWF0kfP/media/2"
    )
    html = (
        "<html><head><title>Medford City Council Meeting 1-1-24</title></head><body>"
        "<script>Player.setupData['playlist'] = ["
        '{"title": "Medford City Council Meeting 1-1-24", "file": null, "tracks": []}'
        "];</script></body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await TelvueAssetFinder().resolve(url)

    assert result.jurisdiction == "Medford"


async def test_resolve_known_org_token_corrects_a_wrong_state_not_just_a_missing_one():
    # Real bug, confirmed live 2026-08-29 via the Common Crawl sweep: the
    # "fills missing state" widening above only fired when the guess had
    # no comma at all. It missed the case where enrich_jurisdiction_text()
    # resolves a bare, ambiguous name to the WRONG place instead of
    # leaving it bare -- "Newmarket" (from the title) enriched to
    # "Newmarket, ON" (a real, more prominent place of that name), when
    # this channel's own real content (newmarketnh.gov's own "Zoning
    # Board of Adjustment" page) confirms it's Newmarket, NH. The
    # base-name-only comparison (ignoring whatever state/country
    # enrichment guessed) corrects this the same way it fills a bare
    # name, without needing a separate code path.
    url = (
        "https://videoplayer.telvue.com/player/XSekkdEeRsk0JHQVHAvKJVka7_5VjxKP/media/1"
    )
    html = (
        "<html><head><title>Newmarket Zoning Board Meeting</title></head><body>"
        "<script>Player.setupData['playlist'] = ["
        '{"title": "Newmarket Zoning Board Meeting", "file": null, "tracks": []}'
        "];</script></body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await TelvueAssetFinder().resolve(url)

    assert result.jurisdiction == "Newmarket, NH"


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


def test_guess_jurisdiction_rejects_bare_governance_body_titles():
    # Real bug, confirmed live 2026-08-28 while enumerating TelVue
    # customers by search-dorking real player URLs: several real customers'
    # titles are just the meeting body's own name with no city prefix at
    # all -- "Select Board" (Goffstown, NH), "Planning Board 5-1-2025"
    # (Nashua, NH), "School Committee - Meeting March 12, 2026" (Yarmouth,
    # MA) -- so the leftmost-match regex happily captured "Select"/
    # "Planning"/"School" as if they were the city name. Real Census
    # lookup was tried as the validation gate first and reverted --
    # jurisdiction_data/places.csv only has 58 MA entries and doesn't
    # include Natick, so it would have also rejected real New England
    # towns (see test_guess_jurisdiction_handles_select_board above).
    assert TelvueAssetFinder._guess_jurisdiction("Select Board") is None
    assert TelvueAssetFinder._guess_jurisdiction("Planning Board 5-1-2025") is None
    assert (
        TelvueAssetFinder._guess_jurisdiction(
            "School Committee - Meeting March 12, 2026"
        )
        is None
    )
    # A real city name merged with an adjacent modifier word ("Summit, NJ"
    # + "Planning") is rejected too, same reasoning -- no reliable way to
    # separate the real name from the modifier without a validated match,
    # and declining beats guessing wrong.
    assert (
        TelvueAssetFinder._guess_jurisdiction(
            "Summit Planning Board Meeting: June 29, 2026"
        )
        is None
    )
    # Confirms the Natick fix still works: a real city name adjacent to
    # "Select" is preserved, only a *trailing* stopword is checked.
    assert (
        TelvueAssetFinder._guess_jurisdiction("Natick Select Board June 10, 2026")
        == "Natick"
    )


def test_guess_jurisdiction_strips_leading_date():
    # Real bug, confirmed live 2026-08-29 via the Common Crawl full-corpus
    # signature sweep (see BACKLOG_DONE.md's matching entry): unlike
    # _TITLE_DATE_RE's trailing "- Month DD, YYYY" shape, a title starting
    # with a numeric date has nothing for that regex to strip, so the date
    # itself flowed into _BODY_SUFFIX_RE and got captured as the
    # "jurisdiction" -- "2024-03-19 Town Board Meeting" produced
    # "2024-03-19 Town", "03/10/2025 Regular Council" produced
    # "03/10/2025 Regular". Both are confident wrong answers, not just a
    # missed one.
    assert (
        TelvueAssetFinder._guess_jurisdiction("2024-03-19 Town Board Meeting") is None
    )
    assert TelvueAssetFinder._guess_jurisdiction("03/10/2025 Regular Council") is None


def test_guess_jurisdiction_handles_zoning_board():
    # Real bug, confirmed live 2026-08-29, same shape as the Select Board
    # fix above: "Newmarket Zoning Board of Adjustments Meeting" matched
    # bare "Board" first, producing "Newmarket Zoning" instead of
    # "Newmarket" -- "Zoning Board" needed its own alternative ahead of
    # the bare "Board" one.
    assert (
        TelvueAssetFinder._guess_jurisdiction(
            "Newmarket Zoning Board of Adjustments Meeting"
        )
        == "Newmarket"
    )


def test_guess_jurisdiction_handles_planning_and_environmental_commission():
    # Real bug, confirmed live 2026-08-29, same shape as Select/Zoning
    # Board: "Vail Planning and Environmental Commission" matched bare
    # "Commission" first, producing "Vail Planning and Environmental"
    # instead of "Vail" -- Vail, CO's real governing body name needed
    # its own alternative ahead of the bare "Commission" one.
    assert (
        TelvueAssetFinder._guess_jurisdiction(
            "Vail Planning and Environmental Commission"
        )
        == "Vail"
    )
