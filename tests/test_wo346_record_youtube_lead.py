"""WO-346: regression test for the `record_youtube_lead()` bug
BACKLOG.md's "`record_youtube_lead()` hardcodes `source_wo="WO-320"`
regardless of the real caller" entry describes (history: WO-345, which
found this live 2026-09-13 -- it called `scripts.wo320_targeted`'s
helper for a real Cochise County, AZ lead and the written row said
`WO-320`, hand-corrected at the time; the helper itself was still
broken).

Two real, independent copies of `record_youtube_lead()` carried this
same bug class, found while auditing the tier-3 queue for missing
owners: `scripts/wo320_targeted.py`'s (the one WO-345 actually called,
now fixed by adding a required `source_wo` parameter with no default)
and `scripts/wo331_targeted.py`'s own copy (a leftover, never-updated
`"WO-325"` literal from copying `wo325_targeted.py` -- fixed by
correcting the literal, since that copy is self-contained and not
imported by anything else).
"""

import csv

import pytest

import scripts.wo320_targeted as wo320_targeted
import scripts.wo331_targeted as wo331_targeted


@pytest.fixture
def wo320_leads_csv(tmp_path, monkeypatch):
    csv_path = tmp_path / "youtube_channel_leads.csv"
    monkeypatch.setattr(wo320_targeted, "YOUTUBE_LEADS_CSV", csv_path)
    monkeypatch.setattr(
        wo320_targeted, "TENANT_OVERRIDES_CSV", tmp_path / "tenant_overrides.csv"
    )
    # Reset the module's own caches -- both are lazily built once per
    # process and would otherwise leak state between tests.
    monkeypatch.setattr(wo320_targeted, "_youtube_leads_seen", None)
    monkeypatch.setattr(wo320_targeted, "_youtube_pinned_handles", None)
    return csv_path


def _read_rows(csv_path):
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_record_youtube_lead_requires_source_wo_with_no_default():
    """No default -- every call site is forced to pass its own real WO
    number, the fix BACKLOG.md's entry calls for."""
    import inspect

    sig = inspect.signature(wo320_targeted.record_youtube_lead)
    assert "source_wo" in sig.parameters
    assert sig.parameters["source_wo"].default is inspect.Parameter.empty


def test_record_youtube_lead_writes_the_callers_own_wo_number(wo320_leads_csv):
    wo320_targeted.record_youtube_lead(
        "example.gov",
        "us:county:04003",
        "Cochise County",
        "AZ",
        "https://www.youtube.com/watch?v=b1JaaRs7Jtc",
        "WO-345",
    )
    rows = _read_rows(wo320_leads_csv)
    assert len(rows) == 1
    assert rows[0]["source_wo"] == "WO-345"
    assert rows[0]["source_wo"] != "WO-320"


def test_record_youtube_lead_a_different_caller_gets_its_own_label(
    wo320_leads_csv,
):
    """Two different callers, two different labels -- the exact thing a
    hardcoded literal can never produce."""
    wo320_targeted.record_youtube_lead(
        "a.gov", "us:place:0000001", "A", "ZZ", "https://youtu.be/aaaaaaaaaaa", "WO-320"
    )
    wo320_targeted.record_youtube_lead(
        "b.gov", "us:place:0000002", "B", "ZZ", "https://youtu.be/bbbbbbbbbbb", "WO-322"
    )
    rows = {r["channel_url"]: r["source_wo"] for r in _read_rows(wo320_leads_csv)}
    assert rows["https://youtu.be/aaaaaaaaaaa"] == "WO-320"
    assert rows["https://youtu.be/bbbbbbbbbbb"] == "WO-322"


@pytest.fixture
def wo331_leads_csv(tmp_path, monkeypatch):
    csv_path = tmp_path / "youtube_channel_leads.csv"
    monkeypatch.setattr(wo331_targeted, "YOUTUBE_LEADS_CSV", csv_path)
    monkeypatch.setattr(
        wo331_targeted,
        "YOUTUBE_LEADS_LOCK",
        tmp_path / "youtube_channel_leads.csv.lock",
    )
    monkeypatch.setattr(
        wo331_targeted, "TENANT_OVERRIDES_CSV", tmp_path / "tenant_overrides.csv"
    )
    monkeypatch.setattr(wo331_targeted, "_youtube_dedupe_keys", None)
    monkeypatch.setattr(wo331_targeted, "_youtube_pinned_keys", None)
    return csv_path


def test_wo331s_own_copy_no_longer_writes_wo325(wo331_leads_csv):
    """Real bug, found live while auditing the tier-3 queue for WO-346:
    `wo331_targeted.py`'s own `record_youtube_lead()` -- a self-contained
    copy of `wo325_targeted.py`'s, not the shared `wo320_targeted.py`
    helper -- still hardcoded the literal `"WO-325"`, unrelated to this
    script's own WO number."""
    wrote = wo331_targeted.record_youtube_lead(
        "https://www.youtube.com/watch?v=cccccccccc1",
        "us:place:0000003",
        "C",
        "ZZ",
        note="a real note",
    )
    assert wrote is True
    rows = _read_rows(wo331_leads_csv)
    assert len(rows) == 1
    assert rows[0]["source_wo"] == "WO-331"
    assert rows[0]["source_wo"] != "WO-325"
    assert "WO-325" not in rows[0]["note"]
