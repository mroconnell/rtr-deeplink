"""scripts/pmn_utah_pilot.py: the results parser against the search
page's own form-POST shape (real page, fetched 2026-09-11 while the JSON
endpoint was down), and the outage detector's spelling."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import pmn_utah_pilot as pmn  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "pmn_search_form_results_provo.html"


def test_parse_results_table_reads_the_form_post_shape():
    notices = pmn._parse_results_table(FIXTURE.read_text())
    assert len(notices) == 3  # 4 <tr>: one header row, three notices
    assert all(n.entity == "Provo" for n in notices)
    assert all(
        n.notice_url.startswith("https://www.utah.gov/pmn/sitemap/notice/")
        for n in notices
    )
    council = [n for n in notices if "Council" in n.public_body]
    assert council, [n.public_body for n in notices]
    cats = {cat for n in council for _, _, cat in n.attachments}
    assert "Audio Recording" in cats
    audio = [
        u for n in council for _, u, cat in n.attachments if cat == "Audio Recording"
    ]
    assert audio and audio[0].endswith(".m4a")


def test_parse_results_table_still_reads_the_json_fragment_id():
    html = FIXTURE.read_text().replace(
        'id="browseResults-table"', 'id="searchResultsTable"'
    )
    assert len(pmn._parse_results_table(html)) == 3


def test_parse_results_table_returns_nothing_for_the_outage_page():
    assert (
        pmn._parse_results_table("<html><title>Techincal Difficulties</title></html>")
        == []
    )


async def test_enumerate_notices_falls_back_to_the_form_post_after_an_outage_page(
    monkeypatch, capsys
):
    """WO-297: the pilot's own search loop (enumerate_notices, via
    fetch_search_page) used to treat PMN's outage page the same as "no
    more rows" -- both parse to an empty notices list -- and would just
    stop enumerating instead of switching to the form-POST path that kept
    working through the same real 2026-09-11 outage. This exercises the
    fallback with no network: fetch_search_page raises PMNOutageError once
    (simulating the outage), and enumerate_notices should switch to
    fetch_search_form_page for that page and stay on it for the rest of
    the run."""
    calls = {"json": 0, "form": 0}

    async def fake_fetch_csrf(session):
        return "tok", "X-CSRF-TOKEN"

    async def fake_fetch_search_page(
        session, csrf_token, csrf_header, start_date, end_date, starting_row
    ):
        calls["json"] += 1
        raise pmn.PMNOutageError("outage")

    async def fake_fetch_form_csrf(session):
        return "form-tok"

    async def fake_fetch_search_form_page(
        session, form_csrf, entity_name, start_date, end_date, starting_row
    ):
        calls["form"] += 1
        assert form_csrf == "form-tok"
        assert entity_name == ""  # unfiltered, all-entities enumeration
        assert start_date == "2026-09-01"  # ISO straight through, no reformatting
        assert end_date == "2026-09-08"
        assert starting_row == 0  # only one page's worth of fixture rows
        return pmn._parse_results_table(FIXTURE.read_text())

    monkeypatch.setattr(pmn, "fetch_csrf", fake_fetch_csrf)
    monkeypatch.setattr(pmn, "fetch_search_page", fake_fetch_search_page)
    monkeypatch.setattr(pmn, "fetch_form_csrf", fake_fetch_form_csrf)
    monkeypatch.setattr(pmn, "fetch_search_form_page", fake_fetch_search_form_page)

    notices = await pmn.enumerate_notices(None, "2026-09-01", "2026-09-08")

    assert len(notices) == 3
    assert calls["json"] == 1  # tried the JSON endpoint once, hit the outage
    # A fixture page short of PAGE_SIZE (3 rows) ends the loop on its own,
    # same as a genuine last page would -- no second form-POST call needed.
    assert calls["form"] == 1
    out = capsys.readouterr().out
    assert out.count("switching to the search page's own form POST") == 1


async def test_enumerate_notices_stays_on_the_form_post_for_later_pages_too(
    monkeypatch,
):
    """Once the outage switch happens on page 1, page 2+ must go straight
    to fetch_search_form_page -- never retry the (still-down) JSON
    endpoint. Page 1 returns a full PAGE_SIZE page (so the loop doesn't
    stop after just one page); page 2 returns a short page to end it."""
    calls = {"json": 0, "form_starting_rows": []}

    async def fake_fetch_csrf(session):
        return "tok", "X-CSRF-TOKEN"

    async def fake_fetch_search_page(
        session, csrf_token, csrf_header, start_date, end_date, starting_row
    ):
        calls["json"] += 1
        raise pmn.PMNOutageError("outage")

    async def fake_fetch_form_csrf(session):
        return "form-tok"

    async def fake_fetch_search_form_page(
        session, form_csrf, entity_name, start_date, end_date, starting_row
    ):
        calls["form_starting_rows"].append(starting_row)
        if starting_row == 0:
            return [
                pmn.Notice(
                    f"https://www.utah.gov/pmn/sitemap/notice/{i}.html",
                    f"Meeting {i} Council Meeting",
                    "Sep 1, 2026",
                    "Council",
                    "Provo",
                )
                for i in range(pmn.PAGE_SIZE)
            ]
        return pmn._parse_results_table(FIXTURE.read_text())  # 3 rows, ends the loop

    monkeypatch.setattr(pmn, "fetch_csrf", fake_fetch_csrf)
    monkeypatch.setattr(pmn, "fetch_search_page", fake_fetch_search_page)
    monkeypatch.setattr(pmn, "fetch_form_csrf", fake_fetch_form_csrf)
    monkeypatch.setattr(pmn, "fetch_search_form_page", fake_fetch_search_form_page)

    notices = await pmn.enumerate_notices(None, "2026-09-01", "2026-09-08")

    assert len(notices) == pmn.PAGE_SIZE + 3
    assert calls["json"] == 1  # never retried after the switch
    assert calls["form_starting_rows"] == [0, pmn.PAGE_SIZE]
