"""WO-286 apply step: queue the 3 real, hand-checked, genuinely-NEW
tier-3 candidates this WO's resolve pass found (`scripts/
wo286_resolve_report.csv` plus one manually-dug-in case, ci.benicia.
ca.us -- see this WO's BACKLOG_DONE entry) through `app/platforms.
queue_probe.finish_candidate()`, per this WO's own brief ("captions ->
page, no captions -> tier-3 through finish_candidate()"). None of the 67
real non-youtube weak-confirmations this WO covered had real captions
(segments) -- every real find was tier-3 -- so `scripts/bulk_ingest.py`
is never invoked this round (nothing to ingest as a page directly).

This script's FIRST real run queued six candidates, not three -- a fresh
meeting-inventory export taken AFTER that run (should have run before;
see the CANDIDATES list's own comment below) found three of them already
covered by an earlier sweep: Summit County UT and Benicia CA already had
real, transcribed pages (Benicia's own page 5557 is the EXACT SAME
granicus clip this WO's own manual dig-in "found" -- a straight
rediscovery), and Watchung NJ already had a different CivicClerk event
pending in the tier-3 queue for the same tenant. Those three queue
lines/pin were removed by hand and jurisdiction_coverage.csv corrected
(`wo286_fix_duplicates.py` in rtr-business) -- see the BACKLOG_DONE entry
for the full account. This file now lists only the three that were
genuinely new, so a future re-run reproduces the corrected outcome, not
the mistake.

Deliberately re-resolves each candidate fresh right before calling
finish_candidate() (passes `platform`+`meeting_url`, no stale `video_url`)
rather than reusing the resolve-phase's captured video_url -- confirmed
live building this WO that a BoxCast signed playlist URL expires fast
enough that a captured one is already dead by apply time (see
farmersvilletx.gov's own case in this WO's report).

One of the three gets a NEW single-tenant `tenant_overrides.csv` pin
(parkcounty.granicus.com) -- written directly here with a blank `match`
(the established convention for a genuinely single-tenant vendor
subdomain, e.g. the existing `summitcounty.granicus.com,,us:county:49043,
...` row) rather than through `queue_probe.write_pin_row()`, whose own
`if not host or not match or not gov_id: return False` guard refuses a
blank match unconditionally -- stricter than the registry loader itself,
which explicitly allows a blank match on a normal single-tenant host
(`app/utils/gov_registry/registry.py` lines ~154-156). emerycounty.com
(a bare state-portal file, not a per-tenant subdomain) and
farmersvilletx.gov (boxcast.tv is a MULTI_GOV_HOSTS entry -- this WO's
own brief: "never a Boxcast account") get none, by design.
"""

import asyncio
import csv
import sys
from pathlib import Path

sys.path.insert(0, ".")

from app.platforms import register_all_finders  # noqa: E402
from app.platforms import queue_probe  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
PINS_CSV = REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "tenant_overrides.csv"

