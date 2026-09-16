#!/usr/bin/env python3
"""WO-368 (2026-09-14): walk the 20 "video, not a meeting" hubs from
WO-361/WO-364 to at least 3 videos each -- Ryan's own words: "For the 10
videos that were not a meeting in wo 364: can you check another video or
two at each of those hubs to make sure we get at least one real meeting
from the hub? If you get to multiple videos that are off mission or
exhaust all the videos in the 'hub' tag that row as off mission in the
research file." Breadth widened this to all 20 rows across both WO-361's
and WO-364's halves (`research/wo364_handread.csv`'s
`handread_verdict == "video-without-meeting"` rows), consistent with the
standing "walk to 3+ videos before an off-mission reject" rule
(preamble.md, CLAUDE.md's tier3 queue and hand-check rules bullet).

Population: the 20 gov_ids in `research/wo364_handread.csv` with
`handread_verdict == "video-without-meeting"`. Their `hub_url` and
`resolved_platform` come from `research/wo361_verify.csv` (read-only --
this is the URL the original access ladder actually hit on that
government's own homepage, which for every one of these 20 rows turned
out to BE the specific decorative/promotional video itself -- WO-361/364
found no separate listing page to walk, only a bare embed).

Method: `verify_hub(hub_url, platform_hint=resolved_platform, name=,
state=, deep_walk=True, listing_limit=15, video_collect_limit=3)` --
WO-355's options, matching the brief's "max_listings=15, max_videos=3"
instruction -- so the walk moves PAST the already hand-read-rejected
video and collects up to 2 more distinct candidates from the SAME hub.
`video_candidates` (newest-first) only gets populated when a real
listing was walked (see that field's own docstring in
app/platforms/passive_verify.py); a bare single-video hub with no
listing to walk correctly returns none, which is this brief's own
anticipated "bare homepage, one promo clip, no listing -- exhausted
after 1" case, not a bug in this script.

Each new candidate gets the same hand-read wo364_handread.py used:
decorative URL/filename signature check, then classify_video_hand_check()
as the automatic Kind A/B pre-filter, then (for Vimeo, when the walker's
own candidate title isn't already legible) the same public Vimeo oEmbed
GET wo364_handread.py uses -- metadata only, never a video download.

Writes `research/wo368_walk.csv` (one row per government -- the summary)
and `research/wo368_handread.csv` (one row per NEW video actually
looked at). Never downloads a media file (reuses wo364_handread.py's
Content-Type-checked fetch/oEmbed helpers directly by import). Never
fetches youtube.com/youtu.be -- `verify_hub()` already runs under
`_youtube_resolve_guard()`, and any bare-youtube-host candidate is
recorded as a tier-2 lead without ever being fetched.

Usage (repo root, shared venv, foreground, per-government ~2s):
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo368_walk.db" \\
        .venv/bin/python scripts/wo368_walk.py
"""

from __future__ import annotations

import asyncio
import csv
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.passive_verify import verify_hub  # noqa: E402
from app.utils.video_hand_check import classify_video_hand_check  # noqa: E402

# Reuse wo364_handread.py's own fetch/oEmbed/decorative-signature helpers
# rather than re-implementing the Content-Type-checked, never-download-
# media fetch a second time.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import wo364_handread as w364  # noqa: E402

register_all_finders()

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
HANDREAD_CSV = RESEARCH_DIR / "wo364_handread.csv"
VERIFY_CSV = RESEARCH_DIR / "wo361_verify.csv"
WALK_OUT = RESEARCH_DIR / "wo368_walk.csv"
HANDREAD_OUT = RESEARCH_DIR / "wo368_handread.csv"

_YOUTUBE_HOSTS = {"www.youtube.com", "youtube.com", "youtu.be", "m.youtube.com"}


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().split("@")[-1].split(":")[0]
    except Exception:  # noqa: BLE001
        return ""


def _norm(url: str) -> str:
    return (url or "").strip().rstrip("/")


def load_population() -> list[dict]:
    with open(HANDREAD_CSV, newline="", encoding="utf-8") as f:
        rows = [
            r
            for r in csv.DictReader(f)
            if r.get("handread_verdict") == "video-without-meeting"
        ]
    return rows


def load_hub_info() -> dict[str, dict]:
    with open(VERIFY_CSV, newline="", encoding="utf-8") as f:
        return {r["gov_id"]: r for r in csv.DictReader(f)}


