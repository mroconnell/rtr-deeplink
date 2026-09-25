#!/usr/bin/env python3
"""WO-1058: match Meeting Finder's own "other government" leads to a real
government, the same way `scripts/hub_harvest.py` (WO-1053) already
matches a hub section -- name + state + body type, hub region-state as a
tie-break, a joint/special body always routed to hand-read. Reuses that
script's own matcher (`_match_place_text()`/`_extract_place_fragment()`/
`_is_joint_or_special_body()`) rather than a second copy, per CLAUDE.md's
"one picking rule" framing for exactly this kind of shared logic.

Where the leads come from: `pick.filter_candidates_to_government()`
(WO-1054, narrowed WO-1058) drops a candidate off a shared hub/account
whose title clearly names a DIFFERENT government -- real examples: College
Township PA's own Centre County C-NET TelVue token also lists "Borough of
State College - Council"; Nashwauk MN's own Iron Range TV Cablecast tenant
also lists "Cohasset City Council". Every one of those is a real, free
link-first lead for that OTHER government -- `runner.py` collects them
(regardless of whether the walk that found them ends in its OWN clean
find) into `VerdictRow.other_gov_leads`, and this script is the offline
step that turns them into a real ingest plan.

Dry run only -- reads one Meeting Finder run's own JSONL output
(`verdict.append_verdict()`'s twin file), dedupes leads by URL (the same
real lead can turn up more than once across different governments' walks
on the same shared hub), and writes two CSVs, same shape/spirit as
WO-1053's own `hub_harvest.py` output:

    other_gov_ingest_queue_plan.csv   confident name+state+type matches,
                                       filed under THAT government's own
                                       gov_id -- never the government whose
                                       walk happened to find it
    other_gov_hand_read.csv           everything else: a joint/special
                                       body, no place name found, or the
                                       resolver's own match wasn't
                                       confident

Never ingests, never writes `tenant_overrides.csv`, `jurisdiction_
coverage.csv`, or any ingest queue -- same read-only posture as
`hub_harvest.py` and Verdict itself (verdict.py's own docstring).

Usage:
    PYTHONPATH=. .venv/bin/python scripts/meeting_finder_other_gov_leads.py \\
        --in <run>.jsonl.csv.jsonl --out <dir>
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.utils.gov_registry import resolver  # noqa: E402
from scripts.hub_harvest import (  # noqa: E402
    HubRow,
    _extract_place_fragment,
    _is_joint_or_special_body,
    _match_place_text,
    load_hubs,
)


@dataclass
class LeadMatch:
    url: str
    title: str
    date: str
    named_place: str
    body_words: str
    hub_host: str
    matched_gov_id: str
    matched_gov_name: str
    confidence: str  # "confident" | "hand_read"
    reason: str


def _hub_region_for_host(hubs: List[HubRow], hub_host: str) -> str:
    """`regional_tv_hubs.csv`'s own `region_state` for whichever hub row
    this lead's `hub_host` belongs to -- the same tie-break `hub_harvest.
    py`'s own matcher already uses (`hub.region_state`), so a place name
    common to more than one state (there are real "Cohasset"s outside MN)
    isn't left to the resolver's own untenanted guess."""
    for hub in hubs:
        if urlparse(hub.url).netloc.lower() == (hub_host or "").lower():
            return hub.region_state
    return ""


def load_leads(jsonl_path: Path) -> List[Dict[str, Any]]:
    """Every `VerdictRow.other_gov_leads` entry across one run's JSONL,
    deduped by `url`."""
    seen_urls = set()
    leads: List[Dict[str, Any]] = []
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            for lead in row.get("other_gov_leads") or []:
                url = lead.get("url")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                leads.append(lead)
    return leads


def match_lead(lead: Dict[str, Any], hubs: List[HubRow]) -> LeadMatch:
    title = lead.get("title") or ""
    hub_host = lead.get("hub_host") or ""
    region_state = _hub_region_for_host(hubs, hub_host)
    body_words = ", ".join(lead.get("body_words") or [])
    named_place = lead.get("named_place") or ""

    def _row(*, matched=None, confidence: str, reason: str) -> LeadMatch:
        return LeadMatch(
            url=lead.get("url") or "",
            title=title,
            date=lead.get("date") or "",
            named_place=named_place,
            body_words=body_words,
            hub_host=hub_host,
            matched_gov_id=(matched.gov_id if matched else "") or "",
            matched_gov_name=(matched.gov_name if matched else "") or "",
            confidence=confidence,
            reason=reason,
        )

    # Rule 1 (same as hub_harvest.py): a joint/special body (a cable
    # board, a council of governments, a watershed commission...) is
    # never auto-matched to the county/town it happens to be named after
    # or hosted by.
    if _is_joint_or_special_body(title):
        return _row(
            confidence="hand_read",
            reason="joint/special body -- needs a human",
        )

    # `describe_foreign_candidate()`'s own `named_place` (pick.py) is
    # already a real place-type phrase ("state college", "cohasset") --
    # prefer it, and fall back to re-extracting a fragment from the title
    # only when it's missing (an older/foreign-format lead).
    place_fragment = named_place or _extract_place_fragment(title)
    if not place_fragment:
        return _row(
            confidence="hand_read",
            reason="no place name found in the lead's own title",
        )

    match = _match_place_text(place_fragment, region_state, hub_host)
    if match.tier in (resolver.TIER_PINNED, resolver.TIER_REGISTRY):
        return _row(
            matched=match,
            confidence="confident",
            reason=f"exact name+state+type match ({match.tier})",
        )
    return _row(
        matched=match,
        confidence="hand_read",
        reason=f"resolver tier={match.tier}: {match.evidence}",
    )


def run(jsonl_path: Path, out_dir: Path) -> List[LeadMatch]:
    hubs = load_hubs()
    leads = load_leads(jsonl_path)
    matches = [match_lead(lead, hubs) for lead in leads]

    out_dir.mkdir(parents=True, exist_ok=True)
    confident = [m for m in matches if m.confidence == "confident"]
    hand_read = [m for m in matches if m.confidence != "confident"]

    with (out_dir / "other_gov_ingest_queue_plan.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.writer(f)
        writer.writerow(
            ["url", "gov_id", "gov_name", "named_place", "title", "date", "hub_host"]
        )
        for m in confident:
            writer.writerow(
                [
                    m.url,
                    m.matched_gov_id,
                    m.matched_gov_name,
                    m.named_place,
                    m.title,
                    m.date,
                    m.hub_host,
                ]
            )

    with (out_dir / "other_gov_hand_read.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "url",
                "title",
                "date",
                "named_place",
                "body_words",
                "hub_host",
                "matched_gov_id",
                "matched_gov_name",
                "reason",
            ]
        )
        for m in hand_read:
            writer.writerow(
                [
                    m.url,
                    m.title,
                    m.date,
                    m.named_place,
                    m.body_words,
                    m.hub_host,
                    m.matched_gov_id,
                    m.matched_gov_name,
                    m.reason,
                ]
            )

    return matches


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--in", dest="jsonl_path", required=True, type=Path, help="Verdict JSONL"
    )
    parser.add_argument("--out", dest="out_dir", required=True, type=Path)
    args = parser.parse_args()
    matches = run(args.jsonl_path, args.out_dir)
    confident = sum(1 for m in matches if m.confidence == "confident")
    print(
        f"{len(matches)} deduped other-government leads: "
        f"{confident} confident (-> other_gov_ingest_queue_plan.csv), "
        f"{len(matches) - confident} hand_read (-> other_gov_hand_read.csv)"
    )


if __name__ == "__main__":
    main()
