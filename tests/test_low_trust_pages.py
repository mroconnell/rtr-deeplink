"""Tests for GET /internal/low-trust-pages (archive/main.py) and the
crud.list_low_trust_pages() audit behind it, plus the best_effort
plumbing the whole thing rides on -- added 2026-08-21 (WO-21), extended
the same day (WO-38) with the review ledger: reviewed_at,
?unreviewed=true, ?reason=, and POST /internal/low-trust-pages/
mark-reviewed.

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


def _fetch(limit: int = 1000, offset: int = 0, **params) -> dict:
    query = f"limit={limit}&offset={offset}"
    for key, value in params.items():
        query += f"&{key}={value}"
    response = client.get(f"/internal/low-trust-pages?{query}", headers=_AUTH)
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


# --- review ledger: ?unreviewed=true + mark-reviewed (WO-38) ------------
#
# The reason this half exists: the first real production call to this
# endpoint (2026-08-21) returned 474 rows, so "read the JSON and re-triage
# it" isn't a workable loop. See crud.list_low_trust_pages()'s docstring
# for the measured breakdown.


def _mark(ids, **params) -> dict:
    query = "&".join([f"ids={ids}"] + [f"{k}={v}" for k, v in params.items()])
    response = client.post(
        f"/internal/low-trust-pages/mark-reviewed?{query}", headers=_AUTH
    )
    return response.json() | {"_status": response.status_code}


def test_mark_reviewed_rejects_missing_token():
    assert client.post("/internal/low-trust-pages/mark-reviewed?ids=1").status_code == (
        404
    )


def test_mark_reviewed_requires_ids():
    """No "mark everything" mode, by design -- an idless call must be an
    error, not a 474-row sweep."""
    response = client.post("/internal/low-trust-pages/mark-reviewed", headers=_AUTH)
    assert response.status_code == 400
    assert "ids" in response.json()["detail"]

    # An explicitly empty list is the same thing, not "all".
    assert _mark("")["_status"] == 400


def test_mark_reviewed_rejects_non_integer_ids():
    assert _mark("12,notanid")["_status"] == 400


def test_mark_reviewed_dry_run_writes_nothing():
    url = "https://example.org/agendas/low-trust-review-dry-run"
    result = _ingest(_payload(platform="unknown", source_url=url, best_effort=True))
    page_id = _row_for(result["slug"])["meeting_page_id"]

    marked = _mark(page_id)
    assert marked["_status"] == 200
    assert marked["dry_run"] is True
    assert marked["would_update"] == 1
    assert marked["updated"] == 0
    assert [c["meeting_page_id"] for c in marked["changed"]] == [page_id]

    # Still unreviewed, and still in the ?unreviewed=true queue.
    assert _row_for(result["slug"])["reviewed_at"] is None
    assert _row_for(result["slug"], unreviewed="true") is not None


def test_mark_reviewed_stamps_and_removes_from_the_unreviewed_queue():
    url = "https://example.org/agendas/low-trust-review-commit"
    result = _ingest(_payload(platform="unknown", source_url=url, best_effort=True))
    slug = result["slug"]
    page_id = _row_for(slug)["meeting_page_id"]

    marked = _mark(page_id, dry_run="false")
    assert marked["updated"] == 1

    row = _row_for(slug)
    # Still listed by default -- reviewing is a ledger entry, not a
    # filter on the audit itself.
    assert row is not None
    assert row["reviewed_at"] is not None

    # ...but gone from the working queue, which is the whole point.
    assert _row_for(slug, unreviewed="true") is None


def test_mark_reviewed_is_idempotent():
    """Re-running the same call must be a no-op, never a re-dating: the
    timestamp answers "when did a human last look at this", and silently
    refreshing it on a repeated request would destroy that."""
    url = "https://example.org/agendas/low-trust-review-idempotent"
    result = _ingest(_payload(platform="unknown", source_url=url, best_effort=True))
    page_id = _row_for(result["slug"])["meeting_page_id"]

    first = _mark(page_id, dry_run="false")
    assert first["updated"] == 1
    stamped_at = _row_for(result["slug"])["reviewed_at"]

    second = _mark(page_id, dry_run="false")
    assert second["updated"] == 0
    assert second["changed"] == []
    assert [e["meeting_page_id"] for e in second["already_reviewed"]] == [page_id]
    assert _row_for(result["slug"])["reviewed_at"] == stamped_at


def test_unreview_clears_the_stamp():
    """The undo for a mis-pasted id list -- without it the only repair
    would need direct DATABASE_URL access."""
    url = "https://example.org/agendas/low-trust-review-undo"
    result = _ingest(_payload(platform="unknown", source_url=url, best_effort=True))
    page_id = _row_for(result["slug"])["meeting_page_id"]

    _mark(page_id, dry_run="false")
    assert _row_for(result["slug"], unreviewed="true") is None

    undone = _mark(page_id, dry_run="false", unreview="true")
    assert undone["updated"] == 1
    assert undone["changed"][0]["reviewed_at_after"] is None
    assert _row_for(result["slug"])["reviewed_at"] is None
    assert _row_for(result["slug"], unreviewed="true") is not None

    # Idempotent in this direction too.
    assert _mark(page_id, dry_run="false", unreview="true")["updated"] == 0


def test_mark_reviewed_reports_unknown_ids_without_failing_the_batch():
    url = "https://example.org/agendas/low-trust-review-partial"
    result = _ingest(_payload(platform="unknown", source_url=url, best_effort=True))
    page_id = _row_for(result["slug"])["meeting_page_id"]

    marked = _mark(f"{page_id},99999999", dry_run="false")
    assert marked["updated"] == 1
    assert marked["missing_ids"] == [99999999]


async def test_mark_reviewed_caps_batch_size():
    ids = set(range(1, crud._MARK_REVIEWED_MAX_IDS + 2))
    response = client.post(
        "/internal/low-trust-pages/mark-reviewed?ids="
        + ",".join(str(i) for i in sorted(ids)),
        headers=_AUTH,
    )
    assert response.status_code == 400
    assert "at most" in response.json()["detail"]


# --- reason filter ------------------------------------------------------


def test_reason_filter_narrows_to_a_single_reason():
    """Worth having because the real queue is 470/474 one reason: without
    this, the handful of pages flagged for a *different* reason are
    invisible in practice."""
    platform_only = _ingest(
        _payload(
            platform="unknown",
            source_url="https://example.org/agendas/low-trust-reason-platform",
        )
    )
    delegated = _ingest(
        _payload(
            platform="youtube",
            source_url="https://example.org/agendas/low-trust-reason-besteffort",
            jurisdiction="City of Dublin, CA",
            best_effort=True,
        )
    )

    by_platform = _fetch(reason="unknown_platform")
    assert by_platform["reason"] == "unknown_platform"
    slugs = {p["slug"] for p in by_platform["pages"]}
    assert platform_only["slug"] in slugs
    assert delegated["slug"] not in slugs
    assert all("unknown_platform" in p["reasons"] for p in by_platform["pages"])

    by_best_effort = _fetch(reason="best_effort")
    assert delegated["slug"] in {p["slug"] for p in by_best_effort["pages"]}
    assert all(p["best_effort"] for p in by_best_effort["pages"])
    assert by_best_effort["total"] < _fetch()["total"]


def test_unknown_reason_is_a_400_not_a_silent_pass_through():
    # A typo'd filter returning the full unfiltered set would read as
    # "nothing matched the filter", which is the wrong conclusion.
    response = client.get("/internal/low-trust-pages?reason=spoofed", headers=_AUTH)
    assert response.status_code == 400


def test_unfiltered_call_is_unchanged():
    """Nothing depending on today's response may break: same rows, and
    the pre-WO-38 keys all still present."""
    data = _fetch()
    assert data["unreviewed"] is False
    assert data["reason"] is None
    assert {"total", "limit", "offset", "best_effort_column_available", "pages"} <= (
        set(data)
    )
    # A reviewed page is still listed by default (see the commit test);
    # ?unreviewed=true is strictly a subset.
    assert _fetch(unreviewed="true")["total"] <= data["total"]


# --- deploy-order safety for reviewed_at --------------------------------


async def test_read_tolerates_reviewed_at_not_existing_yet(monkeypatch):
    """Same one-deploy window as test_tolerates_the_column_not_existing_yet
    above, one migration later, and synthetic in the same narrow way
    (SQLite always has the column, so the detect is forced False rather
    than a column-less database being built).

    What it exercises for real is that neither the SELECT nor the WHERE
    ever names reviewed_at when the gate is False -- which is what the
    deferred=True mapping and the absence of any Python-side default make
    possible. ?unreviewed=true degrading to a no-op is correct rather than
    fail-open: with no column, nothing can have been marked reviewed.
    """
    monkeypatch.setattr(crud, "_reviewed_at_available", _always_unavailable)

    url = "https://example.org/agendas/low-trust-pre-reviewed-at"
    result = await crud.ingest_resolution(
        _payload(platform="unknown", source_url=url), url
    )
    assert result["created"] is True

    data = await crud.list_low_trust_pages(limit=1000, unreviewed=True)
    assert data["reviewed_at_column_available"] is False
    row = next((p for p in data["pages"] if p["slug"] == result["slug"]), None)
    assert row is not None
    assert row["reviewed_at"] is None


async def test_write_refuses_when_reviewed_at_does_not_exist_yet(monkeypatch):
    """Synthetic in the same way, and asserting the opposite policy from
    the read above on purpose: a read can degrade honestly, a write
    cannot. Reporting "marked reviewed" while recording nothing would be
    worse than an error, so this is a 503 the caller can retry after the
    migration runs."""
    monkeypatch.setattr(crud, "_reviewed_at_available", _always_unavailable)

    response = client.post(
        "/internal/low-trust-pages/mark-reviewed?ids=1&dry_run=false", headers=_AUTH
    )
    assert response.status_code == 503
    body = response.json()
    assert body["reviewed_at_column_available"] is False
    assert body["updated"] == 0
