"""Per-state SEO landing pages (/state/{slug}) plus their /coverage and
meeting-page entry points. Seeded rows use real, Census-valid cities
(repo convention: synthetic payloads reuse confirmed-real facts) and
unique external_ids/source_urls per the shared-session-DB convention
(tests/conftest.py). The key regression case: the state match is an
anchored ", CA" suffix match, never list_pages()-style substring ilike --
"Decatur, GA" contains "ca" and must not appear on /state/california.
"""

import json
import re

from fastapi.testclient import TestClient

import app.main
import archive.main
from archive.db import crud
from archive.utils.jurisdiction_format import jurisdiction_hub_slug

client = TestClient(archive.main.app)

_JSON_LD_RE = re.compile(
    r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>', re.DOTALL
)


def _payload(
    external_id: str,
    source_url: str,
    *,
    platform: str = "granicus",
    jurisdiction: str = "Napa, CA",
    title: str = "State Page Test Meeting",
    date: str = "2026-03-03",
    segments=None,
) -> dict:
    return {
        "platform": platform,
        "source_url": source_url,
        "external_id": external_id,
        "title": title,
        "date": date,
        "jurisdiction": jurisdiction,
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": segments
        if segments is not None
        else [{"start": 0, "end": 1, "text": "hello state pages"}],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }


async def _seed(external_id: str, **kwargs) -> str:
    url = f"https://example.com/state-seed/{external_id}"
    result = await crud.ingest_resolution(_payload(external_id, url, **kwargs), url)
    return result["slug"]


async def _seed_all():
    slugs = {}
    slugs["napa"] = await _seed(
        "granicus:state-napa", jurisdiction="Napa, CA", title="Napa City Council"
    )
    slugs["sacramento"] = await _seed(
        "granicus:state-sacramento",
        jurisdiction="Sacramento County, CA",
        title="Sacramento County Board",
    )
    slugs["decatur"] = await _seed(
        "granicus:state-decatur", jurisdiction="Decatur, GA", title="Decatur Commission"
    )
    # Coalinga: a real Census place (places.csv: "Coalinga city, CA"),
    # picked over a bigger city because no other test in the shared
    # session DB seeds it -- tests/test_civicclerk.py seeds its own
    # indexable "Fresno, CA" row, which made jurisdiction-level exclusion
    # assertions on Fresno collide when the full suite runs.
    slugs["coalinga_unknown"] = await _seed(
        "unknown:state-coalinga",
        platform="unknown",
        jurisdiction="Coalinga, CA",
        title="Coalinga Generic Fallback Meeting",
    )
    # Calgary, AB: a real, already-archived Canadian jurisdiction
    # (confirmed live on /coverage as of 2026-08-17), not an invented one
    # -- exercises the "Browse by state"/"Browse by province" country
    # split and the /state/{slug} route for a province slug.
    slugs["calgary"] = await _seed(
        "granicus:state-calgary",
        jurisdiction="Calgary, AB",
        title="Calgary City Council",
    )
    return slugs


async def test_state_page_lists_states_jurisdictions():
    slugs = await _seed_all()
    response = client.get("/state/california")
    assert response.status_code == 200
    assert "Napa" in response.text
    assert "Sacramento County" in response.text
    assert f"/m/{slugs['napa']}" in response.text


async def test_state_page_anchored_match_excludes_substring_hits():
    slugs = await _seed_all()
    # "Decatur, GA" contains "ca" -- a substring ilike would leak it into
    # California. The anchored ", CA" suffix match must not.
    ca = client.get("/state/california")
    assert "Decatur" not in ca.text
    ga = client.get("/state/georgia")
    assert ga.status_code == 200
    assert "Decatur" in ga.text
    assert f"/m/{slugs['decatur']}" in ga.text


async def test_state_page_excludes_unknown_platform_pages():
    slugs = await _seed_all()
    response = client.get("/state/california")
    assert slugs["coalinga_unknown"] not in response.text
    assert "Coalinga Generic Fallback Meeting" not in response.text


