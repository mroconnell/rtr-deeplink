"""WO-1185: tests for scripts/pin_audit.py's report helpers.

SYNTHETIC: the AuditData is hand-built, but the governments are real
registry rows (Sunnyside city WA us:place:5368750 and Sunnyside NL
ca:csd:1001277, the 2026-10-05 case that started the audit).
"""

from scripts import pin_audit as cli
from scripts import pin_audit_core as core
from scripts.pin_audit_core import AuditData, Flag, Pin

WA = "us:place:5368750"
NL = "ca:csd:1001277"


def _data(pins):
    data = AuditData(pins=list(pins))
    core.build_indexes(data)
    return data


def test_one_row_per_address_even_when_flagged_from_both_sides():
    override = Pin(core.STORE_OVERRIDE, "sunnyside.primegov.com", "", NL)
    ledger = Pin(core.STORE_DISCOVERY, "sunnyside.primegov.com", "", WA)
    research = Pin(core.STORE_RESEARCH, "www.sunnyside.primegov.com", "", WA)
    flags = [
        Flag("R4", "high", override, other_gov_id=WA, detail="a"),
        Flag("R4", "high", ledger, other_gov_id=NL, detail="b"),
    ]
    rows = cli.disagreements(_data([override, ledger, research]), flags)
    assert len(rows) == 1
    row = rows[0]
    assert row["host"] == "sunnyside.primegov.com"
    assert row["worst"] == "high"
    assert row["governments_claimed"] == 2
    # Every stored claim is shown, www-insensitive, and no winner is named.
    assert f"({WA}): 1 discovery_tenant, 1 research_row" in row["claims"]
    assert f"({NL}): 1 tenant_overrides" in row["claims"]


def test_low_and_note_flags_make_no_row_and_ryan_side_is_named():
    pin = Pin(core.STORE_OVERRIDE, "x.example.com", "", WA, source="ryan_stated")
    other = Pin(core.STORE_RESEARCH, "x.example.com", "", NL)
    data = _data([pin, other])
    assert cli.disagreements(data, [Flag("R6", "note", pin)]) == []
    rows = cli.disagreements(data, [Flag("R4", "medium", other, other_gov_id=WA)])
    assert rows[0]["ryan_stated_gov"] == WA
