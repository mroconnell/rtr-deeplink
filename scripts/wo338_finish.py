"""WO-338 (2026-09-13): builds `research/wo338_final_classification.csv`
-- one row per government in the 2,825-row population, with the tier
(Ryan's 1-4 vocabulary) and a taxonomy-shaped reject_reason, combining:

  - `wo338_verify.csv` (verify_hub() results for the 623 governments
    phase 3 confirmed a platform for), with this WO's own hand-check
    overrides applied (HAND_OVERRIDES below -- see this WO's
    BACKLOG_DONE entry for the full per-government reasoning: 11 of the
    21 tier 1-3 verify_hub findings were wrong on a hand read --
    not-a-meeting direct-file links, two wrong-governing-body matches,
    one Zoom-join-link-as-video, one non-canonical consolidated-gov row
    already covered elsewhere -- leaving 4 real confirmed governments
    plus 5 YouTube leads).
  - `wo338_report.csv` (phase 1-3 outcome) for the 2,202 governments with
    no confirmed platform at all, mapped to the access/content-class
    taxonomy.

`should_apply` is True only when the tier is 1-3, or the derived
reject_reason genuinely differs from the population row's own
`prior_reject_reason` -- per the WO-337/338 addendum's "Research rows:
only where the tier is 1-3 or the verdict changes." An inconclusive
verify_hub verdict (resolve_error/fetch_failed -- an access-class hiccup
on an otherwise-real platform, not a content verdict) is never applied:
the prior finding stands until a real re-check confirms or overturns it.

Usage:
    .venv/bin/python scripts/wo338_finish.py
"""

from __future__ import annotations

import csv
from pathlib import Path

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
POPULATION_CSV = RESEARCH_DIR / "wo338_population.csv"
VERIFY_CSV = RESEARCH_DIR / "wo338_verify.csv"
REPORT_CSV = RESEARCH_DIR / "wo338_report.csv"
FINAL_CSV = RESEARCH_DIR / "wo338_final_classification.csv"

# Real ingested/queued governments (already applied directly to the
# Archive + tier-3 queue by hand during this WO -- see the BACKLOG_DONE
# entry). Their jc.csv row needs transcribed/queued fields, not just
# reject_reason, so they're handled separately from the generic taxonomy
# mapping below.
REAL_TIER1_INGESTED = {
    "ca:csd:5901006",  # Sparwood, BC -- civicweb/vimeo, 1614 real caption segments
}
REAL_TIER3_QUEUED = {
    "us:place:2747690",  # Oak Grove city, MN -- granicus, 29.1min Council Work Session
    "us:cousub:0911012270",  # Canton town, CT -- direct S3 file, Board of Finance
    "us:sd:0611280",  # Dixon Unified School District, CA -- granicus
}

