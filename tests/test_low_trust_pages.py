"""Tests for GET /internal/low-trust-pages (archive/main.py) and the
crud.list_low_trust_pages() audit behind it, plus the best_effort
plumbing the whole thing rides on -- added 2026-08-21 (WO-21).

Real DB integration against the isolated SQLite file from
tests/conftest.py's _archive_db_schema fixture, driven through the actual
POST /internal/ingest HTTP surface rather than crud directly wherever the
point is that a field survives Pydantic -- which is precisely where
best_effort used to be lost (IngestRequest had no such field, so
`payload = req.model_dump(...)` dropped it before either the social gate
or the database ever saw it).

That shared session-scoped DB is never reset between tests, so every
assertion here looks the page up by its own unique slug/source URL rather
than asserting on totals (same convention as
tests/test_jurisdiction_backfill_audit.py).
"""

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud

client = TestClient(archive.main.app)

_AUTH = {"Authorization": "Bearer test-token"}


def _payload(**overrides) -> dict:
    payload = {
        "platform": "granicus",
        "source_url": "https://example.granicus.com/player/clip/low-trust",
        "external_id": None,
        "title": "City Council Regular Meeting",
        "date": "2026-08-01",
        "jurisdiction": "City of Dublin, CA",
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


def _fetch(limit: int = 1000, offset: int = 0) -> dict:
    response = client.get(
        f"/internal/low-trust-pages?limit={limit}&offset={offset}", headers=_AUTH
    )
    assert response.status_code == 200, response.text
    return response.json()


def _row_for(slug: str, **kwargs) -> dict | None:
    data = _fetch(**kwargs)
    for page in data["pages"]:
        if page["slug"] == slug:
            return page
    return None


# --- auth ---------------------------------------------------------------


def test_rejects_missing_token():
    # 404, not 401/403 -- matches every other /internal/* route.
    assert client.get("/internal/low-trust-pages").status_code == 404


def test_rejects_wrong_token():
    response = client.get(
        "/internal/low-trust-pages", headers={"Authorization": "Bearer nope"}
    )
    assert response.status_code == 404


# --- best_effort survives the boundary and lands on the row -------------


def test_best_effort_survives_ingest_and_appears_in_audit():
    url = "https://example.org/agendas/low-trust-best-effort"
    result = _ingest(_payload(platform="unknown", source_url=url, best_effort=True))

    row = _row_for(result["slug"])
    assert row is not None
    assert row["best_effort"] is True
    assert set(row["reasons"]) >= {"best_effort", "unknown_platform"}
    assert row["source_url"].endswith("/low-trust-best-effort")


def test_youtube_delegated_best_effort_page_is_caught():
    """The case that motivated the column: generic_fallback found a
    YouTube embed and delegated, so `platform` is "youtube", not
    "unknown". A platform-only audit would miss it entirely -- and per
    generic_fallback.py's own comment this is the *most* common real
    fallback outcome, not an edge case."""
    url = "https://example.org/agendas/low-trust-youtube-delegated"
    result = _ingest(
        _payload(
            platform="youtube",
            source_url=url,
            # A confidently-validated jurisdiction, so neither of the
            # other two reasons can be what caught this row.
            jurisdiction="City of Dublin, CA",
            best_effort=True,
        )
    )

    row = _row_for(result["slug"])
    assert row is not None
    assert row["platform"] == "youtube"
    assert row["reasons"] == ["best_effort"]


def test_re_ingest_without_best_effort_does_not_clear_the_flag():
    """Every transcript-only pusher (fetch_youtube_transcripts.py and
    friends) sends a partial payload with no best_effort key, which
    IngestRequest defaults to False. That must never un-flag a page --
    see _find_or_create_page()'s comment for the reasoning."""
    url = "https://example.org/agendas/low-trust-sticky"
    result = _ingest(_payload(platform="youtube", source_url=url, best_effort=True))
    assert _row_for(result["slug"]) is not None

    # A later partial push, exactly as a transcript-only script sends it.
    _ingest(
        _payload(
            platform="youtube",
            source_url=url,
            segments=[{"start": 0.0, "end": 2.0, "text": "Better transcript"}],
        )
    )

    row = _row_for(result["slug"])
    assert row is not None, "a partial re-ingest silently cleared best_effort"
    assert row["best_effort"] is True


# --- the other two reasons ---------------------------------------------


def test_unknown_platform_page_without_best_effort_is_caught():
    # Pre-WO-21 rows can't have best_effort set (nothing ever wrote it),
    # so the platform check is what still covers them.
    url = "https://example.org/agendas/low-trust-unknown-only"
    result = _ingest(_payload(platform="unknown", source_url=url))

    row = _row_for(result["slug"])
    assert row is not None
    assert row["best_effort"] is False
    assert row["reasons"] == ["unknown_platform"]


async def test_unverified_jurisdiction_confidence_is_caught():
    url = "https://example.granicus.com/player/clip/low-trust-unverified-jx"
    result = _ingest(_payload(source_url=url))

    # finalize_jurisdiction() runs on every ingest, so a genuinely
    # unverified value can't be produced through the normal path once the
    # jurisdiction is a real, validated city -- set it directly, same
    # approach tests/test_jurisdiction_backfill_audit.py's _seed_stale()
    # helper already uses.
    from sqlalchemy import select

    from archive.db.engine import async_session
    from archive.db.models import MeetingPage

    async with async_session() as session:
        page = (
            await session.execute(
                select(MeetingPage).where(MeetingPage.slug == result["slug"])
            )
        ).scalar_one()
        page.jurisdiction_confidence = "unverified"
        await session.commit()

    row = _row_for(result["slug"])
    assert row is not None
    assert row["reasons"] == ["unverified_jurisdiction"]


def test_ordinary_verified_page_is_not_listed():
    url = "https://example.granicus.com/player/clip/low-trust-clean-page"
    result = _ingest(_payload(source_url=url))

    row = _row_for(result["slug"])
    assert row is None, f"a clean adapter-resolved page was flagged: {row}"


# --- response shape / pagination ---------------------------------------


def test_response_shape_and_pagination():
    # Seed enough that a limit of 1 is provably a page, not the whole set.
    for n in range(3):
        _ingest(
            _payload(
                platform="unknown",
                source_url=f"https://example.org/agendas/low-trust-page-{n}",
                best_effort=True,
            )
        )

    data = _fetch(limit=1)
    assert data["limit"] == 1
    assert data["offset"] == 0
    assert len(data["pages"]) == 1
    assert data["total"] >= 3
    # SQLite always has the column (create_all builds it off the model);
    # only a Postgres mid-deploy window can report False here.
    assert data["best_effort_column_available"] is True

    second = _fetch(limit=1, offset=1)
    assert second["total"] == data["total"]
    assert second["pages"][0]["slug"] != data["pages"][0]["slug"]


# --- deploy-order safety ------------------------------------------------


async def test_tolerates_the_column_not_existing_yet(monkeypatch):
    """The one-deploy window this code is explicitly designed to survive:
    the new build is live but its Alembic migration hasn't run, so
    meeting_pages.best_effort doesn't exist (CLAUDE.md's rule, and the
    2026-08-17 UndefinedColumnError outage that produced it).

    Synthetic in one narrow respect and flagged as such per CLAUDE.md: the
    column genuinely *can't* be absent on SQLite (create_all() builds the
    table straight off today's model), so _best_effort_available() is
    forced False here rather than a real column-less database being
    constructed. What that does exercise for real is every code path
    gated on it -- both the write in _find_or_create_page() and the read
    here must produce SQL that never names the column. If either one
    referenced it unconditionally, this test would still pass on SQLite
    while failing in production, so it's paired with the deliberate
    design choices that make the SQL itself column-free: no Python-side
    `default=` on the mapping (so an unset attribute is omitted from the
    INSERT) and deferred=True (so no plain `select(MeetingPage)` names
    it). See MeetingPage.best_effort's comment.
    """
    monkeypatch.setattr(crud, "_best_effort_available", _always_unavailable)

    url = "https://example.org/agendas/low-trust-pre-migration"
    # Ingest must still succeed, just without recording the flag.
    result = await crud.ingest_resolution(
        _payload(platform="unknown", source_url=url, best_effort=True), url
    )
    assert result["created"] is True

    data = await crud.list_low_trust_pages(limit=1000)
    assert data["best_effort_column_available"] is False
    row = next((p for p in data["pages"] if p["slug"] == result["slug"]), None)
    # Still surfaced -- via the platform reason, which needs no new column.
    assert row is not None
    assert row["best_effort"] is False
    assert row["reasons"] == ["unknown_platform"]


async def _always_unavailable(session) -> bool:
    return False


async def test_limit_is_clamped_to_a_sane_range():
    # A caller asking for everything shouldn't be able to ask for an
    # unbounded scan, and limit=0 shouldn't return an empty page forever.
    assert (await crud.list_low_trust_pages(limit=10**6))["limit"] == 1000
    assert (await crud.list_low_trust_pages(limit=0))["limit"] == 1
    assert (await crud.list_low_trust_pages(offset=-5))["offset"] == 0
