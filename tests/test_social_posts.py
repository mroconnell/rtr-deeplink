"""Tests for archive/utils/social.py's auto-announce pipeline and the
crud/ingest plumbing it rides on (the `created` flag, the SocialPost
claim-first dedup).

The two network clients (_post_to_bluesky/_post_to_mastodon) are
monkeypatched here, not exercised -- they are written against the
documented Bluesky XRPC / Mastodon statuses APIs but have never made a
real post (no account/credentials existed when this was built, see
BACKLOG.md's live-verification entry). What IS real in these tests: the
fixture SQLite DB, crud.ingest_resolution()'s created/page_id plumbing,
the SocialPost unique-constraint dedup, and the quality gate/composition
logic. The Fountain Valley garbled-warning text used below is the real
adapter warning wording (granicus.py's, the same substring outcomes.py
and crud.py both match on), not an invented string.
"""

from archive.db import crud
from archive.utils import social

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


def test_compose_post_includes_headline_and_url():
    text = social.compose_post(
        "City Council Regular Meeting",
        "City of Dublin, CA",
        "2026-08-01",
        "https://redtaperecordings.com/m/dublin-ca-2026-08-01",
    )
    assert "City of Dublin, CA — City Council Regular Meeting (2026-08-01)" in text
    assert text.endswith("https://redtaperecordings.com/m/dublin-ca-2026-08-01")
    assert len(text) <= 300


def test_compose_post_truncates_long_headline_never_url():
    url = "https://redtaperecordings.com/m/some-city-2026-08-01"
    text = social.compose_post("An Absurdly Long Meeting Title " * 20, None, None, url)
    assert len(text) <= 300
    assert text.endswith(url)  # the permalink always survives whole
    assert "…" in text


def test_compose_post_handles_all_blank_metadata():
    url = "https://redtaperecordings.com/m/x"
    text = social.compose_post(None, None, None, url)
    assert text.endswith(url)
    assert "A public meeting" in text


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
