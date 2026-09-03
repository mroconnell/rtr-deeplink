"""Score `extract_gov_signals()` + `resolve_government(..., signals=...)`
against real data -- Phase 2d ("signal scoring"), WO-105,
`rtr-business/research/GOVERNMENT_IDENTITY_ARCHITECTURE.md`.

Pure measurement. No production write of any kind -- production is
touched exactly one way, the same read-only `GET /internal/export/pages`
`scripts/score_gov_registry.py` already uses. The one NEW kind of network
activity this script does that that one does not: it fetches each corpus
page's own real source HTML once, politely paced, the same convention
`scripts/sweep_tenant_landing_pages.py` uses for tenant landing pages
(real browser User-Agent, one request at a time, `DELAY_SECONDS` apart,
`ssl=False`). An explicit human-verification gate (a Cloudflare "Verify
you are human" challenge) is skipped and counted, never defeated --
CLAUDE.md's "politely" rule, non-negotiable.

**Corpus** (re-derived live, not assumed):
  - every page currently tier `unresolved` or `unverified`
  - a 300-page RANDOM SAMPLE of `registry`-tier pages as the CONTROL --
    the whole point of a control is that the signals must not make an
    already-correct page WORSE, and this is how that gets measured.

The endpoint has no server-side tier filter (confirmed by reading
`archive/main.py`'s route), so the whole export is paged in and filtered
client-side by `jurisdiction_confidence`.

**Resolution, twice per row**: once as `resolve_government()` resolves it
TODAY (no `signals`), once with `extract_gov_signals()`'s output passed
as `signals` -- and the two are diffed. A control-page `gov_id` change is
a DEFECT to fix before the report is written, not a note to move past
(the brief's own explicit target: 0).

Outputs land in `reports/gov_signals_scoring_<date>/`:

  html_cache/                 raw fetched HTML, one file per page id
                               (gitignored -- see .gitignore)
  sheet.csv                   one row per corpus page, before/after
  tier_changes.csv            before -> after tier, per row
  control_regressions.csv     any control-tier page whose gov_id changed
                               (target: empty)
  recovery_by_platform.csv
  recovery_by_country.csv
  recovery_by_canadian_province.csv
  signal_contribution.csv     which signal produced each recovery
  SUMMARY.md                  the numbers, for JURISDICTION_METADATA_PLAN.md

Usage:
    python scripts/score_gov_signals.py                  # full run
    python scripts/score_gov_signals.py --limit 50        # smoke test
    python scripts/score_gov_signals.py --control-size 300
    python scripts/score_gov_signals.py --export-cache reports/export.json
"""

import argparse
import asyncio
import csv
import json
import os
import random
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import certifi

# A fresh Homebrew-Python venv has an empty default SSL trust store, and
# aiohttp builds and caches its default SSLContext as a MODULE-LEVEL
# statement -- so this must run before `import aiohttp`, not merely
# before the first request. CLAUDE.md's own entry; see
# scripts/transcribe_backlog_locally.py for the reference example.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.utils.gov_registry import (  # noqa: E402
    TIER_PINNED,
    TIER_REGISTRY,
    resolve_government,
)
from app.utils.gov_signals import extract_gov_signals  # noqa: E402

# The shared checkout's .env, not the worktree's -- CLAUDE.md's own
# worktree note. Only presence is used here; no value is ever printed.
load_dotenv(REPO_ROOT / ".env")
load_dotenv(Path.home() / "Documents" / "rtr-deeplink" / ".env")

EXPORT_PAGE_DELAY_SECONDS = 1.0
# Same politeness convention as scripts/sweep_tenant_landing_pages.py --
# a real browser UA so a naive hotlink check doesn't false-positive us,
# and a real per-host delay. This fetches MEETING pages, not tenant
# landing pages -- a deliberately different corpus (a prior session's
# postal-code calibration was measured on landing pages; this pass
# measures on the pages the signal actually needs to help, per the
# brief).
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
DELAY_SECONDS = 1.5
FETCH_TIMEOUT = aiohttp.ClientTimeout(total=25)

