"""Tests for POST /internal/jurisdiction/override (archive/main.py) and
crud.override_jurisdiction() behind it -- 2026-08-31, unlocking two
BACKLOG.md entries that had no write path: Santa Clara's 4 already-valid-
but-inconsistent jurisdiction strings needing one canonical form (which
finalize_jurisdiction() makes zero changes to, since each already
validates independently), and the low-trust queue's missing "review ->
repair" write path.

Rewritten for WO-99, which changed what this endpoint *is*. It used to
take a jurisdiction STRING and stamp it on N rows -- and Santa Clara
re-fragmented within two days, because the next ingest recomputed the old
spellings for pages the override had never seen. It now takes a `gov_id`
(which must already exist in the registry -- no caller-supplied display
text is accepted anywhere in this repo any more) and, alongside the row
write, emits a `tenant_overrides.csv`-shaped RULE for a human to commit,
so the fix reaches pages nobody has archived yet.

Real DB integration against the isolated SQLite file from
tests/conftest.py's _archive_db_schema fixture, driven through the actual
POST /internal/ingest HTTP surface -- same convention as
tests/test_low_trust_pages.py, which this file mirrors structurally.
"""

import pytest
from fastapi.testclient import TestClient

import archive.main
from app.utils.gov_registry import registry
from archive.db import crud

client = TestClient(archive.main.app)

_AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture(autouse=True)
def _synthetic_government(monkeypatch):
    """Make `_GOV_ID` resolvable, without adding a test row to the
    committed registry. Patched at the seam `override_jurisdiction()` and
    `_hub_identity()` both use, so the endpoint's real "must be a
    government we can name" check still runs -- see
    test_rejects_a_gov_id_the_registry_does_not_know."""
    real = registry.governments()

    def _lookup(gov_id):
        if gov_id == _GOV_ID:
            return _SYNTHETIC_GOV
        return real.get(gov_id) or registry.government_for_id(gov_id)

    monkeypatch.setattr(crud, "registry_government_for_id", _lookup)
    monkeypatch.setattr(
        crud, "registry_governments", lambda: {**real, _GOV_ID: _SYNTHETIC_GOV}
    )


@pytest.fixture(autouse=True)
def _rules_file(tmp_path, monkeypatch):
    """Keep the pending-rules file inside the test's own tmp dir.

    Its default lives under /tmp so an operator on the Render shell can
    read it back off an ephemeral filesystem; a test suite writing to a
    fixed path there would collide with a parallel session's run and
    accumulate rows across runs, which is exactly what
    `tenant_override_rules_written == 1` must not depend on.
    """
    monkeypatch.setattr(
        crud, "JURISDICTION_OVERRIDE_RULES_FILE", tmp_path / "pending.csv"
    )


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


# A SYNTHETIC government, injected into the registry for these tests only
# -- and the ", ZZ" state is the whole reason.
#
# The obvious choice was a real one (Fresno County, the architecture
# doc's own worked example). Writing it here broke
# tests/test_state_pages.py::test_state_page_lists_states_jurisdictions in
# a full-suite run while passing in isolation: this file's writes land in
# the session-scoped DB every other file reads from, and a real ", CA"
# jurisdiction on ~14 override pages dated 2026-08-01 pushed the Napa
# fixture out of /state/california's 25-row recent list. That is exactly
# the hazard this file's own "Synthetic ', ZZ' jurisdictions throughout"
# comment already warned about for the old string-based endpoint; the
# rewrite has to keep the property, not just the comment.
#
# So: a real-looking id whose display name carries no valid state suffix,
# which makes every state page and hub blind to these rows.
_GOV_ID = "us:county:99999"
_GOV_NAME = "Override Test County, ZZ"
_SYNTHETIC_GOV = registry.Government(
    gov_id=_GOV_ID,
    gov_name="Override Test County",
    gov_type="county",
    country="us",
    state="ZZ",
)


def _override(ids, gov_id=_GOV_ID, **params) -> dict:
    query = "&".join(
        [f"ids={ids}", f"gov_id={gov_id}"] + [f"{k}={v}" for k, v in params.items()]
    )
    response = client.post(f"/internal/jurisdiction/override?{query}", headers=_AUTH)
    return response.json() | {"_status": response.status_code}


# --- auth / validation ---------------------------------------------------


def test_rejects_missing_token():
    assert (
        client.post(
            f"/internal/jurisdiction/override?ids=1&gov_id={_GOV_ID}"
        ).status_code
        == 404
    )


def test_rejects_wrong_token():
    response = client.post(
        f"/internal/jurisdiction/override?ids=1&gov_id={_GOV_ID}",
        headers={"Authorization": "Bearer nope"},
    )
    assert response.status_code == 404


def test_requires_ids():
    response = client.post(
        f"/internal/jurisdiction/override?gov_id={_GOV_ID}", headers=_AUTH
    )
    assert response.status_code == 400
    assert "ids" in response.json()["detail"]


async def test_requires_a_gov_id():
    result = _ingest(
        _payload(source_url="https://example.granicus.com/player/clip/jx-blank")
    )
    page_id = await _page_id_for(result["slug"])
    response = client.post(
        f"/internal/jurisdiction/override?ids={page_id}", headers=_AUTH
    )
    assert response.status_code == 400
    assert "gov_id is required" in response.json()["detail"]
    assert _override(page_id, gov_id="%20%20")["_status"] == 400


async def test_rejects_a_gov_id_the_registry_does_not_know():
    """A pin to an id with no registry row is the one thing worse than no
    pin: nothing can render its name, so the page lands on a blank hub
    while looking resolved. `resolver._pinned()` refuses to return such an
    id for the same reason; this refuses to write one."""
    result = _ingest(
        _payload(source_url="https://example.granicus.com/player/clip/jx-unknown-gov")
    )
    page_id = await _page_id_for(result["slug"])
    response = _override(page_id, gov_id="us:place:0000000")
    assert response["_status"] == 400
    assert "unknown gov_id" in response["detail"]


