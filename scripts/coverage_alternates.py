"""WO-181/WO-184 (2026-09-10/11): shared helper for trying a government's
alternate domains/URLs before recording an access reject.

Why this exists: WO-165 added two columns to
`~/Documents/rtr-business/research/jurisdiction_coverage.csv` --
`alternate_domains` and `alternate_urls` (semicolon-separated, every real
domain or URL a government was ever recorded under, never dropped --
Ryan's rule that several ways into the same government is a good thing).
Nothing read them at all until WO-181; every sweep script in this
directory only looked at the row's `domain`. This module is the one
place that logic lives, so future sweep scripts import it rather than
re-deriving it.

WO-181 shipped a deliberately narrow first version: only an ACCESS-class
reject (we could not even read the host) was worth retrying against an
alternate. WO-184 widens that under a second, opt-in `trigger` policy,
per Ryan's own rule (quoted verbatim, 2026-09-10 -- this supersedes
WO-181's narrower framing wherever the two disagree):

    "A domain keeps priority when it has produced a resolved meeting:
    with video is best, but a meeting or agenda without video is still
    very high quality. If a domain has produced no meeting at all, we
    may simply be looking at the wrong domain, and we lose nothing by
    trying another. Every government posts agendas at least, so the
    line is: found a meeting or agenda, or not."

Concretely, that is `trigger="no-meeting"`: retry an alternate whenever
the primary produced literally nothing (an ACCESS-class reject, or a
CONTENT-class one that means "no platform link, no meeting, no video
was found at all") or was simply never tested. It is still never worth
retrying once a real meeting or agenda WAS found on the primary --
either with video (already the best outcome) or without (still "very
high quality" per Ryan's rule above, so trying a different hostname for
the SAME government doesn't change that answer) -- see
`one_hop_alternate()` below for the separate, no-promotion probe WO-184
runs against THAT population instead. `trigger="access"` keeps WO-181's
original, narrower behaviour unchanged (existing callers that don't pass
`trigger` get it by default).

Two reason taxonomies, from docs/BREADTH_SWEEP_BRIEF.md's "Reject
reasons, two classes" section (the shared vocabulary every sweep script
writes into `reject_reason`):

- ACCESS_REASONS: we could not even read the host. Worth trying again
  under both triggers, including against an alternate domain.
- CONTENT_REASONS: we read the host fine. Split further below into
  NO_MEETING_CONTENT_REASONS (nothing was there at all -- worth retrying
  under `trigger="no-meeting"`) and the rest (a real meeting/agenda, or a
  video, or an off-mission/already-handled row -- never worth retrying,
  under either trigger).

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
import re
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

# WO-184: the subset of CONTENT_REASONS meaning "no meeting/agenda/
# platform link was found at all" -- Ryan's rule says these ARE worth
# retrying against an alternate, unlike the rest of CONTENT_REASONS.
# `no-platform-signature` is a third, WO-184-only spelling covering a
# sweep that couldn't even guess which platform a government uses;
# treated the same as the other two "found nothing" reasons.
NO_MEETING_CONTENT_REASONS = frozenset(
    {
        "no-platform-link-found",
        "no-meeting-nor-video",
        "no-meetings-found",  # pre-2026-09-10 spelling of no-meeting-nor-video
        "no-platform-signature",
    }
)

# WO-184: reasons that mean a real meeting or agenda WAS already found on
# the primary -- with video, or (per Ryan's rule) without. Ryan's rule is
# explicit that these are "very high quality" outcomes on their own and
# a different hostname for the same government doesn't change that, so
# `trigger="no-meeting"` never retries an alternate for these. This is
# the population `one_hop_alternate()` handles instead (no promotion).
MEETING_FOUND_NO_VIDEO_REASONS = frozenset({"meeting-without-video", "no-video-found"})

# WO-184: the full explicit "never retry, under either trigger" list from
# Ryan's instructions -- MEETING_FOUND_NO_VIDEO_REASONS plus off-mission
# and already-spoken-for rows (a video with no matching meeting, a
# platform this codebase has no adapter for, or a row already ingested/
# queued/covered). Listed explicitly, not derived, because "already
# covered" isn't a CONTENT/ACCESS reason at all -- it's a row that has
# moved past needing a reject reason.
NEVER_RETRY_REASONS = MEETING_FOUND_NO_VIDEO_REASONS | frozenset(
    {
        "off-mission",
        "video-without-meeting",
        "unsupported-platform-no-adapter",
        "ingested",
        "queued",
        "already-covered",
    }
)


def is_retry_worthy(reason: Optional[str], trigger: str = "access") -> bool:
    """Whether `reason` (a stored `reject_reason`, or a freshly-fetched
    ladder outcome's own `.reason`) is worth trying the next alternate
    domain for, under the given trigger policy.

    `trigger="access"` (WO-181, unchanged, and the default so existing
    callers behave exactly as before): worth retrying unless `reason` is
    a genuine CONTENT-class answer -- i.e. retry on any ACCESS_REASONS
    member OR an unrecognized reason (an unknown answer is not a
    confirmed content dead-end), matching `ladder_with_alternates()`'s
    original per-candidate loop exactly.

    `trigger="no-meeting"` (Ryan's rule, WO-184): worth retrying unless
    `reason` is in NEVER_RETRY_REASONS -- i.e. retry on any
    ACCESS_REASONS member, any NO_MEETING_CONTENT_REASONS member, a
    blank/never-tested reason, or an unrecognized one; never retry once a
    meeting/agenda (with or without video) was already found, the row is
    off-mission, or the row is already spoken for.
    """
    r = (reason or "").strip()
    if trigger == "access":
        return r not in CONTENT_REASONS
    if trigger == "no-meeting":
        return r not in NEVER_RETRY_REASONS
    raise ValueError(f"unknown trigger policy: {trigger!r}")


def already_has_coverage(row: Dict[str, Any]) -> bool:
    """True when the row already represents real, live coverage --
    `transcribed` or `shares_video` is the literal string "True" -- and
    must never be retried under ANY trigger, regardless of what
    `reject_reason` says.

    Real, confirmed gap found live running WO-184's first test batch
    (2026-09-11): the research file does NOT spell "already covered" as
    a `reject_reason` string the way `NEVER_RETRY_REASONS` assumes -- a
    government with a real, live, transcribed page (e.g. Cook County, IL,
    `cook-county.granicus.com`, `transcribed=True`) sits with a BLANK
    `reject_reason`, the exact same shape `is_retry_worthy()` treats as
    "never tested." Without this check, `trigger="no-meeting"`'s blank-
    reason allowance would re-probe a government's real, already-working
    page purely because nothing had ever written a reject reason for its
    success -- 1,252 of 4,686 rows in WO-184's own candidate count turned
    out to be exactly this shape. Callers building a candidate list MUST
    call this (or filter equivalently) in addition to `is_retry_worthy()`
    -- it is intentionally a separate function, not folded into
    `is_retry_worthy()`, because that function only ever sees a bare
    reason string, not the row it came from."""
    return (row.get("transcribed") or "").strip().lower() == "true" or (
        row.get("shares_video") or ""
    ).strip().lower() == "true"


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
    return host.strip().strip("/").lower().rstrip(".")


# --- WO-193 (2026-09-11): domain-shape classification and canonicalisation ---
#
# `normalize_host()` above is the READ-time helper (used by every sweep to
# try a candidate) -- it always returns a usable host string and never
# tells the caller what the *input* shape was. The functions below exist
# for the one-time bulk normalisation of jurisdiction_coverage.csv's
# `domain`/`alternate_domains` columns (WO-174 found ~20% of `domain`
# values are full URLs, not bare hosts -- see BACKLOG_DONE.md's WO-193
# entry for the measured counts). They share `normalize_host`'s core
# host-extraction logic but additionally report *what shape the input
# was* and *what to preserve*, which the read-time helper doesn't need.
#
# A key design choice: the anomaly checks below (space/comma/semicolon,
# uppercase, trailing dot, a port) look ONLY at the parsed HOST
# component, never the whole raw string. A real, confirmed row in the
# file is a Facebook profile URL with a comma inside its query string
# (`...id=61558365536288&amp;mibextid=LQQJ4d`, the `&amp;` is an
# HTML-entity-encoded `&`, which decodes to a literal `;` in some feeds)
# -- that comma lives in the query, not the hostname, so the row is a
# perfectly ordinary `scheme_host_query` shape, not `other`. Checking the
# whole string would have misclassified it.

_HOST_ANOMALY_RE = re.compile(r"[,\s;]")


def _split_domain_value(value: str) -> Tuple[bool, str, str, str]:
    """(has_scheme, host_with_possible_port, path, query) for a single
    `domain`/`alternate_domains` cell value. Assumes `https://` when no
    scheme is present, purely to get `urlparse` to split host from path
    correctly -- the assumed scheme is never reported back to the
    caller."""
    v = (value or "").strip()
    has_scheme = "://" in v
    work = v if has_scheme else "https://" + v
    parsed = urlparse(work)
    host = parsed.netloc or parsed.path
    if "@" in host:
        host = host.rsplit("@", 1)[-1]
    return has_scheme, host, parsed.path, parsed.query


def classify_domain_shape(value: Optional[str]) -> str:
    """Classify one `domain`/`alternate_domains` cell's shape. One of:
    'blank', 'bare_host', 'bare_host_www', 'scheme_host',
    'scheme_host_path', 'scheme_host_query', 'other'.

    'other' covers a malformed or unexpected host: a space/comma/
    semicolon inside the hostname itself (not the path or query --
    see the module note above), an uppercase letter in the host, a
    trailing dot, an explicit port, or a no-scheme value that still
    carries a path/query (a bare host can't have a path without a
    scheme to separate the two unambiguously, so this file's one such
    row -- `regionalwebtv.com/spotsysb` -- is treated as an edge case,
    not a clean bare host)."""
    v = (value or "").strip()
    if not v:
        return "blank"
    has_scheme, host_raw, path, query = _split_domain_value(v)
    hostonly = host_raw
    port = None
    if ":" in hostonly:
        hostpart, _, portpart = hostonly.rpartition(":")
        if portpart.isdigit():
            hostonly, port = hostpart, portpart
    if not hostonly:
        return "other"
    if _HOST_ANOMALY_RE.search(hostonly):
        return "other"
    if hostonly != hostonly.lower():
        return "other"
    if hostonly.endswith("."):
        return "other"
    if port is not None:
        return "other"
    if has_scheme:
        if query:
            return "scheme_host_query"
        if path not in ("", "/"):
            return "scheme_host_path"
        return "scheme_host"
    if "/" in v or "?" in v:
        return "other"
    return "bare_host_www" if hostonly.startswith("www.") else "bare_host"


def canonicalize_domain(value: Optional[str]) -> Tuple[str, Optional[str]]:
    """Canonical (host, extra_url) for one `domain`/`alternate_domains`
    cell. `host` is the bare, lowercase host -- no scheme, no path, no
    query, no port, no trailing dot. A leading `www.` is preserved
    exactly as recorded (never added or stripped -- some rows record the
    working variant on purpose). `extra_url` is the original value,
    whitespace-trimmed, when it carried a real path or query beyond the
    host (a real page, not just a scheme) -- callers append this to
    `alternate_urls` so nothing is lost; `None` when the value was
    already just a host (with or without a scheme/port/trailing dot to
    strip). Never returns a blank host for a non-blank input -- an
    'other'-shaped value still gets whatever host `urlparse` can find,
    so a row is never silently dropped."""
    v = (value or "").strip()
    if not v:
        return "", None
    shape = classify_domain_shape(v)
    has_scheme, host_raw, path, query = _split_domain_value(v)
    hostonly = host_raw
    if ":" in hostonly:
        hostpart, _, portpart = hostonly.rpartition(":")
        if portpart.isdigit():
            hostonly = hostpart
    host = hostonly.strip().strip("/").lower().rstrip(".")
    extra_url = None
    if shape in ("scheme_host_path", "scheme_host_query"):
        extra_url = v
    elif shape == "other" and not has_scheme and ("/" in v or "?" in v):
        # No-scheme value with a path (e.g. "regionalwebtv.com/spotsysb")
        # -- preserve it as a real URL by supplying the scheme it lacked.
        extra_url = "https://" + v
    return host, extra_url


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

    @property
    def primary_domain(self) -> str:
        """The first candidate actually tried (the row's own `domain`,
        normalized) -- '' if nothing was tried at all."""
        return self.trail[0][0] if self.trail else ""


def decide_promotion(result: AlternatesResult) -> bool:
    """WO-184 promotion rule, verbatim from Ryan's instructions: "when an
    alternate produces a meeting or agenda ... and the primary produced
    none, the alternate becomes `domain` and the old primary moves into
    `alternate_domains`. When both produce meetings, keep the primary."

    True only when the WINNING candidate is FOUND and it is NOT the
    primary (the first domain tried) -- if the primary itself answered
    FOUND, `ladder_with_alternates()` already stopped there and
    `answered_domain` equals the primary, so this is naturally False;
    likewise false when nothing at all answered FOUND."""
    return (
        result.outcome.reason == FOUND
        and bool(result.primary_domain)
        and result.answered_domain != result.primary_domain
    )


def apply_promotion(row: Dict[str, Any], result: AlternatesResult) -> Dict[str, Any]:
    """Returns a shallow-copied row with WO-184's promotion applied: the
    answering alternate becomes `domain`, and the old primary is folded
    into `alternate_domains` -- never dropped, per this file's whole
    reason for existing. Pure/no I/O -- the caller is responsible for
    actually writing the research file (with its own lock/re-read/
    atomic-rename protocol; see docs/COVERAGE_HANDOVER.md).

    Caller should only call this when `decide_promotion(result)` is
    True; calling it otherwise would (harmlessly, since domain would just
    be set to the same value it already is) misrepresent the row, so it
    isn't guarded here -- the guard belongs at the one call site that
    decides whether a promotion happened at all."""
    new_row = dict(row)
    old_primary_raw = (row.get("domain") or "").strip()
    old_primary_host = normalize_host(old_primary_raw)

    existing_alts = [
        d.strip() for d in (row.get("alternate_domains") or "").split(";") if d.strip()
    ]
    # the promoted domain is now primary -- drop it from the alternates
    # list if it was already recorded there.
    existing_alts = [
        d for d in existing_alts if normalize_host(d) != result.answered_domain
    ]
    already_present = {normalize_host(d) for d in existing_alts}
    if old_primary_host and old_primary_host not in already_present:
        existing_alts.append(old_primary_raw or old_primary_host)

    new_row["domain"] = result.answered_domain
    new_row["alternate_domains"] = ";".join(existing_alts)
    return new_row


LadderFn = Callable[[str, Dict[str, Any]], Awaitable[LadderOutcome]]


async def ladder_with_alternates(
    row: Dict[str, Any],
    ladder_fn: LadderFn,
    *,
    trigger: str = "access",
    max_candidates: Optional[int] = None,
    between_candidates_seconds: float = 0.0,
) -> AlternatesResult:
    """Runs `ladder_fn` on the primary domain; if the result is worth
    retrying under `trigger` (see `is_retry_worthy()`), tries the next
    candidate domain, and so on. Stops at the first FOUND answer, or the
    first answer `is_retry_worthy()` says to stop on. Returns the
    winning (or last-tried, if every candidate stayed retry-worthy)
    outcome plus the answering domain and the full per-domain trail.

    `trigger="access"` (the default, WO-181's original behaviour,
    unchanged): stop only on FOUND or a genuine CONTENT-class answer.
    `trigger="no-meeting"` (Ryan's rule, WO-184): stop on FOUND, or on
    any reason meaning a real meeting/agenda (with or without video) was
    already found, or the row is off-mission/already spoken for -- see
    NEVER_RETRY_REASONS. Use `decide_promotion()`/`apply_promotion()` on
    the result to apply WO-184's promotion rule.

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
        if outcome.reason == FOUND or not is_retry_worthy(outcome.reason, trigger):
            return AlternatesResult(outcome, domain, trail)
        # else: retry-worthy under this trigger -- fall through and try
        # the next candidate.

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


@dataclass
class OneHopResult:
    """What `one_hop_alternate()` found (or didn't) on one alternate
    domain, for the `meeting-without-video`/`no-video-found` population.

    `differs_from_primary` is None when nothing was found at all (there
    is nothing to compare); otherwise True/False depending on whether
    the platform found is a DIFFERENT one than the row's own already-
    known `suspected_video_provider`/`suspected_meeting_link_provider` --
    per Ryan's instruction that a *different* platform is "a new view of
    the same meetings and may surface video," while the same platform
    again is not."""

    alternate_domain: str
    reason: str  # FOUND, or an ACCESS/CONTENT reason
    platform: Optional[str] = None
    hit_url: Optional[str] = None
    hop_url: Optional[str] = None
    differs_from_primary: Optional[bool] = None
    detail: str = ""


def _known_platforms(row: Dict[str, Any]) -> set:
    return {
        (row.get("suspected_video_provider") or "").strip().lower(),
        (row.get("suspected_meeting_link_provider") or "").strip().lower(),
    } - {""}


async def one_hop_alternate(
    row: Dict[str, Any],
    alternate_domain: str,
    fetch_one_fn: Callable[[str, Dict[str, str]], Awaitable[Any]],
    honest_headers: Dict[str, str],
    is_challenge: Callable[[str], bool],
    find_platform_link_fn: Callable[[str, str], Optional[Tuple[str, str]]],
    find_hop_links_fn: Callable[[str, str], List[str]],
    *,
    max_hop_links: int = 3,
    between_requests_seconds: float = 0.0,
) -> OneHopResult:
    """WO-184's second retry mode, for the `meeting-without-video`/
    `no-video-found` population: the primary already found a real
    meeting or agenda, so this NEVER promotes the alternate (there is no
    `decide_promotion()`/`apply_promotion()` call anywhere in this
    function or its caller) -- it only checks whether the alternate
    exposes a DIFFERENT platform than the one already known, which per
    Ryan's instruction "may surface video" even though the primary's own
    platform didn't.

    Plain honest HTTP only -- one rung, no browser-headers retry, no
    headless -- fetch `alternate_domain`'s home page, look for a
    platform link there, and if none, follow up to `max_hop_links` of
    its own meeting/agenda hop links (`find_hop_links_fn`, the same
    heuristic every other sweep in this repo uses) and scan each of
    those too. Returns the first platform link found anywhere in that
    walk, or a plain access/content reason if nothing was.

    `fetch_one_fn`/`find_platform_link_fn`/`find_hop_links_fn` are
    injected (not imported directly) for the same reason
    `rungs_2_3_ladder_fn` injects its primitives -- see that function's
    own docstring: importing wo147_access_ladder_sweep for these pure
    helpers is safe for a caller that never touches
    `wo134_confirmed_hits_ingest.process_row()` itself, but this module
    stays import-only regardless."""
    url = (
        alternate_domain if "://" in alternate_domain else f"https://{alternate_domain}"
    )
    r = await fetch_one_fn(url, honest_headers)

    if getattr(r, "error_kind", "") == "dns":
        return OneHopResult(alternate_domain, "dns-unresolvable", detail=r.error or "")
    if getattr(r, "html", None) is None:
        return OneHopResult(
            alternate_domain, "blocked-plain-http", detail=getattr(r, "error", "") or ""
        )
    if is_challenge(r.html):
        return OneHopResult(alternate_domain, "cloudflare-challenge-blocked")

    known = _known_platforms(row)

    hit = find_platform_link_fn(r.html, r.final_url)
    if hit:
        platform, hit_url = hit
        return OneHopResult(
            alternate_domain,
            FOUND,
            platform=platform,
            hit_url=hit_url,
            differs_from_primary=(platform or "").strip().lower() not in known,
        )

    for hop_url in find_hop_links_fn(r.html, r.final_url)[:max_hop_links]:
        if between_requests_seconds:
            await asyncio.sleep(between_requests_seconds)
        rh = await fetch_one_fn(hop_url, honest_headers)
        if getattr(rh, "html", None) is None:
            continue
        if is_challenge(rh.html):
            continue
        hit = find_platform_link_fn(rh.html, rh.final_url)
        if hit:
            platform, hit_url = hit
            return OneHopResult(
                alternate_domain,
                FOUND,
                platform=platform,
                hit_url=hit_url,
                hop_url=hop_url,
                differs_from_primary=(platform or "").strip().lower() not in known,
            )

    return OneHopResult(alternate_domain, "no-platform-link-found")
