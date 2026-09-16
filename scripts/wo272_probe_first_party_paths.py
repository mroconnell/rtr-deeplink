"""WO-272 Stage 2: bounded, polite validation of the top first-party
templates Stage 1 found (`scripts/wo272_url_shape_mining.py`).

Probes a fixed set of first-party path templates on a sample of
governments with a domain on file and no known platform (population
5,000+). One plain HONEST_HEADERS GET per (government, template), one
government's host at a time, a real pause between requests, stopping
outright (never retrying) on a 403 or a CHALLENGE_MARKERS hit. Records,
per (government, template): the HTTP outcome, and -- only for a 200 --
whether the page actually names THIS government AND carries a meeting
word (WO-260's finding: a 200 alone proves nothing, several vendors
answer any bogus path with a 200).

Resumable: flushes `wo272_probe_yield_raw.csv` one row at a time and
skips (government, template) pairs already present on a re-run.

No ingest, no jurisdiction_coverage.csv write, no production write.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

RTR_BUSINESS = Path("/Users/mroconnell/Documents/rtr-business/research")
JC_CSV = RTR_BUSINESS / "jurisdiction_coverage.csv"

SCRATCH = Path(
    "/private/tmp/claude-501/-Users-mroconnell-Documents-rtr-deeplink--claude-worktrees-platform-detection-backfill-c9742a"
    "/1d27de13-eb07-451a-a07a-bb18900b5618/scratchpad/agents/a7e73d38a61b93564"
)
RAW_OUT = SCRATCH / "wo272_probe_yield_raw.csv"

HONEST_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-encoding": "gzip, deflate",
    "accept-language": "en-US,en;q=0.9",
    "user-agent": (
        "rtr-upcoming/0.1 (Red Tape Recordings public-agenda reader; "
        "+https://redtaperecordings.com/about)"
    ),
}
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

MEETING_WORDS = (
    "meeting",
    "agenda",
    "minutes",
    "council",
    "board",
    "video",
    "stream",
)

# Top first-party templates from wo272_url_templates.csv, by
# distinct-government support (2026-09-12 run), excluding CivicPlus's
# bare /AgendaCenter root: already exhaustively probed across the whole
# 14,553-government candidate list by WO-174/WO-230/WO-249/WO-261 (see
# docs/COVERAGE_HANDOVER.md section 6) -- re-probing it here would not
# be a genuinely untested shape.
# The `/{id}/...` and `/{token}` variants Stage 1 also found (e.g.
# `/{id}/Agendas-Minutes`, `/AgendaCenter/{token}`) are excluded here on
# purpose: they need a real numeric id or slug this probe has no way to
# guess cheaply, and the bare-path templates below already answer the
# probe question that matters ("does a path with this NAME exist at
# all"). See the module docstring.
TEMPLATES = [
    "/Agendas-Minutes",
    "/City-Council",
    "/meetings",
    "/government/city-council",
    "/AgendasAndMinutes",
    "/boards",
    "/council",
    "/DocumentCenter",
    "/town-council",
]


def build_url(domain: str, template: str) -> str | None:
    """Fill a template into a real URL. `{id}` templates need a real
    numeric id we don't have -- CivicPlus's `/{id}/...` shape always
    starts numbering from a small number per tenant, so id=1 through a
    handful is tried elsewhere in this repo (see civicplus.py), but a
    single-shot probe here just skips id-shaped templates: they can't be
    guessed cheaply and reliably, and the bare-path templates below
    already cover the real probe question (does a path with this NAME
    exist at all)."""
    if "{id}" in template or "{token}" in template:
        return None
    return f"https://{domain}{template}"


def fetch(url: str) -> tuple[str, str, str | None]:
    """Returns (outcome, note, body_lower_or_None). outcome in {200,
    soft404, 404, blocked, error}. body_lower is only returned for a
    real 200, since that is the only case the caller needs page content
    for."""
    req = urllib.request.Request(url, headers=HONEST_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.status
            body = resp.read(200_000).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 403:
            return "blocked", "http-403", None
        if e.code == 404:
            return "404", "http-404", None
        return "error", f"http-{e.code}", None
    except Exception as e:  # noqa: BLE001 -- network probe, log and move on
        return "error", type(e).__name__, None

    lower = body.lower()
    for marker in CHALLENGE_MARKERS:
        if marker in lower:
            return "blocked", f"challenge:{marker}", None

    if status != 200:
        return "error", f"http-{status}", None

    # Soft-404 heuristic: a real error/redirect page rendered as 200 --
    # common shape is a short body or an explicit "not found"/"page
    # cannot be found" phrase, or a generic CMS home page shell with no
    # real content (WO-260's "any bogus label answers 200" finding).
    soft_404_markers = (
        "page not found",
        "page cannot be found",
        "the page you requested",
        "404 error",
        "we can't find that page",
        "sorry, that page",
    )
    if any(m in lower for m in soft_404_markers) or len(body) < 400:
        return "soft404", f"len={len(body)}", None

    return "200", f"len={len(body)}", lower


def looks_real(body_lower: str, gov_name: str) -> bool:
    name_tokens = [
        t
        for t in re.split(r"[^a-z]+", gov_name.lower())
        if t and t not in ("city", "town", "village", "of", "county", "township")
    ]
    name_hit = any(t in body_lower for t in name_tokens) if name_tokens else False
    word_hit = any(w in body_lower for w in MEETING_WORDS)
    return name_hit and word_hit


def load_candidates(limit: int):
    out = []
    with JC_CSV.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                pop = float(row.get("population_estimate") or 0)
            except ValueError:
                pop = 0
            if pop < 5000:
                continue
            domain = (row.get("domain") or "").strip()
            if not domain:
                continue
            if (row.get("suspected_meeting_link_provider") or "").strip():
                continue
            if (row.get("suspected_video_provider") or "").strip():
                continue
            reject = (row.get("reject_reason") or "").strip()
            if reject and reject not in (
                "no-platform-link-found",
                "no-platform-signature",
                "no-meeting-nor-video",
                "no-meetings-found",
            ):
                continue
            out.append(
                {
                    "domain": domain,
                    "gov_id": row.get("gov_id") or "",
                    "city_name": row.get("city_name") or "",
                    "state": row.get("state_or_province") or "",
                    "population": pop,
                }
            )
            if len(out) >= limit:
                break
    return out


def load_done_keys() -> set[tuple[str, str]]:
    if not RAW_OUT.exists():
        return set()
    done = set()
    with RAW_OUT.open(newline="") as f:
        for row in csv.DictReader(f):
            done.add((row["domain"], row["template"]))
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=80, help="number of governments")
    ap.add_argument("--sleep", type=float, default=2.2)
    args = ap.parse_args()

    candidates = load_candidates(args.limit)
    print(f"Loaded {len(candidates)} candidate governments.", file=sys.stderr)

    done_keys = load_done_keys()
    is_new_file = not RAW_OUT.exists()
    fieldnames = [
        "domain",
        "gov_id",
        "city_name",
        "state",
        "template",
        "url",
        "outcome",
        "note",
        "real_hit",
    ]
    with RAW_OUT.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if is_new_file:
            writer.writeheader()

        for cand in candidates:
            domain = cand["domain"]
            host_blocked = False
            for template in TEMPLATES:
                if (domain, template) in done_keys:
                    continue
                if host_blocked:
                    # Never retry past a human-verification gate on the
                    # same host -- one blocked template is enough to
                    # skip the rest of this government's templates.
                    writer.writerow(
                        {
                            "domain": domain,
                            "gov_id": cand["gov_id"],
                            "city_name": cand["city_name"],
                            "state": cand["state"],
                            "template": template,
                            "url": "",
                            "outcome": "skipped-host-blocked",
                            "note": "",
                            "real_hit": "",
                        }
                    )
                    continue
                url = build_url(domain, template)
                if url is None:
                    writer.writerow(
                        {
                            "domain": domain,
                            "gov_id": cand["gov_id"],
                            "city_name": cand["city_name"],
                            "state": cand["state"],
                            "template": template,
                            "url": "",
                            "outcome": "skipped-needs-id",
                            "note": "",
                            "real_hit": "",
                        }
                    )
                    continue
                outcome, note, body_lower = fetch(url)
                if outcome == "blocked":
                    host_blocked = True
                real_hit = ""
                if outcome == "200" and body_lower is not None:
                    real_hit = str(looks_real(body_lower, cand["city_name"]))
                print(
                    f"{domain:40s} {template:30s} -> {outcome:10s} {note} real_hit={real_hit}",
                    file=sys.stderr,
                )
                writer.writerow(
                    {
                        "domain": domain,
                        "gov_id": cand["gov_id"],
                        "city_name": cand["city_name"],
                        "state": cand["state"],
                        "template": template,
                        "url": url,
                        "outcome": outcome,
                        "note": note,
                        "real_hit": real_hit,
                    }
                )
                f.flush()
                time.sleep(args.sleep)


if __name__ == "__main__":
    main()
