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


async def test_resolve_falls_back_to_known_org_token_for_talk_show_titled_meeting():
    # Real case, found 2026-08-29 auditing archived pages missing a
    # jurisdiction: "Eye on Piscataway August 2026" is a talk-show-style
    # title with no "X Board/Council" suffix at all, so _guess_jurisdiction()
    # never runs its regex successfully, and the real org-logo alt text
    # ("Piscataway Community TV - Piscataway Community TV VOD Player") has
    # no explicit state for the general org-logo parser to key on either
    # -- only the known-org-token map closes this one.
    url = "https://videoplayer.telvue.com/player/Uf_haH9SRhiC9hGsGoevnFKJwHM7n6eY/media/1039761"
    html = (
        "<html><head><title>Eye on Piscataway August 2026.</title></head><body>"
        '<img id="org-logo" alt="Piscataway Community TV - Piscataway Community TV '
        'VOD Player - organization logo" />'
        "<script>Player.setupData['playlist'] = ["
        '{"title": "Eye on Piscataway August 2026.", "file": null, "tracks": []}'
        "];</script></body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await TelvueAssetFinder().resolve(url)

    assert result.jurisdiction == "Piscataway, NJ"


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


async def test_resolve_uses_known_org_token_when_org_logo_alt_text_declines():
    # Auburn Hills, MI's real org token, added 2026-08-29 alongside the
    # messy-org-name parser above -- integration check that when BOTH the
    # title guess (a bare "City Council Meeting", no city prefix) AND the
    # org-logo alt-text parser (real shape, no explicit state -- see
    # test_org_logo_jurisdiction_declines_bare_name_with_no_stated_state)
    # come up empty, _KNOWN_ORG_TOKEN_JURISDICTIONS still lands on the
    # real, hand-verified answer end to end through resolve(), not just
    # in the two helpers tested in isolation above.
    url = (
        "https://videoplayer.telvue.com/player/RbS8sAKYVBOy0BmYID5GwGYZw1XwFiLb/media/1"
    )
    html = (
        "<html><head><title>City Council Meeting 1-1-24</title></head><body>"
        '<img id="org-logo" alt="CMNtv Chris Weagel for Auburn Hills Govt '
        'Cable - Auburn Hills Live and VoD - organization logo" '
        'src="/x.png" />'
        "<script>Player.setupData['playlist'] = ["
        '{"title": "City Council Meeting 1-1-24", "file": null, "tracks": []}'
        "];</script></body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await TelvueAssetFinder().resolve(url)

    assert result.jurisdiction == "Auburn Hills, MI"


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


def test_org_logo_jurisdiction_accepts_clean_city_state_alt_text():
    # Real shape, confirmed live 2026-08-29 (Irondequoit, NY,
    # media id 865360): both dash-separated halves of the alt text are
    # identical and already "City, ST"-shaped, which is specific enough
    # to trust without a lookup.
    html = '<img id="org-logo" alt="Irondequoit, NY - Irondequoit, NY - organization logo" src="/x.png" />'
    assert TelvueAssetFinder._org_logo_jurisdiction(html) == "Irondequoit, NY"


def test_org_logo_jurisdiction_rejects_org_name_alt_text():
    # Real shape from the Ashland/RVTV fixture -- the two halves differ
    # ("Rogue Valley Community Television (RVTV)" vs. "Watch RVTV") and
    # neither is "City, ST"-shaped, so this must decline rather than
    # guess "Rogue Valley Community Television (RVTV)" is a jurisdiction.
    html = load_fixture("telvue", "ashland_planning_1040134_page.html")
    assert TelvueAssetFinder._org_logo_jurisdiction(html) is None


def test_org_logo_jurisdiction_handles_missing_tag():
    assert TelvueAssetFinder._org_logo_jurisdiction("<html></html>") is None


# --- Messy-org-name parser (2026-08-29) -- BACKLOG.md's "TelVue's
# jurisdiction extraction still can't parse a *messy* org name" entry.
# Every alt text below is a real, live-fetched sample from a real TelVue
# customer's own `id="org-logo"` tag (see telvue.py's own module comment
# above `_ORG_LOGO_LEADING_ENTITY_RE` for the full list and how each was
# found) -- these are synthetic HTML fixtures per this repo's own
# synthetic-test convention (the underlying alt-text shapes are already
# live-confirmed, only the wrapping `<img>` tag here is hand-built).


def test_org_logo_jurisdiction_strips_access_tv_and_keeps_stated_state():
    # Real alt text, Fitchburg MA's org token (yycCAZPb0NN3zj2o5qio-
    # YFMNC43NjCG), confirmed live 2026-08-29: "Fitchburg Access TV -
    # Fitchburg MA VOD Player". "Fitchburg" alone is nationally ambiguous
    # (real places in both MA and WI per the Census table), but the state
    # is spelled out right in the second half -- no lookup needed.
    html = (
        '<img id="org-logo" alt="Fitchburg Access TV - Fitchburg MA VOD '
        'Player - organization logo" src="/x.png" />'
    )
    assert TelvueAssetFinder._org_logo_jurisdiction(html) == "Fitchburg, MA"


def test_org_logo_jurisdiction_strips_leading_town_of_and_trailing_tagline():
    # Real alt text, Orleans MA's org token (zzV8HNURw1G02-ue3glR7BRTpI-
    # bknlL), confirmed live 2026-08-29: "Town of Orleans MA - Town of
    # Orleans Video on Demand". Needs both a leading "Town of" strip and
    # a trailing "Video on Demand" strip before the state is visible.
    html = (
        '<img id="org-logo" alt="Town of Orleans MA - Town of Orleans '
        'Video on Demand - organization logo" src="/x.png" />'
    )
    assert TelvueAssetFinder._org_logo_jurisdiction(html) == "Orleans, MA"


def test_org_logo_jurisdiction_handles_three_dash_separated_segments():
    # Real alt text, Nashua NH's org token (LGzST4YdA6GIkRCa0H5CwbVBptJR
    # J3XD), confirmed live 2026-08-29: "NCM - Nashua Community Media -
    # Nashua Government TV" -- three segments, not two, so the parser
    # must not assume there are exactly 2 dash-separated halves. Neither
    # "Nashua Community Media" nor "Nashua Government TV" states a
    # state, and "Nashua" alone is nationally ambiguous (IA/MN/NH/MT per
    # the Census table) -- correctly declines rather than guess NH from
    # world knowledge. (Real jurisdiction added to
    # _KNOWN_ORG_TOKEN_JURISDICTIONS instead, confirmed via nashuanh.gov.)
    html = (
        '<img id="org-logo" alt="NCM - Nashua Community Media - Nashua '
        'Government TV - organization logo" src="/x.png" />'
    )
    assert TelvueAssetFinder._org_logo_jurisdiction(html) is None


def test_org_logo_jurisdiction_declines_bare_name_with_no_stated_state():
    # Real alt text, Auburn Hills MI's org token (RbS8sAKYVBOy0BmYID5Gw
    # GYZw1XwFiLb), confirmed live 2026-08-29: "CMNtv Chris Weagel for
    # Auburn Hills Govt Cable - Auburn Hills Live and VoD". The second
    # half reduces cleanly to bare "Auburn Hills" after stripping "Live
    # and VoD", but there's no state anywhere in the text -- this parser
    # never falls back to a Census lookup to fill one in (see telvue.py's
    # module comment for why: that's exactly what produced the real
    # Needham -> "AL" bug), so it declines even though "Auburn Hills" is
    # otherwise unambiguous. (Real jurisdiction added to
    # _KNOWN_ORG_TOKEN_JURISDICTIONS instead, confirmed via
    # auburnhills.org.)
    html = (
        '<img id="org-logo" alt="CMNtv Chris Weagel for Auburn Hills '
        'Govt Cable - Auburn Hills Live and VoD - organization logo" '
        'src="/x.png" />'
    )
    assert TelvueAssetFinder._org_logo_jurisdiction(html) is None


def test_org_logo_jurisdiction_never_reintroduces_the_needham_al_bug():
    # Real alt text, Needham MA's org token (O7e6JrKKSJ3H_TX3VgEvpbSSL7
    # Dbnrk2), confirmed live 2026-08-29: "The Needham Channel - Needham
    # Community TV VOD Player". Stripping "Community TV" and "VOD Player"
    # from the second half reduces it to bare "Needham" -- and
    # jurisdiction_enrich.lookup_city_state("Needham") really does return
    # "AL" (confirmed live 2026-08-29: places.csv has no Needham, MA
    # entry at all), the exact wrong-state bug already fixed once for the
    # title-guess path via this org's own _KNOWN_ORG_TOKEN_JURISDICTIONS
    # entry. This test exists so a future change that adds a Census-
    # lookup fallback to _reduce_org_logo_piece() gets caught
    # immediately, not just by ordering (the known-token map already
    # protects production because it's checked first).
    html = (
        '<img id="org-logo" alt="The Needham Channel - Needham Community '
        'TV VOD Player - organization logo" src="/x.png" />'
    )
    assert TelvueAssetFinder._org_logo_jurisdiction(html) is None


def test_org_logo_jurisdiction_declines_real_org_name_that_is_not_a_place():
    # Real alt text, Vail CO's org token (YGktjFZCLukJd_8Fx53BkVRk4tAZa
    # fS4), confirmed live 2026-08-29: "High Five Access Media - High
    # Five Access Media" -- both halves IDENTICAL, which would have
    # passed the narrow original "identical halves" check's spirit if
    # "Access Media" were treated as a strippable tagline. "High Five
    # Access Media" is the real Eagle County, CO nonprofit media
    # organization's own name (not Vail), which is exactly why "Access
    # Media" is deliberately excluded from _ORG_LOGO_TRAILING_STOPWORDS
    # -- stripping it would produce a confident, wrong "High Five".
    html = (
        '<img id="org-logo" alt="High Five Access Media - High Five '
        'Access Media - organization logo" src="/x.png" />'
    )
    assert TelvueAssetFinder._org_logo_jurisdiction(html) is None


def test_org_logo_jurisdiction_declines_when_no_segment_states_a_place():
    # Real alt text, a State College PA-serving org token
    # (GNduNoua2rBThhw6N4PRP9OCSPf6B2ru, from jurisdiction_coverage.csv),
    # confirmed live 2026-08-29: "CNET - C-NET VOD Player". Stripping
    # "VOD Player" from the second half leaves "C-NET", an acronym that
    # doesn't reduce to any place name -- correctly declines.
    html = (
        '<img id="org-logo" alt="CNET - C-NET VOD Player - organization '
        'logo" src="/x.png" />'
    )
    assert TelvueAssetFinder._org_logo_jurisdiction(html) is None


def test_org_logo_jurisdiction_stopword_loop_strips_multiple_phrases():
    # Real alt text shape, Everett MA's org token (cT30AQ_xtOBQF0oJM2gIV
    # CDX9kjgfWZb), confirmed live 2026-08-29: "Everett Community TV -
    # Everett Community TV VOD Player". The second half needs BOTH "VOD
    # Player" and "Community TV" stripped in sequence to reach bare
    # "Everett" -- exercises the strip-until-stable loop directly. No
    # state is present anywhere, so this still declines ("Everett" is
    # also nationally ambiguous: MA/WA/PA per the Census table).
    html = (
        '<img id="org-logo" alt="Everett Community TV - Everett '
        'Community TV VOD Player - organization logo" src="/x.png" />'
    )
    assert TelvueAssetFinder._org_logo_jurisdiction(html) is None


def test_org_logo_jurisdiction_already_known_riverhead_shape_still_works():
    # Real alt text, Riverhead NY's org token (BjiipOg61Ac-YpNM5RFZy8f49
    # fIMR7Kq), confirmed live 2026-08-29: "Town of Riverhead, NY - Town
    # of Riverhead, New York". First half strips the leading "Town of"
    # and is already comma-state-shaped; second half's spelled-out "New
    # York" doesn't match the two-letter-abbreviation check and is
    # simply ignored (not a conflict) since the two halves agree on the
    # base city name "Riverhead". This org token is already hand-curated
    # in _KNOWN_ORG_TOKEN_JURISDICTIONS -- this test just confirms the
    # general parser independently reaches the same real answer.
    html = (
        '<img id="org-logo" alt="Town of Riverhead, NY - Town of '
        'Riverhead, New York - organization logo" src="/x.png" />'
    )
    assert TelvueAssetFinder._org_logo_jurisdiction(html) == "Riverhead, NY"


def test_org_logo_jurisdiction_declines_on_disagreeing_segments():
    # Synthetic (no real sample has this exact shape) -- exercises the
    # cross-segment-agreement check directly: two segments that each
    # independently reduce to a state-bearing place, but a DIFFERENT one,
    # must decline rather than pick either guess.
    html = (
        '<img id="org-logo" alt="Springfield MA VOD Player - Springfield '
        'OH VOD Player - organization logo" src="/x.png" />'
    )
    assert TelvueAssetFinder._org_logo_jurisdiction(html) is None
