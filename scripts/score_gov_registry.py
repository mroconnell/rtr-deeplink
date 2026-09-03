"""Score the `gov_id` resolver against real data, before any schema
change. WO-98, architecture doc §6 step 1 -- "the one that proves or
kills the design and costs no migration".

READ-ONLY. Production is touched exactly one way: paged GETs to
`/internal/export/pages`, the same token-gated bulk-read endpoint
rtr-discovery's feed roster uses (WO-93), paced the same way. Nothing is
written to any database, no page is re-resolved, no adapter runs.
rtr-discovery's `ledger.db` is opened `mode=ro`.

Two input sets, per the brief:

  a. every archived page -- current jurisdiction, meeting_body,
     confidence, tenant host and `/j/` slug, against the new gov_id,
     name, type, tier and hub slug;
  b. every distinct (tenant_netloc, resolved jurisdiction) pair among the
     ledger's `resolved_ok`/`ingested` candidates.

Outputs land in `reports/gov_registry_scoring_<date>/`:

  sheet_archive.csv          one row per archived page
  sheet_ledger.csv           one row per ledger pair
  tier_distribution.csv      tiers, per input set
  minted.csv                 every `rtr:` row
  unknown.csv                every `rtr:unknown:` row
  merges.csv                 two or more current `/j/` hubs -> one gov_id
  splits.csv                 one current hub -> several gov_ids
  state_headings.csv         gov_type -> the /state/* heading it lands under
  canada.csv                 Canadian rows, keyed vs not
  SUMMARY.md                 the numbers, for JURISDICTION_METADATA_PLAN.md

Usage:
    python scripts/score_gov_registry.py [--out reports/] [--limit N]
"""

import argparse
import asyncio
import csv
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import certifi

# A fresh Homebrew-Python venv has an empty default SSL trust store, and
# aiohttp builds and caches its default SSLContext as a module-level
# statement -- so this must run BEFORE `import aiohttp`, not merely
# before the first request. See CLAUDE.md's own entry and
# scripts/transcribe_backlog_locally.py's reference example; getting the
# order wrong here silently dropped a full 48-URL batch once.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.utils.gov_registry import registry, resolve_government  # noqa: E402
from archive.utils.gov_groups import GROUP_LABELS, group_for_gov_type  # noqa: E402
from archive.utils.jurisdiction_format import jurisdiction_hub_slug  # noqa: E402

DEFAULT_DISCOVERY = Path.home() / "Documents" / "rtr-discovery"
# The shared checkout's .env, not the worktree's -- CLAUDE.md's own
# worktree note. Only presence is used here; no value is ever printed.
load_dotenv(REPO_ROOT / ".env")
load_dotenv(Path.home() / "Documents" / "rtr-deeplink" / ".env")

PAGE_DELAY_SECONDS = 1.0


async def fetch_export_pages(base_url: str, token: str, limit: int = 500) -> List[dict]:
    """Keyset-paginated metadata sweep, never asking for segments -- the
    light shape, so no `segments` blob is touched (crud.py's own
    contract). ~10 requests for the whole Archive."""
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{base_url.rstrip('/')}/internal/export/pages"
    pages: List[dict] = []
    after_id = 0
    async with aiohttp.ClientSession() as session:
        while True:
            async with session.get(
                url,
                params={"after_id": after_id, "limit": limit},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=180),
            ) as resp:
                if resp.status != 200:
                    raise SystemExit(
                        f"GET {url} -> HTTP {resp.status} (a 404 usually means a bad "
                        "ARCHIVE_INGEST_TOKEN -- the route hides behind it)"
                    )
                body = await resp.json()
            batch = body.get("pages") or []
            pages.extend(batch)
            print(f"  fetched {len(pages)} pages", end="\r", flush=True)
            after_id = body.get("next_after_id")
            if after_id is None:
                break
            await asyncio.sleep(PAGE_DELAY_SECONDS)
    print(f"  fetched {len(pages)} pages      ")
    return pages


def ledger_pairs(discovery_dir: Path) -> List[dict]:
    """Every distinct (tenant_netloc, resolved jurisdiction) among the
    ledger's resolved candidates."""
    path = discovery_dir / "ledger.db"
    if not path.exists():
        print(f"  (skipped, not found: {path})")
        return []
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT tenant_netloc, resolved_json FROM candidates "
            "WHERE status IN ('resolved_ok', 'ingested') AND resolved_json IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    seen = set()
    out = []
    for netloc, blob in rows:
        try:
            payload = json.loads(blob)
        except (TypeError, ValueError):
            continue
        jurisdiction = (payload.get("jurisdiction") or "").strip()
        key = (netloc, jurisdiction)
        if key in seen:
            continue
        seen.add(key)
        out.append({"tenant_host": netloc, "jurisdiction": jurisdiction})
    return out


