"""WO-264 (2026-09-11): overnight, DETECTION-ONLY sweep of the 10,016
governments under 5,000 people that WO-174 reached, found no CivicPlus
`/AgendaCenter` on, and that still have no platform and no Archive page --
`~/Documents/rtr-business/research/wo174_leftover_under_5k.csv`.

**This script never ingests, never queues a tier-3 line, never pins a
tenant, and never writes to `jurisdiction_coverage.csv`.** It only writes
one CSV row per government to `wo264_report.csv` with what it found and
the URL/marker that proves it. A separate morning close-out agent reads
that report, applies the mandatory hand-read gate to every
`video-candidate` row, and does the real ingest/pin/research-file work --
see `CLOSEOUT_BRIEF.md` written alongside the run log for that agent's
full brief. Building this as detection-only (rather than reusing the
full resolve/ingest pipeline other sweeps in this repo run) is
deliberate: an unattended overnight run with no human awake to apply the
2026-09-11 hand-read gate must not be the thing that ingests a wrong-
government video or a school-board channel found on a city row.

Per government, in order (stopping as soon as something useful is
found):

1. **Full-ladder front-page fetch** on the government's own domain --
   plain honest HTTP -> browser headers (only after a 403 or a dropped
   connection, never after a 404) -> headless (only for a page that
   loaded with no visible meeting/agenda/council/board link) -> stop at
   a human-verification gate (`cloudflare-challenge-blocked`, never
   solved or waited on). This whole rung is `run_access_ladder()`,
   imported UNCHANGED from `scripts/wo147_access_ladder_sweep.py` (built
   for WO-147's own 850-government access-ladder sweep and already
   fixture/live-tested there) -- this script adds no new ladder logic of
   its own, only a thinner detection-only shell around it.
2. **One hop** into the meetings/agenda/council/board page
   `run_access_ladder()` finds a link to. When that hop lands on a real
   platform (Granicus, Legistar, CivicClerk, ...), `run_access_ladder()`
   already returns the page it found the platform link on, and this
   script scans THAT page's own anchors/iframes for per-meeting video
   links (`find_video_candidates()` below) exactly the way the WO-264
   brief asks. When the hop lands on a real page with no platform link,
   `run_access_ladder()` doesn't hand back that page's HTML (it only
   preserves the page it actually matched on) -- rather than duplicate
   its whole hop-scoring/fetch logic to get it, this script re-derives
   the SAME top-ranked hop link with the pure, already-imported
   `find_hop_links()` (no network call) and fetches only that one URL
   itself, once, with the ladder's own per-host delay. That is one extra
   request per government in this one specific branch, not a second hop
   tier -- see `probe_domain()`'s own comment at that call site.
3. **Alternate-domain hop** for the (about 1,641) rows carrying an
   `alternate_domains`/`alternate_urls` value: steps 1-2 again on up to
   two alternates, only when the primary domain didn't already turn up a
   platform or a video candidate.
4. **Vendor path guess** -- last resort, only when nothing above found
   anything: try the municipal vendor-tenant URL shapes named in the
   WO-264 brief (Granicus/Legistar/CivicClerk/IQM2/Municode/CivicWeb/
   eScribe/NovusAgenda/Swagit/Town Hall Streams) against a small set of
   guessed labels derived from the government's own domain (see
   `domain_label()`/`label_variants()`). A guess only counts as a hit
   when the fetched tenant page's own text names both this government's
   name AND its state (`_tenant_names_this_government()`) -- a bare 200
   is never enough, per the brief.

Politeness (binding, from the Platforms conductor's ask in this WO's
brief): one request in flight at a time (this script is fully
sequential -- no concurrency anywhere), >=1.5s between different
governments/hosts (`GOV_DELAY_SECONDS`), >=2s between repeated requests
to the SAME host (`ladder.HOST_DELAY_SECONDS`, inherited from
wo147_access_ladder_sweep.py unchanged). **The one halt rule this WO's
brief states is scoped to a single vendor host family, not the whole
run** (`VendorCooloff` below: 6 consecutive access-shaped failures on
one vendor family pauses guesses against that family for 15 minutes,
then resets and retries) -- this is a deliberate narrowing of the
general repo convention (many other sweeps here halt the ENTIRE run
after 6 consecutive connect failures), because this run is unattended
overnight against a population that WO-174 already flagged as mostly
`no-platform-link-found`/`dns-unresolvable`: a run that dies on the
first ordinary string of six already-known-dead small-town domains
would defeat the point of running it overnight at all. A genuinely dead
individual government (DNS failure, timeout) is recorded as `dead` and
the run moves straight on to the next government; only a *vendor*
family's own shared edge (Granicus, Legistar, ...) gets the cool-off,
since that is the shared resource CLAUDE.md's "politely" rule is
protecting.

Evidence: every row that found a platform or a video candidate carries
the exact URL that answered (`platform_evidence_url`/`listing_url`) and
a marker string naming the matched link/badge/HTML fragment
(`platform_evidence_marker`, from `_evidence_marker()` below) or the
literal reason a vendor-guess tenant page was accepted
(`_tenant_names_this_government()`'s own explanation string) -- never
just a label with nothing to check it against.

A note on the `front_page_status` column: `run_access_ladder()`
(imported, not reimplemented here) returns which RUNG answered
(`access_mode`: plain/browser-headers/headless/challenge/dead) but does
not preserve the raw numeric HTTP status of the request that rung sent
-- extracting one honestly would mean a second, redundant fetch of a
host we already just contacted, which the politeness rule above forbids
for no real gain. So this column holds a numeric status ONLY when one
happens to appear in the ladder's own free-text `note` (e.g. "403 under
both plain and browser headers"), and otherwise the rung label itself
(`_front_page_status_label()`) -- `access_mode` is the column to read
first; this one is a best-effort supplement, not a guaranteed HTTP code.

Resumable: `wo264_report.csv` is flushed after every government (one row
each) and a gov_id already present with a non-empty `outcome` is skipped
on restart, so killing and re-launching this script picks up where it
left off.

Run from rtr-deeplink repo root with the shared venv active, from a
dedicated run worktree (see this WO's own "How to start it" section --
never from the shared checkout):
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo264_unused.db" \\
        .venv/bin/python -u scripts/wo264_overnight_sweep.py \\
        --input ~/Documents/rtr-business/research/wo174_leftover_under_5k.csv \\
        --report ~/Documents/rtr-business/research/wo264_report.csv

DATABASE_URL is set explicitly and unused by this script (no `archive`/
`app.db` import) only because some transitively-imported module may probe
for it -- same convention every other sweep script in this repo follows
(see e.g. wo174_pipeline.py's own docstring).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import aiohttp  # noqa: E402

import scripts.wo147_access_ladder_sweep as ladder  # noqa: E402
from app.utils.jurisdiction_enrich import _STATE_NAME_TO_ABBR_LOWER  # noqa: E402
from wo145_api_first_sweep import _GENERIC_NAME_WORDS  # noqa: E402

_STATE_ABBR_TO_NAME_LOWER: Dict[str, str] = {
    abbr: name for name, abbr in _STATE_NAME_TO_ABBR_LOWER.items()
}

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

RESEARCH_DIR = Path("/Users/mroconnell/Documents/rtr-business/research")
DEFAULT_INPUT_CSV = RESEARCH_DIR / "wo174_leftover_under_5k.csv"
DEFAULT_REPORT_CSV = RESEARCH_DIR / "wo264_report.csv"

# --------------------------------------------------------------------------
# Politeness
# --------------------------------------------------------------------------

GOV_DELAY_SECONDS = 1.5  # between different governments/hosts
CONSECUTIVE_VENDOR_FAILURES_HALT = 6
VENDOR_COOLOFF_SECONDS = 15 * 60
MAX_VENDOR_REQUESTS_PER_GOV = 16
MAX_DOMAIN_ATTEMPTS_PER_GOV = 3  # primary + up to 2 alternates

REPORT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "gov_kind",
    "population",
    "domain_tried",
    "is_alternate",
    "access_mode",
    "front_page_status",
    "platform_found",
    "platform_evidence_url",
    "platform_evidence_marker",
    "listing_url",
    "video_candidate_urls",
    "vendor_tenant_url",
    "outcome",
    "note",
]

# --------------------------------------------------------------------------
# Small helpers new to this script (everything else is reused, not
# reimplemented, from wo147_access_ladder_sweep.py)
# --------------------------------------------------------------------------


def normalize_domain(raw: str) -> str:
    """Same rule wo174_pipeline.py's own `normalize_domain()` uses (that
    module's docstring: ~1/3 of a candidate CSV's `domain`-shaped columns
    carry a full URL, not a bare host) -- strips a leading scheme and
    everything from the first `/` or `?` onward."""
    d = (raw or "").strip()
    d = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", d)
    d = d.split("/", 1)[0]
    d = d.split("?", 1)[0]
    return d.strip().rstrip(".")


def _split_list(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    return [p.strip() for p in raw.split(";") if p.strip()]


_STATUS_RE = re.compile(r"\b([1-5]\d{2})\b")


def _front_page_status_label(lr) -> str:
    """See module docstring's own note on this column -- best-effort
    only, `access_mode` is the authoritative rung column."""
    if lr.access_mode == "dead":
        return "no-connection"
    m = _STATUS_RE.search(lr.note or "")
    if m:
        return m.group(1)
    return lr.access_mode or "unknown"


# --------------------------------------------------------------------------
# Video-candidate scanning (new: run_access_ladder() only tells us
# whether a PLATFORM link was found, not whether the page it landed on
# also links out to a raw video host -- this scans the same tag set
# find_platform_link() already scans, wired to a different host list)
# --------------------------------------------------------------------------

_VIDEO_HOST_HINTS = (
    "youtube.com",
    "youtu.be",
    "vimeo.com",
    "drive.google.com",
    "dropbox.com",
    "boxcast.tv",
    "cablecast.tv",
)
_VIDEO_FILE_EXT_RE = re.compile(r"\.(mp4|m3u8|mov|webm|mkv)(\?|$)", re.I)
_VIDEO_TAGS = ("a", "iframe", "video", "source")
_ONCLICK_URL_RE = re.compile(r"""\(\s*['"]([^'"]+)""")


def find_video_candidates(html: str, final_url: str, limit: int = 8) -> List[str]:
    """Per-meeting video links found on a listing/platform page --
    recorded as CANDIDATES only (WO-264 brief), never resolved or
    ingested by this script."""
    soup = ladder._safe_soup(html or "")
    if soup is None:
        return []
    out: List[str] = []
    seen = set()
    for tag in soup.find_all(_VIDEO_TAGS):
        values = []
        href_or_src = tag.get("href") or tag.get("src")
        if href_or_src:
            values.append(href_or_src.strip())
        onclick = tag.get("onclick")
        if onclick:
            m = _ONCLICK_URL_RE.search(onclick)
            if m:
                values.append(m.group(1).strip())
        for value in values:
            if not value or value.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue
            full = urljoin(final_url, value)
            host = urlparse(full).netloc.lower()
            is_hit = any(h in host for h in _VIDEO_HOST_HINTS) or bool(
                _VIDEO_FILE_EXT_RE.search(full)
            )
            if is_hit and full not in seen:
                seen.add(full)
                out.append(full)
        if len(out) >= limit:
            break
    return out[:limit]


def _evidence_marker(html: str, hit_url: str, final_url: str) -> str:
    """Best-effort lookup (not a redetection) of the exact anchor/iframe
    whose resolved href/src/onclick equals the platform hit URL
    `find_platform_link()` already returned, so the report carries the
    real matched fragment rather than just repeating the URL. Falls back
    to a plain description when the hit was a guessed same-domain
    AgendaCenter path with no literal anchor on the page."""
    if not hit_url:
        return ""
    if not html:
        return f"URL matched by host/path shape: {hit_url}"
    soup = ladder._safe_soup(html)
    if soup is None:
        return f"URL matched by host/path shape: {hit_url} (page not re-parseable)"
    hit_no_frag = urlparse(hit_url)._replace(fragment="").geturl()
    for tag in soup.find_all(_VIDEO_TAGS + ("form",)):
        href_or_src = tag.get("href") or tag.get("src")
        onclick = tag.get("onclick") or ""
        candidates = [v for v in (href_or_src,) if v]
        m = _ONCLICK_URL_RE.search(onclick)
        if m:
            candidates.append(m.group(1))
        for value in candidates:
            full = urljoin(final_url, value.strip())
            if urlparse(full)._replace(fragment="").geturl() == hit_no_frag:
                return str(tag)[:300]
    if "agendacenter" in html.lower():
        return "literal 'agendacenter' substring found in page HTML (no matching anchor tag)"
    return f"URL matched by host/path shape: {hit_url}"


# --------------------------------------------------------------------------
# Step 1+2: full ladder + one hop, on one domain
# --------------------------------------------------------------------------


async def probe_domain(
    session: aiohttp.ClientSession, name: str, state: str, domain: str, hub_hint: str
) -> dict:
    lr = await ladder.run_access_ladder(
        session, name, state, domain, hub_hint or domain
    )

    out = {
        "access_mode": lr.access_mode,
        "front_page_status": _front_page_status_label(lr),
        "platform_found": "",
        "platform_evidence_url": "",
        "platform_evidence_marker": "",
        "listing_url": "",
        "video_candidate_urls": [],
        "outcome": "",
        "note": lr.note or "",
    }

    if lr.access_mode == "challenge":
        out["outcome"] = "human-gate"
        out["note"] = "cloudflare-challenge-blocked" + (
            f": {lr.note}" if lr.note else ""
        )
        return out

    if lr.access_mode == "dead":
        out["outcome"] = "dead"
        return out

    if lr.platform:
        out["platform_found"] = lr.platform
        out["platform_evidence_url"] = lr.hit_url or ""
        out["listing_url"] = lr.hit_url or ""
        out["platform_evidence_marker"] = _evidence_marker(
            lr.final_html or "", lr.hit_url or "", lr.final_url
        )
        if lr.final_html:
            out["video_candidate_urls"] = find_video_candidates(
                lr.final_html, lr.final_url
            )
        out["outcome"] = "platform-found"
        return out

    front_html = lr.final_html or ""
    if not front_html:
        # blocked-plain-http / blocked-browser-headers / timeout-with-no-page
        out["outcome"] = "blocked"
        return out

    hop_links = ladder.find_hop_links(front_html, lr.final_url)
    if not hop_links:
        candidates = find_video_candidates(front_html, lr.final_url)
        if candidates:
            out["video_candidate_urls"] = candidates
            out["listing_url"] = lr.final_url
            out["outcome"] = "video-candidate"
        else:
            out["outcome"] = "nothing"
        return out

    # run_access_ladder() already tried these hop links internally and
    # found no platform link on any of them -- see this module's own
    # docstring for why we re-fetch only the single top-ranked one here,
    # once, purely to look at its content for a video candidate.
    top_link = hop_links[0]
    await asyncio.sleep(ladder.HOST_DELAY_SECONDS)
    headers = (
        ladder.BROWSER_HEADERS
        if lr.access_mode == "browser-headers"
        else ladder.HONEST_HEADERS
    )
    rh = await ladder.fetch_one(session, top_link, headers)
    if rh.html and ladder.is_challenge(rh.html):
        out["outcome"] = "human-gate"
        out["note"] = "cloudflare-challenge-blocked (on the hop page)"
        return out
    if rh.html:
        out["listing_url"] = rh.final_url
        candidates = find_video_candidates(rh.html, rh.final_url)
        if candidates:
            out["video_candidate_urls"] = candidates
            out["outcome"] = "video-candidate"
        else:
            out["outcome"] = "listing-found-no-platform"
        return out

    out["outcome"] = "nothing"
    out["note"] = (out["note"] + "; " if out["note"] else "") + (
        f"hop fetch failed: {rh.error or ''}"
    )
    return out


# --------------------------------------------------------------------------
# Step 4: vendor path guess
# --------------------------------------------------------------------------

_LABEL_STOPWORDS = {"co", "city", "town", "village", "twp", "township", "www"}


def domain_label(domain: str) -> str:
    """The domain's own 'second-level label' -- the first DNS label,
    unless it's a generic government-shape word like 'co' (as in the
    real `co.adams.id.us` shape this population's own `domain` column
    carries for some counties), in which case the second label is used
    instead. A deliberate small heuristic, not a full public-suffix-list
    parse -- this is a last-resort guess step, not a scored decision."""
    d = (domain or "").strip().lower()
    d = re.sub(r"^www\.", "", d)
    parts = [p for p in d.split(".") if p]
    if not parts:
        return ""
    label = parts[0]
    if label in _LABEL_STOPWORDS and len(parts) > 1:
        label = parts[1]
    return re.sub(r"[^a-z0-9]", "", label)


def label_variants(domain: str, state: str) -> List[str]:
    """Exactly the WO-264 brief's own list: the domain's second-level
    label, plus `cityof<label>`, `townof<label>`, `<label><st>`.

    Guards against a real, confirmed-live doubling this population hits
    often: a domain like `cityofiowafalls.com` or
    `townofmiddlebury.in.gov` already carries "cityof"/"townof" baked
    into its own second-level label, and blindly prepending it again
    produced a nonsense `cityofcityofiowafalls` guess (live-measured
    building this script) -- wasted requests for a variant no real
    tenant would ever register. Same reasoning for the `<label><st>`
    variant when the label already ends with the state abbreviation."""
    base = domain_label(domain)
    if not base:
        return []
    st = (state or "").strip().lower()
    variants = [base]
    if not base.startswith("cityof"):
        variants.append(f"cityof{base}")
    if not base.startswith("townof"):
        variants.append(f"townof{base}")
    if st and not base.endswith(st):
        variants.append(f"{base}{st}")
    seen = set()
    out = []
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _tenant_names_this_government(html: str, name: str, state: str) -> Optional[str]:
    """A tenant counts only when its page names this government and
    state (WO-264 brief, verbatim). Returns the matched (name_word,
    state_word) pair as an explanation string, or None."""
    if not html:
        return None
    low = html.lower()
    words = re.findall(r"[a-z0-9']+", (name or "").lower())
    core_words = [w for w in words if w not in _GENERIC_NAME_WORDS and len(w) > 2]
    if not core_words:
        core_words = [w for w in words if len(w) > 2]
    matched_name = next((w for w in core_words if w in low), None)
    if not matched_name:
        return None
    st = (state or "").strip().lower()
    if not st:
        return None
    matched_state = None
    if re.search(rf"\b{re.escape(st)}\b", low):
        matched_state = st.upper()
    else:
        full = _STATE_ABBR_TO_NAME_LOWER.get(st, "")
        if full and full in low:
            matched_state = full
    if not matched_state:
        return None
    return f"page text contains government-name word {matched_name!r} and state {matched_state!r}"


def _granicus_urls(label: str) -> List[str]:
    return [
        f"https://{label}.granicus.com/ViewPublisher.php?view_id={n}" for n in (1, 2, 3)
    ]


VENDOR_TEMPLATES: List[Tuple[str, "callable"]] = [
    ("granicus", _granicus_urls),
    ("legistar", lambda label: [f"https://{label}.legistar.com/Calendar.aspx"]),
    ("civicclerk", lambda label: [f"https://{label}.portal.civicclerk.com"]),
    ("iqm2", lambda label: [f"https://{label}.iqm2.com/Citizens/Calendar.aspx"]),
    ("escribe", lambda label: [f"https://pub-{label}.escribemeetings.com"]),
    ("municode", lambda label: [f"https://{label}.municodemeetings.com"]),
    ("civicweb", lambda label: [f"https://{label}.civicweb.net"]),
    ("novusagenda", lambda label: [f"https://{label}.novusagenda.com/agendapublic"]),
    ("swagit", lambda label: [f"https://{label}.swagit.com"]),
    (
        "townhallstreams",
        lambda label: [f"https://townhallstreams.com/towns/{label}"],
    ),
]


class VendorCooloff:
    """Per-vendor-family (not whole-run) failure tracking -- see this
    module's docstring for why the halt is scoped this narrowly."""

    def __init__(self) -> None:
        self._consecutive_fail: Dict[str, int] = {}
        self._cooloff_until: Dict[str, float] = {}

    def blocked(self, vendor_key: str) -> bool:
        until = self._cooloff_until.get(vendor_key)
        return until is not None and time.time() < until

    def record(self, vendor_key: str, is_access_failure: bool) -> None:
        if not is_access_failure:
            self._consecutive_fail[vendor_key] = 0
            return
        n = self._consecutive_fail.get(vendor_key, 0) + 1
        self._consecutive_fail[vendor_key] = n
        if n >= CONSECUTIVE_VENDOR_FAILURES_HALT:
            self._cooloff_until[vendor_key] = time.time() + VENDOR_COOLOFF_SECONDS
            self._consecutive_fail[vendor_key] = 0
            print(
                f"[COOLOFF] vendor family {vendor_key!r}: "
                f"{CONSECUTIVE_VENDOR_FAILURES_HALT} consecutive access-shaped "
                f"failures -- pausing guesses against it for "
                f"{VENDOR_COOLOFF_SECONDS}s",
                flush=True,
            )


async def try_vendor_guesses(
    session: aiohttp.ClientSession,
    name: str,
    state: str,
    domain: str,
    cooloff: VendorCooloff,
) -> Optional[dict]:
    variants = label_variants(domain, state)
    if not variants:
        return None
    tried = 0
    for label in variants:
        for vendor_key, build_urls in VENDOR_TEMPLATES:
            if tried >= MAX_VENDOR_REQUESTS_PER_GOV:
                return None
            if cooloff.blocked(vendor_key):
                continue
            for url in build_urls(label):
                if tried >= MAX_VENDOR_REQUESTS_PER_GOV:
                    return None
                await asyncio.sleep(ladder.HOST_DELAY_SECONDS)
                r = await ladder.fetch_one(session, url, ladder.HONEST_HEADERS)
                tried += 1

                if r.error_kind == "dns":
                    # NXDOMAIN -- no such tenant, not a failure of the
                    # vendor's own infrastructure.
                    cooloff.record(vendor_key, False)
                    continue
                if r.error_kind in ("timeout", "connection"):
                    cooloff.record(vendor_key, True)
                    continue
                if r.html and ladder.is_challenge(r.html):
                    cooloff.record(vendor_key, True)
                    continue
                if r.status in (403, 503):
                    cooloff.record(vendor_key, True)
                    continue
                cooloff.record(vendor_key, False)
                if r.status == 200 and r.html:
                    reason = _tenant_names_this_government(r.html, name, state)
                    if reason:
                        return {
                            "platform": vendor_key,
                            "url": url,
                            "marker": (
                                f"vendor-path guess (label={label!r}) confirmed: "
                                f"{reason}"
                            ),
                        }
    return None


# --------------------------------------------------------------------------
# Per-government orchestration
# --------------------------------------------------------------------------


class ReportWriter:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not path.exists()
        self._f = path.open("a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._f, fieldnames=REPORT_FIELDS)
        if write_header:
            self._writer.writeheader()
            self._f.flush()

    def write(self, row: dict) -> None:
        out = {f: row.get(f, "") for f in REPORT_FIELDS}
        self._writer.writerow(out)
        self._f.flush()

    def close(self) -> None:
        self._f.close()


def load_done_gov_ids(path: Path) -> set:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as f:
        return {
            r["gov_id"] for r in csv.DictReader(f) if (r.get("outcome") or "").strip()
        }


def _build_domain_attempts(cand: dict) -> List[Tuple[str, bool, str]]:
    attempts: List[Tuple[str, bool, str]] = []
    seen = set()

    primary = normalize_domain(cand.get("domain") or "")
    if primary:
        attempts.append((primary, False, cand.get("hub_url") or ""))
        seen.add(primary)

    for raw in _split_list(cand.get("alternate_domains")):
        nd = normalize_domain(raw)
        if nd and nd not in seen:
            seen.add(nd)
            attempts.append((nd, True, ""))

    for raw in _split_list(cand.get("alternate_urls")):
        nd = normalize_domain(raw)
        if nd and nd not in seen:
            seen.add(nd)
            attempts.append((nd, True, raw))

    return attempts[:MAX_DOMAIN_ATTEMPTS_PER_GOV]


_SUCCESS_OUTCOMES = {"platform-found", "video-candidate"}


async def process_government(
    session: aiohttp.ClientSession,
    cand: dict,
    report: ReportWriter,
    cooloff: VendorCooloff,
) -> None:
    row = {f: "" for f in REPORT_FIELDS}
    row.update(
        gov_id=cand["gov_id"],
        name=cand["name"],
        state=cand["state"],
        gov_kind=cand.get("gov_kind", ""),
        population=cand.get("population", ""),
    )

    attempts = _build_domain_attempts(cand)
    if not attempts:
        row.update(
            domain_tried="",
            is_alternate="no",
            outcome="nothing",
            note="no domain or alternate on file",
        )
        report.write(row)
        return

    last_domain, last_is_alt, last_probe = attempts[0][0], attempts[0][1], None
    for i, (dom, is_alt, hub_hint) in enumerate(attempts):
        if i:
            await asyncio.sleep(GOV_DELAY_SECONDS)
        probe = await probe_domain(session, cand["name"], cand["state"], dom, hub_hint)
        last_domain, last_is_alt, last_probe = dom, is_alt, probe
        if probe["outcome"] in _SUCCESS_OUTCOMES:
            break

    assert last_probe is not None
    row.update(
        domain_tried=last_domain,
        is_alternate="yes" if last_is_alt else "no",
        access_mode=last_probe["access_mode"],
        front_page_status=last_probe["front_page_status"],
        platform_found=last_probe["platform_found"],
        platform_evidence_url=last_probe["platform_evidence_url"],
        platform_evidence_marker=last_probe["platform_evidence_marker"],
        listing_url=last_probe["listing_url"],
        video_candidate_urls=";".join(last_probe["video_candidate_urls"]),
        outcome=last_probe["outcome"],
        note=last_probe["note"],
    )

    if last_probe["outcome"] not in _SUCCESS_OUTCOMES:
        await asyncio.sleep(GOV_DELAY_SECONDS)
        vendor_hit = await try_vendor_guesses(
            session, cand["name"], cand["state"], last_domain, cooloff
        )
        if vendor_hit:
            row.update(
                platform_found=vendor_hit["platform"],
                platform_evidence_url=vendor_hit["url"],
                platform_evidence_marker=vendor_hit["marker"],
                vendor_tenant_url=vendor_hit["url"],
                outcome="platform-found",
                note=(row["note"] + "; " if row["note"] else "")
                + "found via vendor-path guess",
            )

    report.write(row)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT_CSV)
    ap.add_argument("--report", type=Path, default=DEFAULT_REPORT_CSV)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    with args.input.open(newline="", encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))
    print(f"{len(all_rows)} total candidates in {args.input}", flush=True)

    done = load_done_gov_ids(args.report)
    todo = [r for r in all_rows if r["gov_id"] not in done]
    print(f"{len(done)} already processed, {len(todo)} to go", flush=True)

    if args.limit:
        todo = todo[: args.limit]
        print(f"--limit {args.limit}: processing {len(todo)} this run", flush=True)

    report = ReportWriter(args.report)
    cooloff = VendorCooloff()
    processed_this_run = 0
    started = time.time()
    try:
        async with aiohttp.ClientSession() as session:
            for cand in todo:
                await process_government(session, cand, report, cooloff)
                processed_this_run += 1
                if processed_this_run % 250 == 0:
                    elapsed = time.time() - started
                    rate = processed_this_run / elapsed * 60 if elapsed else 0
                    print(
                        f"--- {processed_this_run}/{len(todo)} processed this run "
                        f"({rate:.1f}/min) ---",
                        flush=True,
                    )
    finally:
        report.close()

    with args.report.open(newline="", encoding="utf-8") as f:
        results = list(csv.DictReader(f))
    by_outcome: Dict[str, int] = {}
    for r in results:
        by_outcome[r["outcome"]] = by_outcome.get(r["outcome"], 0) + 1
    print("\n=== SUMMARY (cumulative across all runs) ===", flush=True)
    for outcome, count in sorted(by_outcome.items(), key=lambda x: -x[1]):
        print(f"outcome {outcome}: {count}", flush=True)
    print(f"Full report: {args.report}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
