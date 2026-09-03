"""Turn Ryan's filled-in `reports/pin_worklist.csv` back into
`tenant_overrides.csv` pins, and say exactly what to run to key the pages.

Phase 2c of `rtr-business/research/GOVERNMENT_IDENTITY_ARCHITECTURE.md`,
the other half of `scripts/build_pin_worklist.py`. Ryan writes a
government's name in plain English -- "Prince George's County Public
Schools, MD" -- or "ok" to accept the row's proposal, or "skip". This
resolves what he wrote through `gov_registry`, writes the pin, and
reports back every row it could not settle.

**Pin-writing reaches nothing in production.** It writes one local,
committed data file (`app/utils/jurisdiction_data/tenant_overrides.csv`)
and two local reports. The pages only move when
`scripts/backfill_gov_id.py` runs from the Archive's Render shell, which
is Ryan's action and which needs the pins DEPLOYED first -- they are
data files inside the image, so a merge alone ships nothing (CLAUDE.md's
own standing note). The exact command sequence is printed at the end.

**A `DELETE` note reaches production directly, over HTTP, the moment
`--apply-deletes` is passed.** A row is not always a government that
wants a name -- sometimes it is test/staging/spoofed content that should
never have been archived at all (a real 2026-08-19 case: 3 PrimeGov
UAT/staging pages, see BACKLOG_DONE.md). Writing `DELETE` anywhere in
`ryan_gov_name` or `ryan_note` skips resolution entirely and instead
calls the Archive's `POST /internal/admin/delete-pages` for every page
IN THAT ROW'S GROUP -- the same `(tenant_host, match)` grouping the sheet
itself uses, so a delete can never reach a page outside the row it was
written on. This is a call over HTTP to an existing token-gated admin
endpoint (crud.delete_meeting_pages_by_slug(), already dry-run-by-default
and already cascade-safe), not a DB scan -- WO-93's "production access is
HTTP-only" standing decision, same as everything else this script does.

Deletion gets its OWN flag, deliberately separate from `--apply`. Writing
a pin is a one-line git revert; deleting an archived page cascades
(transcript versions, jobs, thumbnails, social posts, saved items) and is
not undone by reverting a file. So a plain `--apply` run -- writing pins,
which is the common case -- can never delete anything, even if a `DELETE`
row is sitting on the sheet; `--apply-deletes` is required in addition,
and every DELETE row is dry-run and previewed in the report regardless of
either flag, so what would be removed is visible before it happens.

**What it does NOT do**: delete only some of a row's pages. `DELETE`
removes every page the row represents -- if a tenant's unresolved pages
are a mix of real meetings and junk, write actual slugs into
`/internal/admin/delete-pages` by hand instead (see BACKLOG.md's
`Nothing verifies a submitted URL is a genuine government site` entry for
the broader gap this doesn't attempt to close). It also does not stop the
same URL being re-ingested later -- there is no denylist; deletion is
retroactive only.

Three more things it will not do, each for a measured reason:

  * **Never `authoritative`.** Every pin written here is `fallback`:
    it settles a page the ladder could not key, and never overrides a
    working extraction. `authoritative` is the tier that can make a
    correct resolution wrong, and no tool takes it.
  * **Never mint on its own.** A name that reaches only an `rtr:` id is
    reported back, not written, unless the row says "ok mint" -- the
    `king.granicus.com` rule ("a machine may not mint a government for a
    tenant"), with the human's "ok mint" as the human source that rule
    asks for.
  * **Never pin a name that is not the government's own.** A name that
    resolves to a government it does not name is reported back with what
    it reached, so the sheet can be corrected. "Howard County Public
    School System, MD" really does resolve -- to Howard *County* -- and
    the registry's own spelling ("Howard County Public Schools, MD")
    resolves to the school district. `gov_registry.is_own_name()`.

Usage:
    python scripts/apply_pin_worklist.py                 # report only
    python scripts/apply_pin_worklist.py --apply         # write the pins
    python scripts/apply_pin_worklist.py --apply-deletes # delete DELETE rows
    python scripts/apply_pin_worklist.py --archive-cache /tmp/export.json
"""

