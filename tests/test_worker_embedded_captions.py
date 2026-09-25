"""Tests for worker/main.py's WO-1065 embedded-captions extraction path
inside maybe_generate_auto_job() -- an Invintus (or any future adapter
exposing the same `extract_embedded_captions` method) meeting whose
resolve() found EMBEDDED_CAPTIONS_MARKER in transcript_warnings gets its
real CEA-608 captions extracted directly, before ever falling into the
ordinary Whisper chunk-job path. See app/platforms/embedded_captions.py's
module docstring and worker/main.py's own WO-1065 comment for the real
background.

Uses a fake finder (a plain class with resolve()/extract_embedded_captions()
methods) rather than the real InvintusAssetFinder -- no network, no
ffmpeg -- same pattern tests/test_worker_auto_generation.py already uses
for every other maybe_generate_auto_job() scenario.
"""

import worker.main
from app.platforms.embedded_captions import EMBEDDED_CAPTIONS_MARKER
from app.platforms.embedded_captions import EmbeddedCaptionsBlocked
from app.platforms.models import ResolvedMeeting


def _candidate(gov_id=None):
    async def _c():
        return {
            "meeting_page_id": 999999,
            "slug": "fake-invintus-meeting",
            "source_url": "https://player.invintus.com/?clientID=1&eventID=2",
            "platform": "invintus",
            "gov_id": gov_id,
        }

    return _c


def _base_setup(monkeypatch, gov_id=None):
    monkeypatch.setattr(
        worker.main, "AUTO_TRANSCRIPTION_REQUESTER_EMAIL", "auto@example.com"
    )
    monkeypatch.setattr(
        worker.main.crud, "find_auto_transcription_candidate", _candidate(gov_id)
    )


class _EmbeddedCapableFinder:
    """A fake finder carrying the exact duck-typed method name the worker
    checks for, plus a resolve() that reports the marker -- everything a
    real InvintusAssetFinder does for this scenario, with no network."""

    def __init__(self, cues=None, extraction_error=None):
        self._cues = cues if cues is not None else []
        self._extraction_error = extraction_error
        self.extract_calls = []

    async def resolve(self, url):
        return ResolvedMeeting(
            platform="invintus",
            source_url=url,
            video_url="https://player.invintus.com/stream.m3u8",
            video_format="m3u8",
            transcript_warnings=[
                f"{EMBEDDED_CAPTIONS_MARKER} but aren't text yet. We'll add "
                "them to this page once they're extracted."
            ],
        )

    async def extract_embedded_captions(self, url):
        self.extract_calls.append(url)
        if self._extraction_error is not None:
            raise self._extraction_error
        return self._cues


async def test_embedded_captions_success_ingests_segments_and_clears_marker(
    monkeypatch,
):
    _base_setup(monkeypatch, gov_id="us:place:41:12345")
    cues = [
        {"start": 0.0, "end": 2.0, "text": "Good morning everyone"},
        {"start": 2.0, "end": 4.0, "text": "let's call this meeting to order"},
    ]
    finder = _EmbeddedCapableFinder(cues=cues)
    monkeypatch.setattr(worker.main, "get_finder", lambda platform: finder)

    ingested = {}

    async def _ingest_resolution(*, payload, input_url_normalized):
        ingested["payload"] = payload
        ingested["input_url_normalized"] = input_url_normalized
        return {"page_id": 1, "created": False, "version_id": 5}

    monkeypatch.setattr(worker.main.crud, "ingest_resolution", _ingest_resolution)

    async def _fail_if_called(*args, **kwargs):
        raise AssertionError(
            "a successful extraction must never fall through to the "
            "ordinary Whisper job path"
        )

    monkeypatch.setattr(worker.main.crud, "create_transcription_job", _fail_if_called)
    monkeypatch.setattr(
        worker.main.crud, "create_failed_auto_transcription_job", _fail_if_called
    )

    assert await worker.main.maybe_generate_auto_job() is True
    assert finder.extract_calls == ["https://player.invintus.com/?clientID=1&eventID=2"]

    payload = ingested["payload"]
    assert payload["source"] == "sourced"
    assert payload["gov_id"] == "us:place:41:12345"
    assert [dict(s) for s in payload["segments"]] == [
        {"start": 0.0, "end": 2.0, "text": "Good morning everyone", "speaker": None},
        {
            "start": 2.0,
            "end": 4.0,
            "text": "let's call this meeting to order",
            "speaker": None,
        },
    ]
    assert not any(
        EMBEDDED_CAPTIONS_MARKER in w for w in payload["transcript_warnings"]
    )
    assert payload["transcript_language"] == "en"
    assert ingested["input_url_normalized"] == (
        "https://player.invintus.com/?clientID=1&eventID=2"
    )


