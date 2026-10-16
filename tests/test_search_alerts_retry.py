"""archive_client.send_search_alerts() retries an Archive restart blip
(2026-09-17: a 502 while the Archive was restarting skipped that day's
saved-search alerts)."""

from unittest import mock

import aiohttp
import pytest

from app import archive_client
from aiohttp_mock import FakeResponse


@pytest.fixture
def archive_env(monkeypatch):
    monkeypatch.setenv("ARCHIVE_BASE_URL", "https://archive.example.test")
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(archive_client.asyncio, "sleep", fake_sleep)
    return sleeps


def _sequence(monkeypatch, outcomes):
    calls = []

    def fake_post(self, url, **kwargs):
        calls.append(url)
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(aiohttp.ClientSession, "post", fake_post)
    return calls


async def test_retries_a_502_then_returns_the_result(monkeypatch, archive_env):
    calls = _sequence(
        monkeypatch,
        [
            FakeResponse(status=502, text="Bad Gateway"),
            FakeResponse(status=200, text='{"sent": 3}'),
        ],
    )
    assert await archive_client.send_search_alerts() == {"sent": 3}
    assert len(calls) == 2
    assert archive_env == [5]


async def test_retries_a_refused_connection(monkeypatch, archive_env):
    refused = aiohttp.ClientConnectorError(mock.Mock(), OSError("refused"))
    calls = _sequence(
        monkeypatch, [refused, refused, FakeResponse(status=200, text="{}")]
    )
    assert await archive_client.send_search_alerts() == {}
    assert len(calls) == 3
    assert archive_env == [5, 10]


async def test_gives_up_after_the_last_retry(monkeypatch, archive_env):
    calls = _sequence(monkeypatch, [FakeResponse(status=503, text="")] * 3)
    assert await archive_client.send_search_alerts() is None
    assert len(calls) == 3


async def test_does_not_retry_a_client_error_or_timeout(monkeypatch, archive_env):
    calls = _sequence(monkeypatch, [FakeResponse(status=401, text="no")])
    assert await archive_client.send_search_alerts() is None
    assert len(calls) == 1

    calls = _sequence(monkeypatch, [TimeoutError()])
    assert await archive_client.send_search_alerts() is None
    assert len(calls) == 1
    assert archive_env == []