import argparse
import asyncio
import csv
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple
from urllib.parse import urlparse

import certifi

# Before `import aiohttp` -- see build_pin_worklist.py's note.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from dotenv import load_dotenv  # noqa: E402

import aiohttp  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.utils.gov_registry import (  # noqa: E402
    TIER_PINNED,
    TIER_REGISTRY,
    display_name,
    is_own_name,
    registry,
    resolve_government,
)
from scripts.build_pin_worklist import (  # noqa: E402
    WANTED_TIERS,
    WORKLIST,
    YOUTUBE_MAP,
    _YOUTUBE_HOSTS,
    fetch_export_pages,
    group_pages,
    read_youtube_map,
    youtube_video_id,
)

load_dotenv(REPO_ROOT / ".env")
load_dotenv(Path.home() / "Documents" / "rtr-deeplink" / ".env")

OVERRIDES = registry.DATA_DIR / registry.TENANT_OVERRIDES_FILE
CURATED_GOVERNMENTS = registry.DATA_DIR / registry.CURATED_GOVERNMENTS_FILE
HOSTS_FILE = REPO_ROOT / "reports" / "pin_worklist_hosts.txt"
REPORT = REPO_ROOT / "reports" / "pin_worklist_applied.csv"

# What Ryan can write in `ryan_gov_name` instead of a name.
ACCEPT_PROPOSAL = "ok"
DECLINE = {"skip", "none", "no", "-", "n/a"}
# Permission to pin a minted `rtr:` id, in either of Ryan's two columns.
MINT_TOKEN = "ok mint"
# In EITHER of Ryan's two columns: this row is not a government, delete
# every page it represents. Word-boundary matched so it can sit next to
# other text ("DELETE - obviously a UAT tenant") without a false miss,
# and so it can never accidentally fire on a real name that merely
# CONTAINS the letters -- there is no real government whose name is the
# word "delete".
_DELETE_RE = re.compile(r"\bdelete\b", re.I)

REPORT_HEADER = [
    "outcome",
    "platform",
    "tenant_host",
    "match",
    "pages",
    "stated_name",
    "gov_id",
    "gov_name",
    "tier",
    "detail",
]


def _is_delete_row(row: dict) -> bool:
    """Whether `row` asks for its pages to be removed rather than named.

    Checked in EITHER `ryan_gov_name` or `ryan_note` -- the sheet is
    filled in by hand and there is no reason to make Ryan remember which
    column a token belongs in. Checked before `_answer()`/`resolve_answer()`
    run at all: a delete row is never resolved, and if `ryan_gov_name` also
    has a name in it (a row filled in, then reconsidered), DELETE wins --
    the more consequential action, so a leftover name doesn't quietly
    downgrade a delete into a pin.
    """
    return bool(
        _DELETE_RE.search(row.get("ryan_gov_name") or "")
        or _DELETE_RE.search(row.get("ryan_note") or "")
    )


def _answer(row: dict) -> Tuple[str, str, str, bool]:
    """(name, accepted gov_id, source token, may-mint) for one row.

    An empty `ryan_gov_name` is not an answer and never becomes one -- the
    sheet is filled in over several sittings, so most rows are blank on
    any given run.

    "ok" accepts the row's `proposed_gov_id` **as an id**, not by
    re-resolving `proposed_name`. Those are not the same thing and the
    difference is not cosmetic: `proposed_name` is the registry's DISPLAY
    form, which for a name that collides inside its state carries an LSAD
    qualifier -- "Portage (city), MI", "Webster (village), NY" -- and that
    qualifier is a display convention, not a lookup key. Re-resolving it
    misses the place table and mints `rtr:us:mi:portage-city` instead. 12
    of the 94 proposals on the first generated sheet had this shape, and
    `test_every_proposal_on_the_sheet_still_resolves_to_the_id_it_records`
    is what found it. The build script already applied the acceptance rule
    to reach that id; accepting the id is accepting that work, and
    re-deriving it would only be a chance to get a different answer.
    """
    stated = (row.get("ryan_gov_name") or "").strip()
    note = (row.get("ryan_note") or "").strip()
    may_mint = MINT_TOKEN in f"{stated} {note}".lower()
    if stated.lower().startswith(ACCEPT_PROPOSAL):
        # The pin records that a human accepted it AND which signal
        # produced it -- two different claims, both of which a later
        # reader needs.
        return (
            row.get("proposed_name") or "",
            row.get("proposed_gov_id") or "",
            "ryan_stated+proposal",
            may_mint,
        )
    return stated, "", "ryan_stated", may_mint


