"""Backfill `meeting_pages.gov_id` / `gov_type`, and rewrite
`jurisdiction` to the registry display name -- WO-99, Phase 2 of
`rtr-business/research/GOVERNMENT_IDENTITY_ARCHITECTURE.md`.

`_find_or_create_page()` does this for every ingest from now on; this is
the retroactive sweep over everything already archived, and the way to
re-run the whole corpus after a registry change (a new pin, a corrected
`governments.csv` row, a resolver fix).

**Dry run by DEFAULT** -- the opposite of every other backfill in this
directory, deliberately. This one rewrites a user-visible column on
thousands of rows, so the safe direction is that a bare invocation only
reports. `--apply` writes.

Run it from the Archive service's Render Shell, never from a laptop
against the production `DATABASE_URL`. That is `BACKLOG.md`'s standing
decision and CLAUDE.md's own bullet, and the reason is measured: the
same rule was broken on 2026-08-23 by
`scripts/backfill_meeting_highlights.py`, which pulled ~1 GB of
`segments` across the network at ~7 pages/minute -- a six-hour run
holding production read load. This script never touches `segments`
(jurisdiction, gov_id and the source URL are all it reads), so it is far
cheaper, but the rule is about where a bulk workload runs, not how big
it is.

Two properties make stopping it safe, and both are deliberate:

  * **commit per row** -- killing it mid-run leaves a consistent partial
    state, not a half-written transaction;
  * **skip rows already current** -- a re-run resumes rather than
    restarting, and a run after a registry change re-does exactly the
    rows whose answer moved.

A `manual_override` row is never touched -- not its `gov_id`, its
`gov_type`, its string or its tier (WO-215): a human already said which
government that page belongs to, and this sweep is precisely the
recomputation that override exists to survive. It is reported as
"already current", never as a proposed change. (WO-240 correction: a
2026-09-11 checkout that predated WO-215 re-keyed page 4097, a manual
override, to the county under the authoritative Gloucester County, VA
pin, and this docstring briefly said the sweep re-keys such rows. It
does not, as of WO-215; that page's move stands because Ryan's pin
decision covers it.)

Usage (from the repo root, with DATABASE_URL set):
    python scripts/backfill_gov_id.py                  # dry run, full report
    python scripts/backfill_gov_id.py --limit 200      # dry run, first 200
    python scripts/backfill_gov_id.py --apply          # write
    python scripts/backfill_gov_id.py --apply --limit 200
    python scripts/backfill_gov_id.py --report /tmp/gov_id_backfill.csv

After a round of pins, restricted to just the hosts those pins settled
(`scripts/apply_pin_worklist.py` writes the file and prints the command):
    python scripts/backfill_gov_id.py --hosts-file reports/pin_worklist_hosts.txt
"""