def _host(url: Optional[str]) -> str:
    if not url:
        return ""
    return (urlparse(url).netloc or "").lower().split(":")[0]


# A raw name that SAYS it is a municipality. Kept here rather than
# imported from the resolver so the report measures the property from the
# outside -- the whole point of the "0 municipal names on the county
# table" check is that it does not just re-assert the resolver's own gate.
_MUNICIPAL_WORD_RE = re.compile(
    r"^(?:the\s+)?(city|town|village|borough|township|municipality)\s+of\b", re.I
)


def has_municipal_type_word(jurisdiction: str) -> bool:
    return bool(_MUNICIPAL_WORD_RE.match((jurisdiction or "").strip()))


def _tenant_consensus(rows: List[dict]) -> Dict[str, str]:
    """tenant_host -> the DOMINANT gov_id among that host's rows that
    resolved through a national table or a pin -- the resolver's rung 5b
    input.

    A pre-pass, because the resolver is pure and cannot see a page's
    siblings. `archive/db/crud._tenant_dominant_gov_id()` is the
    production counterpart, a query against `meeting_pages` by tenant
    host, and the two must agree on what "dominant" means: the most
    common such gov_id, and nothing at all when two are tied.

    Only `registry` and `pinned` rows vote. A minted or inferred id is
    not evidence about a tenant -- it is the resolver's own earlier
    guess, and letting it vote here would be the same
    self-reinforcement `registry.curated_aliases()` refuses for aliases.

    Unlike Phase 1b's version this does NOT require unanimity, because
    it no longer has to carry the whole safety burden on its own: the
    resolver adopts the answer only when the names also agree
    (`resolver._tenant_consistency()`). Requiring unanimity here instead
    would have missed exactly the cases worth collapsing --
    `milwaukee.granicus.com` holds a minted id beside its real one, which
    is the fragmentation, so "every row agrees" is false precisely when
    the rung is needed.
    """
    by_host: Dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        host = (row.get("tenant_host") or "").strip().lower()
        gov_id = row.get("gov_id") or ""
        if not host or not gov_id or gov_id.startswith("rtr:"):
            continue
        if row.get("tier") not in ("registry", "pinned"):
            continue
        by_host[host][gov_id] += 1
    out: Dict[str, str] = {}
    for host, counts in by_host.items():
        ranked = counts.most_common(2)
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            continue
        out[host] = ranked[0][0]
    return out


def score_rows(
    rows: List[dict], consensus: Optional[Dict[str, str]] = None
) -> List[dict]:
    out = []
    for row in rows:
        jurisdiction = row.get("jurisdiction") or ""
        host = row.get("tenant_host") or ""
        match = resolve_government(
            jurisdiction or None,
            tenant_host=host or None,
            tenant_gov_id=(consensus or {}).get(host.lower()),
        )
        out.append(
            {
                **row,
                "gov_id": match.gov_id,
                "gov_name": match.gov_name,
                "gov_type": match.gov_type,
                "tier": match.tier,
                "evidence": match.evidence,
                "new_meeting_body": match.meeting_body or "",
                "new_hub_slug": match.hub_slug or "",
                "country": match.country,
                "state": match.state,
                "old_hub_slug": jurisdiction_hub_slug(jurisdiction) or "",
                "municipal_type_word": (
                    "yes" if has_municipal_type_word(jurisdiction) else "no"
                ),
                "state_heading": GROUP_LABELS[group_for_gov_type(match.gov_type)],
            }
        )
    return out


