"""WO-292 (2026-09-12): school-district pilot -- builds the one-row-per-
government report (`research/wo292_report.csv`) that
`wo292_apply_to_jc.py` reads, from the three phase outputs
(`wo292_recon.jsonl`, `wo292_classified.csv`, `wo292_targeted.csv`).

Outcome precedence per government (first match wins):
  1. dns-unresolvable (phase 1's DNS gate)
  2. cloudflare-challenge-blocked (phase 1's homepage fetch hit a human
     gate)
  3. confirmed-video-platform-youtube -- a real name-matched YouTube/
     Vimeo platform confirmation (phase 3). Per this WO's brief ("Make
     no YouTube calls; collect channel leads for the drip"), NOTHING
     here is hand-verified beyond the title text a resolve() call
     already returned (3 governments -- see the WO-292 report's own
     "YouTube calls made" section) or is a bare channel link (55
     governments) -- both go to `wo292_youtube_leads.txt` for
     `scripts/youtube_drip.py`, not ingested by this script.
  4. confirmed-video-platform-other -- a real name-matched non-YouTube
     platform confirmation (phase 3), but the resolve-diagnostic pass
     (`wo292_resolve_diagnostic.py`, read-only) found no directly
     resolvable video -- every one of these needed a further drill-down
     this pilot didn't build (a hub/listing page, not a specific meeting
     URL); see BACKLOG.md.
  5. agenda-only (BoardDocs/Simbli) -- reported, never chased for video.
  6. no-candidate -- phase 2 found nothing at all (feeds no-platform-
     link-found).
  7. candidate-unconfirmed -- phase 2 found a candidate but phase 3
     never independently confirmed it (weak or absent by design --
     genuinely unresolved, not a reject).

Usage: .venv/bin/python scripts/wo292_build_report.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
RECON_JSONL = RESEARCH_DIR / "wo292_recon.jsonl"
CLASSIFIED_CSV = RESEARCH_DIR / "wo292_classified.csv"
TARGETED_CSV = RESEARCH_DIR / "wo292_targeted.csv"
REPORT_CSV = RESEARCH_DIR / "wo292_report.csv"

# Governments where a resolve() call already fetched real YouTube
# captions during this WO's phase-3 hand-check pass, before the "make no
# YouTube calls" instruction was caught -- see the WO-292 report/
# BACKLOG_DONE entry for the full explanation. Recorded here so the
# report is explicit about it rather than silently folding them into the
# ordinary channel-link bucket.
YOUTUBE_TOUCHED_GOV_IDS = {"us:sd:1808160", "us:sd:2618450", "us:sd:0606450"}


def log(msg: str) -> None:
    print(msg, flush=True)


def load_recon() -> dict:
    out = {}
    if RECON_JSONL.exists():
        with open(RECON_JSONL, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                out[r.get("domain", "")] = r
    return out


def load_classified() -> dict:
    out = {}
    if CLASSIFIED_CSV.exists():
        with open(CLASSIFIED_CSV, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out[r["gov_id"]] = r
    return out


def load_targeted() -> dict:
    """gov_id -> list of rows, in file order."""
    out: dict[str, list] = {}
    if TARGETED_CSV.exists():
        with open(TARGETED_CSV, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out.setdefault(r["gov_id"], []).append(r)
    return out


def is_youtube_channel_url(url: str) -> bool:
    return not ("watch?v=" in url or "youtu.be/" in url)


def main() -> None:
    recon_by_domain = load_recon()
    classified_by_gov = load_classified()
    targeted_by_gov = load_targeted()

    log(
        f"{len(recon_by_domain)} recon, {len(classified_by_gov)} classified, "
        f"{len(targeted_by_gov)} governments with targeted rows"
    )

    rows = []
    for gov_id, crow in classified_by_gov.items():
        domain = crow.get("domain", "")
        name = crow.get("name", "")
        state = crow.get("state", "")
        rec = recon_by_domain.get(domain, {})
        dns_gate = rec.get("dns_gate", "")
        access_mode = rec.get("access_mode", "")

        trow = None
        for r in targeted_by_gov.get(gov_id, []):
            if r.get("platform_confirmed"):
                trow = r
                break

        outcome = ""
        reject_reason = ""
        suspected_video_provider = ""
        suspected_calendar_provider = ""
        note = ""

        if dns_gate == "dns-unresolvable":
            outcome = "dns-unresolvable"
            reject_reason = "dns-unresolvable"
        elif access_mode == "cloudflare-challenge-blocked":
            outcome = "cloudflare-challenge-blocked"
            reject_reason = "cloudflare-challenge-blocked"
        elif trow and trow["platform_confirmed"] == "youtube":
            outcome = "confirmed-video-platform-youtube"
            suspected_video_provider = "youtube"
            if gov_id in YOUTUBE_TOUCHED_GOV_IDS:
                note = "resolve() already called (pre-instruction); title read, not ingested; see report"
            elif is_youtube_channel_url(trow["url"]):
                note = "channel link, drip lane"
            else:
                note = "single-video link, not resolved (no YouTube calls made)"
        elif trow:
            outcome = "confirmed-video-platform-other"
            suspected_video_provider = trow["platform_confirmed"]
            note = "resolve-diagnostic found no directly resolvable video; hub/listing page needs drill-down"
        elif crow.get("agenda_only_platform"):
            outcome = "agenda-only"
            reject_reason = "meeting-without-video"
            suspected_calendar_provider = crow["agenda_only_platform"]
        elif int(crow.get("n_candidates") or 0) == 0:
            outcome = "no-candidate"
            reject_reason = "no-platform-link-found"
        else:
            outcome = "candidate-unconfirmed"
            note = f"confidence={crow.get('confidence')}, n_candidates={crow.get('n_candidates')}, not independently confirmed"

        rows.append(
            {
                "gov_id": gov_id,
                "domain": domain,
                "name": name,
                "state": state,
                "dns_gate": dns_gate,
                "access_mode": access_mode,
                "confidence": crow.get("confidence", ""),
                "outcome": outcome,
                "reject_reason": reject_reason,
                "suspected_video_provider": suspected_video_provider,
                "suspected_calendar_provider": suspected_calendar_provider,
                "note": note,
            }
        )

    fieldnames = [
        "gov_id",
        "domain",
        "name",
        "state",
        "dns_gate",
        "access_mode",
        "confidence",
        "outcome",
        "reject_reason",
        "suspected_video_provider",
        "suspected_calendar_provider",
        "note",
    ]
    with open(REPORT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    log(f"wrote {REPORT_CSV} ({len(rows)} rows)")

    from collections import Counter

    outcome_counts = Counter(r["outcome"] for r in rows)
    log(f"outcome split: {dict(outcome_counts)}")


if __name__ == "__main__":
    main()
