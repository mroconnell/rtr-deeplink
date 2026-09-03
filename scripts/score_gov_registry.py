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
  type_disagreements.csv     new gov_type vs gov_classify.py's bucket
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
from archive.utils.gov_classify import classify_government  # noqa: E402
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
    """tenant_host -> the one gov_id every resolved row for that host
    agrees on, for the same-tenant consistency rung (resolver rung 5b).

    A pre-pass, because the resolver is pure and cannot see a page's
    siblings. In Phase 2 this becomes a query against `meeting_pages` by
    host; here it is a group-by over the sheet. Only hosts where EVERY
    keyed row agrees contribute -- a host serving two governments
    (Cottage Grove, uatccta) must produce nothing rather than pick one,
    which is the same decline-rather-than-guess posture as everywhere
    else in the ladder.
    """
    by_host: Dict[str, set] = defaultdict(set)
    for row in rows:
        host = (row.get("tenant_host") or "").strip().lower()
        gov_id = row.get("gov_id") or ""
        if host and gov_id and not gov_id.startswith("rtr:unknown:"):
            by_host[host].add(gov_id)
    return {host: next(iter(ids)) for host, ids in by_host.items() if len(ids) == 1}


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
                "gov_classify_bucket": classify_government(
                    jurisdiction or None, row.get("meeting_body") or None
                ),
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


# `gov_classify.py`'s four buckets against the Census-of-Governments
# vocabulary. Only a genuine disagreement is reported: "agency" is
# gov_classify's catch-all for everything that isn't a county, city or
# school, so it is counted as agreeing with either kind of district.
_BUCKET_EQUIVALENTS = {
    "county": {"county"},
    "city": {"municipality", "township"},
    "school": {"school_district"},
    "agency": {"special_district", "other", "court", "state"},
}


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
    consensus = _tenant_consensus(
        score_rows(archive_inputs) + score_rows(ledger_inputs)
    )
    print(f"  same-tenant consensus available for {len(consensus)} hosts")
    archive_rows = score_rows(archive_inputs, consensus)

    print("\nrtr-discovery ledger:")
    ledger_rows = score_rows(ledger_inputs, consensus)
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

    disagreements = [
        {
            "input_set": r["input_set"],
            "jurisdiction": r["jurisdiction"],
            "meeting_body": r.get("meeting_body", ""),
            "gov_classify_bucket": r["gov_classify_bucket"],
            "gov_type": r["gov_type"],
            "gov_id": r["gov_id"],
            "tenant_host": r["tenant_host"],
        }
        for r in all_rows
        if r["jurisdiction"]
        and r["gov_type"]
        not in _BUCKET_EQUIVALENTS.get(r["gov_classify_bucket"], set())
    ]
    _write(out_dir / "type_disagreements.csv", disagreements)

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

    _seed_governments(all_rows)
    _write_summary(
        out_dir,
        archive_rows,
        ledger_rows,
        all_rows,
        merges,
        splits,
        disagreements,
        canada,
    )
    print(f"\nWrote {out_dir}")


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


def _write_summary(
    out_dir, archive_rows, ledger_rows, all_rows, merges, splits, disagreements, canada
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

    municipal_on_county = [
        r
        for r in all_rows
        if r["municipal_type_word"] == "yes" and r["gov_id"].startswith("us:county:")
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

    lines.append("## Type disagreements with gov_classify.py")
    lines.append("")
    lines.append(
        f"**{len(disagreements)}** rows where the new `gov_type` disagrees with "
        "`archive/utils/gov_classify.py`'s bucket (the classifier driving the "
        "`/state/*` headings today)."
    )
    lines.append("")
    lines.append("| gov_classify bucket | new gov_type | rows |")
    lines.append("| --- | --- | --- |")
    for (bucket, gov_type), n in Counter(
        (d["gov_classify_bucket"], d["gov_type"]) for d in disagreements
    ).most_common(12):
        lines.append(f"| {bucket} | {gov_type} | {n} |")
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
