"""WO-934: tests for scripts/wrong_page_screen.py, the repeatable form of the
2026-09-06 full-corpus screen.

The rule cases are REAL: each title, government type and expected reason
list is a row of `rtr-business/research/archive_audit/categorized/*.csv`
(the audit's own output for the 5,857-page run), so the port is checked
against what the original script really said. The controls at the end are
SYNTHETIC and marked so.
"""

import csv
from pathlib import Path

import pytest
from conftest import wrong_page_export_2026_09_21

from scripts import wrong_page_screen as screen

REPO_ROOT = Path(__file__).resolve().parent.parent
SHEET = REPO_ROOT / "reports" / "wrong_page_worklist.csv"
EXPORT, EXPORT_SKIP_REASON = wrong_page_export_2026_09_21()


@pytest.mark.parametrize(
    "title, gov_type, expected",
    [
        # audit page 291, confirmed wrong government type
        (
            "DJUSD Board of Education",
            "municipality",
            ["non_school_gov_type_but_school_body_in_title"],
        ),
        # audit page 1723, a talk show
        (
            "STEAM Episode 7 Fish's Garden",
            "other",
            ["no_meeting_keyword", "explicit_non_meeting_marker"],
        ),
        # audit page 4703, a news-recap segment that still says "Council" and "Meeting"
        (
            "Mar 12, 2010 CityView 3/12 Episode (Council Update from 3/11 Meeting)",
            "municipality",
            ["explicit_non_meeting_marker"],
        ),
        # audit page 1116, a planning commission filed under a school district
        (
            "8/6/25 State College Borough Planning Commission",
            "school_district",
            ["school_district_gov_type_but_non_school_body_in_title"],
        ),
        # audit page 3520, no meeting word AND a school body under a city
        (
            "Hopkins School District",
            "municipality",
            ["no_meeting_keyword", "non_school_gov_type_but_school_body_in_title"],
        ),
        # audit page 4708, a year-in-review reel
        (
            "Year in Review 2025",
            "municipality",
            ["no_meeting_keyword", "explicit_non_meeting_marker"],
        ),
    ],
)
def test_the_port_gives_the_audits_own_reasons(title, gov_type, expected):
    assert screen.screen_reasons(title, gov_type) == expected


def test_an_ordinary_meeting_is_not_flagged():
    # SYNTHETIC control: a plain title under a city.
    assert screen.screen_reasons("City Council Regular Meeting", "municipality") == []
    # SYNTHETIC control: a school board under a school district.
    assert screen.screen_reasons("School Board Meeting", "school_district") == []


def _page(page_id, title, gov_type):
    return {
        "id": str(page_id),
        "slug": f"s{page_id}",
        "title": title,
        "jurisdiction": "Somewhere, ZZ",
        "gov_type": gov_type,
        "platform": "Granicus",
        "source_url": "https://example.test/x",
    }


def test_screen_marks_flagged_pages_that_are_on_the_worklist():
    pages = [
        _page(1, "DJUSD Board of Education", "municipality"),
        _page(2, "STEAM Episode 7 Fish's Garden", "other"),
        _page(3, "City Council Regular Meeting", "municipality"),
    ]
    scanned, flagged = screen.screen(pages, {"1": "rekey"})
    assert scanned == 3
    assert [(r["page_id"], r["on_worklist"]) for r in flagged] == [
        ("1", "yes (rekey)"),
        ("2", "no"),
    ]
    text = "\n".join(screen.summary_lines(scanned, flagged))
    assert "Pages flagged: 2 (66.7%)" in text
    assert "Already a row on the worklist | 1" in text
    assert "Not on the worklist (still waiting for a person) | 1" in text


def test_the_archive_reader_pages_through_the_export_and_stops():
    """SYNTHETIC stand-in for the export route's keyset pages."""

    class Reply:
        status_code = 200

        def __init__(self, body):
            self._body = body

        def json(self):
            return self._body

    class Http:
        def __init__(self):
            self.asked = []

        def get(self, path, params, headers):
            self.asked.append((path, params["after_id"], params["limit"]))
            assert headers["Authorization"] == "Bearer t"
            if params["after_id"] == 0:
                return Reply(
                    {
                        "pages": [
                            {"id": 1, "slug": "a", "title": "T1", "gov_type": "county"},
                            {"id": 2, "slug": "b", "title": "T2", "gov_type": "county"},
                        ],
                        "next_after_id": 2,
                    }
                )
            return Reply(
                {
                    "pages": [{"id": 3, "slug": "c", "title": "T3", "gov_type": ""}],
                    "next_after_id": None,
                }
            )

    http = Http()
    pages = list(screen.pages_from_archive("http://x", "t", client=http))
    assert [p["id"] for p in pages] == ["1", "2", "3"]
    assert http.asked == [
        ("/internal/export/pages", 0, 500),
        ("/internal/export/pages", 2, 500),
    ]


def test_from_archive_needs_a_token(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("ARCHIVE_INGEST_TOKEN", raising=False)
    code = screen.main(["--from-archive", "--out", str(tmp_path / "o.csv")])
    assert code == 1 and "ARCHIVE_INGEST_TOKEN" in capsys.readouterr().err


@pytest.mark.skipif(EXPORT is None, reason=EXPORT_SKIP_REASON)
def test_the_screen_runs_on_the_real_export_and_finds_the_worklist_pages(tmp_path):
    """Real data: the 23 wrong-type school-board pages the audit found are
    all still flagged today, and every one of them is a row of the sheet."""
    out = tmp_path / "flagged.csv"
    code = screen.main(
        [
            "--from-inventory",
            str(EXPORT),
            "--worklist",
            str(SHEET),
            "--out",
            str(out),
        ]
    )
    assert code == 0
    flagged = {
        r["page_id"]: r for r in csv.DictReader(open(out, newline="", encoding="utf-8"))
    }
    audit_23 = {
        "291",
        "615",
        "747",
        "1343",
        "1414",
        "1689",
        "2234",
        "2610",
        "2899",
        "3367",
        "3453",
        "3520",
        "3521",
        "3642",
        "3643",
        "3645",
        "3787",
        "3861",
        "3885",
        "4179",
        "5252",
        "5662",
    }  # the audit's 23 minus 2257, the joint meeting left off the sheet on purpose
    for page_id in audit_23:
        assert page_id in flagged, page_id
        assert flagged[page_id]["on_worklist"].startswith("yes"), page_id
