"""WO-912/WO-913 (2026-09-20): turn the hand-confirmed YouTube finds into
`youtube_channel_leads.csv` rows for the drip Mac's hand-read lane.

YouTube is fetched only by the drip Mac (CLAUDE.md, `docs/YOUTUBE_DRIP_RUNBOOK.md`),
so a YouTube find from a sweep on any other machine is never resolved here:
it becomes a LEAD. `research/youtube_channel_leads.csv` is the ONE list that
lane reads (`verified=false` until a person reads the channel and confirms it
is the government's own meeting source, name AND type). The file's owner
commits it, so this script does not edit it: it writes
`wo912_leads_to_add.csv` / `wo913_leads_to_add.csv` (same columns), one per
work order, for the owner to append.

Which finds: rows of each WO's `*_handcheck.csv` where a person read the
government's OWN page and marked the link `right_gov` or `right_meeting` with
`action=lead` on a YouTube URL. Never a `wrong_org`, `not_meeting` or
`cant_tell` row. Plus any hand-added leads in `<wo>_manual_leads.csv`
(columns: youtube_url, gov_id, note, optional kind), for a YouTube URL found
some way other than a report row (read off an ingested page, or a playlist,
which is neither a channel nor a single video: put `playlist` in `kind` and it
is written as such, deduped on its list id).

Dedupe, against the file as COMMITTED at HEAD (not the working tree, which
another session may be mid-edit on): a lead is dropped when the same channel
or video is already listed, whichever government it is filed under. URLs are
compared in a normalised form -- scheme, `www.`/`m.`, tracking parameters and
a trailing `/featured`/`/streams` removed; `@handle`, `/c/name`, `/user/name`
and `/channel/<id>` kept in SEPARATE namespaces (an `@x` and a `/user/x` are
usually one channel but not always, and wrongly dropping a lead loses
information while a duplicate row costs nothing). The tally also says how many
kept leads are for governments that already have other lead rows.

Usage:
    python3 scripts/wo912_wo913_make_leads.py
"""

from __future__ import annotations

import csv
import io
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import parse_qs, urlparse

csv.field_size_limit(sys.maxsize)

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
BUSINESS_REPO = RESEARCH_DIR.parent
LEADS_AT_HEAD = "research/youtube_channel_leads.csv"
JC_CSV = RESEARCH_DIR / "jurisdiction_coverage.csv"

FIELDS = [
    "channel_url",
    "gov_id",
    "government",
    "state",
    "source_wo",
    "kind",
    "verified",
    "note",
]
WOS = ("wo912", "wo913")
# First path segments that are YouTube pages, not a channel's custom name. A
# Short is a clip, never a meeting, so it is not a lead either.
_NOT_A_CHANNEL_NAME = {
    "about",
    "account",
    "embed",
    "feed",
    "gaming",
    "hashtag",
    "live",
    "playlist",
    "premium",
    "results",
    "shorts",
    "signin",
    "t",
    "watch",
}
LEAD_VERDICTS = {"right_gov", "right_meeting"}


def normalise_youtube_url(url: str) -> tuple[str, str, str] | None:
    """(kind, dedupe key, clean URL) for a YouTube channel or video URL, or
    None when it is neither (a bare youtube.com home page, a search, a login)."""
    parsed = urlparse((url or "").strip())
    host = parsed.netloc.lower().removeprefix("www.").removeprefix("m.")
    parts = [p for p in parsed.path.strip().split("/") if p]
    if host == "youtu.be" and parts:
        return (
            "single_video",
            f"video/{parts[0]}",
            f"https://www.youtube.com/watch?v={parts[0]}",
        )
    if not (host == "youtube.com" or host.endswith("youtube-nocookie.com")):
        return None
    if parts[:1] == ["watch"]:
        vid = (parse_qs(parsed.query).get("v") or [""])[0].split("?")[0]
        if vid:
            return (
                "single_video",
                f"video/{vid}",
                f"https://www.youtube.com/watch?v={vid}",
            )
        return None
    if parts[:1] == ["embed"] and len(parts) > 1 and len(parts[1]) >= 11:
        vid = parts[1][:11]
        return "single_video", f"video/{vid}", f"https://www.youtube.com/watch?v={vid}"
    if parts[:1] == ["channel"] and len(parts) > 1:
        return (
            "channel",
            f"channel/{parts[1]}",
            f"https://www.youtube.com/channel/{parts[1]}",
        )
    if parts and parts[0].startswith("@"):
        return (
            "channel",
            f"@{parts[0][1:].lower()}",
            f"https://www.youtube.com/{parts[0]}",
        )
    if parts[:1] in (["c"], ["user"]) and len(parts) > 1:
        return (
            "channel",
            f"{parts[0]}/{parts[1].lower()}",
            f"https://www.youtube.com/{parts[0]}/{parts[1]}",
        )
    if parts[:1] == ["live"] and len(parts) > 1:
        return (
            "single_video",
            f"video/{parts[1]}",
            f"https://www.youtube.com/watch?v={parts[1]}",
        )
    if len(parts) == 1 and parts[0] not in _NOT_A_CHANNEL_NAME:
        # legacy bare custom URL, e.g. youtube.com/cityofmccall
        return "channel", f"c/{parts[0].lower()}", f"https://www.youtube.com/{parts[0]}"
    return None


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if None not in r.values()]


