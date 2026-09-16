"""Old `/j/{slug}` URLs that no longer name a hub, and the government
they now belong to.

WO-99 made `/j/` group by `gov_id` instead of by the slug of a display
string. That is what collapses "County of Fresno, CA" and "Fresno County,
CA" into one hub -- 176 merges over 359 hub pages in the 2026-09-02
scoring run -- and decision D6 accepted up front that a handful of live
URLs change in exchange. Every one of those URLs has been linked from a
`/m/` page, a `/state/` page and `sitemap.xml`, and some are indexed. A
404 would throw that away; a 301 keeps it.

**A generated map, not a table.** The set of old slugs is finite and
knowable exactly once: it is every distinct `jurisdiction_hub_slug()`
over the pages as they stand *before* the backfill rewrites
`MeetingPage.jurisdiction` to the registry display name. After the
backfill the old spelling is gone from the database, so a map derived
live could not reconstruct it -- which is why this is a committed file
written by `scripts/score_gov_registry.py` from the same run that
produced the merge list, reviewable in the pull request beside the
numbers that justify it, and deployed with the code rather than needing a
migration and a write path of its own.

The trade is that a *future* rename (a registry correction, a new pin)
needs the scoring script re-run to extend this file. That is acceptable
because re-running it is already the step someone takes when they edit
the registry, and the file is regenerated wholesale rather than appended
to, so it cannot drift out of agreement with the registry it came from.

**A second, additive writer exists too (WO-293).** `write_retirements()`
below is what `scripts/backfill_gov_id.py --apply` calls the moment it
discovers a slug no government owns any more -- appending (or updating)
one row at a time rather than a wholesale regen, and always followed by
`collapse_chains()` over the WHOLE file so a row this call adds can never
leave a two-hop chain behind, and neither can a pre-existing one it
happens to touch. This is what a retirement that predates this WO
(`lake-havasu-az -> city-of-lake-havasu-az -> 404`, WO-251's fix retiring
the minted government a second time with no alias written for the second
hop) needed and never got -- see that function's own docstring.
"""

from __future__ import annotations

import csv
import io
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

ALIAS_FILE = Path(__file__).parent.parent / "data" / "hub_slug_aliases.csv"

HEADER = ["old_slug", "gov_id", "new_slug", "evidence"]


