"""WO-181 (2026-09-10): shared helper for trying a government's alternate
domains/URLs before recording an access reject.

Why this exists: WO-165 added two columns to
`~/Documents/rtr-business/research/jurisdiction_coverage.csv` --
`alternate_domains` and `alternate_urls` (semicolon-separated, every real
domain or URL a government was ever recorded under, never dropped --
Ryan's rule that several ways into the same government is a good thing).
Nothing reads them yet: every sweep script in this directory only looks
at the row's `domain`. This module is the one place that logic lives, so
future sweep scripts import it rather than re-deriving it.

Scope, deliberately narrow (Ryan's WO-181 instructions): only an
ACCESS-class reject on the primary domain is worth retrying against an
alternate. A CONTENT-class reject means we successfully reached a real
page and it genuinely had no platform link / no video / etc -- trying a
different hostname for the SAME government's website does not change
that answer, so this module does not retry those. That's a scope
decision, not an oversight -- see the residual-gap BACKLOG.md entry filed
alongside this WO for the case (content-class retry, and treating
`alternate_urls` as direct meeting-URL candidates) that's still open.

Two reason taxonomies, from docs/BREADTH_SWEEP_BRIEF.md's "Reject
reasons, two classes" section (the shared vocabulary every sweep script
writes into `reject_reason`):

- ACCESS_REASONS: we could not even read the host. Worth trying again,
  including against an alternate domain.
- CONTENT_REASONS: we read the host fine and there was genuinely nothing
  there. Not worth retrying, on any domain, until the platform itself
  gains a new signal.

`no-video-found` / `no-meetings-found` are the pre-2026-09-10 spellings
of `meeting-without-video` / `no-meeting-nor-video` (WO-164's retag);
both are included here so a row written before the rename still
classifies correctly without needing to be retagged first.

This module is import-only: it has no top-level side effects (no network
calls, no file opens, no registering of platform finders) so it is safe
for any script to `import scripts.coverage_alternates as ca` regardless
of what else that script does at import time.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

ACCESS_REASONS = frozenset(
    {
        "blocked-plain-http",
        "blocked-browser-headers",
        "blocked-headless",
        "cloudflare-challenge-blocked",
        "dns-unresolvable",
        "timeout",
    }
)

CONTENT_REASONS = frozenset(
    {
        "no-platform-link-found",
        "meeting-without-video",
        "no-meeting-nor-video",
        "video-without-meeting",
        "off-mission",
        "unsupported-platform-no-adapter",
        # pre-2026-09-10 spellings (WO-164 retag) -- same meaning, kept so
        # an un-retagged row still classifies right.
        "no-video-found",
        "no-meetings-found",
    }
)

# A ladder_fn signals success with this reason string (never a real
# reject_reason value -- kept out of both sets above on purpose so a
# careless membership check can't confuse it with a content reject).
FOUND = "found"


def normalize_host(value: Optional[str]) -> str:
    """Bare lowercase host, no scheme/path/port/userinfo. '' for blank
    input. Does not strip a leading 'www.' -- 'www.x.com' and 'x.com' are
    kept as distinct candidates, since alternate_domains may legitimately
    record either form and the access ladder itself already tries the
    www/non-www variant of whichever one it's given (see
    run_access_ladder's own candidate-URL construction in
    wo147_access_ladder_sweep.py)."""
    v = (value or "").strip()
    if not v:
        return ""
    if "://" not in v:
        v = "https://" + v
    parsed = urlparse(v)
    host = parsed.netloc or parsed.path
    if "@" in host:
        host = host.rsplit("@", 1)[-1]
    if ":" in host:
        host = host.split(":", 1)[0]
    return host.strip().strip("/").lower()


def candidate_domains(row: Dict[str, Any]) -> List[str]:
    """Primary `domain` first, then each entry of `alternate_domains` in
    file order, then the host of each entry of `alternate_urls` in file
    order -- normalised, deduplicated (first occurrence wins), blanks
    skipped."""
    out: List[str] = []
    seen = set()

    def add(raw: Optional[str]) -> None:
        host = normalize_host(raw)
        if host and host not in seen:
            seen.add(host)
            out.append(host)

    add(row.get("domain"))
    for d in (row.get("alternate_domains") or "").split(";"):
        add(d)
    for u in (row.get("alternate_urls") or "").split(";"):
        add(u)
    return out


@dataclass
class LadderOutcome:
    """What one ladder_fn call against one candidate domain found.

    `reason` is either FOUND (a real platform link was located) or a
    value from ACCESS_REASONS / CONTENT_REASONS. `detail` is a free-text
    note (which rung answered, a WAF family, an exception message) for
    the report row -- ladder_with_alternates never inspects it, only
    passes it through."""

    reason: str
    platform: Optional[str] = None
    hit_url: Optional[str] = None
    rung: str = ""  # "plain" | "browser-headers" | "headless" | "api" | ""
    detail: str = ""


@dataclass
class AlternatesResult:
    outcome: LadderOutcome
    answered_domain: str
    trail: List[Tuple[str, str]] = field(default_factory=list)  # (domain, reason)

    @property
    def alternates_tried(self) -> str:
        """Every candidate domain actually tried, in order, semicolon-
        joined -- for the report CSV's `alternates_tried` column."""
        return ";".join(domain for domain, _ in self.trail)