def test_state_page_unknown_slug_404():
    response = client.get("/state/nowhere")
    assert response.status_code == 404


def test_state_page_empty_state_404():
    # Wyoming is *reserved* as the state no test seeds, so a real state
    # with zero indexable pages 404s rather than rendering an empty
    # shell. The fixture DB is shared and never reset, so seeding a ", WY"
    # jurisdiction anywhere in the suite breaks this test and three others
    # below -- and only in a full run, never in isolation (real
    # occurrence, 2026-08-24, WO-51). If you need a throwaway state, use
    # any other real abbreviation.
    response = client.get("/state/wyoming")
    assert response.status_code == 404


async def test_state_page_seo_meta():
    await _seed_all()
    response = client.get("/state/california")
    assert "California public meeting videos" in response.text
    assert "noindex" not in response.text
    # Canonical is self-referential (unlike /meetings' deliberately
    # filter-blind one) whenever PUBLIC_BASE_URL is configured; the test
    # env may not set it, so only assert the tag when it renders.
    if 'rel="canonical"' in response.text:
        assert "/state/california" in response.text.split('rel="canonical"')[1][:200]


async def test_state_page_moments_itemlist_uses_creativework_not_videoobject(
    monkeypatch,
):
    # Real regression, 2026-08-29: this ItemList used to type its entries
    # as VideoObject even though the state page renders no <video>
    # element -- Google's own indexing-status reference names "a video
    # category page that lists multiple videos of equal prominence" as
    # an explicit non-watch-page example, and Search Console flagged
    # every hub/state page with a moments feed as "video isn't on a
    # watch page" as a result. See BACKLOG_DONE.md's 2026-08-29 entry.
    # Reno, NV (real, deliberately a state no other test in this file
    # touches -- California is used by several other tests that depend
    # on the shared DB pool having *no* real highlight yet, e.g. the
    # "recent_pages" fallback only renders `{% if not featured %}`, so
    # seeding the first-ever real California highlight here would flip
    # that conditional for every other California-based test in this
    # file, same fragility this file's own Wyoming comment already
    # documents for a different reason). Its own dedicated seed: the
    # moments feed only features a page once compute_highlight_payload()
    # finds a quotable window (MIN_WORDS = 25 in
    # archive/utils/highlights.py, and a window must also clear
    # SKIP_HEAD_FRACTION/SKIP_TAIL_FRACTION of the meeting's duration --
    # see the matching test in test_jurisdiction_hubs.py for the full
    # reasoning), and _seed_all()'s short fixture text is deliberately
    # below that bar for its own tests. This transcript text is
    # synthetic filler, not a real quote.
    monkeypatch.setitem(
        archive.main.templates.env.globals, "public_base_url", "https://example.org"
    )
    await _seed(
        "granicus:state-reno",
        jurisdiction="Reno, NV",
        title="Reno City Council",
        segments=[
            {
                "start": 600,
                "end": 3600,
                "text": (
                    "The council will now move to the second item on tonight's "
                    "agenda, a discussion of the proposed downtown parking "
                    "structure and the budget allocation that would be required "
                    "to complete the environmental review process this year."
                ),
            }
        ],
    )
    r = client.get("/state/nevada")
    assert r.status_code == 200
    match = _JSON_LD_RE.search(r.text)
    assert match, "no JSON-LD script block found"
    data = json.loads(match.group(1))
    assert data["@type"] == "CollectionPage"
    items = data["mainEntity"]["itemListElement"]
    assert items, "expected at least one featured meeting"
    for entry in items:
        item = entry["item"]
        assert item["@type"] == "CreativeWork"
        assert item["url"].startswith("https://example.org/m/")
        assert "transcript" not in item
        assert "uploadDate" not in item
        if "datePublished" in item:
            assert item["datePublished"]
    assert "VideoObject" not in r.text


