"""First real coverage of /sitemap.xml (previously only footer links to it
were asserted, see tests/test_footer_and_coverage.py). The regression case:
generic_fallback pages (platform == "unknown") are noindexed by
meeting_page.html, so they must not be listed in the sitemap — the real
Search Console "Excluded by 'noindex' tag ... in a sitemap" alert
(2026-08-17, see BACKLOG_DONE.md). Seeded rows use unique
external_ids/source_urls per this suite's shared-session-DB convention
(tests/conftest.py).
"""

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud

client = TestClient(archive.main.app)


def _payload(platform: str, external_id: str, source_url: str) -> dict:
    return {
        "platform": platform,
        "source_url": source_url,
        "external_id": external_id,
        "title": "Sitemap Test Meeting",
        "date": "2026-02-02",
        "jurisdiction": "Sitemap Test City, CA",
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": [{"start": 0, "end": 1, "text": "hello sitemap"}],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }


async def _seed(platform: str, external_id: str) -> str:
    url = f"https://example.com/sitemap-seed/{external_id}"
    result = await crud.ingest_resolution(
        _payload(platform, external_id, url), url
    )
    return result["slug"]


def test_sitemap_includes_static_paths_and_is_xml():
    response = client.get("/sitemap.xml")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    for path in ("/", "/about", "/coverage", "/meetings"):
        assert f"<loc>{path}</loc>" in response.text or path in response.text


async def test_sitemap_includes_indexable_meeting_pages():
    slug = await _seed("granicus", "granicus:sitemap-indexable")
    response = client.get("/sitemap.xml")
    assert f"/m/{slug}</loc>" in response.text
    assert "<lastmod>" in response.text


async def test_sitemap_excludes_noindex_unknown_platform_pages():
    slug = await _seed("unknown", "unknown:sitemap-noindexed")
    response = client.get("/sitemap.xml")
    assert slug not in response.text


async def test_list_all_page_slugs_excludes_unknown_platform():
    indexable_slug = await _seed("granicus", "granicus:sitemap-crud-level")
    noindexed_slug = await _seed("unknown", "unknown:sitemap-crud-level")
    slugs = {entry["slug"] for entry in await crud.list_all_page_slugs()}
    assert indexable_slug in slugs
    assert noindexed_slug not in slugs