LadderFn = Callable[[str, Dict[str, Any]], Awaitable[LadderOutcome]]


async def ladder_with_alternates(
    row: Dict[str, Any],
    ladder_fn: LadderFn,
    *,
    max_candidates: Optional[int] = None,
    between_candidates_seconds: float = 0.0,
) -> AlternatesResult:
    """Runs `ladder_fn` on the primary domain; if the result is an
    ACCESS-class reason, tries the next candidate domain, and so on.
    Stops at the first FOUND or CONTENT-class answer. Returns the
    winning (or last-tried, if every candidate stayed ACCESS-class)
    outcome plus the answering domain and the full per-domain trail.

    `ladder_fn(domain, row) -> LadderOutcome` is supplied by the caller
    -- this function has no opinion on how a domain is actually fetched
    (plain HTTP, browser headers, headless, a platform API), so the same
    helper serves a rung-restricted pilot and a future full-ladder sweep
    alike. See this module's docstring for why WO-181's own pilot passes
    a rungs-2/3-only ladder_fn rather than wo147's full
    `run_access_ladder` (which also falls back to headless)."""
    candidates = candidate_domains(row)
    if max_candidates is not None:
        candidates = candidates[:max_candidates]

    trail: List[Tuple[str, str]] = []
    last_outcome: Optional[LadderOutcome] = None
    last_domain = ""

    for i, domain in enumerate(candidates):
        if i and between_candidates_seconds:
            await asyncio.sleep(between_candidates_seconds)
        outcome = await ladder_fn(domain, row)
        trail.append((domain, outcome.reason))
        last_outcome = outcome
        last_domain = domain
        if outcome.reason == FOUND or outcome.reason in CONTENT_REASONS:
            return AlternatesResult(outcome, domain, trail)
        # else: ACCESS-class (or an unrecognized reason -- treated the
        # same as ACCESS, since an unknown answer is not a confirmed
        # content dead-end) -- fall through and try the next candidate.

    if last_outcome is None:
        # no candidates at all (a row with a blank domain and no
        # alternates) -- report it plainly rather than raising.
        last_outcome = LadderOutcome(
            reason="dns-unresolvable", detail="no candidate domains"
        )
    return AlternatesResult(last_outcome, last_domain, trail)


def classify_wo147_ladder_result(result: Any) -> LadderOutcome:
    """Maps a `wo147_access_ladder_sweep.LadderResult` onto this module's
    taxonomy, for a future full-ladder (rungs 1-4, headless included)
    sweep that wants to reuse `run_access_ladder` directly as a
    `ladder_fn`. Not used by WO-181's own pilot (which is rungs 2/3 only,
    see `rungs_2_3_ladder_fn` below) -- kept here so the mapping is
    written once, in the one place both the pilot and any future
    full-ladder caller can share it."""
    access_mode = getattr(result, "access_mode", "")
    platform = getattr(result, "platform", None)
    hit_url = getattr(result, "hit_url", None)
    note = getattr(result, "note", "") or ""

    if platform and hit_url:
        return LadderOutcome(
            reason=FOUND,
            platform=platform,
            hit_url=hit_url,
            rung=access_mode,
            detail=note,
        )

    _ACCESS_MODE_TO_REASON = {
        "dead": "dns-unresolvable",
        "challenge": "cloudflare-challenge-blocked",
        "blocked-plain-http": "blocked-plain-http",
        "blocked-browser-headers": "blocked-browser-headers",
        "timeout": "timeout",
    }
    if access_mode in _ACCESS_MODE_TO_REASON:
        return LadderOutcome(
            reason=_ACCESS_MODE_TO_REASON[access_mode], rung=access_mode, detail=note
        )

    # Reached the page fine (access_mode "plain"/"browser-headers"/
    # "headless") but no platform link found anywhere in the ladder --
    # a content-class answer, not an access one.
    return LadderOutcome(reason="no-platform-link-found", rung=access_mode, detail=note)