def _write(path: Path, rows: List[dict], fields: Optional[List[str]] = None) -> None:
    fields = fields or (list(rows[0].keys()) if rows else ["note"])
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  {path.name}: {len(rows)} rows")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "reports")
    parser.add_argument("--discovery", type=Path, default=DEFAULT_DISCOVERY)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument(
        "--archive-cache",
        type=Path,
        default=None,
        help="reuse a previous run's raw export instead of re-fetching",
    )
    parser.add_argument(
        "--save-export",
        type=Path,
        default=None,
        help="write the raw export to this path (for a later --archive-cache)",
    )
    args = parser.parse_args()

    out_dir = args.out / f"gov_registry_scoring_{date.today().isoformat()}"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Archive export:")
    if args.archive_cache and args.archive_cache.exists():
        pages = json.loads(args.archive_cache.read_text())
        print(f"  reused {len(pages)} pages from {args.archive_cache}")
    else:
        base_url = os.environ.get("ARCHIVE_BASE_URL")
        token = os.environ.get("ARCHIVE_INGEST_TOKEN")
        if not base_url or not token:
            raise SystemExit(
                "ARCHIVE_BASE_URL and ARCHIVE_INGEST_TOKEN must be set "
                "(they are in the shared checkout's .env)"
            )
        pages = asyncio.run(fetch_export_pages(base_url, token, args.limit))
        if args.save_export:
            # Deliberately opt-in and never inside the committed report
            # directory: this is ~10 MB of raw production page metadata,
            # and the scored sheet already carries every column the
            # report needs. Useful only to re-run the scoring without a
            # second sweep of production.
            args.save_export.write_text(json.dumps(pages))
            print(f"  saved raw export to {args.save_export}")

    archive_inputs = [
        {
            "page_id": p.get("id"),
            "slug": p.get("slug"),
            "platform": p.get("platform"),
            "source_url": p.get("source_url_normalized"),
            "tenant_host": _host(p.get("source_url_normalized")),
            "jurisdiction": p.get("jurisdiction") or "",
            "meeting_body": p.get("meeting_body") or "",
            "jurisdiction_confidence": p.get("jurisdiction_confidence") or "",
        }
        for p in pages
    ]
    ledger_inputs = ledger_pairs(args.discovery)

    # Two passes. The first resolves every row on its own; the second
    # re-resolves with the same-tenant consensus the first pass revealed,
    # which is the only rung that needs to see a page's siblings.
    #
    # The consensus is computed PER INPUT SET, not over both together.
    # The archive's answer has to depend only on the archive, because
    # that is all `crud._tenant_dominant_gov_id()` and
    # `scripts/backfill_gov_id.py` can see in production -- a scored
    # sheet that quietly consults rtr-discovery's ledger is not modelling
    # what will actually happen. It is not academic: with the ledger
    # mixed in, `kingsport-tn.municodemeetings.com` and six siblings got
    # a dominant government the Archive does not have, went `unresolved`
    # here and `unverified` in the backfill, and the seven hub slugs they
    # retire were left with no 301 because this file never saw them move.
    archive_consensus = _tenant_consensus(score_rows(archive_inputs))
    print(f"  same-tenant consensus available for {len(archive_consensus)} hosts")
    archive_rows = score_rows(archive_inputs, archive_consensus)

    print("\nrtr-discovery ledger:")
    ledger_consensus = _tenant_consensus(score_rows(ledger_inputs))
    ledger_rows = score_rows(ledger_inputs, ledger_consensus)
    print(f"  {len(ledger_rows)} distinct (tenant, jurisdiction) pairs")

    print("\nReports:")
    _write(out_dir / "sheet_archive.csv", archive_rows)
    _write(out_dir / "sheet_ledger.csv", ledger_rows)

    tiers = []
    for label, rows in [("archive", archive_rows), ("ledger", ledger_rows)]:
        counts = Counter(r["tier"] for r in rows)
        for tier, n in counts.most_common():
            tiers.append(
                {
                    "input_set": label,
                    "tier": tier,
                    "rows": n,
                    "pct": f"{100 * n / max(len(rows), 1):.1f}",
                }
            )
    _write(out_dir / "tier_distribution.csv", tiers)

    all_rows = [{**r, "input_set": "archive"} for r in archive_rows] + [
        {**r, "input_set": "ledger"} for r in ledger_rows
    ]

    minted = [r for r in all_rows if r["gov_id"].startswith("rtr:")]
    _write(
        out_dir / "minted.csv",
        sorted(minted, key=lambda r: r["gov_id"]),
        [
            "input_set",
            "gov_id",
            "gov_name",
            "gov_type",
            "tier",
            "jurisdiction",
            "tenant_host",
            "evidence",
        ],
    )
    unresolved = [r for r in all_rows if r["tier"] == "unresolved"]
    _write(
        out_dir / "unresolved.csv",
        sorted(unresolved, key=lambda r: (r["tenant_host"], r["jurisdiction"])),
        [
            "input_set",
            "jurisdiction",
            "gov_name",
            "gov_type",
            "tenant_host",
            "platform",
            "evidence",
        ],
    )
    unknown = [r for r in all_rows if r["gov_id"].startswith("rtr:unknown:")]
    _write(
        out_dir / "unknown.csv",
        unknown,
        ["input_set", "gov_id", "jurisdiction", "tenant_host", "platform", "slug"],
    )

    # MERGE: two or more current `/j/` hubs collapsing into one gov_id.
    # SPLIT: one current hub becoming several gov_ids.
    hubs_by_gov: Dict[str, set] = defaultdict(set)
    govs_by_hub: Dict[str, set] = defaultdict(set)
    names_by_hub: Dict[str, set] = defaultdict(set)
    for r in all_rows:
        # An `unresolved` row has no gov_id at all. It is not a government
        # that hubs merge into -- grouping by the empty string made 220
        # unrelated hubs look like one merge in the first Phase 1b run.
        if not r["old_hub_slug"] or not r["gov_id"]:
            continue
        hubs_by_gov[r["gov_id"]].add(r["old_hub_slug"])
        govs_by_hub[r["old_hub_slug"]].add(r["gov_id"])
        names_by_hub[r["old_hub_slug"]].add(r["jurisdiction"])

    merges = [
        {
            "gov_id": gov_id,
            "gov_name": next(r["gov_name"] for r in all_rows if r["gov_id"] == gov_id),
            "old_hubs": "|".join(sorted(hubs)),
            "hub_count": len(hubs),
        }
        for gov_id, hubs in hubs_by_gov.items()
        if len(hubs) > 1
    ]
    _write(out_dir / "merges.csv", sorted(merges, key=lambda r: -r["hub_count"]))

    splits = [
        {
            "old_hub": hub,
            "gov_ids": "|".join(sorted(govs)),
            "gov_count": len(govs),
            "raw_names": "|".join(sorted(names_by_hub[hub])),
        }
        for hub, govs in govs_by_hub.items()
        if len(govs) > 1
    ]
    _write(out_dir / "splits.csv", sorted(splits, key=lambda r: -r["gov_count"]))

    # What the `/state/*` headings will actually read, per government.
    # This replaced a "disagreements with gov_classify.py" cut once WO-99
    # retired that module: there is no second classifier left to disagree
    # with, and the useful question now is what a reader sees.
    headings = [
        {
            "state_heading": heading,
            "gov_type": gov_type,
            "governments": n,
        }
        for (heading, gov_type), n in sorted(
            Counter(
                (r["state_heading"], r["gov_type"])
                for r in all_rows
                if r["gov_id"] or r["jurisdiction"]
            ).items(),
            key=lambda kv: -kv[1],
        )
    ]
    _write(out_dir / "state_headings.csv", headings)

    canada = [
        {
            "input_set": r["input_set"],
            "jurisdiction": r["jurisdiction"],
            "gov_id": r["gov_id"],
            "keyed": "yes" if r["gov_id"].startswith("ca:") else "no",
            "tenant_host": r["tenant_host"],
        }
        for r in all_rows
        if r["country"] == "ca" or r["gov_id"].startswith("ca:")
    ]
    _write(out_dir / "canada.csv", canada)

    _write_pin_worklist(out_dir, all_rows)
    _seed_governments(all_rows)
    # Archive rows ONLY. A hub is made of pages, and a ledger row is not
    # a page -- it can neither create a hub nor retire one. Including
    # them let a ledger row's `new_hub_slug` mark a slug "still live" and
    # suppress a real 301, which is how 7 junk-named Municode singletons
    # ended up retiring with no redirect after the first backfill.
    _write_hub_slug_aliases(archive_rows)
    _write_summary(
        out_dir,
        archive_rows,
        ledger_rows,
        all_rows,
        merges,
        splits,
        headings,
        canada,
    )
    print(f"\nWrote {out_dir}")


