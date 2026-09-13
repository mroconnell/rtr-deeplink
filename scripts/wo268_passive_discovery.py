"""WO-268 (2026-09-12): passive platform-discovery pilot -- DNS/CNAME,
sitemap.xml + robots.txt, and the per-domain archive index (Wayback CDX +
Common Crawl), on 300 US governments of 5,000+ population with no known
platform. Detection only: this script never ingests, never writes a
queue line, and never touches `jurisdiction_coverage.csv` -- its only
output is a report CSV (`research/wo268_passive_pilot.csv`) and a hub
path-frequency CSV (`research/wo268_hub_path_frequency.csv`). The
research-file apply is a later WO, once Ryan has seen the yields (see
docs/BREADTH_SWEEP_BRIEF.md's overall method for the ladder this
complements, and docs/investigations/passive_platform_discovery_pilot.md
for the full writeup this run produced).

Why passive: today's access ladder (scripts/wo147_access_ladder_sweep.py)
finds a platform only when a vendor hostname shows up on the government's
own homepage or one keyword-guided hop, which means every government in
the candidate list has already failed that check once. This script tries
three lighter-touch methods first, in order, each recorded separately so
the yield of each is knowable on its own:

1. DNS/CNAME -- no request to the government at all. Apex + www A/CNAME,
   a fixed list of guessed platform subdomains, and guessed vendor-tenant
   labels (`<label>.granicus.com` etc). `<label>` is derived from the
   domain's own second-level name (the part before the public suffix --
   matches the pattern already visible in real tenants like
   `baldwincountyal.granicus.com`, `southmiami.granicus.com`). WO-260's
   own label-derivation helper was not available in this checkout when
   this script was written (no file in either repo referenced it); this
   is a plain, documented substitute, not a guess at WO-260's algorithm.
2. Sitemap + robots.txt -- robots.txt first (for Sitemap: directives and
   a crude CMS/builder hint from its Disallow list), then sitemap.xml /
   sitemap_index.xml, following one level of index (capped at 3
   sub-sitemaps, to bound the request count honestly -- see the
   investigation doc's cost table). Every URL is scanned for a vendor
   hostname or a meeting/agenda/minutes/council/commission/board/video/
   stream keyword.
3. Archive index -- Wayback CDX for the domain itself (matchType=domain,
   collapse=urlkey, filter=statuscode:200), and Common Crawl's latest
   index if it answers. Both list only captures OF this domain, never
   outbound links from it, so neither can show a vendor host the
   domain's own pages never mentioned -- recorded as a stated limitation
   per domain, not silently assumed away.
4. Classification -- first positive hit wins, in the order above (DNS,
   then sitemap, then archive index); confidence is "high" for a vendor
   hostname or a known first-party path shape (/AgendaCenter,
   /Portal/MeetingInformation.aspx, /Citizens/, /ViewPublisher.php,
   /MediaPlayer.php, portal.civicclerk.com, go.boarddocs.com,
   simbli.eboardsolutions.com -- the list named in this WO's brief, since
   WO-267's platform_signatures.csv had not landed when this ran), and
   "medium" for a bare keyword match with no vendor signature. A plain
   HEAD (never a GET) on at most 3 candidate hub URLs per domain is
   allowed, only to drop a dead link -- never to confirm video, which is
   the next WO's job.

Politeness: one request in flight per host, >=2.5s between requests to
the SAME host, >=1.5s between governments, an honest User-Agent, and a
robots.txt Disallow on the sitemap path itself is honored (the fetch is
skipped, recorded as `robots_disallows_sitemap`). DNS and the two archive
indexes are not requests to the government and carry no delay. Stops
outright (does not retry) on any response that looks like a human-
verification challenge (same marker list as wo147's CHALLENGE_MARKERS).

Resumable: every processed domain is appended as one JSON line to
`research/wo268_passive_pilot.jsonl` immediately, and a re-run skips any
domain already present there. `--build-candidates` (run once) writes the
stratified 300-domain list to `research/wo268_candidates.csv`; every
other run reads that file and the JSONL resume state. `--limit N`
processes at most N *new* domains this invocation, so a long sweep can be
run in chunks with a generous-but-bounded Bash timeout per chunk, per
CLAUDE.md's rule against an agent-less background sweep.

Usage (from the rtr-deeplink repo root, shared venv):
    .venv/bin/python scripts/wo268_passive_discovery.py --build-candidates
    .venv/bin/python scripts/wo268_passive_discovery.py --limit 40
    .venv/bin/python scripts/wo268_passive_discovery.py --finalize
(`--finalize` rewrites the summary CSV and the hub path-frequency CSV
from whatever is in the JSONL so far -- safe to run after every chunk.)

This script imports no `app.*`/`archive.*` code and opens no database
connection -- it is pure DNS + HTTP against public endpoints, so it needs
no DATABASE_URL. (Set one anyway per CLAUDE.md's worktree `.env` bullet
if you ever add an app/archive import here.)
"""

import argparse
import csv
import gzip
import json
import random
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import requests

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
JC_CSV = RESEARCH_DIR / "jurisdiction_coverage.csv"
CANDIDATES_CSV = RESEARCH_DIR / "wo268_candidates.csv"
PILOT_JSONL = RESEARCH_DIR / "wo268_passive_pilot.jsonl"
PILOT_CSV = RESEARCH_DIR / "wo268_passive_pilot.csv"
HUBFREQ_CSV = RESEARCH_DIR / "wo268_hub_path_frequency.csv"

MIN_POPULATION = 5000
TARGET_COUNTY = 100
TARGET_MUNICIPALITY = 150
TARGET_TOWNSHIP_OTHER = 50
SELECTION_SEED = 268  # WO number, for a reproducible shuffle