async def test_embedded_captions_success_omits_gov_id_when_candidate_has_none(
    monkeypatch,
):
    _base_setup(monkeypatch, gov_id=None)
    finder = _EmbeddedCapableFinder(
        cues=[{"start": 0.0, "end": 1.0, "text": "hello there today"}]
    )
    monkeypatch.setattr(worker.main, "get_finder", lambda platform: finder)

    ingested = {}

    async def _ingest_resolution(*, payload, input_url_normalized):
        ingested["payload"] = payload
        return {"page_id": 1, "created": False, "version_id": 5}

    monkeypatch.setattr(worker.main.crud, "ingest_resolution", _ingest_resolution)

    assert await worker.main.maybe_generate_auto_job() is True
    assert "gov_id" not in ingested["payload"]


async def test_embedded_captions_adds_garbled_warning_when_likely_garbled(monkeypatch):
    _base_setup(monkeypatch)
    # Same real, confirmed shape tests/test_vtt_parser.py's own
    # test_is_likely_garbled_true_for_short_junk_fragments() uses (mirrors
    # the real Alexandria VA pattern documented in vtt_parser.py): short
    # 1-2 letter junk fragments well above the 6% threshold.
    junk_words = ["tm", "Oa", "sd", "xr", "qp"] * 10
    clean_words = ["the", "meeting", "will", "come", "to", "order"] * 3
    cues = [{"start": 0.0, "end": 1.0, "text": " ".join(junk_words + clean_words)}]
    finder = _EmbeddedCapableFinder(cues=cues)
    monkeypatch.setattr(worker.main, "get_finder", lambda platform: finder)

    ingested = {}

    async def _ingest_resolution(*, payload, input_url_normalized):
        ingested["payload"] = payload
        return {"page_id": 1, "created": False, "version_id": 5}

    monkeypatch.setattr(worker.main.crud, "ingest_resolution", _ingest_resolution)

    assert await worker.main.maybe_generate_auto_job() is True
    assert any(
        "looks garbled at the source" in w
        for w in ingested["payload"]["transcript_warnings"]
    )


async def test_embedded_captions_extraction_failure_records_failed_job(monkeypatch):
    _base_setup(monkeypatch)
    finder = _EmbeddedCapableFinder(
        extraction_error=EmbeddedCaptionsBlocked("403 from the CDN")
    )
    monkeypatch.setattr(worker.main, "get_finder", lambda platform: finder)

    recorded = {}

    async def _record_failure(*, meeting_page_id, requester_email, error_message):
        recorded["meeting_page_id"] = meeting_page_id
        recorded["error_message"] = error_message
        return {"job_id": 1, "status": "failed"}

    monkeypatch.setattr(
        worker.main.crud, "create_failed_auto_transcription_job", _record_failure
    )

    async def _fail_if_called(*args, **kwargs):
        raise AssertionError("an extraction failure must not reach ingest_resolution")

    monkeypatch.setattr(worker.main.crud, "ingest_resolution", _fail_if_called)

    assert await worker.main.maybe_generate_auto_job() is True
    assert recorded["meeting_page_id"] == 999999
    assert "Embedded caption extraction failed" in recorded["error_message"]
    assert "403 from the CDN" in recorded["error_message"]