async def delete_pages(
    base_url: str, token: str, slugs: List[str], *, dry_run: bool
) -> dict:
    """POST /internal/admin/delete-pages for `slugs`.

    Thin wrapper -- the endpoint already does the real work (dry-run
    reporting, the FK-safe cascade). `dry_run=True` is always safe to call
    with no flag on this script at all, which is why the main loop calls
    it unconditionally: Ryan sees exactly what a DELETE row would remove
    -- titles, platform, source URL -- before `--apply-deletes` is ever
    passed, the same read-only-first preview the endpoint itself defaults
    to.
    """
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    url = f"{base_url.rstrip('/')}/internal/admin/delete-pages"
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            params={"dry_run": "true" if dry_run else "false"},
            headers=headers,
            json={"slugs": slugs},
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise SystemExit(f"POST {url} -> HTTP {resp.status}: {body[:300]}")
            return await resp.json()


def _existing_pins() -> set:
    if not OVERRIDES.exists():
        return set()
    with open(OVERRIDES, encoding="utf-8") as fh:
        return {
            (
                (r.get("tenant_host") or "").strip().lower(),
                (r.get("match") or "").strip(),
                (r.get("gov_id") or "").strip(),
            )
            for r in csv.DictReader(fh)
        }


def _pages_by_host(pages: List[dict]) -> Dict[str, List[dict]]:
    out: Dict[str, List[dict]] = {}
    for page in pages:
        host = (
            (urlparse(page.get("source_url_normalized") or "").netloc or "")
            .lower()
            .split(":")[0]
        )
        if host:
            out.setdefault(host, []).append(page)
    return out


def _youtube_match_values(
    row: dict, pages_by_host: Dict[str, List[dict]], channels: Dict[str, dict]
) -> List[str]:
    """The `match` values a YouTube channel row must actually be written as.

    A channel handle is the right unit for a HUMAN decision -- one channel
    is one government, and Ryan names it once. It is the wrong unit for a
    pin: `_match_override()` satisfies a `match` by finding it in the
    page's path or query, and a YouTube page's URL carries the video id
    and nothing else. Neither ingest nor the backfill passes `page_hints`,
    so a pin written `match=@TownofWoodside` would be silently inert --
    the worst possible outcome, because the sheet would say the host was
    settled and the pages would stay unresolved.

    So one decision expands to one pin per video id on that channel and
    host, which the path does carry. `reports/pin_worklist_youtube.csv` is
    the map, written by the build script from the same oEmbed lookups
    that produced the channel title Ryan read.
    """
    host = row["tenant_host"]
    channel = row["match"]
    out = []
    for page in pages_by_host.get(host, []):
        vid = youtube_video_id(page.get("source_url_normalized") or "")
        if vid and (channels.get(vid) or {}).get("channel") == channel:
            out.append(vid)
    return sorted(set(out))


