"""Tests for scripts/fetch_youtube_transcripts.py's snippet-to-segment
conversion -- the pure part of the local fetcher (the YouTube fetch itself
is lazy-imported and only ever runs from a residential IP, see the
script's own docstring) -- and process_one()'s WO-15 (BACKLOG.md,
2026-08-16) auto-promote step.
"""

import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from fetch_youtube_transcripts import (  # noqa: E402
    _classify_transcript_api_failure,
    _is_rate_limit_signal,
    _restrict_to_slugs,
    process_one,
    snippets_to_segments,
)


def _snippet(text, start, duration=2.0):
    return SimpleNamespace(text=text, start=start, duration=duration)


def test_converts_start_duration_to_start_end():
    segments = snippets_to_segments([_snippet("Hello there, everyone.", 10.0, 3.5)])
    assert segments == [{"start": 10.0, "end": 13.5, "text": "Hello there, everyone."}]


def test_drops_blank_padding_snippets():
    # Real CC1 tracks contain whitespace-only snippets as timing padding
    # (confirmed on a real Minneapolis video: the first snippet is ' ').
    segments = snippets_to_segments(
        [
            _snippet(" ", 17.9),
            _snippet("Real text here.", 18.1),
        ]
    )
    assert len(segments) == 1
    assert segments[0]["text"] == "Real text here."


def test_replaces_leading_speaker_marker_with_site_convention():
    # A real ">>" character here, unlike the literal "&gt;&gt;" entity
    # text normalize_speaker_change_marker() handles in raw VTT files.
    segments = snippets_to_segments(
        [_snippet(">> All right. It is 1:35 and we are ready to begin.", 18.1)]
    )
    assert segments[0]["text"].startswith("» All right.")


def test_mid_text_marker_left_alone():
    segments = snippets_to_segments([_snippet("He said >> pointing at the sign.", 5.0)])
    assert segments[0]["text"] == "He said >> pointing at the sign."


def test_all_caps_track_gets_deshouted():
    # Human-typed CC tracks are commonly ALL CAPS -- reuses the existing
    # normalize_shouting_caption() (needs a real sample of letters to
    # trigger, so give it enough text).
    segments = snippets_to_segments(
        [
            _snippet(
                ">> ALL RIGHT. IT IS ONE THIRTY FIVE AND WE ARE READY TO GET STARTED.",
                18.1,
            ),
            _snippet(
                "MADAM CLERK PLEASE CALL THE ROLL FOR ALL MEMBERS PRESENT TODAY.", 23.1
            ),
        ]
    )
    joined = " ".join(seg["text"] for seg in segments)
    assert joined != joined.upper()
    assert "» All right." in segments[0]["text"]


def test_normal_case_track_left_alone():
    segments = snippets_to_segments(
        [
            _snippet(
                "The meeting will now come to order, please stand for the pledge of allegiance.",
                0.0,
            ),
        ]
    )
    assert (
        segments[0]["text"]
        == "The meeting will now come to order, please stand for the pledge of allegiance."
    )


def test_pre_escaped_entity_in_snippet_gets_unescaped():
    # Real gap fixed 2026-08-12: this conversion bypasses parse_vtt()
    # entirely, so it never picked up unescape_caption_entities() when
    # that general double-escaping fix was added there.
    segments = snippets_to_segments([_snippet("Smith &amp; Jones, LLC", 0.0)])
    assert segments[0]["text"] == "Smith & Jones, LLC"


def test_is_rate_limit_signal_true_for_request_blocked_and_subclasses():
    # Synthetic stand-ins for youtube-transcript-api's real exception
    # classes (confirmed via this repo's installed copy,
    # youtube_transcript_api/_errors.py: RequestBlocked's docstring is
    # literally "YouTube is blocking requests from your IP", and IpBlocked
    # subclasses it) -- matched by class name in the MRO specifically so
    # this stays true without the library installed (see this module's own
    # lazy-import convention), not because the real shape is in doubt.
    class RequestBlocked(Exception):
        pass

    class IpBlocked(RequestBlocked):
        pass

    assert _is_rate_limit_signal(RequestBlocked("blocked"))
    assert _is_rate_limit_signal(IpBlocked("blocked"))


