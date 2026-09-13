"""WO-346: tests for `app/platforms/queue_probe.py::has_owner()` -- the
"refuses to advance a line with no owner" guard `scripts/
feed_tier3_auto_transcription.py` now checks before every ingest, and for
the queue-advance behaviour that puts such a line back in the queue
instead of dropping it (see that script's own `main()`).

Why this checks against the REAL committed `tenant_overrides.csv` rather
than a monkeypatched one: `has_owner()` deliberately reuses `app/utils/
gov_registry/resolver.py`'s own `_matched_multi_gov_pin()`/
`_tenant_host()` -- the exact functions `archive/db/crud.py`'s
`_resolve_page_government()` calls at ingest time -- rather than
reimplementing the lookup, so this test is only meaningful against the
real, cached `registry.tenant_overrides()` table. The pinned URL used
here (Silver Bow County, MT) is a real row this same WO's own queue
ownership audit added, evidenced by `jurisdiction_coverage.csv`'s
`example_meeting_url` (see `scripts/wo346_ownership_audit.csv`).
"""

from app.platforms.queue_probe import has_owner


def test_owned_by_pin_on_a_multi_gov_host():
    owned, gov_id, reason = has_owner("https://www.youtube.com/watch?v=5OFSWnNQ6qA")
    assert owned is True
    assert gov_id == "us:county:30093"  # Silver Bow County, MT
    assert reason == ""


def test_no_owner_on_a_multi_gov_host_with_no_matching_pin():
    owned, gov_id, reason = has_owner("https://www.youtube.com/watch?v=ZZZZZZZZZZZ")
    assert owned is False
    assert gov_id is None
    assert "www.youtube.com" in reason
    assert "no tenant_overrides.csv pin" in reason


def test_owned_by_registry_on_a_single_tenant_host():
    """A CivicClerk portal subdomain is never in MULTI_GOV_HOSTS -- one
    government per tenant by construction, so no pin is needed, and there
    is no cheap gov_id to hand back without running the full ladder the
    way ingest itself does server-side."""
    owned, gov_id, reason = has_owner(
        "https://mandannd.portal.civicclerk.com/event/344/media"
    )
    assert owned is True
    assert gov_id is None
    assert reason == ""


def test_unparseable_host_has_no_owner():
    owned, gov_id, reason = has_owner("not-a-url")
    assert owned is False
    assert gov_id is None
    assert "unparseable host" in reason