async def test_coverage_page_links_states(monkeypatch):
    from datetime import datetime

    async def _fake_index():
        return [
            {
                "abbr": "CA",
                "name": "California",
                "slug": "california",
                "country": "US",
                "jurisdiction_count": 2,
                "page_count": 5,
                "last_updated": datetime(2026, 3, 3),
            }
        ]

    monkeypatch.setattr(crud, "get_state_coverage_index", _fake_index)
    response = client.get("/coverage")
    assert response.status_code == 200
    assert 'href="/state/california"' in response.text
    assert "Browse by state" in response.text


async def test_coverage_page_links_canadian_provinces(monkeypatch):
    from datetime import datetime

    async def _fake_index():
        return [
            {
                "abbr": "AB",
                "name": "Alberta",
                "slug": "alberta",
                "country": "CA",
                "jurisdiction_count": 1,
                "page_count": 1,
                "last_updated": datetime(2026, 3, 3),
            }
        ]

    monkeypatch.setattr(crud, "get_state_coverage_index", _fake_index)
    response = client.get("/coverage")
    assert response.status_code == 200
    assert 'href="/state/alberta"' in response.text
    assert "Browse by province (Canada)" in response.text
    # No US states in this fake index -- the "Browse by state" heading
    # shouldn't render an empty section.
    assert "Browse by state</h2>" not in response.text


async def test_meeting_page_links_state_page():
    slugs = await _seed_all()
    response = client.get(f"/m/{slugs['napa']}")
    assert response.status_code == 200
    assert 'href="/state/california"' in response.text
    assert "More California meetings" in response.text


async def test_meeting_page_links_canadian_province_page():
    slugs = await _seed_all()
    response = client.get(f"/m/{slugs['calgary']}")
    assert response.status_code == 200
    assert 'href="/state/alberta"' in response.text
    assert "More Alberta meetings" in response.text
    # The Canada display suffix should show on the meeting page itself,
    # through the same jurisdiction_display filter path as US states.
    assert "Calgary, AB (Canada)" in response.text


async def test_meeting_page_without_state_renders_without_link():
    slug = await _seed(
        "granicus:state-no-state",
        jurisdiction="Illinois General Assembly",
        title="Stateless Jurisdiction Meeting",
    )
    response = client.get(f"/m/{slug}")
    assert response.status_code == 200
    assert 'href="/state/' not in response.text


async def test_crud_get_state_page_data_shape_and_counts():
    await _seed_all()
    data = await crud.get_state_page_data("CA")
    assert data is not None
    assert data["name"] == "California"
    # Rows are grouped by hub slug (2026-08-17): the shared fixture DB
    # holds both "Napa, CA" (seeded here) and "City of Napa, CA" (seeded by
    # another test), and those are ONE government -> one row, one
    # /j/napa-ca hub -- so identify rows by hub_slug, not raw string.
    hub_slugs = {j["hub_slug"] for j in data["jurisdictions"]}
    assert "napa-ca" in hub_slugs
    assert "sacramento-county-ca" in hub_slugs
    assert "coalinga-ca" not in hub_slugs  # platform "unknown" excluded
    napa_rows = [j for j in data["jurisdictions"] if j["hub_slug"] == "napa-ca"]
    assert len(napa_rows) == 1  # variants consolidated, not duplicated
    assert data["total_pages"] >= 2
    assert data["jurisdiction_count"] == len(data["jurisdictions"])
    assert len(data["recent_pages"]) <= 25


async def test_crud_get_state_page_data_for_canadian_province():
    slugs = await _seed_all()
    data = await crud.get_state_page_data("AB")
    assert data is not None
    assert data["name"] == "Alberta"
    juris_names = {j["jurisdiction"] for j in data["jurisdictions"]}
    assert "Calgary, AB" in juris_names
    example_slugs = {j["example"]["slug"] for j in data["jurisdictions"]}
    assert slugs["calgary"] in example_slugs


async def test_crud_get_state_page_data_none_for_empty():
    assert await crud.get_state_page_data("WY") is None


