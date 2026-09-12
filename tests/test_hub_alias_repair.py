"""Tests for WO-293: the alias-chain repair -- `archive/utils/hub_
aliases.collapse_chains()`/`write_retirements()`, and the retirement hook
`scripts/backfill_gov_id.py --apply` now calls.

The problem this fixes, confirmed live 2026-09-12: `hub_slug_aliases.csv`
rows are one hop (`old_slug -> new_slug`), but nothing stopped a SECOND
retirement from orphaning that hop -- `lake-havasu-az` pointed at
`city-of-lake-havasu-az` (written when "City of Lake Havasu, AZ" was
first minted, before its registry row existed), and when a later
`backfill_gov_id.py --apply` run re-keyed that minted government onto
the real Census place `us:place:0439370` (WO-251's name-repair fix), no
alias was written for THAT hop -- so `/j/lake-havasu-az` 301'd to a 404.
42 targets were broken this way; see `BACKLOG_DONE.md`'s WO-293 entry for
the full repair and `docs/investigations/hub_architecture_audit.md` §4
for the freeze design this builds on.

`monkeypatch.setattr(hub_aliases, "ALIAS_FILE", ...)` is what keeps every
test here off the real committed file -- `read_rows()`/`write_rows()`/
`write_retirements()` all resolve `ALIAS_FILE` at call time (not as a
bound-at-import default) specifically so this works.
"""

import csv
import sys

from sqlalchemy import select

from archive.db import crud
from archive.db.engine import async_session
from archive.db.models import MeetingPage
from archive.utils import hub_aliases
from scripts import backfill_gov_id


def _write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=hub_aliases.HEADER, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _row(old_slug, gov_id, new_slug, evidence="test"):
    return {
        "old_slug": old_slug,
        "gov_id": gov_id,
        "new_slug": new_slug,
        "evidence": evidence,
    }


# --- collapse_chains() -------------------------------------------------


def test_collapse_chains_rewrites_a_two_hop_chain_to_the_final_target():
    """The real Lake Havasu shape, reproduced from the actual pre-repair
    row content: an alias pointing at a slug that was ITSELF later
    retired, with no second alias ever written."""
    rows = [
        _row(
            "lake-havasu-az",
            "rtr:us:az:lake-havasu",
            "city-of-lake-havasu-az",
            "'City of Lake Havasu, AZ' now resolves to rtr:us:az:lake-havasu "
            "(City of Lake Havasu, AZ)",
        ),
        _row(
            "city-of-lake-havasu-az",
            "us:place:0439370",
            "lake-havasu-city-az",
            "WO-293: second retirement, now resolves to us:place:0439370 "
            "(Lake Havasu City, AZ)",
        ),
    ]
    collapsed = hub_aliases.collapse_chains(rows)
    by_old = {r["old_slug"]: r for r in collapsed}
    assert by_old["lake-havasu-az"]["new_slug"] == "lake-havasu-city-az"
    # The second row, already terminal, is untouched.
    assert by_old["city-of-lake-havasu-az"]["new_slug"] == "lake-havasu-city-az"


def test_collapse_chains_handles_a_three_hop_chain():
    rows = [
        _row("a", "gov:a", "b"),
        _row("b", "gov:b", "c"),
        _row("c", "gov:c", "d"),
    ]
    collapsed = hub_aliases.collapse_chains(rows)
    by_old = {r["old_slug"]: r for r in collapsed}
    assert by_old["a"]["new_slug"] == "d"
    assert by_old["b"]["new_slug"] == "d"
    assert by_old["c"]["new_slug"] == "d"