async def test_accepts_a_national_id_the_committed_file_has_not_got_yet():
    """`governments.csv` is a generated snapshot of what some scoring run
    happened to resolve to, not a list of every government that exists.
    Requiring a row there would mean a valid `us:county:56021` could not
    be pinned until someone re-ran the scorer -- friction for no safety
    gain, since for a national id every field is a function of the id.

    Autauga County, AL: a real county FIPS, and one of the 2,856 in
    us_counties.csv that no archived page has ever resolved to, so the
    committed file has no row for it."""
    assert "us:county:01001" not in registry.governments()
    gov = registry.government_for_id("us:county:01001")
    assert gov is not None
    assert (gov.gov_name, gov.state, gov.gov_type) == (
        "Autauga County",
        "AL",
        "county",
    )
    # Garbage in the same namespace is still refused.
    assert registry.government_for_id("us:county:99998") is None


async def test_rejects_an_unknown_meeting_kind():
    result = _ingest(
        _payload(source_url="https://example.granicus.com/player/clip/jx-bad-kind")
    )
    page_id = await _page_id_for(result["slug"])
    response = _override(page_id, meeting_kind="brunch")
    assert response["_status"] == 400
    assert "meeting_kind" in response["detail"]


def test_rejects_non_integer_ids():
    assert _override("12,notanid")["_status"] == 400


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

    overridden = _override(page_id)
    assert overridden["_status"] == 200
    assert overridden["dry_run"] is True
    assert overridden["would_update"] == 1
    assert overridden["updated"] == 0
    assert [c["meeting_page_id"] for c in overridden["changed"]] == [page_id]
    assert overridden["changed"][0]["gov_id_after"] == _GOV_ID
    # The display name comes from the registry row, never from the
    # caller.
    assert overridden["changed"][0]["jurisdiction_after"] == _GOV_NAME
    # A dry run shows the RULE it would write as well as the row diff --
    # seeing the rule before creating it is most of the point of one.
    assert overridden["tenant_override_rules"], "dry run must preview the rule"
    rule = overridden["tenant_override_rules"][0]
    assert rule["tenant_host"] == "example.granicus.com"
    assert rule["gov_id"] == _GOV_ID
    assert rule["strength"] == "authoritative"
    # ...but writes nothing to the rules file either.
    assert overridden["tenant_override_rules_written"] == 0

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
        assert page.gov_id != _GOV_ID


async def test_commit_writes_jurisdiction_confidence_and_reviewed_at():
    result = _ingest(
        _payload(source_url="https://example.granicus.com/player/clip/jx-commit")
    )
    page_id = await _page_id_for(result["slug"])

    overridden = _override(page_id, dry_run="false", meeting_kind="press_conference")
    assert overridden["updated"] == 1
    assert overridden["reviewed_at_stamped"] is True
    # The rule half actually landed this time.
    assert overridden["tenant_override_rules_written"] == 1

    from sqlalchemy import select

    from archive.db.engine import async_session
    from archive.db.models import MeetingPage

    # Select the specific columns rather than the whole ORM object --
    # reviewed_at is a deferred column (see MeetingPage.reviewed_at's own
    # comment), and touching it via plain attribute access outside the
    # SELECT that named it raises MissingGreenlet on an async session.
    async with async_session() as session:
        jurisdiction, confidence, gov_id, gov_type, kind, reviewed_at = (
            await session.execute(
                select(
                    MeetingPage.jurisdiction,
                    MeetingPage.jurisdiction_confidence,
                    MeetingPage.gov_id,
                    MeetingPage.gov_type,
                    MeetingPage.meeting_kind,
                    MeetingPage.reviewed_at,
                ).where(MeetingPage.slug == result["slug"])
            )
        ).one()
        assert gov_id == _GOV_ID
        assert gov_type == "county"
        assert jurisdiction == _GOV_NAME
        assert confidence == "manual_override"
        # Decision D2a: a press conference is not a meeting of a body,
        # and the two gates that key on "plausibly meeting-length" need
        # telling rather than guessing from a duration.
        assert kind == "press_conference"
        assert reviewed_at is not None


async def test_idempotent_on_repeat_call():
    result = _ingest(
        _payload(source_url="https://example.granicus.com/player/clip/jx-idempotent")
    )
    page_id = await _page_id_for(result["slug"])

    first = _override(page_id, dry_run="false")
    assert first["updated"] == 1

    second = _override(page_id, dry_run="false")
    assert second["updated"] == 0
    assert second["changed"] == []
    assert [e["meeting_page_id"] for e in second["already_overridden"]] == [page_id]


async def test_reports_unknown_ids_without_failing_the_batch():
    result = _ingest(
        _payload(source_url="https://example.granicus.com/player/clip/jx-partial")
    )
    page_id = await _page_id_for(result["slug"])

    overridden = _override(f"{page_id},99999999", dry_run="false")
    assert overridden["updated"] == 1
    assert overridden["missing_ids"] == [99999999]


def test_caps_batch_size():
    ids = set(range(1, crud._JURISDICTION_OVERRIDE_MAX_IDS + 2))
    response = client.post(
        f"/internal/jurisdiction/override?gov_id={_GOV_ID}&ids="
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

    _override(page_id, dry_run="false")

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
        assert page.jurisdiction == _GOV_NAME
        assert page.jurisdiction_confidence == "manual_override"
        # The identity is on the same guard as the display name, and for
        # the same reason: a passive re-resolve would overwrite it with
        # exactly the guess the override was written to correct.
        assert page.gov_id == _GOV_ID


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
