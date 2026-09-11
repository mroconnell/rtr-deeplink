"""`POST /internal/ingest` with a caller-supplied `gov_id`, and the channel
columns -- the ingest-facing half of the gov-id audit (2026-09-10).

Real DB integration against the isolated SQLite file from
tests/conftest.py's _archive_db_schema fixture, driven through the actual
HTTP surface, same convention as tests/test_jurisdiction_override.py.
Every gov_id below is a real registry id (Sioux Falls and Rapid City, SD, from
us_places.csv), never invented -- the registry refuses an id it cannot
render, which one test relies on. South Dakota on purpose (not California, whose Napa page a state-page test looks for, and not Wyoming, which another test relies on being EMPTY): the session-scoped
test database accumulates every file's pages, and tests/test_state_pages.py
asserts a specific Napa page appears on /state/california, which four more
California pages from here pushed off the list (found on the full-suite
run, not on any subset).
"""

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud

client = TestClient(archive.main.app)
_AUTH = {"Authorization": "Bearer test-token"}

SIOUX_FALLS = "us:place:4659020"
RAPID_CITY = "us:place:4652980"


def _payload(**overrides) -> dict:
    payload = {
        "platform": "youtube",
        "source_url": "https://www.youtube.com/watch?v=govidtest01",
        "external_id": "youtube:govidtest01",
        "title": "Town Council Regular Meeting",
        "date": "2026-08-01",
        "jurisdiction": None,
        "video_url": "https://www.youtube.com/embed/govidtest01",
        "video_format": "youtube",
        "segments": [{"start": 0.0, "end": 1.0, "text": "Call to order"}],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }
    payload.update(overrides)
    return payload


def _ingest(payload: dict):
    body = dict(payload)
    body["input_url_normalized"] = payload["source_url"]
    return client.post("/internal/ingest", json=body, headers=_AUTH)


async def _page(source_url: str) -> dict:
    return await crud.get_page_by_slug(
        (await crud.lookup_page_for_url(source_url))["slug"]
    )


async def test_a_supplied_gov_id_pins_the_page_and_names_it_from_the_registry():
    url = "https://www.youtube.com/watch?v=govidtest01"
    r = _ingest(
        _payload(
            gov_id=SIOUX_FALLS,
            video_channel="@CityofSiouxFalls",
            video_channel_id="UCsiouxfalls",
        )
    )
    assert r.status_code == 200, r.text
    page = await _page(url)
    assert page["gov_id"] == SIOUX_FALLS
    assert (
        page["jurisdiction"] == "Sioux Falls, SD"
    )  # from the registry row, not a name
    assert page["jurisdiction_confidence"] == "pinned"
    assert page["video_channel"] == "@CityofSiouxFalls"
    assert page["video_channel_id"] == "UCsiouxfalls"


async def test_a_supplied_gov_id_that_disagrees_with_the_page_is_refused():
    """The collision detector: two pushes for the same external_id from
    two different governments (ENUMERATION_METHODS.md §98's generic-embed
    shape) must not silently overwrite each other."""
    url = "https://www.youtube.com/watch?v=govidtest02"
    assert (
        _ingest(
            _payload(
                source_url=url, external_id="youtube:govidtest02", gov_id=SIOUX_FALLS
            )
        ).status_code
        == 200
    )
    r = _ingest(
        _payload(source_url=url, external_id="youtube:govidtest02", gov_id=RAPID_CITY)
    )
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["existing_gov_id"] == SIOUX_FALLS
    assert body["supplied_gov_id"] == RAPID_CITY
    page = await _page(url)
    assert page["gov_id"] == SIOUX_FALLS  # untouched
    # The same id again is fine -- idempotent re-push.
    assert (
        _ingest(
            _payload(
                source_url=url, external_id="youtube:govidtest02", gov_id=SIOUX_FALLS
            )
        ).status_code
        == 200
    )


async def test_an_unknown_gov_id_is_refused_not_ignored():
    r = _ingest(
        _payload(
            source_url="https://www.youtube.com/watch?v=govidtest03",
            external_id="youtube:govidtest03",
            gov_id="rtr:us:zz:no-such-government",
        )
    )
    assert r.status_code == 400
    assert r.json()["gov_id"] == "rtr:us:zz:no-such-government"


async def test_a_supplied_gov_id_fills_a_page_that_had_none():
    """A page archived without an identity gains the caller's -- a caller
    id counts as 'identity supplied' for WO-102's gates, unlike a
    transcript-only push, which must still leave everything alone."""
    url = "https://www.youtube.com/watch?v=govidtest04"
    assert (
        _ingest(_payload(source_url=url, external_id="youtube:govidtest04")).status_code
        == 200
    )
    page = await _page(url)
    assert not page["gov_id"] or page["gov_id"].startswith("rtr:unknown:")
    assert (
        _ingest(
            _payload(
                source_url=url, external_id="youtube:govidtest04", gov_id=SIOUX_FALLS
            )
        ).status_code
        == 200
    )
    page = await _page(url)
    assert page["gov_id"] == SIOUX_FALLS
    assert page["jurisdiction"] == "Sioux Falls, SD"
    # transcript-only push: no jurisdiction, no gov_id, no channel -> nothing changes
    assert (
        _ingest(
            _payload(source_url=url, external_id="youtube:govidtest04", title=None)
        ).status_code
        == 200
    )
    page = await _page(url)
    assert page["gov_id"] == SIOUX_FALLS


async def test_a_blank_multi_gov_answer_on_re_ingest_keeps_the_existing_gov_id():
    """WO-215: rung 1b (WO-210, `MULTI_GOV_HOSTS`) answers `blank` --
    gov_id `rtr:unknown:<host>` -- for EVERY re-ingest on a shared host
    (YouTube here) that has no matching per-video/channel pin,
    regardless of what identity the page already carries. That answer
    means "no matching pin on THIS re-ingest," not "this page has no
    government," so a page that keyed to a real government at a tier the
    ladder could still produce before rung 1b existed (`registry` --
    the shape a real production page was found in: Millbrae, CA,
    `us:place:0647486`, `www.youtube.com`, by a 2026-09-11 dry run of
    `scripts/backfill_gov_id.py`) must not be blanked by a routine later
    re-ingest that supplies a jurisdiction string but no matching pin --
    exactly what a caption-only re-push for this video would send.

    A caller-supplied `gov_id` always lands on tier `pinned`, never
    `registry`, so the tier is hand-set afterward to simulate the real
    pre-WO-210 shape directly -- same pattern as
    tests/test_jurisdiction_backfill_apply.py's `_seed_stale()`.
    """
    from sqlalchemy import select

    from archive.db.engine import async_session
    from archive.db.models import MeetingPage

    url = "https://www.youtube.com/watch?v=govidtest06"
    assert (
        _ingest(
            _payload(
                source_url=url, external_id="youtube:govidtest06", gov_id=SIOUX_FALLS
            )
        ).status_code
        == 200
    )
    slug = (await _page(url))["slug"]
    async with async_session() as session:
        page = (
            await session.execute(select(MeetingPage).where(MeetingPage.slug == slug))
        ).scalar_one()
        page.jurisdiction_confidence = "registry"
        await session.commit()

    assert (
        _ingest(
            _payload(
                source_url=url,
                external_id="youtube:govidtest06",
                jurisdiction="Sioux Falls, SD",
            )
        ).status_code
        == 200
    )
    page = await _page(url)
    assert page["gov_id"] == SIOUX_FALLS  # not downgraded to rtr:unknown:*
    assert page["jurisdiction_confidence"] == "registry"