@lru_cache(maxsize=1)
def hub_slug_aliases() -> Dict[str, str]:
    """old slug -> the slug that government's hub lives at now.

    Empty when the file is absent, which is a working state, not an
    error: before the backfill runs there are no retired slugs, and a
    missing map costs a 404 on a URL that would have 404'd anyway.
    """
    if not ALIAS_FILE.exists():
        return {}
    out: Dict[str, str] = {}
    with open(ALIAS_FILE, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            old = (row.get("old_slug") or "").strip().lower()
            new = (row.get("new_slug") or "").strip().lower()
            # A self-referential row would be a redirect loop. It should
            # never be written, and is skipped here rather than trusted.
            if old and new and old != new:
                out[old] = new
    return out


def redirect_target(slug: str) -> Optional[str]:
    """The live hub slug a retired one redirects to, or None."""
    return hub_slug_aliases().get((slug or "").strip().lower())


# --- WO-293: chain repair and the ongoing retirement writer -----------------
#
# `redirect_target()` above is deliberately a single dict lookup, not a
# chain-follower: `archive/main.py`'s `/j/{hub_slug}` route only calls it
# once per request, when the DIRECT hub lookup for that slug comes back
# empty. So a row whose OWN `new_slug` is *itself* another row's
# `old_slug` costs the reader a second 301 round trip (still correct,
# just slower) -- unless that second hop is itself broken, in which case
# the reader lands on a 404. Both shapes are real, live 2026-09-12: the
# second was 42 confirmed targets, almost all from
# `scripts/backfill_gov_id.py --apply` retiring a MINTED government's
# hub a second time (the government keeps its `gov_id`, but a fixed
# name-repair bug, WO-251, moves it onto the real Census place's id) with
# no alias written for that second hop -- the classic case is
# `lake-havasu-az -> city-of-lake-havasu-az` (written when "City of Lake
# Havasu, AZ" was first minted) left orphaned when a later backfill
# re-keyed it onto `us:place:0439370`'s real, frozen `lake-havasu-city-az`.
#
# `collapse_chains()` below is what both the one-time repair and the
# ongoing writer (`write_retirements()`) use to guarantee "no alias
# resolves to another alias" -- not just for the row a writer just added,
# but for the whole file, since an unrelated older row can coincidentally
# share a slug with a value a new row introduces.


def collapse_chains(
    rows: List[Dict[str, str]], *, max_hops: int = 50
) -> List[Dict[str, str]]:
    """Rewrite every row's `new_slug` to the FINAL slug in its redirect
    chain, so no row's `new_slug` is itself another row's `old_slug`.

    Walks each row's own chain independently, tracking the slugs seen
    *during that row's own walk*. A genuine cycle -- two rows retiring
    into each other, which really happened for Caledonia Township/
    Village, MI on two consecutive days (2026-09-10, then WO-231's
    2026-09-11 correction reversed it) -- is left for the row-under-walk
    UNCHANGED rather than forced into a self-reference: which of the two
    slugs is actually live is a fact about the SITE (does the direct hub
    lookup succeed for it), not something this file alone can decide, and
    guessing wrong risks breaking a row that is currently correct (here,
    `caledonia-village-mi -> caledonia-township-mi`, confirmed live via a
    301 that lands on a real 200 -- collapsing it blindly would have
    turned that into a dead self-reference the loader silently drops).

    A row whose walk lands back on its OWN `old_slug` (not a row-external
    cycle, just this row's chain looping back to itself) is also left
    unchanged for the same reason -- the loader's own self-reference
    guard is what actually retires it once it is genuinely no longer
    needed, and that only happens when the direct hub lookup for its
    `old_slug` stops succeeding.
    """
    by_old = {r["old_slug"].strip().lower(): r for r in rows}
    out: List[Dict[str, str]] = []
    for r in rows:
        start = r["old_slug"].strip().lower()
        target = r["new_slug"].strip().lower()
        seen = {start, target}
        hops = 0
        cyclic = False
        while target in by_old and hops < max_hops:
            nxt = by_old[target]["new_slug"].strip().lower()
            if nxt == target:
                # The next hop is already a self-reference (dead,
                # loader-skipped) -- nothing further to walk.
                break
            if nxt in seen:
                cyclic = True
                break
            seen.add(nxt)
            target = nxt
            hops += 1
        new_row = dict(r)
        if not cyclic:
            new_row["new_slug"] = target
        out.append(new_row)
    return out


def read_rows(path: Optional[Path] = None) -> List[Dict[str, str]]:
    """The alias file's rows as plain dicts, in file order. Empty (not an
    error) when the file does not exist yet -- same working-state
    convention as `hub_slug_aliases()`.

    `path` defaults to the CURRENT `ALIAS_FILE` -- read at CALL time, not
    bound into the function signature -- so a test can
    `monkeypatch.setattr(hub_aliases, "ALIAS_FILE", tmp_path)` and every
    caller here (including `write_retirements()`, which has no `path`
    argument of its own) picks it up without touching the real committed
    file."""
    path = path if path is not None else ALIAS_FILE
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_rows(rows: Iterable[Dict[str, str]], path: Optional[Path] = None) -> None:
    """Write `rows` back to `path`, then drop the cached map so a reader
    in this same process (a script, a test) sees the update immediately.

    **Byte-for-byte preserving for every row that did not change.** Row
    `i` is compared against physical data line `i` already on disk; if
    every field is identical, the ORIGINAL bytes are kept verbatim
    (whatever line ending they already had); only a row whose values
    actually differ, or one past the end of the file (newly appended),
    is re-rendered. Two things this avoids, both measured while building
    this (WO-293): (1) re-sorting the file -- it has never been in a
    single global sort order, it grew across several append/regen passes
    -- turned a 4-row fix into a 470-line diff; (2) even an
    order-preserving but naive round trip through `csv.DictWriter`
    touches every row whose line happens to carry a stray `\\r\\n` left
    over from an earlier regen pass (16 of them, found this way, unrelated
    to any real change) because it normalizes every line ending to the
    writer's own. Either failure mode buries the real, reviewable change
    in incidental noise. Callers must pass back the *original* row list
    with only the actually-changed rows edited in place and any brand-new
    ones appended at the end -- never a freshly built list, or every row
    looks new to the position-based comparison this relies on.
    """
    path = path if path is not None else ALIAS_FILE
    rows = list(rows)
    original = path.read_bytes() if path.exists() else b""
    lines = original.splitlines(keepends=True)
    header_line = lines[0] if lines else (",".join(HEADER) + "\n").encode("utf-8")
    if not header_line.endswith(b"\n"):
        header_line += b"\n"
    original_data_lines = lines[1:]

    def _parse(line: bytes) -> Optional[Dict[str, str]]:
        text = line.decode("utf-8").rstrip("\r\n")
        try:
            fields = next(csv.reader([text]))
        except StopIteration:
            return None
        return {k: (fields[i] if i < len(fields) else "") for i, k in enumerate(HEADER)}

    def _render(row: Dict[str, str]) -> bytes:
        buf = io.StringIO()
        csv.writer(buf, lineterminator="\n").writerow([row.get(k, "") for k in HEADER])
        return buf.getvalue().encode("utf-8")

    out_lines: List[bytes] = [header_line]
    for i, row in enumerate(rows):
        if i < len(original_data_lines):
            orig_line = original_data_lines[i]
            parsed = _parse(orig_line)
            if parsed is not None and all(
                parsed.get(k, "") == (row.get(k) or "") for k in HEADER
            ):
                if not orig_line.endswith(b"\n"):
                    orig_line += b"\n"
                out_lines.append(orig_line)
                continue
        out_lines.append(_render(row))

    with open(path, "wb") as fh:
        fh.write(b"".join(out_lines))
    hub_slug_aliases.cache_clear()


def write_retirements(
    entries: Iterable[Tuple[str, str, str, str]], *, path: Optional[Path] = None
) -> int:
    """Retire the given `(old_slug, gov_id, new_slug, evidence)` hubs into
    the alias file in one pass, then collapse the WHOLE file's chains --
    not just the rows this call touches, since an older, unrelated row
    can coincidentally point at a slug one of these entries retires.

    This is the writer `scripts/backfill_gov_id.py --apply` calls
    (WO-293) so a slug it retires never needs a second, manual hop added
    later: the same operation that discovers "no government owns this
    slug any more" also keeps the redirect file in the one-hop shape
    `collapse_chains()` guarantees.

    An entry whose `old_slug == new_slug` is skipped (nothing to
    retire). Returns the number of rows added or changed. Safe to call
    with an empty `entries` list -- it still re-collapses the file, which
    is how the one-time WO-293 repair also fixed the pre-existing chains
    that predate this function.
    """
    rows = read_rows(path)
    by_old = {r["old_slug"].strip().lower(): r for r in rows}
    changed = 0
    for old_slug, gov_id, new_slug, evidence in entries:
        old_slug = (old_slug or "").strip().lower()
        new_slug = (new_slug or "").strip().lower()
        if not old_slug or not new_slug or old_slug == new_slug:
            continue
        existing = by_old.get(old_slug)
        if existing is None:
            row = {
                "old_slug": old_slug,
                "gov_id": gov_id or "",
                "new_slug": new_slug,
                "evidence": evidence or "",
            }
            rows.append(row)
            by_old[old_slug] = row
            changed += 1
        elif existing["new_slug"].strip().lower() != new_slug:
            existing["new_slug"] = new_slug
            existing["gov_id"] = gov_id or existing.get("gov_id", "")
            existing["evidence"] = evidence or existing.get("evidence", "")
            changed += 1

    rows = collapse_chains(rows)
    write_rows(rows, path)
    return changed
