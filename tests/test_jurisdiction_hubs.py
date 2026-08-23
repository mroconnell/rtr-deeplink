"""Jurisdiction hub pages -- /j/{slug} (archive/main.py), the crud behind
them (get_jurisdiction_hub_data / list_indexable_hub_entries /
JURISDICTION_HUB_MIN_INDEXABLE) and jurisdiction_hub_slug(). Real DB
integration against the shared SQLite fixture, same pattern as
tests/test_state_pages.py. Every seed here uses a jurisdiction no other
test file uses (Hercules-adjacent real CA/TX places would collide with
the state-page tests' shared session DB), so counts and threshold
assertions are stable regardless of test order.
"""

from fastapi.testclient import TestClient

import app.main
import archive.main
from archive.db import crud
from archive.utils.jurisdiction_format import jurisdiction_hub_slug

client = TestClient(archive.main.app)


def _payload(
    external_id,
    url,
    *,
    jurisdiction,
    title,
    date,
    platform="granicus",
    segments=None,
):
    return {
        "platform": platform,
        "source_url": url,
        "external_id": external_id,
        "title": title,
        "date": date,
        "jurisdiction": jurisdiction,
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": segments
        if segments is not None
        else [{"start": 0, "end": 1, "text": "hub page test transcript"}],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }


async def _seed(external_id, meeting_body=None, **kwargs) -> str:
    url = f"https://example.com/hub-seed/{external_id}"
    payload = _payload(external_id, url, **kwargs)
    if meeting_body:
        # meeting_body IS a payload field since 2026-08-23 (an adapter
        # that names the governing body itself, e.g. Granicus's RSS
        # channel title, sends it; crud prefers it over the
        # finalize_jurisdiction() split) -- seeding through the payload
        # exercises that pass-through on every hub test. This helper
        # previously had to set the column directly post-ingest.
        payload["meeting_body"] = meeting_body
    result = await crud.ingest_resolution(payload, url)
    return result["slug"]


async def _seed_all():
    """Yountville, CA (real Napa-county town, only seeded here): three
    meetings across two raw-string variants ("Yountville, CA" x2 and
    "City of Yountville, CA" x1) -> ONE hub, indexable. Rio Vista, CA
    (real Solano-county city, only seeded here): a single meeting -> a hub
    that renders but is below JURISDICTION_HUB_MIN_INDEXABLE. Also a
    platform="unknown" Yountville row that must not count."""
    s = {}
    s["y1"] = await _seed(
        "granicus:hub-y1",
        jurisdiction="Yountville, CA",
        title="Yountville Town Council",
        date="2026-02-03",
        meeting_body="Town Council",
    )
    s["y2"] = await _seed(
        "granicus:hub-y2",
        jurisdiction="Yountville, CA",
        title="Yountville Planning Commission",
        date="2026-01-14",
        meeting_body="Planning Commission",
    )
    s["y3"] = await _seed(
        "granicus:hub-y3",
        jurisdiction="City of Yountville, CA",
        title="Yountville Town Council (older)",
        date="2025-12-02",
        meeting_body="Town Council",
    )
    s["y_unknown"] = await _seed(
        "unknown:hub-y4",
        platform="unknown",
        jurisdiction="Yountville, CA",
        title="Yountville generic fallback",
        date="2026-03-01",
    )
    s["riovista"] = await _seed(
        "granicus:hub-rv1",
        jurisdiction="Rio Vista, CA",
        title="Rio Vista City Council",
        date="2026-02-20",
        meeting_body="City Council",
    )
    return s


# --- slug helper -----------------------------------------------------------


def test_hub_slug_merges_display_variants_and_keeps_real_distinctions():
    assert jurisdiction_hub_slug("Napa, CA") == "napa-ca"
    assert (
        jurisdiction_hub_slug("City of Napa, CA") == "napa-ca"
    )  # display strips "City of"
    assert jurisdiction_hub_slug("NAPA, CA") == "napa-ca"  # casing variants
    assert (
        jurisdiction_hub_slug("County of Napa, CA") == "county-of-napa-ca"
    )  # a different government
    assert (
        jurisdiction_hub_slug("City and County of San Francisco, CA")
        == "city-and-county-of-san-francisco-ca"
    )
    assert (
        jurisdiction_hub_slug("Calgary, AB") == "calgary-ab"
    )  # " (Canada)" display suffix not in slug
    assert jurisdiction_hub_slug("California State Senate") == "california-state-senate"
    assert jurisdiction_hub_slug(None) is None
    assert jurisdiction_hub_slug("") is None


