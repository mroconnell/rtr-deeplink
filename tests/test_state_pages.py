"""Per-state SEO landing pages (/state/{slug}) plus their /coverage and
meeting-page entry points. Seeded rows use real, Census-valid cities
(repo convention: synthetic payloads reuse confirmed-real facts) and
unique external_ids/source_urls per the shared-session-DB convention
(tests/conftest.py). The key regression case: the state match is an
anchored ", CA" suffix match, never list_pages()-style substring ilike --
"Decatur, GA" contains "ca" and must not appear on /state/california.
"""

from fastapi.testclient import TestClient

import app.main
import archive.main
from archive.db import crud

client = TestClient(archive.main.app)


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
    # No test seeds any ", WY" jurisdiction (checked by grep when this was
    # written) -- a real state with zero indexable pages 404s rather than
    # rendering an empty shell.
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


async def test_coverage_page_links_states(monkeypatch):
    from datetime import datetime

    async def _fake_index():
        return [
            {
                "abbr": "CA",
                "name": "California",
                "slug": "california",
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


async def test_meeting_page_links_state_page():
    slugs = await _seed_all()
    response = client.get(f"/m/{slugs['napa']}")
    assert response.status_code == 200
    assert 'href="/state/california"' in response.text
    assert "More California meetings" in response.text


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
    juris_names = {j["jurisdiction"] for j in data["jurisdictions"]}
    assert "Napa, CA" in juris_names
    assert "Sacramento County, CA" in juris_names
    assert "Coalinga, CA" not in juris_names  # platform "unknown" excluded
    assert data["total_pages"] >= 2
    assert data["jurisdiction_count"] == len(data["jurisdictions"])
    assert len(data["recent_pages"]) <= 25


async def test_crud_get_state_page_data_none_for_empty():
    assert await crud.get_state_page_data("WY") is None


async def test_crud_get_state_coverage_index():
    await _seed_all()
    index = await crud.get_state_coverage_index()
    by_abbr = {row["abbr"]: row for row in index}
    assert "CA" in by_abbr
    ca = by_abbr["CA"]
    assert ca["name"] == "California"
    assert ca["slug"] == "california"
    assert ca["jurisdiction_count"] >= 2
    assert ca["page_count"] >= 2
    assert ca["last_updated"] is not None
    assert "WY" not in by_abbr
    # Sorted by state name.
    names = [row["name"] for row in index]
    assert names == sorted(names)


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