# Platform order for the pin worklist: the four where a landing page
# reliably names its organisation in the header, so a single fetch per
# host settles the pin the way Phase 0's `visual_confirmed` rows were
# made by hand.
_WORKLIST_PLATFORM_ORDER = ["escribe", "cablecast", "swagit", "telvue"]

# TelVue's per-customer identifier is an opaque token in the URL PATH,
# not a subdomain -- `videoplayer.telvue.com/player/{org_token}/...` --
# so every TelVue customer shares one host and a host-level pin is
# meaningless for them. The token is the `match` value.
# See rtr-business/research/telvue_org_tokens.md, which already
# identifies 12 of these by hand.
_TELVUE_TOKEN_RE = re.compile(r"/player/([A-Za-z0-9_\-]{16,})", re.I)


def _telvue_match(source_url: str) -> str:
    m = _TELVUE_TOKEN_RE.search(source_url or "")
    return m.group(1) if m else ""


def _worklist_platform(host: str, platform: str) -> str:
    host = (host or "").lower()
    for name in ("escribemeetings", "cablecast", "swagit", "telvue"):
        if name in host:
            return "escribe" if name == "escribemeetings" else name
    return platform or "unknown"


def _write_pin_worklist(out_dir: Path, all_rows: List[dict]) -> None:
    """One row per tenant host that still has no government, with a
    landing URL to fetch.

    This is the input to the Phase 2 side-task: fetch each landing page
    once and read the organisation name out of its header, exactly how
    `jurisdiction_overrides.csv`'s `visual_confirmed` rows were made.
    Grouped by platform with the four that put their customer's name in
    the page header first, because those are the ones a single fetch
    settles.

    A TelVue row carries the org token from its own source URL as
    `match_value`: every TelVue customer shares
    `videoplayer.telvue.com`, so a host-level pin there would be wrong
    for all of them -- the token is what identifies the government.
    """
    # Tenants that resolved to MORE THAN ONE government. Not a failure --
    # `pwcgov.granicus.com` really is Prince William County plus the City
    # of Manassas Park, and `clerkshq.com` is a shared host serving many
    # -- but each one is either that, or a leftover the consistency rung
    # could not settle, and only a human can tell which. Listed with the
    # ids each carries so the review can do that in one pass.
    multi: Dict[str, set] = defaultdict(set)
    multi_names: Dict[str, set] = defaultdict(set)
    for row in all_rows:
        host = (row.get("tenant_host") or "").strip().lower()
        gov_id = row.get("gov_id") or ""
        if host and gov_id and not gov_id.startswith("rtr:unknown:"):
            multi[host].add(gov_id)
            multi_names[host].add(f"{gov_id} ({row.get('gov_name') or '?'})")

    by_host: Dict[str, dict] = {}
    for host, ids in multi.items():
        if len(ids) < 2:
            continue
        by_host[f"{host}|multi"] = {
            "platform": _worklist_platform(host, ""),
            "tenant_host": host,
            "match_value": "",
            "rows": len(ids),
            "reason": "multiple_governments",
            "stored_names": set(sorted(multi_names[host])),
            "landing_url": "",
            "example_slug": "",
        }

    for row in all_rows:
        if row["tier"] not in ("unresolved", "blank"):
            continue
        host = (row.get("tenant_host") or "").strip().lower()
        if not host:
            continue
        source_url = row.get("source_url") or ""
        platform = _worklist_platform(host, row.get("platform") or "")
        match_value = _telvue_match(source_url) if platform == "telvue" else ""
        key = f"{host}|{match_value}"
        if key in by_host and by_host[key]["reason"] == "multiple_governments":
            key = f"{key}|unresolved"
        entry = by_host.setdefault(
            key,
            {
                "platform": platform,
                "tenant_host": host,
                "match_value": match_value,
                "rows": 0,
                "reason": row["tier"],
                "stored_names": set(),
                "landing_url": "",
                "example_slug": row.get("slug") or "",
            },
        )
        entry["rows"] += 1
        if row.get("jurisdiction"):
            entry["stored_names"].add(row["jurisdiction"])
        if source_url and not entry["landing_url"]:
            entry["landing_url"] = _landing_url(source_url, platform, match_value)

    order = {name: i for i, name in enumerate(_WORKLIST_PLATFORM_ORDER)}
    rows = [
        {
            **e,
            "stored_names": "|".join(sorted(e["stored_names"])),
        }
        for e in by_host.values()
    ]
    rows.sort(
        key=lambda r: (
            # The multi-government hosts first: they are the shortest
            # list and the one where a human decision unblocks the most.
            0 if r["reason"] == "multiple_governments" else 1,
            order.get(r["platform"], len(order)),
            r["platform"],
            -r["rows"],
            r["tenant_host"],
        )
    )
    _write(
        out_dir / "pin_worklist.csv",
        rows,
        [
            "platform",
            "tenant_host",
            "match_value",
            "rows",
            "reason",
            "landing_url",
            "stored_names",
            "example_slug",
        ],
    )