import argparse
import asyncio
import csv
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write. Without it this only reports (the default).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process the first N pages, by id (for a smoke test)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Write the per-row diff to this CSV as well as summarising it",
    )
    parser.add_argument(
        "--hosts",
        default=None,
        help="Comma-separated tenant hosts to restrict the sweep to",
    )
    parser.add_argument(
        "--hosts-file",
        type=Path,
        default=None,
        help=(
            "File of tenant hosts, one per line -- what "
            "scripts/apply_pin_worklist.py writes after a round of pins"
        ),
    )
    args = parser.parse_args()

    # Restricting by HOST rather than by page id is what keeps the
    # same-tenant consistency rung honest: every page of a named host is
    # still loaded, so the dominant-government pre-pass below sees exactly
    # what an unrestricted run would see for that host. A page-id filter
    # would not, and would quietly give a different answer than the full
    # sweep.
    only_hosts = set()
    if args.hosts:
        only_hosts |= {h.strip().lower() for h in args.hosts.split(",") if h.strip()}
    if args.hosts_file:
        only_hosts |= {
            line.strip().lower()
            for line in args.hosts_file.read_text().splitlines()
            if line.strip() and not line.startswith("#")
        }

    load_dotenv()

    from sqlalchemy import select

    from app.utils.gov_registry import (
        TIER_BLANK,
        TIER_INFERRED,
        TIER_PINNED,
        TIER_REGISTRY,
        TIER_UNRESOLVED,
        TIER_UNVERIFIED,
        is_multi_gov_host,
        page_hints_for,
        resolve_government,
    )
    from archive.db import hub_slugs as hub_slug_table
    from archive.db.engine import async_session
    from archive.db.crud import (
        _display_from_registry,
        _display_jurisdiction,
        live_hub_slug,
    )
    from archive.db.models import MeetingPage
    from archive.utils.jurisdiction_format import normalize_state_suffix

    # The one tier this sweep must not overwrite. Imported by value
    # rather than re-spelled, so a rename cannot silently un-protect
    # every hand-fixed page in the archive.
    from archive.db.crud import _MANUAL_OVERRIDE_CONFIDENCE

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"gov_id backfill -- {mode}")

    async with async_session() as session:
        # WO-256: the hubs this run could move a page between are read off
        # the frozen `hub_slugs` table, not recomputed from each page's
        # text. That is the whole point of the freeze: a page changing
        # GOVERNMENT no longer retires a SLUG, so the "hub slugs retired"
        # line below counts only a slug that genuinely stops belonging to
        # anybody. Empty before the migration/backfill has run, which just
        # means the report falls back to the live computation it used
        # before.
        await hub_slug_table.refresh(session, force=True)
        stmt = select(
            MeetingPage.id,
            MeetingPage.slug,
            MeetingPage.jurisdiction,
            MeetingPage.jurisdiction_confidence,
            MeetingPage.meeting_body,
            MeetingPage.gov_id,
            MeetingPage.gov_type,
            MeetingPage.source_url_normalized,
            # WO-105: platform/external_id feed page_hints_for(), which
            # is what makes a tenant_overrides.csv `match=key=value` row
            # reachable at all -- see that function's own docstring.
            MeetingPage.platform,
            MeetingPage.external_id,
            MeetingPage.video_channel,
        ).order_by(MeetingPage.id.asc())
        if args.limit:
            stmt = stmt.limit(args.limit)
        rows = (await session.execute(stmt)).all()

    print(f"  {len(rows)} pages to consider")
    if only_hosts:
        print(f"  restricted to {len(only_hosts)} tenant hosts")

    # Two passes, the same shape scripts/score_gov_registry.py uses and
    # for the same reason -- with one extra reason that only applies
    # here.
    #
    # The resolver's same-tenant consistency rung needs to know the
    # government most of a tenant's OTHER pages resolved to. At ingest
    # time `_find_or_create_page()` answers that with a query, because
    # the rest of the archive is already resolved. On a first backfill
    # nothing is: every `gov_id` is NULL, so that query returns nothing
    # for every row and the rung can never fire. Running it against the
    # database here would silently produce a worse result than the
    # scoring report predicted -- measured on a seeded copy before this
    # was fixed: `milwaukee.granicus.com` kept its minted id beside its
    # real one, which is the exact fragmentation the rung exists to
    # collapse.
    #
    # So pass 1 resolves every row on its own evidence, in memory; the
    # dominant government per tenant is computed from those results; and
    # pass 2 re-resolves only the rows pass 1 left `unverified` or
    # `unresolved`. Cheaper as well as more correct -- no per-row query
    # at all.
    resolved: dict[int, object] = {}
    keep = []
    overrides = 0
    for row in rows:
        (
            page_id,
            slug,
            jurisdiction,
            confidence,
            current_meeting_body,
            current_gov_id,
            current_gov_type,
            source_url,
            platform,
            external_id,
            video_channel,
        ) = row
        parsed = urlparse(source_url or "")
        host = (parsed.netloc or "").lower().split(":")[0]
        if only_hosts and host not in only_hosts:
            continue
        if confidence == _MANUAL_OVERRIDE_CONFIDENCE:
            overrides += 1
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        # The stored `jurisdiction` is already finalize_jurisdiction()'s
        # output, not an adapter's raw payload -- the resolver runs it
        # through that function again, which is idempotent on its own
        # output. normalize_state_suffix() first, matching the order
        # _find_or_create_page() uses.
        raw = normalize_state_suffix(jurisdiction)
        # WO-105: same page_hints_for() build as crud._resolve_page_
        # government() -- see that function's docstring for why this was
        # previously always empty in production.
        hints = page_hints_for(platform, external_id, channel=video_channel)
        keep.append((row, host, path, raw, hints))
        resolved[page_id] = resolve_government(
            raw, tenant_host=host or None, path=path, page_hints=hints
        )

    dominant_by_host: dict[str, str] = {}
    votes: dict[str, Counter] = {}
    for row, host, _path, _raw, _hints in keep:
        match = resolved[row[0]]
        if not host or match.tier not in (TIER_REGISTRY, TIER_PINNED):
            continue
        if not match.gov_id or match.gov_id.startswith("rtr:"):
            continue
        votes.setdefault(host, Counter())[match.gov_id] += 1
    for host, counts in votes.items():
        ranked = counts.most_common(2)
        # A tie is no answer, same rule as crud._tenant_dominant_gov_id()
        # and the scoring script's own pre-pass.
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            continue
        dominant_by_host[host] = ranked[0][0]
    print(f"  dominant government known for {len(dominant_by_host)} tenants")

    changes = []
    tiers: Counter = Counter()
    unchanged = 0
    hub_moves: Counter = Counter()
    # Every slug some real government owns, so the report can tell a slug
    # that MOVED PAGES (normal, and no longer a URL change for anybody)
    # from one that genuinely stops belonging to anybody (WO-256). Seeded
    # with every frozen slug, then extended with the live slug of each
    # government this run touches.
    owned_slugs: set = set(hub_slug_table.frozen_hub_slugs().values())

    for row, host, path, raw, hints in keep:
        (
            page_id,
            slug,
            jurisdiction,
            confidence,
            current_meeting_body,
            current_gov_id,
            current_gov_type,
            _source_url,
            _platform,
            _external_id,
            _video_channel,
        ) = row
        match = resolved[page_id]
        if match.tier in (TIER_UNVERIFIED, TIER_UNRESOLVED):
            dominant = dominant_by_host.get(host)
            if dominant:
                match = resolve_government(
                    raw,
                    tenant_host=host or None,
                    path=path,
                    page_hints=hints,
                    tenant_gov_id=dominant,
                )

        tiers[match.tier] += 1
        overridden = confidence == _MANUAL_OVERRIDE_CONFIDENCE
        # WO-215, defect 1: rung 1b (WO-210) answers `blank` -- gov_id
        # `rtr:unknown:<host>` -- for EVERY row on a MULTI_GOV_HOSTS host
        # (YouTube, Vimeo, ClerkHQ, ...) that has no matching per-video/
        # channel/external-id pin, regardless of what identity the row
        # already carries. That answer means "no matching pin was found,"
        # not "this page has no government," so a row that already keyed
        # to a real national or curated id (its CURRENT gov_id isn't
        # itself rtr:unknown:*) must keep it. Confirmed live: an
        # unguarded dry run against production proposed exactly this
        # downgrade on 825 YouTube-host rows (757 registry, 56
        # unverified, 12 unresolved). `_find_or_create_page()` carries
        # the identical guard now (WO-215) for live re-ingest.
        blank_downgrade = (
            not overridden
            and match.tier == TIER_BLANK
            and host
            and is_multi_gov_host(host)
            and current_gov_id
            and not current_gov_id.startswith("rtr:unknown:")
        )
        # WO-215, defect 2: a manual_override row's gov_id/gov_type is a
        # human's decision and must never be recomputed by this sweep --
        # previously only the jurisdiction string and the tier were
        # protected here, so an overridden row's gov_id was silently
        # rewritten the moment rung 1b answered `blank` for its host
        # (228 rows, confirmed live against production). A
        # blank_downgrade row (defect 1, above) gets the identical
        # treatment: keep the id, the type, the tier and the display name
        # exactly as they are, so the row is reported as already current
        # rather than a proposed change.
        protect_identity = overridden or blank_downgrade
        new_gov_id = current_gov_id if protect_identity else (match.gov_id or None)
        new_gov_type = (
            current_gov_type if protect_identity else (match.gov_type or None)
        )
        # A protected row keeps BOTH its string and its tier: the string
        # because a human chose it (or because nothing new was actually
        # learned), the tier because `_find_or_create_page()`'s guard
        # recognises pages by exactly that value, and turning it into a
        # resolution tier would quietly un-protect every hand-fixed page
        # in the archive.
        new_confidence = confidence if protect_identity else match.tier
        # The same rule `_find_or_create_page()` applies at ingest -- one
        # function, imported, so the backfill can never disagree with a
        # fresh ingest about what a page is called (gov-id audit,
        # 2026-09-10: every keyed tier takes the registry name now, not
        # only pinned/registry).
        new_jurisdiction = (
            jurisdiction
            if protect_identity
            else _display_jurisdiction(match, jurisdiction)
        )
        # When the display name comes from the registry for a non-place
        # government, finalize_jurisdiction()'s split body duplicates the
        # entity ("Housing Authority" beside "Housing Authority of the
        # County of Santa Clara, CA"). Drop it only in that exact shape --
        # the stored body is a prefix of the new display name -- so a
        # body an adapter supplied on its own (Granicus's RSS title) is
        # never touched.
        new_meeting_body = current_meeting_body
        if (
            not protect_identity
            and _display_from_registry(match)
            and match.meeting_body is None
            and current_meeting_body
            and (new_jurisdiction or "")
            .lower()
            .startswith(current_meeting_body.lower())
        ):
            new_meeting_body = None

        # "Already current" tolerates one specific tier flip: pass 1
        # rewrites `jurisdiction` to the registry name, and on pass 2 that
        # string keys straight to the national table (`registry`) where a
        # fallback pin (`pinned`) had keyed the raw one -- same gov_id,
        # same name, only the label moves. Measured 2026-09-09: 187 of a
        # 315-row run re-proposed exactly this on a second dry run.
        # Treating the pair as equivalent is what makes "dry run again ->
        # expect 0" true after one apply.
        # `inferred` joins the set (2026-09-10, second full run): pass 1
        # rewrote "The City of Milwaukee, WI" to the registry's
        # "Milwaukee, WI" on an inferred row, and pass 2 keys that string
        # straight to the table -- same gov_id, same name, only the label.
        tier_equivalent = {confidence, new_confidence} <= {
            TIER_PINNED,
            TIER_REGISTRY,
            TIER_INFERRED,
        }
        if (
            new_gov_id == current_gov_id
            and new_gov_type == current_gov_type
            and new_jurisdiction == jurisdiction
            and new_meeting_body == current_meeting_body
            and (confidence == new_confidence or tier_equivalent)
        ):
            unchanged += 1
            continue

        # A government's FROZEN slug first, then the live computation for
        # a government that has not got one yet (WO-256). `match.hub_slug`
        # is the resolver's own live answer for the new id and is still
        # the right fallback for one the freeze has never seen.
        old_hub = hub_slug_table.frozen_hub_slug(current_gov_id) or live_hub_slug(
            current_gov_id, jurisdiction
        )
        new_hub = (
            hub_slug_table.frozen_hub_slug(new_gov_id)
            or match.hub_slug
            or live_hub_slug(new_gov_id, new_jurisdiction)
        )
        if old_hub and current_gov_id and not current_gov_id.startswith("rtr:unknown:"):
            owned_slugs.add(old_hub)
        if new_hub and new_gov_id and not new_gov_id.startswith("rtr:unknown:"):
            owned_slugs.add(new_hub)
        if old_hub and new_hub and old_hub != new_hub:
            hub_moves[(old_hub, new_hub)] += 1

        changes.append(
            {
                "page_id": page_id,
                "slug": slug,
                "tenant_host": host,
                "jurisdiction_before": jurisdiction or "",
                "jurisdiction_after": new_jurisdiction or "",
                "confidence_before": confidence or "",
                "tier_after": new_confidence,
                "resolver_tier": match.tier,
                "gov_id_before": current_gov_id or "",
                "gov_id_after": new_gov_id or "",
                "gov_type_after": new_gov_type or "",
                "hub_before": old_hub or "",
                "hub_after": new_hub or "",
                "evidence": match.evidence,
            }
        )

        if args.apply:
            # Commit per row. Slower than one big UPDATE and worth it:
            # this is the property that makes a Ctrl-C safe and a re-run
            # a resume rather than a restart.
            async with async_session() as write_session:
                page = await write_session.get(MeetingPage, page_id)
                if page is None:
                    continue
                # Re-read inside the write session: a human may have
                # overridden this row since the read above, and an
                # override that landed in between must still keep its
                # id, its type, its string and its tier -- WO-215:
                # gov_id/gov_type used to be written unconditionally
                # here, so an override landing in that gap could still
                # be overwritten by the very sweep the override exists
                # to survive.
                live_override = (
                    page.jurisdiction_confidence == _MANUAL_OVERRIDE_CONFIDENCE
                )
                if not live_override:
                    page.gov_id = new_gov_id
                    page.gov_type = new_gov_type
                    page.jurisdiction = new_jurisdiction
                    page.meeting_body = new_meeting_body
                    if not (
                        {page.jurisdiction_confidence, match.tier}
                        <= {TIER_PINNED, TIER_REGISTRY, TIER_INFERRED}
                    ):
                        page.jurisdiction_confidence = match.tier
                await write_session.commit()

    _report(changes, tiers, hub_moves, owned_slugs, unchanged, overrides, args)


