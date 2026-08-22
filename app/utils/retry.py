"""One shared exponential-backoff-with-jitter retry policy, for the places
that call out to a *live government media source* and can't tell a
permanently-broken meeting apart from a source that was busy for ten
seconds.

Why this exists as a shared helper rather than a third hand-rolled loop:
the same policy shape was already written twice in this repo --
`app/platforms/granicus.py`'s `_fetch_page()` (`(2**attempt) *
random.uniform(0.5, 1.5)`) and `scripts/transcribe_backlog_locally.py`'s
`_request_json()` (the same shape with a bigger base delay, and a
deliberately narrower "what counts as retryable" predicate). When
`transcribe_backlog_locally.py` and `worker/main.py` both needed the same
treatment around `finder.resolve()`/`extract_chunk_audio()`/
`probe_duration()`, the choice was a third copy or this. See BACKLOG.md's
"`transcribe_backlog_locally.py` gives up on a live meeting after one
transient failure" entry for the ten-plus confirmed real cases that
prompted it.

**The discipline this carries over from `_request_json()` matters more
than the arithmetic**: a retry must not paper over a permanently-broken
target. `_request_json()` retries 5xx and connection-level failures but
fails a 4xx immediately, because a bad token can't be waited out. The same
split applies here, just against different failure shapes:

* an exception type that means "this will never work" (an unregistered
  platform) is listed in `permanent_exceptions` and re-raised on the first
  attempt, un-retried and un-delayed;
* a *returned* failure value (`extract_chunk_audio()` -> `(False,
  reason)`, `probe_duration()` -> `None`) is only retried when
  `retryable_failure` says so -- "ffmpeg not found on PATH" is a broken
  machine, not a flaky CDN, and waiting 15 seconds won't install it.

Lives under `app/utils/` (not `worker/`) so the worker and the local
script can both import it without `app/` ever depending on `worker/` --
the same one-way dependency direction `app/platforms/media_probe.py`'s
docstring spells out.
"""

import asyncio
import logging
import random
from typing import Awaitable, Callable, Optional, Sequence, TypeVar

T = TypeVar("T")


def backoff_delay(attempt: int, *, base_delay: float, max_delay: float) -> float:
    """Seconds to wait before attempt number `attempt + 1` (`attempt` is
    0-based, so the first retry uses `attempt=0`). Exponential in the
    attempt, multiplied by real jitter so a batch that trips the same
    rate-limit on several meetings in a row doesn't retry all of them in
    lockstep -- same `(2**attempt) * random.uniform(0.5, 1.5)` shape
    `granicus.py` and `_request_json()` already use, capped at
    `max_delay`.
    """
    return min(max_delay, base_delay * (2**attempt) * random.uniform(0.5, 1.5))


async def retry_async(
    operation: Callable[[], Awaitable[T]],
    *,
    label: str,
    attempts: int,
    base_delay: float,
    max_delay: float,
    logger: logging.Logger,
    permanent_exceptions: Sequence[type] = (),
    retryable_failure: Optional[Callable[[T], Optional[str]]] = None,
) -> T:
    """Await `operation()` up to `attempts` times, backing off between
    tries. Returns whatever the operation returned.

    `attempts` is the *total* number of tries, not the number of retries --
    `attempts=2` means "try, and if that fails try once more", which is the
    settled default for the live-media calls (see the callers' own
    constants and the Brookhaven NY note there: one retry demonstrably
    isn't enough for every real case, which is exactly why the count is a
    tunable constant and not a hard-coded `2` in a loop).

    Two failure shapes, deliberately handled differently:

    * **The operation raises.** Anything in `permanent_exceptions`
      propagates immediately -- no sleep, no retry, no log noise -- so a
      genuinely-permanent failure stays as fast and as clearly reported as
      it was before any of this existed. Any other exception is retried,
      and if the final attempt also raises, that last exception propagates
      to the caller unchanged (so existing `except` blocks around the call
      site keep working).
    * **The operation returns a failure value.** `retryable_failure(result)`
      returns a short reason string to retry, or `None` to stop and hand
      the result straight back to the caller. `None` therefore covers both
      "this succeeded" and "this failed in a way retrying cannot fix" --
      in both cases the helper's job is done and the caller's own existing
      failure handling takes over. Omit `retryable_failure` entirely for an
      operation that signals failure only by raising.
    """
    last_result: Optional[T] = None
    for attempt in range(attempts):
        failure: Optional[str] = None
        try:
            result = await operation()
        except tuple(permanent_exceptions):
            raise
        except Exception as e:
            if attempt == attempts - 1:
                raise
            failure = f"{type(e).__name__}: {str(e)[:200]}"
        else:
            last_result = result
            failure = retryable_failure(result) if retryable_failure else None
            if failure is None:
                return result
            if attempt == attempts - 1:
                return result

        delay = backoff_delay(attempt, base_delay=base_delay, max_delay=max_delay)
        logger.warning(
            "%s failed (attempt %d/%d): %s -- retrying in %.0fs "
            "(this is an automatic retry, not the process hanging)",
            label,
            attempt + 1,
            attempts,
            failure,
            delay,
        )
        await asyncio.sleep(delay)

    # Unreachable for attempts >= 1: the final attempt above either
    # returns or raises. Kept as a real value rather than an assert so a
    # nonsensical attempts=0 degrades to "did nothing" instead of raising
    # something unrelated from inside a retry helper.
    return last_result  # type: ignore[return-value]
