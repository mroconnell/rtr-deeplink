"""Tests for archive/utils/social.py's auto-announce pipeline and the
crud/ingest plumbing it rides on (the `created` flag, the SocialPost
claim-first dedup).

The two network clients (_post_to_bluesky/_post_to_mastodon) are
monkeypatched here, not exercised. The Bluesky one is live-verified
separately (first real post 2026-08-21, see BACKLOG_DONE.md); the
Mastodon one has still never made a real post -- no account exists, see
BACKLOG.md's residuals entry. What IS real in these tests: the
fixture SQLite DB, crud.ingest_resolution()'s created/page_id plumbing,
the SocialPost unique-constraint dedup, and the quality gate/composition
logic. The Fountain Valley garbled-warning text used below is the real
adapter warning wording (granicus.py's, the same substring outcomes.py
and crud.py both match on), not an invented string.
"""

from datetime import datetime, timedelta, timezone

import pytest

from archive.db import crud
from archive.utils import social


@pytest.fixture(autouse=True)
def _reset_post_buffer():
    """The between-posts buffer's timestamp is module-global in-memory
    state (see social._last_announce_at) -- without this reset, whichever
    announce test runs first would silently suppress every later one."""
    social._last_announce_at = None
    yield
    social._last_announce_at = None


# The adapters' real garbled-source warning shape (see granicus.py and
# crud._GARBLED_MARKER) -- confirmed real-world case: Fountain Valley,
# CA's transcript is genuinely garbled at the source (BACKLOG_DONE.md).
_GARBLED_WARNING = (
    "This transcript looks garbled at the source -- the platform's own "
    "captions are corrupted."
)


def _segments(n: int) -> list:
    return [
        {"start": float(i), "end": float(i + 1), "text": f"segment {i}"}
        for i in range(n)
    ]


def _quality_payload(**overrides) -> dict:
    payload = {
        "platform": "granicus",
        "source_url": "https://example.granicus.com/player/clip/social-quality",
        "external_id": "granicus:social-quality",
        "title": "City Council Regular Meeting",
        "date": "2026-08-01",
        "jurisdiction": "City of Dublin, CA",
        "video_url": "https://example.com/video.m3u8",
        "video_format": "m3u8",
        "segments": _segments(60),
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }
    payload.update(overrides)
    return payload


# --- quality gate -------------------------------------------------------


def test_high_quality_payload_passes():
    assert social.payload_is_high_quality(_quality_payload())


def test_no_video_fails():
    assert not social.payload_is_high_quality(_quality_payload(video_url=None))


def test_too_few_segments_fails():
    # 3 lines is a caption stub, not an announceable meeting -- below the
    # SOCIAL_MIN_SEGMENTS default of 50.
    assert not social.payload_is_high_quality(_quality_payload(segments=_segments(3)))


def test_garbled_warning_fails():
    assert not social.payload_is_high_quality(
        _quality_payload(transcript_warnings=[_GARBLED_WARNING])
    )


def test_non_english_fails():
    # Mirrors outcomes.py's non_english_transcript bucket -- e.g. the real
    # Fountain Valley misdetected-as-Portuguese case.
    assert not social.payload_is_high_quality(
        _quality_payload(transcript_language="pt")
    )


def test_undetected_language_still_passes():
    # outcomes.py only flags a *detected* non-English language; an
    # undetected one still classifies as success, so it must pass here too.
    assert social.payload_is_high_quality(_quality_payload(transcript_language=None))


# --- composition --------------------------------------------------------


def test_compose_post_full_sentence_and_footer():
    url = "https://redtaperecordings.com/m/dublin-ca-2026-08-01"
    text = social.compose_post(
        "City Council Regular Meeting", "City of Dublin, CA", "2026-08-01", url
    )
    assert text.startswith("Somebody looked up City Council Regular Meeting — ")
    assert f"link to specific timestamps at {url}" in text
    assert text.endswith("\n\nCity of Dublin, CA — 2026-08-01")
    assert len(text) <= 300


def test_compose_post_truncates_long_title_keeps_url_and_footer():
    url = "https://redtaperecordings.com/m/some-city-2026-08-01"
    text = social.compose_post(
        "An Absurdly Long Meeting Title " * 20, "City of Test, CA", "2026-08-01", url
    )
    assert len(text) <= 300
    assert url in text  # the permalink always survives whole
    assert "…" in text
    # A short footer fits within the ladder's first rung, so it survives.
    assert text.endswith("\n\nCity of Test, CA — 2026-08-01")