def _report(changes, tiers, hub_moves, owned_slugs, unchanged, overrides, args) -> None:
    print("")
    label = "changed          " if args.apply else "would change     "
    print(f"  {label} : {len(changes)}")
    print(f"  already current   : {unchanged}")
    print(f"  manual_override   : {overrides} (keyed; their string is left alone)")
    print("")
    print("  tier distribution:")
    for tier, n in tiers.most_common():
        print(f"    {tier:12} {n}")

    keyed = sum(
        1
        for r in changes
        if r["gov_id_after"] and not r["gov_id_after"].startswith("rtr:")
    )
    print("")
    print(f"  rows gaining a national id: {keyed}")

    merges = Counter()
    for (old_hub, new_hub), n in hub_moves.items():
        merges[new_hub] += n
    # WO-256: a page changing government no longer retires a slug -- the
    # government keeps its own frozen hub whether or not this page stays
    # on it. A slug is only really retired when NO government owns it,
    # which since the freeze means an un-keyed page's raw-text hub losing
    # its last page. That is the number that needs a
    # `hub_slug_aliases.csv` row; the rest need nothing.
    retired = {o for o, _ in hub_moves if o not in owned_slugs}
    print(f"  hub slugs retired         : {len(retired)} (no government owns them)")
    print(f"  pages moving to another hub: {sum(hub_moves.values())}")
    print(f"  hubs receiving pages      : {len(merges)}")
    print("")
    print("  largest hub moves:")
    for (old_hub, new_hub), n in hub_moves.most_common(15):
        print(f"    /j/{old_hub} -> /j/{new_hub}  ({n} pages)")

    # The rows a human has to look at: a real government name the ladder
    # could not key, left NULL rather than given an id nobody can look
    # up. These are what `tenant_overrides.csv` pins are for, and what
    # the landing-page sweep works from.
    unresolved = [r for r in changes if not r["gov_id_after"]]
    if unresolved:
        print("")
        print(f"  left unresolved (want a pin): {len(unresolved)}")
        by_host = Counter(r["tenant_host"] for r in unresolved)
        for host, n in by_host.most_common(15):
            print(f"    {host}  ({n})")

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with open(args.report, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=[
                    "page_id",
                    "slug",
                    "tenant_host",
                    "jurisdiction_before",
                    "jurisdiction_after",
                    "confidence_before",
                    "tier_after",
                    "resolver_tier",
                    "gov_id_before",
                    "gov_id_after",
                    "gov_type_after",
                    "hub_before",
                    "hub_after",
                    "evidence",
                ],
            )
            writer.writeheader()
            writer.writerows(changes)
        print("")
        print(f"  per-row diff written to {args.report}")

    if not args.apply:
        print("")
        print("  DRY RUN -- nothing written. Re-run with --apply to commit.")


if __name__ == "__main__":
    asyncio.run(main())
