"""Tests for POST /internal/jurisdiction/override (archive/main.py) and
crud.override_jurisdiction() behind it -- 2026-08-31, unlocking two
BACKLOG.md entries that had no write path: Santa Clara's 4 already-valid-
but-inconsistent jurisdiction strings needing one canonical form (which
finalize_jurisdiction() makes zero changes to, since each already
validates independently), and the low-trust queue's missing "review ->
repair" write path.

Real DB integration against the isolated SQLite file from
tests/conftest.py's _archive_db_schema fixture, driven through the actual
POST /internal/ingest HTTP surface -- same convention as
tests/test_low_trust_pages.py, which this file mirrors structurally.
"""

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud

client = TestClient(archive.main.app)

_AUTH = {"Authorization": "Bearer test-token"}


def _payload(**overrides) -> dict:
    payload = {
        "platform": "granicus",
        "source_url": "https://example.granicus.com/player/clip/jx-override",
        "external_id": None,
        "title": "City Council Regular Meeting",
        "date": "2026-08-01",
        "jurisdiction": "Override Default City, ZZ",
        "video_url": "https://example.com/video.m3u8",
        "video_format": "m3u8",
        "segments": [{"start": 0.0, "end": 1.0, "text": "Call to order"}],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }
    payload.update(overrides)
    return payload


def _ingest(payload: dict) -> dict:
    body = dict(payload)
    body["input_url_normalized"] = payload["source_url"]
    response = client.post("/internal/ingest", json=body, headers=_AUTH)
    assert response.status_code == 200, response.text
    return response.json()


def _override(ids, jurisdiction, **params) -> dict:
    query = "&".join(
        [f"ids={ids}", f"jurisdiction={jurisdiction}"]
        + [f"{k}={v}" for k, v in params.items()]
    )
    response = client.post(f"/internal/jurisdiction/override?{query}", headers=_AUTH)
    return response.json() | {"_status": response.status_code}


# --- auth / validation ---------------------------------------------------


def test_rejects_missing_token():
    assert (
        client.post("/internal/jurisdiction/override?ids=1&jurisdiction=X").status_code
        == 404
    )


def test_rejects_wrong_token():
    response = client.post(
        "/internal/jurisdiction/override?ids=1&jurisdiction=X",
        headers={"Authorization": "Bearer nope"},
    )
    assert response.status_code == 404


def test_requires_ids():
    response = client.post(
        "/internal/jurisdiction/override?jurisdiction=X", headers=_AUTH
    )
    assert response.status_code == 400
    assert "ids" in response.json()["detail"]


async def test_requires_non_blank_jurisdiction():
    result = _ingest(
        _payload(source_url="https://example.granicus.com/player/clip/jx-blank")
    )
    # This page won't be low-trust (jurisdiction validates), so fetch its
    # id directly rather than via the low-trust listing.
    page_id = await _page_id_for(result["slug"])
    assert _override(page_id, "%20%20")["_status"] == 400
    assert _override(page_id, "")["_status"] == 400


def test_rejects_non_integer_ids():
    assert _override("12,notanid", "Some City, CA")["_status"] == 400


# --- core write behavior --------------------------------------------------


async def _page_id_for(slug: str) -> int:
    from sqlalchemy import select

    from archive.db.engine import async_session
    from archive.db.models import MeetingPage

    async with async_session() as session:
        page = (
            await session.execute(select(MeetingPage).where(MeetingPage.slug == slug))
        ).scalar_one()
        return page.id


async def test_dry_run_writes_nothing():
    result = _ingest(
        _payload(source_url="https://example.granicus.com/player/clip/jx-dry-run")
    )
    page_id = await _page_id_for(result["slug"])

    overridden = _override(page_id, "Override Test County, ZZ")
    assert overridden["_status"] == 200
    assert overridden["dry_run"] is True
    assert overridden["would_update"] == 1
    assert overridden["updated"] == 0
    assert [c["meeting_page_id"] for c in overridden["changed"]] == [page_id]
    assert overridden["changed"][0]["jurisdiction_after"] == "Override Test County, ZZ"

    # Nothing actually written.
    from sqlalchemy import select

    from archive.db.engine import async_session
    from archive.db.models import MeetingPage

    async with async_session() as session:
        page = (
            await session.execute(
                select(MeetingPage).where(MeetingPage.slug == result["slug"])
            )
        ).scalar_one()
        assert page.jurisdiction == "Override Default City, ZZ"
        assert page.jurisdiction_confidence != "manual_override"