async def test_state_page_renders_a_canadian_province():
    slugs = await _seed_all()
    response = client.get("/state/alberta")
    assert response.status_code == 200
    assert "Calgary" in response.text
    assert f"/m/{slugs['calgary']}" in response.text
    assert "Alberta public meeting videos" in response.text


async def test_crud_get_state_coverage_index():
    await _seed_all()
    index = await crud.get_state_coverage_index()
    by_abbr = {row["abbr"]: row for row in index}
    assert "CA" in by_abbr
    ca = by_abbr["CA"]
    assert ca["name"] == "California"
    assert ca["slug"] == "california"
    assert ca["country"] == "US"
    assert ca["jurisdiction_count"] >= 2
    assert ca["page_count"] >= 2
    assert ca["last_updated"] is not None
    assert "WY" not in by_abbr
    # Alberta shows up as its own real row, distinct from any US state,
    # via the "Calgary, AB" seed in _seed_all().
    assert "AB" in by_abbr
    ab = by_abbr["AB"]
    assert ab["name"] == "Alberta"
    assert ab["slug"] == "alberta"
    assert ab["country"] == "CA"
    assert ab["page_count"] >= 1
    # Sorted by country group (US before Canada, matching /coverage's
    # "Browse by state" section coming before "Browse by province
    # (Canada)"), then alphabetically by name within each group -- not a
    # single global alphabetical sort across both, since that would
    # interleave "Alberta" ahead of "California".
    us_names = [row["name"] for row in index if row["country"] == "US"]
    ca_names = [row["name"] for row in index if row["country"] == "CA"]
    assert us_names == sorted(us_names)
    assert ca_names == sorted(ca_names)
    countries = [row["country"] for row in index]
    assert countries == sorted(countries, key=lambda c: c != "US")


def test_resolver_proxies_state_route():
    # No HTTP-level proxy test precedent exists for the other proxied
    # routes either -- assert the route is registered, same level of
    # guarantee the /coverage and /meetings proxy entries get.
    assert any(
        getattr(route, "path", "") == "/state/{path:path}"
        for route in app.main.app.routes
    )


async def test_sitemap_includes_state_pages():
    await _seed_all()
    response = client.get("/sitemap.xml")
    assert "/state/california</loc>" in response.text
    assert "/state/georgia</loc>" in response.text
    assert "/state/wyoming" not in response.text
    # A Canadian province gets a sitemap entry the same way a US state
    # does -- get_state_coverage_index()'s extra "country" field doesn't
    # change what sitemap.xml.jinja needs (just .slug/.last_updated).
    assert "/state/alberta</loc>" in response.text


# --- /state/all-50 (national, 50-US-states-only hub, added 2026-08-26) ----
#
# Reuses _seed_all()'s existing rows rather than seeding its own: Napa/
# Sacramento County (CA), Decatur (GA) cover "multiple states show up
# together"; Coalinga (platform "unknown") and Calgary (a real Canadian
# jurisdiction) are exactly the two exclusions this page's scope depends
# on -- get_national_government_list()'s platform != "unknown" bar and its
# US_50_STATE_ABBRS-only scope, respectively.


async def test_crud_get_national_government_list_scopes_to_us_states():
    await _seed_all()
    rows = await crud.get_national_government_list()
    hub_slugs = {r["hub_slug"] for r in rows}
    assert "napa-ca" in hub_slugs
    assert "sacramento-county-ca" in hub_slugs
    assert "decatur-ga" in hub_slugs
    # Canadian jurisdiction excluded -- this page is 50-US-states-only for
    # its first cut (CLAUDE.md), Canada/territories are later work.
    assert "calgary-ab" not in hub_slugs
    # Not asserting on napa's exact example.slug: the shared fixture DB
    # also holds a "City of Napa, CA" row seeded by another test, grouped
    # under this same hub_slug (see test_crud_get_state_page_data_shape_
    # and_counts's identical caveat above).
    napa = next(r for r in rows if r["hub_slug"] == "napa-ca")
    assert napa["gov_type"] == "city"
    sacramento = next(r for r in rows if r["hub_slug"] == "sacramento-county-ca")
    assert sacramento["gov_type"] == "county"


