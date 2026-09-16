#!/usr/bin/env python3
"""WO-352: classify chunk-1's verify_hub() results (research/wo352_verify.csv)
into a should_apply/reject_reason table, per the WO-337/338 addendum's rule
("Research rows: only where the tier is 1-3 or the verdict changes") and
this WO's own brief ("never touch rows that are not yours" / hand-read gate
cautions this weekend).

Verdict -> reject_reason mapping (tier is verify_hub()'s own, tier='' means
meeting_found=False):
  tier 4                              -> meeting-without-video
  tier '' , verdict=no_platform_detected -> no-platform-link-found
  tier '' , any other real completed verdict (resolved_empty,
            generic_link_scan_no_video, resolved_no_video,
            listing_walked_no_video, no_video_in_listing, resolved) with
            meeting_found=False       -> no-meeting-nor-video
  tier '' , verdict in {fetch_failed, resolve_error, exception} -> NOT
            APPLIED (inconclusive -- an access hiccup, not a content
            verdict; prior finding stands)
  tier 1/2/3 -> handled by hand (this WO's own ingest/queue/lead steps),
            never auto-applied here as a plain reject_reason row

HAND_OVERRIDES below records this chunk's own hand-read verdicts on every
tier 1-3 candidate (6 of 7 real videos found were not real meeting
footage or were already covered under another gov_id -- see BACKLOG_DONE
entry), same shape as wo338_finish.py's HAND_OVERRIDES.

Usage:
    .venv/bin/python scripts/wo352_finish.py
"""

from __future__ import annotations

import csv
from pathlib import Path

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
POPULATION_CSV = RESEARCH_DIR / "wo352_population.csv"
VERIFY_CSV = RESEARCH_DIR / "wo352_verify.csv"
FINAL_CSV = RESEARCH_DIR / "wo352_final_classification.csv"

INCONCLUSIVE_VERDICTS = {"fetch_failed", "resolve_error", "exception"}

# Hand-read verdicts on chunk 1's 7 tier 1-3 verify_hub candidates
# (2026-09-13/14). See this WO's BACKLOG_DONE entry for the full
# per-government reasoning.
HAND_OVERRIDES = {
    "us:county:04003": (  # Cochise County AZ -- YouTube lead
        "2",
        "youtube_lead",
        "tier 2 stands: verify_hub found a YouTube embed via the "
        "CivicPlus hub's listing walk, never fetched per rule -- "
        "recorded as a single_video lead in youtube_channel_leads.csv, "
        "not ingested/queued",
    ),
    "us:county:23031": (  # York County ME -- duplicate of York town ME
        "",
        "already-covered-other-id",
        "the townhallstreams.com location_id=77 candidate (id=74303, "
        "2026-07-28 Budget Committee) is real, but this domain "
        "(www.yorkmaine.org) is a non-canonical duplicate row for York "
        "town ME (us:cousub:2303187985), which WO-345 already pinned "
        "and queued the SAME location_id under a different meeting "
        "(id=75043). One meeting per government -- not applied under "
        "this gov_id.",
    ),
    "us:county:08003": (  # Alamosa County CO -- real content, probe failed
        "",
        "candidate-not-confirmed",
        "AgendaCenter 'Board of County Commissioners Agenda 9-9' entry "
        "(2026-09-09) links a real, dated, governing-body-labelled Drive "
        "file (aria-label names 'Board of County Commissioners' "
        "explicitly, stronger context than WO-338's own earlier "
        "hand-check of this same government found) -- but ffprobe could "
        "not read a duration from Drive's resolved download URL "
        "(interstitial/confirm-page response, not the real stream). Not "
        "queued: a real probe failure, not a hand-read rejection.",
    ),
    "us:place:1884752": (  # Winchester city IN
        "",
        "no-meeting-nor-video",
        "resolve() found a homepage <video loop autoplay muted> hero "
        "banner ('cityofwinchesterspeedway.mp4'), confirmed via the "
        "page's own <video> tag -- decorative, not a meeting recording",
    ),
    "us:place:0174688": (  # Tallassee city AL
        "",
        "no-meeting-nor-video",
        "resolve() found a homepage <video loop autoplay muted> hero "
        "banner ('homebanner.mp4') -- decorative, not a meeting "
        "recording",
    ),
    "us:county:48169": (  # Garza County TX
        "",
        "no-meeting-nor-video",
        "resolve() found a Google Drive file titled "
        "'2023.10.23_Pavilion_Flythrough.MP4' (confirmed via the Drive "
        "share page's own title) -- a drone flythrough video, not a "
        "meeting recording",
    ),
    "us:place:4521265": (  # Duncan town SC
        "",
        "no-meeting-nor-video",
        "resolve() found a homepage <video autoplay muted loop "
        "playsinline> hero banner ('Duncan3.mp4') -- decorative, not a "
        "meeting recording",
    ),
    "us:place:4283928": (  # West Reading borough PA
        "",
        "no-meeting-nor-video",
        "resolve() found a homepage <video loop autoplay muted> hero "
        "banner ('WRB-Banner-Video.mp4') -- decorative, not a meeting "
        "recording",
    ),
}


