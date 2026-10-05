"""A pin naming one meeting by its own external id beats the page's name
(rung 1a, pin-failure trace 2026-10-05).

Archive page 12060, "6-29-26 Pilot Mountain Board Meeting", has a per-show
pin to Pilot Mountain NC. The station's site names "Town of Elkin, NC" for
every show, so rung 4's national table matched Elkin first and the
`fallback` pin, which waited for rung 5, never got a turn. The WO-1180 test
missed this because it resolves each per-show pin with no name at all.

Every case here passes the name the real page carried.
"""

import csv
from pathlib import Path

import pytest

import app.utils.gov_registry.resolver as resolver
from app.utils.gov_registry import registry
from app.utils.gov_registry.resolver import TIER_PINNED, resolve_government


def _cablecast(name, host, show):
    return resolve_government(
        name,
        tenant_host=host,
        path=f"/internetchannel/show/{show}",
        page_hints={"platform": "cablecast", "external_id": f"cablecast:{host}:{show}"},
    )


@pytest.mark.parametrize(
    "page_id, name, host, show, gov_id",
    [
        # 12060: Pilot Mountain's board, filed under Elkin on 2026-10-03.
        (
            12060,
            "Town of Elkin, NC",
            "reflect-surryco-nc.cablecast.tv",
            1954,
            "us:place:3751820",
        ),
        # 12059: Surry County's board on the same station.
        (
            12059,
            "Town of Elkin, NC",
            "reflect-surryco-nc.cablecast.tv",
            2008,
            "us:county:37171",
        ),
        # 12151: Elkin City Schools, a school district, not the town.
        (
            12151,
            "Town of Elkin, NC",
            "reflect-origin-888.cablecast.tv",
            2000,
            "us:sd:3701380",
        ),
        # 12086: Minnehaha County's commission on Sioux Falls' CityLink.
        (
            12086,
            "City of Sioux Falls, SD",
            "reflect-citylink-siouxfalls.cablecast.tv",
            3692,
            "us:county:46099",
        ),
    ],
)
def test_per_show_pin_beats_the_station_name(page_id, name, host, show, gov_id):
    match = _cablecast(name, host, show)
    assert match.gov_id == gov_id, page_id
    assert match.tier == TIER_PINNED
    assert "rung 1a" in match.evidence


def test_unpinned_show_on_the_same_station_keeps_the_name():
    # No pin for this show: the station's name still decides, as before.
    match = _cablecast("Town of Elkin, NC", "reflect-surryco-nc.cablecast.tv", 999999)
    assert match.gov_id == "us:place:3720620"
    assert "rung 1a" not in match.evidence


def test_a_longer_show_id_does_not_borrow_the_pin():
    # Show 19540 must not match the pin for show 1954.
    got = resolver._exact_external_id_pin(
        "reflect-surryco-nc.cablecast.tv",
        {"external_id": "cablecast:reflect-surryco-nc.cablecast.tv:19540"},
    )
    assert got is None


def test_no_external_id_means_no_rung_1a():
    assert (
        resolver._exact_external_id_pin("reflect-surryco-nc.cablecast.tv", None) is None
    )
    assert (
        resolver._exact_external_id_pin("reflect-surryco-nc.cablecast.tv", {}) is None
    )


def test_shared_hosts_are_left_to_rung_1b(monkeypatch):
    # YouTube, Vimeo and the other MULTI_GOV_HOSTS keep their own order.
    assert registry.is_multi_gov_host("www.youtube.com")

    def boom(*_a, **_k):
        raise AssertionError("rung 1a must not run on a shared host")

    monkeypatch.setattr(resolver, "_exact_external_id_pin", boom)
    resolve_government(
        "Osage County",
        tenant_host="www.youtube.com",
        path="/watch?v=kGepCh07dg4",
        page_hints={"platform": "youtube", "external_id": "youtube:kGepCh07dg4"},
    )


def _external_id_pins():
    path = (
        Path(__file__).resolve().parent.parent
        / "app"
        / "utils"
        / "jurisdiction_data"
        / "tenant_overrides.csv"
    )
    with open(path, newline="", encoding="utf-8") as fh:
        return [
            r
            for r in csv.DictReader(fh)
            if r["match"].startswith("cablecast:")
            and not registry.is_multi_gov_host(r["tenant_host"])
        ]


PINS = _external_id_pins()


def test_there_are_per_show_pins_to_check():
    assert len(PINS) > 400


@pytest.mark.parametrize("row", PINS, ids=lambda r: r["match"])
def test_every_per_show_pin_beats_another_towns_name(row):
    # A station's name for some other town must never outrank the pin.
    _, host, show = row["match"].split(":")
    match = _cablecast("Springfield, IL", host, show)
    assert match.gov_id == row["gov_id"]