async def test_crud_get_national_government_list_excludes_unknown_platform():
    await _seed_all()
    rows = await crud.get_national_government_list()
    hub_slugs = {r["hub_slug"] for r in rows}
    assert "coalinga-ca" not in hub_slugs


async def test_crud_get_all50_page_data_bounded_pool_and_scope():
    await _seed_all()
    data = await crud.get_all50_page_data()
    hub_slugs = {j["hub_slug"] for j in data["jurisdictions"]}
    assert "napa-ca" in hub_slugs
    assert "decatur-ga" in hub_slugs
    assert "calgary-ab" not in hub_slugs
    assert "coalinga-ca" not in hub_slugs
    assert len(data["featured"]) <= crud.ALL50_FEATURED_COUNT
    assert data["jurisdiction_count"] == len(data["jurisdictions"])
    # Grouped list feeds straight into the shared _group_governments()
    # output shape, same as get_state_page_data()'s.
    group_keys = {g["key"] for g in data["government_groups"]}
    assert group_keys <= {"county", "city", "school", "agency"}


async def test_crud_get_all50_page_data_recent_pages_fallback_without_highlights(
    monkeypatch,
):
    # Real bug caught in-browser: recent_pages was first derived from the
    # highlight-joined pool, which is empty in exactly the case this
    # fallback exists to cover (no MeetingHighlight rows yet) -- so the
    # fallback rendered its heading over an empty list. It needs its own
    # query, independent of MeetingHighlight. Forces the "nothing
    # featured" branch via monkeypatch rather than asserting
    # data["featured"] == [] directly -- the shared fixture DB may
    # already hold a real MeetingHighlight for one of _seed_all()'s
    # common city names from another test, which would make that
    # assertion order-dependent (same shared-DB caveat as
    # test_state_page_empty_state_404 above).
    await _seed_all()
    monkeypatch.setattr(crud, "_build_featured", lambda *a, **k: [])
    data = await crud.get_all50_page_data()
    assert data["featured"] == []
    assert len(data["recent_pages"]) > 0
    assert all("has_transcript" in p for p in data["recent_pages"])
    hub_slugs = {jurisdiction_hub_slug(p["jurisdiction"]) for p in data["recent_pages"]}
    assert "calgary-ab" not in hub_slugs
    assert "coalinga-ca" not in hub_slugs


def test_state_all50_page_renders():
    response = client.get("/state/all-50")
    assert response.status_code == 200
    assert "Public meetings from all 50 states" in response.text


async def test_state_all50_moments_itemlist_uses_creativework_not_videoobject(
    monkeypatch,
):
    # Same regression as test_state_page_moments_itemlist_uses_
    # creativework_not_videoobject above, checked separately since
    # state_all50.html is its own template with its own copy of the
    # ItemList block, not sharing state_page.html's route handler.
    monkeypatch.setitem(
        archive.main.templates.env.globals, "public_base_url", "https://example.org"
    )
    await _seed(
        "granicus:state-all50-elpaso",
        jurisdiction="El Paso, TX",
        title="El Paso City Council",
        segments=[
            {
                "start": 600,
                "end": 3600,
                "text": (
                    "The council will now move to the second item on tonight's "
                    "agenda, a discussion of the proposed downtown parking "
                    "structure and the budget allocation that would be required "
                    "to complete the environmental review process this year."
                ),
            }
        ],
    )
    r = client.get("/state/all-50")
    assert r.status_code == 200
    match = _JSON_LD_RE.search(r.text)
    assert match, "no JSON-LD script block found"
    data = json.loads(match.group(1))
    assert data["@type"] == "CollectionPage"
    items = data["mainEntity"]["itemListElement"]
    assert items, "expected at least one featured meeting"
    for entry in items:
        item = entry["item"]
        assert item["@type"] == "CreativeWork"
        assert "transcript" not in item
        assert "uploadDate" not in item
    assert "VideoObject" not in r.text


