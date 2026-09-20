"""WO-912/WO-913 (2026-09-20): send the HAND-CONFIRMED non-YouTube finds
through `scripts/wo134_confirmed_hits_ingest.py`'s pipeline, unchanged.

WO-912 (headless pilot) and WO-913 (AgendaCenter hop sweep) are measurements:
their reports say where a platform link was found, never whether it is the
right government. A person then read every "found" row (see each WO's
`*_handcheck.csv` in `~/Documents/rtr-business/research/`) and marked the
ones that are the government's own meeting video on a single-tenant platform
(`action=ingest`). Those -- and only those -- go through WO-134's resolve/
ingest path, with every guard it already has: a fresh-inventory dedupe, the
title-safety gate, WO-144's probe, tier-3 queueing for video without
captions, shared-host pins, and the consecutive-error circuit breaker. This
file adds nothing to that logic; it only (1) builds WO-134's input CSV from
the hand-check files and (2) points WO-134's input/log paths at this WO's own
files so the run does not mix into WO-134's own resumable log.

YouTube finds never come through here: YouTube is fetched only by the drip
Mac (CLAUDE.md), so those are appended to `youtube_channel_leads.csv` for its
hand-read lane instead (`scripts/wo912_wo913_make_leads.py`). That rule also
covers the INDIRECT routes, which this run hit once (WO-913, Toledo OR: a
CivicClerk event whose media was a YouTube embed made WO-134's resolve and
WO-144 probe call YouTube from this Mac). So `main()` installs
`scripts/youtube_fetch_guard.py` before anything is resolved: any YouTube
hostname lookup, from any library, raises instead. A row that needed YouTube
fails as an ordinary error, and is written to `wo912_wo913_youtube_refused.csv`
(gov_id, the seed URL, the hosts refused) so it can become a lead for the drip
lane instead of being lost.

Identity: this path sends each row's `gov_id` in the ingest payload (WO-222),
and the Archive treats a caller-supplied id as a PIN -- it only checks that the
id exists in the registry (`archive/db/crud.py` `_caller_pinned_match()`), not
that the source really is that government. So a row whose recorded domain is
some other government's would be filed under the wrong one. WO-134 has an
optional guard for exactly this and most sweeps install it (wo218, wo223, ...);
this run left it off on its first batch, relying on the hand-check alone. It is
installed now: WO-149's `jurisdiction_check_hook()` rejects a hit whose
adapter-guessed state disagrees with the row's registry government (a De Kalb,
TX row whose site is De Kalb, IL's) and pins the jurisdiction to the row's own
name.

WO-134 reads the platform link from `hit_source_urls`; when that value is
already a URL of the named platform (`detect_platform(url) == platform`) it
uses it directly (`locate_platform_url()`), which is how a find that already
IS the platform URL is passed in. For CivicClerk, the tenant root is added
as a second hit so WO-134's depth search can look past the one event the
sweep happened to find if that event has no video.

Usage (from the repo root; needs the real ARCHIVE_BASE_URL/ARCHIVE_INGEST_TOKEN
from `.env`, and a fresh inventory export -- both are WO-134's own
requirements, see its docstring):
    python scripts/export_meeting_inventory.py --out-dir /tmp/wo913_inventory --source export
    python scripts/wo912_wo913_ingest_confirmed.py --build-only          # write the input, stop
    python scripts/wo912_wo913_ingest_confirmed.py --limit 1 --inventory-csv /tmp/wo913_inventory/meeting_inventory.csv
    python scripts/wo912_wo913_ingest_confirmed.py --inventory-csv /tmp/wo913_inventory/meeting_inventory.csv
"""

from __future__ import annotations

import asyncio
import csv
import sys
from pathlib import Path
from urllib.parse import urlparse

csv.field_size_limit(sys.maxsize)

# Run as `python scripts/...`, sys.path[0] is scripts/, not the repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
HANDCHECKS = [
    (RESEARCH_DIR / "wo912_handcheck.csv", "wo912"),
    (RESEARCH_DIR / "wo913_handcheck.csv", "wo913"),
]
REPORTS = {
    "wo912": RESEARCH_DIR / "wo912_report.csv",
    "wo913": RESEARCH_DIR / "wo913_report.csv",
}
INPUT_CSV = RESEARCH_DIR / "wo912_wo913_confirmed_hits.csv"
LOG_CSV = RESEARCH_DIR / "wo912_wo913_ingest_log.csv"
REFUSED_CSV = RESEARCH_DIR / "wo912_wo913_youtube_refused.csv"
REFUSED_FIELDS = [
    "gov_id",
    "unit_name",
    "platform_hits",
    "hit_source_urls",
    "hosts_refused",
]

