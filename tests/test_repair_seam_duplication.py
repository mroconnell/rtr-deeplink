"""Tests for scripts/repair_seam_duplication.py's pure detection logic
and for the admin action it drives, POST /internal/transcript-version/
repair-seam-duplication (archive/main.py) ->
crud.create_seam_repair_version() -- the retroactive repair for the
already-live seam-duplication defect (see that script's own module
docstring, and BACKLOG.md's "[JUST-DO-IT] `[BIG]` Repair the three
already-live transcript-defect populations" entry).
"""

import hashlib

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud
from archive.db.engine import async_session
from archive.db.models import TranscriptVersion
from archive.utils.transcript_export import to_srt
from scripts.repair_seam_duplication import find_seam_duplicates

client = TestClient(archive.main.app)


# --- find_seam_duplicates() -- pure logic, no I/O -------------------------
#
# _REAL_* below is the exact real, live text this bug produced on the
# Boulder County, CO page (bouldercounty-2026-02-05-historic-
# preservation-advisory-board), quoted verbatim from
# tests/test_worker_segment_utils.py's own real-production fixture --
# not invented text standing in for a real duplicate.

_REAL_PREVIOUS_TAIL = {
    "start": 896.0,
    "end": 899.5,
    "text": "...this whole question about truck caro, which may actually predate the Bracero program.",
}
_REAL_PREVIOUS_EDGE = {
    "start": 900.0,
    "end": 900.9,
    "text": "Um, there's an exhibit at the.",
}
_REAL_NEW_HEAD = {
    "start": 908.0,
    "end": 918.7,
    "text": (
        "This whole question about truck caro, which may actually predate the "
        "Bracero program, there's an exhibit at the Colorado Railroad Museum, "
        "so down in Golden..."
    ),
}


def test_finds_the_real_boulder_county_seam_duplicate():
    segments = [_REAL_PREVIOUS_TAIL, _REAL_PREVIOUS_EDGE, _REAL_NEW_HEAD]
    findings = find_seam_duplicates(segments, total_chunks=2, chunk_size_seconds=900)

    assert len(findings) == 1
    finding = findings[0]
    assert finding["seam_index"] == 1
    assert finding["boundary_seconds"] == 900
    # Both prev-side segments are the confirmed duplicate -- same result
    # count_seam_overlap_segments() itself returns for this exact real
    # case in tests/test_worker_segment_utils.py.
    assert finding["drop_segment_indices"] == [0, 1]


def test_boundary_segment_belongs_to_the_previous_chunk_not_the_new_one():
    """Regression test for the reconstruction gap this script's own
    module docstring calls out: a naive "first segment at/after the
    boundary timestamp" split would put _REAL_PREVIOUS_EDGE (which
    starts at exactly the 900s boundary) on the wrong side and miss the
    real duplicate entirely. SPLIT_SEARCH_RADIUS's neighborhood search
    is what recovers it -- this test fails without that search."""
    segments = [_REAL_PREVIOUS_TAIL, _REAL_PREVIOUS_EDGE, _REAL_NEW_HEAD]
    findings = find_seam_duplicates(segments, total_chunks=2, chunk_size_seconds=900)
    assert findings, "expected the real duplicate to be found"


def test_no_false_positive_on_ordinary_non_duplicated_speech():
    segments = [
        {
            "start": 850.0,
            "end": 895.0,
            "text": "The chair recognizes the next speaker.",
        },
        {
            "start": 895.0,
            "end": 899.0,
            "text": "Thank you, I'll keep my comments brief.",
        },
        {
            "start": 905.0,
            "end": 912.0,
            "text": "Moving on to the next agenda item, item four.",
        },
        {
            "start": 912.0,
            "end": 920.0,
            "text": "This concerns the proposed zoning variance.",
        },
    ]
    findings = find_seam_duplicates(segments, total_chunks=2, chunk_size_seconds=900)
    assert findings == []


def test_single_chunk_job_has_no_seams_to_check():
    segments = [{"start": 0.0, "end": 5.0, "text": "Only one chunk, no seam at all."}]
    assert find_seam_duplicates(segments, total_chunks=1, chunk_size_seconds=900) == []


def test_empty_segments_is_safe():
    assert find_seam_duplicates([], total_chunks=3, chunk_size_seconds=900) == []