# "Nothing found" reject-reason family, per this WO's brief and
# ENUMERATION_METHODS.md #23's taxonomy -- a blank reason means "never
# checked," which counts the same way here.
NOTHING_FOUND_REASONS = {"no-platform-link-found", "no-platform-signature", ""}

HONEST_UA = (
    "rtr-upcoming/0.1 (Red Tape Recordings public-agenda reader; "
    "+https://redtaperecordings.com/about)"
)
HEADERS = {
    "User-Agent": HONEST_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

REQUEST_TIMEOUT = 10
CDX_TIMEOUT = 20
CC_TIMEOUT = 15
HOST_DELAY_SECONDS = 2.5
GOV_DELAY_SECONDS = 1.5
DNS_TIMEOUT = "3"  # dig +time=<n>
MAX_SUB_SITEMAPS = 3
MAX_FLAGGED_RECORDED = 25  # cap per domain, per source, so the JSONL stays sane
MAX_HUB_HEAD_CHECKS = 3

# Same marker list as scripts/wo147_access_ladder_sweep.py's
# CHALLENGE_MARKERS -- copied, not imported, to keep this script free of
# that module's heavier aiohttp/app import chain.
CHALLENGE_MARKERS = [
    "just a moment",
    "attention required! | cloudflare",
    "checking your browser before accessing",
    "cf-browser-verification",
    "cf-chl-bypass",
    "ddos protection by",
    "sgcaptcha",
    "px-captcha",
    "perimeterx",
    "distil_r_captcha",
    "captcha-delivery",
    "request unsuccessful. incapsula",
    "access to this page has been denied",
]

# Copied verbatim from scripts/wo147_access_ladder_sweep.py's
# _PLATFORM_ALIASES (WO-147, 2026-09-10) -- kept as a local copy rather
# than an import so this detection-only pilot stays free of app/archive
# imports and a DB connection. WO-267's platform_signatures.csv +
# scripts/platform_fingerprints.py are meant to supersede this list once
# they land (per this WO's brief) -- update here when they do.
_PLATFORM_ALIASES = {
    "granicus.com": "granicus",
    "legistar.com": "legistar",
    "civicweb.net": "civicweb",
    "escribemeetings": "escribe",
    "escribemeetings.com": "escribe",
    "civicclerk.com": "civicclerk",
    "civicplus.com": "civicplus",
    "primegov.com": "primegov",
    "swagit.com": "swagit",
    "iqm2.com": "iqm2",
    "cablecast.tv": "cablecast",
    "telvue.com": "telvue",
    "champds.com": "champds",
    "clerkshq.com": "clerkbase",
    "municodemeetings.com": "municode_meetings",
    "meetings.municode.com": "municode_meetings",
}

# First-party path shapes named in this WO's brief -- platforms that can
# be self-hosted under the government's own domain (or a vendor host not
# already covered by _PLATFORM_ALIASES), so a hostname-only match would
# miss them.
_PATH_SHAPE_PLATFORMS = [
    (re.compile(r"/agendacenter", re.I), "civicplus"),
    (re.compile(r"/portal/meetinginformation\.aspx", re.I), "civicclerk"),
    (re.compile(r"/citizens/", re.I), "iqm2"),
    (re.compile(r"/viewpublisher\.php", re.I), "granicus"),
    (re.compile(r"/mediaplayer\.php", re.I), "granicus"),
]
_HOST_SHAPE_PLATFORMS = [
    ("portal.civicclerk.com", "civicclerk"),
    ("go.boarddocs.com", "boarddocs"),
    ("simbli.eboardsolutions.com", "eboardsolutions"),
]

VENDOR_SUBDOMAIN_GUESSES = [
    "agenda",
    "agendas",
    "meetings",
    "video",
    "granicus",
    "legistar",
    "civicweb",
    "boarddocs",
]
# Confirmed live against this checkout on 2026-09-12 (`dig A
# nonsensexyz123.<vendor-domain>`, a label that cannot be a real tenant):
# granicus.com, legistar.com, iqm2.com and civicclerk.com's portal
# subdomain each resolve a NONSENSE label to the same real cluster --
# exactly ENUMERATION_METHODS.md #48's "six platforms don't wildcard
# their DNS" finding, confirmed again rather than assumed (ruled out:
# primegov.com and civicweb.net did return NXDOMAIN for the same nonsense
# label, matching #48's list). `wildcards_dns=True` means a resolving
# guess under that vendor proves NOTHING by itself -- recorded as an
# unverified candidate, never as a classification hit on its own.
VENDOR_LABEL_TEMPLATES = [
    ("{label}.granicus.com", "granicus", True),
    ("{label}.legistar.com", "legistar", True),
    ("{label}.civicweb.net", "civicweb", False),
    ("{label}.iqm2.com", "iqm2", True),
    ("{label}.portal.civicclerk.com", "civicclerk", True),
    ("{label}.primegov.com", "primegov", False),
]

KEYWORD_RE = re.compile(
    r"meeting|agenda|minutes|council|commission|board|video|stream", re.I
)

# CNAME-target substring -> vendor family, for the DNS rung's
# classification of a CNAME that isn't one of the meeting-platform
# aliases above but still identifies the site's hosting stack (useful for
# the site-builder/hub-path reporting even when it isn't a meeting
# platform).
CNAME_VENDOR_FAMILIES = [
    ("civicplus.com", "civicplus"),
    ("revize.com", "revize"),
    ("granicus.com", "granicus"),
    ("govaccess.org", "granicus-govaccess"),
    ("streamlinecities.com", "streamline"),
    ("municode.com", "municode"),
    ("wixdns.net", "wix"),
    ("squarespace.com", "squarespace"),
    ("cloudflare.net", "cloudflare"),
    ("cdn.cloudflare.net", "cloudflare"),
]


def log(msg: str) -> None:
    print(msg, flush=True)


# --------------------------------------------------------------------------
# Candidate selection
# --------------------------------------------------------------------------


def government_type(gov_id: str) -> str:
    gov_id = (gov_id or "").strip()
    if gov_id.startswith("us:county:"):
        return "county"
    if gov_id.startswith("us:place:"):
        return "municipality"
    if gov_id.startswith("us:cousub:"):
        return "township_other"
    return "township_other"  # no gov_id, or a type outside place/county/cousub


def looks_like_township_or_other(row: dict) -> bool:
    """`municipality` (`us:place:`) covers cities, towns, villages,
    boroughs and parishes alike -- the research file's gov_id doesn't
    distinguish them. Checked directly: among the 2,026-row candidate
    population this filter produces (see --build-candidates output),
    every us:cousub: row dropped out entirely once population>=5,000 and
    "nothing found" were both applied (there was exactly one). So
    "township/other" is defined operationally, not by gov_id alone: a
    us:cousub: row, OR a us:place: row whose city_name doesn't end in
    "city" (town/village/borough/parish/etc), OR a row with no gov_id at
    all. This is reported plainly in the investigation doc, not hidden."""
    gov_id = (row.get("gov_id") or "").strip()
    if gov_id.startswith("us:cousub:") or not gov_id.startswith(
        ("us:place:", "us:county:")
    ):
        return True
    if gov_id.startswith("us:place:"):
        name = (row.get("city_name") or "").strip().lower()
        return not name.endswith("city")
    return False


def load_jc_rows() -> list:
    with open(JC_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_candidate_pool(rows: list) -> list:
    def is_blank(v):
        return v is None or str(v).strip() == ""

    def pop(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    pool = []
    for row in rows:
        if (row.get("country") or "").strip() != "United States":
            continue
        p = pop(row.get("population_estimate"))
        if p is None or p < MIN_POPULATION:
            continue
        if is_blank(row.get("domain")):
            continue
        if (row.get("transcribed") or "").strip().lower() in ("true", "1", "yes"):
            continue
        if not (
            is_blank(row.get("suspected_calendar_provider"))
            and is_blank(row.get("suspected_meeting_link_provider"))
            and is_blank(row.get("suspected_video_provider"))
        ):
            continue
        rr = (row.get("reject_reason") or "").strip()
        if rr not in NOTHING_FOUND_REASONS:
            continue
        pool.append(row)
    return pool


def stratified_sample(pool: list) -> list:
    counties = [r for r in pool if government_type(r.get("gov_id", "")) == "county"]
    townships = [r for r in pool if looks_like_township_or_other(r)]
    # municipality bucket = everything left once counties and
    # township/other are pulled out (so a row never counts twice).
    taken_ids = {id(r) for r in counties} | {id(r) for r in townships}
    municipalities = [r for r in pool if id(r) not in taken_ids]

    def spread_by_state(rows: list, n: int) -> list:
        rng = random.Random(SELECTION_SEED)
        by_state = {}
        for r in rows:
            by_state.setdefault(r.get("state_or_province", ""), []).append(r)
        for st in by_state:
            rng.shuffle(by_state[st])
        states = sorted(by_state.keys())
        rng.shuffle(states)
        picked = []
        i = 0
        while len(picked) < n and any(by_state.values()):
            st = states[i % len(states)]
            if by_state[st]:
                picked.append(by_state[st].pop())
            i += 1
            if i > 10000:
                break
        return picked

    chosen = (
        spread_by_state(counties, TARGET_COUNTY)
        + spread_by_state(municipalities, TARGET_MUNICIPALITY)
        + spread_by_state(townships, TARGET_TOWNSHIP_OTHER)
    )
    return chosen, len(counties), len(municipalities), len(townships)


def cmd_build_candidates() -> None:
    rows = load_jc_rows()
    pool = build_candidate_pool(rows)
    chosen, n_counties, n_munis, n_townships = stratified_sample(pool)
    log(
        f"candidate pool (US, pop>=5000, domain set, no suspected platform, "
        f"not transcribed, reject_reason in nothing-found family): {len(pool)}"
    )
    log(
        f"  of which: county-typed={n_counties}, "
        f"municipality-bucket={n_munis}, township/other-bucket={n_townships}"
    )
    log(f"selected: {len(chosen)} (target 100/150/50)")

    with open(CANDIDATES_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "domain",
                "state_or_province",
                "gov_type",
                "gov_id",
                "population_estimate",
                "city_name",
            ]
        )
        for r in chosen:
            w.writerow(
                [
                    (r.get("domain") or "").strip(),
                    r.get("state_or_province", ""),
                    (
                        "county"
                        if government_type(r.get("gov_id", "")) == "county"
                        and not looks_like_township_or_other(r)
                        else (
                            "township_other"
                            if looks_like_township_or_other(r)
                            else "municipality"
                        )
                    ),
                    r.get("gov_id", ""),
                    r.get("population_estimate", ""),
                    r.get("city_name", ""),
                ]
            )
    log(f"wrote {CANDIDATES_CSV}")


# --------------------------------------------------------------------------
# DNS rung
# --------------------------------------------------------------------------


def dig(record_type: str, host: str) -> list:
    try:
        out = subprocess.run(
            ["dig", f"+time={DNS_TIMEOUT}", "+tries=1", "+short", record_type, host],
            capture_output=True,
            text=True,
            timeout=6,
        )
        lines = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
        return lines
    except Exception:  # noqa: BLE001 -- DNS failure is a normal outcome
        return []


def classify_cname_family(target: str) -> str:
    target = (target or "").lower()
    for host_alias, platform in _PLATFORM_ALIASES.items():
        if host_alias in target:
            return platform
    for suffix, family in CNAME_VENDOR_FAMILIES:
        if suffix in target:
            return family
    return ""


def registrable_label(domain: str) -> str:
    """Best-effort second-level-label guess (e.g. "baldwincountyal.gov"
    -> "baldwincountyal"), used only to guess a vendor tenant subdomain.
    Not WO-260's own helper -- see the module docstring for why."""
    parts = domain.lower().strip(".").split(".")
    if len(parts) < 2:
        return domain.lower()
    # Handle the common two-label public suffixes this corpus actually
    # has (.gov/.org/.com/.us + a state code like .oh.us), and Canada's
    # province suffixes (ville.sthonore.qc.ca -> "sthonore"; without this
    # every *.qc.ca domain guessed "qc" and hit PrimeGov's own regional
    # qc.primegov.com page -- WO-324, ENUMERATION_METHODS §333). Same rule
    # as wo273_recon.registrable_label(), kept in step by hand.
    if len(parts) >= 3 and parts[-1] == "us" and len(parts[-2]) <= 3:
        return parts[-3]
    if (
        len(parts) >= 3
        and parts[-1] == "ca"
        and parts[-2]
        in (
            "ab",
            "bc",
            "mb",
            "nb",
            "nl",
            "ns",
            "nt",
            "nu",
            "on",
            "pe",
            "qc",
            "sk",
            "yk",
            "gc",
        )
    ):
        return parts[-3]
    return parts[-2]


def dns_lookup(domain: str) -> dict:
    result = {
        "apex_a": dig("A", domain),
        "apex_cname": (dig("CNAME", domain) or [""])[0],
        "www_a": dig("A", f"www.{domain}"),
        "www_cname": (dig("CNAME", f"www.{domain}") or [""])[0],
        "resolving_subdomains": [],
        "resolving_vendor_labels": [],
    }
    result["cname_target_family"] = classify_cname_family(
        result["apex_cname"] or result["www_cname"]
    )

    apex_a_set = set(result["apex_a"])
    for sub in VENDOR_SUBDOMAIN_GUESSES:
        host = f"{sub}.{domain}"
        cname = (dig("CNAME", host) or [""])[0]
        a = dig("A", host) if not cname else []
        if not (cname or a):
            continue
        # A guessed subdomain that resolves to the SAME A records as the
        # apex, with no CNAME of its own, is almost always the
        # government's own catch-all/wildcard DNS on its own zone, not a
        # deliberately created "granicus."/"agenda." subdomain -- flagged
        # so classify_from_dns() doesn't treat it as a real signal.
        likely_own_domain_wildcard = (
            bool(a) and not cname and set(a) == apex_a_set and bool(apex_a_set)
        )
        result["resolving_subdomains"].append(
            {
                "subdomain": sub,
                "host": host,
                "cname": cname,
                "a": a,
                "family": classify_cname_family(cname) if cname else "",
                "likely_own_domain_wildcard": likely_own_domain_wildcard,
            }
        )

    label = registrable_label(domain)
    for template, platform, wildcards_dns in VENDOR_LABEL_TEMPLATES:
        host = template.format(label=label)
        a = dig("A", host)
        cname = (dig("CNAME", host) or [""])[0]
        if a or cname:
            result["resolving_vendor_labels"].append(
                {
                    "host": host,
                    "platform": platform,
                    "a": a,
                    "cname": cname,
                    "wildcards_dns": wildcards_dns,
                }
            )

    return result


def classify_from_dns(dns_info: dict) -> dict:
    if dns_info["cname_target_family"] in _PLATFORM_ALIASES.values():
        return {
            "platform": dns_info["cname_target_family"],
            "evidence": f"CNAME -> {dns_info['apex_cname'] or dns_info['www_cname']}",
            "confidence": "high",
        }
    for sub in dns_info["resolving_subdomains"]:
        if sub["likely_own_domain_wildcard"]:
            continue
        if sub["family"] in _PLATFORM_ALIASES.values():
            return {
                "platform": sub["family"],
                "evidence": f"{sub['host']} CNAME -> {sub['cname']}",
                "confidence": "high",
            }
    for vl in dns_info["resolving_vendor_labels"]:
        # A resolving guess under a wildcarding vendor (granicus,
        # legistar, iqm2, civicclerk -- see VENDOR_LABEL_TEMPLATES'
        # comment) proves nothing by itself; it's kept in the record as
        # an unverified candidate but never counted as a DNS hit here.
        if vl["wildcards_dns"]:
            continue
        return {
            "platform": vl["platform"],
            "evidence": f"guessed tenant host resolves: {vl['host']}",
            "confidence": "high",
        }
    return {}


# --------------------------------------------------------------------------
# Sitemap + robots rung
# --------------------------------------------------------------------------

_last_request_at = {}


def polite_get(url: str, timeout=REQUEST_TIMEOUT, method="GET"):
    host = urlparse(url).netloc
    now = time.monotonic()
    last = _last_request_at.get(host)
    if last is not None:
        wait = HOST_DELAY_SECONDS - (now - last)
        if wait > 0:
            time.sleep(wait)
    try:
        resp = requests.request(
            method, url, headers=HEADERS, timeout=timeout, allow_redirects=True
        )
    finally:
        _last_request_at[host] = time.monotonic()
    return resp


def is_challenge(text: str) -> bool:
    lower = (text or "").lower()
    return any(marker in lower for marker in CHALLENGE_MARKERS)


def parse_robots(text: str) -> dict:
    sitemap_urls = []
    disallow_paths = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "sitemap":
            sitemap_urls.append(value)
        elif key == "disallow":
            disallow_paths.append(value)
    return {"sitemap_urls": sitemap_urls, "disallow_paths": disallow_paths}


def builder_hint_from_disallow(disallow_paths: list) -> str:
    blob = " ".join(disallow_paths).lower()
    if "/wp-admin" in blob or "/wp-json" in blob or "wp-content" in blob:
        return "wordpress"
    if "/core/" in blob or "/node/" in blob or "/misc/" in blob:
        return "drupal"
    if "/umbraco" in blob:
        return "umbraco"
    if "/_ah/" in blob:
        return "appengine"
    return ""


def fetch_robots(domain: str) -> dict:
    url = f"https://{domain}/robots.txt"
    out = {
        "fetched": False,
        "status": None,
        "sitemap_directives": [],
        "disallow_paths": [],
        "builder_hint": "",
        "disallows_sitemap": False,
        "error": "",
    }
    try:
        resp = polite_get(url)
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:200]
        return out
    out["status"] = resp.status_code
    if resp.status_code != 200 or not resp.text:
        return out
    if is_challenge(resp.text):
        out["error"] = "challenge-gate"
        return out
    parsed = parse_robots(resp.text)
    out["fetched"] = True
    out["sitemap_directives"] = parsed["sitemap_urls"]
    out["disallow_paths"] = parsed["disallow_paths"][:50]
    out["builder_hint"] = builder_hint_from_disallow(parsed["disallow_paths"])
    out["disallows_sitemap"] = any(
        "sitemap" in d.lower() for d in parsed["disallow_paths"]
    )
    return out


def parse_sitemap_xml(body: bytes):
    try:
        if body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
        root = ElementTree.fromstring(body)
    except Exception:
        return None, []
    tag = root.tag.rsplit("}", 1)[-1].lower()
    urls = []
    if tag == "sitemapindex":
        for sm in root:
            loc = sm.find("{*}loc")
            if loc is None:
                for child in sm:
                    if child.tag.rsplit("}", 1)[-1].lower() == "loc":
                        loc = child
                        break
            if loc is not None and loc.text:
                urls.append(loc.text.strip())
        return "index", urls
    if tag == "urlset":
        for u in root:
            loc = None
            for child in u:
                if child.tag.rsplit("}", 1)[-1].lower() == "loc":
                    loc = child
                    break
            if loc is not None and loc.text:
                urls.append(loc.text.strip())
        return "urlset", urls
    return None, []


def guess_site_builder(urls: list, sub_sitemap_names: list) -> str:
    names_blob = " ".join(sub_sitemap_names).lower()
    if re.search(r"(post|page|category)-sitemap", names_blob):
        return "wordpress"
    if re.search(r"wp-sitemap", names_blob):
        return "wordpress"
    sample = " ".join(urls[:50]).lower()
    if "/config/" in sample and "squarespace" in sample:
        return "squarespace"
    if "civicplus" in sample or "/agendacenter" in sample:
        return "civicplus"
    return ""


def flag_urls(urls: list) -> list:
    flagged = []
    for u in urls:
        host = urlparse(u).netloc.lower()
        path = urlparse(u).path
        platform = None
        for alias, p in _PLATFORM_ALIASES.items():
            if alias in host:
                platform = p
                break
        if platform is None:
            for shape_host, p in _HOST_SHAPE_PLATFORMS:
                if shape_host in host:
                    platform = p
                    break
        if platform is None:
            for rx, p in _PATH_SHAPE_PLATFORMS:
                if rx.search(path):
                    platform = p
                    break
        keyword_hit = bool(KEYWORD_RE.search(path))
        if platform or keyword_hit:
            flagged.append(
                {"url": u, "platform": platform or "", "keyword_hit": keyword_hit}
            )
    return flagged


def fetch_sitemap(domain: str, robots_info: dict) -> dict:
    out = {
        "found": False,
        "url_used": "",
        "kind": "",
        "sub_sitemaps_followed": 0,
        "url_count": 0,
        "flagged_urls": [],
        "flagged_count": 0,
        "site_builder_guess": "",
        "error": "",
    }
    if robots_info.get("disallows_sitemap"):
        out["error"] = "robots-disallows-sitemap"
        return out

    base = f"https://{domain}/"
    # A Sitemap: directive is allowed to be a relative path by a
    # noncompliant robots.txt (real-world example hit live: holtcountyne
    # et al's directive was a bare "/sitemap.xml") -- resolve it against
    # the site's own origin rather than letting requests.get() raise
    # "No scheme supplied" on a half-finished URL.
    candidates = [
        urljoin(base, d) for d in (robots_info.get("sitemap_directives") or [])
    ]
    for default in (
        f"https://{domain}/sitemap.xml",
        f"https://{domain}/sitemap_index.xml",
    ):
        if default not in candidates:
            candidates.append(default)

    all_urls = []
    sub_sitemap_names = []
    used_url = ""
    kind = ""
    last_error = ""
    for url in candidates:
        try:
            resp = polite_get(url)
        except Exception as e:  # noqa: BLE001
            last_error = str(e)[:200]
            continue
        if resp.status_code != 200 or not resp.content:
            last_error = f"http-{resp.status_code}"
            continue
        if resp.content[:2] != b"\x1f\x8b" and is_challenge(
            resp.content[:4000].decode("utf-8", errors="replace")
        ):
            out["error"] = "challenge-gate"
            return out
        kind, urls = parse_sitemap_xml(resp.content)
        if kind is None:
            continue
        used_url = url
        if kind == "index":
            sub_sitemap_names = urls
            all_urls.extend(urls)
            followed = 0
            for sub_url in urls[:MAX_SUB_SITEMAPS]:
                try:
                    sub_resp = polite_get(sub_url)
                except Exception:  # noqa: BLE001
                    continue
                if sub_resp.status_code != 200 or not sub_resp.content:
                    continue
                sub_kind, sub_urls = parse_sitemap_xml(sub_resp.content)
                if sub_kind == "urlset":
                    all_urls.extend(sub_urls)
                    followed += 1
            out["sub_sitemaps_followed"] = followed
        else:
            all_urls.extend(urls)
        break

    if not used_url:
        out["error"] = last_error or "no-sitemap-found"
        return out

    out["found"] = True
    out["url_used"] = used_url
    out["kind"] = kind
    out["error"] = ""
    out["url_count"] = len(all_urls)
    flagged = flag_urls(all_urls)
    out["flagged_count"] = len(flagged)
    out["flagged_urls"] = flagged[:MAX_FLAGGED_RECORDED]
    out["site_builder_guess"] = robots_info.get("builder_hint") or guess_site_builder(
        all_urls, sub_sitemap_names
    )
    return out


# --------------------------------------------------------------------------
# Archive-index rung (Wayback CDX + Common Crawl)
# --------------------------------------------------------------------------


def fetch_wayback_cdx(domain: str) -> dict:
    out = {
        "reachable": False,
        "capture_count": 0,
        "flagged_urls": [],
        "flagged_count": 0,
        "error": "",
    }
    url = (
        "https://web.archive.org/cdx/search/cdx"
        f"?url={domain}/*&matchType=domain&collapse=urlkey"
        "&filter=statuscode:200&limit=2000&fl=original,timestamp&output=json"
    )
    try:
        resp = requests.get(url, headers=HEADERS, timeout=CDX_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:200]
        return out
    if resp.status_code != 200 or not resp.text.strip():
        out["error"] = (
            f"http-{resp.status_code}" if resp.text.strip() else "empty-no-captures"
        )
        out["reachable"] = resp.status_code == 200
        return out
    try:
        rows = json.loads(resp.text)
    except Exception as e:  # noqa: BLE001
        out["error"] = f"bad-json: {e}"[:200]
        return out
    out["reachable"] = True
    data_rows = rows[1:] if rows else []
    out["capture_count"] = len(data_rows)
    urls = [r[0] for r in data_rows if r]
    flagged = flag_urls(urls)
    out["flagged_count"] = len(flagged)
    out["flagged_urls"] = flagged[:MAX_FLAGGED_RECORDED]
    return out


def fetch_common_crawl(domain: str, crawl_id: str) -> dict:
    out = {
        "reachable": False,
        "crawl_id": crawl_id,
        "capture_count": 0,
        "flagged_urls": [],
        "flagged_count": 0,
        "error": "",
    }
    if not crawl_id:
        out["error"] = "no-crawl-id-available"
        return out
    url = (
        f"https://index.commoncrawl.org/{crawl_id}-index"
        f"?url={domain}/*&output=json&limit=2000"
    )
    try:
        resp = requests.get(url, headers=HEADERS, timeout=CC_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:200]
        return out
    if resp.status_code == 404:
        out["reachable"] = True
        out["error"] = "no-captures"
        return out
    if resp.status_code != 200:
        out["error"] = f"http-{resp.status_code}"
        return out
    out["reachable"] = True
    urls = []
    for line in resp.text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if rec.get("url"):
            urls.append(rec["url"])
    out["capture_count"] = len(urls)
    flagged = flag_urls(urls)
    out["flagged_count"] = len(flagged)
    out["flagged_urls"] = flagged[:MAX_FLAGGED_RECORDED]
    return out


_cc_latest_crawl_id_cache = None


def latest_common_crawl_id() -> str:
    global _cc_latest_crawl_id_cache
    if _cc_latest_crawl_id_cache is not None:
        return _cc_latest_crawl_id_cache
    try:
        resp = requests.get(
            "https://index.commoncrawl.org/collinfo.json",
            headers=HEADERS,
            timeout=CC_TIMEOUT,
        )
        resp.raise_for_status()
        info = resp.json()
        _cc_latest_crawl_id_cache = info[0]["id"] if info else ""
    except Exception:  # noqa: BLE001
        _cc_latest_crawl_id_cache = ""
    return _cc_latest_crawl_id_cache


# --------------------------------------------------------------------------
# Classification + hub verification
# --------------------------------------------------------------------------


def classify_from_flagged(flagged: list) -> dict:
    for f in flagged:
        if f.get("platform"):
            return {
                "platform": f["platform"],
                "evidence": f["url"],
                "confidence": "high",
            }
    for f in flagged:
        if f.get("keyword_hit"):
            return {
                "platform": "",
                "evidence": f["url"],
                "confidence": "medium",
            }
    return {}


def head_check(url: str) -> bool:
    try:
        resp = polite_get(url, timeout=6, method="HEAD")
        return resp.status_code < 400
    except Exception:  # noqa: BLE001
        try:
            resp = polite_get(url, timeout=6, method="GET")
            return resp.status_code < 400
        except Exception:  # noqa: BLE001
            return False


def classify_domain(dns_info, sitemap_info, wayback_info, cc_info) -> dict:
    method_order = [
        ("dns", classify_from_dns(dns_info)),
        ("sitemap", classify_from_flagged(sitemap_info.get("flagged_urls", []))),
        ("wayback", classify_from_flagged(wayback_info.get("flagged_urls", []))),
        ("commoncrawl", classify_from_flagged(cc_info.get("flagged_urls", []))),
    ]
    for method, hit in method_order:
        if hit:
            hit["method"] = method
            return hit
    return {"platform": "", "evidence": "", "confidence": "none", "method": "none"}


def rank_candidate_hub_urls(
    classification: dict, sitemap_info, wayback_info, cc_info
) -> list:
    """Best-first list of candidate hub URLs: the classification's own
    evidence URL (if it has one) leads, then every platform-flagged URL
    across the three sources, then every keyword-only flag. Deduplicated,
    order preserved -- `process_domain()` HEAD-checks up to
    MAX_HUB_HEAD_CHECKS of these and keeps the first one that answers, per
    this WO's "allowed to drop a dead link" rule."""
    ranked = []
    seen = set()

    def add(url):
        if url and url.startswith("http") and url not in seen:
            seen.add(url)
            ranked.append(url)

    add(classification.get("evidence", ""))
    for info in (sitemap_info, wayback_info, cc_info):
        for f in info.get("flagged_urls", []):
            if f.get("platform"):
                add(f["url"])
    for info in (sitemap_info, wayback_info, cc_info):
        for f in info.get("flagged_urls", []):
            if f.get("keyword_hit"):
                add(f["url"])
    return ranked


# --------------------------------------------------------------------------
# Main sweep
# --------------------------------------------------------------------------


def load_done_domains() -> set:
    done = set()
    if PILOT_JSONL.exists():
        with open(PILOT_JSONL, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    done.add(rec["domain"])
                except Exception:  # noqa: BLE001
                    continue
    return done


def process_domain(row: dict, crawl_id: str) -> dict:
    domain = row["domain"]
    record = {
        "domain": domain,
        "state": row.get("state_or_province", ""),
        "gov_type": row.get("gov_type", ""),
        "gov_id": row.get("gov_id", ""),
        "population": row.get("population_estimate", ""),
        "processed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    dns_info = dns_lookup(domain)
    record["dns"] = dns_info

    robots_info = fetch_robots(domain)
    record["robots"] = robots_info

    sitemap_info = fetch_sitemap(domain, robots_info)
    record["sitemap"] = sitemap_info

    wayback_info = fetch_wayback_cdx(domain)
    record["wayback"] = wayback_info

    cc_info = fetch_common_crawl(domain, crawl_id)
    record["common_crawl"] = cc_info

    classification = classify_domain(dns_info, sitemap_info, wayback_info, cc_info)
    ranked_hubs = rank_candidate_hub_urls(
        classification, sitemap_info, wayback_info, cc_info
    )
    hub_url = ""
    hub_alive = None
    hubs_tried = 0
    dead_hubs = []
    for candidate in ranked_hubs[:MAX_HUB_HEAD_CHECKS]:
        hubs_tried += 1
        if head_check(candidate):
            hub_url = candidate
            hub_alive = True
            break
        dead_hubs.append(candidate)
    else:
        # exhausted the cap with nothing alive -- keep the top-ranked
        # candidate for visibility, marked dead rather than silently
        # dropped, so "found a hub but it's dead" is its own reportable
        # bucket distinct from "nothing found at all."
        if ranked_hubs:
            hub_url = ranked_hubs[0]
            hub_alive = False

    classification["candidate_hub_url"] = hub_url
    classification["hub_checked"] = hubs_tried > 0
    classification["hub_alive"] = hub_alive
    classification["hub_candidates_tried"] = hubs_tried
    classification["dead_hub_candidates"] = dead_hubs
    record["classification"] = classification

    return record


def cmd_sweep(limit: int) -> None:
    if not CANDIDATES_CSV.exists():
        log(f"{CANDIDATES_CSV} missing -- run with --build-candidates first")
        sys.exit(1)
    with open(CANDIDATES_CSV, newline="", encoding="utf-8") as f:
        candidates = list(csv.DictReader(f))

    done = load_done_domains()
    crawl_id = latest_common_crawl_id()
    log(f"common crawl latest index: {crawl_id or '(unreachable)'}")

    remaining = [r for r in candidates if r["domain"] not in done]
    log(f"{len(done)} already done, {len(remaining)} remaining of {len(candidates)}")

    to_process = remaining[:limit] if limit else remaining
    consecutive_errors = 0
    with open(PILOT_JSONL, "a", encoding="utf-8") as out:
        for i, row in enumerate(to_process):
            domain = row["domain"]
            log(
                f"[{i + 1}/{len(to_process)}] {domain} ({row.get('gov_type')}, {row.get('state_or_province')})"
            )
            try:
                record = process_domain(row, crawl_id)
                out.write(json.dumps(record) + "\n")
                out.flush()
                consecutive_errors = 0
                cls = record["classification"]
                log(
                    f"    -> platform={cls.get('platform') or '(none)'} "
                    f"confidence={cls.get('confidence')} method={cls.get('method')}"
                )
            except KeyboardInterrupt:
                raise
            except Exception as e:  # noqa: BLE001 -- one bad domain never kills the sweep
                consecutive_errors += 1
                log(f"    ERROR: {e}")
                err_record = {
                    "domain": domain,
                    "state": row.get("state_or_province", ""),
                    "gov_type": row.get("gov_type", ""),
                    "gov_id": row.get("gov_id", ""),
                    "population": row.get("population_estimate", ""),
                    "processed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "error": str(e)[:300],
                    "classification": {
                        "platform": "",
                        "confidence": "none",
                        "method": "error",
                    },
                }
                out.write(json.dumps(err_record) + "\n")
                out.flush()
                if consecutive_errors >= 8:
                    log("8 consecutive errors -- stopping this chunk early")
                    break
            time.sleep(GOV_DELAY_SECONDS)

    log(f"chunk done. {len(remaining) - len(to_process)} domains remain unprocessed.")


# --------------------------------------------------------------------------
# Finalize: summary CSV + hub path-frequency CSV
# --------------------------------------------------------------------------


def load_all_records() -> list:
    records = []
    if not PILOT_JSONL.exists():
        return records
    with open(PILOT_JSONL, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:  # noqa: BLE001
                continue
    return records


def cmd_finalize() -> None:
    records = load_all_records()
    log(f"{len(records)} records in {PILOT_JSONL}")

    fieldnames = [
        "domain",
        "state",
        "gov_type",
        "gov_id",
        "population",
        "platform_found",
        "confidence",
        "method",
        "candidate_hub_url",
        "hub_checked",
        "hub_alive",
        "dns_cname_family",
        "dns_resolving_subdomains",
        "dns_resolving_vendor_labels",
        "robots_fetched",
        "robots_builder_hint",
        "sitemap_found",
        "sitemap_url_count",
        "sitemap_flagged_count",
        "sitemap_site_builder_guess",
        "wayback_reachable",
        "wayback_capture_count",
        "wayback_flagged_count",
        "wayback_error",
        "common_crawl_reachable",
        "common_crawl_capture_count",
        "common_crawl_flagged_count",
        "common_crawl_error",
        "error",
    ]
    with open(PILOT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in records:
            dns_info = r.get("dns", {}) or {}
            robots_info = r.get("robots", {}) or {}
            sitemap_info = r.get("sitemap", {}) or {}
            wayback_info = r.get("wayback", {}) or {}
            cc_info = r.get("common_crawl", {}) or {}
            cls = r.get("classification", {}) or {}
            w.writerow(
                {
                    "domain": r.get("domain", ""),
                    "state": r.get("state", ""),
                    "gov_type": r.get("gov_type", ""),
                    "gov_id": r.get("gov_id", ""),
                    "population": r.get("population", ""),
                    "platform_found": cls.get("platform", ""),
                    "confidence": cls.get("confidence", "none"),
                    "method": cls.get("method", "none"),
                    "candidate_hub_url": cls.get("candidate_hub_url", ""),
                    "hub_checked": cls.get("hub_checked", False),
                    "hub_alive": cls.get("hub_alive", ""),
                    "dns_cname_family": dns_info.get("cname_target_family", ""),
                    "dns_resolving_subdomains": ";".join(
                        s["host"]
                        + (
                            " (own-domain-wildcard)"
                            if s.get("likely_own_domain_wildcard")
                            else ""
                        )
                        for s in dns_info.get("resolving_subdomains", [])
                    ),
                    "dns_resolving_vendor_labels": ";".join(
                        v["host"]
                        + (" (unverified-wildcard)" if v.get("wildcards_dns") else "")
                        for v in dns_info.get("resolving_vendor_labels", [])
                    ),
                    "robots_fetched": robots_info.get("fetched", False),
                    "robots_builder_hint": robots_info.get("builder_hint", ""),
                    "sitemap_found": sitemap_info.get("found", False),
                    "sitemap_url_count": sitemap_info.get("url_count", 0),
                    "sitemap_flagged_count": sitemap_info.get("flagged_count", 0),
                    "sitemap_site_builder_guess": sitemap_info.get(
                        "site_builder_guess", ""
                    ),
                    "wayback_reachable": wayback_info.get("reachable", False),
                    "wayback_capture_count": wayback_info.get("capture_count", 0),
                    "wayback_flagged_count": wayback_info.get("flagged_count", 0),
                    "wayback_error": wayback_info.get("error", ""),
                    "common_crawl_reachable": cc_info.get("reachable", False),
                    "common_crawl_capture_count": cc_info.get("capture_count", 0),
                    "common_crawl_flagged_count": cc_info.get("flagged_count", 0),
                    "common_crawl_error": cc_info.get("error", ""),
                    "error": r.get("error", ""),
                }
            )
    log(f"wrote {PILOT_CSV}")

    # Hub path-frequency table, from sitemap flagged URLs only (per this
    # WO's brief -- deliverable #4 feeds the next WO's path-probe builder).
    pattern_counter = Counter()
    pattern_example = {}
    pattern_platform = Counter()
    for r in records:
        sitemap_info = r.get("sitemap", {}) or {}
        for f in sitemap_info.get("flagged_urls", []):
            path = urlparse(f["url"]).path or "/"
            segments = [s for s in path.split("/") if s]
            pattern = "/" + segments[0].lower() if segments else "/"
            pattern_counter[pattern] += 1
            pattern_example.setdefault(pattern, f["url"])
            if f.get("platform"):
                pattern_platform[(pattern, f["platform"])] += 1

    with open(HUBFREQ_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["path_pattern", "count", "example_url", "platform_implied"])
        for pattern, count in pattern_counter.most_common():
            implied = ""
            best = 0
            for (p, plat), c in pattern_platform.items():
                if p == pattern and c > best:
                    implied = plat
                    best = c
            w.writerow([pattern, count, pattern_example.get(pattern, ""), implied])
    log(f"wrote {HUBFREQ_CSV}")

    # Quick console summary
    total = len(records)
    found = sum(1 for r in records if (r.get("classification") or {}).get("platform"))
    hub_only = sum(
        1
        for r in records
        if not (r.get("classification") or {}).get("platform")
        and (r.get("classification") or {}).get("candidate_hub_url")
    )
    nothing = total - found - hub_only
    log(
        f"summary: total={total} platform_found={found} hub_found_no_platform={hub_only} nothing={nothing}"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-candidates", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()

    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)

    if args.build_candidates:
        cmd_build_candidates()
        return
    if args.finalize:
        cmd_finalize()
        return
    cmd_sweep(args.limit)


if __name__ == "__main__":
    main()
