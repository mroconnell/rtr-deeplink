"""WO-279 (2026-09-12): second look at every government tonight's sweeps
deferred for length or turned away at the hand-read -- find a shorter
on-mission meeting on the same channel/hub, else take the long one.

Population is fixed, not re-derived from a filter: the 72-row
`<scratch>/wo279_population.csv` built by unioning WO-230/235/247/249/
252/253/258/259/271/276's own decision files (see this WO's
BACKLOG_DONE entry for the derivation), re-checked against a fresh
`jurisdiction_coverage.csv` to drop anything that already gained a page
since. WO-277's three turned-away governments (Mont Belvieu TX, Aransas
Pass TX, Horseheads NY) are excluded -- that WO already re-checks them.

Two stages, same shape as WO-235/247's own two-stage discover/finalize
pipeline (reused directly: classify_video_hand_check, the yt-dlp flat
listing technique, queue_probe's finish_candidate()):

  discover  -- one yt-dlp flat-listing call per government (playlistend
  40, `videos` then `streams` tab), applies the automated pre-filter
  (`_looks_like_real_meeting` + `classify_video_hand_check`) to every
  entry, and writes `<scratch>/wo279_discovery.csv` -- no ingest, no
  pin, nothing touched in jurisdiction_coverage.csv. A human (this
  session) reads it and decides per CLAUDE.md's hand-check rule.

  finalize  -- reads `<scratch>/wo279_decisions.csv` (hand-written) and,
  for each `approve` row, resolves the chosen video and either ingests
  it (captions -> bulk_ingest.py, called as a subprocess so this script
  stays resolve-agnostic) or runs the tier-3 probe/queue decision
  directly via `app.platforms.queue_probe`, with one override from
  Ryan's new rule: an over-90-minute accepted candidate is queued
  anyway, never deferred (finish_candidate()'s own defer-over-90-min
  behavior is bypassed for exactly this run).
"""

import argparse
import csv
import os
import sys
import time
from pathlib import Path
from typing import Optional

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

import yt_dlp  # noqa: E402

from app.utils.video_hand_check import classify_video_hand_check  # noqa: E402
import scripts.wo134_confirmed_hits_ingest as wo134  # noqa: E402

SCRATCH = Path(
    "/private/tmp/claude-501/-Users-mroconnell-Documents-rtr-deeplink--claude-worktrees-"
    "platform-detection-backfill-c9742a/1d27de13-eb07-451a-a07a-bb18900b5618/scratchpad/"
    "agents/a8e9233b00ccbe9a1"
)
POPULATION_CSV = SCRATCH / "wo279_population.csv"
DISCOVERY_CSV = SCRATCH / "wo279_discovery.csv"
DECISIONS_CSV = SCRATCH / "wo279_decisions.csv"
REPORT_CSV = SCRATCH / "wo279_report.csv"

_YDL_BASE_OPTS = {
    "skip_download": True,
    "quiet": True,
    "no_warnings": True,
    "extract_flat": "in_playlist",
    "extractor_args": {"youtube": {"player_client": ["android", "ios", "tv", "web"]}},
    "ignoreerrors": True,
}

_looks_like_real_meeting = wo134._looks_like_real_meeting

BLOCK_SIGNATURES = (
    "429",
    "sign in to confirm",
    "confirm you're not a bot",
    "http error 403",
)


class YoutubeBlocked(RuntimeError):
    pass


def _yt_dlp_listing_sync(url: str, playlistend: int) -> Optional[dict]:
    opts = dict(_YDL_BASE_OPTS)
    opts["playlistend"] = playlistend
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)
    except Exception as e:
        msg = str(e).lower()
        if any(sig in msg for sig in BLOCK_SIGNATURES):
            raise YoutubeBlocked(str(e))
        return None


def _yt_dlp_single_sync(url: str) -> Optional[dict]:
    opts = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "extractor_args": {
            "youtube": {"player_client": ["android", "ios", "tv", "web"]}
        },
        "ignoreerrors": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)
    except Exception as e:
        msg = str(e).lower()
        if any(sig in msg for sig in BLOCK_SIGNATURES):
            raise YoutubeBlocked(str(e))
        return None


