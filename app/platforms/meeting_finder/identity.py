"""The identity check (WO-1024): does a resolved meeting's own content
agree with the government we believe it belongs to?

docs/MEETING_FINDER.md's "Pin mode and audit mode" section: "A `gov_id`
is sometimes wrong, so Verdict always checks it against what the meeting
itself says." That "always" is the interface detail this module settles
(not fully spelled out in the design doc, recorded in docs/
MEETING_FINDER.md's Status section as of this WO): **both modes derive
"what the meeting itself says" the same way** -- by running
`resolve_government()` (`app/utils/gov_registry/resolver.py`) with the
account's own `tenant_overrides.csv` pin switched off, so the answer
always comes from the page's own content, never an echo of the pin that
produced `gov_id` in the first place. The design doc's own warning
("Without switching the pin off, the resolver would just echo the pin
back") applies just as much to pin mode -- a host that already carries a
whole-tenant pin would otherwise always "agree" with itself regardless of
what the specific meeting page actually said, which defeats the point of
checking at all. `mode` records which was asked for, and `expected_gov_id`
is `finder_input.gov_id` in both.

**What actually distinguishes the two modes, since the derivation is
identical (conductor's question, 2026-09-23):** not this module's own
mechanism, but what the `gov_id` MEANS and what a caller does with the
answer. **Pin mode**'s `gov_id` is already the value in active use --
docs/MEETING_FINDER.md's design and CLAUDE.md's "send the government's
id in every ingest payload" rule both treat a pin-mode `gov_id` as the
one an ingest would carry forward regardless of this check; Identity here
is a QA backstop that flags a disagreement without being the thing that
decided the government. **Audit mode**'s `gov_id` IS the thing under
test -- a `tenant_overrides.csv` pin being audited for whether it's still
right, per the design doc's own framing ("Verdict reports agrees/
disagrees/page-says-nothing... without switching the pin off, the
resolver would just echo the pin back"). A `disagrees`/`silent` verdict
in audit mode is the actual finding a human acts on (keep, fix, or
remove the pin); in pin mode it's a caution alongside a result that's
still otherwise usable. Meeting Finder itself never writes anything
either way -- `verdict.py` is read-only in both modes; a pin only ever
gets fixed by a human (or a later, separate tool) reading Verdict's
output.
"""

from __future__ import annotations

import contextlib
import contextvars
from typing import FrozenSet, Optional
from urllib.parse import urlparse

from app.platforms.models import ResolvedMeeting
from app.utils.gov_registry import resolver as gov_resolver
from app.utils.gov_registry.resolver import (
    TIER_BLANK,
    page_hints_for,
    resolve_government,
)

from .models import FinderInput, IdentityCheck

# Task-local (asyncio) set of hosts currently switched off -- see
# `tenant_pin_switched_off()`'s own docstring for why this replaced an
# earlier, broken version of this function that reassigned
# `gov_resolver._override_rows_for_host` directly on each call.
_SWITCHED_OFF_HOSTS: "contextvars.ContextVar[FrozenSet[str]]" = contextvars.ContextVar(
    "meeting_finder_switched_off_hosts", default=frozenset()
)

# The real function, captured once. Guarded by an attribute on the
# wrapper itself (not just "run this module-level code once", which
# `import`'s own caching already guarantees in the ordinary case) so that
# a test harness reloading this module -- `importlib.reload()`, or two
# independent import paths landing on the same module object -- can never
# wrap an already-wrapped function and lose the real one.
_already_installed = getattr(
    gov_resolver._override_rows_for_host, "_mf_switch_off_wrapper", False
)
_original_override_rows_for_host = (
    gov_resolver._override_rows_for_host._mf_real
    if _already_installed
    else gov_resolver._override_rows_for_host
)


def _override_rows_for_host_respecting_switch_off(host: str):
    if host.lower() in _SWITCHED_OFF_HOSTS.get():
        return []
    return _original_override_rows_for_host(host)


_override_rows_for_host_respecting_switch_off._mf_switch_off_wrapper = True
_override_rows_for_host_respecting_switch_off._mf_real = (
    _original_override_rows_for_host
)

# Installed ONCE (idempotent, per the guard above), at import time, and
# never touched again after this -- this is the only reassignment of
# `gov_resolver._override_rows_for_host` this module ever does. It is
# permanent and process-wide, but it is also a pure function of
# `_SWITCHED_OFF_HOSTS`, which is what actually varies per caller -- see
# `tenant_pin_switched_off()` below.
gov_resolver._override_rows_for_host = _override_rows_for_host_respecting_switch_off


