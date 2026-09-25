"""Tests for `scripts/hub_harvest.py` (WO-1053).

`ictv_root.html` and `telvue_centre_county_home.html` are real pages,
fetched live 2026-09-24 from `reflect-ictv.cablecast.tv/` (Iron Range TV)
and `videoplayer.telvue.com/player/GNduNoua2rBThhw6N4PRP9OCSPf6B2ru/home`
(Centre County C-NET) -- see `regional_tv_hubs.csv`'s own notes for how
each host was found. No test here makes a network call; the harvester's
own fetch functions are exercised only against these saved real pages.
"""

from pathlib import Path

from scripts import hub_harvest

FIXTURES = Path(__file__).parent / "fixtures" / "hub_harvest"


def _hub(**overrides) -> hub_harvest.HubRow:
    defaults = dict(
        hub="Test Hub",
        platform="cablecast_remix",
        url="https://example.cablecast.tv/",
        region_state="MN",
        notes="",
    )
    defaults.update(overrides)
    return hub_harvest.HubRow(**defaults)


class TestRemixExtraction:
    """Real Iron Range TV page -- the hub behind the Nashwauk/Wilder
    finding (Ryan, 2026-09-24): this tenant carries several Iron Range
    cities as separate galleries on one site, and Nashwauk and Cohasset
    are two distinct, real galleries with their own real shows, not one
    government's video misfiled as another's."""

    def setup_method(self):
        self.html = (FIXTURES / "ictv_root.html").read_text(encoding="utf-8")
        self.data = hub_harvest._extract_remix_context(self.html)

    def test_remix_context_parses(self):
        assert self.data is not None

    def test_site_object_found(self):
        site = hub_harvest._find_site_object(self.data)
        assert site is not None
        # siteId is a string on this real page ("1") -- compared loosely,
        # same as `_harvest_cablecast_remix()`'s own `site_id` handling.
        assert str(site.get("siteId")) == "1"

    def test_nashwauk_and_cohasset_are_distinct_real_galleries(self):
        galleries = hub_harvest._find_all(
            self.data, lambda o: "cablecastGalleryId" in o
        )
        by_title = {g["title"]: g for g in galleries}
        assert "Nashwauk City Council" in by_title
        assert "Cohasset City Council" in by_title
        # Different galleries, different real show catalogs -- the whole
        # point: a video from one must never stand in for the other.
        nashwauk_shows = {
            s["showId"] for s in by_title["Nashwauk City Council"]["shows"]
        }
        cohasset_shows = {
            s["showId"] for s in by_title["Cohasset City Council"]["shows"]
        }
        assert nashwauk_shows.isdisjoint(cohasset_shows)

    def test_newest_show_picks_latest_event_date(self):
        galleries = hub_harvest._find_all(
            self.data, lambda o: "cablecastGalleryId" in o
        )
        nashwauk = next(g for g in galleries if g["title"] == "Nashwauk City Council")
        newest = hub_harvest._newest_show(nashwauk["shows"])
        assert newest is not None
        assert newest["title"] == "Nashwauk City Council - 09-08-2026"


class TestNashwaukWilderMatching:
    """The actual government-matching outcome for the two governments
    Ryan named -- pure registry lookups, no network."""

    def test_nashwauk_city_council_matches_real_place(self):
        match = hub_harvest.resolver.resolve_government(
            hub_harvest._resolver_candidate_text("Nashwauk City Council") + ", MN",
            tenant_host="reflect-ictv.cablecast.tv",
        )
        assert match.gov_id == "us:place:2744980"
        assert match.tier in (
            hub_harvest.resolver.TIER_REGISTRY,
            hub_harvest.resolver.TIER_PINNED,
        )

    def test_wilder_city_council_matches_real_place(self):
        match = hub_harvest.resolver.resolve_government(
            hub_harvest._resolver_candidate_text("Wilder City Council") + ", KY",
            tenant_host="reflect-campbellcounty.cablecast.tv",
        )
        assert match.gov_id == "us:place:2183172"
        assert match.tier in (
            hub_harvest.resolver.TIER_REGISTRY,
            hub_harvest.resolver.TIER_PINNED,
        )

    def test_bare_city_council_without_meeting_word_would_mint_instead(self):
        """Documents the real gap `_resolver_candidate_text()` works
        around: without appending "Meeting", `finalize_jurisdiction()`
        does not repair "X City Council, ST" to the place name, and the
        resolver mints a new id instead of finding the real one."""
        match = hub_harvest.resolver.resolve_government(
            "Nashwauk City Council, MN", tenant_host="reflect-ictv.cablecast.tv"
        )
        assert match.gov_id != "us:place:2744980"
        assert match.tier == hub_harvest.resolver.TIER_UNVERIFIED