def rungs_2_3_ladder_fn(
    session: Any,
    honest_headers: Dict[str, str],
    browser_headers: Dict[str, str],
    fetch_one: Callable[[Any, str, Dict[str, str]], Awaitable[Any]],
    is_challenge: Callable[[str], bool],
    find_platform_link: Callable[[str, str], Optional[Tuple[str, str]]],
    *,
    host_delay_seconds: float = 2.0,
) -> LadderFn:
    """Builds a ladder_fn restricted to WO-181's pilot rungs: plain
    honest HTTP, then browser headers once -- only after a 403 or a
    dropped connection, never after a 404 -- and NO headless fallback at
    all. This is a deliberate, narrower ladder than
    `wo147_access_ladder_sweep.run_access_ladder` (which also falls back
    to headless when a page has no visible meeting link); WO-181's brief
    is explicit that this pilot must not use headless, so rather than
    editing that shared script (it is being run by other active
    sweeps right now) or calling it and hoping a code path never
    triggers, this builds a standalone, smaller ladder from the SAME
    primitives -- headers, challenge detection, and platform-link
    scanning are imported unchanged from wo147_access_ladder_sweep by the
    caller and passed in here, so "does this page have a real platform
    link" is judged identically to every other sweep in this repo.

    All the pure helpers this needs (HONEST_HEADERS, BROWSER_HEADERS,
    fetch_one, is_challenge, find_platform_link) are module-level
    constants/functions in wo147_access_ladder_sweep.py.
    Importing that module to reach them is safe for a caller that never
    touches `wo134_confirmed_hits_ingest.process_row()` -- confirmed:
    `register_all_finders()` and every file/network access in that
    module happen inside `main()`, which only runs under
    `if __name__ == "__main__"`. One real import-time side effect DOES
    exist though: the module's own top level runs
    `wo134.TIER3_HANDLER = tier3_pending_handler` unconditionally,
    pointing that shared hook at wo147's own pending-CSV writer. Harmless
    for a caller (like scripts/wo181_pilot.py) that only imports these
    header/parsing primitives and never calls `wo134.process_row()`
    itself -- but a script that DOES call `process_row()` (WO-181's own
    ingest step, once a pilot row is FOUND) must set `wo134.TIER3_HANDLER`
    itself, AFTER importing `wo134_confirmed_hits_ingest` directly, and
    must NOT import wo147_access_ladder_sweep at all, or that import
    silently overwrites the hook back to wo147's handler/pending file.
    -- see scripts/wo181_pilot.py for this function's own wiring, and
    scripts/wo181_ingest_found.py for the process_row-calling case.
    """

    async def _fetch(url: str, headers: Dict[str, str]) -> Any:
        return await fetch_one(session, url, headers)

    async def ladder_fn(domain: str, row: Dict[str, Any]) -> LadderOutcome:
        url = domain if "://" in domain else f"https://{domain}"

        r = await _fetch(url, honest_headers)

        if getattr(r, "error_kind", "") == "dns":
            return LadderOutcome(
                reason="dns-unresolvable", rung="plain", detail=r.error or ""
            )

        if getattr(r, "error_kind", "") == "timeout" and r.status is None:
            await asyncio.sleep(host_delay_seconds)
            rb = await _fetch(url, browser_headers)
            return _judge(
                rb, rung="browser-headers", prior_note="timeout on plain HTTP"
            )

        if r.html is None:
            # a dropped connection / non-DNS, non-timeout transport error
            # on the FIRST honest-header request -- eligible for the
            # browser-headers retry per the brief ("once, after a 403 or
            # a dropped connection").
            await asyncio.sleep(host_delay_seconds)
            rb = await _fetch(url, browser_headers)
            return _judge(
                rb, rung="browser-headers", prior_note=f"connection error: {r.error}"
            )

        if is_challenge(r.html):
            return LadderOutcome(reason="cloudflare-challenge-blocked", rung="plain")

        hit = find_platform_link(r.html, r.final_url)
        if hit:
            return LadderOutcome(
                reason=FOUND, platform=hit[0], hit_url=hit[1], rung="plain"
            )

        if r.status == 403:
            await asyncio.sleep(host_delay_seconds)
            rb = await _fetch(url, browser_headers)
            return _judge(rb, rung="browser-headers", prior_note="403 under plain HTTP")

        # reached fine (2xx or a non-403 non-404 status), no platform
        # link on the home page -- a content-class answer for THIS
        # domain. (A 404 never retries under browser headers, per the
        # brief -- it falls straight through to here as well, since a
        # 404 response still has HTML for aiohttp to decode.)
        return LadderOutcome(
            reason="no-platform-link-found", rung="plain", detail=f"status={r.status}"
        )

    def _judge(rb: Any, *, rung: str, prior_note: str) -> LadderOutcome:
        if getattr(rb, "error_kind", "") == "dns":
            return LadderOutcome(
                reason="dns-unresolvable", rung=rung, detail=prior_note
            )
        if rb.html is None:
            return LadderOutcome(
                reason="blocked-browser-headers", rung=rung, detail=prior_note
            )
        if is_challenge(rb.html):
            return LadderOutcome(
                reason="cloudflare-challenge-blocked", rung=rung, detail=prior_note
            )
        hit = find_platform_link(rb.html, rb.final_url)
        if hit:
            return LadderOutcome(
                reason=FOUND,
                platform=hit[0],
                hit_url=hit[1],
                rung=rung,
                detail=prior_note,
            )
        if rb.status == 403:
            return LadderOutcome(
                reason="blocked-browser-headers", rung=rung, detail=prior_note
            )
        return LadderOutcome(
            reason="no-platform-link-found", rung=rung, detail=prior_note
        )

    return ladder_fn
