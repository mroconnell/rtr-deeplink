"""Check the gov-id problem-case list against the archive -- the small,
hand-picked regression corpus behind `backfill_gov_id.py`'s whole-archive
dry run (Ryan, 2026-09-10: "a list of fewer than 6000 meetings ... likely
problem cases, collisions, difficult situations, unique platform
combinations").

`reports/gov_id_problem_cases.csv` holds one row per archived page whose
identity was checked by a human or a test during the 2026-09-09/10 gov-id
audit and is known to be RIGHT (or, for the blank/unresolved rows, known
to be honestly unkeyed): the shared TelVue token that filed Half Moon Bay
under Pacifica, Juneau AK keyed to Juneau WI, the WFWRD board under
Wasatch County, subdomains whose two letters are a type ("arkansas-sc"),
the consolidated city-counties, Lloydminster's two provinces, the nine
tenants that are not the government whose name they carry (LADWP,
SANDAG, ...), the generic-embed collisions, and a few controls that must
NOT move (South San Francisco is not San Francisco).

Two ways to run it, both read-only:

    python scripts/check_gov_id_problem_cases.py --export pages.json
        compares each case's expected gov_id / display / tier with what
        the Archive holds NOW (a saved GET /internal/export/pages, or
        fetched live when ARCHIVE_BASE_URL/ARCHIVE_INGEST_TOKEN are set
        and --export is omitted)

    python scripts/check_gov_id_problem_cases.py --export pages.json \\
        --dry-run-report /tmp/gov_id_dryrun.csv
        additionally reads a `backfill_gov_id.py --report` file and flags
        any case the backfill WOULD move off its expected answer -- run
        this before every `--apply`; it is how a resolver change that
        re-breaks a settled case gets caught before it is written

Exit status 1 on any drift, so it can gate a run. A case whose page has
been deleted is reported, not failed.

Adding a case: append a row with the page id, the expected `gov_id`
(blank for a page that must stay blank/unresolved), the expected display
name, the tier, a category, and a one-line note saying WHY this page is
hard. Expected values are what a human verified, never what the
resolver happens to say today -- that is the whole point.
"""

import argparse
import asyncio
import csv
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from dotenv import load_dotenv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")
load_dotenv(Path.home() / "Documents" / "rtr-deeplink" / ".env")

CASES = REPO_ROOT / "reports" / "gov_id_problem_cases.csv"


async def _fetch_export(base_url: str, token: str) -> List[dict]:
    import aiohttp

    pages: List[dict] = []
    after = 0
    async with aiohttp.ClientSession(headers={"Authorization": f"Bearer {token}"}) as s:
        while True:
            async with s.get(
                f"{base_url.rstrip('/')}/internal/export/pages",
                params={"after_id": after, "limit": 500},
                timeout=aiohttp.ClientTimeout(total=180),
            ) as r:
                if r.status != 200:
                    raise SystemExit(f"export -> HTTP {r.status}")
                body = await r.json()
            pages.extend(body.get("pages") or [])
            after = body.get("next_after_id")
            if after is None:
                return pages
            await asyncio.sleep(0.4)


def load_cases() -> List[dict]:
    with open(CASES, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load_dry_run(path: Optional[Path]) -> Dict[str, dict]:
    if not path:
        return {}
    with open(path, encoding="utf-8") as fh:
        return {r["page_id"]: r for r in csv.DictReader(fh)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--export", type=Path, help="saved /internal/export/pages JSON")
    ap.add_argument(
        "--dry-run-report", type=Path, help="backfill_gov_id.py --report CSV"
    )
    args = ap.parse_args()

    if args.export:
        pages = json.loads(args.export.read_text(encoding="utf-8"))
        if isinstance(pages, dict):
            pages = pages.get("pages") or []
    else:
        base, tok = (
            os.environ.get("ARCHIVE_BASE_URL"),
            os.environ.get("ARCHIVE_INGEST_TOKEN"),
        )
        if not base or not tok:
            raise SystemExit(
                "pass --export, or set ARCHIVE_BASE_URL and ARCHIVE_INGEST_TOKEN"
            )
        pages = asyncio.run(_fetch_export(base, tok))
    by_id = {str(p["id"]): p for p in pages}
    would = load_dry_run(args.dry_run_report)

    cases = load_cases()
    drift, missing, ok = [], [], 0
    for c in cases:
        p = by_id.get(c["page_id"])
        if p is None:
            missing.append(c)
            continue
        problems = []
        now_gov = p.get("gov_id") or ""
        exp_gov = c["expected_gov_id"]
        if exp_gov and now_gov != exp_gov:
            problems.append(f"gov_id now {now_gov or 'NULL'} (expected {exp_gov})")
        if not exp_gov and now_gov and not now_gov.startswith("rtr:unknown:"):
            problems.append(f"gov_id now {now_gov} (expected blank/unresolved)")
        if (
            c["expected_jurisdiction"]
            and (p.get("jurisdiction") or "") != c["expected_jurisdiction"]
        ):
            problems.append(
                f"display now {p.get('jurisdiction')!r} (expected {c['expected_jurisdiction']!r})"
            )
        w = would.get(c["page_id"])
        if w:
            if exp_gov and (w.get("gov_id_after") or "") != exp_gov:
                problems.append(
                    f"backfill WOULD set gov_id {w.get('gov_id_after') or 'NULL'} (expected {exp_gov})"
                )
            if (
                c["expected_jurisdiction"]
                and (w.get("jurisdiction_after") or "") != c["expected_jurisdiction"]
            ):
                problems.append(
                    f"backfill WOULD set display {w.get('jurisdiction_after')!r} (expected {c['expected_jurisdiction']!r})"
                )
        if problems:
            drift.append((c, problems))
        else:
            ok += 1

    # `status`: verified rows fail the run on drift; known_wrong rows are
    # documented live bugs (the generic-embed collisions) and open rows are
    # honestly unkeyed pages awaiting a pin -- both are reported so the
    # list stays honest, but neither fails the run.
    failing = [
        (c, p) for c, p in drift if (c.get("status") or "verified") == "verified"
    ]
    noted = [(c, p) for c, p in drift if (c.get("status") or "verified") != "verified"]
    print(
        f"problem cases: {len(cases)} | ok: {ok} | drift: {len(failing)} | "
        f"known-wrong/open still wrong: {len(noted)} | page gone: {len(missing)}"
    )
    for c, problems in failing + noted:
        label = (
            "DRIFT"
            if (c.get("status") or "verified") == "verified"
            else c["status"].upper()
        )
        print(f"\n  {label} page {c['page_id']} /m/{c['slug']}  [{c['category']}]")
        for msg in problems:
            print(f"    - {msg}")
        if c["note"]:
            print(f"    note: {c['note']}")
    for c in missing:
        print(
            f"\n  GONE  page {c['page_id']} /m/{c['slug']}  [{c['category']}] -- not in the export"
        )
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
