"""Tests for POST /internal/admin/reslug-page (archive/main.py) and its
old-slug redirect map -- the by-hand fix for a page whose permanent slug
was frozen from vendor boilerplate rather than the meeting's own title
(real case: /m/welcome-to-clerkbase, a real Yellow Springs, OH meeting --
see BACKLOG_DONE.md). Not slug-regeneration as a general sweep; a human
names one existing slug, and crud.reslug_page() recomputes the
replacement from that page's current jurisdiction/date/title via the same
build_base_slug()/_unique_slug() pair every fresh ingest already uses.
"""

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud

client = TestClient(archive.main.app)


def test_reslug_endpoint_rejects_missing_token():
    response = client.post(
        "/internal/admin/reslug-page", json={"slug": "does-not-matter"}
    )
    assert response.status_code == 404


async def test_reslug_dry_run_previews_without_writing(monkeypatch):
    payload = {
        "platform": "clerkbase",
        "source_url": "https://reslug-dry-run-test.example.gov/meeting",
        "external_id": "reslug-dry-run-test",
        "title": "Welcome to ClerkBase",
        "date": "2022-02-07",
        "jurisdiction": "Yellow Springs, OH",
        "video_url": None,
        "segments": [],
        "agenda_items": [],
        "transcript_warnings": [],
    }
    created = await crud.ingest_resolution(
        payload, "https://reslug-dry-run-test.example.gov/meeting"
    )
    old_slug = created["slug"]

    response = client.post(
        "/internal/admin/reslug-page",
        json={"slug": old_slug},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["old_slug"] == old_slug
    assert "yellow-springs" in body["new_slug_preview"]

    # Dry run must not have written anything.
    unchanged = await crud.get_page_by_slug(old_slug)
    assert unchanged is not None


async def test_reslug_real_call_updates_slug_and_old_slug_404s():
    payload = {
        "platform": "clerkbase",
        "source_url": "https://reslug-real-test.example.gov/meeting",
        "external_id": "reslug-real-test",
        "title": "Regular Village Council Meeting",
        "date": "2022-02-07",
        "jurisdiction": "Yellow Springs, OH",
        "video_url": None,
        "segments": [],
        "agenda_items": [],
        "transcript_warnings": [],
    }
    created = await crud.ingest_resolution(
        payload, "https://reslug-real-test.example.gov/meeting"
    )
    old_slug = created["slug"]

    response = client.post(
        "/internal/admin/reslug-page",
        json={"slug": old_slug},
        params={"dry_run": "false"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is False
    new_slug = body["new_slug"]
    assert new_slug != old_slug

    assert await crud.get_page_by_slug(old_slug) is None
    updated = await crud.get_page_by_slug(new_slug)
    assert updated is not None
    assert updated["title"] == "Regular Village Council Meeting"


async def test_wo925_partial_ingest_corrects_title_and_date_only():
    """The supported way to retitle one page (WO-925, Part B): a partial
    ingest carrying only platform/source_url/external_id + title/date.
    Identity, slug and video stay untouched (no jurisdiction supplied)."""
    url = "https://wo925-retitle-test.example.gov/meeting"
    created = await crud.ingest_resolution(
        {
            "platform": "clerkbase",
            "source_url": url,
            "external_id": "wo925-retitle-test",
            "title": "video1516165031",
            "date": "2026-06-08",
            "jurisdiction": "Yellow Springs, OH",
            "video_url": "https://example.gov/v.mp4",
            "video_format": "mp4",
        },
        url,
    )
    slug = created["slug"]
    await crud.ingest_resolution(
        {
            "platform": "clerkbase",
            "source_url": url,
            "external_id": "wo925-retitle-test",
            "title": "Advisory Board Meeting",
            "date": "2026-06-04",
        },
        url,
    )
    page = await crud.get_page_by_slug(slug)
    assert page is not None
    assert page["title"] == "Advisory Board Meeting"
    assert page["date"] == "2026-06-04"
    assert page["jurisdiction"] == "Yellow Springs, OH"
    assert page["video_url"] == "https://example.gov/v.mp4"


def test_reslug_unknown_slug_returns_error_not_a_crash():
    response = client.post(
        "/internal/admin/reslug-page",
        json={"slug": "no-such-page-exists-at-all"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    assert "error" in response.json()


def test_old_slug_redirect_map_301s_when_populated(monkeypatch):
    # _SLUG_REDIRECTS is normally empty until a real reslug lands -- pin
    # the mechanism itself with a synthetic entry rather than depending on
    # production data being present in the test DB.
    monkeypatch.setitem(
        archive.main._SLUG_REDIRECTS, "old-boilerplate-slug", "real-new-slug"
    )
    response = client.get("/m/old-boilerplate-slug", follow_redirects=False)
    assert response.status_code == 301
    assert response.headers["location"] == "/m/real-new-slug"


# WO-925: five Vimeo pages first filed under "Oak Bluffs, MA" by a
# blank-match pin, later re-keyed by manual override. Slugs and their
# previews are real (production dry runs of reslug-page, 2026-09-20).
_WO925_OAK_BLUFFS_REDIRECTS = {
    "oak-bluffs-ma-2026-09-02-planning-board-september-2-2026": "amherst-nh-2026-09-02-planning-board-september-2-2026",
    "oak-bluffs-ma-2026-04-10-board-of-supervisors-4-14-26": "hanover-township-pa-2026-04-10-board-of-supervisors-4-14-26",
    "oak-bluffs-ma-2026-08-27-8-26-26-florence-urban-renewal-agency": "florence-or-2026-08-27-8-26-26-florence-urban-renewal-agency",
    "oak-bluffs-ma-2026-09-08-sc-board-meeting-2026-09-08": "steele-county-mn-2026-09-08-sc-board-meeting-2026-09-08",
    "oak-bluffs-ma-2026-09-02-september-2-2026-council-meeting": "middletown-township-pa-2026-09-02-september-2-2026-council-meeting",
}


def test_wo925_oak_bluffs_old_slugs_301_to_the_real_governments():
    for old, new in _WO925_OAK_BLUFFS_REDIRECTS.items():
        response = client.get(f"/m/{old}", follow_redirects=False)
        assert response.status_code == 301, old
        assert response.headers["location"] == f"/m/{new}"