def test_is_rate_limit_signal_false_for_ordinary_per_video_failures():
    # These are expected, routine noise this queue surfaces regardless
    # (private video, disabled captions, video removed) -- must NOT trigger
    # backoff, or a normal run with a few of these would falsely back off.
    class TranscriptsDisabled(Exception):
        pass

    class VideoUnavailable(Exception):
        pass

    assert not _is_rate_limit_signal(TranscriptsDisabled("disabled"))
    assert not _is_rate_limit_signal(VideoUnavailable("gone"))
    assert not _is_rate_limit_signal(RuntimeError("ingest failed (500)"))


def test_classify_transcript_api_failure_maps_confirmed_permanent_exceptions():
    # WO-135, 2026-09-09: real, confirmed-live counts from this module's
    # own top docstring (8 TranscriptsDisabled / 4 VideoUnplayable / 3
    # VideoUnavailable in the first 15 real permanent failures). Synthetic
    # stand-in exception classes, same convention as
    # test_is_rate_limit_signal_true_for_request_blocked_and_subclasses
    # above -- matched by class name so this stays testable without
    # youtube-transcript-api installed.
    from app.platforms.youtube import (
        YOUTUBE_CAPTIONS_DISABLED_MARKER,
        YOUTUBE_VIDEO_UNAVAILABLE_MARKER,
    )

    class TranscriptsDisabled(Exception):
        pass

    class VideoUnavailable(Exception):
        pass

    class VideoUnplayable(Exception):
        def __init__(self, reason):
            self.reason = reason
            super().__init__(
                f"The video is unplayable for the following reason: {reason}"
            )

    assert (
        _classify_transcript_api_failure(TranscriptsDisabled("abc"))
        == YOUTUBE_CAPTIONS_DISABLED_MARKER
    )
    assert (
        _classify_transcript_api_failure(VideoUnavailable("abc"))
        == YOUTUBE_VIDEO_UNAVAILABLE_MARKER
    )
    assert (
        _classify_transcript_api_failure(
            VideoUnplayable("Sign in to confirm you are not a bot")
        )
        == YOUTUBE_VIDEO_UNAVAILABLE_MARKER
    )


def test_classify_transcript_api_failure_does_not_flag_scheduled_live_event():
    # Real, confirmed-live VideoUnplayable `reason` text (2026-09-09, see
    # this module's own top docstring) for a scheduled-but-not-yet-live
    # stream -- must NOT be treated as permanent (the same video resolves
    # fine once it starts).
    class VideoUnplayable(Exception):
        def __init__(self, reason):
            self.reason = reason
            super().__init__(
                f"The video is unplayable for the following reason: {reason}"
            )

    assert (
        _classify_transcript_api_failure(
            VideoUnplayable("This live event will begin in a few moments.")
        )
        is None
    )


def test_classify_transcript_api_failure_ignores_language_mismatch():
    # NoTranscriptFound means captions exist in some OTHER language --
    # a different, already-handled outcome, not a permanent failure.
    class NoTranscriptFound(Exception):
        pass

    assert _classify_transcript_api_failure(NoTranscriptFound("no en track")) is None


class _FakePostResponse:
    def __init__(self, json_body):
        self._json_body = json_body
        self.status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self):
        return str(self._json_body)

    async def json(self):
        return self._json_body


@contextmanager
def _mock_post(routes: dict):
    """routes: {url: response_dict}. Records every call as (url, json_body)
    tuples on the returned list, mirroring aiohttp_mock.py's exact-URL-match
    convention but for POST (fetch_youtube_transcripts.py only ever POSTs,
    never GETs, to the Archive)."""
    calls = []

    def fake_post(self, url, json=None, **kwargs):
        calls.append((str(url), json))
        key = str(url)
        if key not in routes:
            raise AssertionError(f"Unmocked POST in test: {key}")
        return _FakePostResponse(routes[key])

    with mock.patch.object(aiohttp.ClientSession, "post", fake_post):
        yield calls


