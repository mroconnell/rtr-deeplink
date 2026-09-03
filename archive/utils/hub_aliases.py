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
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

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