async def test_state_all50_excludes_canada_and_unknown_platform():
    slugs = await _seed_all()
    response = client.get("/state/all-50")
    assert response.status_code == 200
    assert "/j/calgary-ab" not in response.text
    assert slugs["calgary"] not in response.text
    assert "Coalinga Generic Fallback Meeting" not in response.text


async def test_state_all50_omits_search_all_and_rss_footer_links():
    await _seed_all()
    response = client.get("/state/all-50")
    assert "Search all" not in response.text
    assert "/feed.xml?jurisdiction=" not in response.text


async def test_state_all50_most_watched_appears_before_recently_archived(monkeypatch):
    # User feedback 2026-08-26: "most watched" reads better leading the
    # page than trailing the recency feed. Deliberately only for this
    # national page -- state_page.html's own per-state ordering is
    # untouched. MOST_ACTIVE_MIN_GOVERNMENTS lowered to 1 so this test's
    # own assertion doesn't depend on how many *other* tests have already
    # pushed the shared DB's US-state government count over the real
    # threshold (8) by the time this file runs -- true in a full suite
    # run, not guaranteed in isolation.
    monkeypatch.setattr(crud, "MOST_ACTIVE_MIN_GOVERNMENTS", 1)
    await _seed_all()
    response = client.get("/state/all-50")
    text = response.text
    most_watched_pos = text.index("Most watched governments")
    # The recency heading has two non-topic-filtered variants depending on
    # whether `featured` is empty (real, shared-DB-scale-dependent: many
    # other tests may have already created MeetingHighlight rows for
    # US-state jurisdictions by the time this runs) -- check whichever one
    # actually rendered, not a specific hardcoded variant.
    recency_variants = [
        "Recently archived nationwide",
        "Recent moments from across the country",
    ]
    recency_positions = [text.index(v) for v in recency_variants if v in text]
    assert recency_positions, "neither recency heading variant rendered"
    assert most_watched_pos < min(recency_positions)


def test_state_all50_registered_before_dynamic_state_route():
    # "all-50" isn't a real state slug -- if the dynamic /state/{state_slug}
    # route matched first, this would just 404 through STATE_SLUG_TO_ABBR's
    # miss path instead of rendering the real page.
    paths = [getattr(route, "path", "") for route in archive.main.app.routes]
    assert paths.index("/state/all-50") < paths.index("/state/{state_slug}")


async def test_sitemap_includes_state_all50_not_coverage_detail():
    response = client.get("/sitemap.xml")
    assert "/state/all-50</loc>" in response.text
    assert "/coverage/detail" not in response.text


def test_resolver_proxies_coverage_detail_route():
    assert any(
        getattr(route, "path", "") == "/coverage/detail"
        for route in app.main.app.routes
    )


def test_resolver_proxies_api_jurisdictions_route():
    assert any(
        getattr(route, "path", "") == "/api/jurisdictions"
        for route in app.main.app.routes
    )


# --- /api/jurisdictions (lightweight search behind /coverage's search box)


async def test_api_jurisdictions_search_returns_matches():
    await _seed_all()
    response = client.get("/api/jurisdictions", params={"q": "Napa"})
    assert response.status_code == 200
    matches = response.json()["matches"]
    assert all(m["kind"] == "jurisdiction" for m in matches)
    assert any(m["link"] == "/j/napa-ca" for m in matches)
    assert any("Napa" in m["label"] for m in matches)


async def test_api_jurisdictions_search_requires_min_length():
    response = client.get("/api/jurisdictions", params={"q": "n"})
    assert response.status_code == 200
    assert response.json()["matches"] == []


