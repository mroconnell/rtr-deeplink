"""Tests for scripts/pin_audit_core.py.

Registry facts are REAL (Sunnyside WA vs Sunnyside NL). The select_pins
cases use a SYNTHETIC hand-built AuditData: the hosts are invented, only the
gov_ids are real.
"""

import pytest

from scripts import pin_audit_core as core

WA = "us:place:5368750"
NL = "ca:csd:1001277"


def test_sunnyside_twin_across_countries():
    assert NL in core.twins(WA)
    assert WA in core.twins(NL)
    assert WA not in core.twins(WA)


def test_gov_info_state_and_minted():
    info = core.gov_info(WA)
    assert info.state == "WA" and info.country == "us" and info.base == "sunnyside"
    assert core.gov_info(NL).state == "NL"
    assert core.gov_info("us:place:0000000") is None
    minted = core.gov_info("rtr:us:wa:made-up-place")
    assert minted.state == "WA" and minted.name == "made up place"
    assert minted.kind == "rtr:us"


@pytest.mark.parametrize(
    "raw,want",
    [
        ("City of Sunnyside", "sunnyside"),
        ("Sunnyside (town)", "sunnyside"),
        ("Saint Louis County", "st louis"),
        ("St. Paul", "st paul"),
        ("Mount Vernon", "mt vernon"),
        ("Mt. Vernon city", "mt vernon"),
        ("Unified School District", "unified school district"),
        ("Town of  Foo-Bar", "foo bar"),
    ],
)
def test_base_name(raw, want):
    assert core.base_name(raw) == want


def test_states_adjacent():
    assert core.states_adjacent("WA", "BC")
    assert core.states_adjacent("BC", "WA")
    assert core.states_adjacent("WA", "WA")
    assert core.states_adjacent("wa", "or")
    assert not core.states_adjacent("WA", "FL")
    assert not core.states_adjacent("NL", "WA")
    assert core.states_adjacent("ME", "NB")
    assert not core.states_adjacent("PE", "NS")  # bridge only, not a land border


def _syn(host, match, source, gov=WA, store=core.STORE_OVERRIDE):
    return core.Pin(store, host, match, gov, source=source, ref=f"{host}:{match}")


def _synthetic():
    pins = []
    for i in range(60):
        pins.append(_syn(f"a{i}.example.org", "", "step0_dns_full"))
        pins.append(_syn(f"b{i}.example.org", "", "landing_page"))
        pins.append(_syn(f"c{i}.example.org", "", "ryan_stated"))
    pins.append(_syn("d.example.org", "", "landing_page", gov="us:place:0000000"))
    pins.append(_syn("youtube.com", "", "landing_page"))  # whole-host on shared host
    pins.append(_syn("e.example.org", "", "", store=core.STORE_ARCHIVE))
    data = core.AuditData(pins=pins)
    core.build_indexes(data)
    return data


def test_select_pins_pilot_deterministic_and_shaped():
    data = _synthetic()
    a = core.select_pins(data, "pilot", 7)
    b = core.select_pins(data, "pilot", 7)
    assert a == b
    assert a != core.select_pins(data, "pilot", 8)
    assert len(a) == 100
    assert sum("step0_dns_full" in p.source for p in a) == 40
    assert sum("ryan_stated" in p.source for p in a) == 30
    assert all(p.host != "youtube.com" and p.store == core.STORE_OVERRIDE for p in a)


def test_select_pins_all_and_ambiguous():
    data = _synthetic()
    everything = core.select_pins(data, "all")
    assert all(p.store != core.STORE_ARCHIVE for p in everything)
    assert len(everything) == 182
    amb = core.select_pins(data, "ambiguous")
    assert all(p.gov_id == WA for p in amb) and len(amb) == 181
    with pytest.raises(ValueError):
        core.select_pins(data, "bogus")


def test_host_indexes_cover_www():
    data = core.AuditData(
        pins=[core.Pin(core.STORE_OVERRIDE, "www.x.org", "", WA)],
        pages=[
            core.Page(
                "1", WA, "t", "", "https://www.x.org/a", "", "www.x.org", "", "@Chan"
            )
        ],
    )
    core.build_indexes(data)
    assert data.pins_by_host["www.x.org"] and data.pins_by_host["x.org"]
    assert data.pages_by_host["x.org"] and data.pages_by_channel["@chan"]


def test_load_all_real_overrides(tmp_path):
    missing = tmp_path / "nope"
    data = core.load_all(
        {k: missing for k in ("queue_deferred", "research", "discovery", "inventory")}
    )
    assert any(m.startswith("research") for m in data.missing)
    hits = [
        p
        for p in data.pins_by_host.get("sunnyside.primegov.com", [])
        if p.store == core.STORE_OVERRIDE
    ]
    assert hits and hits[0].gov_id == WA
    assert hits[0].ref.startswith("tenant_overrides.csv:")