async def test_process_one_promotes_after_a_successful_push(monkeypatch):
    # WO-15 (BACKLOG.md, 2026-08-16): a page already in the transcript-
    # wanted queue because its existing default is garbled has segments+
    # language already, so archive/db/crud.py's _is_real_improvement()
    # won't auto-promote a fresh push on its own -- process_one() must
    # explicitly follow up with POST /internal/transcript-version/promote.
    base = "https://archive.example.com"
    monkeypatch.setattr("fetch_youtube_transcripts._base_url", lambda: base)
    # WO-135's precheck (a real yt-dlp metadata call) would otherwise run
    # for real against this test's fake video id -- stub it clean/healthy
    # so this test still isolates only the promote-after-push behavior it
    # was written for.
    monkeypatch.setattr(
        "fetch_youtube_transcripts.YouTubeAssetFinder.check_permanent_failure",
        lambda video_id: (None, None),
    )
    monkeypatch.setattr(
        "fetch_youtube_transcripts.fetch_transcript",
        lambda video_id: ([{"start": 0.0, "end": 1.0, "text": "hello"}], "en"),
    )
    page = {
        "slug": "promote-test-meeting",
        "title": "Promote Test Meeting",
        "platform": "youtube",
        "external_id": "youtube:promote-test",
        "source_url_normalized": "https://www.youtube.com/watch?v=AAAAAAAAAAA",
        "video_url": "https://www.youtube.com/embed/AAAAAAAAAAA",
    }
    routes = {
        f"{base}/internal/ingest": {
            "slug": "promote-test-meeting",
            "url": "/m/promote-test-meeting",
            "version_id": 42,
        },
        f"{base}/internal/transcript-version/promote": {
            "slug": "promote-test-meeting",
            "promoted_version_id": 42,
        },
    }

    async with aiohttp.ClientSession() as session:
        with _mock_post(routes) as calls:
            result = await process_one(session, page, dry_run=False)

    assert result["status"] == "ingested"
    assert "(promoted to default)" in result["detail"]
    urls_called = [url for url, _body in calls]
    assert urls_called == [
        f"{base}/internal/ingest",
        f"{base}/internal/transcript-version/promote",
    ]
    promote_body = calls[1][1]
    assert promote_body == {
        "slug": "promote-test-meeting",
        "version_id": 42,
        # Real gap fixed 2026-08-20: dedup-by-content-hash in
        # ingest_resolution() can reuse an existing, already-garbled-flagged
        # version row on re-fetch, so this script always asks the promote
        # endpoint to also clear that stale warning -- see _promote()'s
        # docstring.
        "clear_warnings": True,
    }


async def test_process_one_skips_promote_when_ingest_had_no_segments(monkeypatch):
    # A push whose content exactly content-hash-duplicates an already
    # *non-default* version with no fresh segments created would come back
    # with version_id=None from ingest_resolution() in one real edge case
    # (see its own docstring) -- process_one() shouldn't call promote with
    # nothing to promote.
    base = "https://archive.example.com"
    monkeypatch.setattr("fetch_youtube_transcripts._base_url", lambda: base)
    monkeypatch.setattr(
        "fetch_youtube_transcripts.YouTubeAssetFinder.check_permanent_failure",
        lambda video_id: (None, None),
    )
    monkeypatch.setattr(
        "fetch_youtube_transcripts.fetch_transcript",
        lambda video_id: ([{"start": 0.0, "end": 1.0, "text": "hello"}], "en"),
    )
    page = {
        "slug": "no-version-id-meeting",
        "platform": "youtube",
        "external_id": "youtube:no-version-id",
        "source_url_normalized": "https://www.youtube.com/watch?v=BBBBBBBBBBB",
        "video_url": "https://www.youtube.com/embed/BBBBBBBBBBB",
    }
    routes = {
        f"{base}/internal/ingest": {
            "slug": "no-version-id-meeting",
            "url": "/m/no-version-id-meeting",
            "version_id": None,
        },
    }

    async with aiohttp.ClientSession() as session:
        with _mock_post(routes) as calls:
            result = await process_one(session, page, dry_run=False)

    assert result["status"] == "ingested"
    assert "(promoted to default)" not in result["detail"]
    assert [url for url, _body in calls] == [f"{base}/internal/ingest"]