def test_collapse_chains_leaves_a_genuine_cycle_unchanged():
    """The real Caledonia Township/Village, MI shape: two rows retiring
    into each other on consecutive days (2026-09-10, then WO-231's
    2026-09-11 correction). Neither direction can be resolved from the
    file alone -- which slug is actually live is a fact about the site,
    not the CSV -- so both are left exactly as they were."""
    rows = [
        _row("caledonia-township-mi", "us:place:x", "caledonia-village-mi"),
        _row("caledonia-village-mi", "us:cousub:y", "caledonia-township-mi"),
    ]
    collapsed = hub_aliases.collapse_chains(rows)
    by_old = {r["old_slug"]: r for r in collapsed}
    assert by_old["caledonia-township-mi"]["new_slug"] == "caledonia-village-mi"
    assert by_old["caledonia-village-mi"]["new_slug"] == "caledonia-township-mi"


def test_collapse_chains_leaves_a_self_looping_walk_unchanged():
    """A row whose OWN chain loops back to its own old_slug (not a
    two-row cycle, just this row pointing into a loop) is left alone for
    the same reason -- the loader's self-reference guard is what actually
    retires a row, once the direct lookup for its `old_slug` stops
    succeeding."""
    rows = [
        _row("a", "gov:a", "b"),
        _row("b", "gov:b", "a"),
    ]
    collapsed = hub_aliases.collapse_chains(rows)
    by_old = {r["old_slug"]: r for r in collapsed}
    assert by_old["a"]["new_slug"] == "b"
    assert by_old["b"]["new_slug"] == "a"


def test_collapse_chains_does_not_touch_an_unrelated_terminal_row():
    rows = [
        _row("x", "gov:x", "y"),
        _row("only-row", "gov:z", "already-terminal"),
    ]
    collapsed = hub_aliases.collapse_chains(rows)
    by_old = {r["old_slug"]: r for r in collapsed}
    assert by_old["x"]["new_slug"] == "y"
    assert by_old["only-row"]["new_slug"] == "already-terminal"


# --- write_rows(): byte-preserving, order-preserving --------------------


def test_write_rows_preserves_untouched_lines_byte_for_byte(tmp_path, monkeypatch):
    alias_file = tmp_path / "hub_slug_aliases.csv"
    # A stray CRLF on one untouched row, like 16 real rows in the
    # committed file had (found while building this).
    alias_file.write_bytes(
        b"old_slug,gov_id,new_slug,evidence\r\n"
        b'aaa,gov:a,aaa-live,"first"\n'
        b'bbb,gov:b,bbb-live,"second"\n'
    )
    monkeypatch.setattr(hub_aliases, "ALIAS_FILE", alias_file)
    hub_aliases.hub_slug_aliases.cache_clear()

    rows = hub_aliases.read_rows()
    rows[1]["new_slug"] = "bbb-live-v2"  # only touch the second row
    hub_aliases.write_rows(rows)

    raw = alias_file.read_bytes()
    lines = raw.split(b"\n")
    assert lines[0] == b"old_slug,gov_id,new_slug,evidence\r"  # untouched
    assert lines[1] == b'aaa,gov:a,aaa-live,"first"'  # untouched
    assert lines[2] == b"bbb,gov:b,bbb-live-v2,second"  # rewritten


def test_write_rows_never_resorts_the_file(tmp_path, monkeypatch):
    alias_file = tmp_path / "hub_slug_aliases.csv"
    _write_csv(
        alias_file,
        [_row("zzz", "gov:z", "zzz-live"), _row("aaa", "gov:a", "aaa-live")],
    )
    monkeypatch.setattr(hub_aliases, "ALIAS_FILE", alias_file)
    hub_aliases.hub_slug_aliases.cache_clear()

    rows = hub_aliases.read_rows()
    hub_aliases.write_rows(rows)  # no changes at all
    after = hub_aliases.read_rows()
    assert [r["old_slug"] for r in after] == ["zzz", "aaa"]  # order kept


# --- write_retirements() -------------------------------------------------