def load_population() -> dict:
    pop = {}
    with open(POPULATION_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pop[row["gov_id"]] = row
    return pop


def load_verify() -> list[dict]:
    with open(VERIFY_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def classify(row: dict, pop: dict) -> tuple[str, str, bool, str]:
    """Returns (tier, reject_reason, should_apply, note)."""
    gov_id = row["gov_id"]
    if gov_id in HAND_OVERRIDES:
        tier, reject_reason, note = HAND_OVERRIDES[gov_id]
        should_apply = tier not in ("1", "2", "3") and reject_reason not in (
            "already-covered-other-id",
            "candidate-not-confirmed",
        )
        return tier, reject_reason, should_apply, note

    tier = row["tier"]
    verdict = row["verdict"]
    prior = pop.get(gov_id, {}).get("prior_reject_reason", "")
    if tier == "4":
        return "4", "meeting-without-video", True, "verify_hub: meeting_found, no video"
    if tier in ("1", "2", "3"):
        # Not expected here (all real tier 1-3 candidates in chunk 1 are
        # in HAND_OVERRIDES above) -- flagged, not silently applied.
        return (
            tier,
            "",
            False,
            f"tier {tier} candidate with no hand-check override on file",
        )
    # tier == ''
    if verdict in INCONCLUSIVE_VERDICTS:
        return "", "", False, f"verify_hub: {verdict} (inconclusive, not applied)"
    if verdict == "no_platform_detected":
        if prior and prior != "no-platform-link-found":
            # WO-352 finding: this chunk's re-verification falls back to
            # a bare-homepage fetch when wo338_targeted.csv has no
            # platform_confirmed row for the domain (most of this
            # population). A bare-homepage miss is weaker evidence than
            # whatever earlier sweep originally confirmed a platform on
            # this government (prior_reject_reason already implies a
            # platform WAS reached) -- never downgrade a stronger prior
            # finding to "no-platform-link-found" on that weaker basis.
            # Treated as inconclusive, same as an access-class hiccup.
            return (
                "",
                "",
                False,
                f"verify_hub: no_platform_detected via bare-homepage fallback, "
                f"but prior_reject_reason={prior!r} implies a platform was "
                f"already confirmed once -- not downgraded (inconclusive)",
            )
        return "", "no-platform-link-found", True, "verify_hub: no platform link found"
    return "", "no-meeting-nor-video", True, f"verify_hub: {verdict}"


def main():
    pop = load_population()
    verify_rows = load_verify()
    out_rows = []
    for row in verify_rows:
        gov_id = row["gov_id"]
        prow = pop.get(gov_id, {})
        prior = prow.get("prior_reject_reason", "")
        tier, reject_reason, should_apply, note = classify(row, pop)
        changed = reject_reason != "" and reject_reason != prior
        out_rows.append(
            {
                "domain": row["domain"],
                "gov_id": gov_id,
                "name": row["name"],
                "state": row["state"],
                "population": row["population"],
                "tier": tier,
                "prior_reject_reason": prior,
                "new_reject_reason": reject_reason,
                "should_apply": should_apply and changed,
                "note": note,
                "meeting_url": row["meeting_url"],
                "resolved_platform": row["resolved_platform"],
            }
        )

    write_header = not FINAL_CSV.exists()
    with open(FINAL_CSV, "a", newline="", encoding="utf-8") as f:
        fieldnames = list(out_rows[0].keys()) if out_rows else []
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header and fieldnames:
            w.writeheader()
        for row in out_rows:
            w.writerow(row)

    n_apply = sum(1 for r in out_rows if r["should_apply"])
    print(
        f"{len(out_rows)} rows classified, {n_apply} should_apply=True, written to {FINAL_CSV}"
    )


if __name__ == "__main__":
    main()
