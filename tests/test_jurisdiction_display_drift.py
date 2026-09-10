"""Tests for crud.effective_jurisdiction() (WO-114) and the real bug it
fixes: a page's DISPLAYED jurisdiction drifting out of sync with its own
`gov_id` whenever the stored `MeetingPage.jurisdiction` TEXT predates (or
was written before) some now-fixed convention.

effective_jurisdiction() shares `_hub_identity()`'s exact three-case rule
(see that function's docstring in archive/db/crud.py) -- it is the
non-hub counterpart of `hub_slug_for_page()`, used wherever a single
page's jurisdiction is shown to a reader rather than grouped into a `/j/`
hub.

Real, confirmed production bug (found 2026-09-05 via
/internal/jurisdiction/search?q=Kansas): two `manual_override` pages for
Kansas City (gov_id=us:place:2938000, kansascity.granicus.com) are stored
with the bare jurisdiction string "Kansas City" -- no state -- because
they were overridden before the override endpoint always wrote the full
display_name(). "Kansas City" is a genuinely ambiguous real jurisdiction
name (see tests/test_jurisdiction_enrich.py's own
test_lookup_city_state_is_none_for_a_real_ambiguous_name-style coverage:
`je.lookup_city_state("Kansas City") is None`), which is exactly why a
human had to pin it by gov_id in the first place -- the raw stored string
alone can never disambiguate it.

`us:place:2938000` and `us:county:01005` are both real ids confirmed
directly against this repo's own committed registry data
(app/utils/jurisdiction_data/governments.csv and us_counties.csv) rather
than invented -- same convention tests/test_gov_registry.py's module
docstring documents.
"""

from sqlalchemy import select

import archive.main
from app.utils.gov_registry import registry
from archive.db import crud
from archive.db.engine import async_session
from archive.db.models import MeetingPage
from fastapi.testclient import TestClient

client = TestClient(archive.main.app)

_AUTH = {"Authorization": "Bearer test-token"}

# Real municipality row, confirmed present in the committed registry
# snapshot (governments.csv) -- see this module's docstring.
_KC_GOV_ID = "us:place:2938000"

# Real county FIPS id with NO row in the committed governments.csv
# snapshot -- confirmed the same way
# tests/test_jurisdiction_override.py::
# test_accepts_a_national_id_the_committed_file_has_not_got_yet confirms
# it (Barbour County, AL: a real county no archived page has ever
# resolved to, so the generated snapshot never picked it up). Was
# Autauga County (us:county:01001) until the 2026-09-09 score_gov_
# registry.py re-run picked that one up for real -- see this file's own
# test_registry_fixtures_are_real, which exists to catch exactly that
# and force picking a fresh never-scored example.
# effective_jurisdiction()/`_hub_identity()` both key off
# registry_governments() (the committed-snapshot lookup), not
# government_for_id() (which would derive this one from the national
# table) -- so this id exercises the real "gov_id set, no registry row
# yet" case, not a fabricated one.
_UNSCORED_GOV_ID = "us:county:01005"


def test_registry_fixtures_are_real():
    # Guards the two assumptions this whole file is built on, so a future
    # regeneration of the registry data can't silently turn either into a
    # different (or no-longer-representative) case without a loud
    # failure here first.
    assert _KC_GOV_ID in registry.governments()
    assert _UNSCORED_GOV_ID not in registry.governments()
    assert registry.government_for_id(_UNSCORED_GOV_ID) is not None


# --- crud.effective_jurisdiction() unit tests -------------------------


def test_effective_jurisdiction_derives_from_the_registry_when_a_row_exists():
    # The real, confirmed production case: a manual_override page keyed
    # to Kansas City's real gov_id but still storing the bare, pre-fix
    # "Kansas City" string must display the full, disambiguated name --
    # exactly what its own /j/ hub already shows via _hub_identity().
    assert crud.effective_jurisdiction(_KC_GOV_ID, "Kansas City") == "Kansas City, MO"


def test_effective_jurisdiction_falls_back_when_gov_id_has_no_registry_row():
    # A freshly-minted/not-yet-backfilled gov_id: falls back to the
    # stored string exactly like _hub_identity()'s own case 2.
    assert crud.effective_jurisdiction(_UNSCORED_GOV_ID, "Barbour, AL") == "Barbour, AL"


def test_effective_jurisdiction_falls_back_with_no_gov_id_at_all():
    assert crud.effective_jurisdiction(None, "Some Unresolved Place") == (
        "Some Unresolved Place"
    )
    assert crud.effective_jurisdiction(None, None) is None
    assert crud.effective_jurisdiction("", "Some Unresolved Place") == (
        "Some Unresolved Place"
    )


# --- end-to-end: /m/{slug} must not drift from gov_id -------------------