async def test_crud_search_jurisdictions_state_name_returns_state_result_first():
    # A bare full state/province name is special-cased (real UI gap found
    # 2026-08-26: searching "California" returned nothing useful before
    # this -- stored jurisdictions hold "CA", not the full name, so a
    # plain substring match mostly missed it) into a state-page link,
    # followed by that state's own governments -- not just a jurisdiction-
    # name substring match, which "California" would barely hit.
    await _seed_all()
    results = await crud.search_jurisdictions("California")
    assert results[0] == {
        "kind": "state",
        "label": "California",
        "link": "/state/california",
    }
    # Not asserting a specific jurisdiction (e.g. napa-ca) is among the
    # results: the full suite seeds dozens of real CA jurisdictions, and
    # the popularity-ranked, capped-at-25 result set is a real, shared-
    # DB-scale-dependent slice of that -- see
    # test_crud_search_jurisdictions_state_name_ranks_by_meeting_count
    # below for the exact-ordering check, done with isolated data instead.
    # This test only checks the state-branch's own structural shape.
    assert len(results) > 1
    for row in results[1:]:
        assert row["kind"] == "jurisdiction"
        assert row["link"].startswith("/j/")


async def test_crud_search_jurisdictions_state_abbreviation_also_matches():
    await _seed_all()
    results = await crud.search_jurisdictions("AB")
    assert results[0]["kind"] == "state"
    assert results[0]["link"] == "/state/alberta"


async def test_crud_search_jurisdictions_state_name_ranks_by_meeting_count():
    # Real, controlled-count New Mexico cities -- not touched elsewhere in
    # this shared-DB file -- so "most popular" has an unambiguous real
    # answer to check, immune to whatever other tests have already seeded
    # into the shared CA/GA/AB counts _seed_all() itself uses.
    await _seed(
        "granicus:nm-roswell-1",
        jurisdiction="Roswell, NM",
        title="Roswell City Council",
    )
    await _seed(
        "granicus:nm-roswell-2",
        jurisdiction="Roswell, NM",
        title="Roswell Budget Workshop",
    )
    await _seed(
        "granicus:nm-taos-1", jurisdiction="Taos, NM", title="Taos Town Council"
    )

    results = await crud.search_jurisdictions("New Mexico")
    assert results[0] == {
        "kind": "state",
        "label": "New Mexico",
        "link": "/state/new-mexico",
    }
    links_in_order = [r["link"] for r in results[1:]]
    assert links_in_order.index("/j/roswell-nm") < links_in_order.index("/j/taos-nm")


async def _seed_ambiguous_names():
    """Two real, confirmed-ambiguous cases for search_jurisdictions():
    San Diego is both a real city AND a real county in California (same
    state, different government type), and Alexandria is a real city in
    both Virginia (confirmed live as alexandria.granicus.com's default
    jurisdiction, see tests/test_jurisdiction_enrich.py) and Louisiana
    (real, the seat of Rapides Parish) -- same name, two different
    states. jurisdiction_hub_slug()'s state suffix is what's supposed to
    keep all four as distinct hubs rather than colliding into one."""
    await _seed(
        "granicus:ambiguous-san-diego-city",
        jurisdiction="San Diego, CA",
        title="San Diego City Council",
    )
    await _seed(
        "granicus:ambiguous-san-diego-county",
        jurisdiction="San Diego County, CA",
        title="San Diego County Board of Supervisors",
    )
    await _seed(
        "granicus:ambiguous-alexandria-va",
        jurisdiction="Alexandria, VA",
        title="Alexandria City Council",
    )
    await _seed(
        "granicus:ambiguous-alexandria-la",
        jurisdiction="Alexandria, LA",
        title="Alexandria City Council",
    )


async def test_crud_search_jurisdictions_city_and_county_same_name_stay_distinct():
    await _seed_ambiguous_names()
    links = {r["link"] for r in await crud.search_jurisdictions("San Diego")}
    assert "/j/san-diego-ca" in links
    assert "/j/san-diego-county-ca" in links


async def test_crud_search_jurisdictions_same_city_name_different_states_stay_distinct():
    await _seed_ambiguous_names()
    links = {r["link"] for r in await crud.search_jurisdictions("Alexandria")}
    assert "/j/alexandria-va" in links
    assert "/j/alexandria-la" in links