class TestResolverCandidateText:
    def test_appends_meeting_when_missing(self):
        assert hub_harvest._resolver_candidate_text("Nashwauk City Council") == (
            "Nashwauk City Council Meeting"
        )

    def test_leaves_existing_meeting_suffix_alone(self):
        assert (
            hub_harvest._resolver_candidate_text("Anoka County Board Meetings")
            == "Anoka County Board Meetings"
        )

    def test_empty_text_stays_empty(self):
        assert hub_harvest._resolver_candidate_text("") == ""


class TestLooksLikeAGovernmentBody:
    """Real section titles seen live 2026-09-24 -- see
    `regional_tv_hubs.csv` for where each one came from."""

    def test_recognizes_two_word_phrases(self):
        assert hub_harvest._looks_like_a_government_body("Nashwauk City Council")
        assert hub_harvest._looks_like_a_government_body(
            "Halfmoon Township Board of Supervisors"
        )

    def test_recognizes_loose_single_word_forms(self):
        # Real Centre County C-NET playlist titles that don't contain any
        # exact _BODY_TYPE_WORDS phrase but clearly name a governing body.
        assert hub_harvest._looks_like_a_government_body(
            "Borough of State College - Council"
        )
        assert hub_harvest._looks_like_a_government_body("College Township Council")

    def test_rejects_non_government_programming(self):
        assert not hub_harvest._looks_like_a_government_body("Bad Movie Bros")
        assert not hub_harvest._looks_like_a_government_body(
            "Exercise at Home with Sue Thomas"
        )


class TestTelvueCardExtraction:
    def setup_method(self):
        self.html = (FIXTURES / "telvue_centre_county_home.html").read_text(
            encoding="utf-8"
        )

    def test_finds_real_playlist_cards(self):
        cards = hub_harvest._TELVUE_CARD_RE.findall(self.html)
        titles = {title.strip() for _, title in cards}
        assert "Borough of Bellefonte - Council" in titles
        assert "College Township Council" in titles
        assert "Halfmoon Township Board of Supervisors" in titles

    def test_card_path_carries_playlist_and_media_id(self):
        cards = hub_harvest._TELVUE_CARD_RE.findall(self.html)
        by_title = {title.strip(): path for path, title in cards}
        path = by_title["Borough of Bellefonte - Council"]
        assert "/playlists/4806/media/" in path


class TestDedupeSections:
    """Synthetic: a shared county body syndicated onto several member
    cities' own site pages (the real North Metro TV "Anoka County Board
    Meetings" shape confirmed live 2026-09-24 -- see
    `regional_tv_hubs.csv`) collapses to one row; two genuinely different
    sections do not collapse into each other."""

    def test_same_section_and_video_collapses_once(self):
        hub = _hub()
        rows = [
            hub_harvest._section(
                hub,
                section="Anoka County Board Meetings",
                newest_url="https://example.cablecast.tv/vod/1.m3u8",
                matched_gov_id="us:county:27003",
            )
            for _ in range(3)
        ]
        deduped = hub_harvest._dedupe_sections(rows)
        assert len(deduped) == 1

    def test_different_sections_are_kept(self):
        hub = _hub()
        rows = [
            hub_harvest._section(
                hub,
                section="Nashwauk City Council",
                newest_url="https://example.cablecast.tv/vod/nashwauk.m3u8",
                matched_gov_id="us:place:2744980",
            ),
            hub_harvest._section(
                hub,
                section="Cohasset City Council",
                newest_url="https://example.cablecast.tv/vod/cohasset.m3u8",
                matched_gov_id="us:place:2712412",
            ),
        ]
        deduped = hub_harvest._dedupe_sections(rows)
        assert len(deduped) == 2


class TestLoadHubs:
    def test_seed_csv_loads_and_has_expected_hubs(self):
        hubs = hub_harvest.load_hubs()
        names = {h.hub for h in hubs}
        assert "Iron Range TV Cablecast" in names
        assert "Pierce County TV" in names
        for hub in hubs:
            assert hub.platform in hub_harvest._HARVESTERS


class TestPierceCountyNeverTouchesYoutube:
    """Constraint from the brief: Pierce County TV is YouTube-drip-only.
    `_harvest_youtube_hub()` must never issue a network request of its
    own -- it is passed a session but must not use it."""

    def test_harvest_makes_no_network_call(self):
        import asyncio

        class ExplodingSession:
            def get(self, *args, **kwargs):  # pragma: no cover - must not run
                raise AssertionError("youtube_hub harvester must never fetch anything")

        hub = _hub(
            hub="Pierce County TV",
            platform="youtube_hub",
            url="https://www.piercecountytv.org/",
            region_state="WA",
        )
        sections, error = asyncio.run(
            hub_harvest._harvest_youtube_hub(ExplodingSession(), hub)
        )
        assert error is None
        assert len(sections) == len(hub_harvest._PIERCE_COUNTY_SECTIONS)
        for section in sections:
            assert "youtube" not in section.newest_url.lower()