def _landing_url(source_url: str, platform: str, match_value: str) -> str:
    """The page most likely to name the organisation in its header.

    Deliberately conservative: for the platforms whose landing page is a
    known fixed path this returns it, and otherwise it returns the host
    root. Getting this wrong costs one wasted fetch, not a wrong pin.

    eScribe and Cablecast are the host root, not a guessed sub-path --
    corrected 2026-09-03 (WO-103) after `/CablecastPublicSite/` was found
    to 404 on every real Cablecast host checked while root 200s and
    already carries the real government name in `<title>`/`og:site_name`;
    `/Meetings.aspx` 200s but is eScribe's generic meeting-calendar shell,
    matching BACKLOG.md's existing "eScribe landing pages do not name
    their customer" finding. See `scripts/build_pin_worklist.py`'s own
    `landing_url()` docstring for the live-check detail -- this function
    is that one's ancestor and should stay in step with it.
    """
    parsed = urlparse(source_url)
    root = f"{parsed.scheme or 'https'}://{parsed.netloc}"
    if platform == "telvue" and match_value:
        return f"{root}/player/{match_value}"
    return root or source_url


def _seed_governments(all_rows: List[dict]) -> None:
    """§4: `governments.csv` is seeded with every government the scoring
    run resolves. Existing rows win (they may be hand-reviewed); a raw
    string that resolved to a government is recorded as one of its
    aliases, which is what makes "County of Fresno, CA|Fresno County, CA"
    visible as one government's two spellings."""
    existing = dict(registry.governments())
    aliases: Dict[str, set] = defaultdict(set)
    fresh: Dict[str, registry.Government] = {}
    for r in all_rows:
        match = resolve_government(
            r["jurisdiction"] or None, tenant_host=r["tenant_host"] or None
        )
        if not match.government:
            continue
        fresh[match.gov_id] = match.government
        if r["jurisdiction"]:
            aliases[match.gov_id].add(r["jurisdiction"])
    # Every government a PIN names, too -- not only the ones some page
    # resolved to. `tenant_overrides.csv` can name a government no
    # archived page has reached yet (the landing-page sweep writes
    # exactly those), and a pin whose id `governments.csv` cannot render
    # is a broken registry rather than a resolution.
    for rows in registry.tenant_overrides().values():
        for override in rows:
            if override.gov_id in fresh or override.gov_id in existing:
                continue
            derived = registry.government_for_id(override.gov_id)
            if derived:
                fresh[override.gov_id] = derived

    merged = []
    for gov_id, gov in {**fresh, **existing}.items():
        merged.append(
            registry.Government(
                gov_id=gov.gov_id,
                gov_name=gov.gov_name,
                gov_type=gov.gov_type,
                country=gov.country,
                state=gov.state,
                place_geoid=gov.place_geoid,
                county_fips=gov.county_fips,
                sgc_code=gov.sgc_code,
                nces_lea_id=gov.nces_lea_id,
                cog_id=gov.cog_id,
                aliases=tuple(sorted(set(gov.aliases) | aliases.get(gov_id, set()))),
                source=gov.source or "scored",
                evidence=gov.evidence,
            )
        )
    registry.write_governments(merged)
    print(f"  governments.csv: {len(merged)} rows")


