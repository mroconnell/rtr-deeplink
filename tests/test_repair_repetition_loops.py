"""Tests for scripts/repair_repetition_loops.py's pure detection logic,
against the exact real WO-36 fixtures already used by
tests/test_worker_segment_utils.py (not invented text -- see
tests/fixtures/hallucination_runs/README.md for provenance), plus a
focused check that its findings apply cleanly through the shared
POST /internal/transcript-version/drop-segments route (full HTTP-level
coverage of that route itself lives in
tests/test_repair_seam_duplication.py; this file only confirms this
script's own findings are consumable by it).
"""

import hashlib
import re
from pathlib import Path

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud
from archive.db.engine import async_session
from archive.db.models import TranscriptVersion
from archive.utils.transcript_export import to_srt
from scripts.repair_repetition_loops import find_repetition_loops

client = TestClient(archive.main.app)

_FIXTURES = Path(__file__).parent / "fixtures" / "hallucination_runs"
_SRT_TIMING_RE = re.compile(
    r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)"
)


def _load_srt_fixture(name: str) -> list:
    """Duplicated from tests/test_worker_segment_utils.py's own loader --
    small and pure enough that importing across test files isn't worth
    the coupling."""
    blocks = re.split(
        r"\n\s*\n", (_FIXTURES / name).read_text(encoding="utf-8").strip()
    )
    segments = []
    for block in blocks:
        lines = [line for line in block.splitlines() if line.strip()]
        if len(lines) < 3:
            continue
        match = _SRT_TIMING_RE.match(lines[1])
        assert match, lines[1]
        h1, m1, s1, ms1, h2, m2, s2, ms2 = (int(g) for g in match.groups())
        segments.append(
            {
                "start": h1 * 3600 + m1 * 60 + s1 + ms1 / 1000,
                "end": h2 * 3600 + m2 * 60 + s2 + ms2 / 1000,
                "text": " ".join(lines[2:]),
            }
        )
    assert segments, name
    return segments


# --- find_repetition_loops() -- pure logic, real fixtures -----------------


def test_finds_the_real_haines_city_tiled_block():
    segments = _load_srt_fixture("loop_haines_city_fl.srt")
    findings = find_repetition_loops(segments)

    assert len(findings) == 1
    finding = findings[0]
    # Real, confirmed shape: a lone "You're in the process." at index 6 is
    # broken by a different real sentence at index 7, so the actual
    # maximal run is indices 8-13 (6 consecutive), not 6-13.
    assert finding["run_start_index"] == 8
    assert finding["run_length"] == 6
    assert finding["kept_segment_index"] == 8
    assert finding["drop_segment_indices"] == [9, 10, 11, 12, 13]
    # The isolated cue at index 6 and the real interrupting sentence at
    # index 7 must never be touched -- only the run itself.
    assert 6 not in finding["drop_segment_indices"]
    assert 7 not in finding["drop_segment_indices"]


def test_finds_the_real_halifax_recess_long_sparse_run():
    """The OTHER rule (long sparse run, not tiled block) -- 28 consecutive
    "Thank you." cues on a 30s cadence across a real dinner recess. This
    is the case BACKLOG.md once wrongly called a false positive (see
    tests/test_worker_segment_utils.py's own regression test for that
    correction) -- confirming this script's detection agrees with the
    corrected classification, not the original wrong one."""
    segments = _load_srt_fixture("recess_halifax_ns.srt")
    findings = find_repetition_loops(segments)

    assert len(findings) == 1
    finding = findings[0]
    assert finding["run_start_index"] == 8
    assert finding["run_length"] == 28
    assert finding["kept_segment_index"] == 8
    assert finding["drop_segment_indices"] == list(range(9, 36))


def test_no_false_positive_on_real_decoder_stutters_and_roll_calls():
    """Real speech that must never be collapsed -- genuine stutters
    (words really said, then duplicated, with real pauses intact) and
    real roll calls. Two of these have runs longer than Haines City's
    flagged 6 (8 and 9), which is exactly why run length alone can't be
    the rule -- these must still score clean."""
    for name in (
        "stutter_troy_nh.srt",
        "stutter_creve_coeur_mo.srt",
        "stutter_blackford_county_in.srt",
        "rollcall_coweta_county_ga.srt",
        "rollcall_bentonville_ar.srt",
    ):
        segments = _load_srt_fixture(name)
        assert find_repetition_loops(segments) == [], name


def test_empty_and_short_input_are_safe():
    assert find_repetition_loops([]) == []
    assert find_repetition_loops([{"start": 0.0, "end": 1.0, "text": "Hello."}]) == []


# --- Findings apply cleanly through the shared drop-segments route -------


def _srt_hash(segments: list[dict]) -> str:
    return hashlib.sha256(to_srt(segments).encode("utf-8")).hexdigest()


async def test_a_real_loop_finding_applies_cleanly_through_drop_segments():
    segments = _load_srt_fixture("loop_haines_city_fl.srt")
    url = "https://example.granicus.com/player/clip/repetition-loop-apply"
    await crud.ingest_resolution(
        {
            "platform": "granicus",
            "source_url": url,
            "external_id": "granicus:repetition-loop-apply",
            "title": "Test Meeting",
            "date": "2026-01-01",
            "jurisdiction": "City of Test",
            "video_url": "https://example.com/v.m3u8",
            "video_format": "m3u8",
            "segments": segments,
            "agenda_items": [],
            "transcript_language": "en",
            "transcript_warnings": [],
        },
        url,
    )
    slug = (await crud.lookup_page_for_url(url))["slug"]

    finding = find_repetition_loops(segments)[0]
    response = client.post(
        "/internal/transcript-version/drop-segments",
        json={
            "slug": slug,
            "expected_srt_hash": _srt_hash(segments),
            "drop_segment_indices": finding["drop_segment_indices"],
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["dropped"] == 5
    assert body["kept"] == len(segments) - 5

    async with async_session() as session:
        new_version = await session.get(TranscriptVersion, body["version_id"])
        texts = [seg["text"] for seg in new_version.segments]
        # Two "You're in the process." lines survive: the isolated real
        # one at the original index 6 (never part of the flagged run)
        # and the kept head of the collapsed run at index 8 -- only the
        # five REPEATED cues after it are gone. Every real surrounding
        # sentence, including the one that interrupts the two, is
        # untouched.
        assert texts.count("You're in the process.") == 2
        assert "You have to do it right." in texts
        assert "I'm sorry." in texts