def resolve_answer(name: str, host: str, may_mint: bool, accepted_gov_id: str = ""):
    """(match, gov_id, gov_name, tier, outcome, detail) for one answer.

    `outcome` is what the report prints and what decides whether a pin is
    written: only "pin" is written.
    """
    if accepted_gov_id:
        gov = registry.government_for_id(accepted_gov_id)
        if gov is None:
            return (
                None,
                accepted_gov_id,
                "",
                "",
                "unknown_gov_id",
                "the sheet proposes an id no governments.csv row renders -- "
                "rebuild the worklist",
            )
        return (
            None,
            accepted_gov_id,
            display_name(gov),
            "proposal",
            "pin",
            "accepted the sheet's proposal",
        )
    if not name:
        return None, "", "", "", "no_proposal", 'row says "ok" but has no proposed_name'
    match = resolve_government(name, tenant_host=host)
    gov_name = display_name(match.government) if match.government else ""
    if not match.gov_id:
        return match, "", gov_name, match.tier, "unresolved", match.evidence
    if match.gov_id.startswith("rtr:unknown:"):
        return match, "", gov_name, match.tier, "unresolved", match.evidence
    if match.gov_id.startswith("rtr:"):
        if not may_mint:
            return (
                match,
                match.gov_id,
                gov_name,
                match.tier,
                "unverified",
                'no national table row for this name -- add "ok mint" to '
                "ryan_note to pin the minted id",
            )
        return (
            match,
            match.gov_id,
            gov_name,
            match.tier,
            "pin",
            f"minted: {match.evidence}",
        )
    if not is_own_name(name, match):
        return (
            match,
            match.gov_id,
            gov_name,
            match.tier,
            "name_mismatch",
            f'resolves to "{gov_name}" ({match.gov_id}), which is not what the '
            f"name says -- retype it as the registry spells it",
        )
    if match.tier not in (TIER_REGISTRY, TIER_PINNED):
        return match, match.gov_id, gov_name, match.tier, "unresolved", match.evidence
    return match, match.gov_id, gov_name, match.tier, "pin", match.evidence


