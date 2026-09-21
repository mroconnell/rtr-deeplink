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
EXPORT = Path("/tmp/rtr_meeting_inventory/meeting_inventory.csv")

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


def test_only_page_6114_is_approved_to_delete():
    """Ryan approved deleting page 6114 on 2026-09-21 and nothing else. A new
    approval must be a deliberate edit of this test, so it is reviewed."""
    approved = {r.page_id for r in _sheet_rows() if r.approved}
    assert approved == {6114}
    (row,) = [r for r in _sheet_rows() if r.page_id == 6114]
    assert row.action == "delete"


def test_the_gone_video_group_is_never_ready_to_delete_except_6114():
    """Pages 6906 and 7086 wait for a checked status file; 7086 also waits for
    its replacement page. None is approved."""
    by_id = {r.page_id: r for r in _sheet_rows()}
    for page_id in (6906, 7086):
        row = by_id[page_id]
        assert row.action == "delete"
        assert row.needs_ryan and not row.approved
        assert ("video-gone", "") in row.requires
    assert ("replacement-page", "") in by_id[7086].requires


def test_deletes_always_wait_for_ryan_and_no_rekey_runs_without_evidence():
    for row in _sheet_rows():
        if row.action == "delete":
            assert row.needs_ryan, row.origin
        if not row.needs_ryan:
            assert row.confidence == "high", row.origin
            assert row.action == "rekey" and row.target_gov_id, row.origin


def test_rows_needing_a_mint_have_no_target_and_wait_for_ryan():
    """A blank target is a finding, not a gap to fill from a guess."""
    by_id = {r.page_id: r for r in _sheet_rows()}
    for page_id in (5945, 10852, 3453, 2504, 645, 2004, 5301):
        assert by_id[page_id].target_gov_id == ""
        assert by_id[page_id].needs_ryan


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


@pytest.mark.skipif(
    not EXPORT.exists(), reason="the local 2026-09-21 export is not here"
)
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
        ({"requires": "replacement-page:abc"}, "unknown condition"),
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
    tokens, problems = parse_requires("video-gone; replacement-page:12")
    assert tokens == [("video-gone", ""), ("replacement-page", "12")] and not problems
    tokens, problems = parse_requires("replacement-page:")
    assert tokens == [("replacement-page", "")] and not problems
    assert parse_requires("")[0] == []


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


def test_a_replacement_page_must_exist_and_share_the_government():
    status = _status(page_id=1)
    blank = _gone_delete_row(1, requires="video-gone;replacement-page:")
    missing = _gone_delete_row(1, requires="video-gone;replacement-page:50")
    good = _gone_delete_row(1, requires="video-gone;replacement-page:51")
    other_gov = _gone_delete_row(1, requires="video-gone;replacement-page:52")

    def fresh():
        return FakeClient([_yt_page(1), _page(51), _page(52, gov="us:place:9999999")])

    for row, expected in [
        (blank, tool.REFUSED_REQUIRES),
        (missing, tool.REFUSED_REQUIRES),
        (other_gov, tool.REFUSED_REQUIRES),
        (good, tool.DELETED),
    ]:
        report = _run([row], fresh(), apply=True, allow_deletes=True, status=status)
        assert _outcomes(report) == {1: expected}, row.requires


def test_the_malibu_shape_page_7086_cannot_be_deleted_by_its_committed_row():
    """The real 7086 row, run against a stand-in page: with a fresh 'deleted'
    check but no replacement page id, and even with Ryan's approve, it is refused."""
    (row,) = [r for r in _sheet_rows() if r.page_id == 7086]
    row.ryan_decision = "approve"  # pretend Ryan approved, to prove the second lock
    page = _yt_page(
        7086,
        video_id="JGHPsOlz7wI",
        gov=row.expected_current_gov_id,
        slug=row.expected_slug,
    )
    report = _run(
        [row],
        FakeClient([page]),
        apply=True,
        allow_deletes=True,
        status=_status(page_id=7086, video_id="JGHPsOlz7wI"),
    )
    assert _outcomes(report) == {7086: tool.REFUSED_REQUIRES}
    assert "replacement" in report.results[0].detail


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
