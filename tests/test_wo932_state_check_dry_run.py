"""WO-932: the read-only dry run that counts what a blocking Archive state
check would refuse (`scripts/wo932_state_check_dry_run.py`).

The rows are REAL pages copied from the 2026-09-21 inventory export
(`scripts/export_meeting_inventory.py`): page 1 Yountville CA; page 5642
Collierville TN (a minted id the registry has no committed row for); and the
Wellfleet, Weston and Castine pages, three of the 12 the full run would
refuse. Only the columns the script reads are filled in. One name is built by
hand and says so.
"""

import csv

import pytest

from scripts import wo932_state_check_dry_run as dry

BELTRAMI_MN = "us:place:2705014"


def _page(page_id, stored, gov_id, tier="registry", platform="Swagit"):
    return {
        "page_id": str(page_id),
        "stored_jurisdiction": stored,
        "gov_id": gov_id,
        "jurisdiction_confidence": tier,
        "page_platform": platform,
        "source_url": f"https://example.invalid/{page_id}",
    }


YOUNTVILLE = _page(1, "Yountville, CA", "us:place:0686930")
# Real: the stored name says Nebraska; the id is Wellfleet town, Massachusetts.
WELLFLEET = _page(
    10397, "Town of Wellfleet, NE", "us:cousub:2500174385", "pinned", "Cablecast"
)
WESTON = _page(10343, "Weston, WY", "us:cousub:2501777255", "pinned", "Castus")
CASTINE = _page(
    8270, "Town of Castine, OH", "us:cousub:2300911265", "registry", "YouTube"
)
# Real id, real page 5642: minted by the name ladder, no committed registry row.
COLLIERVILLE = _page(
    5642, "The Town of Collierville, TN", "rtr:us:tn:collierville-town", "unverified"
)
NO_GOV = _page(1, "Anywhere", "")
UNIDENTIFIED = _page(2, "Anywhere", "rtr:unknown:www.youtube.com", "blank", "YouTube")
# A sweep that forces `result.jurisdiction = unit_name` sends the registry
# row's own name: no state on it, so a state check has nothing to compare.
FORCED_NAME = _page(3, "Beltrami city", BELTRAMI_MN)


@pytest.mark.parametrize(
    "row, bucket",
    [
        (YOUNTVILLE, dry.AGREES),
        (WELLFLEET, dry.WOULD_REFUSE),
        (WESTON, dry.WOULD_REFUSE),
        (CASTINE, dry.WOULD_REFUSE),
        (COLLIERVILLE, dry.UNREADABLE),
        (NO_GOV, dry.NO_GOV),
        (UNIDENTIFIED, dry.NO_GOV),
        (FORCED_NAME, dry.NO_STATE),
    ],
)
def test_each_kind_of_page_lands_in_its_bucket(row, bucket):
    assert dry.classify_row(row)[0] == bucket


def test_a_refused_page_carries_what_a_person_needs_to_read_it():
    _bucket, detail = dry.classify_row(WELLFLEET)
    assert detail["gov_id"] == "us:cousub:2500174385"
    assert detail["stored_state"] == "NE"
    assert detail["registry_state"] == "MA"
    assert detail["confidence"] == "pinned"
    assert detail["platform"] == "Cablecast"


def test_a_two_state_city_agrees_with_either_of_its_states():
    """Lloydminster is one city on both sides of the AB/SK border; its
    registry row holds "AB/SK". The stored name below is built by hand (the
    real page's own string, "Lloydminster, AB/SK", carries no single code and
    lands in "no state")."""
    row = _page(4, "Lloydminster, SK", "rtr:ca:ab-sk:lloydminster")
    assert dry.classify_row(row)[0] == dry.AGREES
    row = _page(5, "Lloydminster, ON", "rtr:ca:ab-sk:lloydminster")
    assert dry.classify_row(row)[0] == dry.WOULD_REFUSE


def test_summary_counts_every_page_once_and_reports_the_tiers():
    rows = [YOUNTVILLE, WELLFLEET, WESTON, CASTINE, COLLIERVILLE, NO_GOV, FORCED_NAME]
    counts, refused, by_tier = dry.summarize(rows)
    assert sum(counts.values()) == len(rows)
    assert counts[dry.WOULD_REFUSE] == 3
    assert len(refused) == 3
    assert by_tier == {"pinned": 2, "registry": 1}


def test_report_uses_the_plain_labels_and_says_its_limits():
    rows = [YOUNTVILLE, WELLFLEET]
    counts, refused, by_tier = dry.summarize(rows)
    text = dry.render_report(len(rows), counts, refused, by_tier, limit=5)
    assert "Count of 2" in text
    for label in dry.BUCKETS:
        assert label in text
    assert "Town of Wellfleet, NE" in text
    assert "upper bound" in text


def test_report_says_so_when_nothing_would_be_refused():
    counts, refused, by_tier = dry.summarize([YOUNTVILLE])
    text = dry.render_report(1, counts, refused, by_tier, limit=5)
    assert "No page would be refused." in text


def test_main_reads_a_csv_and_writes_only_the_file_it_is_told_to(tmp_path, capsys):
    src = tmp_path / "inventory.csv"
    fields = list(YOUNTVILLE)
    with src.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows([YOUNTVILLE, WELLFLEET])
    out = tmp_path / "refused.csv"

    assert dry.main(["--inventory-csv", str(src), "--out-csv", str(out)]) == 0

    printed = capsys.readouterr().out
    assert "Pages a blocking state check would refuse" in printed
    written = list(csv.DictReader(out.open(newline="", encoding="utf-8")))
    assert [r["page_id"] for r in written] == ["10397"]
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "inventory.csv",
        "refused.csv",
    ]
