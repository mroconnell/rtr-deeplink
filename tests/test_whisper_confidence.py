"""WO-1968: Whisper's own per-segment confidence numbers (avg_logprob,
no_speech_prob, compression_ratio) are kept on each transcribed segment, so
a later change can shade shaky stretches for readers. Nothing displays them
yet.

SYNTHETIC: faster-whisper's Segment/Word objects are faked with dataclasses
below, the same way tests/test_transcription_engine.py does. Their field
names (start, end, text, words, avg_logprob, no_speech_prob,
compression_ratio) match faster-whisper's real Segment dataclass, checked
against faster_whisper/transcribe.py in the 1.2.1 wheel (2026-10-16). The
numbers are plausible values, not read from a real model run; no model is
loaded here.
"""

import math
from dataclasses import dataclass, field
from typing import List, Optional

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud
from worker.segment_utils import (
    WHISPER_CONFIDENCE_FIELDS,
    merge_chunk_segments,
    shift_segments,
    whisper_confidence_fields,
)
from worker.transcription_engine import (
    FasterWhisperEngine,
    _split_segment_on_word_gaps,
)

client = TestClient(archive.main.app)
_AUTH = {"Authorization": "Bearer test-token"}


@dataclass
class _FakeWord:
    start: float
    end: float
    word: str


@dataclass
class _FakeSegment:
    start: float
    end: float
    text: str
    words: Optional[List[_FakeWord]] = field(default=None)
    avg_logprob: Optional[float] = -0.2345678
    no_speech_prob: Optional[float] = 0.0123456
    compression_ratio: Optional[float] = 1.4567891


_ROUNDED = {"avg_logprob": -0.235, "no_speech_prob": 0.012, "compression_ratio": 1.457}


# --- The pure helper ---------------------------------------------------------


def test_fields_are_rounded_to_three_decimals():
    assert whisper_confidence_fields(_FakeSegment(0, 1, "x")) == _ROUNDED


def test_missing_or_non_finite_values_are_left_out_not_invented():
    seg = _FakeSegment(
        0, 1, "x", avg_logprob=None, no_speech_prob=math.nan, compression_ratio=math.inf
    )
    assert whisper_confidence_fields(seg) == {}

    class _Bare:  # an object with none of the attributes at all
        pass

    assert whisper_confidence_fields(_Bare()) == {}


# --- The engine's segment builder -------------------------------------------


def test_segment_without_words_keeps_its_numbers():
    result = _split_segment_on_word_gaps(_FakeSegment(0.0, 1.0, " Roll call."))
    assert result == [
        {"start": 0.0, "end": 1.0, "text": "Roll call.", "speaker": None, **_ROUNDED}
    ]


def test_each_piece_of_a_gap_split_carries_the_parent_numbers():
    seg = _FakeSegment(
        start=66.8,
        end=735.9,
        text=" So folks, a reminder.",
        words=[
            _FakeWord(67.5, 67.9, " So"),
            _FakeWord(732.8, 733.1, " folks,"),
            _FakeWord(733.1, 733.5, " a"),
            _FakeWord(733.5, 736.2, " reminder."),
        ],
    )
    result = _split_segment_on_word_gaps(seg)
    assert len(result) == 2
    for piece in result:
        assert {k: piece[k] for k in WHISPER_CONFIDENCE_FIELDS} == _ROUNDED


def test_transcribe_sync_returns_the_numbers(tmp_path):
    class _FakeModel:
        def transcribe(self, *_args, **_kwargs):
            return iter([_FakeSegment(0.0, 2.0, " Motion carries.")]), None

    engine = FasterWhisperEngine.__new__(FasterWhisperEngine)  # skip model load
    engine._language = None
    engine._model = _FakeModel()
    result = engine._transcribe_sync(tmp_path / "chunk.mp3")
    assert result == [
        {
            "start": 0.0,
            "end": 2.0,
            "text": "Motion carries.",
            "speaker": None,
            **_ROUNDED,
        }
    ]


# --- Chunk offsetting and seam merging --------------------------------------


def test_shift_segments_moves_times_and_keeps_numbers():
    raw = _split_segment_on_word_gaps(_FakeSegment(1.0, 2.0, " Aye."))
    shifted = shift_segments(raw, 900.0)
    assert shifted == [
        {"start": 901.0, "end": 902.0, "text": "Aye.", "speaker": None, **_ROUNDED}
    ]


def test_shift_segments_adds_no_keys_to_a_segment_without_numbers():
    shifted = shift_segments([{"start": 0.0, "end": 1.0, "text": "a"}], 10.0)
    assert shifted == [{"start": 10.0, "end": 11.0, "text": "a", "speaker": None}]


