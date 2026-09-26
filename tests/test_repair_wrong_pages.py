"""WO-934: tests for scripts/repair_wrong_pages.py and the committed sheet.

Three layers, each named for what it proves.

  1. The committed sheet (`reports/wrong_page_worklist.csv`). Its rows are
     REAL pages checked by hand against the 2026-09-21 export, so the
     guard tests here read the real file. They pin the decisions a person
     made (which page is approved to delete, which rows may run without
     Ryan) so a change to any of them shows up in review.
  2. The logic, with a plain-Python stand-in for the Archive. That stand-in
     is SYNTHETIC. It copies the answer shape of the two real endpoints
     (`POST /internal/jurisdiction/override`, `POST /internal/admin/
     delete-pages`), and layer 3 runs the same scenarios against the real
     Archive app, so the stand-in cannot drift without a failure there.
  3. The real Archive app on the isolated local SQLite file from
     tests/conftest.py, driven through its own HTTP routes. Nothing here
     reaches a network or a production database. Government id
     `us:county:99999` (", ZZ") is a synthetic government injected for
     these tests only, the same device tests/test_jurisdiction_override.py
     uses, so no test row bleeds into a state page.
"""

import csv
import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import archive.main
from conftest import wrong_page_export_2026_09_21
from app.utils.gov_registry import government_for_id, registry
from archive.db import crud
from scripts import repair_wrong_pages as tool
from scripts.repair_wrong_pages import (
    ArchiveClient,
    Row,
    StatusIndex,
    UnexpectedResponse,
    build_gone_video_rows,
    check_sheet,
    parse_requires,
    parse_row,
    read_inventory,
    read_status_file,
    read_worklists,
    run_rows,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SHEET = REPO_ROOT / "reports" / "wrong_page_worklist.csv"
POOL = REPO_ROOT / "reports" / "wo934_youtube_no_transcript_pool.csv"
EXPORT, EXPORT_SKIP_REASON = wrong_page_export_2026_09_21()

TODAY = dt.date(2026, 9, 21)


def _no_sleep(_seconds):
    return None


# ===========================================================================
# Layer 1: the committed sheet (real rows)
# ===========================================================================


def _sheet_rows():
    rows, problems = read_worklists([SHEET])
    assert problems == []
    return rows


def test_committed_sheet_has_no_faults():
    rows, problems = read_worklists([SHEET])
    assert problems == []
    assert len(rows) >= 40


def test_every_target_is_a_government_the_archive_knows():
    """The override endpoint refuses an unknown id. Finding that out on the
    Render shell is the slow way, so the sheet is checked here first."""
    for row in _sheet_rows():
        if row.target_gov_id:
            assert government_for_id(row.target_gov_id) is not None, row.origin


_APPROVED_DELETES = {
    6114,  # a county homepage intro video, not a meeting
    6101,  # Greenwood County, KS: an unrelated rocket-lab channel's video
    6830,  # New Haven, IN: a private person's drone footage
    6906,  # Sebring, FL: Ryan clicked it, it does not play (approval inferred)
    7086,  # Malibu, CA: Ryan clicked it, it does not play
}
_REJECTED = {6119, 6218}  # government videos that are not meetings: kept
_APPROVED_SCHOOL_BOARD_REKEYS = {
    1414, 2610, 2899, 3787, 3885, 1311, 1324, 1333, 5565, 1938, 2298, 2666, 5501,
}  # fmt: skip
_APPROVED_MINT_REKEYS = {5945, 10852, 645, 2004, 5301}
_APPROVED_RYAN_NAMED_REKEYS = {3367, 3453}  # Derry, NH and Hopkins, MN
_STILL_WAITING: set = set()


def test_the_approved_rows_are_exactly_the_ones_ryan_approved():
    """Ryan's 2026-09-21 decisions, pinned. A new approval must be a
    deliberate edit of this test, so it is reviewed. Apart from these, only
    the rows the sheet marks `needs_ryan=no` can run at all."""
    rows = _sheet_rows()
    approved_deletes = {r.page_id for r in rows if r.approved and r.action == "delete"}
    assert approved_deletes == _APPROVED_DELETES
    approved_rekeys = {r.page_id for r in rows if r.approved and r.action == "rekey"}
    assert approved_rekeys == (
        _APPROVED_SCHOOL_BOARD_REKEYS
        | _APPROVED_MINT_REKEYS
        | _APPROVED_RYAN_NAMED_REKEYS
        | {2504}
    )
    assert {r.page_id for r in rows if r.rejected} == _REJECTED
    waiting = {
        r.page_id for r in rows if r.needs_ryan and not r.approved and not r.rejected
    }
    assert waiting == _STILL_WAITING


def test_sebring_and_malibu_are_approved_but_wait_for_their_replacement_pages():
    """Ryan clicked both videos on 2026-09-21 and neither plays. Each delete
    still needs its replacement page live (`replacement-video`), and the
    recorded check is the `video-gone` evidence. Page 6906's approval is an
    inference by analogy with Malibu, and its reason says so."""
    by_id = {r.page_id: r for r in _sheet_rows()}
    expected = {
        6906: [("video-gone", "ryan-2026-09-21"), ("replacement-video", "yTeXBxcodt8")],
        7086: [("video-gone", "ryan-2026-09-21"), ("replacement-video", "PveTE-5yFiU")],
    }
    for page_id, requires in expected.items():
        row = by_id[page_id]
        assert row.action == "delete" and row.approved and row.needs_ryan
        assert row.requires == requires
        assert "2026-09-21" in row.reason
    assert "INFERRED" in by_id[6906].reason
    assert "INFERRED" not in by_id[7086].reason
    # Malibu's further examples are recorded as evidence only: nothing ingested.
    evidence = by_id[7086].evidence
    assert "malibucity.org/662/Public-Meeting-Video-Archive" in evidence
    assert "XoWrMZwRFcU" in evidence
    assert by_id[6114].approved and by_id[6114].requires == []


def test_the_replacement_videos_are_already_pinned_to_the_same_government():
    """The replacement for each delete row is pinned to the page's own
    government on main, so the page the drip creates is filed where the tool
    will look for it."""
    pins = (
        REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "tenant_overrides.csv"
    ).read_text(encoding="utf-8")
    by_id = {r.page_id: r for r in _sheet_rows()}
    for page_id, video_id in ((6906, "yTeXBxcodt8"), (7086, "PveTE-5yFiU")):
        gov = by_id[page_id].expected_current_gov_id
        assert f"www.youtube.com,{video_id},{gov},fallback" in pins


def test_derry_and_hopkins_carry_the_ids_ryan_named():
    """Ryan, 2026-09-21: page 3367 is the Derry Cooperative School District,
    page 3453 is Hopkins, MN. Derry is NOT minted: NCES's own page for LEA
    3302610 is titled 'Derry Cooperative School District'."""
    by_id = {r.page_id: r for r in _sheet_rows()}
    assert by_id[3367].target_gov_id == "us:sd:3302610" and by_id[3367].approved
    assert by_id[3453].target_gov_id == "us:sd:2714260" and by_id[3453].approved
    assert "Derry Cooperative School District" in by_id[3367].reason
    assert "Hopkins, MN" in by_id[3453].reason
    gov = government_for_id("us:sd:3302610")
    assert gov is not None and gov.gov_name == "Derry Cooperative School District"


def test_the_minted_rows_carry_the_minted_ids_and_say_the_deploy_comes_first():
    by_id = {r.page_id: r for r in _sheet_rows()}
    expected = {
        5945: "rtr:us:wa:south-snohomish-county-fire-and-rescue-regional-fire-authority",
        10852: "rtr:us:ut:north-valley-public-safety-department",
        645: "rtr:us:ca:santa-clara-county-office-of-education",
        2004: "rtr:us:ca:santa-clara-county-office-of-education",
        5301: "rtr:us:ca:solano-county-office-of-education",
    }
    for page_id, gov_id in expected.items():
        row = by_id[page_id]
        assert row.target_gov_id == gov_id and row.approved
        assert "DEPLOYED" in row.reason
        gov = government_for_id(gov_id)
        assert gov is not None and gov.source.startswith("curated")


def test_page_2504_is_approved_to_move_to_unresolved_and_is_not_a_delete():
    """Ryan: move it to unresolved like page 5816, do not delete it. No registry
    id exists to write, so the row cannot run through the tool; it records the
    path that does apply."""
    row = {r.page_id: r for r in _sheet_rows()}[2504]
    assert (row.action, row.target_gov_id, row.approved) == ("rekey", "", True)
    assert "does NOT apply" in row.evidence  # the backfill path
    assert "repoint_page.py" in row.evidence and "--dry-run" in row.evidence
    assert "MediaPlayer.php?view_id=2&clip_id=2573" in row.evidence


def test_the_two_kept_government_videos_talk_about_meeting_kind_not_a_new_column():
    """`meeting_kind` already exists, and nothing filters on it yet."""
    by_id = {r.page_id: r for r in _sheet_rows()}
    for page_id in _REJECTED:
        text = by_id[page_id].reason
        assert "meeting_kind" in text and "not a new column" in text


def test_deletes_always_wait_for_ryan_and_no_rekey_runs_without_evidence():
    for row in _sheet_rows():
        if row.action == "delete":
            assert row.needs_ryan, row.origin
        if not row.needs_ryan:
            assert row.confidence == "high", row.origin
            assert row.action == "rekey" and row.target_gov_id, row.origin


def test_the_only_row_with_no_target_is_the_one_with_no_id_to_write():
    """A blank target is a finding, not a gap to fill from a guess: page 2504
    (Ryan will not mint a state commission)."""
    blank = {
        r.page_id for r in _sheet_rows() if r.action == "rekey" and not r.target_gov_id
    }
    assert blank == {2504}
    for row in _sheet_rows():
        if row.action == "rekey" and not row.target_gov_id:
            assert row.needs_ryan


def test_wo932_pages_point_at_washington_county_arkansas():
    by_id = {r.page_id: r for r in _sheet_rows()}
    for page_id in (9073, 9681):
        assert by_id[page_id].target_gov_id == "us:county:05143"
        assert by_id[page_id].expected_current_gov_id == "us:county:01129"


def test_the_washcoar_pins_no_longer_file_the_channel_under_alabama():
    pins = (
        REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "tenant_overrides.csv"
    ).read_text(encoding="utf-8")
    wash = [
        line
        for line in pins.splitlines()
        if "channel=@washcoar" in line or ",cGA0CKMbJwI," in line
    ]
    assert len(wash) == 2
    for line in wash:
        assert "us:county:05143" in line and "us:county:01129" not in line


@pytest.mark.skipif(EXPORT is None, reason=EXPORT_SKIP_REASON)
def test_every_row_matches_the_local_export_it_was_built_from():
    """Real check, run where the export exists: the sheet is not stale against it."""
    rows = _sheet_rows()
    problems, counts = check_sheet(rows, inventory=read_inventory(EXPORT))
    assert problems == []
    assert counts == {"matches the export": len(rows)}


# ===========================================================================
# The sheet reader
# ===========================================================================


def _raw(**over):
    raw = {
        "page_id": "101",
        "action": "rekey",
        "target_gov_id": "us:sd:0610620",
        "expected_current_gov_id": "us:place:0618100",
        "expected_slug": "some-slug",
        "requires": "",
        "confidence": "high",
        "needs_ryan": "no",
        "ryan_decision": "",
    }
    raw.update(over)
    return raw


def _row(**over) -> Row:
    row, problems = parse_row(_raw(**over), "test:2")
    assert problems == [], problems
    return row


def test_a_good_row_reads_cleanly():
    row = _row()
    assert (row.page_id, row.action, row.needs_ryan, row.approved) == (
        101,
        "rekey",
        False,
        False,
    )


@pytest.mark.parametrize(
    "over, fragment",
    [
        ({"page_id": "abc"}, "not an integer"),
        ({"action": "move"}, "rekey or delete"),
        ({"confidence": "sure"}, "high, medium or low"),
        ({"needs_ryan": "maybe"}, "needs_ryan"),
        ({"ryan_decision": "yes"}, "ryan_decision"),
        ({"expected_current_gov_id": ""}, "expected_current_gov_id is required"),
        ({"target_gov_id": "us:place:0618100"}, "equals expected_current"),
        ({"confidence": "medium"}, "only a high-confidence row"),
        (
            {"target_gov_id": "", "confidence": "high"},
            "no target must say needs_ryan=yes",
        ),
        ({"requires": "video-alive"}, "unknown condition"),
        ({"requires": "replacement-page:12"}, "replacement-page is gone"),
        ({"requires": "replacement-video:"}, "11-character video id"),
        ({"requires": "replacement-video:short"}, "11-character video id"),
        ({"requires": "video-gone:ryan-21-9-2026"}, "video-gone:<who>-<YYYY-MM-DD>"),
        ({"requires": "video-gone:ryan-2026-13-40"}, "video-gone:<who>-<YYYY-MM-DD>"),
    ],
)
def test_a_bad_row_is_reported(over, fragment):
    _, problems = parse_row(_raw(**over), "test:2")
    assert any(fragment in p for p in problems), problems


def test_a_delete_row_needs_a_slug_ryan_and_no_target():
    _, problems = parse_row(
        _raw(action="delete", target_gov_id="", expected_slug="", needs_ryan="no"),
        "test:2",
    )
    text = " ".join(problems)
    assert "needs expected_slug" in text and "must say needs_ryan=yes" in text
    _, problems = parse_row(
        _raw(action="delete", target_gov_id="us:sd:0610620", needs_ryan="yes"), "t:2"
    )
    assert any("must not carry a target" in p for p in problems)


def test_requires_tokens():
    tokens, problems = parse_requires("video-gone; replacement-video:PveTE-5yFiU")
    assert tokens == [("video-gone", ""), ("replacement-video", "PveTE-5yFiU")]
    assert not problems
    tokens, problems = parse_requires(
        "video-gone:ryan-2026-09-21;replacement-video:yTeXBxcodt8"
    )
    assert tokens == [
        ("video-gone", "ryan-2026-09-21"),
        ("replacement-video", "yTeXBxcodt8"),
    ]
    assert not problems
    assert parse_requires("")[0] == []
    assert tool.parse_human_check("ryan-2026-09-21") == ("ryan", dt.date(2026, 9, 21))
    assert tool.parse_human_check("2026-09-21") is None
    assert tool.parse_human_check("ryan-2026-02-30") is None


def test_a_page_may_appear_once_across_sheets(tmp_path):
    header = ",".join(
        [
            "page_id",
            "action",
            "target_gov_id",
            "expected_current_gov_id",
            "expected_slug",
            "requires",
            "confidence",
            "needs_ryan",
            "ryan_decision",
        ]
    )
    line = "101,rekey,us:sd:0610620,us:place:0618100,s,,high,no,"
    one, two = tmp_path / "one.csv", tmp_path / "two.csv"
    one.write_text(header + "\n" + line + "\n")
    two.write_text(header + "\n" + line + "\n")
    rows, problems = read_worklists([one, two])
    assert len(rows) == 1
    assert any("already on the sheet" in p for p in problems)


# ===========================================================================
# Layer 2: the logic, against a synthetic stand-in for the Archive
# ===========================================================================


def _page(page_id, gov="us:place:0618100", slug=None, **over):
    page = {
        "id": page_id,
        "slug": slug or f"slug-{page_id}",
        "gov_id": gov,
        "jurisdiction": "Old Name, ZZ",
        "jurisdiction_confidence": "registry",
        "source_url_normalized": f"https://example.test/{page_id}",
        "video_url": "",
    }
    page.update(over)
    return page


class FakeClient:
    """SYNTHETIC. Same answer shape as the real override and delete-pages routes."""

    def __init__(self, pages, *, fail_on_page=None):
        self.pages = {p["id"]: dict(p) for p in pages}
        self.fail_on_page = fail_on_page
        self.calls = []
        self.writes = []

    def read_pages(self, ids):
        return {i: dict(self.pages[i]) for i in set(ids) if i in self.pages}

    def pages_with_video(self, video_id):
        self.calls.append(("pages_with_video", video_id, True))
        return [
            {"id": p["id"], "slug": p["slug"], "gov_id": p["gov_id"]}
            for p in self.pages.values()
            if video_id in tool.page_video_ids(p)
        ]

    def override(self, page_id, gov_id, *, dry_run):
        self.calls.append(("override", page_id, dry_run))
        if page_id == self.fail_on_page:
            raise UnexpectedResponse("simulated HTTP 500")
        page = self.pages[page_id]
        entry = {
            "meeting_page_id": page_id,
            "slug": page["slug"],
            "gov_id_before": page["gov_id"],
            "gov_id_after": gov_id,
            "jurisdiction_after": "New Name, ZZ",
        }
        if not dry_run:
            self.writes.append(f"override {page_id}")
            page["gov_id"] = gov_id
            page["jurisdiction_confidence"] = tool.MANUAL_OVERRIDE
        return {
            "dry_run": dry_run,
            "gov_id": gov_id,
            "gov_name": "New Name, ZZ",
            "changed": [entry],
            "already_overridden": [],
            "missing_ids": [],
            "would_update": 1,
            "updated": 0 if dry_run else 1,
            "tenant_override_rules": ["example.test,,us:sd:0000000,fallback,human,x"],
        }

    def delete(self, slug, *, dry_run):
        self.calls.append(("delete", slug, dry_run))
        page = next((p for p in self.pages.values() if p["slug"] == slug), None)
        if page is None:
            return {"dry_run": dry_run, "found": [], "not_found": [slug], "deleted": 0}
        found = [
            {
                "slug": slug,
                "title": "t",
                "platform": "p",
                "source_url_normalized": page["source_url_normalized"],
            }
        ]
        if not dry_run:
            self.writes.append(f"delete {slug}")
            del self.pages[page["id"]]
        return {
            "dry_run": dry_run,
            "found": found,
            "not_found": [],
            "deleted": 0 if dry_run else 1,
        }


def _run(rows, client, **kw):
    kw.setdefault("sleep", _no_sleep)
    kw.setdefault("today", TODAY)
    return run_rows(rows, client, **kw)


def _outcomes(report):
    return {r.row.page_id: r.outcome for r in report.results}


def _rekey_row(page_id, target="us:sd:0610620", **over):
    return _row(
        page_id=str(page_id),
        target_gov_id=target,
        expected_slug=f"slug-{page_id}",
        **over,
    )


def test_a_dry_run_writes_nothing_and_says_what_it_would_do():
    client = FakeClient([_page(1), _page(2)])
    report = _run([_rekey_row(1), _rekey_row(2)], client)
    assert _outcomes(report) == {1: tool.WOULD_REKEY, 2: tool.WOULD_REKEY}
    assert client.writes == []
    assert all(dry for (_, _, dry) in client.calls)


def test_apply_rekeys_and_reads_the_page_back():
    client = FakeClient([_page(1)])
    report = _run([_rekey_row(1)], client, apply=True)
    assert _outcomes(report) == {1: tool.REKEYED}
    assert client.pages[1]["gov_id"] == "us:sd:0610620"
    (result,) = report.results
    assert result.before["gov_id"] == "us:place:0618100"
    assert result.after["gov_id"] == "us:sd:0610620"
    assert result.draft_rules


def test_a_stale_row_never_acts():
    """The page's government changed after the sheet was written."""
    client = FakeClient([_page(1, gov="us:county:11111")])
    report = _run([_rekey_row(1)], client, apply=True)
    assert _outcomes(report) == {1: tool.REFUSED_STALE}
    assert client.calls == [] and client.writes == []
    assert "us:county:11111" in report.results[0].detail


def test_a_changed_slug_is_stale_too():
    client = FakeClient([_page(1, slug="a-different-slug")])
    report = _run([_rekey_row(1)], client, apply=True)
    assert _outcomes(report) == {1: tool.REFUSED_STALE}
    assert client.writes == []


def test_a_no_government_row_matches_only_a_page_with_none():
    row = _row(page_id="1", expected_current_gov_id=tool.NO_GOV, expected_slug="slug-1")
    assert _outcomes(_run([row], FakeClient([_page(1, gov="")]))) == {
        1: tool.WOULD_REKEY
    }
    assert _outcomes(_run([row], FakeClient([_page(1, gov="us:x:1")]))) == {
        1: tool.REFUSED_STALE
    }


def test_a_page_already_at_the_target_is_left_alone():
    client = FakeClient([_page(1, gov="us:sd:0610620")])
    report = _run([_rekey_row(1)], client, apply=True)
    assert _outcomes(report) == {1: tool.ALREADY_DONE}
    assert client.calls == []


def test_a_missing_page_is_refused_for_a_rekey_and_done_for_a_delete():
    rekey = _rekey_row(9)
    delete = _row(
        page_id="10",
        action="delete",
        target_gov_id="",
        needs_ryan="yes",
        expected_slug="slug-10",
        ryan_decision="approve",
    )
    report = _run([rekey, delete], FakeClient([]), apply=True, allow_deletes=True)
    assert _outcomes(report) == {9: tool.REFUSED_MISSING, 10: tool.ALREADY_DONE}


def test_a_row_that_needs_ryan_waits_until_he_approves():
    waiting = _rekey_row(1, needs_ryan="yes")
    approved = _rekey_row(2, needs_ryan="yes", ryan_decision="approve")
    rejected = _rekey_row(3, needs_ryan="yes", ryan_decision="reject")
    client = FakeClient([_page(1), _page(2), _page(3)])
    report = _run([waiting, approved, rejected], client, apply=True)
    assert _outcomes(report) == {
        1: tool.SKIP_AWAITING,
        2: tool.REKEYED,
        3: tool.SKIP_REJECTED,
    }
    assert client.writes == ["override 2"]


def test_a_row_with_no_target_is_reported_not_guessed():
    row = _rekey_row(1, target="", needs_ryan="yes")
    report = _run([row], FakeClient([_page(1)]), apply=True)
    assert _outcomes(report) == {1: tool.SKIP_BLOCKED}


def test_a_stale_row_that_needs_ryan_is_reported_stale_not_awaiting():
    """Ryan should not be asked about a row that is already wrong."""
    row = _rekey_row(1, needs_ryan="yes")
    report = _run([row], FakeClient([_page(1, gov="us:county:11111")]))
    assert _outcomes(report) == {1: tool.REFUSED_STALE}


def _delete_row(page_id, **over):
    values = dict(
        page_id=str(page_id),
        action="delete",
        target_gov_id="",
        needs_ryan="yes",
        confidence="medium",
        expected_slug=f"slug-{page_id}",
    )
    values.update(over)
    return _row(**values)


def test_a_delete_needs_approve_and_allow_deletes():
    unapproved = _delete_row(1)
    approved = _delete_row(2, ryan_decision="approve")
    client = FakeClient([_page(1), _page(2)])

    dry = _run([unapproved, approved], client)
    assert _outcomes(dry) == {1: tool.SKIP_AWAITING, 2: tool.WOULD_DELETE}
    assert client.writes == []

    no_flag = _run([unapproved, approved], client, apply=True)
    assert _outcomes(no_flag) == {1: tool.SKIP_AWAITING, 2: tool.SKIP_NO_DELETES}
    assert client.writes == []

    done = _run([unapproved, approved], client, apply=True, allow_deletes=True)
    assert _outcomes(done) == {1: tool.SKIP_AWAITING, 2: tool.DELETED}
    assert client.writes == ["delete slug-2"]
    assert set(client.pages) == {1}


def test_a_batch_writes_at_most_batch_size_rows_and_a_rerun_resumes():
    rows = [_rekey_row(i) for i in (1, 2, 3)]
    client = FakeClient([_page(1), _page(2), _page(3)])
    first = _run(rows, client, apply=True, batch_size=2)
    assert _outcomes(first) == {
        1: tool.REKEYED,
        2: tool.REKEYED,
        3: tool.SKIP_BATCH_FULL,
    }
    assert first.eligible_left == 1
    second = _run(rows, client, apply=True, batch_size=2)
    assert _outcomes(second) == {
        1: tool.ALREADY_DONE,
        2: tool.ALREADY_DONE,
        3: tool.REKEYED,
    }


def test_the_run_stops_on_the_first_unexpected_answer():
    rows = [_rekey_row(i) for i in (1, 2, 3)]
    client = FakeClient([_page(1), _page(2), _page(3)], fail_on_page=2)
    report = _run(rows, client, apply=True)
    assert [r.outcome for r in report.results] == [tool.REKEYED, tool.HALTED]
    assert "page 2" in report.halted and "simulated HTTP 500" in report.halted
    assert client.pages[3]["gov_id"] == "us:place:0618100"  # never tried
    assert "STOPPED" in tool.summarise(report, apply=True)


def test_a_before_value_that_differs_from_the_live_read_halts_the_run():
    """The page changed between the read and the dry run."""
    client = FakeClient([_page(1)])
    real_override = client.override

    def racing(page_id, gov_id, *, dry_run):
        client.pages[page_id]["gov_id"] = "us:county:22222"
        return real_override(page_id, gov_id, dry_run=dry_run)

    client.override = racing
    report = _run([_rekey_row(1)], client, apply=True)
    assert report.results[0].outcome == tool.HALTED
    assert client.writes == []


def test_only_ids_limits_the_rows_touched():
    rows = [_rekey_row(1), _rekey_row(2)]
    client = FakeClient([_page(1), _page(2)])
    report = _run(rows, client, apply=True, only_ids={2})
    assert _outcomes(report) == {2: tool.REKEYED}
    assert client.pages[1]["gov_id"] == "us:place:0618100"


def test_the_log_records_before_and_after(tmp_path):
    log_path = tmp_path / "log.csv"
    log = tool.LogWriter(log_path)
    client = FakeClient([_page(1)])
    _run([_rekey_row(1)], client, apply=True, log=log)
    log.close()
    (line,) = list(csv.DictReader(open(log_path, newline="", encoding="utf-8")))
    assert list(line) == tool.LOG_COLUMNS
    assert (line["outcome"], line["before_gov_id"], line["after_gov_id"]) == (
        tool.REKEYED,
        "us:place:0618100",
        "us:sd:0610620",
    )
    assert line["after_confidence"] == tool.MANUAL_OVERRIDE
    assert "example.test" in line["draft_tenant_rules"]


# --- requirements ---------------------------------------------------------


def _status(page_id=None, video_id=None, status="deleted", days_ago=0):
    index = StatusIndex()
    checked = TODAY - dt.timedelta(days=days_ago)
    if page_id is not None:
        index.by_page[page_id] = (status, checked)
    if video_id is not None:
        index.by_video[video_id] = (status, checked)
    return index


def _gone_delete_row(page_id, requires="video-gone", **over):
    return _delete_row(page_id, requires=requires, ryan_decision="approve", **over)


def _yt_page(page_id, video_id="abcdefghijk", **over):
    return _page(page_id, video_url=f"https://www.youtube.com/embed/{video_id}", **over)


def test_video_gone_needs_a_checked_status_file():
    client = FakeClient([_yt_page(1)])
    row = _gone_delete_row(1)
    report = _run([row], client, apply=True, allow_deletes=True)
    assert _outcomes(report) == {1: tool.REFUSED_REQUIRES}
    assert "--video-status" in report.results[0].detail
    assert client.writes == []


@pytest.mark.parametrize(
    "status, expected",
    [
        (_status(page_id=1, status="deleted"), tool.DELETED),
        (_status(video_id="abcdefghijk", status="private"), tool.DELETED),
        (_status(page_id=1, status="malformed"), tool.DELETED),
        (_status(page_id=1, status="ok"), tool.REFUSED_REQUIRES),
        (_status(page_id=1, status="embedding_disabled"), tool.REFUSED_REQUIRES),
        (_status(page_id=1, status="unknown"), tool.REFUSED_REQUIRES),
        (_status(page_id=1, status="deleted", days_ago=30), tool.REFUSED_REQUIRES),
        (_status(page_id=2, status="deleted"), tool.REFUSED_REQUIRES),
    ],
)
def test_only_a_recent_gone_status_satisfies_video_gone(status, expected):
    client = FakeClient([_yt_page(1)])
    report = _run(
        [_gone_delete_row(1)], client, apply=True, allow_deletes=True, status=status
    )
    assert _outcomes(report) == {1: expected}


def test_a_replacement_video_must_be_live_on_another_page_under_the_same_government():
    """The replacement's page id cannot be known before the drip creates the
    page, so the tool finds it by the video id. Pages 51 and 52 are stand-ins."""
    status = _status(page_id=1)
    rv = "replacement-video:zzzzzzzzzzz"

    def fresh(*extra):
        return FakeClient([_yt_page(1), *extra])

    def outcome(client):
        row = _gone_delete_row(1, requires=f"video-gone;{rv}")
        report = _run([row], client, apply=True, allow_deletes=True, status=status)
        return report.results[0]

    # Not ingested yet: refused, and the reason says to ingest it first.
    result = outcome(fresh())
    assert (
        result.outcome == tool.REFUSED_REQUIRES
        and "ingest the replacement first" in result.detail
    )
    # Live, but under another government: refused.
    other = _yt_page(52, video_id="zzzzzzzzzzz", gov="us:place:9999999")
    result = outcome(fresh(other))
    assert (
        result.outcome == tool.REFUSED_REQUIRES and "not this page's" in result.detail
    )
    # Live under the same government: deleted.
    good = _yt_page(51, video_id="zzzzzzzzzzz")
    client = fresh(good)
    assert outcome(client).outcome == tool.DELETED
    assert set(client.pages) == {51}
    # A page never counts as its own replacement.
    own = FakeClient([_yt_page(1, video_id="zzzzzzzzzzz")])
    assert outcome(own).outcome == tool.REFUSED_REQUIRES


def test_page_video_ids_reads_the_address_the_source_and_the_external_id():
    page = {
        "video_url": "https://www.youtube.com/embed/aaaaaaaaaaa",
        "source_url_normalized": "https://www.youtube.com/watch?v=bbbbbbbbbbb",
        "external_id": "youtube:ccccccccccc",
    }
    assert tool.page_video_ids(page) == ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"]
    assert tool.page_video_ids({"video_url": "https://x.granicus.com/a.m3u8"}) == []
    assert tool.page_video_ids({"external_id": "youtube:live_stream"}) == []


def test_replacement_video_with_no_way_to_look_is_refused():
    row = _gone_delete_row(1, requires="replacement-video:zzzzzzzzzzz")
    ctx = tool.Context(
        live={1: _yt_page(1)}, today=TODAY, apply=True, allow_deletes=True
    )
    assert "none is available" in tool.check_requirements(row, ctx)


def _human_row(check, replacement="zzzzzzzzzzz"):
    return _gone_delete_row(
        1, requires=f"video-gone:{check};replacement-video:{replacement}"
    )


def test_a_recorded_human_check_stands_in_for_the_status_file():
    good = _yt_page(51, video_id="zzzzzzzzzzz")
    client = FakeClient([_yt_page(1), good])
    report = _run(
        [_human_row("ryan-2026-09-21")], client, apply=True, allow_deletes=True
    )  # no status file at all
    assert _outcomes(report) == {1: tool.DELETED}


@pytest.mark.parametrize(
    "check, fragment",
    [
        ("ryan-2026-08-01", "51 days old"),  # too old to trust
        ("ryan-2026-09-30", "in the future"),  # not yet dated
    ],
)
def test_a_human_check_must_be_recent_and_not_in_the_future(check, fragment):
    good = _yt_page(51, video_id="zzzzzzzzzzz")
    client = FakeClient([_yt_page(1), good])
    report = _run([_human_row(check)], client, apply=True, allow_deletes=True)
    assert _outcomes(report) == {1: tool.REFUSED_REQUIRES}
    assert fragment in report.results[0].detail
    assert client.writes == []


def test_a_newer_status_check_that_says_alive_overrules_a_human_check():
    """Ryan clicked on the 21st and it did not play; the drip Mac checked on
    the 23rd and the video answers. A private video can be made public."""
    good = _yt_page(51, video_id="zzzzzzzzzzz")
    client = FakeClient([_yt_page(1), good])
    newer_ok = StatusIndex()
    newer_ok.by_page[1] = ("ok", dt.date(2026, 9, 23))
    report = _run(
        [_human_row("ryan-2026-09-21")],
        client,
        apply=True,
        allow_deletes=True,
        status=newer_ok,
        today=dt.date(2026, 9, 24),
    )
    assert _outcomes(report) == {1: tool.REFUSED_REQUIRES}
    assert "newer" in report.results[0].detail
    # An OLDER alive check does not overrule the person's later look.
    older_ok = StatusIndex()
    older_ok.by_page[1] = ("ok", dt.date(2026, 9, 10))
    report = _run(
        [_human_row("ryan-2026-09-21")],
        FakeClient([_yt_page(1), good]),
        apply=True,
        allow_deletes=True,
        status=older_ok,
        today=dt.date(2026, 9, 22),
    )
    assert _outcomes(report) == {1: tool.DELETED}


def test_the_committed_sebring_and_malibu_rows_follow_the_ordering_rule():
    """The REAL rows, run against stand-in pages. Ryan approved both deletes,
    and neither may run until its replacement video is on a live page under
    the same government. The stand-in pages copy each row's expected slug and
    government; the replacement is added or left out."""
    rows = {r.page_id: r for r in _sheet_rows() if r.page_id in (6906, 7086)}
    videos = {
        6906: ("_RZBcYEbQr4", "yTeXBxcodt8"),
        7086: ("JGHPsOlz7wI", "PveTE-5yFiU"),
    }
    today = dt.date(2026, 9, 22)  # the day after Ryan's check
    for page_id, (old, new) in videos.items():
        row = rows[page_id]

        def page(replacement_gov=None):
            pages = [
                _yt_page(
                    page_id,
                    video_id=old,
                    gov=row.expected_current_gov_id,
                    slug=row.expected_slug,
                )
            ]
            if replacement_gov is not None:
                pages.append(_yt_page(900 + page_id, video_id=new, gov=replacement_gov))
            return FakeClient(pages)

        # 1. replacement not ingested yet: refused, nothing written
        client = page()
        report = _run([row], client, apply=True, allow_deletes=True, today=today)
        assert _outcomes(report) == {page_id: tool.REFUSED_REQUIRES}, page_id
        assert client.writes == []
        # 2. replacement live under another government: refused
        client = page("us:place:9999999")
        report = _run([row], client, apply=True, allow_deletes=True, today=today)
        assert _outcomes(report) == {page_id: tool.REFUSED_REQUIRES}
        # 3. replacement live under the page's own government: deleted, and only
        #    with --allow-deletes
        client = page(row.expected_current_gov_id)
        report = _run([row], client, apply=True, allow_deletes=False, today=today)
        assert _outcomes(report) == {page_id: tool.SKIP_NO_DELETES}
        assert client.writes == []
        report = _run([row], client, apply=True, allow_deletes=True, today=today)
        assert _outcomes(report) == {page_id: tool.DELETED}
        assert client.writes == [f"delete {row.expected_slug}"]
        # 4. a stale row is still refused, replacement or not
        stale = page(row.expected_current_gov_id)
        stale.pages[page_id]["slug"] = "someone-renamed-this"
        report = _run([row], stale, apply=True, allow_deletes=True, today=today)
        assert _outcomes(report) == {page_id: tool.REFUSED_STALE}
        # 5. Ryan's check ages out after 14 days
        report = _run(
            [row], page(row.expected_current_gov_id), apply=True, allow_deletes=True,
            today=dt.date(2026, 10, 6),
        )  # fmt: skip
        assert _outcomes(report) == {page_id: tool.REFUSED_REQUIRES}


# --- status file and gone-videos --------------------------------------------


def _write(path, lines):
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_the_status_file_reads_and_keeps_the_newest_check(tmp_path):
    path = _write(
        tmp_path / "status.csv",
        [
            "page_id,video_id,status,checked_on,http_status,note",
            "6114,Eh1JO9zT_u0,ok,2026-09-01,200,",
            "6114,Eh1JO9zT_u0,deleted,2026-09-20,404,",
            ",zzzzzzzzzzz,private,2026-09-20,403,",
        ],
    )
    index, problems = read_status_file(path)
    assert problems == []
    assert index.by_page[6114] == ("deleted", dt.date(2026, 9, 20))
    assert index.by_video["zzzzzzzzzzz"][0] == "private"


def test_a_bad_status_file_is_reported(tmp_path):
    path = _write(
        tmp_path / "status.csv",
        [
            "page_id,video_id,status,checked_on",
            "1,a,vanished,2026-09-20",
            "2,b,deleted,20-9-2026",
            ",,deleted,2026-09-20",
        ],
    )
    _, problems = read_status_file(path)
    assert len(problems) == 3
    _, problems = read_status_file(_write(tmp_path / "x.csv", ["status,when", "ok,1"]))
    assert any("missing column" in p for p in problems)


def test_gone_video_rows_come_only_from_a_recent_checked_status_file():
    pool = [
        {
            "page_id": "1",
            "gov_id": "us:place:1",
            "government": "A",
            "title": "T1",
            "video_url": "https://www.youtube.com/watch?v=aaaaaaaaaaa",
            "archive_url": "https://redtaperecordings.com/m/one",
        },
        {
            "page_id": "2",
            "gov_id": "",
            "government": "B",
            "title": "",
            "video_url": "https://www.youtube.com/watch?v=bbbbbbbbbbb",
            "archive_url": "https://redtaperecordings.com/m/two",
        },
        {
            "page_id": "3",
            "gov_id": "us:place:3",
            "government": "C",
            "title": "T3",
            "video_url": "https://www.youtube.com/watch?v=ccccccccccc",
            "archive_url": "https://redtaperecordings.com/m/three",
        },
        {
            "page_id": "4",
            "gov_id": "us:place:4",
            "government": "D",
            "title": "T4",
            "video_url": "https://www.youtube.com/watch?v=ddddddddddd",
            "archive_url": "https://redtaperecordings.com/m/four",
        },
        {
            "page_id": "5",
            "gov_id": "us:place:5",
            "government": "E",
            "title": "T5",
            "video_url": "https://www.youtube.com/watch?v=eeeeeeeeeee",
            "archive_url": "https://redtaperecordings.com/m/five",
        },
        {
            "page_id": "6",
            "gov_id": "us:place:6",
            "government": "F",
            "title": "T6",
            "video_url": "https://www.youtube.com/watch?v=fffffffffff",
            "archive_url": "https://redtaperecordings.com/m/six",
        },
    ]
    status = StatusIndex()
    status.by_page[1] = ("deleted", TODAY)  # gone: a row
    status.by_page[2] = ("malformed", TODAY)  # gone, and no government id: a row
    status.by_page[3] = ("ok", TODAY)  # alive: none
    status.by_page[4] = ("embedding_disabled", TODAY)  # alive: none
    status.by_page[5] = ("private", TODAY - dt.timedelta(days=40))  # too old: none
    # page 6 has no check at all: none
    rows, counts = build_gone_video_rows(pool, status, today=TODAY)
    assert [r["page_id"] for r in rows] == ["1", "2"]
    assert rows[1]["expected_current_gov_id"] == tool.NO_GOV
    assert counts["not checked yet"] == 1 and counts["check too old to trust"] == 1
    for r in rows:
        assert (r["action"], r["needs_ryan"], r["ryan_decision"], r["requires"]) == (
            "delete",
            "yes",
            "",
            "video-gone",
        )
        parsed, problems = parse_row(r, "gone:2")
        assert problems == [] and not parsed.approved


def test_gone_video_rows_skip_pages_already_on_the_committed_sheet():
    pool = [
        {
            "page_id": "7086",
            "gov_id": "us:place:0645246",
            "government": "Malibu",
            "title": "City Council Regular Meeting",
            "video_url": "https://www.youtube.com/watch?v=JGHPsOlz7wI",
            "archive_url": "https://redtaperecordings.com/m/malibu",
        },
    ]
    status = _status(page_id=7086)
    rows, counts = build_gone_video_rows(
        pool, status, today=TODAY, skip_page_ids=[7086]
    )
    assert rows == [] and counts == {"already on the committed sheet": 1}


def test_the_real_pool_has_only_readable_video_addresses_and_holds_the_three_pages():
    with open(POOL, newline="", encoding="utf-8") as fh:
        pool = list(csv.DictReader(fh))
    assert len(pool) == 101
    ids = {r["page_id"] for r in pool}
    assert {"6114", "6906", "7086"} <= ids
    # With no status file at all, no row can be built: nothing is ever
    # guessed gone.
    rows, counts = build_gone_video_rows(pool, StatusIndex(), today=TODAY)
    assert rows == [] and counts == {"not checked yet": 101}


# --- the sheet against an export -----------------------------------------------


def test_check_sheet_flags_stale_and_missing_rows_against_an_export():
    rows = [_rekey_row(1), _rekey_row(2), _rekey_row(3), _rekey_row(4)]
    inventory = {
        1: _page(1),
        2: _page(2, gov="us:county:11111"),
        3: _page(3, gov="us:sd:0610620"),
    }
    problems, counts = check_sheet(rows, inventory=inventory)
    assert counts == {
        "matches the export": 1,
        "stale: the export no longer matches the row": 1,
        "already carries the target": 1,
        "page not in the export": 1,
    }
    assert len(problems) == 1 and "page 2" in problems[0]


def test_check_sheet_flags_a_target_the_registry_does_not_know():
    problems, _ = check_sheet([_rekey_row(1)], registry_lookup=lambda gov_id: None)
    assert len(problems) == 1 and "not a government the Archive knows" in problems[0]


# --- addresses, the token ---------------------------------------------------------


def test_apply_only_talks_to_this_machine_by_default():
    assert tool._is_local("http://127.0.0.1:10000")
    assert tool._is_local("http://localhost:8000")
    assert not tool._is_local("https://redtaperecordings.com")
    assert not tool._is_local("https://rtr-deeplink-archive.onrender.com")


def test_the_address_comes_from_the_flag_then_the_environment_then_port():
    assert (
        tool.resolve_base_url("http://a/", {"ARCHIVE_BASE_URL": "http://b"})
        == "http://a"
    )
    assert tool.resolve_base_url(None, {"ARCHIVE_BASE_URL": "http://b/"}) == "http://b"
    assert tool.resolve_base_url(None, {"PORT": "10000"}) == "http://127.0.0.1:10000"
    assert tool.resolve_base_url(None, {}) == ""


def test_the_tool_never_loads_a_dotenv_file():
    """A .env in a parent folder is how a worktree once reached production."""
    source = Path(tool.__file__).read_text(encoding="utf-8")
    assert "dotenv" not in source


def test_apply_against_a_remote_address_is_refused(monkeypatch, capsys):
    monkeypatch.setenv("ARCHIVE_INGEST_TOKEN", "a-secret-token-value")
    code = tool.main(
        [
            "run",
            str(SHEET),
            "--apply",
            "--base-url",
            "https://redtaperecordings.com",
            "--log",
            "/dev/null",
        ]
    )
    out = capsys.readouterr()
    assert code == 1 and "not this machine" in out.err
    assert "a-secret-token-value" not in out.out + out.err


def test_run_needs_a_token(monkeypatch, capsys):
    monkeypatch.delenv("ARCHIVE_INGEST_TOKEN", raising=False)
    assert tool.main(["run", str(SHEET), "--base-url", "http://127.0.0.1:1"]) == 1
    assert "ARCHIVE_INGEST_TOKEN" in capsys.readouterr().err


def test_allow_deletes_means_nothing_without_apply(monkeypatch, capsys):
    monkeypatch.setenv("ARCHIVE_INGEST_TOKEN", "x")
    code = tool.main(
        ["run", str(SHEET), "--allow-deletes", "--base-url", "http://127.0.0.1:1"]
    )
    assert code == 1 and "--allow-deletes" in capsys.readouterr().err


def test_the_manual_override_tier_matches_the_archives():
    assert tool.MANUAL_OVERRIDE == crud._MANUAL_OVERRIDE_CONFIDENCE


# ===========================================================================
# Layer 3: the real Archive app on the local SQLite file
# ===========================================================================

_GOV_ID = "us:county:99999"
_SYNTHETIC_GOV = registry.Government(
    gov_id=_GOV_ID,
    gov_name="Wo934 Test County",
    gov_type="county",
    country="us",
    state="ZZ",
)
_AUTH_TOKEN = "test-token"


@pytest.fixture
def live_archive(monkeypatch, tmp_path):
    """The real Archive app, with the synthetic government resolvable and the
    pending-rules file inside the test's own folder."""
    real = registry.governments()

    def _lookup(gov_id):
        if gov_id == _GOV_ID:
            return _SYNTHETIC_GOV
        return real.get(gov_id) or registry.government_for_id(gov_id)

    monkeypatch.setattr(crud, "registry_government_for_id", _lookup)
    monkeypatch.setattr(
        crud, "registry_governments", lambda: {**real, _GOV_ID: _SYNTHETIC_GOV}
    )
    monkeypatch.setattr(
        crud, "JURISDICTION_OVERRIDE_RULES_FILE", tmp_path / "pending.csv"
    )
    http = TestClient(archive.main.app)
    return ArchiveClient("http://testserver", _AUTH_TOKEN, http=http), http


def _ingest(http, tag):
    payload = {
        "platform": "granicus",
        "source_url": f"https://wo934-{tag}.granicus.com/player/clip/{tag}",
        "external_id": None,
        "title": f"City Council Regular Meeting {tag}",
        "date": "2026-08-01",
        "jurisdiction": "Wo934 Default City, ZZ",
        "video_url": "https://example.com/video.m3u8",
        "video_format": "m3u8",
        "segments": [{"start": 0.0, "end": 1.0, "text": "Call to order"}],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }
    body = dict(payload, input_url_normalized=payload["source_url"])
    response = http.post(
        "/internal/ingest",
        json=body,
        headers={"Authorization": f"Bearer {_AUTH_TOKEN}"},
    )
    assert response.status_code == 200, response.text
    return response.json()["slug"]


async def _page_id(slug):
    from sqlalchemy import select

    from archive.db.engine import async_session
    from archive.db.models import MeetingPage

    async with async_session() as session:
        return (
            await session.execute(
                select(MeetingPage.id).where(MeetingPage.slug == slug)
            )
        ).scalar_one()


async def _real_row(client, http, tag, **over):
    """Ingest a page, read it live, and build a row that expects what it shows."""
    slug = _ingest(http, tag)
    page_id = await _page_id(slug)
    live = client.read_pages([page_id])[page_id]
    values = dict(
        page_id=str(page_id),
        target_gov_id=_GOV_ID,
        expected_current_gov_id=live["gov_id"] or tool.NO_GOV,
        expected_slug=slug,
    )
    values.update(over)
    return _row(**values), page_id


async def test_real_archive_dry_run_reads_but_writes_nothing(live_archive):
    client, http = live_archive
    row, page_id = await _real_row(client, http, "dry")
    report = _run([row], client)
    assert _outcomes(report) == {page_id: tool.WOULD_REKEY}
    assert client.writes == []
    live = client.read_pages([page_id])[page_id]
    assert live["gov_id"] != _GOV_ID
    assert live["jurisdiction_confidence"] != tool.MANUAL_OVERRIDE
    assert report.results[0].draft_rules, "the dry run previews the rule it would write"


async def test_real_archive_apply_rekeys_and_a_second_run_finds_it_done(live_archive):
    client, http = live_archive
    row, page_id = await _real_row(client, http, "apply")
    first = _run([row], client, apply=True)
    assert _outcomes(first) == {page_id: tool.REKEYED}
    live = client.read_pages([page_id])[page_id]
    assert live["gov_id"] == _GOV_ID
    assert live["jurisdiction_confidence"] == tool.MANUAL_OVERRIDE
    assert live["jurisdiction"] == "Wo934 Test County, ZZ"
    assert first.results[0].before["gov_id"] != _GOV_ID
    assert first.results[0].after["gov_id"] == _GOV_ID
    second = _run([row], client, apply=True)
    assert _outcomes(second) == {page_id: tool.ALREADY_DONE}
    assert client.writes == [f"override page {page_id} -> {_GOV_ID}"]


async def test_real_archive_a_stale_row_is_refused_and_nothing_is_written(live_archive):
    client, http = live_archive
    row, page_id = await _real_row(
        client, http, "stale", expected_current_gov_id="us:county:11111"
    )
    report = _run([row], client, apply=True)
    assert _outcomes(report) == {page_id: tool.REFUSED_STALE}
    assert client.writes == []
    assert client.read_pages([page_id])[page_id]["gov_id"] != _GOV_ID


async def test_real_archive_a_delete_needs_approve_and_allow_deletes(live_archive):
    client, http = live_archive
    row, page_id = await _real_row(
        client,
        http,
        "delete",
        action="delete",
        target_gov_id="",
        needs_ryan="yes",
        confidence="medium",
        ryan_decision="approve",
    )
    dry = _run([row], client)
    assert _outcomes(dry) == {page_id: tool.WOULD_DELETE}
    blocked = _run([row], client, apply=True)
    assert _outcomes(blocked) == {page_id: tool.SKIP_NO_DELETES}
    assert page_id in client.read_pages([page_id])
    done = _run([row], client, apply=True, allow_deletes=True)
    assert _outcomes(done) == {page_id: tool.DELETED}
    assert client.read_pages([page_id]) == {}
    again = _run([row], client, apply=True, allow_deletes=True)
    assert _outcomes(again) == {page_id: tool.ALREADY_DONE}
    assert client.writes == [f"delete {row.expected_slug}"]


async def test_real_archive_an_unapproved_delete_is_never_sent(live_archive):
    client, http = live_archive
    row, page_id = await _real_row(
        client,
        http,
        "unapproved",
        action="delete",
        target_gov_id="",
        needs_ryan="yes",
        confidence="medium",
    )
    report = _run([row], client, apply=True, allow_deletes=True)
    assert _outcomes(report) == {page_id: tool.SKIP_AWAITING}
    assert client.writes == [] and page_id in client.read_pages([page_id])


async def test_real_archive_an_unknown_government_halts_the_run(live_archive):
    """The Archive answers 400 for a gov_id it does not know. That is an
    unexpected answer, so the run stops and the next row is never tried."""
    client, http = live_archive
    bad, bad_id = await _real_row(
        client, http, "unknown", target_gov_id="us:place:0000000"
    )
    good, good_id = await _real_row(client, http, "after-unknown")
    report = _run([bad, good], client, apply=True)
    assert [r.outcome for r in report.results] == [tool.HALTED]
    assert "HTTP 400" in report.halted
    assert client.writes == []
    assert client.read_pages([good_id])[good_id]["gov_id"] != _GOV_ID


async def test_real_archive_the_wrong_token_halts_before_anything_is_read(live_archive):
    _, http = live_archive
    client = ArchiveClient("http://testserver", "not-the-token", http=http)
    report = _run([_rekey_row(1)], client, apply=True)
    assert report.results == [] and "HTTP 404" in report.halted
    assert client.writes == []


async def test_command_line_end_to_end_writes_a_log_and_never_prints_the_token(
    live_archive, monkeypatch, tmp_path, capsys
):
    client, http = live_archive
    row, page_id = await _real_row(client, http, "cli")
    sheet = tmp_path / "sheet.csv"
    with open(sheet, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=tool.WORKLIST_COLUMNS)
        writer.writeheader()
        writer.writerow(
            {
                "page_id": row.page_id,
                "action": "rekey",
                "target_gov_id": _GOV_ID,
                "expected_current_gov_id": row.expected_current_gov_id,
                "expected_slug": row.expected_slug,
                "confidence": "high",
                "needs_ryan": "no",
            }
        )
    monkeypatch.setenv("ARCHIVE_INGEST_TOKEN", _AUTH_TOKEN)
    monkeypatch.setattr(
        tool, "ArchiveClient", lambda base, token: ArchiveClient(base, token, http=http)
    )
    log_path = tmp_path / "log.csv"
    code = tool.main(
        [
            "run",
            str(sheet),
            "--apply",
            "--base-url",
            "http://testserver",
            "--log",
            str(log_path),
            "--pause-seconds",
            "0",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "Re-keyed | 1" in out and "APPLY" in out
    assert _AUTH_TOKEN not in out
    (line,) = list(csv.DictReader(open(log_path, newline="", encoding="utf-8")))
    assert (line["outcome"], line["after_gov_id"]) == (tool.REKEYED, _GOV_ID)


async def test_page_2504_path_a_repush_under_the_commission_name_moves_a_page_to_unresolved(
    live_archive,
):
    """The path recorded on the sheet for page 2504 (a Minnesota Public
    Utilities Commission meeting filed under Beltrami County, MN).

    Ryan decided the page moves to unresolved, the same state as page 5816
    (gov_id blank, jurisdiction "Minnesota Public Utilities Commission",
    confidence unresolved). `POST /internal/jurisdiction/override` cannot do
    that: it needs a registry id. And `backfill_gov_id.py` cannot: it
    recomputes from the STORED name, which is "Beltrami County, MN", and the
    resolver answers Beltrami County again (checked in the same file below).
    What does work is a re-resolve push whose jurisdiction is the commission's
    own name, which the Granicus adapter gives for the MediaPlayer.php?view_id=2
    address of the clip (checked live 2026-09-21 with repoint_page.py
    --dry-run) and NOT for the player/clip address.

    This drives that push through the real ingest route on the local SQLite
    Archive. The page first carries a synthetic government (a stand-in for
    Beltrami, so no test row lands on a Minnesota page); the second push has
    the commission's real name, no gov_id and no transcript, as a repoint of a
    Granicus page with no captions would.
    """
    client, http = live_archive
    headers = {"Authorization": f"Bearer {_AUTH_TOKEN}"}
    source = "https://wo934-puc.granicus.com/player/clip/2573"
    first = {
        "platform": "granicus",
        "source_url": source,
        "input_url_normalized": source,
        "title": "PUC Agenda Meeting on 2025-09-04 10:00 AM",
        "date": "2025-09-04",
        "jurisdiction": "Wo934 Default City, ZZ",
        "gov_id": _GOV_ID,
        "video_url": "https://example.com/video.m3u8",
        "video_format": "m3u8",
        "segments": [{"start": 0.0, "end": 1.0, "text": "Call to order"}],
        "transcript_language": "en",
    }
    reply = http.post("/internal/ingest", json=first, headers=headers)
    assert reply.status_code == 200, reply.text
    page_id = await _page_id(reply.json()["slug"])
    before = client.read_pages([page_id])[page_id]
    assert before["gov_id"] == _GOV_ID
    assert before["versions"][0]["segment_count"] == 1

    push = {
        "platform": "granicus",
        "source_url": source,
        "input_url_normalized": source,
        "title": "PUC Agenda Meeting on 2025-09-04 10:00 AM",
        "date": "2025-09-04",
        "jurisdiction": "Minnesota Public Utilities Commission",
        "video_url": "https://example.com/video.m3u8",
        "video_format": "m3u8",
        "segments": [],
    }
    reply = http.post("/internal/ingest", json=push, headers=headers)
    assert reply.status_code == 200, reply.text
    assert reply.json()["created"] is False

    after = client.read_pages([page_id])[page_id]
    # Page 5816's own state.
    assert not after["gov_id"]
    assert after["jurisdiction"] == "Minnesota Public Utilities Commission"
    assert after["jurisdiction_confidence"] == "unresolved"
    assert after["slug"] == before["slug"]
    # The transcript is untouched by a push that carries none.
    assert after["versions"][0]["segment_count"] == 1


def test_page_2504_the_backfill_path_would_leave_it_under_beltrami():
    """The other half of the reasoning above, on the real stored name: the
    resolver, given what `backfill_gov_id.py` feeds it for page 2504, answers
    Beltrami County again; given page 5816's stored name it stays unresolved."""
    from app.utils.gov_registry import resolve_government

    host = "minnesotapuc.granicus.com"
    page_2504 = resolve_government(
        "Beltrami County, MN", tenant_host=host, path="/player/clip/2573"
    )
    assert (page_2504.gov_id, page_2504.tier) == ("us:county:27007", "registry")
    page_5816 = resolve_government(
        "Minnesota Public Utilities Commission",
        tenant_host=host,
        path="/MediaPlayer.php?clip_id=2731&view_id=2",
    )
    assert page_5816.gov_id == "" and page_5816.tier == "unresolved"


def _ingest_youtube(http, video_id):
    """A YouTube page keyed to the synthetic government (a caller gov_id is a pin)."""
    payload = {
        "platform": "youtube",
        "source_url": f"https://www.youtube.com/watch?v={video_id}",
        "input_url_normalized": f"https://www.youtube.com/watch?v={video_id}",
        "external_id": f"youtube:{video_id}",
        "title": f"City Council Regular Meeting {video_id}",
        "date": "2026-08-01",
        "jurisdiction": "Wo934 Default City, ZZ",
        "gov_id": _GOV_ID,
        "video_url": f"https://www.youtube.com/embed/{video_id}",
        "video_format": "youtube",
        "segments": [],
    }
    reply = http.post(
        "/internal/ingest",
        json=payload,
        headers={"Authorization": f"Bearer {_AUTH_TOKEN}"},
    )
    assert reply.status_code == 200, reply.text
    return reply.json()["slug"]


async def test_real_archive_a_delete_waits_for_its_replacement_video_to_be_live(
    live_archive,
):
    """The Sebring and Malibu rule against the real Archive: the delete row is
    refused until another live page carries the replacement's video id under
    the same government. The tool finds it through the real page-list route."""
    client, http = live_archive
    old_slug = _ingest_youtube(http, "Wo934Gone01")
    old_id = await _page_id(old_slug)
    row = _row(
        page_id=str(old_id),
        action="delete",
        target_gov_id="",
        needs_ryan="yes",
        confidence="medium",
        ryan_decision="approve",
        expected_current_gov_id=_GOV_ID,
        expected_slug=old_slug,
        requires="video-gone:ryan-2026-09-21;replacement-video:Wo934Repl01",
    )

    before = _run([row], client, apply=True, allow_deletes=True)
    assert _outcomes(before) == {old_id: tool.REFUSED_REQUIRES}
    assert "ingest the replacement first" in before.results[0].detail
    assert client.writes == []
    assert old_id in client.read_pages([old_id])

    new_slug = _ingest_youtube(http, "Wo934Repl01")
    new_id = await _page_id(new_slug)
    after = _run([row], client, apply=True, allow_deletes=True)
    assert _outcomes(after) == {old_id: tool.DELETED}
    assert client.writes == [f"delete {old_slug}"]
    live = client.read_pages([old_id, new_id])
    assert old_id not in live and new_id in live


async def test_real_archive_the_page_list_read_finds_a_page_by_any_of_its_video_ids(
    live_archive,
):
    client, http = live_archive
    slug = _ingest_youtube(http, "Wo934Scan01")
    page_id = await _page_id(slug)
    found = client.pages_with_video("Wo934Scan01")
    assert [p["id"] for p in found] == [page_id]
    assert found[0]["gov_id"] == _GOV_ID
    assert client.pages_with_video("Wo934None01") == []
    # one read of the list serves every later question in the run
    calls = len(client.calls)
    client.pages_with_video("Wo934Scan01")
    assert len(client.calls) == calls