def test_compose_post_drops_footer_before_gutting_title():
    # A worst-case slug (this repo caps slugs well under this, but the
    # composition shouldn't depend on that) plus a long jurisdiction:
    # keeping the footer would leave the title under _MIN_TRUNCATED_TITLE
    # chars, so the footer goes first and the title keeps the larger
    # budget.
    url = "https://redtaperecordings.com/m/" + "x" * 140
    jurisdiction = "Housing Authority of the County of Santa Clara, CA"
    text = social.compose_post(
        "Planning Commission Special Meeting and Joint Study Session",
        jurisdiction,
        "2026-08-19",
        url,
    )
    assert len(text) <= 300
    assert url in text
    assert jurisdiction not in text  # footer dropped, not the title's core
    assert "Planning Commission" in text


def test_compose_post_handles_all_blank_metadata():
    url = "https://redtaperecordings.com/m/x"
    text = social.compose_post(None, None, None, url)
    assert text.startswith("Somebody looked up a public meeting — ")
    assert text.endswith(url)  # no footer when there's nothing to put in it


# --- ingest plumbing + end-to-end announce ------------------------------


async def test_ingest_resolution_reports_created_only_on_first_push():
    url = "https://example.granicus.com/player/clip/social-created-flag"
    payload = _quality_payload(
        external_id="granicus:social-created-flag", source_url=url
    )

    first = await crud.ingest_resolution(payload, url)
    assert first["created"] is True
    assert first["page_id"] is not None

    second = await crud.ingest_resolution(payload, url)
    assert second["created"] is False
    assert second["page_id"] == first["page_id"]


async def test_announce_posts_once_and_dedups(monkeypatch):
    monkeypatch.setenv("BLUESKY_HANDLE", "rtr.test")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "test-app-password")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://redtaperecordings.com")
    monkeypatch.delenv("MASTODON_BASE_URL", raising=False)
    # Buffer off so this tests the SocialPost claim dedup in isolation --
    # the buffer has its own test below.
    monkeypatch.setenv("SOCIAL_MIN_POST_INTERVAL_SECONDS", "0")

    url = "https://example.granicus.com/player/clip/social-announce-once"
    payload = _quality_payload(
        external_id="granicus:social-announce-once", source_url=url
    )
    result = await crud.ingest_resolution(payload, url)

    posted = []

    async def fake_bluesky(text, link_url):
        posted.append((text, link_url))
        return "at://did:plc:test/app.bsky.feed.post/abc123"

    monkeypatch.setattr(social, "_post_to_bluesky", fake_bluesky)

    await social.announce_new_page(result["page_id"], result["slug"], payload)
    assert len(posted) == 1
    text, link_url = posted[0]
    assert link_url == f"https://redtaperecordings.com/m/{result['slug']}"
    assert link_url in text

    # Second call (e.g. a duplicate first-ingest race) -- the SocialPost
    # claim already exists, so nothing posts again.
    await social.announce_new_page(result["page_id"], result["slug"], payload)
    assert len(posted) == 1


async def test_announce_skips_low_quality_and_leaves_no_claim(monkeypatch):
    monkeypatch.setenv("BLUESKY_HANDLE", "rtr.test")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "test-app-password")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://redtaperecordings.com")

    url = "https://example.granicus.com/player/clip/social-low-quality"
    payload = _quality_payload(
        external_id="granicus:social-low-quality",
        source_url=url,
        segments=[],  # agenda-only page: a real result, but not announceable
        agenda_items=[{"start": 0.0, "end": 1.0, "text": "Call to order"}],
    )
    result = await crud.ingest_resolution(payload, url)

    async def fail_if_called(text, link_url):
        raise AssertionError("low-quality page must never be posted")

    monkeypatch.setattr(social, "_post_to_bluesky", fail_if_called)
    await social.announce_new_page(result["page_id"], result["slug"], payload)

    # No claim was burned, so a later, better first ingest could still
    # announce -- (page, network) stays unclaimed after a quality skip.
    claim = await crud.claim_social_post(result["page_id"], "bluesky")
    assert claim is not None


