"""WO-1180: 147 per-video (TelVue) and per-show (Cablecast) pins.

These stations carry several governments, so each meeting is pinned on its
own, not the whole host. Ryan accepted each proposal on 2026-10-03; the
proposal came from the meeting's title (evidence in each row of
`tenant_overrides.csv`, which starts "WO-1180:"). Every row here is read
back from the committed CSV and must resolve to the id it records.
"""

import pytest

from app.utils.gov_registry.resolver import resolve_government


def _rows():
    import csv
    from pathlib import Path

    path = (
        Path(__file__).resolve().parent.parent
        / "app"
        / "utils"
        / "jurisdiction_data"
        / "tenant_overrides.csv"
    )
    with open(path, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if "WO-1180:" in r["evidence"]]


PINS = _rows()


def test_all_147_pins_are_present():
    assert len(PINS) == 147


@pytest.mark.parametrize("row", PINS, ids=lambda r: r["match"])
def test_the_meeting_resolves_to_the_right_government(row):
    if row["match"].startswith("player/"):
        got = resolve_government(
            None, tenant_host=row["tenant_host"], path="/" + row["match"]
        )
    else:
        _, host, show = row["match"].split(":")
        got = resolve_government(
            None,
            tenant_host=host,
            path=f"/internetchannel/show/{show}",
            page_hints={"external_id": row["match"]},
        )
    assert got.gov_id == row["gov_id"]