CANDIDATES = [
    dict(
        domain="emerycounty.com",
        gov_id="us:county:49015",
        platform="utah_pmn",
        meeting_url="https://www.utah.gov/pmn/sitemap/notice/1100607.html",
        source_url="https://emery.utah.gov/home/department-directory/economic-development/economic-development-meetings/",
        jurisdiction="Emery County, Utah",
        title="Emery County Economic Development Board",
        pin=None,
    ),
    dict(
        domain="farmersvilletx.gov",
        gov_id="us:place:4825488",
        platform="boxcast",
        meeting_url=(
            "https://boxcast.tv/view/farmersville-community-development-"
            "corporation-fcdc-4b-meeting-ewh3fjbymcc64jcz0sja"
        ),
        source_url="https://www.farmersvilletx.com/meetings/recent?boards-commissions=71",
        jurisdiction="City of Farmersville, TX",
        title="Farmersville Community Development Corporation (FCDC 4B) Meeting",
        pin=None,  # boxcast.tv is a MULTI_GOV_HOSTS -- never pinned by account
    ),
    dict(
        domain="parkcounty.org",
        gov_id="us:county:30067",
        platform="granicus",
        meeting_url="https://parkcounty.granicus.com/MediaPlayer.php?view_id=1&clip_id=2806",
        source_url="https://www.parkcountymt.gov/Government-Departments/Commissioners/Commission-Enhanced-Agendas-Audio-and-Meeting-Minutes/",
        jurisdiction="Park County, MT",
        title="Planning and Zoning Commission Meeting",
        pin={"host": "parkcounty.granicus.com", "gov_id": "us:county:30067"},
    ),
    # Three more candidates this WO's resolve pass found --
    # summitcountytreasurerutah.gov (us:county:49043), watchungnj.gov
    # (us:place:3477600), ci.benicia.ca.us (us:place:0605290) -- are
    # DELIBERATELY not listed here. A post-hoc fresh meeting-inventory
    # export (run AFTER this script's first real pass -- should have run
    # BEFORE, per the standard sweep pattern) found all three already
    # covered: Summit County UT and Benicia CA already had real,
    # transcribed pages (Benicia's own page 5557 is the EXACT SAME
    # granicus clip_id=4819 this WO's manual dig-in "found" -- a straight
    # rediscovery), and Watchung NJ already had a pending tier-3 queue
    # entry for a different CivicClerk event on the same tenant. This
    # script's first real run queued all six, then removed the three
    # duplicate queue lines/pin and corrected jurisdiction_coverage.csv
    # for them by hand (`wo286_fix_duplicates.py` in rtr-business) -- see
    # this WO's BACKLOG_DONE entry for the full account. Left out here so
    # a future re-run of this script (idempotent for the three real ones
    # via `finish_candidate()`'s own already-queued check) can't
    # reintroduce them.
]


def write_single_tenant_pin(host: str, gov_id: str, evidence: str) -> bool:
    """Blank-match pin for a confirmed single-tenant vendor host -- see
    this module's own docstring for why `queue_probe.write_pin_row()`
    isn't used directly."""
    existing = set()
    if PINS_CSV.exists():
        with PINS_CSV.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing.add((row.get("tenant_host", ""), row.get("match", "")))
    if (host, "") in existing:
        print(f"  pin already exists for {host}, skipping")
        return False
    is_new = not PINS_CSV.exists()
    with PINS_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "tenant_host",
                "match",
                "gov_id",
                "strength",
                "source",
                "evidence",
            ],
            lineterminator="\n",
        )
        if is_new:
            writer.writeheader()
        writer.writerow(
            {
                "tenant_host": host,
                "match": "",
                "gov_id": gov_id,
                "strength": "fallback",
                "source": "wo286",
                "evidence": evidence,
            }
        )
    print(f"  wrote pin: {host} -> {gov_id}")
    return True


async def main():
    register_all_finders()
    for c in CANDIDATES:
        print(f"\n=== {c['domain']} ({c['gov_id']}) ===")
        outcome = await queue_probe.finish_candidate(
            c["meeting_url"],
            source_url=c["source_url"],
            platform=c["platform"],
            gov_id=c["gov_id"],
            jurisdiction=c["jurisdiction"],
            title=c["title"],
            pin=None,  # pins written separately below (blank-match convention)
            caller="wo286",
        )
        print(
            f"  action={outcome.action} queued={outcome.queued} "
            f"verdict={outcome.probe.verdict} duration={outcome.probe.duration_seconds}"
        )
        if outcome.action == "queued" and c["pin"]:
            write_single_tenant_pin(
                c["pin"]["host"],
                c["pin"]["gov_id"],
                evidence=f"{c['domain']} -- WO-286 confirmed tier-3, gov_id={c['gov_id']}",
            )


if __name__ == "__main__":
    asyncio.run(main())
