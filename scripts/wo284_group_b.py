"""WO-284: group (b) -- the 53 wo264_report.csv rows (47 platform-found, 6
video-candidate) that the WO-264 close-out never hand-read because the
overnight worker wrote them after the 1,894-government stopping point
(re-derived: 2,270 completed - 1,894 = 376 post-stop rows total; these 53
are the actionable subset -- see scripts/wo284_listing_hop.py's module
docstring for the full re-derivation and why "376" isn't the right count
to hand-read against).

Per-row action depends on what `platform_found`/`platform_evidence_url`
actually is (re-checked live, not trusted from the report):

  - A bare `youtube.com`/`youtube.com/` "evidence" is the same false-
    positive `wo284_listing_hop.py`'s group (c) already found (a footer
    social icon or embed-player "visit YouTube" button, not a real
    channel) -- refetch the front page and look for a real channel link
    with the WO-285-widened `find_youtube_links()`.
  - A real channel/handle URL -- yt-dlp flat listing (both /videos and
    /streams tabs, `app.platforms.youtube_channel._list_channel`), then
    `classify_video_hand_check()` on every candidate title, newest
    on-mission match first, 9-40 minutes preferred.
  - A specific video URL already on file -- YouTube oEmbed (title +
    author_name, one lightweight request, no yt-dlp needed to just read
    the title/channel) then the same hand-check.
  - A named vendor tenant (Granicus/CivicPlus/Castus/CivicWeb/Wistia/
    Vimeo) -- fetch the tenant/listing URL directly and look for a
    per-meeting link with `find_video_candidates()`/`detect_platform()`.
  - A video-candidate row whose only URLs are Google Drive or a wix-
    hosted mp4 -- flagged, not resolved (Drive has no adapter at all,
    confirmed gap; a wix mp4 is checked against `detect_platform()` but
    not assumed).

Writes `research/wo284_group_b.csv`, one row per government -- resumable.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests
import yt_dlp

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
REPO_ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

from wo273_recon import HEADERS  # noqa: E402
import wo281_homepage_hop as h1  # noqa: E402
import wo264_overnight_sweep as overnight  # noqa: E402
import wo235_channel_pilot as ytscan  # noqa: E402

from app.platforms.base import detect_platform  # noqa: E402
from app.utils.video_hand_check import classify_video_hand_check  # noqa: E402

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
WO264_REPORT = RESEARCH_DIR / "wo264_report.csv"
WO264_HAND_READ = RESEARCH_DIR / "wo264_hand_read_decisions.csv"
OUT_CSV = RESEARCH_DIR / "wo284_group_b.csv"

_FIELDS = [
    "gov_id",
    "name",
    "state",
    "gov_kind",
    "outcome_hint",
    "platform_found",
    "action",
    "best_url",
    "title",
    "channel_text",
    "duration_s",
    "hand_check",
    "note",
]


def log(msg: str) -> None:
    print(msg, flush=True)


def load_group_b() -> list:
    with open(WO264_REPORT, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    with open(WO264_HAND_READ, newline="", encoding="utf-8") as f:
        hr = {r["gov_id"] for r in csv.DictReader(f)}
    return [
        r
        for r in rows
        if r["outcome"] in ("platform-found", "video-candidate")
        and r["gov_id"] not in hr
    ]


_BARE_YOUTUBE = {
    "https://www.youtube.com",
    "https://www.youtube.com/",
    "http://www.youtube.com",
    "http://www.youtube.com/",
    "https://www.youtube.com",
    "https://www.Youtube.com",
}


def is_bare_youtube(url: str) -> bool:
    return url.strip().rstrip("/").lower() in (
        "https://www.youtube.com",
        "http://www.youtube.com",
    )


def oembed_lookup(video_url: str) -> dict:
    try:
        resp = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": video_url, "format": "json"},
            headers=HEADERS,
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:  # noqa: BLE001
        pass
    return {}


def yt_flat_listing(channel_url: str, limit: int = 40) -> list:
    ydl_opts = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "playlistend": limit,
        "extractor_args": {
            "youtube": {"player_client": ["android", "ios", "tv", "web"]}
        },
        "ignoreerrors": True,
    }
    out = []
    tabs = ["videos", "streams"]
    base = channel_url.rstrip("/")
    for tab in tabs:
        url = f"{base}/{tab}"
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            entries = [e for e in (info.get("entries") or []) if e and e.get("id")]
            out.extend(entries)
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if "429" in msg or "Sign in to confirm" in msg:
                raise
            continue
    seen = set()
    deduped = []
    for e in out:
        if e["id"] not in seen:
            seen.add(e["id"])
            deduped.append(e)
    return deduped


def pick_best_entry(entries: list, name: str, gov_kind: str) -> dict:
    """Prefer 9-40 min, on-mission (no Kind A/B hand-check hit), newest
    first (yt-dlp flat listing is already newest-first)."""
    scored = []
    for e in entries:
        title = e.get("title") or ""
        hc = classify_video_hand_check(title, "", name, gov_kind)
        dur = e.get("duration") or 0
        in_range = 9 * 60 <= dur <= 40 * 60
        scored.append((hc is None, in_range, e, hc))
    # rank: no hand-check hit first, then in preferred duration range,
    # preserving newest-first order within each bucket
    scored.sort(key=lambda t: (not t[0], not t[1]))
    return scored[0] if scored else None


def process_row(row: dict) -> dict:
    gov_id = row["gov_id"]
    name = row.get("name", "")
    state = row.get("state", "")
    gov_kind = row.get("gov_kind", "")
    platform = row.get("platform_found", "")
    evidence_url = row.get("platform_evidence_url", "")
    video_cands = [u for u in (row.get("video_candidate_urls") or "").split("|") if u]
    out = {
        "gov_id": gov_id,
        "name": name,
        "state": state,
        "gov_kind": gov_kind,
        "outcome_hint": row["outcome"],
        "platform_found": platform,
        "action": "",
        "best_url": "",
        "title": "",
        "channel_text": "",
        "duration_s": "",
        "hand_check": "",
        "note": "",
    }

    if row["outcome"] == "video-candidate":
        drive_only = (
            all("drive.google.com" in u for u in video_cands) if video_cands else False
        )
        if drive_only:
            out["action"] = "no-adapter-google-drive"
            out["best_url"] = video_cands[0] if video_cands else ""
            out["note"] = "Google Drive video, no adapter (confirmed gap, BACKLOG.md)"
            return out
        wix = [u for u in video_cands if "wixstatic.com" in u or "img1.wsimg.com" in u]
        if wix:
            dp = None
            try:
                dp = detect_platform(wix[0])
            except Exception:  # noqa: BLE001
                dp = None
            out["best_url"] = wix[0]
            out["action"] = (
                "no-adapter-wix-video"
                if not dp or dp == "unknown"
                else "wix-video-detected"
            )
            out["note"] = f"detect_platform={dp}"
            return out
        out["action"] = "unhandled-video-candidate"
        out["best_url"] = video_cands[0] if video_cands else ""
        return out

    # platform-found rows
    if platform == "youtube":
        if is_bare_youtube(evidence_url) or (
            video_cands
            and all(
                is_bare_youtube(u)
                or u.rstrip("/")
                .lower()
                .startswith(
                    (
                        "https://www.youtube.com/about",
                        "https://www.youtube.com/t/",
                        "https://www.youtube.com/creators",
                        "https://www.youtube.com/ads",
                    )
                )
                for u in video_cands
            )
        ):
            domain = row.get("domain_tried", "")
            url = domain if domain.startswith("http") else f"https://{domain}/"
            try:
                fetch = h1.fetch_with_ladder(
                    url, rate_key=urlparse(url).netloc or domain
                )
            except Exception as e:  # noqa: BLE001
                out["action"] = "front-page-refetch-failed"
                out["note"] = str(e)[:200]
                return out
            if not fetch["html"]:
                out["action"] = "front-page-unreachable"
                out["note"] = fetch.get("error", "")
                return out
            hits = ytscan.find_youtube_links(fetch["html"], fetch["final_url"])
            real_channels = [
                u for kind, u in hits if kind == "channel" and not is_bare_youtube(u)
            ]
            if not real_channels:
                out["action"] = "still-false-positive-no-real-channel"
                return out
            out["best_url"] = real_channels[0]
            out["action"] = "real-channel-found-needs-listing"
            evidence_url = real_channels[0]
        # channel/handle-shaped: do the flat listing
        kind = ytscan.classify_youtube_url(evidence_url)
        if kind == "channel":
            try:
                entries = yt_flat_listing(evidence_url)
            except Exception as e:  # noqa: BLE001
                out["action"] = (
                    "youtube-block"
                    if ("429" in str(e) or "Sign in to confirm" in str(e))
                    else "listing-failed"
                )
                out["note"] = str(e)[:300]
                return out
            if not entries:
                out["action"] = "channel-empty-or-unlisted"
                out["best_url"] = evidence_url
                return out
            picked = pick_best_entry(entries, name, gov_kind)
            hc, in_range, entry, hand_check_result = picked
            out["best_url"] = f"https://www.youtube.com/watch?v={entry['id']}"
            out["title"] = entry.get("title", "")
            out["duration_s"] = entry.get("duration", "")
            out["hand_check"] = f"{hand_check_result}" if hand_check_result else "clear"
            out["action"] = (
                "candidate-found-needs-hand-read"
                if hand_check_result is None
                else "candidate-flagged-by-hand-check"
            )
            return out
        elif kind == "video":
            info = oembed_lookup(evidence_url)
            out["best_url"] = evidence_url
            out["title"] = info.get("title", "")
            out["channel_text"] = info.get("author_name", "")
            hc = classify_video_hand_check(
                out["title"], out["channel_text"], name, gov_kind
            )
            out["hand_check"] = f"{hc}" if hc else "clear"
            out["action"] = (
                "candidate-found-needs-hand-read"
                if hc is None
                else "candidate-flagged-by-hand-check"
            )
            return out
        else:
            out["action"] = "unrecognized-youtube-shape"
            out["best_url"] = evidence_url
            return out

    if platform == "vimeo":
        out["best_url"] = evidence_url
        info = oembed_lookup(evidence_url) if False else {}
        try:
            resp = requests.get(
                "https://vimeo.com/api/oembed.json",
                params={"url": evidence_url},
                headers=HEADERS,
                timeout=10,
            )
            if resp.status_code == 200:
                info = resp.json()
        except Exception:  # noqa: BLE001
            info = {}
        out["title"] = info.get("title", "")
        out["channel_text"] = info.get("author_name", "")
        hc = classify_video_hand_check(
            out["title"], out["channel_text"], name, gov_kind
        )
        out["hand_check"] = f"{hc}" if hc else "clear"
        out["action"] = (
            "candidate-found-needs-hand-read"
            if hc is None
            else "candidate-flagged-by-hand-check"
        )
        return out

    # Named vendor tenants: fetch the tenant/listing URL and look for a
    # meeting/video link.
    if platform in ("granicus", "civicplus", "castus", "civicweb", "wistia"):
        url = evidence_url
        try:
            fetch = h1.fetch_with_ladder(url, rate_key=urlparse(url).netloc or url)
        except Exception as e:  # noqa: BLE001
            out["action"] = "tenant-fetch-failed"
            out["note"] = str(e)[:200]
            return out
        if not fetch["html"]:
            out["action"] = "tenant-unreachable"
            out["note"] = fetch.get("error", "")
            return out
        video_hits = overnight.find_video_candidates(fetch["html"], fetch["final_url"])
        out["best_url"] = video_hits[0] if video_hits else url
        out["action"] = (
            "vendor-video-found" if video_hits else "vendor-page-reached-no-video-link"
        )
        return out

    out["action"] = "unhandled-platform"
    out["best_url"] = evidence_url
    return out


def main() -> None:
    population = load_group_b()
    done = set()
    if OUT_CSV.exists():
        with open(OUT_CSV, newline="", encoding="utf-8") as f:
            done = {r["gov_id"] for r in csv.DictReader(f)}
    remaining = [r for r in population if r["gov_id"] not in done]
    log(f"{len(done)} already done, {len(remaining)} remaining of {len(population)}")
    write_header = not OUT_CSV.exists()
    with open(OUT_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDS)
        if write_header:
            writer.writeheader()
        for i, row in enumerate(remaining, 1):
            try:
                result = process_row(row)
            except Exception as e:  # noqa: BLE001
                result = {k: "" for k in _FIELDS}
                result.update(
                    gov_id=row["gov_id"],
                    name=row.get("name", ""),
                    state=row.get("state", ""),
                    action="error",
                    note=str(e)[:300],
                )
            writer.writerow({k: result.get(k, "") for k in _FIELDS})
            f.flush()
            log(f"[{i}/{len(remaining)}] {result['gov_id']} -> {result['action']}")
            if result["action"] == "youtube-block":
                log("YOUTUBE BLOCK SIGNATURE HIT -- stopping YouTube work per rule.")
                break


if __name__ == "__main__":
    main()