def leads_at_head() -> list[dict]:
    out = subprocess.run(
        ["git", "-C", str(BUSINESS_REPO), "show", f"HEAD:{LEADS_AT_HEAD}"],
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    lines = [line for line in out.splitlines() if not line.startswith("#")]
    return list(csv.DictReader(io.StringIO("\n".join(lines))))


def state_names() -> dict[str, str]:
    """gov_id -> the full state/province name the leads file uses (the first
    non-blank `state_or_province` across the government's research rows)."""
    names: dict[str, str] = {}
    with JC_CSV.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            gid = (r.get("gov_id") or "").strip()
            st = (r.get("state_or_province") or "").strip()
            if gid and st and gid not in names:
                names[gid] = st
    return names


def candidate_leads(wo: str) -> list[dict]:
    """Raw lead candidates for one work order, before dedupe."""
    out: list[dict] = []
    for hc in _rows(RESEARCH_DIR / f"{wo}_handcheck.csv"):
        if hc["action"] != "lead" or hc["verdict"] not in LEAD_VERDICTS:
            continue
        out.append(
            {
                "url": hc["hit_url"],
                "gov_id": hc["gov_id"],
                "name": hc["name"],
                "note": hc["basis"],
            }
        )
    return out + _manual(wo)


def _manual(wo: str) -> list[dict]:
    names = {
        r["gov_id"]: r["name"] for r in _rows(RESEARCH_DIR / f"{wo}_handcheck.csv")
    }
    out = []
    for r in _rows(RESEARCH_DIR / f"{wo}_manual_leads.csv"):
        out.append(
            {
                "url": r["youtube_url"],
                "gov_id": r["gov_id"],
                "name": r.get("name") or names.get(r["gov_id"], ""),
                "note": r["note"],
                "kind": (r.get("kind") or "").strip(),
            }
        )
    return out


def build(
    wo: str, head: list[dict], states: dict[str, str]
) -> tuple[list[dict], Counter]:
    seen: dict[str, str] = {}  # dedupe key -> gov_id, HEAD first
    for r in head:
        norm = normalise_youtube_url(r["channel_url"])
        if norm:
            seen.setdefault(norm[1], r["gov_id"])
    head_govs = {r["gov_id"] for r in head}
    tally: Counter = Counter()
    kept: list[dict] = []
    for cand in candidate_leads(wo):
        tally["candidates"] += 1
        if cand.get("kind") == "playlist":
            list_id = (parse_qs(urlparse(cand["url"]).query).get("list") or [""])[0]
            norm = ("playlist", f"playlist/{list_id}", cand["url"]) if list_id else None
        else:
            norm = normalise_youtube_url(cand["url"])
        if norm is None:
            tally["not a channel or video URL"] += 1
            continue
        kind, key, clean = norm
        if key in seen:
            tally["already listed"] += 1
            continue
        seen[key] = cand["gov_id"]
        if cand["gov_id"] in head_govs:
            tally["kept, but the government already has other leads"] += 1
        kept.append(
            {
                "channel_url": clean,
                "gov_id": cand["gov_id"],
                "government": cand["name"],
                "state": states.get(cand["gov_id"], ""),
                "source_wo": wo.upper().replace("WO", "WO-"),
                "kind": kind,
                "verified": "false",
                "note": f"{cand['note']}; hand-read {wo.upper().replace('WO', 'WO-')}, "
                "channel content not read",
            }
        )
    tally["kept"] = len(kept)
    return kept, tally


def main() -> None:
    head = leads_at_head()
    states = state_names()
    print(
        f"{len(head)} lead rows at HEAD ({len({r['gov_id'] for r in head})} governments)"
    )
    by_gov: dict[str, list[str]] = defaultdict(list)
    for wo in WOS:
        kept, tally = build(wo, head, states)
        # A lead written for one WO must not be re-offered by the other.
        for r in kept:
            n = normalise_youtube_url(r["channel_url"])
            head.append({"channel_url": r["channel_url"], "gov_id": r["gov_id"]})
            by_gov[r["gov_id"]].append(n[1] if n else "")
        out = RESEARCH_DIR / f"{wo}_leads_to_add.csv"
        with out.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
            w.writeheader()
            w.writerows(kept)
        print(f"\n{wo}: wrote {len(kept)} lead(s) to {out}")
        for k, v in tally.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