def _write_hub_slug_aliases(all_rows: List[dict]) -> int:
    """Write `archive/data/hub_slug_aliases.csv` -- every `/j/` slug that
    stops being a hub, and where it goes.

    This has to be generated HERE, and only here, because the set of old
    slugs is knowable exactly once: it is `jurisdiction_hub_slug()` over
    the stored `jurisdiction` values as they are *before* the backfill
    rewrites them to registry display names. After the backfill the old
    spelling is gone from the database and nothing could reconstruct it.
    See archive/utils/hub_aliases.py for why the map is a committed file
    rather than a table.

    Only a slug that no longer belongs to ANY live hub is written -- a
    slug that survives as some other government's hub must never redirect,
    which is what would happen if the raw before/after pairs were dumped
    unfiltered.
    """
    # A row with no `gov_id` is `unresolved` or `blank`: it has no
    # government, so it has no hub, and `_hub_identity()` will keep
    # filing its page under the OLD display slug. 82 such aliases were
    # written before this guard and every one pointed at a hub that would
    # 404 -- `/j/cottage-grove` -> `/j/city-of-cottage-grove`, a redirect
    # to nothing, which is strictly worse than the 404 it replaced.
    live = {r["new_hub_slug"] for r in all_rows if r["new_hub_slug"] and r["gov_id"]}
    rows: Dict[str, dict] = {}
    for r in all_rows:
        old, new = r["old_hub_slug"], r["new_hub_slug"]
        if not r["gov_id"] or not old or not new or old == new or old in live:
            continue
        rows.setdefault(
            old,
            {
                "old_slug": old,
                "gov_id": r["gov_id"],
                "new_slug": new,
                "evidence": (
                    f"{r['jurisdiction']!r} now resolves to {r['gov_id']} "
                    f"({r['gov_name']})"
                ),
            },
        )
    path = REPO_ROOT / "archive" / "data" / "hub_slug_aliases.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["old_slug", "gov_id", "new_slug", "evidence"]
        )
        writer.writeheader()
        for row in sorted(rows.values(), key=lambda r: r["old_slug"]):
            writer.writerow(row)
    print(f"  archive/data/hub_slug_aliases.csv: {len(rows)} retired slugs")
    return len(rows)