@contextlib.contextmanager
def tenant_pin_switched_off(host: str):
    """Scoped for the duration of one call: while active, `host`'s
    `tenant_overrides.csv` pin is invisible to
    `resolver._override_rows_for_host()` (the one function every pin
    lookup goes through), so `resolve_government()` answers purely from
    the page's own content. Restored on exit.

    **Correction (conductor review, 2026-09-23): this used to reassign
    `gov_resolver._override_rows_for_host` directly on entry/exit** --
    broken under concurrency (the runner's own `--concurrency` flag can
    reach it): task A saves the real function and installs its own
    switched-off wrapper; task B, running concurrently, saves what it
    sees (A's wrapper, not the real function) and installs its own; A
    finishes first and restores what IT saved (the real function) --
    silently undoing B's switch-off while B is still inside its `with`
    block; B then finishes and restores what it saved (A's wrapper,
    which no longer does anything useful) -- A's host stays switched off
    for the rest of the run. Two overlapping callers corrupt each other's
    state and the process is left in neither original nor either
    intended state.

    **Fix**: install one wrapper on `gov_resolver._override_rows_for_host`
    permanently, at import time (`_override_rows_for_host_respecting_
    switch_off()` above), and never touch that attribute again. The
    wrapper consults a `contextvars.ContextVar` holding the current SET
    of switched-off hosts. A `ContextVar` is task-local under asyncio --
    each `asyncio.Task` (from `asyncio.create_task()`/`gather()`, which
    is how `runner.py`'s `--concurrency` fans out) gets its own copy of
    the context at creation, so one task's `.set()` is invisible to a
    sibling task and to the task that created it, and `.reset(token)`
    restores exactly the prior value even across nested/nested-looking
    calls. Two concurrent tasks each switching off a DIFFERENT host see
    only their own -- proven by `tests/test_wo1024_meeting_finder_
    identity.py`'s `test_concurrent_switch_off_is_task_local`, which runs
    two overlapping `asyncio.gather()`'d checks and asserts each only
    ever sees its own host switched off, with both fully restored
    afterward.

    An explicit resolver parameter (threading a "skip this host's pin"
    flag through `resolve_government()`/`_resolve_government_ladder()`/
    `_pinned()`/`_matched_multi_gov_pin()`) was the other option
    considered -- rejected because it would touch several functions deep
    in `resolver.py` for behavior that is entirely Meeting Finder's own
    (nothing else in this codebase ever wants to see a pin switched off),
    versus this module owning the one, contained wrapper.
    """
    host = (host or "").lower()
    current = _SWITCHED_OFF_HOSTS.get()
    token = _SWITCHED_OFF_HOSTS.set(current | {host})
    try:
        yield
    finally:
        _SWITCHED_OFF_HOSTS.reset(token)


def check_identity(
    resolved_meeting: Optional[ResolvedMeeting], finder_input: FinderInput
) -> IdentityCheck:
    """See this module's docstring for how "what the meeting itself
    says" is derived, identically in pin and audit mode.

    `resolved_meeting=None` (nothing was resolved -- Resolve came back
    with an outcome instead of a meeting) or no `gov_id` on the input
    both mean there is nothing to check: `verdict="not-checked"`.
    """
    expected = finder_input.gov_id

    if resolved_meeting is None:
        return IdentityCheck(
            mode=finder_input.mode,
            expected_gov_id=expected,
            resolved_gov_id=None,
            resolved_tier=None,
            verdict="not-checked",
        )

    parsed = urlparse(resolved_meeting.source_url or "")
    host = (parsed.netloc or "").lower().split(":")[0]
    path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    hints = page_hints_for(
        resolved_meeting.platform,
        resolved_meeting.external_id,
        channel=resolved_meeting.video_channel,
    )

    with tenant_pin_switched_off(host):
        match = resolve_government(
            resolved_meeting.jurisdiction,
            tenant_host=host,
            path=path,
            page_hints=hints,
            origin_host=resolved_meeting.origin_host,
        )

    # WO-1031: an empty gov_id (a name the ladder couldn't key) is "the page
    # says nothing we can match", not a disagreement -- Pomona and Piedmont
    # reported "disagrees" with no government at all before this fix.
    resolved_gov_id = (
        None if match.tier == TIER_BLANK or not match.gov_id else match.gov_id
    )

    if expected is None:
        verdict = "not-checked"
    elif resolved_gov_id is None:
        verdict = "silent"
    elif resolved_gov_id == expected:
        verdict = "agrees"
    else:
        verdict = "disagrees"

    return IdentityCheck(
        mode=finder_input.mode,
        expected_gov_id=expected,
        resolved_gov_id=resolved_gov_id,
        resolved_tier=match.tier,
        verdict=verdict,
        points_to=resolved_gov_id if verdict == "disagrees" else None,
    )