# Same columns `wo134_confirmed_hits_ingest.py` reads (see wo139_confirmed_hits.csv).
INPUT_FIELDS = [
    "gov_id",
    "unit_name",
    "population",
    "homepage",
    "homepage_status",
    "hop2_pages_checked",
    "hop2_urls",
    "platform_hits",
    "hit_source_urls",
    "detail",
]


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if None not in r.values()]


def civicclerk_tenant_root(url: str) -> str:
    """`https://<tenant>.portal.civicclerk.com` for any URL on that tenant,
    or "" when the URL is not a CivicClerk portal."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.endswith(".portal.civicclerk.com"):
        return f"{parsed.scheme or 'https'}://{host}"
    return ""


def hit_source_urls_for(platform: str, hit_url: str) -> str:
    pairs = [f"{platform}={hit_url}"]
    root = civicclerk_tenant_root(hit_url) if platform == "civicclerk" else ""
    if root and root.rstrip("/") != hit_url.rstrip("/"):
        pairs.append(f"civicclerk={root}")
    return ";".join(pairs)


def build_input() -> list[dict]:
    """One WO-134 input row per hand-confirmed `action=ingest` government,
    across both WOs' hand-check files (a government is listed once)."""
    out: list[dict] = []
    seen: set[str] = set()
    for handcheck, wo in HANDCHECKS:
        reports = {r["gov_id"]: r for r in _rows(REPORTS[wo])}
        for hc in _rows(handcheck):
            gid = hc["gov_id"]
            if hc["action"] != "ingest" or gid in seen:
                continue
            if hc["platform"].lower() == "youtube":
                # Never through this path, whatever the action says.
                continue
            seen.add(gid)
            rep = reports.get(gid, {})
            domain = (rep.get("domain") or "").strip()
            homepage = domain if "://" in domain or not domain else f"https://{domain}"
            out.append(
                {
                    "gov_id": gid,
                    "unit_name": hc["name"],
                    "population": rep.get("population", ""),
                    "homepage": homepage,
                    "homepage_status": "200",
                    "hop2_pages_checked": "0",
                    "hop2_urls": "",
                    "platform_hits": hc["platform"],
                    "hit_source_urls": hit_source_urls_for(
                        hc["platform"], hc["hit_url"]
                    ),
                    "detail": f"{wo}-hand-confirmed",
                }
            )
    return out


def write_input(rows: list[dict]) -> None:
    with INPUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=INPUT_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def record_refused(row: dict, hosts: list[str]) -> None:
    """Append one row that needed YouTube (so it can become a drip-lane lead)."""
    is_new = not REFUSED_CSV.exists()
    with REFUSED_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REFUSED_FIELDS, lineterminator="\n")
        if is_new:
            w.writeheader()
        w.writerow(
            {
                "gov_id": row["gov_id"],
                "unit_name": row["unit_name"],
                "platform_hits": row.get("platform_hits", ""),
                "hit_source_urls": row.get("hit_source_urls", ""),
                "hosts_refused": ";".join(hosts),
            }
        )


def configure(w134, jurisdiction_check_hook, refused: list[str]) -> None:
    """Point WO-134 at this WO's own files and put both guards in place.
    Takes the ingest module and the hook as arguments (rather than importing
    them) so a test can prove the wiring without running a real ingest."""
    real_process_row = w134.process_row

    async def tracked_process_row(session, row, covered_gov_ids, source_tag):
        before = len(refused)
        try:
            return await real_process_row(session, row, covered_gov_ids, source_tag)
        finally:
            if len(refused) > before:
                hosts = sorted(set(refused[before:]))
                print(f"YOUTUBE-REFUSED {row['gov_id']} {row['unit_name']}: {hosts}")
                record_refused(row, hosts)

    w134.JURISDICTION_CHECK_HOOK = jurisdiction_check_hook
    w134.process_row = tracked_process_row
    w134.INPUT_CSVS = [INPUT_CSV]
    w134.LOG_CSV = LOG_CSV


def main() -> None:
    build_only = "--build-only" in sys.argv
    if build_only:
        sys.argv.remove("--build-only")
    rows = build_input()
    write_input(rows)
    print(f"Wrote {len(rows)} hand-confirmed row(s) to {INPUT_CSV}")
    for r in rows:
        print(f"  {r['gov_id']}  {r['unit_name']}  {r['hit_source_urls'][:110]}")
    if build_only or not rows:
        return

    # BEFORE anything is resolved, probed or ingested: see the docstring.
    from scripts.youtube_fetch_guard import REFUSED, install

    install()

    # Imported late: they load .env and pull in the resolver, which a plain
    # --build-only run does not need. Importing wo149 also installs its hook
    # on w134; `configure()` sets it explicitly too.
    import scripts.wo134_confirmed_hits_ingest as w134
    import scripts.wo149_county_ladder_sweep as wo149

    configure(w134, wo149.jurisdiction_check_hook, REFUSED)
    asyncio.run(w134.main())


if __name__ == "__main__":
    main()
