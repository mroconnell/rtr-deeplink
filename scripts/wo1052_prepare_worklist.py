"""WO-1052: build the worklist for the 2026-09-24 large-county audit's page
fixes. READ-ONLY -- it writes nothing to the Archive.

What it does, step by step.

1. Reads every live page's metadata once, the same read-only way
   `scripts/repair_wrong_pages.py` does (`GET /internal/export/pages`, 500
   rows per request, no transcripts).
2. Finds every page on the tenant hosts this WO corrects (METRO, The Harris
   Center, the Port of Corpus Christi, the Metropolitan Water District
   of Southern California, and six county hosts that were
   pinned to a same-named city). A page whose government is not the
   host's real one gets a `rekey` row. This finds pages the audit did not
   list, as well as the ones it did.
3. Checks each twin page before it gets a `delete` row: the page to keep
   must be live, and its default transcript must match the twin's
   (same segment count and content hash). A twin that fails this gets no
   row, and the reason is printed.
4. Writes `reports/wo1052_worklist.csv` in `repair_wrong_pages.py`'s own
   format, and prints one line per row.

Then run the real tool on that file, dry run first:

    python scripts/repair_wrong_pages.py check reports/wo1052_worklist.csv
    python scripts/repair_wrong_pages.py run reports/wo1052_worklist.csv
    python scripts/repair_wrong_pages.py run reports/wo1052_worklist.csv \\
        --apply --allow-deletes

`repair_wrong_pages.py` re-reads every page before acting, refuses a row
whose page has changed, and reads the page again after writing.

Order matters. The new government ids (METRO, The Harris Center, the Port)
exist only in the registry this WO commits, so the Archive must be
DEPLOYED with this WO before any rekey to them can succeed. The two twin
redirects in `archive/main.py`'s `_SLUG_REDIRECTS` ride the same deploy,
so each twin's old address already forwards before it is deleted.

Where to run it. The Archive service's Render shell (CLAUDE.md: bulk reads
run there, not from a laptop). The token comes from `ARCHIVE_INGEST_TOKEN`
in the environment and is never printed. The address comes from
`--base-url`, then `ARCHIVE_BASE_URL`, then `http://127.0.0.1:$PORT`.

    python scripts/wo1052_prepare_worklist.py
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.repair_wrong_pages import (  # noqa: E402
    NO_GOV,
    WORKLIST_COLUMNS,
    ArchiveClient,
    UnexpectedResponse,
    resolve_base_url,
)

SOURCE_ENTRY = "WO-1052: 2026-09-24 large-county audit loose ends"

METRO = "rtr:us:tx:metropolitan-transit-authority-of-harris-county"
HARRIS_CENTER = "rtr:us:tx:the-harris-center-for-mental-health-and-idd"
PORT = "rtr:us:tx:port-of-corpus-christi"
MWD = "rtr:us:ca:metropolitan-water-district-of-southern-california"


@dataclass(frozen=True)
class HostTarget:
    gov_id: str
    # Pages the audit named for this host. A named page that is missing
    # from the host scan is printed as a note, never guessed at.
    named_ids: Tuple[int, ...]
    needs_ryan: bool
    ryan_decision: str
    reason: str


HOST_TARGETS: Dict[str, HostTarget] = {
    "ridemetro.granicus.com": HostTarget(
        METRO,
        (399, 4177, 5908),
        True,
        "approve",
        "METRO's own Granicus site; filed under Harris County. Ryan approved "
        "the mint and the move 2026-09-24.",
    ),
    "theharriscentertx.new.swagit.com": HostTarget(
        HARRIS_CENTER,
        (3759,),
        True,
        "approve",
        "The Harris Center's own Swagit site (Board of Trustees); filed under "
        "Harris County. Ryan approved the mint and the move 2026-09-24.",
    ),
    "portofcorpuschristi.granicus.com": HostTarget(
        PORT,
        (2659,),
        True,
        "approve",
        "The Port of Corpus Christi Authority's own Granicus site (Port "
        "Commission). Ryan's 2026-09-24 audit brief asks for page 2659 to "
        "move here.",
    ),
    "mwdh2o.granicus.com": HostTarget(
        MWD,
        (2535,),
        True,
        "approve",
        "The Metropolitan Water District of Southern California's own "
        "Granicus site; filed under Los Angeles County. Ryan approved the "
        "mint 2026-09-24.",
    ),
    # Six county hosts the seed script pinned to a same-named city
    # (see tenant_overrides.csv's WO-1052 evidence for what each page says).
    "agendanet.saccounty.gov": HostTarget(
        "us:county:06067", (), False, "", "Sacramento County's own agenda site."
    ),
    "egenda.scgov.net": HostTarget(
        "us:county:12115", (), False, "", "Sarasota County's own agenda site."
    ),
    "imaging.sedgwickcounty.org": HostTarget(
        "us:county:20173", (), False, "", "Sedgwick County, KS's own agenda site."
    ),
    "hcjfsonbase.jfs.hamilton-co.org": HostTarget(
        "us:county:39061",
        (),
        False,
        "",
        "Hamilton County, OH's Job & Family Services agenda site.",
    ),
    "mccobagenda.databankcloud.com": HostTarget(
        "us:county:04013", (), False, "", "Maricopa County Board's agenda site."
    ),
    "cocookmn.civicweb.net": HostTarget(
        "us:county:27031", (), False, "", "Cook County, MN's own CivicWeb site."
    ),
}


@dataclass(frozen=True)
class Delete:
    slug: str
    # The twin that stays. None for a page removed as off-mission.
    keep_slug: Optional[str]
    audit_page_id: int
    ryan_decision: str
    reason: str


DELETES: Tuple[Delete, ...] = (
    Delete(
        "harris-county-tx-2026-06-11-jun-11-2026-commissioners-court-12cb68",
        "harris-county-tx-2026-06-11-jun-11-2026-commissioners-court",
        1171,
        "approve",
        "Twin of Harris County's Jun 11 2026 Commissioners Court, archived "
        "from the Swagit URL with a stray trailing %5C. Ryan's 2026-09-24 "
        "audit brief asks for it to be removed.",
    ),
    Delete(
        "los-angeles-county-ca-2026-08-11-english-los-angeles-county-board-of-supervisors-fcc9d9",
        "los-angeles-county-ca-2026-08-11-english-los-angeles-county-board-of-supervisors",
        3964,
        "",
        "Twin of LA County's 2026-08-11 Board of Supervisors (Granicus clip "
        "12325), archived from the MediaPlayer.php URL shape.",
    ),
    Delete(
        "los-angeles-county-ca-2025-08-26-2025-cssd-learning-summit-trailer-extended-aug",
        None,
        5775,
        "",
        "A promo trailer (2025 CSSD Learning Summit, lacountymediahost clip "
        "13160), not a meeting.",
    ),
)


def page_host(page: dict) -> str:
    url = page.get("source_url_normalized") or ""
    return (urlsplit(url).hostname or "").lower()


def default_version(page: dict) -> Optional[dict]:
    versions = page.get("versions") or []
    return next((v for v in versions if v.get("is_default")), None)


def _row(
    page: dict,
    action: str,
    target: str,
    needs_ryan: bool,
    decision: str,
    reason: str,
) -> Dict[str, str]:
    return {
        "page_id": str(page["id"]),
        "action": action,
        "target_gov_id": target,
        "expected_current_gov_id": (page.get("gov_id") or "").strip() or NO_GOV,
        "expected_slug": page.get("slug") or "",
        "requires": "",
        "confidence": "high",
        "needs_ryan": "yes" if needs_ryan else "no",
        "ryan_decision": decision,
        "source_entry": SOURCE_ENTRY,
        "shown_today": page.get("jurisdiction") or "",
        "reason": reason,
        "evidence": page.get("source_url_normalized") or "",
    }


def plan_rows(pages: Iterable[dict]) -> Tuple[List[Dict[str, str]], List[str]]:
    """The worklist rows, plus notes for anything that got no row."""
    pages = list(pages)
    by_slug = {p.get("slug"): p for p in pages}
    rows: List[Dict[str, str]] = []
    notes: List[str] = []

    for host, target in HOST_TARGETS.items():
        on_host = [p for p in pages if page_host(p) == host]
        found_ids = {p["id"] for p in on_host}
        for missing in sorted(set(target.named_ids) - found_ids):
            notes.append(f"page {missing}: named by the audit, not found on {host}")
        for page in sorted(on_host, key=lambda p: p["id"]):
            if (page.get("gov_id") or "") == target.gov_id:
                notes.append(f"page {page['id']}: already on {target.gov_id}")
                continue
            rows.append(
                _row(
                    page,
                    "rekey",
                    target.gov_id,
                    target.needs_ryan,
                    target.ryan_decision,
                    target.reason,
                )
            )

    for delete in DELETES:
        page = by_slug.get(delete.slug)
        if page is None:
            notes.append(f"{delete.slug}: not live (already deleted?)")
            continue
        if page["id"] != delete.audit_page_id:
            notes.append(
                f"{delete.slug}: is page {page['id']}, the audit said "
                f"{delete.audit_page_id} -- no row"
            )
            continue
        if delete.keep_slug is not None:
            keep = by_slug.get(delete.keep_slug)
            if keep is None:
                notes.append(
                    f"{delete.slug}: its twin {delete.keep_slug} is not live -- no row"
                )
                continue
            a, b = default_version(page), default_version(keep)
            same = (
                a is not None
                and b is not None
                and a.get("segment_count") == b.get("segment_count")
                and a.get("content_hash") == b.get("content_hash")
            )
            if not same:
                notes.append(
                    f"{delete.slug}: default transcript differs from page "
                    f"{keep['id']}'s -- no row; compare them by hand"
                )
                continue
        rows.append(_row(page, "delete", "", True, delete.ryan_decision, delete.reason))

    # normalize_url() now drops a trailing backslash, so a page whose stored
    # key still ends in one can no longer be found by its own URL.
    for page in pages:
        key = (page.get("source_url_normalized") or "").lower()
        if key.endswith("%5c") or key.endswith("\\"):
            notes.append(
                f"page {page['id']} ({page.get('slug')}): stored URL ends in a "
                "backslash"
            )

    return rows, notes


def read_all_pages(client: ArchiveClient) -> List[dict]:
    pages: List[dict] = []
    after_id = 0
    while True:
        body = client._send(
            "GET", "/internal/export/pages", params={"after_id": after_id, "limit": 500}
        )
        batch = body.get("pages")
        if not isinstance(batch, list):
            raise UnexpectedResponse("export/pages answered no 'pages' list")
        pages.extend(batch)
        after_id = body.get("next_after_id")
        if after_id is None:
            return pages


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-url", help="the Archive's address")
    parser.add_argument(
        "--out", default="reports/wo1052_worklist.csv", help="worklist to write"
    )
    args = parser.parse_args(argv)

    token = os.environ.get("ARCHIVE_INGEST_TOKEN", "")
    base_url = resolve_base_url(args.base_url)
    if not token or not base_url:
        print(
            "Needs ARCHIVE_INGEST_TOKEN and an Archive address (--base-url, "
            "ARCHIVE_BASE_URL or $PORT).",
            file=sys.stderr,
        )
        return 2

    pages = read_all_pages(ArchiveClient(base_url, token))
    rows, notes = plan_rows(pages)

    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=WORKLIST_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Read {len(pages)} pages. Wrote {len(rows)} rows to {args.out}.")
    for row in rows:
        print(
            f"  page {row['page_id']:>6}  {row['action']:6}  "
            f"{row['expected_current_gov_id']} -> {row['target_gov_id'] or '(deleted)'}"
            f"  {row['expected_slug']}"
        )
    for note in notes:
        print(f"  note: {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