async def test_failed_post_records_failure_and_never_retries(monkeypatch):
    monkeypatch.setenv("BLUESKY_HANDLE", "rtr.test")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "test-app-password")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://redtaperecordings.com")
    # Buffer off: the second announce here must reach the claim check to
    # prove no-retry comes from the burned claim, not from the buffer.
    monkeypatch.setenv("SOCIAL_MIN_POST_INTERVAL_SECONDS", "0")

    url = "https://example.granicus.com/player/clip/social-post-fails"
    payload = _quality_payload(external_id="granicus:social-post-fails", source_url=url)
    result = await crud.ingest_resolution(payload, url)

    calls = []

    async def flaky_bluesky(text, link_url):
        calls.append(text)
        raise RuntimeError("bsky.social is down")

    monkeypatch.setattr(social, "_post_to_bluesky", flaky_bluesky)

    # Must not raise -- a social failure can't surface near ingest.
    await social.announce_new_page(result["page_id"], result["slug"], payload)
    assert len(calls) == 1

    # At-most-once on purpose (see social.py's module docstring): the
    # failed claim stays, so a retry does NOT re-post.
    await social.announce_new_page(result["page_id"], result["slug"], payload)
    assert len(calls) == 1


async def test_announce_noop_when_no_network_configured(monkeypatch):
    monkeypatch.delenv("BLUESKY_HANDLE", raising=False)
    monkeypatch.delenv("BLUESKY_APP_PASSWORD", raising=False)
    monkeypatch.delenv("MASTODON_BASE_URL", raising=False)
    monkeypatch.delenv("MASTODON_ACCESS_TOKEN", raising=False)

    url = "https://example.granicus.com/player/clip/social-disabled"
    payload = _quality_payload(external_id="granicus:social-disabled", source_url=url)
    result = await crud.ingest_resolution(payload, url)

    await social.announce_new_page(result["page_id"], result["slug"], payload)

    # Nothing claimed -- the feature was entirely inert.
    claim = await crud.claim_social_post(result["page_id"], "bluesky")
    assert claim is not None


async def test_post_buffer_spaces_burst_and_burns_no_claim(monkeypatch):
    """A burst of qualifying first-ingests (e.g. a bulk seed) posts at
    most one announcement per SOCIAL_MIN_POST_INTERVAL_SECONDS window --
    the default-180s buffer, user request 2026-08-21. The skipped
    candidate must not burn its SocialPost claim, and once the window
    has elapsed announcements flow again."""
    monkeypatch.setenv("BLUESKY_HANDLE", "rtr.test")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "test-app-password")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://redtaperecordings.com")
    # Default interval (180s) deliberately NOT overridden -- this test
    # exercises the shipped default, moving the clock instead of the env.

    url_a = "https://example.granicus.com/player/clip/social-buffer-a"
    url_b = "https://example.granicus.com/player/clip/social-buffer-b"
    page_a = await crud.ingest_resolution(
        _quality_payload(external_id="granicus:social-buffer-a", source_url=url_a),
        url_a,
    )
    payload_b = _quality_payload(
        external_id="granicus:social-buffer-b", source_url=url_b
    )
    page_b = await crud.ingest_resolution(payload_b, url_b)

    posted = []

    async def fake_bluesky(text, link_url):
        posted.append(link_url)
        return "at://did:plc:test/app.bsky.feed.post/buffer"

    monkeypatch.setattr(social, "_post_to_bluesky", fake_bluesky)

    payload_a = _quality_payload(
        external_id="granicus:social-buffer-a", source_url=url_a
    )
    await social.announce_new_page(page_a["page_id"], page_a["slug"], payload_a)
    await social.announce_new_page(page_b["page_id"], page_b["slug"], payload_b)
    assert len(posted) == 1  # page B landed inside the window -> skipped

    # The skip happened before any claim, so page B's (page, network)
    # slot is still open...
    claim = await crud.claim_social_post(page_b["page_id"], "bluesky")
    assert claim is not None
    # ...and once the window has elapsed (timestamp backdated past the
    # 180s default instead of a real sleep), a fresh candidate posts
    # normally. Page B itself can't (its claim was just burned above) --
    # which is fine, this asserts the *buffer* reopens, on a third page.
    social._last_announce_at = datetime.now(timezone.utc) - timedelta(seconds=181)
    url_c = "https://example.granicus.com/player/clip/social-buffer-c"
    payload_c = _quality_payload(
        external_id="granicus:social-buffer-c", source_url=url_c
    )
    page_c = await crud.ingest_resolution(payload_c, url_c)
    await social.announce_new_page(page_c["page_id"], page_c["slug"], payload_c)
    assert len(posted) == 2