def _ingest(payload: dict) -> dict:
    body = dict(payload)
    body["input_url_normalized"] = payload["source_url"]
    response = client.post("/internal/ingest", json=body, headers=_AUTH)
    assert response.status_code == 200, response.text
    return response.json()


async def _seed_stale_kc_override(external_id: str, source_url: str) -> str:
    """Ingests a page the way a real adapter would (jurisdiction=bare
    "Kansas City", which finalize_jurisdiction() cannot disambiguate --
    see this module's docstring), then patches gov_id directly onto the
    row without touching `jurisdiction` -- reproducing exactly the real,
    confirmed pre-fix state (a manual_override written before the
    override endpoint always wrote the full display_name()), the same
    "set it directly" approach
    tests/test_low_trust_pages.py::test_unverified_jurisdiction_confidence_is_caught
    already uses for a state finalize_jurisdiction() would not itself
    produce.
    """
    result = _ingest(
        {
            "platform": "granicus",
            "source_url": source_url,
            "external_id": external_id,
            "title": "Kansas City Council Regular Session",
            "date": "2026-08-01",
            "jurisdiction": "Kansas City",
            "video_url": "https://example.com/kc-video.m3u8",
            "video_format": "m3u8",
            "segments": [{"start": 0.0, "end": 1.0, "text": "Call to order"}],
            "agenda_items": [],
            "transcript_language": "en",
            "transcript_warnings": [],
        }
    )
    slug = result["slug"]
    async with async_session() as session:
        page = (
            await session.execute(select(MeetingPage).where(MeetingPage.slug == slug))
        ).scalar_one()
        # Forced back to bare regardless of what the real ingest pipeline
        # just did with it (kansascity.granicus.com has a real
        # tenant_overrides.csv rule to this same gov_id, so a fresh
        # ingest may already resolve this correctly going forward) --
        # this reproduces the exact stored shape of the two real,
        # currently-live pages the bug report found, not whatever a
        # brand-new ingest happens to produce today.
        page.gov_id = _KC_GOV_ID
        page.gov_type = "municipality"
        page.jurisdiction = "Kansas City"
        await session.commit()
    return slug


async def test_meeting_page_shows_the_registry_derived_jurisdiction_not_the_stale_string():
    slug = await _seed_stale_kc_override(
        "granicus:kc-override-drift-1",
        "https://kansascity.granicus.com/player/clip/jx-override-drift-1",
    )
    r = client.get(f"/m/{slug}")
    assert r.status_code == 200
    # The real bug: the raw stored string alone ("Kansas City") would
    # render with no state at all, and the "More {State} meetings" link
    # would be silently omitted because state_abbr_from_jurisdiction()
    # can't find a ", ST" suffix on it. Fixed: the page shows the same
    # gov_id-derived name its own /j/ hub already would.
    assert "Kansas City, MO" in r.text
    assert "More Missouri meetings" in r.text
    assert 'href="/state/missouri"' in r.text
    # hub_slug_for_page() was already gov_id-aware before this fix (WO-99)
    # -- confirms the hub link and the jurisdiction text now agree on the
    # same government, closing the drift between them.
    assert 'href="/j/kansas-city-mo"' in r.text


async def test_meeting_page_json_ld_uses_the_registry_derived_name():
    slug = await _seed_stale_kc_override(
        "granicus:kc-override-drift-2",
        "https://kansascity.granicus.com/player/clip/jx-override-drift-2",
    )
    r = client.get(f"/m/{slug}")
    assert r.status_code == 200
    assert '"name": "Kansas City, MO"' in r.text


def test_an_unknown_host_id_renders_no_placeholder_and_no_hub():
    """Gov-id audit, 2026-09-10. `rtr:unknown:<host>` is a real,
    distinguishable id -- "nothing was extracted on this host" -- with a
    registry row whose display form is "Unidentified government (host)".
    Rendering that on a meeting page linked "More Unidentified government
    (vimeo.com) meetings" to a /j/ hub `_hub_base_conditions()` never
    builds (a blank page stores an empty `jurisdiction`), a 404 on 289
    live pages. A blank page now behaves exactly like a page with no id:
    the stored string (empty) is the display, and there is no hub."""
    # Falsy either way -- an empty stored string passes through
    # format_jurisdiction_display() as "", None as None; the template
    # tests `page.jurisdiction` for truth, so both render nothing.
    assert not crud.effective_jurisdiction("rtr:unknown:vimeo.com", "")
    assert not crud.effective_jurisdiction("rtr:unknown:vimeo.com", None)
    assert not crud.hub_slug_for_page("rtr:unknown:vimeo.com", "")
    # A stored string, if one exists, still shows -- the id is what is
    # ignored, not the page's own text.
    assert crud.effective_jurisdiction("rtr:unknown:vimeo.com", "Somewhere") == (
        "Somewhere"
    )