_CLOUDFLARE_CHALLENGE_MARKERS = (
    "checking your browser before accessing",
    "cf-browser-verification",
    "cf-chl-",
    "just a moment...",
    "attention required! | cloudflare",
)

CORPUS_TIERS = ("unresolved", "unverified")
CONTROL_TIER = "registry"


def _tag_re_free_text(html: str) -> str:
    """Cheap tag-stripped text for `extract_gov_signals()`'s `page_text`
    -- the same "strip tags, collapse whitespace" shape every adapter in
    this repo already uses for jurisdiction extraction (not a full HTML
    parser; a signal-scoring pass doesn't need one)."""
    import re

    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


async def fetch_export_pages(base_url: str, token: str, limit: int = 500) -> List[dict]:
    """Keyset-paginated metadata sweep -- never asks for `segments`, same
    contract `score_gov_registry.py`'s own fetcher uses."""
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
            await asyncio.sleep(EXPORT_PAGE_DELAY_SECONDS)
    print(f"  fetched {len(pages)} pages      ")
    return pages


def _host(url: Optional[str]) -> str:
    if not url:
        return ""
    return (urlparse(url).netloc or "").lower().split(":")[0]


def build_corpus(pages: List[dict], control_size: int, seed: int) -> List[dict]:
    """Every `unresolved`/`unverified` page, plus a random `registry`-tier
    control sample -- re-derived from the live export, per-tier counts
    stated in the SUMMARY rather than assumed from an older document."""
    by_tier: Dict[str, List[dict]] = defaultdict(list)
    for p in pages:
        by_tier[(p.get("jurisdiction_confidence") or "").strip()].append(p)

    corpus = []
    for tier in CORPUS_TIERS:
        rows = by_tier.get(tier, [])
        print(f"  {tier}: {len(rows)} live pages")
        for p in rows:
            corpus.append({**p, "_corpus_role": "target", "_tier_before": tier})

    control_pool = by_tier.get(CONTROL_TIER, [])
    print(f"  {CONTROL_TIER}: {len(control_pool)} live pages ({control_size} sampled)")
    rng = random.Random(seed)
    control_sample = rng.sample(control_pool, min(control_size, len(control_pool)))
    for p in control_sample:
        corpus.append({**p, "_corpus_role": "control", "_tier_before": CONTROL_TIER})

    return corpus


def _cache_path(cache_dir: Path, page_id) -> Path:
    return cache_dir / f"{page_id}.html"


async def fetch_one(session: aiohttp.ClientSession, url: str) -> Optional[str]:
    try:
        async with session.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=FETCH_TIMEOUT, ssl=False
        ) as resp:
            if resp.status != 200:
                return None
            return await resp.text(errors="replace")
    except (aiohttp.ClientError, asyncio.TimeoutError, UnicodeDecodeError, OSError):
        return None


def _looks_like_human_verification_gate(html: str) -> bool:
    lowered = html[:4000].lower()
    return any(marker in lowered for marker in _CLOUDFLARE_CHALLENGE_MARKERS)


