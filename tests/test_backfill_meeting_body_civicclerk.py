"""WO-1977: the CivicClerk meeting_body refill reads the same field, by the
same rule, as the adapter. Event records are real captured fixtures."""

import json
from pathlib import Path

from scripts.backfill_meeting_body_civicclerk import body_from_event, event_api_url

FIX = Path(__file__).parent / "fixtures" / "civicclerk"


def _event(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def test_event_api_url_matches_the_adapter():
    assert (
        event_api_url("https://anacorteswa.portal.civicclerk.com/event/1452/media")
        == "https://anacorteswa.api.civicclerk.com/v1/Events/1452"
    )
    assert (
        event_api_url("https://stjosephmo.portal.civicclerk.com/event/1310/overview")
        == "https://stjosephmo.api.civicclerk.com/v1/Events/1310"
    )


def test_event_api_url_refuses_non_event_pages():
    assert event_api_url("https://anacorteswa.portal.civicclerk.com/") is None
    assert event_api_url("https://www.youtube.com/watch?v=abc") is None


def test_body_from_real_events():
    # Anacortes WA event 1452, captured 2026-10-17 (PR #2095).
    assert body_from_event(_event("anacorteswa_event1452_2026-10-17.json")) == (
        "City Council",
        "filled",
    )
    # Claycomo MO event 4967.
    assert body_from_event(_event("claycomo_event4967.json"))[0] == (
        "Board of County Commission"
    )


def test_body_skips_blank_and_general_category():
    # Synthetic variants of a real record's shape: only categoryName changes.
    event = _event("clovisca_event17.json")
    assert body_from_event({**event, "categoryName": "  "}) == (None, "no_category")
    assert body_from_event({**event, "categoryName": "General"}) == (
        None,
        "non_informative_category",
    )


def test_skip_list_matches_the_adapter():
    from app.platforms.civicclerk import _NON_INFORMATIVE_CATEGORY_NAMES
    from scripts.backfill_meeting_body_civicclerk import (
        NON_INFORMATIVE_CATEGORY_NAMES,
    )

    assert NON_INFORMATIVE_CATEGORY_NAMES == _NON_INFORMATIVE_CATEGORY_NAMES


def test_runs_without_yt_dlp():
    # The Archive service does not install yt_dlp, and this script runs on
    # its shell (2026-10-17: ModuleNotFoundError via app.platforms.civicclerk).
    import subprocess
    import sys

    code = (
        "import sys; sys.modules['yt_dlp'] = None\n"
        "from scripts.backfill_meeting_body_civicclerk import body_from_event\n"
        "import archive.db.engine, archive.db.models\n"
        "assert body_from_event({'categoryName': 'City Council'}) == "
        "('City Council', 'filled')\n"
        "assert 'app.platforms.civicclerk' not in sys.modules\n"
    )
    root = Path(__file__).resolve().parent.parent
    r = subprocess.run(
        [sys.executable, "-c", code], cwd=root, capture_output=True, text=True
    )
    assert r.returncode == 0, r.stderr


def test_body_unescapes_html_entities():
    # Synthetic record. The escaped name itself is real: the 2026-10-18
    # dry run on the Archive found 5 pages whose categoryName was
    # "Planning &amp; Zoning Commission". Which tenant sent it is not
    # recorded here.
    event = {"categoryName": "Planning &amp; Zoning Commission"}
    assert body_from_event(event) == ("Planning & Zoning Commission", "filled")
