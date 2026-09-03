"""Fetch each unpinned tenant's landing page once, read the organisation
name out of it, and write a `tenant_overrides.csv` pin when that name
resolves to a registry government.

WO-99 step 8, and the same method that produced
`jurisdiction_overrides.csv`'s `visual_confirmed` rows by hand: the
platforms in `pin_worklist.csv` put their customer's name in the page
header, title or footer ("The Corporation of the Town of
Niagara-on-the-Lake"), and one fetch settles a host the resolver could
not key from its stored strings alone. The eScribe block is the
highest-yield -- `pub-cambridge`, `pub-london`, `pub-halifax`,
`pub-hamilton` are real Canadian governments that are `unresolved` only
because no province could be recovered.

READ-ONLY against every government site: one GET per host, no crawl, no
form, paced the way the bulk ingests are. It writes to exactly two
places, both local: `tenant_overrides.csv` and its own report. It never
touches the Archive, the ledger, or `CLAUDE_INBOX_TRIAGE_SEEN.txt`.

**YouTube hosts are skipped and not counted as failures.** Every YouTube
row shares `www.youtube.com`/`youtu.be`, so the host is not the tenant --
the channel id in `match` is -- and a landing page for the shared host
would name Google, not a government. Those rows want a different method
(the channel page, per channel), which is separate work.

Usage:
    python scripts/sweep_tenant_landing_pages.py --limit 20   # a taste
    python scripts/sweep_tenant_landing_pages.py --apply      # write pins
"""

import argparse
import asyncio
import csv
import os
import re
import sys
from collections import Counter
from html import unescape
from pathlib import Path
from typing import List, Optional, Tuple

import certifi

# A fresh Homebrew-Python venv has an empty default SSL trust store, and
# aiohttp builds and caches its default SSLContext as a MODULE-LEVEL
# statement -- so this must run before `import aiohttp`, not merely
# before the first request. CLAUDE.md's own entry, and the ordering that
# silently dropped a 48-URL batch once.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.utils.gov_registry import registry, resolve_government  # noqa: E402

WORKLIST = (
    REPO_ROOT / "reports" / "gov_registry_scoring_2026-09-02" / "pin_worklist.csv"
)
OVERRIDES = registry.DATA_DIR / registry.TENANT_OVERRIDES_FILE

# Same politeness the bulk ingests use: a real browser UA so a naive
# hotlink check does not false-positive us, and a delay between hosts.
# One request per host, so this is gentler than any ingest run.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
DELAY_SECONDS = 1.5
TIMEOUT = aiohttp.ClientTimeout(total=25)

# Hosts whose landing page names Google rather than a government.
SKIP_PLATFORMS = {"youtube"}

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.I | re.S)
_OG_SITE_RE = re.compile(
    r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)', re.I
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# Boilerplate every one of these platforms puts in its own title, which
# is the vendor's name and not the customer's. Stripped from ANYWHERE in
# a candidate, not just matched whole: Granicus titles its view page
# "New Smyrna Beach FL View Page - Granicus Content", where the customer
# and the vendor share one string.
_VENDOR_NOISE_RE = re.compile(
    r"\b(escribe|iCompass|granicus content|granicus|swagit ?admin|swagit|"
    r"cablecast|telvue|civicclerk|civicweb|civicplus|primegov|iqm2|municode|"
    r"view page|public site|media site|meeting portal|meeting hub|"
    r"agenda center|video on demand|vod|live stream|streaming|webcast|"
    r"listing videos|upcoming meetings|past meetings|"
    r"meetings?|agendas?|minutes|calendar|portal|home ?page|welcome to)\b",
    re.I,
)
_SEPARATORS = re.compile(r"\s+[|–—·-]\s+")

# "The Corporation of the Town of Niagara-on-the-Lake" -> "Town of
# Niagara-on-the-Lake". A real Ontario legal-name prefix, and one the
# registry never writes.
_CORPORATION_RE = re.compile(
    r"^(?:the\s+)?(?:corporation|municipal corporation)\s+of\s+(?:the\s+)?", re.I
)


def _clean(text: str) -> str:
    return _WS_RE.sub(" ", unescape(_TAG_RE.sub(" ", text or ""))).strip(" |-–—·\t\n")


def _strip_vendor_words(part: str) -> str:
    """Remove the vendor's own words from a candidate, leaving whatever
    the customer contributed. "New Smyrna Beach FL View Page - Granicus
    Content" -> "New Smyrna Beach FL"."""
    return _clean(_VENDOR_NOISE_RE.sub(" ", part))


# Per-platform landing URLs, in the order they are tried. The worklist's
# single `landing_url` is used for anything not listed.
#
# MEASURED, not assumed -- and the worklist's own ordering note ("the
# four whose landing page reliably names its customer") turns out to be
# only half right, which is why this table exists:
#
#   cablecast   root names it, in <title> AND og:site_name ("Huron
#               Charter Township"). The best of the four.
#   granicus    the root serves nothing; ViewPublisher.php DOES --
#               "New Smyrna Beach FL View Page - Granicus Content". The
#               view id varies per customer, so a couple are tried.
#   escribe     names it NOWHERE. Meetings.aspx is titled "Meetings" and
#               the only place a customer name could be is a logo whose
#               alt text is the literal string "Organization Logo".
#   swagit      root is titled "SwagitAdmin"; /videos 404s.
#   civicclerk  root is "Public Portal • CivicClerk"; the org name only
#               exists behind its API.
#
# So this sweep's real yield is cablecast and granicus, and saying so is
# more useful than sweeping 41 eScribe hosts that cannot answer.
_PLATFORM_PATHS = {
    "granicus": (
        "/ViewPublisher.php?view_id=1",
        "/ViewPublisher.php?view_id=2",
        "/ViewPublisher.php?view_id=3",
    ),
}


