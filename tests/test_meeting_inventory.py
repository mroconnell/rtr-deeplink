"""archive/utils/meeting_inventory.py + GET /internal/meeting-inventory
(+ /summary) -- WO-124. Row derivation is tested on a dict shaped exactly
like crud.list_pages_for_export()'s output, with REAL values copied from
the first production run (Yountville, CA, page 1, 2026-09-09) rather than
invented ones; the endpoint tests go through ingest against the shared
SQLite fixture, same pattern as tests/test_export_pages.py (find rows by
source_url_normalized, never assume the table is empty).
"""

import csv
import io

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud
from archive.utils.meeting_inventory import (
    COLUMNS,
    follows_city_st,
    inventory_row,
    names_match,
    rows_to_csv,
)

client = TestClient(archive.main.app)
AUTH = {"Authorization": "Bearer test-token"}

# Real export shape + real values (Yountville, CA -- us:place:0686930 is
# its real Census place id; the video really streams from Granicus even
# though the page is a Swagit page, which is what video_host_domain is
# for).
YOUNTVILLE = {
    "id": 1,
    "slug": "yountville-ca-2026-07-21-jul-21-2026-town-council-regular-meeting",
    "platform": "swagit",
    "external_id": "394093",
    "source_url_normalized": "https://yountvilleca.new.swagit.com/videos/394093",
    "title": "Jul 21, 2026 Town Council Regular Meeting",
    "date": "2026-07-21",
    "jurisdiction": "Yountville, CA",
    "meeting_body": None,
    "jurisdiction_confidence": "validated",
    "gov_id": "us:place:0686930",
    "gov_type": "municipality",
    "meeting_kind": None,
    "video_url": (
        "https://archive-stream.granicus.com/OnDemand/_definst_/mp4:swagitVideo/"
        "yountvilleca/5294f2f1-6b21-4b25-bea8-085e571bf3c9.mp4/playlist.m3u8"
    ),
    "video_format": "m3u8",
    "agenda_items": None,
    "video_warnings": None,
    "agenda_link": None,
    "packet_link": None,
    "best_effort": False,
    "created_at": "2026-08-09T02:11:40+00:00",
    "updated_at": "2026-08-09T02:11:40+00:00",
    "versions": [
        {
            "id": 1,
            "language": "en",
            "source": "transcribed",
            "is_default": True,
            "segment_count": 1390,
            "transcript_warnings": [],
            "content_hash": "not-the-empty-hash",
            "created_at": "2026-08-09T02:11:40+00:00",
        }
    ],
}


def test_inventory_row_reports_stored_and_derived_values_without_guessing():
    row = inventory_row(YOUNTVILLE)
    assert list(row) == list(COLUMNS)
    assert row["stored_jurisdiction"] == "Yountville, CA"
    assert row["page_display_name"] == "Yountville, CA"
    assert row["gov_display_name"] == "Yountville, CA"
    assert row["names_match"] == "yes"
    assert row["follows_city_st"] == "yes"
    # Stored column only: the title says "Town Council" but nothing here
    # reads it into meeting_body.
    assert row["meeting_body"] == ""
    assert row["has_video"] == "yes"
    assert row["has_transcript"] == "yes"
    assert row["transcript_source"] == "transcribed"
    assert row["transcript_segments"] == 1390
    assert row["outcome"] == "Transcript (English)"
    assert row["page_platform"] == "Swagit"
    assert row["page_platform_by_url"] == "swagit"
    assert row["video_platform"] == "Swagit"
    assert row["video_host_domain"] == "archive-stream.granicus.com"
    assert row["best_effort_resolve"] == "no"
    assert row["archive_url"] == (
        "https://redtaperecordings.com/m/"
        "yountville-ca-2026-07-21-jul-21-2026-town-council-regular-meeting"
    )


def test_inventory_row_without_video_or_versions():
    page = {**YOUNTVILLE, "video_url": None, "video_format": None, "versions": []}
    row = inventory_row(page)
    assert row["has_video"] == "no"
    assert row["video_platform"] == ""
    assert row["video_host_domain"] == ""
    assert row["has_transcript"] == "no"
    assert row["transcript_source"] == ""
    assert row["transcript_segments"] == 0
    assert row["outcome"] == "No video"


