"""A4 (WO-1960): a time-corrected copy of a page's source captions.

Synthetic segments; the shape (start/end/text/speaker) is the real one the
export returns (Port Moody BC page 4143, read 2026-10-18). The real offsets
come from reports/wo-a4_caption_audit_2026-10-16.md (Port Moody: captions
244 s later than the audio, constant).
"""

import copy

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud

client = TestClient(archive.main.app)

SEGS = [
    {
        "start": 247.3,
        "end": 249.0,
        "text": "Okay, it's seven o'clock.",
        "speaker": None,
    },
    {
        "start": 250.0,
        "end": 252.5,
        "text": "We're going to call this meeting",
        "speaker": None,
    },
    {"start": 253.0, "end": 256.0, "text": "to order.", "speaker": None},
]


async def _page(external_id: str, segments=None) -> tuple[str, int]:
    url = f"https://example.com/time-corrected/{external_id}"
    r = await crud.ingest_resolution(
        {
            "platform": "escribe",
            "source_url": url,
            "external_id": external_id,
            "title": "Regular Council",
            "date": "2026-07-28",
            "jurisdiction": "Port Moody, BC",
            "video_url": "https://example.com/v.m3u8",
            "video_format": "m3u8",
            "segments": copy.deepcopy(segments or SEGS),
            "agenda_items": [],
            "transcript_language": "en",
            "transcript_warnings": [],
        },
        url,
    )
    page = await crud.get_page_by_slug(r["slug"])
    default = next(v for v in page["versions"] if v["is_default"])
    return r["slug"], default["id"]


def _shifted(seconds: float) -> list:
    out = copy.deepcopy(SEGS)
    for s in out:
        s["start"] = round(s["start"] - seconds, 3)
        s["end"] = round(s["end"] - seconds, 3)
    return out


async def test_dry_run_reports_and_writes_nothing():
    slug, base = await _page("tc-dry")
    r = await crud.add_time_corrected_version(
        slug=slug, base_version_id=base, segments=_shifted(244.0), note="", dry_run=True
    )
    assert r["segments_moved"] == 3 and r["largest_shift_seconds"] == 244.0
    page = await crud.get_page_by_slug(slug)
    assert len(page["versions"]) == 1


async def test_apply_adds_a_promoted_version_and_keeps_the_original():
    slug, base = await _page("tc-apply")
    r = await crud.add_time_corrected_version(
        slug=slug,
        base_version_id=base,
        segments=_shifted(244.0),
        note="Times corrected to match the video.",
        dry_run=False,
    )
    page = await crud.get_page_by_slug(slug)
    by_id = {v["id"]: v for v in page["versions"]}
    new = by_id[r["version_id"]]
    assert new["is_default"] and new["source"] == "aligned"
    assert new["segments"][0]["start"] == 3.3
    assert "Times corrected to match the video." in new["transcript_warnings"]
    assert not by_id[base]["is_default"]
    assert by_id[base]["segments"][0]["start"] == 247.3
    html = client.get(f"/m/{slug}").text
    assert "time-corrected" in html


async def test_reingest_of_the_source_captions_does_not_undo_it():
    slug, base = await _page("tc-reingest")
    r = await crud.add_time_corrected_version(
        slug=slug,
        base_version_id=base,
        segments=_shifted(244.0),
        note="",
        dry_run=False,
    )
    await _page("tc-reingest")  # the same source captions again
    page = await crud.get_page_by_slug(slug)
    assert len(page["versions"]) == 2
    default = next(v for v in page["versions"] if v["is_default"])
    assert default["id"] == r["version_id"]


async def test_refuses_any_text_or_field_change():
    slug, base = await _page("tc-text")
    segs = _shifted(10.0)
    segs[1]["text"] = "We are going to call this meeting"
    r = await crud.add_time_corrected_version(
        slug=slug, base_version_id=base, segments=segs, note="", dry_run=False
    )
    assert r == {"error": "segment_changed", "index": 1}
    segs = _shifted(10.0)
    segs[2]["speaker"] = "Mayor"
    r = await crud.add_time_corrected_version(
        slug=slug, base_version_id=base, segments=segs, note="", dry_run=False
    )
    assert r["error"] == "segment_changed"


async def test_refuses_count_change_bad_times_huge_shifts_and_no_change():
    slug, base = await _page("tc-refuse")

    async def call(segs):
        return await crud.add_time_corrected_version(
            slug=slug, base_version_id=base, segments=segs, note="", dry_run=False
        )

    assert (await call(_shifted(5.0)[:2]))["error"] == "segment_count_differs"
    bad = _shifted(5.0)
    bad[0]["start"] = -1
    assert (await call(bad))["error"] == "bad_time"
    assert (await call(_shifted(-4000.0)))["error"] == "shift_too_large"
    assert (await call(copy.deepcopy(SEGS)))["error"] == "nothing_moved"
    page = await crud.get_page_by_slug(slug)
    assert len(page["versions"]) == 1


async def test_another_pages_version_is_not_found():
    slug_a, base_a = await _page("tc-own-a")
    slug_b, _ = await _page("tc-own-b")
    assert (
        await crud.add_time_corrected_version(
            slug=slug_b, base_version_id=base_a, segments=_shifted(5.0), note=""
        )
        is None
    )


def test_route_needs_the_token():
    r = client.post(
        "/internal/transcript-version/add-time-corrected",
        json={"slug": "x", "base_version_id": 1, "segments": []},
    )
    assert r.status_code == 404