def candidate_names(html: str) -> List[str]:
    """Every plausible organisation name on a landing page, best first.

    `og:site_name` before `<h1>` before `<title>`: the first is an
    explicit statement of whose site this is, the second is usually the
    masthead, and the third is the one most likely to be padded with the
    vendor's own words. Each is also split on the common separators, so
    "Town of Lincoln | eSCRIBE Meetings" yields the half that is a
    government.
    """
    out: List[str] = []
    for pattern in (_OG_SITE_RE, _H1_RE, _TITLE_RE):
        for raw in pattern.findall(html or ""):
            whole = _clean(raw)
            for part in [whole] + _SEPARATORS.split(whole):
                part = _CORPORATION_RE.sub("", _strip_vendor_words(part)).strip()
                if not part or len(part) < 3 or len(part) > 90:
                    continue
                if _VENDOR_NOISE_RE.fullmatch(part):
                    continue
                if part not in out:
                    out.append(part)
    return out


async def fetch(session, url: str) -> Optional[str]:
    try:
        async with session.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, ssl=False
        ) as resp:
            if resp.status != 200:
                return None
            return await resp.text(errors="replace")
    except (aiohttp.ClientError, asyncio.TimeoutError, UnicodeDecodeError, OSError):
        return None


def best_match(names: List[str], host: str) -> Tuple[Optional[str], str, str]:
    """(gov_id, the name that resolved, evidence) for the first candidate
    that reaches a REGISTRY government.

    A minted `rtr:` id is deliberately not accepted: the point of a pin
    is to say which known government a tenant belongs to, and minting one
    from a page title would invent an identity out of a masthead. A host
    with no national match stays on the worklist with what was found.
    """
    for name in names:
        match = resolve_government(name, tenant_host=host)
        if match.gov_id and not match.gov_id.startswith("rtr:"):
            return match.gov_id, name, match.evidence
    return None, "", ""


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Append the pins to tenant_overrides.csv (default: report only)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=REPO_ROOT / "reports" / "landing_page_sweep.csv",
    )
    args = parser.parse_args()

    with open(WORKLIST, encoding="utf-8") as fh:
        worklist = list(csv.DictReader(fh))

    already = set(registry.tenant_overrides())
    hosts: List[dict] = []
    seen = set()
    for row in worklist:
        host = (row["tenant_host"] or "").strip().lower()
        if not host or host in seen:
            continue
        if row["platform"] in SKIP_PLATFORMS or host in already:
            continue
        seen.add(host)
        hosts.append(row)
    if args.limit:
        hosts = hosts[: args.limit]

    print(f"{len(hosts)} hosts to sweep (YouTube and already-pinned hosts skipped)")

    results = []
    async with aiohttp.ClientSession() as session:
        for i, row in enumerate(hosts, 1):
            host = row["tenant_host"].strip().lower()
            paths = _PLATFORM_PATHS.get(row["platform"])
            urls = (
                [f"https://{host}{p}" for p in paths]
                if paths
                else [row["landing_url"] or f"https://{host}/"]
            )
            html = None
            url = urls[0]
            names: List[str] = []
            gov_id = name = evidence = ""
            for candidate_url in urls:
                page = await fetch(session, candidate_url)
                if page is None:
                    await asyncio.sleep(DELAY_SECONDS)
                    continue
                html, url = page, candidate_url
                names = candidate_names(page)
                gov_id, name, evidence = best_match(names, host)
                if gov_id:
                    break
                await asyncio.sleep(DELAY_SECONDS)
            results.append(
                {
                    "platform": row["platform"],
                    "tenant_host": host,
                    "landing_url": url,
                    "fetched": "yes" if html else "no",
                    "extracted": " | ".join(names[:4]),
                    "gov_id": gov_id or "",
                    "resolved_from": name,
                    "evidence": evidence,
                    "stored_names": row.get("stored_names", ""),
                }
            )
            flag = gov_id or ("no name" if html else "unreachable")
            print(f"  [{i}/{len(hosts)}] {host:52} {flag}")
            await asyncio.sleep(DELAY_SECONDS)

    _write_report(results, args.report)
    pins = [r for r in results if r["gov_id"]]
    if args.apply and pins:
        _append_pins(pins)
        print(f"\nwrote {len(pins)} pins to {OVERRIDES}")

    print("")
    print(f"hosts swept          : {len(results)}")
    print(f"landing page fetched : {sum(1 for r in results if r['fetched'] == 'yes')}")
    print(f"pins found           : {len(pins)}")
    print("still unresolved by platform:")
    for platform, n in Counter(
        r["platform"] for r in results if not r["gov_id"]
    ).most_common():
        print(f"  {platform:16} {n}")


def _write_report(results: List[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=list(results[0].keys()) if results else []
        )
        if results:
            writer.writeheader()
            writer.writerows(results)
    print(f"\nreport: {path}")


def _append_pins(pins: List[dict]) -> None:
    """Append to `tenant_overrides.csv`, `source=landing_page`, with the
    quoted text as the evidence.

    `strength=authoritative`: the government's own site saying who it is
    is the strongest evidence this scheme has, and stronger than the
    extraction it overrides -- which is the whole reason these hosts are
    unresolved.
    """
    with open(OVERRIDES, "a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        for pin in pins:
            writer.writerow(
                [
                    pin["tenant_host"],
                    "",
                    pin["gov_id"],
                    "authoritative",
                    "landing_page",
                    f'landing page {pin["landing_url"]} reads "{pin["resolved_from"]}"',
                ]
            )


if __name__ == "__main__":
    asyncio.run(main())
