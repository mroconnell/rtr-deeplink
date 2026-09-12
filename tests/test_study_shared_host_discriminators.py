"""Tests for scripts/study_shared_host_discriminators.py's adaptive pacing.

Video ids below are synthetic placeholders -- this only exercises the
delay/backoff bookkeeping around a mocked oEmbed call, no identity
resolution (see CLAUDE.md's "Synthetic tests" convention).
"""

import asyncio

import pytest

from scripts import study_shared_host_discriminators as study


@pytest.mark.asyncio
async def test_fetch_lookups_backs_off_after_a_miss_and_recovers_after_a_hit(
    monkeypatch,
):
    # ok, miss, ok, miss, miss, ok -- exercises both a lone miss and a
    # run of consecutive misses.
    outcomes = [
        {"author_url": "https://x/@a", "author_name": "Channel A"},
        None,
        {"author_url": "https://x/@c", "author_name": "Channel C"},
        None,
        None,
        {"author_url": "https://x/@f", "author_name": "Channel F"},
    ]

    async def fake_oembed(session, family, video_id):
        return outcomes.pop(0)

    monkeypatch.setattr(study, "_oembed", fake_oembed)
    monkeypatch.setattr(study, "save_cache", lambda cache: None)

    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    keys = [f"youtube:{c}" for c in "abcdef"]
    stats = await study.fetch_lookups(keys, {}, delay=121.0, backoff_delay=180.0)

    assert sleeps == [121.0, 180.0, 121.0, 180.0, 180.0, 121.0]
    assert stats["youtube_ok"] == 3
    assert sum(v for k, v in stats.items() if k.startswith("youtube_miss")) == 3


@pytest.mark.asyncio
async def test_fetch_lookups_defaults_backoff_to_delay_when_unset(monkeypatch):
    async def fake_oembed(session, family, video_id):
        return None  # every lookup misses

    monkeypatch.setattr(study, "_oembed", fake_oembed)
    monkeypatch.setattr(study, "save_cache", lambda cache: None)

    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    await study.fetch_lookups(["youtube:zzzzzzzzzzz"], {}, delay=0.6)

    assert sleeps == [0.6]