def test_multiple_seams_each_checked_independently():
    """Three chunks, two seams -- only the second one has a real
    duplicate. Confirms seams are scored independently, not just the
    first one found. The middle chunk carries enough ordinary filler
    segments to clear LOOKBACK_SEGMENTS on both sides of seam 1 -- a real
    900s chunk of actual speech always has far more than 8 segments in
    it, so this reflects real segment density rather than the
    pathologically sparse middle chunk a tighter synthetic case would
    need to also exercise the seam-scoping bound directly (see the
    seam-scoping test below for that)."""
    _FILLER_TEXTS = [
        "The council took up the parking variance next.",
        "A resident spoke in favor of the proposed bike lane.",
        "The treasurer presented the quarterly budget figures.",
        "Staff clarified the timeline for the sidewalk repair project.",
        "The chair called for a brief recess before the next item.",
        "The clerk read the minutes from the previous meeting aloud.",
        "A motion was made to table the zoning amendment.",
        "The engineer described the drainage study's findings.",
        "Public comment closed after three more speakers.",
        "The board voted to approve the consent calendar.",
    ]
    filler = [
        {"start": 900.0 + i * 20, "end": 900.0 + i * 20 + 15, "text": text}
        for i, text in enumerate(_FILLER_TEXTS)
    ]
    segments = [
        {
            "start": 850.0,
            "end": 899.0,
            "text": "Ordinary speech before the first seam.",
        },
        *filler,
        {"start": 1796.0, "end": 1799.5, "text": _REAL_PREVIOUS_TAIL["text"]},
        {"start": 1800.0, "end": 1800.9, "text": _REAL_PREVIOUS_EDGE["text"]},
        {"start": 1808.0, "end": 1818.7, "text": _REAL_NEW_HEAD["text"]},
    ]
    findings = find_seam_duplicates(segments, total_chunks=3, chunk_size_seconds=900)
    assert [f["seam_index"] for f in findings] == [2]
    real_tail_index = segments.index(
        next(s for s in segments if s["text"] == _REAL_PREVIOUS_TAIL["text"])
    )
    real_edge_index = real_tail_index + 1
    # The two genuinely duplicated segments must always be in the drop
    # set. count_seam_overlap_segments() itself may also pull in one
    # adjacent, non-duplicate segment at the matched span's edge --
    # that's the underlying, already-shipped detector's own documented
    # tradeoff ("erring toward dropping a couple of genuinely-unique
    # words... is a far smaller cost than leaving a visibly duplicated
    # sentence behind"), not something this reconstruction introduces,
    # so this test doesn't demand exact-index equality. What it does
    # demand: the drop never reaches all the way back to the *first*
    # filler segment (index 1) or further -- that would mean this seam's
    # window swallowed most of an unrelated chunk, which is exactly what
    # the seam-scoping bound exists to prevent.
    drop = set(findings[0]["drop_segment_indices"])
    assert {real_tail_index, real_edge_index} <= drop
    assert min(drop) >= real_tail_index - 1


def test_seam_scoping_never_reaches_back_across_an_earlier_seam():
    """Regression test for the reconstruction gap find_seam_duplicates()'s
    own module comment calls out: with too few segments between two
    consecutive seams to fill LOOKBACK_SEGMENTS, the naive window would
    reach past the earlier seam's own boundary and risk over-dropping
    genuinely unrelated content from an earlier chunk. This is a real,
    if unusual, production shape (e.g. a near-silent recess chunk) -- the
    scoping bound must keep seam 2's window from ever crossing back into
    seam 1's territory (segment index 0 here), even in this pathological
    sparse case."""
    segments = [
        {
            "start": 850.0,
            "end": 899.0,
            "text": "Ordinary speech before the first seam.",
        },
        {"start": 900.0, "end": 905.0, "text": "Different ordinary speech after it."},
        {"start": 1796.0, "end": 1799.5, "text": _REAL_PREVIOUS_TAIL["text"]},
        {"start": 1800.0, "end": 1800.9, "text": _REAL_PREVIOUS_EDGE["text"]},
        {"start": 1808.0, "end": 1818.7, "text": _REAL_NEW_HEAD["text"]},
    ]
    findings = find_seam_duplicates(segments, total_chunks=3, chunk_size_seconds=900)
    for finding in findings:
        if finding["seam_index"] == 2:
            # Must never include index 0 -- that segment belongs to the
            # chunk BEFORE seam 1, a full seam away from seam 2.
            assert 0 not in finding["drop_segment_indices"]


# --- POST /internal/transcript-version/repair-seam-duplication -----------