async def test_commit_writes_jurisdiction_confidence_and_reviewed_at():
    result = _ingest(
        _payload(source_url="https://example.granicus.com/player/clip/jx-commit")
    )
    page_id = await _page_id_for(result["slug"])

    overridden = _override(page_id, "Override Test County, ZZ", dry_run="false")
    assert overridden["updated"] == 1
    assert overridden["reviewed_at_stamped"] is True

    from sqlalchemy import select

    from archive.db.engine import async_session
    from archive.db.models import MeetingPage

    # Select the specific columns rather than the whole ORM object --
    # reviewed_at is a deferred column (see MeetingPage.reviewed_at's own
    # comment), and touching it via plain attribute access outside the
    # SELECT that named it raises MissingGreenlet on an async session.
    async with async_session() as session:
        jurisdiction, confidence, reviewed_at = (
            await session.execute(
                select(
                    MeetingPage.jurisdiction,
                    MeetingPage.jurisdiction_confidence,
                    MeetingPage.reviewed_at,
                ).where(MeetingPage.slug == result["slug"])
            )
        ).one()
        assert jurisdiction == "Override Test County, ZZ"
        assert confidence == "manual_override"
        assert reviewed_at is not None


async def test_idempotent_on_repeat_call():
    result = _ingest(
        _payload(source_url="https://example.granicus.com/player/clip/jx-idempotent")
    )
    page_id = await _page_id_for(result["slug"])

    first = _override(page_id, "Override Test County, ZZ", dry_run="false")
    assert first["updated"] == 1

    second = _override(page_id, "Override Test County, ZZ", dry_run="false")
    assert second["updated"] == 0
    assert second["changed"] == []
    assert [e["meeting_page_id"] for e in second["already_overridden"]] == [page_id]


async def test_reports_unknown_ids_without_failing_the_batch():
    result = _ingest(
        _payload(source_url="https://example.granicus.com/player/clip/jx-partial")
    )
    page_id = await _page_id_for(result["slug"])

    overridden = _override(
        f"{page_id},99999999", "Override Test County, ZZ", dry_run="false"
    )
    assert overridden["updated"] == 1
    assert overridden["missing_ids"] == [99999999]


def test_caps_batch_size():
    ids = set(range(1, crud._JURISDICTION_OVERRIDE_MAX_IDS + 2))
    response = client.post(
        "/internal/jurisdiction/override?jurisdiction=X&ids="
        + ",".join(str(i) for i in sorted(ids)),
        headers=_AUTH,
    )
    assert response.status_code == 400
    assert "at most" in response.json()["detail"]


# --- the whole point: survives the next passive re-ingest -----------------


async def test_override_survives_a_later_re_ingest():
    """The real gap this endpoint exists to close -- without the
    manual_override guard in _find_or_create_page(), a Santa Clara-style
    fix would silently drift back the next time the page is re-resolved
    (a passive ARCHIVE_RECHECK_AFTER cycle, or a manual "Refresh this
    page" click), since an ordinary re-ingest's recomputed jurisdiction
    is exactly the value the override was written to correct."""
    # Synthetic ", ZZ" jurisdictions throughout this file, not a real
    # state -- same reasoning as test_low_trust_pages.py's "Suspicious
    # Source Test City, ZZ": this file's writes land in the same
    # session-scoped shared DB every other test file reads from, and a
    # real state/county string would bump a real ranking count (see that
    # file's own comment for the Dublin CA incident this avoids).
    url = "https://example.granicus.com/player/clip/jx-survives-reingest"
    result = _ingest(_payload(source_url=url, jurisdiction="Override County A, ZZ"))
    page_id = await _page_id_for(result["slug"])

    _override(page_id, "Override Test County, ZZ", dry_run="false")

    # A later re-ingest of the same URL, with a DIFFERENT (but still
    # independently valid) jurisdiction string -- exactly the shape a
    # real re-resolve produces.
    _ingest(_payload(source_url=url, jurisdiction="Override County B, ZZ"))

    from sqlalchemy import select

    from archive.db.engine import async_session
    from archive.db.models import MeetingPage

    async with async_session() as session:
        page = (
            await session.execute(
                select(MeetingPage).where(MeetingPage.slug == result["slug"])
            )
        ).scalar_one()
        assert page.jurisdiction == "Override Test County, ZZ"
        assert page.jurisdiction_confidence == "manual_override"


async def test_ordinary_re_ingest_still_updates_jurisdiction_without_an_override():
    """Control for the test above: the manual_override guard must be
    scoped to pages that actually went through this endpoint, not a
    blanket freeze on jurisdiction updates generally."""
    url = "https://example.granicus.com/player/clip/jx-ordinary-reingest"
    result = _ingest(_payload(source_url=url, jurisdiction="Override Default City, ZZ"))

    _ingest(_payload(source_url=url, jurisdiction="Override County C, ZZ"))

    from sqlalchemy import select

    from archive.db.engine import async_session
    from archive.db.models import MeetingPage

    async with async_session() as session:
        page = (
            await session.execute(
                select(MeetingPage).where(MeetingPage.slug == result["slug"])
            )
        ).scalar_one()
        assert page.jurisdiction == "Override County C, ZZ"