def test_names_match_distinguishes_prefix_only_from_wrong():
    assert names_match("Napa, CA", "us:place:0650258", "Napa, CA") == "yes"
    assert names_match("City of Napa, CA", "us:place:0650258", "Napa, CA") == (
        "prefix only"
    )
    assert names_match("Duncanville, TX", "us:place:4821628", "Dallas, TX") == "no"
    assert names_match("Anything", None, "") == "no gov_id"
    assert names_match("Anything", "rtr:us:tx:minted-slug", "") == (
        "gov_id not in registry"
    )


def test_follows_city_st_accepts_canadian_marker_and_rejects_bare_names():
    assert follows_city_st("Medicine Hat, AB (Canada)") == "yes"
    assert follows_city_st("Beaufort County, SC") == "yes"
    assert follows_city_st("Kansas City") == "no"
    assert follows_city_st("Napa, California") == "no"
    assert follows_city_st("") == "no"


def test_rows_to_csv_uses_the_column_order():
    text = rows_to_csv([inventory_row(YOUNTVILLE)])
    reader = csv.DictReader(io.StringIO(text))
    assert reader.fieldnames == list(COLUMNS)
    (row,) = list(reader)
    assert row["video_host_domain"] == "archive-stream.granicus.com"


def _payload(external_id: str, source_url: str) -> dict:
    return {
        "platform": "granicus",
        "source_url": source_url,
        "external_id": external_id,
        "title": "Inventory Test Meeting",
        "date": "2026-09-01",
        # No ", ST" suffix on purpose -- see tests/test_export_pages.py's
        # note on tests/test_state_pages.py's per-state counts.
        "jurisdiction": "Inventory Test Authority",
        "video_url": "https://example.com/inventory.m3u8",
        "video_format": "m3u8",
        "segments": [{"start": 0.0, "end": 3.0, "text": "Call to order."}],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }


def _walk_json(limit: int) -> list[dict]:
    rows, after_id = [], 0
    while True:
        r = client.get(
            "/internal/meeting-inventory",
            params={"after_id": after_id, "limit": limit},
            headers=AUTH,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        rows.extend(body["rows"])
        if body["next_after_id"] is None:
            return rows
        assert body["next_after_id"] > after_id
        after_id = body["next_after_id"]


def test_inventory_endpoints_require_token_and_hide_themselves():
    assert client.get("/internal/meeting-inventory").status_code == 404
    assert client.get("/internal/meeting-inventory/summary").status_code == 404


async def test_inventory_endpoint_returns_rows_as_json_and_csv():
    url = "https://example.granicus.com/player/clip/inventory-1"
    await crud.ingest_resolution(_payload("inventory:1", url), url)

    rows = _walk_json(limit=500)
    (row,) = [r for r in rows if r["source_url"] == url]
    assert row["stored_jurisdiction"] == "Inventory Test Authority"
    assert row["has_video"] == "yes"
    assert row["has_transcript"] == "yes"
    assert row["page_platform"] == "Granicus"
    assert row["video_host_domain"] == "example.com"
    assert row["archive_url"].startswith("https://redtaperecordings.com/m/")

    # CSV: same rows, same columns, cursor in the header.
    r = client.get(
        "/internal/meeting-inventory",
        params={"after_id": row["page_id"] - 1, "limit": 1, "format": "csv"},
        headers=AUTH,
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["x-next-after-id"] == str(row["page_id"])
    parsed = list(csv.DictReader(io.StringIO(r.text)))
    assert parsed[0]["source_url"] == url
    assert list(parsed[0]) == list(COLUMNS)


async def test_inventory_summary_counts_missing_fields():
    url = "https://example.granicus.com/player/clip/inventory-summary"
    payload = _payload("inventory:summary", url)
    payload["date"] = None
    await crud.ingest_resolution(payload, url)

    before = client.get("/internal/meeting-inventory/summary", headers=AUTH).json()
    rows = _walk_json(limit=500)
    # The summary is a SQL aggregate and the rows are Python-derived from
    # the same read path; they must agree on every count.
    assert before["total_pages"] == len(rows)
    assert before["missing_date"] == sum(r["meeting_date"] == "" for r in rows)
    assert before["missing_meeting_body"] == sum(r["meeting_body"] == "" for r in rows)
    assert before["missing_gov_id"] == sum(r["gov_id"] == "" for r in rows)
    assert before["no_video"] == sum(r["has_video"] == "no" for r in rows)
    assert before["no_transcript"] == sum(r["has_transcript"] == "no" for r in rows)
    assert before["missing_date"] >= 1
