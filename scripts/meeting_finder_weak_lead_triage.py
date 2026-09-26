"""WO-1111: pick which Meeting Finder weak leads are worth a hand-check.

A weak lead is a verdict row whose outcome is `video-low-confidence`, or
any row carrying `handcheck_lead=yes`. Hand-checks of the 2026-09-25/26
runs found about 98% of them were not meetings: homepage hero clips,
promos, vendor demos, and a few identical videos embedded on dozens of
unrelated government sites. This script is the triage step in front of
the hand-check -- nothing else. Meeting Finder itself never reads the
known-bad list (Ryan, 2026-09-26: "don't build it into the finder, just
the weak lead triage step").

Two filters, in order:

1. **Known non-meeting videos.** `--known-bad` points at
   rtr-business `research/known_non_meeting_videos.csv`: videos a
   hand-check already confirmed are not meetings. A lead whose video
   matches a row there is dropped (and counted).
2. **Ryan's duration bands** (2026-09-26): 70+ minutes is checked first,
   then 40-70, then 20-40; 8-20 only on request (`--include-8-20`); under
   8 minutes is never a meeting and is skipped. Unknown length (e.g. an
   embed-restricted Vimeo) is kept -- in the 2026-09-26 run both
   weak-lead approvals came from that group.

Output: a JSON case file for the hand-check, ordered by band, plus a
one-screen summary of what was kept and why the rest was skipped.

Usage:
    python scripts/meeting_finder_weak_lead_triage.py \\
        --verdicts-jsonl run/verdicts.csv.jsonl [--verdicts-jsonl ...] \\
        --known-bad ~/Documents/rtr-business/research/known_non_meeting_videos.csv \\
        --out run/weak_leads_to_check.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

CASE_FIELDS = [
    "input_url",
    "identity_expected_gov_id",
    "outcome",
    "tier",
    "platform",
    "result_url",
    "meeting_url",
    "meeting_title",
    "duration_seconds",
    "audio_only",
    "identity_verdict",
    "path",
    "low_confidence_reason",
    "handcheck_lead",
]

BAND_ORDER = ["70+", "40-70", "20-40", "unknown", "8-20"]

_VIMEO_RE = re.compile(r"vimeo\.com/(?:video/)?(\d+)")
_YOUTUBE_RE = re.compile(r"(?:[?&]v=|/embed/|youtu\.be/|/live/)([\w-]{11})")


def video_keys(url: str) -> Set[str]:
    """Every key a known-bad row could use for this URL: `vimeo:<id>`,
    `youtube:<id>`, `file:<basename>`, `url:<url without query>`."""
    if not url:
        return set()
    low = url.strip().lower()
    keys: Set[str] = set()
    m = _VIMEO_RE.search(low)
    if m:
        keys.add(f"vimeo:{m.group(1)}")
    m = _YOUTUBE_RE.search(url)
    if m:
        keys.add(f"youtube:{m.group(1)}")
    bare = low.split("?")[0].split("#")[0]
    keys.add(f"url:{bare}")
    base = bare.rstrip("/").rsplit("/", 1)[-1].replace("%20", " ")
    if base and "." in base:
        keys.add(f"file:{base}")
    return keys


def load_known_bad(path: Optional[Path]) -> Set[str]:
    if path is None:
        return set()
    lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.startswith("#")
    ]
    return {
        row["video_key"].strip().lower()
        for row in csv.DictReader(lines)
        if row.get("video_key")
    }


def band(duration_seconds) -> str:
    if not duration_seconds:
        return "unknown"
    minutes = float(duration_seconds) / 60
    if minutes >= 70:
        return "70+"
    if minutes >= 40:
        return "40-70"
    if minutes >= 20:
        return "20-40"
    if minutes >= 8:
        return "8-20"
    return "under-8"


def is_weak_lead(row: Dict) -> bool:
    return row.get("outcome") == "video-low-confidence" or (
        bool(row.get("outcome")) and row.get("handcheck_lead") == "yes"
    )


def lead_urls(row: Dict) -> List[str]:
    return [u for u in (row.get("meeting_url"), row.get("result_url")) if u]


def triage(rows: Iterable[Dict], known_bad: Set[str], include_8_20: bool = False):
    kept: List[Dict] = []
    skipped = Counter()
    for row in rows:
        if not is_weak_lead(row):
            continue
        if any(video_keys(u) & known_bad for u in lead_urls(row)):
            skipped["known non-meeting video"] += 1
            continue
        b = band(row.get("duration_seconds"))
        if b == "under-8":
            skipped["under 8 minutes"] += 1
            continue
        if b == "8-20" and not include_8_20:
            skipped["8-20 minutes (not requested)"] += 1
            continue
        case = {k: row.get(k) for k in CASE_FIELDS}
        case["band"] = b
        kept.append(case)
    kept.sort(key=lambda c: BAND_ORDER.index(c["band"]))
    return kept, skipped


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--verdicts-jsonl", action="append", required=True, type=Path)
    ap.add_argument(
        "--known-bad", type=Path, default=None, help="known_non_meeting_videos.csv"
    )
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument(
        "--include-8-20", action="store_true", help="also keep 8-20 minute leads"
    )
    args = ap.parse_args(argv)

    rows: List[Dict] = []
    for path in args.verdicts_jsonl:
        rows.extend(
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    kept, skipped = triage(rows, load_known_bad(args.known_bad), args.include_8_20)
    args.out.write_text(json.dumps(kept, indent=0), encoding="utf-8")

    by_band = Counter(c["band"] for c in kept)
    print(f"weak leads kept for hand-check: {len(kept)}")
    for b in BAND_ORDER:
        if by_band[b]:
            print(f"  {b}: {by_band[b]}")
    print(f"skipped: {sum(skipped.values())}")
    for reason, n in skipped.most_common():
        print(f"  {reason}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
