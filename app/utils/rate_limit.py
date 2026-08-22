"""Recognising "the far end is refusing us", as distinct from "this one
page failed".

Exists because of a real, measured incident (2026-08-22): a bulk
re-resolve hit `HTTP Error 429: Too Many Requests` on ten consecutive
YouTube-backed pages, and both driver scripts kept going -- one because
its circuit-breaker threshold was only checked on a different failure
path, the other because it had no breaker at all. Across two runs that
sent 20 requests to an endpoint refusing every one, which plausibly
extends the block being hit. A retry ten minutes later at 60s spacing
failed identically on its *first* request, so this is a sustained block
on the caller, not a per-request throttle something can pace around.

The rule that follows: a rate-limit signal is not a per-page failure to
log and move past. It means stop the run.
"""

import re

# 429 is the explicit signal. The text forms are what actually reaches a
# caller here: aiohttp/urllib raise `HTTP Error 429: Too Many Requests`,
# and yt-dlp surfaces YouTube's block as prose without a status code --
# both were seen in the 2026-08-22 run. Matching the message rather than
# a status field is deliberate: these arrive as strings by the time the
# driver scripts see them.
_RATE_LIMIT_RE = re.compile(
    r"(?:\b429\b"
    r"|too many requests"
    r"|rate[- ]?limit"
    r"|sign in to confirm(?:.{0,40})?not a bot"
    r"|temporarily blocked)",
    re.IGNORECASE,
)


def looks_rate_limited(message: object) -> bool:
    """True when `message` reads like the far end refusing the caller
    rather than one page being broken.

    Deliberately permissive on input type -- callers pass exception
    objects, result dicts' detail strings, and plain text.
    """
    if message is None:
        return False
    return bool(_RATE_LIMIT_RE.search(str(message)))
