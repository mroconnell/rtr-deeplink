"""Three per-meeting pins (Ryan, 2026-10-11): one Boston School Committee clip on the city's
Granicus host and two Southampton, MA shows on Easthampton Media's Cablecast. Each is read back from
the committed CSV and must resolve to the id it records. Other meetings on those hosts are untouched."""

import csv
from pathlib import Path

import pytest

from app.utils.gov_registry.resolver import resolve_government

PATH = (
    Path(__file__).resolve().parent.parent
    / "app"
    / "utils"
    / "jurisdiction_data"
    / "tenant_overrides.csv"
)


def _rows():
    with open(PATH, newline="", encoding="utf-8") as fh:
        return [
            r
            for r in csv.DictReader(fh)
            if r["source"].endswith("pin_proposal_2026-10-11")
        ]


PINS = _rows()


def test_the_four_pin_rows_are_present():
    assert len(PINS) == 4


@pytest.mark.parametrize("row", PINS, ids=lambda r: r["match"])
def test_the_meeting_resolves_to_the_right_government(row):
    if row["tenant_host"] == "boston.granicus.com":
        # The match text is a substring of the address, so each Boston row
        # is tried on the address form it names.
        match = row["match"]
        path = (
            f"/MediaPlayer.php?{match}&view_id=1"
            if match.startswith("clip_id=")
            else f"/{match}?view_id=1"
        )
        got = resolve_government(None, tenant_host=row["tenant_host"], path=path)
    else:
        _, host, show = row["match"].split(":")
        got = resolve_government(
            None,
            tenant_host=host,
            path=f"/internetchannel/show/{show}",
            page_hints={"external_id": row["match"]},
        )
    assert got.gov_id == row["gov_id"]


def test_another_boston_clip_still_resolves_to_the_city():
    got = resolve_government(
        None, tenant_host="boston.granicus.com", path="/player/clip/10742"
    )
    assert got.gov_id == "us:place:2507000"