def test_write_retirements_appends_a_new_row_and_collapses_the_file(
    tmp_path, monkeypatch
):
    """The real Lake Havasu chain, end to end through the public writer:
    the file already carries the FIRST hop (written when the minted
    government was created); `write_retirements()` is given the SECOND
    hop (what `scripts/backfill_gov_id.py --apply` discovers), and the
    result must be a single, direct hop with no alias left resolving to
    another alias."""
    alias_file = tmp_path / "hub_slug_aliases.csv"
    _write_csv(
        alias_file,
        [
            _row(
                "lake-havasu-az",
                "rtr:us:az:lake-havasu",
                "city-of-lake-havasu-az",
                "'City of Lake Havasu, AZ' now resolves to "
                "rtr:us:az:lake-havasu (City of Lake Havasu, AZ)",
            )
        ],
    )
    monkeypatch.setattr(hub_aliases, "ALIAS_FILE", alias_file)
    hub_aliases.hub_slug_aliases.cache_clear()

    changed = hub_aliases.write_retirements(
        [
            (
                "city-of-lake-havasu-az",
                "us:place:0439370",
                "lake-havasu-city-az",
                "WO-293 test: second retirement",
            )
        ]
    )
    assert changed == 1

    hub_aliases.hub_slug_aliases.cache_clear()
    assert hub_aliases.redirect_target("lake-havasu-az") == "lake-havasu-city-az"
    assert hub_aliases.redirect_target("city-of-lake-havasu-az") == (
        "lake-havasu-city-az"
    )
    # No alias resolves to another alias.
    for row in hub_aliases.read_rows():
        assert hub_aliases.redirect_target(row["new_slug"]) is None


def test_write_retirements_skips_a_self_referential_entry(tmp_path, monkeypatch):
    alias_file = tmp_path / "hub_slug_aliases.csv"
    _write_csv(alias_file, [])
    monkeypatch.setattr(hub_aliases, "ALIAS_FILE", alias_file)
    hub_aliases.hub_slug_aliases.cache_clear()

    changed = hub_aliases.write_retirements([("same", "gov:x", "same", "no-op")])
    assert changed == 0
    assert hub_aliases.read_rows() == []


def test_write_retirements_updates_an_existing_row_rather_than_duplicating(
    tmp_path, monkeypatch
):
    alias_file = tmp_path / "hub_slug_aliases.csv"
    _write_csv(alias_file, [_row("old", "gov:a", "stale-target")])
    monkeypatch.setattr(hub_aliases, "ALIAS_FILE", alias_file)
    hub_aliases.hub_slug_aliases.cache_clear()

    changed = hub_aliases.write_retirements(
        [("old", "gov:b", "fresh-target", "corrected")]
    )
    assert changed == 1
    rows = hub_aliases.read_rows()
    assert len(rows) == 1
    assert rows[0]["new_slug"] == "fresh-target"
    assert rows[0]["gov_id"] == "gov:b"


def test_write_retirements_with_no_entries_still_collapses_existing_chains(
    tmp_path, monkeypatch
):
    """Safe to call with an empty batch -- this is how the one-time
    WO-293 repair also fixed chains that predate `write_retirements()`
    ever being called with real entries."""
    alias_file = tmp_path / "hub_slug_aliases.csv"
    _write_csv(
        alias_file,
        [_row("a", "gov:a", "b"), _row("b", "gov:b", "c")],
    )
    monkeypatch.setattr(hub_aliases, "ALIAS_FILE", alias_file)
    hub_aliases.hub_slug_aliases.cache_clear()

    hub_aliases.write_retirements([])
    hub_aliases.hub_slug_aliases.cache_clear()
    assert hub_aliases.redirect_target("a") == "c"


# --- the real committed file ---------------------------------------------


def test_committed_file_has_no_alias_resolving_to_another_alias():
    """The invariant WO-293's repair exists to establish: following one
    redirect never lands on another live redirect. Uses the real
    `redirect_target()` (which already excludes self-referential rows,
    the Caledonia Township/Village, MI resolution) rather than raw CSV
    inspection, since a self-referential row is correctly inert, not a
    violation."""
    hub_aliases.hub_slug_aliases.cache_clear()
    violations = []
    for old_slug, new_slug in hub_aliases.hub_slug_aliases().items():
        further = hub_aliases.redirect_target(new_slug)
        if further is not None:
            violations.append((old_slug, new_slug, further))
    assert violations == []