async def test_process_one_skips_via_precheck_without_calling_fetch_transcript(
    monkeypatch,
):
    # WO-135, 2026-09-09: the metadata-only precheck confirms a permanent
    # failure BEFORE any real (rate-limited) transcript request -- assert
    # fetch_transcript() is never even called, and the marker is recorded
    # via POST /internal/pages/{slug}/video-status rather than
    # /internal/ingest (see record_youtube_video_status()'s docstring for
    # why that route can't do this).
    from app.platforms.youtube import YOUTUBE_CAPTIONS_DISABLED_MARKER

    base = "https://archive.example.com"
    monkeypatch.setattr("fetch_youtube_transcripts._base_url", lambda: base)
    monkeypatch.setattr(
        "fetch_youtube_transcripts.YouTubeAssetFinder.check_permanent_failure",
        lambda video_id: (YOUTUBE_CAPTIONS_DISABLED_MARKER, None),
    )

    def _unexpected_fetch(video_id):
        raise AssertionError(
            "fetch_transcript() must not be called after a precheck hit"
        )

    monkeypatch.setattr("fetch_youtube_transcripts.fetch_transcript", _unexpected_fetch)
    page = {
        "slug": "captions-disabled-meeting",
        "platform": "youtube",
        "external_id": "youtube:captions-disabled",
        "source_url_normalized": "https://www.youtube.com/watch?v=CCCCCCCCCCC",
        "video_url": "https://www.youtube.com/embed/CCCCCCCCCCC",
    }
    routes = {
        f"{base}/internal/pages/captions-disabled-meeting/video-status": {
            "slug": "captions-disabled-meeting",
            "page_id": 1,
            "version_id": 99,
        },
    }

    async with aiohttp.ClientSession() as session:
        with _mock_post(routes) as calls:
            result = await process_one(session, page, dry_run=False)

    assert result["status"] == "skipped"
    assert "will never be re-queued" in result["detail"]
    assert calls == [
        (
            f"{base}/internal/pages/captions-disabled-meeting/video-status",
            {"transcript_marker": YOUTUBE_CAPTIONS_DISABLED_MARKER},
        )
    ]


async def test_process_one_records_permanent_failure_from_real_fetch_exception(
    monkeypatch,
):
    # The precheck can come back clean while the real youtube-transcript-api
    # fetch still raises a confirmed-permanent exception (different
    # InnerTube recipe than yt-dlp's -- see this module's own top
    # docstring) -- that must ALSO be recorded and skipped, not just
    # reported as an ordinary "failed".
    from app.platforms.youtube import YOUTUBE_VIDEO_UNAVAILABLE_MARKER

    class VideoUnavailable(Exception):
        pass

    base = "https://archive.example.com"
    monkeypatch.setattr("fetch_youtube_transcripts._base_url", lambda: base)
    monkeypatch.setattr(
        "fetch_youtube_transcripts.YouTubeAssetFinder.check_permanent_failure",
        lambda video_id: (None, None),
    )

    def _raise(video_id):
        raise VideoUnavailable("gone")

    monkeypatch.setattr("fetch_youtube_transcripts.fetch_transcript", _raise)
    page = {
        "slug": "video-gone-meeting",
        "platform": "youtube",
        "external_id": "youtube:video-gone",
        "source_url_normalized": "https://www.youtube.com/watch?v=DDDDDDDDDDD",
        "video_url": "https://www.youtube.com/embed/DDDDDDDDDDD",
    }
    routes = {
        f"{base}/internal/pages/video-gone-meeting/video-status": {
            "slug": "video-gone-meeting",
            "page_id": 2,
            "version_id": 100,
        },
    }

    async with aiohttp.ClientSession() as session:
        with _mock_post(routes) as calls:
            result = await process_one(session, page, dry_run=False)

    assert result["status"] == "skipped"
    assert "will never be re-queued" in result["detail"]
    assert calls == [
        (
            f"{base}/internal/pages/video-gone-meeting/video-status",
            {"transcript_marker": YOUTUBE_VIDEO_UNAVAILABLE_MARKER},
        )
    ]


