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


async def test_resolve_falls_back_to_known_org_token_for_leominster():
    # Real case, found 2026-08-30 (WO-67) auditing the same TelVue batch
    # that surfaced the colon-date/"Common Council" gaps: real raw title
    # is a bare "Monday, August 24, 2026" (/m/monday-august-24-2026), no
    # body-suffix phrase for _guess_jurisdiction() to key on. Real
    # org-logo alt text confirmed live, "Leominster TV (MA) - Leominster
    # Access TV - organization logo" -- the state IS present but
    # parenthesized ("(MA)"), a shape the general org-logo parser
    # doesn't accept (only a trailing bare 2-letter abbreviation), so
    # only the known-org-token map closes this one.
    url = "https://videoplayer.telvue.com/player/m-2Fvz8xhxNtIFGMxiGzJrgCaIr0cVZT/media/1034895"
    html = (
        "<html><head><title>Monday, August 24, 2026</title></head><body>"
        '<img id="org-logo" alt="Leominster TV (MA) - Leominster Access TV '
        '- organization logo" />'
        "<script>Player.setupData['playlist'] = ["
        '{"title": "Monday, August 24, 2026", "file": null, "tracks": []}'
        "];</script></body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await TelvueAssetFinder().resolve(url)

    assert result.jurisdiction == "Leominster, MA"


async def test_resolve_falls_back_to_known_org_token_for_royal_oak():
    # Real case, found 2026-08-30 (WO-67), same batch/shape as Leominster
    # above: real raw title is a bare "City Commission (2026-08-24)"
    # (/m/2026-08-24-city-commission). Real org-logo alt text confirmed
    # live, "City of Royal Oak Michigan - Royal Oak VOD Player -
    # organization logo" -- the state is spelled out in full
    # ("Michigan") rather than a 2-letter abbreviation, which the general
    # org-logo parser's state check doesn't recognize, so only the
    # known-org-token map closes this one.
    url = "https://videoplayer.telvue.com/player/aOt1iJYvW4IQawSCE8Goebgvo0CdBFwN/media/884230"
    html = (
        "<html><head><title>City Commission (2026-08-24)</title></head><body>"
        '<img id="org-logo" alt="City of Royal Oak Michigan - Royal Oak VOD '
        'Player - organization logo" />'
        "<script>Player.setupData['playlist'] = ["
        '{"title": "City Commission (2026-08-24)", "file": null, "tracks": []}'
        "];</script></body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await TelvueAssetFinder().resolve(url)

    assert result.jurisdiction == "Royal Oak, MI"


async def test_resolve_falls_back_to_known_org_token_for_luverne():
    # Real case, found 2026-08-30 (WO-67), same batch/shape as Leominster/
    # Royal Oak above: real raw title is a bare "City Council Meeting
    # (2026-08-25)" (/m/2026-08-25-city-council-meeting). Real org-logo
    # alt text confirmed live, "City of Luverne - LuvTV VOD Player -
    # organization logo", has no state anywhere (same shape as Auburn
    # Hills/Nashua/Piscataway), so the general org-logo parser correctly
    # declines -- only the known-org-token map closes this one.
    # "Luverne" is nationally ambiguous (real places in MN and AL);
    # confirmed MN specifically via cityofluverne.org/luvtv.
    url = (
        "https://videoplayer.telvue.com/player/yHwj4ve7ki-YFodojv3bS3m9Y1sTcXCC/media/1"
    )
    html = (
        "<html><head><title>City Council Meeting (2026-08-25)</title></head><body>"
        '<img id="org-logo" alt="City of Luverne - LuvTV VOD Player - '
        'organization logo" />'
        "<script>Player.setupData['playlist'] = ["
        '{"title": "City Council Meeting (2026-08-25)", "file": null, "tracks": []}'
        "];</script></body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await TelvueAssetFinder().resolve(url)

    assert result.jurisdiction == "Luverne, MN"


async def test_resolve_falls_back_to_known_org_token_for_derry():
    # Real case, found 2026-08-31 (WO-89): org token from the site's own
    # real home-page listing (Town Council/Planning Board/Conservation
    # Commission series, real and active). Real org-logo alt text
    # confirmed live, "Derry CAM - Derry Gov. VOD - organization logo",
    # has no state anywhere (same shape as Luverne above), so the general
    # org-logo parser correctly declines. This one is more than just
    # unhelpful without the registry entry: `jurisdiction_enrich.
    # _table_lookup("Derry")` resolves to Derry, PA (a real borough) --
    # NH's own Derry never surfaces at that tier -- so a bare-name
    # fallback would confidently return the wrong state, not just miss
    # one. Confirmed NH via derrynh.org, the town's own real site.
    url = "https://videoplayer.telvue.com/player/CXN6V2zmqTebSQfLjvlDzEql3BwiQh_l/media/865668"
    html = (
        "<html><head><title>Town Council - 04/02/24</title></head><body>"
        '<img id="org-logo" alt="Derry CAM - Derry Gov. VOD - '
        'organization logo" />'
        "<script>Player.setupData['playlist'] = ["
        '{"title": "Town Council - 04/02/24", "file": null, "tracks": []}'
        "];</script></body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await TelvueAssetFinder().resolve(url)

    assert result.jurisdiction == "Derry, NH"


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


# WO-74, 2026-08-30: 16 real org tokens from a second CDX
# `collapse=urlkey:64` enumeration pass (see
# ~/Documents/rtr-business/research/cc_scan_data/telvue_batch2_verified.json
# and _methodology.md), each independently second-source-confirmed and
# resolve()-checked against the real, unmodified adapter before this WO.
# Every title/date/org-token/media-id below is copied verbatim from that
# research file's own `resolve_check`/`sample_media_url` fields, not
# invented -- these are synthetic HTML pages (per this repo's convention,
# exercising one already-real-verified logic branch), built from a real
# confirmed shape, not fabricated data.


async def test_resolve_falls_back_to_known_org_token_for_orange_ct():
    # Real title "Zoning Board of Appeals - Monday, November 3, 2025" has
    # no city prefix -- before WO-74 this matched bare "Board", capturing
    # "Zoning" as the jurisdiction. Fixed by adding "zoning" to
    # _guess_jurisdiction()'s last-word stopword list.
    url = "https://videoplayer.telvue.com/player/BUJHRRxhCf0u3AtXMrx7Sx7CjdW8zUFT/media/993225"
    html = (
        "<html><head><title>Zoning Board of Appeals - Monday, November 3, "
        "2025</title></head><body>"
        "<script>Player.setupData['playlist'] = ["
        '{"title": "Zoning Board of Appeals - Monday, November 3, 2025", '
        '"file": null, "tracks": []}'
        "];</script></body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await TelvueAssetFinder().resolve(url)

    assert result.jurisdiction == "Orange, CT"


async def test_resolve_falls_back_to_known_org_token_for_marlboro_township():
    # Real title "council 8-20-26 1" is bare, lowercase, no city prefix --
    # the title guess never matches at all.
    url = "https://videoplayer.telvue.com/player/1VSAEpYHq96Q6serFVh1RRX5Y_XOzuSA/media/1042012"
    html = (
        "<html><head><title>council 8-20-26 1</title></head><body>"
        "<script>Player.setupData['playlist'] = ["
        '{"title": "council 8-20-26 1", "file": null, "tracks": []}'
        "];</script></body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await TelvueAssetFinder().resolve(url)

    assert result.jurisdiction == "Marlboro Township, NJ"


async def test_resolve_falls_back_to_known_org_token_for_oradell():
    # Real title "mc 8 25 26f hd" is a cryptic lowercase abbreviation
    # ("mc" = Mayor & Council) with no city name.
    url = "https://videoplayer.telvue.com/player/1VW_MUovXoKdUW9jRAnqt0YBpoJ5zDVU/media/1042640"
    html = (
        "<html><head><title>mc 8 25 26f hd</title></head><body>"
        "<script>Player.setupData['playlist'] = ["
        '{"title": "mc 8 25 26f hd", "file": null, "tracks": []}'
        "];</script></body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await TelvueAssetFinder().resolve(url)

    assert result.jurisdiction == "Oradell, NJ"


async def test_resolve_falls_back_to_known_org_token_for_miami_beach():
    # Real title "Board of Adjustment Meeting: October 11, 2024" has no
    # city name anywhere.
    url = "https://videoplayer.telvue.com/player/0cCY8Wm5F5ODnSOeAaE0k0Lxsinvidcb/media/911387"
    html = (
        "<html><head><title>Board of Adjustment Meeting: October 11, "
        "2024</title></head><body>"
        "<script>Player.setupData['playlist'] = ["
        '{"title": "Board of Adjustment Meeting: October 11, 2024", '
        '"file": null, "tracks": []}'
        "];</script></body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await TelvueAssetFinder().resolve(url)

    assert result.jurisdiction == "Miami Beach, FL"


async def test_resolve_falls_back_to_known_org_token_for_berkley_mi():
    # Real title "Planning Commission" is bare, no city name. Distinct
    # org token from the earlier-known Oakland-County multi-city token
    # Hejq7tDUseFZXc46e8pIxdl8NpmSEupd -- a different (CMNtv) tenant that
    # also happens to cover Berkley.
    url = "https://videoplayer.telvue.com/player/EJtfn8ouxWiUp9uEPl2tc6q8wbMfpV1O/media/1042603"
    html = (
        "<html><head><title>Planning Commission</title></head><body>"
        "<script>Player.setupData['playlist'] = ["
        '{"title": "Planning Commission", "file": null, "tracks": []}'
        "];</script></body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await TelvueAssetFinder().resolve(url)

    assert result.jurisdiction == "Berkley, MI"


async def test_resolve_fixes_truckee_extra_town_word():
    # Real title "Truckee Town Council, August 11, 2026" used to resolve
    # "Truckee Town, CA" (extra "Town" word) instead of "Truckee, CA" --
    # fixed by adding "Town Council" as its own _BODY_SUFFIX_RE
    # alternative (parallel to "City Council"), so the guess is now bare
    # "Truckee", which already enriches correctly via the Census table.
    url = "https://videoplayer.telvue.com/player/EdhI2xtM1vAxHWMytVkqEFJ6vUupMLaS/media/1040083"
    html = (
        "<html><head><title>Truckee Town Council, August 11, 2026"
        "</title></head><body>"
        "<script>Player.setupData['playlist'] = ["
        '{"title": "Truckee Town Council, August 11, 2026", "file": null, '
        '"tracks": []}'
        "];</script></body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await TelvueAssetFinder().resolve(url)

    assert result.jurisdiction == "Truckee, CA"


async def test_resolve_falls_back_to_known_org_token_for_savannah():
    # Real title "Savannah City Council 2/8/24" guesses the correct bare
    # "Savannah" but with no state -- a state fill, same shape as the
    # Ashland/OR entry above.
    url = "https://videoplayer.telvue.com/player/KPxII4Dm-djtTqV7JZXpXeOM2kiyqvRV/media/861081"
    html = (
        "<html><head><title>Savannah City Council 2/8/24</title></head>"
        "<body>"
        "<script>Player.setupData['playlist'] = ["
        '{"title": "Savannah City Council 2/8/24", "file": null, '
        '"tracks": []}'
        "];</script></body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await TelvueAssetFinder().resolve(url)

    assert result.jurisdiction == "Savannah, GA"


async def test_resolve_falls_back_to_known_org_token_for_madison_nh():
    # The real sample checked ("A Brief History of Atkinson Park,
    # Madison, NH") is a non-meeting local-history video with no
    # body-suffix phrase, so the title guess comes up empty even though
    # the title text itself names the town -- _guess_jurisdiction() only
    # parses body-suffix shapes, not arbitrary place mentions. This org's
    # own org-logo alt text is empty, so only the registry entry closes
    # the gap.
    url = "https://videoplayer.telvue.com/player/YhjrGzjr53TBI-xqCQGATh6xTOfUjhiy/media/1041526"
    html = (
        "<html><head><title>A Brief History of Atkinson Park, Madison, "
        "NH</title></head><body>"
        "<script>Player.setupData['playlist'] = ["
        '{"title": "A Brief History of Atkinson Park, Madison, NH", '
        '"file": null, "tracks": []}'
        "];</script></body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await TelvueAssetFinder().resolve(url)

    assert result.jurisdiction == "Madison, NH"


async def test_resolve_falls_back_to_known_org_token_for_tewksbury():
    # Real title "Conservation Commission" is bare, no city prefix --
    # before WO-74 this matched bare "Commission", capturing
    # "Conservation" as the jurisdiction. Fixed by adding "conservation"
    # to _guess_jurisdiction()'s last-word stopword list.
    url = "https://videoplayer.telvue.com/player/eUhghhtERCG4gx5ywQy9U8mv66_FACrU/media/1040356"
    html = (
        "<html><head><title>Conservation Commission</title></head><body>"
        "<script>Player.setupData['playlist'] = ["
        '{"title": "Conservation Commission", "file": null, "tracks": []}'
        "];</script></body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await TelvueAssetFinder().resolve(url)

    assert result.jurisdiction == "Tewksbury, MA"


async def test_resolve_falls_back_to_known_org_token_for_gardner_ma():
    # Real title "Planning Board" is bare, no city name.
    url = "https://videoplayer.telvue.com/player/f8r896ULmGZtrF3mCzOdRbTTP_Wnx2Q1/media/1039988"
    html = (
        "<html><head><title>Planning Board</title></head><body>"
        "<script>Player.setupData['playlist'] = ["
        '{"title": "Planning Board", "file": null, "tracks": []}'
        "];</script></body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await TelvueAssetFinder().resolve(url)

    assert result.jurisdiction == "Gardner, MA"


async def test_resolve_falls_back_to_known_org_token_for_stoughton_wi():
    # Real title "City Council 7/28/26" is bare, no city name. Confirmed
    # specifically as the Wisconsin city (not Stoughton, MA, which has no
    # "City of" government) via cityofstoughton.com and wsto.tv.
    url = "https://videoplayer.telvue.com/player/fSUt1ChllWIwWn_g28Mu3g-avz7I94a_/media/1039958"
    html = (
        "<html><head><title>City Council 7/28/26</title></head><body>"
        "<script>Player.setupData['playlist'] = ["
        '{"title": "City Council 7/28/26", "file": null, "tracks": []}'
        "];</script></body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await TelvueAssetFinder().resolve(url)

    assert result.jurisdiction == "Stoughton, WI"


async def test_resolve_fixes_rome_ga_wrong_state_collision():
    # REAL BUG, not just a missing value: real title "Rome City
    # Commission Meeting: August 24th, 2026" used to resolve to "Rome
    # City, IN" -- enrich_jurisdiction_text() treating the captured name
    # "Rome City" (title guess matching bare "Commission" and pulling in
    # "City" as part of the name) as the real, small Indiana town of that
    # literal name. This asserts the FIXED value, not just a
    # missing-then-present check, since the old behavior was a confident
    # WRONG answer. Fixed by adding "City Commission" as its own
    # _BODY_SUFFIX_RE alternative (parallel to "City Council"), so the
    # guess is now bare "Rome" -- the registry entry then supplies the
    # state via the base-name-match branch. Confirmed via
    # romefloyd.com/rome/commission and floydcountyga.gov.
    url = "https://videoplayer.telvue.com/player/iOiDZeQipT8NNECGBd7HJNiDkuPUTlCw/media/1042473"
    html = (
        "<html><head><title>Rome City Commission Meeting: August 24th, "
        "2026</title></head><body>"
        "<script>Player.setupData['playlist'] = ["
        '{"title": "Rome City Commission Meeting: August 24th, 2026", '
        '"file": null, "tracks": []}'
        "];</script></body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await TelvueAssetFinder().resolve(url)

    # The old, wrong behavior -- guarded explicitly so a regression in
    # either the regex fix or the registry entry is caught, not just a
    # "not None" check.
    assert result.jurisdiction != "Rome City, IN"
    assert result.jurisdiction == "Rome, GA"


async def test_resolve_falls_back_to_known_org_token_for_walpole_ma():
    # Real title "School Committee" is bare, no city name.
    url = "https://videoplayer.telvue.com/player/uZcpghEaKQJJjrP2iCkoRSkyKbNZPvO-/media/1013923"
    html = (
        "<html><head><title>School Committee</title></head><body>"
        "<script>Player.setupData['playlist'] = ["
        '{"title": "School Committee", "file": null, "tracks": []}'
        "];</script></body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await TelvueAssetFinder().resolve(url)

    assert result.jurisdiction == "Walpole, MA"


async def test_resolve_fixes_long_hill_township_acronym_prefix():
    # Real title "LHT - Planing Board Mtg: 8-11-26" (a real source typo,
    # "Planing" for "Planning") used to resolve the literal "LHT -
    # Planing" as the jurisdiction. Fixed by declining any name starting
    # with a short (2-5 letter) all-caps acronym followed by " - " in
    # _guess_jurisdiction(), same shape as the existing bare "WB"/"MCS"
    # initialism reject.
    url = "https://videoplayer.telvue.com/player/ydrTBZKBSaGNTnGcCEGmbeMYupgFhhCk/media/1040015"
    html = (
        "<html><head><title>LHT - Planing Board Mtg: 8-11-26"
        "</title></head><body>"
        "<script>Player.setupData['playlist'] = ["
        '{"title": "LHT - Planing Board Mtg: 8-11-26", "file": null, '
        '"tracks": []}'
        "];</script></body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await TelvueAssetFinder().resolve(url)

    assert result.jurisdiction != "LHT - Planing"
    assert result.jurisdiction == "Long Hill Township, NJ"


async def test_resolve_falls_back_to_known_org_token_for_wilbraham_ma():
    # Real title "Select Board - 08-17-2026" is bare, no city name.
    url = "https://videoplayer.telvue.com/player/wCwBAXHtGCN-aqYz22Xuje-5ELUZawSc/media/1040989"
    html = (
        "<html><head><title>Select Board - 08-17-2026</title></head>"
        "<body>"
        "<script>Player.setupData['playlist'] = ["
        '{"title": "Select Board - 08-17-2026", "file": null, '
        '"tracks": []}'
        "];</script></body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await TelvueAssetFinder().resolve(url)

    assert result.jurisdiction == "Wilbraham, MA"


async def test_resolve_falls_back_to_known_org_token_for_pipestone_mn():
    # Real title "Pipestone City Council Meeting 7.6" guesses the correct
    # bare "Pipestone" but with no state -- a state fill, same shape as
    # the Ashland/OR and Savannah/GA entries above.
    url = "https://videoplayer.telvue.com/player/qDzDQ8k2993lxm2IqCNZjdoqxagPQUa_/media/1035486"
    html = (
        "<html><head><title>Pipestone City Council Meeting 7.6"
        "</title></head><body>"
        "<script>Player.setupData['playlist'] = ["
        '{"title": "Pipestone City Council Meeting 7.6", "file": null, '
        '"tracks": []}'
        "];</script></body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await TelvueAssetFinder().resolve(url)

    assert result.jurisdiction == "Pipestone, MN"


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
    # Was: "Summit Planning Board Meeting: June 29, 2026" -> None, on the
    # reasoning that a city name merged with an adjacent modifier word
    # ("Summit" + "Planning") can't be reliably separated without a
    # validated match. WO-67 (2026-08-30) corrected this: Summit, NJ's
    # real title has exactly this shape (confirmed live,
    # /m/summit-planning-board-meeting-august-17-2026, real raw title
    # "Summit Planning Board Meeting: August 17, 2026"), and "Planning
    # Board" is itself a real, common governing-body name (same as
    # "Select Board"/"Zoning Board" above) -- giving it its own
    # alternative in _BODY_SUFFIX_RE resolves the ambiguity the same way
    # those two did, rather than needing a validated lookup.
    assert (
        TelvueAssetFinder._guess_jurisdiction(
            "Summit Planning Board Meeting: June 29, 2026"
        )
        == "Summit"
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


async def test_split_title_date_handles_colon_separator():
    # Real bug, confirmed live 2026-08-30 (WO-67): Summit, NJ's real raw
    # title uses a colon, not the dash every prior sample used --
    # "Summit Planning Board Meeting: August 17, 2026" (fetched live from
    # /m/summit-planning-board-meeting-august-17-2026). Before this fix
    # _TITLE_DATE_RE only matched a trailing "- Month DD, YYYY" shape, so
    # the whole string reached _guess_jurisdiction() with the date still
    # attached and the page resolved with a blank jurisdiction.
    title, date = TelvueAssetFinder._split_title_date(
        "Summit Planning Board Meeting: August 17, 2026"
    )
    assert title == "Summit Planning Board Meeting"
    assert date == "2026-08-17"


def test_guess_jurisdiction_handles_planning_board():
    # Real bug, confirmed live 2026-08-30 (WO-67), same shape as the
    # Select Board / Zoning Board fixes above: once the colon-date fix
    # strips the trailing date, Summit, NJ's real title is "Summit
    # Planning Board Meeting" -- without its own alternative this matched
    # bare "Board" first, capturing "Summit Planning" (rejected outright
    # by the "planning" stopword below, so the meeting resolved with no
    # jurisdiction at all rather than a wrong one).
    assert (
        TelvueAssetFinder._guess_jurisdiction("Summit Planning Board Meeting")
        == "Summit"
    )


def test_guess_jurisdiction_handles_common_council():
    # Real bug, confirmed live 2026-08-30 (WO-67): Albany, NY's real raw
    # title is "Albany Common Council 08 03 26" (fetched live from
    # /m/albany-common-albany-common-council-08-03-26, no dash/colon
    # date suffix for _TITLE_DATE_RE to strip at all, so the whole string
    # reaches _guess_jurisdiction() as-is). "Common Council" is Albany's
    # real governing-body name; without its own alternative this matched
    # bare "Council" first, capturing "Albany Common" -- a confident WRONG
    # answer (reads like a plausible place name on its own), not just a
    # missed one, same failure family as the Natick/Newmarket/Vail cases
    # above.
    assert (
        TelvueAssetFinder._guess_jurisdiction("Albany Common Council 08 03 26")
        == "Albany"
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


def test_guess_jurisdiction_rejects_short_allcaps_initialisms():
    # Real bug, confirmed live 2026-08-29 auditing archived pages missing
    # a jurisdiction: "WB Board of Selectmen Mtg" (West Bridgewater, MA)
    # and "MCS Board Mtg." both matched with a 2-3 letter all-caps
    # initialism as the captured name -- no real US/CA jurisdiction is
    # a bare short all-caps initialism, so this must decline rather than
    # store "WB"/"MCS" verbatim.
    assert (
        TelvueAssetFinder._guess_jurisdiction(
            "WB Board of Selectmen Mtg: - March 20th, 2024"
        )
        is None
    )
    assert TelvueAssetFinder._guess_jurisdiction("MCS Board Mtg.") is None
    # A real, longer place name must still pass through untouched -- this
    # guard is keyed on length + case, not a blanket rejection of any
    # short-looking prefix.
    assert TelvueAssetFinder._guess_jurisdiction("Delta Board Meeting") == "Delta"


def test_guess_jurisdiction_rejects_bare_zoning_and_conservation():
    # WO-74, 2026-08-30: real bare titles from the CDX batch-2 pass --
    # Orange, CT's "Zoning Board of Appeals - Monday, November 3, 2025"
    # and Tewksbury, MA's "Conservation Commission" -- both have no city
    # prefix, so the leftmost-match search used to capture the modifier
    # word ("Zoning"/"Conservation") as the jurisdiction. Same
    # governance-generic shape as the existing select/planning/school/
    # regular stopwords.
    assert (
        TelvueAssetFinder._guess_jurisdiction(
            "Zoning Board of Appeals - Monday, November 3, 2025"
        )
        is None
    )
    assert TelvueAssetFinder._guess_jurisdiction("Conservation Commission") is None


def test_guess_jurisdiction_handles_city_commission():
    # WO-74, 2026-08-30: same shape as the existing "City Council" fix --
    # Rome, GA's real "Rome City Commission Meeting: August 24th, 2026"
    # used to match bare "Commission", capturing "Rome City" (which
    # enrich_jurisdiction_text() then resolved to the wrong "Rome City,
    # IN"). "City Commission" as its own _BODY_SUFFIX_RE alternative
    # correctly captures just "Rome".
    assert (
        TelvueAssetFinder._guess_jurisdiction(
            "Rome City Commission Meeting: August 24th, 2026"
        )
        == "Rome"
    )


def test_guess_jurisdiction_handles_town_council():
    # WO-74, 2026-08-30: same shape as City Commission above -- Truckee,
    # CA's real "Truckee Town Council, August 11, 2026" used to match
    # bare "Council", capturing "Truckee Town" instead of "Truckee".
    # "Town Council" as its own _BODY_SUFFIX_RE alternative fixes it.
    assert (
        TelvueAssetFinder._guess_jurisdiction("Truckee Town Council, August 11, 2026")
        == "Truckee"
    )


def test_guess_jurisdiction_rejects_acronym_dash_prefix():
    # WO-74, 2026-08-30: Long Hill Township, NJ's real "LHT - Planing
    # Board Mtg: 8-11-26" (a real source typo, "Planing" for "Planning")
    # used to store the literal "LHT - Planing" as the jurisdiction. The
    # leading short all-caps acronym followed by " - " is the same
    # unreliable shape as the existing bare "WB"/"MCS" initialism reject,
    # just with a dash-separated continuation.
    assert (
        TelvueAssetFinder._guess_jurisdiction("LHT - Planing Board Mtg: 8-11-26")
        is None
    )
    # A real, longer prefix that happens to contain a dash must still
    # pass through -- this guard is keyed on a SHORT leading acronym
    # specifically, not any name containing a dash.
    assert (
        TelvueAssetFinder._guess_jurisdiction("Winston-Salem Board Meeting")
        == "Winston-Salem"
    )