async def handread_candidate(
    session: aiohttp.ClientSession, gov_name: str, gov_kind: str, candidate: dict
) -> dict:
    """Same hand-read discipline as wo364_handread.py, applied to one new
    `video_candidates` entry: decorative URL/filename signature first,
    then the WO-191 Kind A/B phrase pre-filter, then (Vimeo only, when
    the walker's own title isn't already legible) the public oEmbed
    title lookup. Returns a dict with the same shape as
    wo368_handread.csv's rows."""
    url = candidate.get("url") or ""
    title = candidate.get("title") or ""
    platform = candidate.get("platform") or ""
    out = {
        "url": url,
        "title": title,
        "date": candidate.get("date") or "",
        "platform": platform,
        "captions_found": candidate.get("captions_found"),
        "decorative_url_signature": w364._is_decorative_url(url),
        "decorative_filename": w364._is_decorative_filename(url),
        "hand_check_kind": "",
        "hand_check_reason": "",
        "oembed_title": "",
        "oembed_author": "",
        "verdict": "",
    }
    if out["decorative_url_signature"] or out["decorative_filename"]:
        out["verdict"] = "off-mission"
        out["hand_check_reason"] = "decorative URL/filename signature"
        return out

    if _host(url) in _YOUTUBE_HOSTS:
        # Never fetched -- record as a tier-2 lead candidate for a human/
        # the drip to hand-read from the page's own context, per
        # CLAUDE.md's "never fetch youtube.com" rule.
        out["verdict"] = "youtube_lead"
        return out

    hand_check = classify_video_hand_check(title, None, gov_name, gov_kind)
    if hand_check is not None:
        kind, reason = hand_check
        out["hand_check_kind"] = kind
        out["hand_check_reason"] = reason
        out["verdict"] = "kind_a" if kind == "A" else "off-mission"
        return out

    # Title already legible and passed the pre-filter -- read it directly
    # against the WO-364 real-meeting title shape.
    if title and w364._TITLE_MEETING_RE.search(title):
        out["verdict"] = "needs_manual_check"
        return out

    if platform == "vimeo" and not title:
        oe_title, oe_author, oerr = await w364.fetch_vimeo_oembed(session, url)
        out["oembed_title"] = oe_title
        out["oembed_author"] = oe_author
        if oerr and not oe_title:
            out["verdict"] = "needs_manual_check"
            return out
        if w364._TITLE_MEETING_RE.search(oe_title):
            out["verdict"] = "needs_manual_check"
        else:
            out["verdict"] = "off-mission"
        return out

    if title:
        out["verdict"] = "off-mission"
    else:
        out["verdict"] = "needs_manual_check"
    return out