# --- the ongoing writer: scripts/backfill_gov_id.py --apply -------------


async def test_backfill_gov_id_apply_writes_an_alias_when_it_retires_a_slug(
    tmp_path, monkeypatch
):
    """End to end, real DB: an un-keyed page (`gov_id` blank, the
    pre-freeze raw-text fallback hub `rockaway-nj`) gets a real
    government backfilled onto it. `rockaway-nj` genuinely stops
    belonging to anybody the moment this page is re-keyed -- WO-293's
    hook must write the alias in the SAME `--apply` run, matching the
    real 2026-09-10 precedent (`BACKLOG_DONE.md`: "11 hub slugs retired;
    alias rows added so the old links redirect" -- done by hand back
    then, automatic now).

    Uses a real Census place (Rockaway, NJ / `us:place:3464050`) rather
    than an invented one, and a real, already-confirmed fact about it
    (`tests/test_hub_aliases.py`'s own committed-file test covers the
    SAME government's raw-text slug diverging from its registry slug --
    `rockaway-nj` vs `rockaway-borough-nj` -- this is the live mechanism
    that produces that divergence, not a fabricated shape)."""
    alias_file = tmp_path / "hub_slug_aliases.csv"
    monkeypatch.setattr(hub_aliases, "ALIAS_FILE", alias_file)
    hub_aliases.hub_slug_aliases.cache_clear()

    source_url = "https://wo293-alias-hook-test.example.com/meeting/1"
    payload = {
        "platform": "boxcast",
        "source_url": source_url,
        "external_id": "boxcast:wo293-alias-hook-test",
        "title": "Council Meeting",
        "date": "2026-09-01",
        "jurisdiction": "Wo293 Alias Hook Placeholder Government, ZZ",
        "video_url": None,
        "video_format": None,
        "segments": [],
        "agenda_items": [],
        "transcript_language": None,
        "transcript_warnings": [],
    }
    result = await crud.ingest_resolution(payload, source_url)
    slug = result["slug"]

    # Un-key it by hand -- the shape of a page nothing has resolved yet,
    # sitting on its raw-text fallback hub until something backfills a
    # real government onto it.
    async with async_session() as session:
        page = (
            await session.execute(select(MeetingPage).where(MeetingPage.slug == slug))
        ).scalar_one()
        page.gov_id = None
        page.gov_type = None
        page.jurisdiction = "Rockaway, NJ"
        page.jurisdiction_confidence = "blank"
        await session.commit()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "backfill_gov_id.py",
            "--hosts",
            "wo293-alias-hook-test.example.com",
            "--apply",
        ],
    )
    await backfill_gov_id.main()

    async with async_session() as session:
        page = (
            await session.execute(select(MeetingPage).where(MeetingPage.slug == slug))
        ).scalar_one()
    assert page.gov_id == "us:place:3464050"

    hub_aliases.hub_slug_aliases.cache_clear()
    assert hub_aliases.redirect_target("rockaway-nj") == "rockaway-borough-nj"
    # One hop -- the new target carries no alias of its own.
    assert hub_aliases.redirect_target("rockaway-borough-nj") is None


def test_the_four_wo293_repaired_targets_resolve_in_one_hop():
    """The real, live-confirmed 2026-09-12 repairs -- each of these
    301'd to a 404 before this WO; each must now be exactly one hop from
    a slug with no further alias."""
    hub_aliases.hub_slug_aliases.cache_clear()
    for old_slug, expected_target in [
        ("lake-havasu-az", "lake-havasu-city-az"),
        ("deland", "deland-fl"),
        ("janesville-wi", "janesville-city-wi"),
        ("oak-ridge", "oak-ridge-tn"),
    ]:
        assert hub_aliases.redirect_target(old_slug) == expected_target
        assert hub_aliases.redirect_target(expected_target) is None
