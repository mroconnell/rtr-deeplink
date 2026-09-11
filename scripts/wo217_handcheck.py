"""WO-217 (2026-09-11): the shared hand-check hook, wired onto
`wo134_confirmed_hits_ingest.IDENTITY_CHECK_HOOK`, for both the Group 1
(has-alternate) and Group 2 (found-alternate) sweeps.

Preamble rule: "Hand-check every found video before it becomes a page or
a queue line. ... Use classify_video_hand_check() ... as the automatic
pre-filter, then actually read the title and channel yourself for every
find." This hook is the automatic pre-filter half -- it runs inside
`wo134_confirmed_hits_ingest.process_row()`, right after a hit resolves
real video content and before it is ingested or queued (see that
module's own IDENTITY_CHECK_HOOK comment for exactly where). It combines
two existing checks, same as `wo174_pipeline.py`'s own caller does:

1. `wo146_api_relist_sweep._looks_wrong_government()` -- a state/gov-kind/
   off-mission-entity mismatch read from the resolved jurisdiction/
   meeting_body/title text.
2. `wo174_pipeline.classify_video_hand_check()` -- a phrase-list check
   over the video's title plus its channel text (video_channel + the
   adapter's own jurisdiction guess), catching the two failure shapes
   Ryan named: Kind A (the channel belongs to another real public body)
   and Kind B (right channel, wrong video -- e.g. a swearing-in ceremony
   or a "why run for city council" video, not the deliberative meeting
   itself).

Every hit this hook sees (flagged or not) is logged to
`research/wo217_handcheck_log.csv` -- this is the "read the title and
channel yourself" record: after each foreground chunk, the agent running
this WO reads that log before starting the next chunk, the same
personal-review step WO-184's continuation did after the fact (this
hook does it before ingest instead, per this WO's stricter preamble). A
flagged Kind A additionally appends to `research/wo217_owner_bodies.csv`
(owner name, channel, video URL, gov_id if known) for a later mint pass,
and marks this government's own row `hand_check=kind_A` with a `wrong-
domain-mapping` reason so `coverage_alternates.NEVER_RETRY_REASONS`
skips it on a future run.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.wo146_api_relist_sweep import _looks_wrong_government  # noqa: E402
from scripts.wo174_pipeline import classify_video_hand_check  # noqa: E402

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
HANDCHECK_LOG_CSV = RESEARCH_DIR / "wo217_handcheck_log.csv"
OWNER_BODIES_CSV = RESEARCH_DIR / "wo217_owner_bodies.csv"

_LOG_FIELDS = [
    "gov_id",
    "name",
    "state",
    "gov_kind",
    "platform",
    "title",
    "channel_text",
    "video_url",
    "verdict",  # ok | kind_A | kind_B | state_or_kind_conflict
    "reason",
]
_OWNER_FIELDS = ["owner_name", "channel", "video_url", "gov_id", "note"]

# Filled in by the caller (wo217_group1_sweep.py / wo217_group2_sweep.py)
# per row, since IDENTITY_CHECK_HOOK's own signature (row, platform,
# result, final_seed, effective_title) doesn't carry gov_kind/state on
# `row` under the same keys wo152's hook used -- same convention (private
# `_wo217_*` keys stashed on the synthetic row before calling process_row).
_last_verdict: Optional[str] = None


def _append(path: Path, fields: list, data: dict) -> None:
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        if is_new:
            w.writeheader()
        w.writerow(data)


def get_last_verdict() -> Optional[str]:
    """The verdict ('ok' | 'kind_A' | 'kind_B' | 'state_or_kind_conflict')
    from the most recent hand_check_hook() call, for the caller to fold
    into its own report row (`hand_check` column) -- process_row() itself
    only sees the hook's return value (a mismatch string or None), not
    this finer classification."""
    return _last_verdict


def hand_check_hook(row, platform, result, final_seed, effective_title):
    global _last_verdict
    gov_id = row.get("_wo217_gov_id", "") or row.get("gov_id", "")
    name = row.get("_wo217_name", "")
    state = row.get("_wo217_state", "")
    gov_kind = row.get("_wo217_gov_kind", "municipality")

    channel_text = " ".join(
        filter(
            None,
            [
                (getattr(result, "video_channel", None) or "").lstrip("@"),
                result.jurisdiction or "",
            ],
        )
    )

    verdict = "ok"
    reason = ""
    mismatch = None

    conflict = _looks_wrong_government(
        {"state": state, "gov_kind": gov_kind},
        {
            "jurisdiction": result.jurisdiction or "",
            "meeting_body": getattr(result, "meeting_body", "") or "",
            "title": effective_title or "",
        },
    )
    if conflict:
        verdict = "state_or_kind_conflict"
        reason = conflict
        mismatch = conflict

    hc = classify_video_hand_check(effective_title, channel_text, name, gov_kind)
    if hc:
        kind, hc_reason = hc
        verdict = f"kind_{kind}"
        reason = hc_reason
        mismatch = f"hand-check-kind-{kind.lower()}: {hc_reason}"
        if kind == "A":
            _append(
                OWNER_BODIES_CSV,
                _OWNER_FIELDS,
                {
                    "owner_name": hc_reason,
                    "channel": (getattr(result, "video_channel", None) or ""),
                    "video_url": result.video_url or final_seed,
                    "gov_id": "",
                    "note": f"WO-217: flagged looking for {name}, {state}'s own "
                    f"video ({gov_id})",
                },
            )

    _append(
        HANDCHECK_LOG_CSV,
        _LOG_FIELDS,
        {
            "gov_id": gov_id,
            "name": name,
            "state": state,
            "gov_kind": gov_kind,
            "platform": platform,
            "title": effective_title or "",
            "channel_text": channel_text,
            "video_url": result.video_url or final_seed,
            "verdict": verdict,
            "reason": reason,
        },
    )
    _last_verdict = verdict
    return mismatch