async def _ingest_meeting_with_segments(url_suffix: str, segments: list[dict]) -> str:
    url = f"https://example.granicus.com/player/clip/{url_suffix}"
    await crud.ingest_resolution(
        {
            "platform": "granicus",
            "source_url": url,
            "external_id": f"granicus:{url_suffix}",
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
    return (await crud.lookup_page_for_url(url))["slug"]


def _srt_hash(segments: list[dict]) -> str:
    return hashlib.sha256(to_srt(segments).encode("utf-8")).hexdigest()


def test_repair_endpoint_rejects_missing_token():
    response = client.post(
        "/internal/transcript-version/repair-seam-duplication",
        json={
            "slug": "whatever",
            "expected_srt_hash": "x",
            "drop_segment_indices": [0],
        },
    )
    assert response.status_code == 404


def test_repair_endpoint_404s_for_unknown_slug():
    response = client.post(
        "/internal/transcript-version/repair-seam-duplication",
        json={
            "slug": "no-such-slug-at-all",
            "expected_srt_hash": "x",
            "drop_segment_indices": [0],
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 404


async def test_repair_endpoint_drops_the_named_segments_and_promotes_a_new_version():
    segments = [_REAL_PREVIOUS_TAIL, _REAL_PREVIOUS_EDGE, _REAL_NEW_HEAD]
    slug = await _ingest_meeting_with_segments("repair-success", segments)
    page = await crud.get_page_by_slug(slug)
    original_default_id = next(v["id"] for v in page["versions"] if v["is_default"])

    response = client.post(
        "/internal/transcript-version/repair-seam-duplication",
        json={
            "slug": slug,
            "expected_srt_hash": _srt_hash(segments),
            "drop_segment_indices": [0, 1],
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["dropped"] == 2
    assert body["kept"] == 1

    async with async_session() as session:
        new_version = await session.get(TranscriptVersion, body["version_id"])
        assert new_version.is_default is True
        assert new_version.segments == [_REAL_NEW_HEAD]

        # Never destroys history -- the old default stays reachable.
        old_version = await session.get(TranscriptVersion, original_default_id)
        assert old_version.is_default is False
        assert old_version.segments == segments


async def test_repair_endpoint_refuses_a_stale_hash():
    segments = [_REAL_PREVIOUS_TAIL, _REAL_PREVIOUS_EDGE, _REAL_NEW_HEAD]
    slug = await _ingest_meeting_with_segments("repair-stale", segments)
    page = await crud.get_page_by_slug(slug)
    original_default_id = next(v["id"] for v in page["versions"] if v["is_default"])

    response = client.post(
        "/internal/transcript-version/repair-seam-duplication",
        json={
            "slug": slug,
            "expected_srt_hash": "0" * 64,  # deliberately wrong
            "drop_segment_indices": [0, 1],
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 409
    assert response.json()["error"] == "stale"

    # Nothing changed -- the original default is still the default.
    async with async_session() as session:
        version = await session.get(TranscriptVersion, original_default_id)
        assert version.is_default is True


async def test_repair_endpoint_refuses_to_empty_a_transcript():
    segments = [_REAL_PREVIOUS_TAIL, _REAL_PREVIOUS_EDGE, _REAL_NEW_HEAD]
    slug = await _ingest_meeting_with_segments("repair-empty", segments)

    response = client.post(
        "/internal/transcript-version/repair-seam-duplication",
        json={
            "slug": slug,
            "expected_srt_hash": _srt_hash(segments),
            "drop_segment_indices": [0, 1, 2],  # every segment
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "empty_result"


async def test_repair_endpoint_reapplying_the_same_repair_reuses_the_existing_version():
    """A retry (or a second --apply run against an already-repaired page)
    must not stack a second, content-identical TranscriptVersion -- same
    dedup convention as ingest_resolution()."""
    segments = [_REAL_PREVIOUS_TAIL, _REAL_PREVIOUS_EDGE, _REAL_NEW_HEAD]
    slug = await _ingest_meeting_with_segments("repair-idempotent", segments)

    first = client.post(
        "/internal/transcript-version/repair-seam-duplication",
        json={
            "slug": slug,
            "expected_srt_hash": _srt_hash(segments),
            "drop_segment_indices": [0, 1],
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert first.status_code == 200
    repaired_version_id = first.json()["version_id"]

    # Re-fetch the (now repaired) transcript's real hash, same as the
    # script's own --apply re-probe-before-writing step.
    second = client.post(
        "/internal/transcript-version/repair-seam-duplication",
        json={
            "slug": slug,
            "expected_srt_hash": _srt_hash([_REAL_NEW_HEAD]),
            "drop_segment_indices": [],
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert second.status_code == 200
    assert second.json()["version_id"] == repaired_version_id