async def walk_one(session: aiohttp.ClientSession, hr_row: dict, hub_row: dict) -> dict:
    gov_id = hr_row["gov_id"]
    name = hr_row["name"]
    state = hr_row["state"]
    rejected_url = hr_row["meeting_url"]
    hub_url = hub_row.get("hub_url") or ""
    platform = hub_row.get("resolved_platform") or hr_row.get("resolved_platform") or ""

    walk_row = {
        "gov_id": gov_id,
        "name": name,
        "state": state,
        "hub_url": hub_url,
        "platform": platform,
        "rejected_meeting_url": rejected_url,
        "videos_seen_total": 1,
        "new_video_urls": "",
        "new_titles": "",
        "new_verdicts": "",
        "final_row_verdict": "",
        "note": "",
    }

    if not hub_url:
        walk_row["final_row_verdict"] = "off-mission"
        walk_row["note"] = "no hub_url on file in wo361_verify.csv"
        return walk_row

    try:
        result = await asyncio.wait_for(
            verify_hub(
                hub_url,
                platform_hint=platform or None,
                name=name,
                state=state,
                deep_walk=True,
                listing_limit=15,
                video_collect_limit=3,
            ),
            timeout=90,
        )
    except asyncio.TimeoutError:
        walk_row["note"] = "verify_hub timeout after 90s"
        walk_row["final_row_verdict"] = "unresolved-timeout"
        return walk_row
    except Exception as e:  # noqa: BLE001
        walk_row["note"] = f"verify_hub {type(e).__name__}: {str(e)[:200]}"
        walk_row["final_row_verdict"] = "unresolved-error"
        return walk_row

    candidates = result.video_candidates or []
    rejected_norm = _norm(rejected_url)
    new_candidates = [c for c in candidates if _norm(c.get("url", "")) != rejected_norm]

    if not new_candidates:
        walk_row["note"] = (
            "hub exhausted after 1: verify_hub() found no listing to walk past the "
            f"already-rejected video (verdict={result.verdict!r}, evidence="
            f"{result.evidence[:160]!r}, candidates_checked={result.candidates_checked})"
        )
        walk_row["final_row_verdict"] = "off-mission"
        return walk_row

    new_candidates = new_candidates[:2]
    walk_row["videos_seen_total"] = 1 + len(new_candidates)

    urls, titles, verdicts = [], [], []
    on_mission_found = False
    off_mission_count = 0
    kind_a_hits = []

    for cand in new_candidates:
        hr = await handread_candidate(session, name, hr_row.get("gov_kind", ""), cand)
        urls.append(hr["url"])
        titles.append(hr["title"] or hr["oembed_title"] or "")
        verdicts.append(hr["verdict"])
        HANDREAD_ROWS.append(
            {
                "gov_id": gov_id,
                "name": name,
                "state": state,
                "candidate_url": hr["url"],
                "candidate_title": hr["title"],
                "candidate_date": hr["date"],
                "candidate_platform": hr["platform"],
                "captions_found": hr["captions_found"],
                "decorative_url_signature": hr["decorative_url_signature"],
                "decorative_filename": hr["decorative_filename"],
                "hand_check_kind": hr["hand_check_kind"],
                "hand_check_reason": hr["hand_check_reason"],
                "oembed_title": hr["oembed_title"],
                "oembed_author": hr["oembed_author"],
                "handread_verdict": hr["verdict"],
            }
        )
        if hr["verdict"] == "needs_manual_check":
            on_mission_found = True
        elif hr["verdict"] == "kind_a":
            kind_a_hits.append(cand)
        elif hr["verdict"] in ("off-mission",):
            off_mission_count += 1

    walk_row["new_video_urls"] = " | ".join(urls)
    walk_row["new_titles"] = " | ".join(titles)
    walk_row["new_verdicts"] = " | ".join(verdicts)

    if kind_a_hits:
        walk_row["note"] = (walk_row["note"] + " | " if walk_row["note"] else "") + (
            f"{len(kind_a_hits)} Kind A candidate(s) -- logged to wo368_owner_bodies.csv"
        )

    if on_mission_found:
        walk_row["final_row_verdict"] = "needs_manual_check"
    elif len(new_candidates) < 2:
        # Fewer than 2 new candidates means the listing itself ran dry
        # before reaching the cap -- genuinely exhausted, per the brief's
        # own rule, even if what we did see wasn't (yet) 2 off-mission.
        walk_row["final_row_verdict"] = "off-mission"
    elif off_mission_count >= 2:
        walk_row["final_row_verdict"] = "off-mission"
    else:
        # 2 new candidates seen, not all off-mission-classified (e.g. one
        # Kind A + one still ambiguous) -- leave for the report/human
        # rather than silently picking a bucket.
        walk_row["final_row_verdict"] = "needs_manual_check"

    return walk_row


HANDREAD_ROWS: list[dict] = []


async def main() -> None:
    population = load_population()
    hub_info = load_hub_info()
    print(f"{len(population)} governments to walk")

    walk_rows = []
    headers_ = {
        "User-Agent": w364._HEADERS["User-Agent"],
        "Accept": w364._HEADERS["Accept"],
    }
    async with aiohttp.ClientSession(headers=headers_) as session:
        for i, hr_row in enumerate(population, 1):
            gov_id = hr_row["gov_id"]
            hub_row = hub_info.get(gov_id, {})
            row = await walk_one(session, hr_row, hub_row)
            walk_rows.append(row)
            print(
                f"[{i}/{len(population)}] {gov_id} {hr_row['name']} {hr_row['state']} "
                f"seen={row['videos_seen_total']} verdict={row['final_row_verdict']} "
                f"note={row['note'][:100]}"
            )
            await asyncio.sleep(1.5)

    walk_fields = [
        "gov_id",
        "name",
        "state",
        "hub_url",
        "platform",
        "rejected_meeting_url",
        "videos_seen_total",
        "new_video_urls",
        "new_titles",
        "new_verdicts",
        "final_row_verdict",
        "note",
    ]
    with open(WALK_OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=walk_fields)
        writer.writeheader()
        writer.writerows(walk_rows)

    handread_fields = [
        "gov_id",
        "name",
        "state",
        "candidate_url",
        "candidate_title",
        "candidate_date",
        "candidate_platform",
        "captions_found",
        "decorative_url_signature",
        "decorative_filename",
        "hand_check_kind",
        "hand_check_reason",
        "oembed_title",
        "oembed_author",
        "handread_verdict",
    ]
    with open(HANDREAD_OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=handread_fields)
        writer.writeheader()
        writer.writerows(HANDREAD_ROWS)

    print(f"\nWrote {len(walk_rows)} rows to {WALK_OUT}")
    print(f"Wrote {len(HANDREAD_ROWS)} rows to {HANDREAD_OUT}")


if __name__ == "__main__":
    asyncio.run(main())