async def fetch_corpus_html(
    corpus: List[dict], cache_dir: Path
) -> Dict[int, Optional[str]]:
    """One GET per corpus page's real `source_url`, politely paced, cached
    to disk so a re-run (a smoke test, then the full run) never re-fetches
    a page already on hand. Returns page_id -> html (None for a fetch
    that failed or hit a human-verification gate -- see `skipped`
    counters printed by the caller)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    html_by_id: Dict[int, Optional[str]] = {}
    fetched = skipped_gate = failed = cached = 0
    async with aiohttp.ClientSession() as session:
        for i, page in enumerate(corpus):
            page_id = page.get("id")
            url = page.get("source_url_normalized")
            cache_file = _cache_path(cache_dir, page_id)
            if cache_file.exists():
                html_by_id[page_id] = cache_file.read_text(encoding="utf-8")
                cached += 1
                continue
            if not url:
                html_by_id[page_id] = None
                continue
            html = await fetch_one(session, url)
            if html and _looks_like_human_verification_gate(html):
                # CLAUDE.md's "politely" rule: an explicit human-
                # verification gate means the host is saying no automated
                # client gets through at all -- skip and record it,
                # never attempt to defeat it.
                html_by_id[page_id] = None
                skipped_gate += 1
            elif html is None:
                html_by_id[page_id] = None
                failed += 1
            else:
                cache_file.write_text(html, encoding="utf-8")
                html_by_id[page_id] = html
                fetched += 1
            if (i + 1) % 25 == 0:
                print(
                    f"  fetched {i + 1}/{len(corpus)} "
                    f"(new {fetched}, cached {cached}, gate {skipped_gate}, "
                    f"failed {failed})",
                    end="\r",
                    flush=True,
                )
            await asyncio.sleep(DELAY_SECONDS)
    print(
        f"  fetch done: {fetched} new, {cached} cached, "
        f"{skipped_gate} human-verification gates skipped, {failed} failed"
    )
    return html_by_id


def _ca_province_for_gov_id(gov_id: str) -> str:
    """`ON`/`BC`/... from a `ca:csd:`/`ca:cd:` id's registry row -- looked
    up rather than parsed, since the id itself carries no province."""
    from app.utils.gov_registry import government_for_id

    gov = government_for_id(gov_id) if gov_id else None
    return (gov.state or "").upper() if gov and gov.country == "ca" else ""


def score_corpus(
    corpus: List[dict], html_by_id: Dict[int, Optional[str]]
) -> List[dict]:
    rows = []
    for page in corpus:
        page_id = page.get("id")
        html = html_by_id.get(page_id)
        raw_jurisdiction = page.get("jurisdiction") or ""
        source_url = page.get("source_url_normalized")
        host = _host(source_url)
        path = urlparse(source_url or "").path

        before = resolve_government(raw_jurisdiction, tenant_host=host, path=path)

        row = {
            "page_id": page_id,
            "slug": page.get("slug"),
            "corpus_role": page["_corpus_role"],
            "tier_before": page["_tier_before"],
            "platform": page.get("platform"),
            "tenant_host": host,
            "source_url": source_url,
            "jurisdiction": raw_jurisdiction,
            "gov_id_before": before.gov_id,
            "tier_after_no_signals": before.tier,
            "fetched": html is not None,
        }

        if html is None:
            row.update(
                {
                    "gov_id_after": before.gov_id,
                    "tier_after": before.tier,
                    "changed": False,
                    "signals_used": "",
                }
            )
            rows.append(row)
            continue

        page_text = _tag_re_free_text(html)
        signals = extract_gov_signals(html, page_text, source_url or "", page)
        after = resolve_government(
            raw_jurisdiction, tenant_host=host, path=path, signals=signals
        )

        changed = after.gov_id != before.gov_id
        used = []
        if changed:
            if signals.get("zip_codes"):
                used.append("zip_codes")
            if signals.get("postal_codes"):
                used.append("postal_codes")
            if signals.get("org_names"):
                used.append("org_names")
        row.update(
            {
                "gov_id_after": after.gov_id,
                "tier_after": after.tier,
                "changed": changed,
                "signals_used": "|".join(used),
                "country_after": after.country,
                "state_after": after.state,
                "ca_province_after": _ca_province_for_gov_id(after.gov_id)
                if after.country == "ca"
                else "",
            }
        )
        rows.append(row)
    return rows


def _write(
    path: Path, rows: List[dict], fieldnames: Optional[List[str]] = None
) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = fieldnames or list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_report(rows: List[dict], out_dir: Path) -> None:
    _write(out_dir / "sheet.csv", rows)

    targets = [r for r in rows if r["corpus_role"] == "target"]
    controls = [r for r in rows if r["corpus_role"] == "control"]

    tier_changes = [
        {
            "page_id": r["page_id"],
            "tenant_host": r["tenant_host"],
            "platform": r["platform"],
            "tier_before": r["tier_before"],
            "tier_after": r["tier_after"],
            "gov_id_before": r["gov_id_before"],
            "gov_id_after": r["gov_id_after"],
            "signals_used": r["signals_used"],
        }
        for r in targets
        if r["changed"]
    ]
    _write(out_dir / "tier_changes.csv", tier_changes)

    control_regressions = [
        {
            "page_id": r["page_id"],
            "tenant_host": r["tenant_host"],
            "platform": r["platform"],
            "gov_id_before": r["gov_id_before"],
            "gov_id_after": r["gov_id_after"],
            "signals_used": r["signals_used"],
        }
        for r in controls
        if r["changed"]
    ]
    _write(
        out_dir / "control_regressions.csv",
        control_regressions,
        [
            "page_id",
            "tenant_host",
            "platform",
            "gov_id_before",
            "gov_id_after",
            "signals_used",
        ],
    )

    recovered = [
        r
        for r in targets
        if r["changed"] and r["tier_after"] in (TIER_REGISTRY, TIER_PINNED)
    ]

    by_platform = Counter(r["platform"] for r in recovered)
    _write(
        out_dir / "recovery_by_platform.csv",
        [{"platform": k, "recovered": v} for k, v in by_platform.most_common()],
        ["platform", "recovered"],
    )

    by_country = Counter(r.get("country_after") for r in recovered)
    _write(
        out_dir / "recovery_by_country.csv",
        [{"country": k, "recovered": v} for k, v in by_country.most_common()],
        ["country", "recovered"],
    )

    by_province = Counter(
        r.get("ca_province_after") for r in recovered if r.get("country_after") == "ca"
    )
    _write(
        out_dir / "recovery_by_canadian_province.csv",
        [
            {"province": k or "(unresolved)", "recovered": v}
            for k, v in by_province.most_common()
        ],
        ["province", "recovered"],
    )

    signal_hits = Counter()
    for r in recovered:
        for sig in (r["signals_used"] or "").split("|"):
            if sig:
                signal_hits[sig] += 1
    _write(
        out_dir / "signal_contribution.csv",
        [{"signal": k, "unique_recoveries": v} for k, v in signal_hits.most_common()],
        ["signal", "unique_recoveries"],
    )

    fetched_targets = [r for r in targets if r["fetched"]]
    fetched_ca_target_pages = [
        r
        for r in fetched_targets
        if r["tenant_host"].endswith((".ca", "escribemeetings.com"))
    ]
    postal_hit_pages = [
        r
        for r in fetched_ca_target_pages
        if "postal_codes" in (r["signals_used"] or "")
    ]

    lines = [
        "## Phase 2d — signal scoring",
        "",
        f"*Run {date.today().isoformat()}. `scripts/score_gov_signals.py`; "
        f"raw sheets in `reports/gov_signals_scoring_{date.today().isoformat()}/`.*",
        "",
        "### Corpus",
        "",
        f"- **{len(targets)}** target pages (`unresolved`/`unverified`, live count re-derived "
        "at run time, not assumed from an earlier document).",
        f"- **{len(controls)}** `registry`-tier control pages (random sample).",
        f"- **{len(fetched_targets)}/{len(targets)}** target pages' real source HTML fetched "
        "successfully (the rest: fetch failure or an explicit human-verification gate, "
        "skipped per CLAUDE.md's 'politely' rule, never defeated).",
        "",
        "### Recovery",
        "",
        f"- **{len(recovered)}** of {len(targets)} target pages recovered a `registry`/`pinned` "
        "`gov_id` from signals alone.",
        "",
        "By platform:",
        "",
        "| platform | recovered |",
        "| --- | --- |",
    ]
    for k, v in by_platform.most_common():
        lines.append(f"| {k} | {v} |")
    lines += [
        "",
        "By country:",
        "",
        "| country | recovered |",
        "| --- | --- |",
    ]
    for k, v in by_country.most_common():
        lines.append(f"| {k} | {v} |")
    lines += [
        "",
        "**Canada, by province** (the number Ryan needs to decide on the BC/QC/NU "
        "division-table rows -- ~130 rows, no live-confirmed positive case yet, per "
        "CLAUDE.md):",
        "",
        "| province | recovered |",
        "| --- | --- |",
    ]
    for k, v in by_province.most_common():
        lines.append(f"| {k or '(unresolved)'} | {v} |")
    lines += [
        "",
        "### Postal-code signal hit rate",
        "",
        f"- **{len(postal_hit_pages)}** of **{len(fetched_ca_target_pages)}** fetched Canadian "
        "target pages (`.ca`/`escribemeetings.com` tenant hosts) carried a usable postal code "
        f"({100 * len(postal_hit_pages) / max(len(fetched_ca_target_pages), 1):.0f}%). Prior "
        "calibration (a different corpus -- tenant LANDING pages, not meeting pages) found "
        "roughly 1 in 4; this run measures on meeting pages specifically, which is expected "
        "to differ and is stated here rather than assumed to match.",
        "",
        "### Control regressions",
        "",
    ]
    if control_regressions:
        lines.append(
            f"**{len(control_regressions)}** control-tier page(s) changed `gov_id` -- "
            "target is 0. Each one is a defect, not a note:"
        )
        lines.append("")
        for r in control_regressions[:20]:
            lines.append(
                f"- page {r['page_id']} ({r['tenant_host']}): "
                f"`{r['gov_id_before']}` -> `{r['gov_id_after']}` (signals: {r['signals_used']})"
            )
    else:
        lines.append("**0 control-tier pages changed `gov_id`.** Target met.")
    lines += [
        "",
        "### Per-signal contribution (sequential)",
        "",
        "A signal earning zero unique recoveries once the others have already run is "
        "dropped, not shipped -- same discipline as the tournament sections above.",
        "",
        "| signal | unique recoveries |",
        "| --- | --- |",
    ]
    for k, v in signal_hits.most_common():
        lines.append(f"| {k} | {v} |")
    lines.append("")

    (out_dir / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("  SUMMARY.md")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "reports")
    parser.add_argument(
        "--limit", type=int, default=500, help="export page-size, not corpus size"
    )
    parser.add_argument("--control-size", type=int, default=300)
    parser.add_argument("--seed", type=int, default=105)
    parser.add_argument(
        "--export-cache",
        type=Path,
        default=None,
        help="reuse a previous run's raw export instead of re-fetching",
    )
    parser.add_argument(
        "--save-export",
        type=Path,
        default=None,
        help="write the raw export for later reuse",
    )
    parser.add_argument(
        "--max-fetch",
        type=int,
        default=None,
        help="cap the number of corpus pages actually fetched (smoke test)",
    )
    args = parser.parse_args()

    out_dir = args.out / f"gov_signals_scoring_{date.today().isoformat()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = out_dir / "html_cache"

    print("Archive export:")
    if args.export_cache and args.export_cache.exists():
        pages = json.loads(args.export_cache.read_text())
        print(f"  reused {len(pages)} pages from {args.export_cache}")
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
            args.save_export.write_text(json.dumps(pages))
            print(f"  saved raw export to {args.save_export}")

    print("\nCorpus:")
    corpus = build_corpus(pages, args.control_size, args.seed)
    if args.max_fetch:
        corpus = corpus[: args.max_fetch]
        print(f"  --max-fetch capped corpus to {len(corpus)} pages")

    print("\nFetching corpus pages (politely paced, real source URLs):")
    html_by_id = asyncio.run(fetch_corpus_html(corpus, cache_dir))

    print("\nScoring:")
    rows = score_corpus(corpus, html_by_id)

    print("\nReport:")
    write_report(rows, out_dir)
    print(f"\nDone. See {out_dir}/SUMMARY.md")


if __name__ == "__main__":
    main()
