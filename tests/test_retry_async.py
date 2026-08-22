"""Tests for app/utils/retry.py -- the shared exponential-backoff policy
scripts/transcribe_backlog_locally.py and worker/main.py both use around
their live-source calls (finder.resolve(), probe_duration(),
extract_chunk_audio()).

SYNTHETIC by necessity, and narrowly so: what's under test here is a
control-flow policy (how many times, on which failure shapes, with what
delay), not a parser reading a real page. The real-world *shape* it has to
match is the confirmed one from BACKLOG.md -- an operation that fails once
and then succeeds unchanged minutes later -- which is precisely what a
counting fake reproduces exactly and a live government source reproduces
only by luck. The callers' own integration with it is covered against
their real code paths in tests/test_transcribe_backlog_locally.py and
tests/test_worker_auto_generation.py.
"""

import logging

import pytest

from app.utils.retry import backoff_delay, retry_async

logger = logging.getLogger("test_retry_async")


# Every test below passes millisecond delays rather than mocking sleep
# away: the real backoff mechanism (a real asyncio.sleep of a real
# jittered, computed delay) still runs, it just doesn't spend the
# production 5-15s window. Same approach tests/test_transcribe_backlog_
# locally.py already takes with _request_json()'s own retry loop.


class _FlakyOperation:
    """Fails `fail_times` times, then succeeds -- the confirmed real
    pattern (Diamond Bar CA, Genesee County MI, Sullivan County NY and 3 of
    4 new.swagit.com extractions all succeeded on an unchanged re-run)."""

    def __init__(self, fail_times: int, error: Exception):
        self.fail_times = fail_times
        self.error = error
        self.calls = 0

    async def __call__(self):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.error
        return "resolved"


async def test_retries_an_operation_that_fails_once_then_succeeds():
    op = _FlakyOperation(1, TimeoutError())
    result = await retry_async(
        op,
        label="test resolve",
        attempts=2,
        base_delay=0.001,
        max_delay=0.002,
        logger=logger,
    )
    assert result == "resolved"
    assert op.calls == 2


async def test_a_permanently_failing_operation_raises_after_its_attempts():
    """A genuinely broken source must still fail -- and must not be tried
    more times than the policy allows (an unattended overnight run's time
    is the budget being protected)."""
    op = _FlakyOperation(99, RuntimeError("source is really gone"))
    with pytest.raises(RuntimeError, match="really gone"):
        await retry_async(
            op,
            label="test resolve",
            attempts=2,
            base_delay=0.001,
            max_delay=0.002,
            logger=logger,
        )
    assert op.calls == 2


async def test_a_permanent_exception_type_is_not_retried_at_all():
    """The 4xx-equivalent: an unregistered platform can't start working
    mid-run, so it must fail on the first attempt with no backoff."""

    class _Permanent(Exception):
        pass

    op = _FlakyOperation(99, _Permanent("no finder for this platform"))
    with pytest.raises(_Permanent):
        await retry_async(
            op,
            label="test resolve",
            attempts=5,
            base_delay=0.001,
            max_delay=0.002,
            logger=logger,
            permanent_exceptions=(_Permanent,),
        )
    assert op.calls == 1


async def test_retries_a_returned_failure_value_then_returns_the_success():
    """extract_chunk_audio()/probe_duration() report failure by *returning*
    it, not raising -- the shape this branch exists for."""
    outcomes = [(False, "ffmpeg timed out after 120s"), (True, None)]
    calls = []

    async def op():
        calls.append(1)
        return outcomes[len(calls) - 1]

    result = await retry_async(
        op,
        label="test extraction",
        attempts=2,
        base_delay=0.001,
        max_delay=0.002,
        logger=logger,
        retryable_failure=lambda o: None if o[0] else o[1],
    )
    assert result == (True, None)
    assert len(calls) == 2


async def test_a_non_retryable_returned_failure_stops_immediately():
    """`retryable_failure` returning None means "hand this back to the
    caller now" -- for a success *or* for a failure retrying can't fix
    (ffmpeg missing from PATH). Confirms the second case doesn't sleep and
    try again."""
    calls = []

    async def op():
        calls.append(1)
        return (False, "ffmpeg not found on PATH")

    result = await retry_async(
        op,
        label="test extraction",
        attempts=5,
        base_delay=0.001,
        max_delay=0.002,
        logger=logger,
        retryable_failure=lambda o: (
            None if o[0] or "not found on PATH" in (o[1] or "") else o[1]
        ),
    )
    assert result == (False, "ffmpeg not found on PATH")
    assert len(calls) == 1


async def test_a_still_failing_returned_value_comes_back_to_the_caller():
    """After the last attempt, a value-shaped failure is returned rather
    than raised -- the callers' existing `if not extracted:` handling has
    to keep working unchanged."""
    calls = []

    async def op():
        calls.append(1)
        return (False, "ffmpeg timed out after 120s")

    result = await retry_async(
        op,
        label="test extraction",
        attempts=2,
        base_delay=0.001,
        max_delay=0.002,
        logger=logger,
        retryable_failure=lambda o: None if o[0] else o[1],
    )
    assert result == (False, "ffmpeg timed out after 120s")
    assert len(calls) == 2


def test_backoff_delay_grows_and_is_capped():
    """The arithmetic itself, jitter included: every delay stays inside the
    0.5-1.5x jitter window around base * 2**attempt, and nothing exceeds
    max_delay."""
    for _ in range(50):
        assert 5.0 <= backoff_delay(0, base_delay=10.0, max_delay=60.0) <= 15.0
        assert 10.0 <= backoff_delay(1, base_delay=10.0, max_delay=60.0) <= 30.0
        assert backoff_delay(10, base_delay=10.0, max_delay=60.0) == 60.0