# Hand-check overrides: verify_hub()'s own tier 1-3 verdict for these 21
# governments was checked by hand (title/context read, never a YouTube
# fetch) and 11 were wrong. `tier` is the CORRECTED tier ('' for none),
# `note` is the reasoning kept for the report/BACKLOG_DONE entry.
HAND_OVERRIDES = {
    "wspmn.gov": (
        "",
        "wrong body: Granicus clip resolved to 'Mendota Heights Natural "
        "Resources Commission' via the shared townsquaretv tenant, not "
        "West St Paul's own meeting -- not re-searched within budget",
    ),
    "jodaviesscountyil.gov": (
        "4",
        "CivicClerk resolve() returned a Zoom join link "
        "(us06web.zoom.us/j/...) as video_url, not a saved recording -- "
        "same gap WO-325 already flagged on this county. The meeting "
        "itself ('Joint Committee Budget Review: Law & Courts with "
        "Finance') is real, so tier 4 stands, not tier 3.",
    ),
    "salisburyct.us": (
        "",
        "homepage direct-file link is a First Selectman storm-update "
        "address, not a meeting recording",
    ),
    "geistownborough.com": (
        "",
        "homepage direct-file link is a welcome/promo video "
        "('HELLO GEISTOWN'), not a meeting recording",
    ),
    "historicsumpter.com": (
        "",
        "homepage direct-file link is a historical dredge documentary, "
        "not a meeting recording",
    ),
    "taghkanic.gov": (
        "",
        "homepage direct-file links are nature/community videos "
        "('Planting Activities', 'Forest Overview'), not meeting "
        "recordings",
    ),
    "townofkirkwood.gov": (
        "",
        "homepage direct-file link is a generic town video with no "
        "meeting-specific context ('Download the video')",
    ),
    "lemon-township.org": (
        "",
        "wrong body (Kind A): homepage links to Butler County OH's own "
        "site; the walk found Butler County's real Board of "
        "Commissioners meeting, not Lemon Township's own -- Butler "
        "County (us:county:39017) already has real transcribed coverage "
        "under its own tenant, nothing to mint",
    ),
    "alamosacounty.org": (
        "",
        "AgendaCenter walk found a generically-named ('September 9 "
        "2026') Google Drive file with no recovered meeting-specific "
        "title; not confident enough to confirm as a real meeting "
        "recording",
    ),
    "www.oshtemo.org": (
        "",
        "TelVue resolve() returned a perpetual live-channel stream "
        "('PMN Three - LIVE'), not one specific completed meeting "
        "recording",
    ),
    "www.cranfordnj.org": (
        "",
        "TelVue resolve() returned 'Cranford TV-35 Live Stream', a live "
        "channel feed, not one specific completed meeting recording",
    ),
    "augustaga.gov": (
        "",
        "us:county:13245 is a non-canonical id for the Augusta-Richmond "
        "County Consolidated Government (canonical us:place:1304204); "
        "this exact gov_id is already covered (reject_reason="
        "video-no-captions-queued, queued=true, a different real "
        "YouTube video) -- one meeting per government, not applied",
    ),
}

# Never applied at all, regardless of tier: the government is already
# covered under this exact gov_id (a different real finding), so
# nothing here should touch its jc.csv row -- "one meeting per
# government", not a verdict to overwrite with a weaker one.
SKIP_DOMAINS = {"augustaga.gov"}

YOUTUBE_LEAD_DOMAINS = {
    "scottcounty.in.gov",
    "cityofspringtown.com",
    "stearnscountymn.gov",
    "slrd.bc.ca",
    "qathet.ca",
}

TIER_TO_REASON = {
    "4": "meeting-without-video",
}


def load_csv_by_key(path: Path, key: str) -> dict:
    out = {}
    if not path.exists():
        return out
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out[row.get(key, "")] = row
    return out