def channel_tab_urls(channel_url: str):
    from urllib.parse import urlsplit, urlunsplit

    if "/playlist" in channel_url or "list=" in channel_url:
        return [channel_url]
    # strip query string/fragment first -- several source rows carry
    # ?view_as=subscriber / ?sort=dd&shelf_id=3 etc, which otherwise gets
    # a tab suffix appended AFTER it (a malformed URL yt-dlp 404s on).
    parts = urlsplit(channel_url)
    base = urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))
    # strip a known existing tab suffix before re-adding /videos + /streams
    for suffix in ("/videos", "/streams", "/about", "/featured", "/live", "/playlists"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    return [f"{base}/videos", f"{base}/streams"]


def load_population():
    with open(POPULATION_CSV) as f:
        return list(csv.DictReader(f))


def already_discovered():
    if not DISCOVERY_CSV.exists():
        return set()
    with open(DISCOVERY_CSV) as f:
        return {row["gov_id"] for row in csv.DictReader(f)}


DISCOVERY_FIELDS = [
    "gov_id",
    "name",
    "state",
    "channel_or_video",
    "channel_name",
    "channel_description_snippet",
    "n_entries_seen",
    "candidates_json",
    "youtube_blocked",
    "note",
]


def append_discovery_row(row: dict):
    is_new = not DISCOVERY_CSV.exists()
    with open(DISCOVERY_CSV, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=DISCOVERY_FIELDS)
        if is_new:
            w.writeheader()
        w.writerow(row)


def cmd_discover(args):
    pop = load_population()
    done = already_discovered()
    n_processed = 0
    for row in pop:
        gid = row["gov_id"]
        if gid in done:
            continue
        if args.limit and n_processed >= args.limit:
            print(f"[STOP] limit {args.limit} reached; resume with --start-after {gid}")
            break
        name = row["name"]
        state = row["state"]
        gov_kind = row["gov_kind"]
        channel_url = row["channel_url"]
        video_url = row["video_url"]
        print(f"\n=== {gid} {name}, {state} ===")

        info = None
        source = channel_url
        if not channel_url and video_url:
            # derive channel from the single known video first
            try:
                vinfo = _yt_dlp_single_sync(video_url)
            except YoutubeBlocked as e:
                append_discovery_row(
                    {
                        "gov_id": gid,
                        "name": name,
                        "state": state,
                        "channel_or_video": video_url,
                        "channel_name": "",
                        "channel_description_snippet": "",
                        "n_entries_seen": 0,
                        "candidates_json": "[]",
                        "youtube_blocked": "yes",
                        "note": f"BLOCKED deriving channel: {e}",
                    }
                )
                print(f"[YOUTUBE BLOCKED] {e}")
                print(
                    f"[STOP] processed {n_processed} governments this run before the block."
                )
                return
            if not vinfo:
                append_discovery_row(
                    {
                        "gov_id": gid,
                        "name": name,
                        "state": state,
                        "channel_or_video": video_url,
                        "channel_name": "",
                        "channel_description_snippet": "",
                        "n_entries_seen": 0,
                        "candidates_json": "[]",
                        "youtube_blocked": "no",
                        "note": "could not resolve video to derive channel",
                    }
                )
                n_processed += 1
                time.sleep(1.5)
                continue
            channel_url = vinfo.get("channel_url") or vinfo.get("uploader_url") or ""
            if not channel_url:
                uid = vinfo.get("channel_id") or vinfo.get("uploader_id")
                if uid:
                    channel_url = f"https://www.youtube.com/channel/{uid}"
            source = channel_url or video_url

        candidates = []
        channel_name = ""
        channel_desc = ""
        n_entries = 0
        blocked = False
        note = ""
        if channel_url:
            for tab_url in channel_tab_urls(channel_url):
                try:
                    info = _yt_dlp_listing_sync(tab_url, args.playlistend)
                except YoutubeBlocked as e:
                    blocked = True
                    note = f"BLOCKED: {e}"
                    break
                time.sleep(2.0)
                if not info:
                    continue
                channel_name = (
                    channel_name or info.get("title") or info.get("channel") or ""
                )
                channel_desc = channel_desc or (info.get("description") or "")[:300]
                entries = [e for e in (info.get("entries") or []) if e]
                n_entries += len(entries)
                channel_text = f"{channel_name} {channel_desc}"
                for e in entries:
                    title = e.get("title") or ""
                    duration = e.get("duration") or 0
                    vid = e.get("id") or e.get("url") or ""
                    if e.get("live_status") in ("is_upcoming", "is_live"):
                        continue
                    passes_title = _looks_like_real_meeting(
                        title, require_allowlist=True
                    )
                    hand_check = classify_video_hand_check(
                        title, channel_text, name, gov_kind
                    )
                    candidates.append(
                        {
                            "id": vid,
                            "title": title,
                            "duration": duration,
                            "passes_title_filter": passes_title,
                            "hand_check": list(hand_check) if hand_check else None,
                        }
                    )
            if blocked:
                append_discovery_row(
                    {
                        "gov_id": gid,
                        "name": name,
                        "state": state,
                        "channel_or_video": source,
                        "channel_name": channel_name,
                        "channel_description_snippet": channel_desc,
                        "n_entries_seen": n_entries,
                        "candidates_json": "[]",
                        "youtube_blocked": "yes",
                        "note": note,
                    }
                )
                print(f"[YOUTUBE BLOCKED] {note}")
                print(
                    f"[STOP] processed {n_processed} governments this run before the block."
                )
                return
        else:
            note = "no channel url resolvable"

        import json

        append_discovery_row(
            {
                "gov_id": gid,
                "name": name,
                "state": state,
                "channel_or_video": source,
                "channel_name": channel_name,
                "channel_description_snippet": channel_desc,
                "n_entries_seen": n_entries,
                "candidates_json": json.dumps(candidates),
                "youtube_blocked": "no",
                "note": note,
            }
        )
        print(
            f"  channel={channel_name!r} entries_seen={n_entries} candidates={len(candidates)}"
        )
        n_processed += 1
        time.sleep(1.5)
    print(f"\n[DONE] discovered {n_processed} governments this run.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_discover = sub.add_parser("discover")
    p_discover.add_argument("--limit", type=int, default=0)
    p_discover.add_argument("--playlistend", type=int, default=40)
    args = parser.parse_args()
    if args.cmd == "discover":
        cmd_discover(args)