def _write_summary(
    out_dir, archive_rows, ledger_rows, all_rows, merges, splits, headings, canada
) -> None:
    def pct(n, d):
        return f"{100 * n / max(d, 1):.1f}%"

    lines = [f"# Phase 1 — gov_id registry scoring ({date.today().isoformat()})", ""]
    lines.append(
        f"Inputs: **{len(archive_rows)}** archived pages "
        f"(`GET /internal/export/pages`, metadata only) and **{len(ledger_rows)}** "
        "distinct (tenant, jurisdiction) pairs from rtr-discovery's ledger. "
        "Read-only; no schema change, no production write."
    )
    lines.append("")
    lines.append("## Tier distribution")
    lines.append("")
    lines.append("| tier | archive pages | ledger pairs |")
    lines.append("| --- | --- | --- |")
    a = Counter(r["tier"] for r in archive_rows)
    b = Counter(r["tier"] for r in ledger_rows)
    for tier in ("pinned", "registry", "inferred", "unverified", "unresolved", "blank"):
        lines.append(
            f"| {tier} | {a[tier]} ({pct(a[tier], len(archive_rows))}) "
            f"| {b[tier]} ({pct(b[tier], len(ledger_rows))}) |"
        )
    lines.append("")

    # A national id means a real Census/StatCan code. An `unresolved` row
    # has an EMPTY gov_id, which this test used to count as "not rtr:"
    # and therefore as keyed -- it inflated the headline by 422 rows in
    # the first Phase 1b run.
    keyed = [r for r in all_rows if r["gov_id"] and not r["gov_id"].startswith("rtr:")]
    lines.append(
        f"**{len(keyed)} of {len(all_rows)}** rows ({pct(len(keyed), len(all_rows))}) "
        "got a national id."
    )
    lines.append("")

    # A hand-verified `authoritative` pin is deliberately exempt: it is
    # the one tier allowed to override a classified name, and the only
    # rows it exempts today are the two consolidated city-counties on
    # `honolulu.granicus.com`, where "City of Honolulu" landing on
    # `us:county:15003` is the CORRECT answer -- Hawaii has no separate
    # municipal government there. Counting those as failures would ask
    # the resolver to un-learn a fact a human established.
    municipal_on_county = [
        r
        for r in all_rows
        if r["municipal_type_word"] == "yes"
        and r["gov_id"].startswith("us:county:")
        and r["tier"] != "pinned"
    ]
    xx_ids = [r for r in all_rows if ":xx:" in r["gov_id"]]
    auto_only_pins = [
        host
        for host, rows in registry.tenant_overrides().items()
        for o in rows
        if o.source == "auto_derived"
    ]
    lines.append("## Phase 1b targets — before / after")
    lines.append("")
    lines.append("| check | Phase 1 | now | target |")
    lines.append("| --- | --- | --- | --- |")
    lines.append(
        f"| rows on the county table whose raw name had a municipal type word "
        f"| 26 | **{len(municipal_on_county)}** | 0 |"
    )
    lines.append(f"| `rtr:us:xx:` / `rtr:ca:xx:` ids | 624 | **{len(xx_ids)}** | 0 |")
    lines.append(
        f"| pins sourced only from `auto_derived` | 447 | **{len(auto_only_pins)}** | 0 |"
    )
    lines.append("")
    if municipal_on_county:
        for r in municipal_on_county[:10]:
            lines.append(f"- still on a county: {r['jurisdiction']!r} -> {r['gov_id']}")
        lines.append("")
    if xx_ids:
        for r in xx_ids[:10]:
            lines.append(
                f"- still unknown-state: {r['jurisdiction']!r} -> {r['gov_id']}"
            )
        lines.append("")

    gated = [
        r
        for r in all_rows
        if r["tier"] == "unresolved" and "not a government name" in r["evidence"]
    ]
    lines.append("## The minting gate")
    lines.append("")
    lines.append(
        f"**{len(gated)}** rows carry a string that is not a government name -- "
        "a subdomain fragment, an initialism or a station callsign -- and are "
        "tier `unresolved` with the raw text kept in `evidence`, rather than "
        "minting an `rtr:` id nobody could ever look up."
    )
    lines.append("")
    lines.append("| platform | rows | distinct hosts |")
    lines.append("| --- | --- | --- |")
    by_platform = defaultdict(list)
    for r in gated:
        by_platform[r.get("platform") or "(ledger)"].append(r)
    for platform, rows in sorted(by_platform.items(), key=lambda kv: -len(kv[1])):
        hosts = len({r["tenant_host"] for r in rows})
        lines.append(f"| {platform} | {len(rows)} | {hosts} |")
    lines.append("")
    lines.append("| country | rows |")
    lines.append("| --- | --- |")
    for country, n in Counter(r["country"] for r in gated).most_common():
        lines.append(f"| {country} | {n} |")
    lines.append("")
    if gated:
        lines.append(
            "Examples: "
            + ", ".join(
                sorted({repr(r["jurisdiction"]) for r in gated if r["jurisdiction"]})[
                    :12
                ]
            )
        )
        lines.append("")

    lines.append("## Pin worklist")
    lines.append("")
    worklist = [r for r in all_rows if r["tier"] in ("unresolved", "blank")]
    worklist_hosts = {r["tenant_host"] for r in worklist if r["tenant_host"]}
    lines.append(
        f"`pin_worklist.csv` -- **{len(worklist_hosts)}** tenant hosts with no "
        f"government across {len(worklist)} rows, each with a landing URL to "
        "fetch once and read the organisation name out of the header, the way "
        "`jurisdiction_overrides.csv`'s `visual_confirmed` rows were made. "
        "Ordered eScribe / Cablecast / Swagit / TelVue first -- the four whose "
        "landing page reliably names its customer. TelVue rows carry the org "
        "token from the URL path as `match_value`, because every TelVue "
        "customer shares one host and a host-level pin would be wrong for all "
        "of them."
    )
    lines.append("")

    lines.append("## Government types")
    lines.append("")
    lines.append("| gov_type | rows |")
    lines.append("| --- | --- |")
    for gov_type, n in Counter(r["gov_type"] for r in all_rows).most_common():
        lines.append(f"| {gov_type} | {n} |")
    lines.append("")

    lines.append("## Merges and splits")
    lines.append("")
    lines.append(
        f"- **{len(merges)} merges** — two or more current `/j/` hubs collapsing "
        f"into one `gov_id` ({sum(m['hub_count'] for m in merges)} hubs in total)."
    )
    lines.append(
        f"- **{len(splits)} splits** — one current hub becoming several `gov_id`s."
    )
    lines.append("")
    if merges:
        lines.append("Largest merges:")
        lines.append("")
        for m in sorted(merges, key=lambda r: -r["hub_count"])[:15]:
            lines.append(f"- `{m['gov_id']}` — {m['gov_name']} ← {m['old_hubs']}")
        lines.append("")
    if splits:
        lines.append("Splits:")
        lines.append("")
        for s in sorted(splits, key=lambda r: -r["gov_count"])[:15]:
            lines.append(f"- `/j/{s['old_hub']}` → {s['gov_ids']}")
        lines.append("")

    lines.append("## What the /state/* headings will read")
    lines.append("")
    lines.append(
        "From `gov_type` via `archive/utils/gov_groups.py`, which replaced "
        "`archive/utils/gov_classify.py`'s regex over the display name "
        "(WO-99). Every row is a page, not a distinct government."
    )
    lines.append("")
    lines.append("| heading | gov_type | rows |")
    lines.append("| --- | --- | --- |")
    for h in headings[:12]:
        lines.append(f"| {h['state_heading']} | {h['gov_type']} | {h['governments']} |")
    lines.append("")

    ca_keyed = [r for r in canada if r["keyed"] == "yes"]
    lines.append("## Canada")
    lines.append("")
    lines.append(
        f"**{len(ca_keyed)} of {len(canada)}** Canadian rows "
        f"({pct(len(ca_keyed), len(canada))}) got a StatCan id "
        "(`ca:csd` / `ca:cd` / `ca:pr`); the rest mint `rtr:ca:`."
    )
    lines.append("")

    minted = [r for r in all_rows if r["gov_id"].startswith("rtr:")]
    unresolved = [r for r in all_rows if r["tier"] == "unresolved"]
    _write(
        out_dir / "unresolved.csv",
        sorted(unresolved, key=lambda r: (r["tenant_host"], r["jurisdiction"])),
        [
            "input_set",
            "jurisdiction",
            "gov_name",
            "gov_type",
            "tenant_host",
            "platform",
            "evidence",
        ],
    )
    unknown = [r for r in all_rows if r["gov_id"].startswith("rtr:unknown:")]
    lines.append("## Minted and unknown")
    lines.append("")
    lines.append(
        f"- **{len({r['gov_id'] for r in minted})}** distinct minted `rtr:` "
        f"governments over {len(minted)} rows."
    )
    lines.append(
        f"- **{len(unknown)}** rows with nothing at all (`rtr:unknown:<host>`)."
    )
    lines.append(
        f"- **{len(unresolved)}** rows tier `unresolved` — a real government "
        "name with no state and nothing to key it by. Listed in "
        "`unresolved.csv` for a `tenant_overrides.csv` pin; deliberately "
        "NOT minted, because an id nobody can key looks resolved and is not."
    )
    inferred = [r for r in all_rows if r["tier"] == "inferred"]
    lines.append(
        f"- **{len(inferred)}** rows resolved by same-tenant consistency "
        "(tier `inferred`)."
    )
    lines.append("")
    (out_dir / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("  SUMMARY.md")


if __name__ == "__main__":
    main()