def main() -> None:
    with open(POPULATION_CSV, newline="", encoding="utf-8") as f:
        population = list(csv.DictReader(f))
    verify = load_csv_by_key(VERIFY_CSV, "domain")
    report = load_csv_by_key(REPORT_CSV, "domain")

    out_rows = []
    tier_counts = {}
    apply_count = 0
    youtube_leads = []

    for row in population:
        domain = row["domain"]
        gov_id = row["gov_id"]
        prior = row.get("prior_reject_reason", "")

        vrow = verify.get(domain)
        tier = ""
        reject_reason = ""
        verdict_note = ""
        confident = False

        if gov_id in REAL_TIER1_INGESTED:
            tier = "1"
            reject_reason = ""  # transcribed=True, blank reject_reason
            confident = True
            verdict_note = "ingested (real captions)"
        elif gov_id in REAL_TIER3_QUEUED:
            tier = "3"
            reject_reason = "video-no-captions-queued"
            confident = True
            verdict_note = "queued to tier-3 auto-transcription"
        elif domain in YOUTUBE_LEAD_DOMAINS:
            tier = "2"
            reject_reason = ""  # not applied -- lead only, see leads file
            confident = False
            verdict_note = "youtube_lead -- appended to youtube_channel_leads.csv, not applied to jc.csv"
            youtube_leads.append(domain)
        elif domain in HAND_OVERRIDES:
            new_tier, note = HAND_OVERRIDES[domain]
            tier = new_tier
            verdict_note = f"hand-check override: {note}"
            if tier == "4":
                reject_reason = "meeting-without-video"
                confident = True
            else:
                # Downgraded to "no confirmed real meeting" -- same
                # taxonomy bucket as an empty/no-walker verify result.
                reject_reason = "no-meeting-nor-video"
                confident = True
        elif vrow is not None:
            tier = vrow.get("tier", "")
            verdict = vrow.get("verdict", "")
            if tier == "4":
                # A real listing/meeting was actually walked and found --
                # unambiguously stronger than any prior finding (finding
                # something is always real positive evidence), safe to
                # apply as an upgrade even over an existing
                # meeting-without-video (this can still record a NEWER
                # specific meeting) or no-meeting-nor-video prior.
                reject_reason = "meeting-without-video"
                confident = True
            elif verdict in ("resolved_empty", "empty_listing"):
                # NOT applied, on purpose, even though this looks like a
                # legitimate "walked and found nothing" content
                # re-observation. Checked live for this WO's own 105
                # would-be downgrades from meeting-without-video: 16 were
                # townhallstreams and 1 was civicclerk/escribe each --
                # platforms the WO-337/338 addendum explicitly lists as
                # "still hand-step" (no real listing walker yet), where
                # this verdict just reflects the walker's own lack of
                # support, not a real absence of a meeting. The other
                # ~85 (civicweb/utah_pmn/civicplus/iqm2/...) can't be
                # told apart from those without a per-platform, per-row
                # hand check this WO's budget doesn't cover -- so, per
                # the standing guard ("an access/no-signal result never
                # overwrites an already-correct content-class finding"),
                # none of them are applied. Recorded in verdict_note for
                # a future WO with budget to hand-check platform by
                # platform.
                reject_reason = ""
                confident = False
            else:
                # resolve_error / fetch_failed / exception -- an access
                # hiccup on an otherwise-real platform, not a content
                # verdict. Never applied.
                reject_reason = ""
                confident = False
            verdict_note = f"verify_hub: {verdict}"
        else:
            # No phase-3-confirmed platform this run (no verify.csv row
            # at all -- verify_hub was never even called). Every row in
            # this WO's population already carries a content-class prior
            # (meeting-without-video or no-meeting-nor-video, by
            # construction of the population filter) -- per the
            # standing guard ("an access/no-signal result never
            # overwrites an already-correct content-class finding",
            # `wo283_apply_to_jc.py`'s own WO-226 reference), failing to
            # RE-confirm a platform this run is never itself grounds to
            # downgrade that prior finding to no-platform-link-found or
            # an access-class reason. Left unchanged; the report outcome
            # is recorded in verdict_note for visibility only.
            rrow = report.get(domain, {})
            outcome = rrow.get("outcome", "")
            reject_reason = ""
            confident = False
            verdict_note = (
                f"no platform reconfirmed this run (report outcome: "
                f"{outcome or 'unknown'}) -- prior finding left unchanged "
                f"per the access/no-signal guard"
            )

        should_apply = confident and (tier in ("1", "3") or reject_reason != prior)
        # tier 2 (youtube lead) and non-applying rows never touch jc.csv
        if tier == "2":
            should_apply = False
        if domain in SKIP_DOMAINS:
            should_apply = False

        if should_apply:
            apply_count += 1

        tier_counts[tier or "none"] = tier_counts.get(tier or "none", 0) + 1

        out_rows.append(
            {
                "domain": domain,
                "gov_id": gov_id,
                "name": row.get("name", ""),
                "state": row.get("state", ""),
                "tier": tier,
                "prior_reject_reason": prior,
                "new_reject_reason": reject_reason,
                "should_apply": should_apply,
                "verdict_note": verdict_note,
            }
        )

    with open(FINAL_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "domain",
                "gov_id",
                "name",
                "state",
                "tier",
                "prior_reject_reason",
                "new_reject_reason",
                "should_apply",
                "verdict_note",
            ],
            lineterminator="\n",
        )
        w.writeheader()
        w.writerows(out_rows)

    print(f"wrote {FINAL_CSV} ({len(out_rows)} rows)")
    print("tier counts:", tier_counts)
    print(f"should_apply=True: {apply_count}")
    print(f"youtube leads to append: {len(youtube_leads)} ({youtube_leads})")


if __name__ == "__main__":
    main()