def _append_minted_governments(minted: List[dict]) -> None:
    """Give every minted `rtr:` pin a `curated_governments.csv` row.

    A pin whose gov_id has no `governments.csv` row is not a resolution,
    it is a broken registry: `_pinned()` looks the id up to render its
    name, misses, and falls through to the ladder -- so the host stays
    exactly as unresolved as before, with a pin on the sheet saying it is
    settled. `test_every_tenant_override_row_has_a_resolvable_gov_id`
    exists for this and caught it the first time this script minted one
    (`achdidaho.civicweb.net`, Ada County Highway District).

    `curated_governments.csv` rather than `governments.csv` because the
    latter is a generated snapshot of whatever the last scoring run
    resolved to, and a regeneration would drop a row no page has reached
    yet -- which is every freshly minted government, by construction.

    No aliases are written. On a curated row the `aliases` column is an
    assertion that a raw string MEANS this government, trusted for lookup
    everywhere (`registry.curated_aliases()`); "Ryan typed this name for
    this tenant" is a narrower claim than that, and the pin already
    carries it.
    """
    with open(CURATED_GOVERNMENTS, "a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        for gov, evidence in minted:
            writer.writerow(
                [
                    gov.gov_id,
                    gov.gov_name,
                    gov.gov_type,
                    gov.country,
                    gov.state,
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "curated+ryan_stated",
                    evidence,
                ]
            )


def _append_pins(pins: List[dict]) -> None:
    with open(OVERRIDES, "a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        for pin in pins:
            writer.writerow(
                [
                    pin["tenant_host"],
                    pin["match"],
                    pin["gov_id"],
                    "fallback",
                    pin["source"],
                    pin["evidence"],
                ]
            )


def _write_report(results: List[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=REPORT_HEADER)
        writer.writeheader()
        writer.writerows(results)


def _verify(pages: List[dict], hosts: set) -> Tuple[int, int]:
    """(pages still without a government, pages now keyed) among the pages
    that WANTED a pin on the hosts this run touched, re-resolved with the
    pins actually on disk.

    Scoped to the `unresolved`/`blank` pages on purpose: `youtu.be` alone
    carries hundreds of already-keyed pages, and counting those would
    report a large number that says nothing about what this run did.

    Only meaningful after `--apply`: it re-reads `tenant_overrides.csv`
    through the real loader, so it tests the file that shipped rather than
    the intention behind it. A pin the loader drops -- an `rtr:` id with no
    human source, a gov_id with no `governments.csv` row -- shows up here
    as a page that did not move.
    """
    registry.clear_caches()
    keyed = unkeyed = 0
    for page in pages:
        parsed = urlparse(page.get("source_url_normalized") or "")
        host = (parsed.netloc or "").lower().split(":")[0]
        if host not in hosts:
            continue
        if (page.get("jurisdiction_confidence") or "") not in WANTED_TIERS:
            continue
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        match = resolve_government(
            page.get("jurisdiction"), tenant_host=host, path=path
        )
        if match.gov_id and not match.gov_id.startswith("rtr:unknown:"):
            keyed += 1
        else:
            unkeyed += 1
    return unkeyed, keyed


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the pins to tenant_overrides.csv. Without it, report only.",
    )
    parser.add_argument(
        "--apply-deletes",
        action="store_true",
        help=(
            "Actually delete every page a DELETE row represents. Without it, "
            "DELETE rows are still previewed (dry_run against the real "
            "endpoint) but nothing is removed. Separate from --apply on "
            "purpose -- see the module docstring."
        ),
    )
    parser.add_argument("--worklist", type=Path, default=WORKLIST)
    parser.add_argument(
        "--archive-cache",
        type=Path,
        default=None,
        help="reuse a saved export instead of sweeping production again",
    )
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY RUN"
    if args.apply_deletes:
        mode += " + DELETES ARMED"
    print(f"pin worklist -- {mode}")

    if not args.worklist.exists():
        raise SystemExit(
            f"{args.worklist} not found -- run scripts/build_pin_worklist.py first"
        )
    with open(args.worklist, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    answered = [
        r for r in rows if (r.get("ryan_gov_name") or "").strip() or _is_delete_row(r)
    ]
    print(f"  {len(rows)} rows, {len(answered)} answered")
    if not answered:
        print("\nNothing to do. Fill in `ryan_gov_name` and re-run.")
        return

    # Needed for DELETE previews too, even with --archive-cache -- a
    # cached export answers "what pages does this row represent" but a
    # delete still has to reach the live Archive to preview or apply.
    base_url = os.environ.get("ARCHIVE_BASE_URL")
    token = os.environ.get("ARCHIVE_INGEST_TOKEN")
    any_deletes = any(_is_delete_row(r) for r in rows)
    if (not (args.archive_cache and args.archive_cache.exists()) or any_deletes) and (
        not base_url or not token
    ):
        raise SystemExit(
            "ARCHIVE_BASE_URL and ARCHIVE_INGEST_TOKEN must be set "
            "(they are in the shared checkout's .env)"
        )

    print("\nArchive export:")
    if args.archive_cache and args.archive_cache.exists():
        pages = json.loads(args.archive_cache.read_text())
        print(f"  reused {len(pages)} pages from {args.archive_cache}")
    else:
        pages = asyncio.run(fetch_export_pages(base_url, token))
    pages_by_host = _pages_by_host(pages)
    channels = read_youtube_map(YOUTUBE_MAP)
    wanted = [
        p for p in pages if (p.get("jurisdiction_confidence") or "") in WANTED_TIERS
    ]
    # The SAME grouping the sheet itself was built from -- a DELETE row
    # can only ever reach the pages its own row represents, never a
    # neighbour's, and never a page that already has a government.
    groups_by_key = {
        (g["tenant_host"], g["match"]): g for g in group_pages(wanted, channels)
    }

    existing = _existing_pins()
    known_governments = set(registry.governments())
    results: List[dict] = []
    pins: List[dict] = []
    minted: List[Tuple[object, str]] = []
    deletes: List[dict] = []
    hosts_touched: set = set()
    pages_keyed = 0
    pages_deleted = 0

    for row in rows:
        stated_raw = (row.get("ryan_gov_name") or "").strip()
        host = (row.get("tenant_host") or "").strip().lower()
        pages_here = int(row.get("pages") or 0)
        base = {
            "platform": row.get("platform") or "",
            "tenant_host": host,
            "match": row.get("match") or "",
            "pages": pages_here,
            "stated_name": stated_raw,
        }

        if _is_delete_row(row):
            group = groups_by_key.get((host, row.get("match") or ""))
            slugs = [
                pg.get("slug")
                for pg in (group or {}).get("_pages", [])
                if pg.get("slug")
            ]
            if not slugs:
                results.append(
                    {
                        **base,
                        "outcome": "no_pages_to_delete",
                        "gov_id": "",
                        "gov_name": "",
                        "tier": "",
                        "detail": (
                            "no unresolved/blank page currently matches this row -- "
                            "already keyed, already deleted, or the worklist is stale"
                        ),
                    }
                )
                continue
            preview = asyncio.run(delete_pages(base_url, token, slugs, dry_run=True))
            found_slugs = [f["slug"] for f in preview.get("found", [])]
            if args.apply_deletes and found_slugs:
                asyncio.run(delete_pages(base_url, token, found_slugs, dry_run=False))
                outcome = "deleted"
                pages_deleted += len(found_slugs)
            elif found_slugs:
                outcome = "would_delete"
            else:
                outcome = "no_pages_to_delete"
            results.append(
                {
                    **base,
                    "outcome": outcome,
                    "gov_id": "",
                    "gov_name": "",
                    "tier": "",
                    "detail": (
                        f"{len(found_slugs)} page(s): "
                        + ", ".join(found_slugs[:5])
                        + (
                            f" (+{len(found_slugs) - 5} more)"
                            if len(found_slugs) > 5
                            else ""
                        )
                    ),
                }
            )
            if found_slugs:
                deletes.append({**base, "slugs": found_slugs, "outcome": outcome})
            continue

        if not stated_raw:
            continue
        if stated_raw.lower() in DECLINE:
            results.append(
                {
                    **base,
                    "outcome": "skipped",
                    "gov_id": "",
                    "gov_name": "",
                    "tier": "",
                    "detail": "declined on the sheet",
                }
            )
            continue

        name, accepted_gov_id, source, may_mint = _answer(row)
        resolved, gov_id, gov_name, tier, outcome, detail = resolve_answer(
            name, host, may_mint, accepted_gov_id
        )
        if outcome == "pin" and stated_raw.lower().startswith(ACCEPT_PROPOSAL):
            detail = f"accepted proposal: {row.get('proposed_evidence') or detail}"
        results.append(
            {
                **base,
                "outcome": outcome,
                "gov_id": gov_id,
                "gov_name": gov_name,
                "tier": tier,
                "detail": detail,
            }
        )
        if outcome != "pin":
            continue

        # A YouTube channel is one decision and several pins -- see
        # `_youtube_match_values()` for why the handle itself cannot be one.
        if host in _YOUTUBE_HOSTS and (row.get("match") or ""):
            match_values = _youtube_match_values(row, pages_by_host, channels)
            if not match_values:
                results[-1]["outcome"] = "no_videos"
                results[-1]["detail"] = (
                    "no archived video on this host maps to this channel -- "
                    "rebuild the worklist"
                )
                continue
            channel_note = f" (YouTube channel {row['match']})"
        else:
            match_values = [row.get("match") or ""]
            channel_note = ""

        evidence = f"{name}{channel_note} -- {detail}"
        # A minted government needs its own registry row before the pin
        # can render, and exactly one even when the pin expands to 24
        # video ids.
        if (
            resolved is not None
            and gov_id.startswith("rtr:")
            and gov_id not in known_governments
        ):
            known_governments.add(gov_id)
            minted.append((resolved.government, evidence))
        wrote = 0
        for match_value in match_values:
            key = (host, match_value, gov_id)
            if key in existing:
                continue
            existing.add(key)
            pins.append(
                {
                    "tenant_host": host,
                    "match": match_value,
                    "gov_id": gov_id,
                    "source": source,
                    "evidence": evidence,
                }
            )
            wrote += 1
        if wrote:
            hosts_touched.add(host)
            pages_keyed += pages_here
        else:
            results[-1]["outcome"] = "already_pinned"

    _write_report(results, args.report)
    print(f"\nreport: {args.report}")

    outcomes = Counter(r["outcome"] for r in results)
    print("")
    for outcome, n in outcomes.most_common():
        print(f"  {outcome:16} {n}")

    if args.apply and pins:
        if minted:
            _append_minted_governments(minted)
            print(
                f"\nwrote {len(minted)} minted government rows to {CURATED_GOVERNMENTS}"
            )
        _append_pins(pins)
        print(f"wrote {len(pins)} pin rows to {OVERRIDES}")
    elif pins:
        print(f"\nwould write {len(pins)} pin rows to {OVERRIDES} (--apply to do it)")

    delete_outcomes = ("deleted", "would_delete", "no_pages_to_delete")
    if deletes:
        print("")
        if args.apply_deletes:
            print(f"  deleted {pages_deleted} page(s) across {len(deletes)} row(s):")
        else:
            print(
                f"  would delete {sum(len(d['slugs']) for d in deletes)} page(s) "
                f"across {len(deletes)} row(s) (--apply-deletes to do it):"
            )
        for d in deletes:
            print(
                f"    {d['tenant_host'][:38]:40} {len(d['slugs']):>3} page(s)  "
                f"{', '.join(d['slugs'][:3])}"
                + (f" (+{len(d['slugs']) - 3} more)" if len(d["slugs"]) > 3 else "")
            )

    print("")
    print(f"  pins written        : {len(pins) if args.apply else 0}")
    print(f"  hosts settled       : {len(hosts_touched)}")
    print(f"  pages keyed by them : {pages_keyed}")
    still = [
        r
        for r in results
        if r["outcome"] not in ("pin", "already_pinned") + delete_outcomes
    ]
    print(f"  rows still open     : {len(still)}")
    for row in still[:15]:
        print(
            f"    {row['outcome']:14} {row['tenant_host'][:38]:40} "
            f"{row['stated_name'][:32]:34} {row['detail'][:60]}"
        )
    if len(still) > 15:
        print(f"    ... and {len(still) - 15} more, in {args.report}")

    if args.apply and hosts_touched:
        unkeyed, keyed = _verify(pages, hosts_touched)
        print("")
        print("  re-resolved with the pins now on disk:")
        print(f"    pages keyed        : {keyed}")
        print(f"    pages still unkeyed: {unkeyed}")

    if hosts_touched:
        HOSTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        HOSTS_FILE.write_text("\n".join(sorted(hosts_touched)) + "\n")
        print(f"\nhosts to backfill: {HOSTS_FILE} ({len(hosts_touched)} hosts)")
        print("")
        print("Ryan's turn -- the pins are data files inside the image, so a")
        print("merge alone ships nothing:")
        print("")
        print("  1. Merge the PR.")
        print("  2. Render dashboard -> rtr-deeplink-archive -> Manual Deploy ->")
        print("     latest commit. Wait for it to go live.")
        print("  3. Archive service -> Shell tab, dry run first:")
        print("")
        print("     python scripts/backfill_gov_id.py \\")
        print("       --hosts-file reports/pin_worklist_hosts.txt \\")
        print("       --report /tmp/pins_dryrun.csv")
        print("")
        print(f"     Expect `would change : {pages_keyed}` and no NULL gov_id_after.")
        print("")
        print("  4. Same command with --apply:")
        print("")
        print("     python scripts/backfill_gov_id.py --apply \\")
        print("       --hosts-file reports/pin_worklist_hosts.txt \\")
        print("       --report /tmp/pins_applied.csv")
        print("")
        print("  5. Paste the output back, then re-run")
        print("     scripts/build_pin_worklist.py to refresh the sheet.")


if __name__ == "__main__":
    main()
