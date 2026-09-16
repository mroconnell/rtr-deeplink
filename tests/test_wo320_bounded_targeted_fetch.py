"""Binary leads must stay unfetched while ordinary meeting pages remain scorable."""

import json

import pytest

import scripts.wo320_targeted as wo320
import scripts.wo325_targeted as wo325

shared = wo320.w273t


class StreamResponse:
    def __init__(self, url, chunks=(), headers=None, status=200):
        self.url = url
        self.chunks = chunks
        self.headers = headers or {}
        self.status_code = status
        self.read_chunks = 0
        self.closed = False

    @property
    def content(self):
        raise AssertionError("body was read without the stream limit")

    def iter_content(self, chunk_size):
        for chunk in self.chunks:
            self.read_chunks += 1
            yield chunk

    def close(self):
        self.closed = True


@pytest.mark.parametrize("module", [wo320, wo325])
def test_direct_media_url_never_reaches_archive_or_network(monkeypatch, module):
    def forbidden(*args, **kwargs):
        raise AssertionError("direct MP4 must remain an unfetched lead")

    monkeypatch.setattr(shared, "try_wayback_archived_body", forbidden)
    monkeypatch.setattr(shared, "polite_fetch", forbidden)
    result = module.fetch_and_score_v2(
        "https://jeffersoncountytx.gov/Coffee%20Bean_Damon%20West_short_46m.mp4",
        "Jefferson",
        "Texas",
        None,
    )
    assert result["error"] == "skipped-media-url"
    assert result["platform_confirmed"] == ""
    assert result["url"].endswith(".mp4")


@pytest.mark.parametrize("module", [wo320, wo325])
@pytest.mark.parametrize(
    ("head_headers", "head_url", "expected"),
    [
        (
            {"Content-Type": "application/pdf"},
            "https://example.gov/download",
            "skipped-non-html",
        ),
        (
            {"Content-Length": str(shared.PAGE_BODY_LIMIT + 1)},
            "https://example.gov/page",
            "skipped-oversize",
        ),
        ({}, "https://www.youtube.com/watch?v=abc", "skipped-youtube-redirect"),
        ({}, "https://example.gov/meeting.pdf", "skipped-media-url"),
    ],
)
def test_head_headers_and_redirect_stop_before_get(
    monkeypatch, module, head_headers, head_url, expected
):
    monkeypatch.setattr(shared, "try_wayback_archived_body", lambda url: (None, False))
    head = StreamResponse(head_url, headers=head_headers)
    calls = []

    def fake_fetch(url, method="GET", **kwargs):
        calls.append(method)
        if method == "GET":
            raise AssertionError("HEAD already identified the unsafe lead")
        return head

    monkeypatch.setattr(shared, "polite_fetch", fake_fetch)
    result = module.fetch_and_score_v2(
        "https://example.gov/meeting", "Example", "Iowa", None
    )
    assert result["error"] == expected
    assert calls == ["HEAD"]
    assert head.read_chunks == 0


@pytest.mark.parametrize("module", [wo320, wo325])
def test_get_stream_rechecks_redirect_and_content_type(monkeypatch, module):
    monkeypatch.setattr(shared, "try_wayback_archived_body", lambda url: (None, False))
    head = StreamResponse("https://example.gov/page")
    get = StreamResponse(
        "https://example.gov/file", [b"%PDF-1.7"], {"Content-Type": "application/pdf"}
    )

    def fake_fetch(url, method="GET", **kwargs):
        if method == "HEAD":
            return head
        assert kwargs["stream"] is True
        return get

    monkeypatch.setattr(shared, "polite_fetch", fake_fetch)
    result = module.fetch_and_score_v2(
        "https://example.gov/page", "Example", "Iowa", None
    )
    assert result["error"] == "skipped-non-html"
    assert get.read_chunks == 0
    assert get.closed


@pytest.mark.parametrize("module", [wo320, wo325])
@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("https://example.gov/large.mp4", "skipped-media-url"),
        ("https://www.youtube.com/watch?v=abc", "skipped-youtube-redirect"),
    ],
)
def test_get_redirect_body_is_never_drained_or_followed_to_media(
    monkeypatch, module, location, expected
):
    monkeypatch.setattr(shared, "try_wayback_archived_body", lambda url: (None, False))
    head = StreamResponse("https://example.gov/page")
    redirect = StreamResponse(
        "https://example.gov/page",
        [b"x" * (shared.PAGE_BODY_LIMIT + 1)],
        {"Location": location},
        status=302,
    )
    calls = []

    def fake_fetch(url, method="GET", **kwargs):
        calls.append((url, method, kwargs))
        assert kwargs["allow_redirects"] is False
        return head if method == "HEAD" else redirect

    monkeypatch.setattr(shared, "polite_fetch", fake_fetch)
    result = module.fetch_and_score_v2(
        "https://example.gov/page", "Example", "Iowa", None
    )
    assert result["error"] == expected
    assert [method for _, method, _ in calls] == ["HEAD", "GET"]
    assert redirect.read_chunks == 0
    assert redirect.closed