# --- crud ------------------------------------------------------------------


async def test_hub_data_consolidates_variants_counts_bodies_and_excludes_unknown():
    s = await _seed_all()
    data = await crud.get_jurisdiction_hub_data("yountville-ca")
    assert data is not None
    assert data["display"] == "Yountville, CA"
    slugs = [p["slug"] for p in data["pages"]]
    assert set(slugs) == {
        s["y1"],
        s["y2"],
        s["y3"],
    }  # both raw variants, no unknown-platform row
    assert data["total_pages"] == 3
    assert data["indexable"] is True
    assert slugs[0] == s["y1"]  # newest first
    assert data["bodies"] == [
        {"name": "Town Council", "count": 2},
        {"name": "Planning Commission", "count": 1},
    ]
    assert (data["earliest_date"], data["latest_date"]) == ("2025-12-02", "2026-02-03")
    assert data["transcript_count"] == 3
    assert (data["state_abbr"], data["state_slug"], data["state_name"]) == (
        "CA",
        "california",
        "California",
    )


async def test_hub_below_threshold_renders_but_is_not_indexable():
    await _seed_all()
    data = await crud.get_jurisdiction_hub_data("rio-vista-ca")
    assert data is not None and data["total_pages"] == 1
    assert data["indexable"] is False
    assert crud.JURISDICTION_HUB_MIN_INDEXABLE == 2


async def test_unknown_hub_slug_is_none():
    assert await crud.get_jurisdiction_hub_data("no-such-place-zz") is None


async def test_indexable_hub_entries_apply_threshold_with_lastmod():
    await _seed_all()
    entries = {e["slug"]: e for e in await crud.list_indexable_hub_entries()}
    assert "yountville-ca" in entries
    assert entries["yountville-ca"]["last_updated"] is not None
    assert "rio-vista-ca" not in entries  # single meeting -> not in the sitemap


# --- routes ----------------------------------------------------------------


async def test_hub_route_renders_meetings_breadcrumb_and_links():
    s = await _seed_all()
    r = client.get("/j/yountville-ca")
    assert r.status_code == 200
    assert "Yountville, CA public meetings" in r.text
    for k in ("y1", "y2", "y3"):
        assert f"/m/{s[k]}" in r.text
    assert f"/m/{s['y_unknown']}" not in r.text
    assert 'href="/state/california"' in r.text
    assert "Town Council" in r.text and "Planning Commission" in r.text
    assert 'content="noindex"' not in r.text
    # canonical/BreadcrumbList are gated on PUBLIC_BASE_URL (unset in tests),
    # same as the state pages -- rendering without it is the tested path.


async def test_hub_route_below_threshold_is_noindexed_and_unknown_404s():
    await _seed_all()
    r = client.get("/j/rio-vista-ca")
    assert r.status_code == 200
    assert '<meta name="robots" content="noindex">' in r.text
    assert "Only 1 meeting archived so far" in r.text
    assert client.get("/j/no-such-place-zz").status_code == 404


async def test_sitemap_lists_only_indexable_hubs():
    await _seed_all()
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    assert "/j/yountville-ca</loc>" in r.text
    assert "/j/rio-vista-ca" not in r.text


async def test_meeting_page_and_state_page_link_to_hub():
    s = await _seed_all()
    r = client.get(f"/m/{s['y1']}")
    assert (
        'href="/j/yountville-ca"' in r.text and "More Yountville, CA meetings" in r.text
    )
    r2 = client.get("/state/california")
    assert 'href="/j/yountville-ca"' in r2.text
    # ...and the state page's government list shows the two raw variants
    # as ONE row. Scoped to that list rather than counting hub links
    # across the whole page: since 2026-08-23 the page can legitimately
    # link to the same hub more than once (the "Most active governments"
    # section links to the busiest hubs, and a featured snippet's card
    # links to its meeting's government), and a page-wide count would be
    # asserting something this test never meant to -- the bug it guards
    # against is a duplicate *row*, one per raw jurisdiction string.
    gov_list = r2.text.split('class="state-gov-scroll"', 1)[-1]
    assert gov_list.count('href="/j/yountville-ca"') == 1


def test_resolver_proxies_hub_path():
    # Same shape as the /state proxy test in test_state_pages.py: the route
    # exists on the resolver and targets the archive's j/ prefix.
    routes = {r.path: r for r in app.main.app.routes if hasattr(r, "path")}
    assert "/j/{path:path}" in routes
