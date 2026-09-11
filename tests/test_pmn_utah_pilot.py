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
