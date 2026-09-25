#!/usr/bin/env python3
"""WO-1058 (fixed WO-1060): match Meeting Finder's own "other government"
leads to a real government, the same way `scripts/hub_harvest.py`
(WO-1053) already matches a hub section -- name + state + body type, hub
region-state as a tie-break, a joint/special body always routed to
hand-read. Reuses that script's own matcher (`_match_place_text()`/
`_is_joint_or_special_body()`) rather than a second copy, per CLAUDE.md's
"one picking rule" framing for exactly this kind of shared logic.

WO-1060: a review of WO-1058's live output found the recorded lead
itself, not just the match step, was the problem -- of 9 "confident"
leads, all 9 were Galesburg IL's own meetings ("Galesburg, IL City
Council" mistaking its own state abbreviation "IL" for a different
place); of 144 hand-read rows, the dominant `named_place`s were bare
meeting-descriptor words ("regular" x70, "recessed ..." x27, "special"
x14) a too-loose extraction pattern mistook for a place. Fixed at the
source: `pick.describe_foreign_candidate()` (app/platforms/meeting_finder/
pick.py) now requires an explicit place-TYPE word, strips meeting/
procedural noise first, and never records a lead that's just the
SEARCHED government's own name/state resurfacing. This script re-derives
`named_place`/`state` from each lead's own `title` using that SAME
function -- rather than trusting a `named_place` already written by an
older run's code -- so re-running this script against an existing JSONL
picks up the fix without needing to re-run Meeting Finder itself. The
searched government's own name/state come from the JSONL row's own
`identity_expected_gov_id` (`government_for_id()`), when present.

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

from app.platforms.meeting_finder.models import Candidate  # noqa: E402
from app.platforms.meeting_finder.pick import describe_foreign_candidate  # noqa: E402
from app.utils.gov_registry import resolver  # noqa: E402
from app.utils.gov_registry.registry import government_for_id  # noqa: E402
from scripts.hub_harvest import (  # noqa: E402
    HubRow,
    _guessed_body_type,
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


_GOV_CACHE: Dict[str, Any] = {}


def _gov_for_id(gov_id: str):
    if not gov_id:
        return None
    if gov_id not in _GOV_CACHE:
        try:
            _GOV_CACHE[gov_id] = government_for_id(gov_id)
        except Exception:  # noqa: BLE001
            _GOV_CACHE[gov_id] = None
    return _GOV_CACHE[gov_id]


def load_leads(jsonl_path: Path) -> List[Dict[str, Any]]:
    """Every `VerdictRow.other_gov_leads` entry across one run's JSONL,
    deduped by `url`. WO-1060: each lead also carries the SEARCHED
    government's own `_gov_name`/`_gov_state` (from that row's own
    `identity_expected_gov_id`, when the registry has one) -- needed by
    `match_lead()` to re-derive the lead fresh from `title` via
    `pick.describe_foreign_candidate()`, the same function Meeting Finder
    itself calls live, rather than trusting a `named_place` an older run's
    (buggy) code may have already written."""
    seen_urls = set()
    leads: List[Dict[str, Any]] = []
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            gov = _gov_for_id(row.get("identity_expected_gov_id") or "")
            for lead in row.get("other_gov_leads") or []:
                url = lead.get("url")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                lead = dict(lead)
                lead["_gov_name"] = gov.gov_name if gov else None
                lead["_gov_state"] = (gov.state or None) if gov else None
                leads.append(lead)
    return leads


def match_lead(lead: Dict[str, Any], hubs: List[HubRow]) -> LeadMatch:
    title = lead.get("title") or ""
    hub_host = lead.get("hub_host") or ""
    hub_region_state = _hub_region_for_host(hubs, hub_host)
    gov_name = lead.get("_gov_name")
    gov_state = lead.get("_gov_state")

    def _row(
        *, matched=None, named_place="", body_words="", confidence: str, reason: str
    ) -> LeadMatch:
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
            named_place=lead.get("named_place") or "",
            body_words=", ".join(lead.get("body_words") or []),
            confidence="hand_read",
            reason="joint/special body -- needs a human",
        )

    # WO-1060: re-derive from `title` via the SAME function Meeting
    # Finder calls live, rather than trusting whatever `named_place` this
    # lead was already written with (that field is exactly what WO-1058's
    # calibration found unreliable -- see this script's own module
    # docstring). `describe_foreign_candidate()` returns `None` when the
    # title names no real place at all, or only the searched government's
    # own name/state -- both are "no lead", not "hand read".
    described = describe_foreign_candidate(
        Candidate(url=lead.get("url") or "", title=title, date=lead.get("date")),
        gov_name=gov_name,
        gov_state=gov_state,
    )
    if described is None:
        return _row(
            confidence="hand_read",
            reason="no real place name found in the lead's own title",
        )
    named_place = described["named_place"]
    place_type = described.get("place_type") or ""
    body_words = ", ".join(described["body_words"])

    # Rule 3 (WO-1060): the title's OWN state first, else the hub's
    # region, else the searched government's own state -- never "no
    # state" when the searched government has one.
    region_state = described.get("state") or hub_region_state or gov_state or ""

    body_type_hint = _guessed_body_type(title)
    # `_place_core()` (pick.py) already dropped the place-type word from
    # `named_place` ("Nassau County" -> "nassau") -- put a COUNTY name
    # back together for `_match_place_text()`'s own school-district
    # qualifier ("Nassau School District" doesn't resolve; "Nassau County
    # School District" does -- confirmed live building this WO), since
    # the real-world shape is "<County> County School District", not
    # "<County> School District".
    place_text = (
        f"{named_place} County"
        if body_type_hint == "school district" and place_type == "county"
        else named_place
    )
    match = _match_place_text(
        place_text, region_state, hub_host, body_type_hint=body_type_hint
    )
    if match.tier in (resolver.TIER_PINNED, resolver.TIER_REGISTRY):
        return _row(
            matched=match,
            named_place=named_place,
            body_words=body_words,
            confidence="confident",
            reason=f"exact name+state+type match ({match.tier})",
        )
    return _row(
        matched=match,
        named_place=named_place,
        body_words=body_words,
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
