"""WO-356 item 6: "this is a historic archive after all" -- Ryan's rule,
no freshness cutoff for a real meeting video. Queues three real,
identifiable, but old tier-3 finds that WO-349 had rejected purely for
staleness: Grinnell city, IA (Regular City Council Session, 2024-12-02,
20.8 min), Hastings-on-Hudson village, NY (Information Session on the
Plus One ADU Program, 2024-10-08, 32.3 min -- on-mission-checked: the
village's own official Swagit tenant, hastingsonhudsonny.swagit.com,
carries this alongside its Board of Trustees/Committees/Planning/Zoning
categories; a real village-government-hosted public session about its
own housing program, not off-mission content), and Easton town, CT
(Affordable Housing Committee, 2022-04-07, 53.5 min). All three probed
under 90 minutes -- no long-video defer question. Easton's video sits on
vimeo.com, a MULTI_GOV_HOSTS host, so it needs a real pin before the
WO-346 guard would let it queue; Grinnell and Hastings-on-Hudson are
single-tenant hosts (has_owner() already True) but get a pin too, same
convention as every other WO-349 finish."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from app.platforms.queue_probe import (  # noqa: E402
    TENANT_OVERRIDES_CSV,
    TIER3_QUEUE_FILE,
    append_queue_line,
    write_pin_row,
)

CANDIDATES = [
    dict(
        url="https://grinnell.granicus.com/MediaPlayer.php?view_id=1&clip_id=614",
        pin_host="grinnell.granicus.com",
        pin_match="",
        gov_id="us:place:1933105",
        evidence=(
            "Grinnell city, IA -- WO-349 rejected this real, identifiable "
            "meeting ('Regular City Council Session', 2024-12-02, "
            "20.8 min) as stale (the newest the listing walker could "
            "reach). WO-356 (2026-09-13): Ryan's rule is 'this is a "
            "historic archive after all' -- no freshness cutoff for a "
            "real meeting video. Queued."
        ),
    ),
    dict(
        url="https://hastingsonhudsonny.swagit.com/play/10102024-509",
        pin_host="hastingsonhudsonny.swagit.com",
        pin_match="",
        gov_id="us:place:3632710",
        evidence=(
            "Hastings-on-Hudson village, NY -- WO-349 rejected this real, "
            "identifiable meeting ('Information Session on the Plus One "
            "ADU Program', 2024-10-08, 32.3 min) as stale. WO-356 "
            "(2026-09-13) hand-checked on-mission status first (title "
            "reads as a topic, not a body): the video sits on the "
            "village's own official Swagit tenant "
            "(hastingsonhudsonny.swagit.com), whose own category nav "
            "carries Board of Trustees / Committees / Events / Planning / "
            "Programs / Zoning alongside it -- a real village-government-"
            "hosted public information session about its own housing "
            "program, on-mission. Ryan's 'historic archive' rule applies "
            "-- no freshness cutoff. Queued."
        ),
    ),
    dict(
        url="https://vimeo.com/697711522/afbcc0c15d",
        pin_host="vimeo.com",
        pin_match="697711522",
        gov_id="us:cousub:0912023890",
        evidence=(
            "Easton town, CT -- WO-349 rejected this real, identifiable "
            "meeting ('April 7th, 2022 - Affordable Housing Committee', "
            "2022-04-09, 53.5 min) as stale (46 months old). WO-356 "
            "(2026-09-13): Ryan's rule is 'this is a historic archive "
            "after all' -- no freshness cutoff for a real meeting video. "
            "vimeo.com is a MULTI_GOV_HOSTS shared host, so pinned to "
            "this one video id (bare numeric id -- the working match "
            "shape per _match_override()'s substring check against the "
            "URL path; the 'vimeo:<id>' shape used by some older rows "
            "does not actually match any real vimeo.com URL path and "
            "would silently never apply -- see BACKLOG.md entry this WO "
            "filed). Queued."
        ),
    ),
]


def main() -> None:
    for c in CANDIDATES:
        pinned = write_pin_row(
            host=c["pin_host"],
            match=c["pin_match"],
            gov_id=c["gov_id"],
            strength="fallback",
            source="wo356",
            evidence=c["evidence"],
            pins_path=TENANT_OVERRIDES_CSV,
        )
        queued = append_queue_line(c["url"], c["url"], queue_path=TIER3_QUEUE_FILE)
        print(f"{c['url']} -> pinned={pinned} queued={queued}")


if __name__ == "__main__":
    main()
