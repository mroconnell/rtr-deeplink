"""WO-1024: app/platforms/meeting_finder/identity.py -- pin mode and
audit mode both derive "what the meeting itself says" by switching off
the account's own tenant_overrides.csv pin (see identity.py's own
docstring for why this applies to both modes, not just audit).
"""

from app.platforms.meeting_finder.identity import (
    check_identity,
    tenant_pin_switched_off,
)
from app.platforms.meeting_finder.models import FinderInput
from app.platforms.models import ResolvedMeeting
from app.utils.gov_registry import resolver as gov_resolver
from app.utils.gov_registry.resolver import _override_rows_for_host


def test_pin_mode_agrees_when_page_content_matches():
    meeting = ResolvedMeeting(
        platform="civicclerk",
        source_url="https://fresnoca.portal.civicclerk.com/event/1/media",
        jurisdiction="Fresno, CA",
    )
    finder_input = FinderInput(
        url=meeting.source_url, gov_id="us:place:0627000", mode="pin", entry="resolve"
    )
    result = check_identity(meeting, finder_input)
    assert result.mode == "pin"
    assert result.expected_gov_id == "us:place:0627000"
    assert result.verdict in ("agrees", "disagrees", "silent")
    # Fresno CA is unambiguous (CLAUDE.md's own synthetic-test note cites
    # it as confirmed-unambiguous) -- the page's own text should resolve
    # to Fresno regardless of the pin.
    assert result.resolved_gov_id == "us:place:0627000"
    assert result.verdict == "agrees"


def test_pin_mode_disagrees_when_page_names_a_different_real_government():
    meeting = ResolvedMeeting(
        platform="civicclerk",
        source_url="https://fresnoca.portal.civicclerk.com/event/1/media",
        jurisdiction="Fresno, CA",
    )
    finder_input = FinderInput(
        url=meeting.source_url,
        gov_id="us:place:9999999",  # deliberately wrong
        mode="pin",
        entry="resolve",
    )
    result = check_identity(meeting, finder_input)
    assert result.verdict == "disagrees"
    assert result.points_to == "us:place:0627000"


def test_not_checked_when_no_gov_id_given():
    meeting = ResolvedMeeting(
        platform="civicclerk",
        source_url="https://fresnoca.portal.civicclerk.com/event/1/media",
        jurisdiction="Fresno, CA",
    )
    finder_input = FinderInput(
        url=meeting.source_url, gov_id=None, mode="pin", entry="resolve"
    )
    result = check_identity(meeting, finder_input)
    assert result.verdict == "not-checked"


def test_not_checked_when_nothing_was_resolved():
    finder_input = FinderInput(
        url="https://example.gov/nothing",
        gov_id="us:place:0627000",
        mode="pin",
        entry="resolve",
    )
    result = check_identity(None, finder_input)
    assert result.verdict == "not-checked"
    assert result.resolved_gov_id is None


def test_audit_mode_switches_off_a_real_tenant_overrides_pin():
    """Real pinned host from tenant_overrides.csv (wildcard_http_sweep_2,
    a name that exists in more than one jurisdiction, per the brief):
    `lincoln.escribemeetings.com` is pinned to `ca:csd:3526057` (Lincoln,
    Ontario) -- "Lincoln" is also a real, common US place name. With no
    real jurisdiction text at all (the honest worst case -- an eScribe
    page whose own content this test doesn't fabricate), the pin would
    normally answer `ca:csd:3526057`; with it switched off, the resolver
    has nothing to go on and must land on a blank/silent tier instead of
    quietly echoing the pin back."""
    host = "lincoln.escribemeetings.com"
    before = _override_rows_for_host(host)
    assert before, "expected a real tenant_overrides.csv row for this host"
    assert before[0].gov_id == "ca:csd:3526057"

    meeting = ResolvedMeeting(
        platform="escribe",
        source_url=f"https://{host}/Meeting.aspx?Id=1",
        jurisdiction=None,
    )
    finder_input = FinderInput(
        url=meeting.source_url, gov_id="ca:csd:3526057", mode="audit", entry="resolve"
    )
    result = check_identity(meeting, finder_input)
    assert result.mode == "audit"
    assert result.verdict == "silent"
    assert result.resolved_gov_id is None

    # The pin itself is untouched afterward -- a DIFFERENT caller (or the
    # same one, right after) still sees it normally, proving the
    # switch-off was scoped, not a global mutation.
    after = _override_rows_for_host(host)
    assert after == before
    assert gov_resolver._override_rows_for_host is _override_rows_for_host


def test_tenant_pin_switched_off_only_affects_the_named_host():
    # Called through the MODULE attribute, not a locally-imported name --
    # `tenant_pin_switched_off()` patches `gov_resolver._override_rows_
    # for_host` on the module object, and only a call that looks the
    # function up via the module (the way resolver.py's own
    # `_match_override()` does, by bare name within the same module,
    # which Python resolves through the module's globals at call time)
    # observes the patch. A `from ... import _override_rows_for_host`
    # binds a separate reference in the importer's namespace that the
    # patch never touches -- confirmed by this test initially calling it
    # that way and seeing the real, unpatched row.
    other_host = "adamscounty.primegov.com"
    before = gov_resolver._override_rows_for_host(other_host)
    assert before, "expected a real tenant_overrides.csv row for this host too"
    with tenant_pin_switched_off("lincoln.escribemeetings.com"):
        # A different host's pin is unaffected while the scoped patch is
        # active for lincoln.escribemeetings.com.
        assert gov_resolver._override_rows_for_host(other_host) == before
        assert gov_resolver._override_rows_for_host("lincoln.escribemeetings.com") == []
    # Restored after the context manager exits.
    assert gov_resolver._override_rows_for_host("lincoln.escribemeetings.com")