@pytest.mark.parametrize("module", [wo320, wo325])
def test_unknown_length_get_stops_at_body_limit(monkeypatch, module):
    monkeypatch.setattr(shared, "try_wayback_archived_body", lambda url: (None, False))
    head = StreamResponse("https://example.gov/page")
    chunks = [b"a" * 65536] * 40
    get = StreamResponse(
        "https://example.gov/page", chunks, {"Content-Type": "text/html"}
    )
    monkeypatch.setattr(
        shared,
        "polite_fetch",
        lambda url, method="GET", **kwargs: head if method == "HEAD" else get,
    )
    result = module.fetch_and_score_v2(
        "https://example.gov/page", "Example", "Iowa", None
    )
    assert result["error"] == "skipped-oversize"
    assert get.read_chunks == 33
    assert get.closed


def test_extensionless_binary_with_no_content_type_stops_after_first_chunk():
    binary = StreamResponse("https://example.gov/download", [bytes(range(256))] * 100)
    body, reason = shared.bounded_page_body(binary)
    assert body is None
    assert reason == "skipped-non-html"
    assert binary.read_chunks == 1


@pytest.mark.parametrize("module", [wo320, wo325])
def test_ordinary_html_uses_bounded_stream(monkeypatch, module):
    monkeypatch.setattr(shared, "try_wayback_archived_body", lambda url: (None, False))
    head = StreamResponse(
        "https://example.gov/meetings", headers={"Content-Type": "text/html"}
    )
    page = b"<html><title>Example Iowa City Council</title></html>" * 25
    get = StreamResponse(
        "https://example.gov/meetings", [page], {"Content-Type": "text/html"}
    )
    monkeypatch.setattr(
        shared,
        "polite_fetch",
        lambda url, method="GET", **kwargs: head if method == "HEAD" else get,
    )
    result = module.fetch_and_score_v2(
        "https://example.gov/meetings", "Example", "Iowa", None
    )
    assert result["body_len"] == len(page)
    assert result["error"] == ""
    assert get.closed


def test_archive_replay_is_streamed_and_capped(monkeypatch):
    replay = StreamResponse(
        "https://web.archive.org/web/20260901id_/https://example.gov/page",
        [b"a" * 65536] * 40,
        {"Content-Type": "text/html"},
    )
    calls = []

    cdx = StreamResponse(
        "https://web.archive.org/cdx/search/cdx",
        [
            json.dumps(
                [["original", "timestamp"], ["https://example.gov/page", "20260901"]]
            ).encode()
        ],
    )

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return cdx if "/cdx/" in url else replay

    monkeypatch.setattr(shared.requests, "get", fake_get)
    monkeypatch.setattr(shared, "capture_age_days", lambda ts: 0)
    assert shared.try_wayback_archived_body("https://example.gov/page") == (None, False)
    assert calls[-1][1]["stream"] is True
    assert replay.read_chunks == 33
    assert replay.closed
    assert cdx.closed


def test_archive_redirect_to_media_does_not_read_or_follow_body(monkeypatch):
    cdx = StreamResponse(
        "https://web.archive.org/cdx/search/cdx",
        [
            json.dumps(
                [["original", "timestamp"], ["https://example.gov/page", "20260901"]]
            ).encode()
        ],
    )
    redirect = StreamResponse(
        "https://web.archive.org/web/20260901id_/https://example.gov/page",
        [b"x" * (shared.PAGE_BODY_LIMIT + 1)],
        {"Location": "https://example.gov/meeting.mp4"},
        status=302,
    )
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        assert kwargs["allow_redirects"] is False
        return cdx if "/cdx/" in url else redirect

    monkeypatch.setattr(shared.requests, "get", fake_get)
    monkeypatch.setattr(shared, "capture_age_days", lambda ts: 0)
    assert shared.try_wayback_archived_body("https://example.gov/page") == (None, False)
    assert len(calls) == 2
    assert redirect.read_chunks == 0
    assert redirect.closed


def test_archive_cdx_response_is_bounded(monkeypatch):
    cdx = StreamResponse("https://web.archive.org/cdx/search/cdx", [b"x" * 16384] * 6)
    monkeypatch.setattr(shared.requests, "get", lambda url, **kwargs: cdx)
    assert shared.try_wayback_archived_body("https://example.gov/page") == (None, False)
    assert cdx.read_chunks == 5
    assert cdx.closed