async def test_process_one_records_embed_disabled_but_still_fetches_transcript(
    monkeypatch,
):
    # Real, confirmed-live case found probing all 96 real no-transcript
    # YouTube pages 2026-09-09 (video id 5IoXmnqr72Y): embedding disabled
    # and captions disabled are independent facts -- this real page has
    # real automatic_captions available despite playable_in_embed being
    # False. A video_marker-only precheck result must record that marker
    # for visibility but still proceed to the real transcript fetch below
    # -- unlike a transcript_marker hit, which skips the fetch entirely.
    from app.platforms.youtube import YOUTUBE_EMBED_DISABLED_MARKER

    base = "https://archive.example.com"
    monkeypatch.setattr("fetch_youtube_transcripts._base_url", lambda: base)
    monkeypatch.setattr(
        "fetch_youtube_transcripts.YouTubeAssetFinder.check_permanent_failure",
        lambda video_id: (None, YOUTUBE_EMBED_DISABLED_MARKER),
    )
    monkeypatch.setattr(
        "fetch_youtube_transcripts.fetch_transcript",
        lambda video_id: ([{"start": 0.0, "end": 1.0, "text": "hello"}], "en"),
    )
    page = {
        "slug": "embed-disabled-meeting",
        "platform": "youtube",
        "external_id": "youtube:embed-disabled",
        "source_url_normalized": "https://www.youtube.com/watch?v=5IoXmnqr72Y",
        "video_url": "https://www.youtube.com/embed/5IoXmnqr72Y",
    }
    routes = {
        f"{base}/internal/pages/embed-disabled-meeting/video-status": {
            "slug": "embed-disabled-meeting",
            "page_id": 3,
            "version_id": None,
        },
        f"{base}/internal/ingest": {
            "slug": "embed-disabled-meeting",
            "url": "/m/embed-disabled-meeting",
            "version_id": 200,
        },
        f"{base}/internal/transcript-version/promote": {
            "slug": "embed-disabled-meeting",
            "promoted_version_id": 200,
        },
    }

    async with aiohttp.ClientSession() as session:
        with _mock_post(routes) as calls:
            result = await process_one(session, page, dry_run=False)

    assert result["status"] == "ingested"
    urls_called = [url for url, _body in calls]
    assert urls_called == [
        f"{base}/internal/pages/embed-disabled-meeting/video-status",
        f"{base}/internal/ingest",
        f"{base}/internal/transcript-version/promote",
    ]
    assert calls[0][1] == {"video_marker": YOUTUBE_EMBED_DISABLED_MARKER}


def test_restrict_to_slugs_no_file_returns_all_pages():
    pages = [{"slug": "a"}, {"slug": "b"}]
    assert _restrict_to_slugs(pages, None) is pages


def test_restrict_to_slugs_filters_to_requested_slugs(tmp_path, capsys):
    slugs_file = tmp_path / "slugs.txt"
    slugs_file.write_text("a\n# a comment\n\nc\n")
    pages = [{"slug": "a"}, {"slug": "b"}, {"slug": "d"}]

    kept = _restrict_to_slugs(pages, slugs_file)

    assert kept == [{"slug": "a"}]
    out = capsys.readouterr().out
    assert "2 slug(s) requested, 1 found" in out
    assert "not in transcript-wanted queue (1): c" in out
