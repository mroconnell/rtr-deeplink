"""Regression test for the robots.txt prefix-match bug found in the
2026-08-14 audit -- a bare "Disallow: /meeting" also blocks /meetings
(the Archive's browse/search hub) because robots.txt Disallow matching is
prefix-based, not exact. /meetings is simultaneously listed as indexable
in the sitemap, so the site was telling crawlers to index a page it also
told them not to crawl. Fix anchors the ephemeral /meeting resolver page
specifically: "/meeting$" (exact path) and "/meeting?" (its query-string
variants), leaving /meetings alone.
"""

from fastapi.testclient import TestClient

import app.main

client = TestClient(app.main.app)


def _disallow_lines(body: str) -> list[str]:
    return [
        line.split("Disallow: ", 1)[1]
        for line in body.splitlines()
        if line.startswith("Disallow: ")
    ]


def _matches(pattern: str, path: str) -> bool:
    # Real crawler semantics (Google/Bing): "$" anchors end-of-path, any
    # other character (including "?") is compared literally, not as a
    # wildcard. Deliberately not using urllib.robotparser here -- it
    # doesn't implement "$" anchoring or query-string literals at all, so
    # it gives wrong answers for exactly the cases this test needs to
    # check (confirmed by hand against both directives before writing this).
    if pattern.endswith("$"):
        return path == pattern[:-1]
    return path.startswith(pattern)


def test_robots_txt_anchors_the_meeting_disallow():
    body = client.get("/robots.txt").text
    assert "Disallow: /meeting$" in body
    assert "Disallow: /meeting?" in body
    # the old bare, prefix-matching directive must be gone, not just
    # supplemented -- it's the one that swallowed /meetings.
    assert not any(line.strip() == "Disallow: /meeting" for line in body.splitlines())


def test_meetings_hub_is_not_matched_by_any_emitted_rule():
    body = client.get("/robots.txt").text
    for pattern in _disallow_lines(body):
        assert not _matches(pattern, "/meetings"), f"'{pattern}' still blocks /meetings"


def test_ephemeral_meeting_resolver_is_still_blocked():
    body = client.get("/robots.txt").text
    patterns = _disallow_lines(body)
    assert any(_matches(p, "/meeting") for p in patterns)
    assert any(_matches(p, "/meeting?url=https://example.com") for p in patterns)
