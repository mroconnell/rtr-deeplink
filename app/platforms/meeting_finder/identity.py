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
checking at all. The two modes differ only in bookkeeping: `mode` records
which was asked for, and `expected_gov_id` is `finder_input.gov_id` in
both -- pin mode's caller supplies the government it believes is right,
audit mode's caller supplies the pin's own gov_id (the thing being
audited).
"""

from __future__ import annotations

import contextlib
from typing import Optional
from urllib.parse import urlparse

from app.platforms.models import ResolvedMeeting
from app.utils.gov_registry import resolver as gov_resolver
from app.utils.gov_registry.resolver import (
    TIER_BLANK,
    page_hints_for,
    resolve_government,
)

from .models import FinderInput, IdentityCheck


@contextlib.contextmanager
def tenant_pin_switched_off(host: str):
    """Scoped for the duration of one call, same idiom
    `app/platforms/base.py`'s `youtube_resolve_guard()` already uses:
    monkey-patch the one function every pin lookup goes through
    (`resolver._override_rows_for_host()`), so it answers "no rows" for
    `host` specifically, then restore the original on exit.

    Deliberately not a global/process-wide change and not a mutation of
    `registry.tenant_overrides()`'s cached table (which every OTHER
    caller in the process -- a concurrent request, a different Meeting
    Finder input on another host -- shares): patching the lookup function
    for the scope of this one `with` block means a different host's pin
    resolves normally even while this one's is switched off, and a
    caller elsewhere in the same process that isn't inside this block is
    never affected, exactly like `youtube_resolve_guard()`'s own reasoning
    for patching a class method rather than mutating shared state.
    """
    host = (host or "").lower()
    original = gov_resolver._override_rows_for_host

    def _patched(h: str):
        if h.lower() == host:
            return []
        return original(h)

    gov_resolver._override_rows_for_host = _patched
    try:
        yield
    finally:
        gov_resolver._override_rows_for_host = original


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

    resolved_gov_id = None if match.tier == TIER_BLANK else match.gov_id

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