def test_seam_merge_keeps_numbers_on_kept_segments():
    previous = shift_segments(
        _split_segment_on_word_gaps(_FakeSegment(1.0, 2.0, " First chunk.")), 0.0
    )
    new = shift_segments(
        _split_segment_on_word_gaps(_FakeSegment(1.0, 2.0, " Second chunk.")), 900.0
    )
    merged = merge_chunk_segments(previous, new)
    assert len(merged) == 2
    for seg in merged:
        assert {k: seg[k] for k in WHISPER_CONFIDENCE_FIELDS} == _ROUNDED


# --- The Archive boundary ----------------------------------------------------


def test_archive_model_field_names_match_the_worker_tuple():
    declared = set(archive.main.TranscriptSegmentIn.model_fields)
    assert set(WHISPER_CONFIDENCE_FIELDS) <= declared


def test_archive_model_keeps_numbers_and_omits_absent_ones():
    with_numbers = archive.main.TranscriptSegmentIn(
        start=0, end=1, text="x", **_ROUNDED
    ).model_dump()
    assert {k: with_numbers[k] for k in WHISPER_CONFIDENCE_FIELDS} == _ROUNDED

    caption = archive.main.TranscriptSegmentIn(start=0, end=1, text="x").model_dump()
    # A scraped-caption cue's stored shape is unchanged: no null keys.
    assert caption == {"start": 0.0, "end": 1.0, "text": "x", "speaker": None}


def _ingest_body(url: str, segments: list) -> dict:
    return {
        "input_url_normalized": url,
        "platform": "granicus",
        "source_url": url,
        "external_id": "granicus:" + url.rsplit("/", 1)[-1],
        "title": "WO-1968 Test Meeting",
        "date": "2026-10-01",
        "jurisdiction": "City of Test",
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": segments,
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
        "source": "transcribed",
    }


async def test_ingest_route_stores_numbers_and_readers_never_see_them():
    # The local script's path: segments pass through /internal/ingest.
    url = "https://example.granicus.com/player/clip/wo1968-1"
    segments = shift_segments(
        _split_segment_on_word_gaps(
            _FakeSegment(1.0, 4.0, " The council will now hear public comment.")
        ),
        0.0,
    )
    response = client.post(
        "/internal/ingest", json=_ingest_body(url, segments), headers=_AUTH
    )
    assert response.status_code == 200
    slug = response.json()["slug"]

    page = await crud.get_page_by_slug(slug)
    stored = page["versions"][0]["segments"][0]
    assert {k: stored[k] for k in WHISPER_CONFIDENCE_FIELDS} == _ROUNDED

    # Reader-facing outputs read only start/end/text, so nothing changes.
    html = client.get(f"/m/{slug}").text
    txt = client.get(f"/m/{slug}/transcript.txt").text
    srt = client.get(f"/m/{slug}/transcript.srt").text
    for body in (html, txt, srt):
        assert "public comment" in body
        assert "avg_logprob" not in body
        assert "-0.235" not in body


async def test_ingest_route_adds_no_keys_to_caption_segments():
    url = "https://example.granicus.com/player/clip/wo1968-2"
    body = _ingest_body(url, [{"start": 0.0, "end": 1.0, "text": "Call to order."}])
    body.pop("source")
    response = client.post("/internal/ingest", json=body, headers=_AUTH)
    assert response.status_code == 200
    page = await crud.get_page_by_slug(response.json()["slug"])
    assert page["versions"][0]["segments"] == [
        {"start": 0.0, "end": 1.0, "text": "Call to order.", "speaker": None}
    ]


async def test_cloud_worker_chunk_report_stores_numbers():
    # The cloud worker's path: shifted segments go straight into
    # partial_segments via crud.report_chunk_result(), no Pydantic model.
    url = "https://example.granicus.com/player/clip/wo1968-3"
    payload = _ingest_body(url, [])
    payload.pop("input_url_normalized")
    payload.pop("source")
    job = await crud.create_transcription_job(
        payload=payload,
        input_url_normalized=url,
        requester_email="wo1968@example.com",
        media_url="https://example.com/v.m3u8",
        media_kind="video",
        probed_duration_seconds=1000,
        chunk_size_seconds=900,
        skip_confirmation=True,
    )
    assert job["total_chunks"] == 2
    for i in range(2):
        claim = await crud.claim_next_chunk()
        assert claim["job_id"] == job["job_id"]
        shifted = shift_segments(
            _split_segment_on_word_gaps(
                _FakeSegment(1.0, 2.0, f" Item {i} is approved.")
            ),
            i * 900.0,
        )
        result = await crud.report_chunk_result(
            claim["job_id"], success=True, shifted_segments=shifted
        )
    assert result["status"] == "completed"

    page = await crud.get_page_by_slug(job["meeting_page_slug"])
    transcribed = [v for v in page["versions"] if v["source"] == "transcribed"]
    assert [s["start"] for s in transcribed[0]["segments"]] == [1.0, 901.0]
    for seg in transcribed[0]["segments"]:
        assert {k: seg[k] for k in WHISPER_CONFIDENCE_FIELDS} == _ROUNDED