async def test_embedded_captions_empty_cues_falls_back_to_whisper_job(monkeypatch):
    _base_setup(monkeypatch)
    finder = _EmbeddedCapableFinder(cues=[])  # probe said yes, extraction found none
    monkeypatch.setattr(worker.main, "get_finder", lambda platform: finder)

    async def _fail_if_called(*args, **kwargs):
        raise AssertionError(
            "empty cues must fall through to the Whisper path, not be treated "
            "as a failure"
        )

    monkeypatch.setattr(
        worker.main.crud, "create_failed_auto_transcription_job", _fail_if_called
    )
    monkeypatch.setattr(worker.main.crud, "ingest_resolution", _fail_if_called)

    async def _probe(video_url, *, source_page_url):
        return 3600.0

    monkeypatch.setattr(worker.main, "probe_duration", _probe)

    created = {}

    async def _create_job(**kwargs):
        created.update(kwargs)
        return {"job_id": 4242}

    monkeypatch.setattr(worker.main.crud, "create_transcription_job", _create_job)

    assert await worker.main.maybe_generate_auto_job() is True
    assert finder.extract_calls == ["https://player.invintus.com/?clientID=1&eventID=2"]
    assert created["probed_duration_seconds"] == 3600.0


async def test_no_marker_never_calls_extract_embedded_captions(monkeypatch):
    """A resolve with no EMBEDDED_CAPTIONS_MARKER (the ordinary case for
    every other platform, and for Invintus meetings with real sidecar
    captions or none at all) must behave exactly as before WO-1065 --
    extract_embedded_captions() is never even called."""
    _base_setup(monkeypatch)

    class _OrdinaryFinder:
        extract_calls = []

        async def resolve(self, url):
            return ResolvedMeeting(
                platform="invintus",
                source_url=url,
                video_url="https://player.invintus.com/stream.m3u8",
                video_format="m3u8",
                transcript_warnings=["No captions found for this video."],
            )

        async def extract_embedded_captions(self, url):
            self.extract_calls.append(url)
            raise AssertionError("must not be called when no marker is present")

    finder = _OrdinaryFinder()
    monkeypatch.setattr(worker.main, "get_finder", lambda platform: finder)

    async def _probe(video_url, *, source_page_url):
        return 3600.0

    monkeypatch.setattr(worker.main, "probe_duration", _probe)

    created = {}

    async def _create_job(**kwargs):
        created.update(kwargs)
        return {"job_id": 4242}

    monkeypatch.setattr(worker.main.crud, "create_transcription_job", _create_job)

    assert await worker.main.maybe_generate_auto_job() is True
    assert finder.extract_calls == []
    assert created["probed_duration_seconds"] == 3600.0


async def test_finder_without_extractor_method_is_unaffected(monkeypatch):
    """A platform whose adapter has no extract_embedded_captions method at
    all (every platform except Invintus today) must never be touched by
    this code path, even if it somehow carried the marker text."""
    _base_setup(monkeypatch)

    class _NoExtractorFinder:
        async def resolve(self, url):
            return ResolvedMeeting(
                platform="some_other_platform",
                source_url=url,
                video_url="https://example.org/meeting.m3u8",
                video_format="m3u8",
                transcript_warnings=[EMBEDDED_CAPTIONS_MARKER],
            )

    finder = _NoExtractorFinder()
    monkeypatch.setattr(worker.main, "get_finder", lambda platform: finder)

    async def _probe(video_url, *, source_page_url):
        return 3600.0

    monkeypatch.setattr(worker.main, "probe_duration", _probe)

    created = {}

    async def _create_job(**kwargs):
        created.update(kwargs)
        return {"job_id": 4242}

    monkeypatch.setattr(worker.main.crud, "create_transcription_job", _create_job)

    assert await worker.main.maybe_generate_auto_job() is True
    assert created["probed_duration_seconds"] == 3600.0
