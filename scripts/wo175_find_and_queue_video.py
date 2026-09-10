"""WO-175 step 3: for every channel wo175_classify_channels.py verdicted
`own-channel` or `shared`, find a clearly on-mission meeting video on
that channel, probe it (app/platforms/queue_probe.py -- WO-144), and
queue the first one that passes.

Ryan's rule for picking the candidate: prefer the newest complete
meeting between 9 and 40 minutes; otherwise take the shortest available.
Reuses `scripts/wo134_confirmed_hits_ingest.py`'s own title
allowlist/blocklist (a real meeting title contains a governing-body word
-- council, commission, board, ... -- and none of the promo/tour/PSA
blocklist words) so a "State of the City" address or a ribbon-cutting
clip is never picked over a real meeting. Up to 6 candidates are tried
per channel before giving up, same ceiling WO-134/WO-145 use.

A channel already covered by a real Archive page (checked against a
fresh `scripts/export_meeting_inventory.py --source export` pull, not a
stale file) is skipped outright -- `already_covered`.

Writes:
- rtr-business/research/wo175_queue_outcomes.csv (one row per attempted
  gov_id)
- scripts/tier3_auto_transcription_queue.txt (append, dedup'd against
  the file's own existing first-column URLs)
- app/utils/jurisdiction_data/tenant_overrides.csv (append, dedup'd on
  (tenant_host, match)) -- a per-video pin always; a channel pin too
  when the verdict is `own-channel` (never for `shared`, per this
  morning's shared-host pin convention: a per-video pin only for a
  community/media channel that is not certified to belong to the
  government as a whole)

Politeness: one channel at a time, 2 seconds between every YouTube call
(the /videos and /streams flat-playlist listings, and each candidate's
probe). Stops outright on YouTube's block signature (429, or "Sign in
to confirm you're not a bot") and after 6 consecutive real (non-content)
errors.

Usage:
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo175_scratch.db" \\
        python scripts/wo175_find_and_queue_video.py
"""

import asyncio
import csv
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import certifi  # noqa: E402

# Must run before `import aiohttp` -- see CLAUDE.md's matching convention
# bullet (a fresh Homebrew-Python venv has an empty default SSL trust
# store, and aiohttp caches its default SSLContext the instant `import
# aiohttp` runs anywhere in the process).
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:////tmp/wo175_scratch.db")

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.queue_probe import probe_queue_entry  # noqa: E402
from app.utils.gov_registry.registry import government_for_id  # noqa: E402

register_all_finders()

BUSINESS_RESEARCH = Path.home() / "Documents" / "rtr-business" / "research"
RECHECK_CSV = BUSINESS_RESEARCH / "wo175_channel_recheck.csv"
INVENTORY_CSV = Path("/tmp/wo175_inventory/meeting_inventory.csv")
OUT_CSV = BUSINESS_RESEARCH / "wo175_queue_outcomes.csv"

TIER3_QUEUE_FILE = REPO_ROOT / "scripts" / "tier3_auto_transcription_queue.txt"
TENANT_OVERRIDES_CSV = (
    REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "tenant_overrides.csv"
)

MEETING_ALLOWLIST = (
    "council",
    "commission",
    "board",
    "committee",
    "meeting",
    "session",
    "hearing",
    "authority",
    "trustees",
    "supervisors",
    "assembly",
    "selectboard",
    "select board",
    "bocc",
)
PROMO_BLOCKLIST = (
    "promo",
    "advertisement",
    "commercial",
    "psa",
    "public service announcement",
    "how to",
    "tutorial",
    "instructional",
    "training video",
    "orientation video",
    "welcome",
    "message from the mayor",
    "highlight reel",
    "sizzle reel",
    "ribbon cutting",
    "parade",
    "test stream",
    "test broadcast",
    "sample video",
    "demo video",
    "career",
    "job fair",
    "recruitment",
    "state of the city",
    "year in review",
    "commercial break",
    "tour of",
)
PREFERRED_MIN = 9 * 60
PREFERRED_MAX = 40 * 60
MAX_CANDIDATES_TRIED = 6

BLOCK_MARKERS = ("429", "sign in to confirm", "not a bot")


def _contains_word(text: str, phrase: str) -> bool:
    return re.search(r"\b" + re.escape(phrase) + r"\b", text) is not None


def looks_like_real_meeting(title: str) -> bool:
    t = (title or "").lower()
    if any(_contains_word(t, b) for b in PROMO_BLOCKLIST):
        return False
    return any(_contains_word(t, kw) for kw in MEETING_ALLOWLIST)


def is_block_signature(text: str) -> bool:
    t = (text or "").lower()
    return any(m in t for m in BLOCK_MARKERS)


def channel_path(handle: str, channel_id: str) -> str:
    """WO-171 never resolved a @handle for the 31 originally oEmbed-
    unreachable channels -- `handle` is blank for those rows even after
    wo175_classify_channels.py finds a real title via the channel_id
    URL. Building "/{handle}/..." with a blank handle silently produces
    "https://www.youtube.com//videos", which yt-dlp resolves to
    something else entirely and returns zero real candidates for --
    the exact bug this recheck's own About-page fetch hit and fixed
    first (see wo175_retry_unreachable's channel_id fallback). Same
    fix here: fall back to the permanent channel_id path."""
    return f"@{handle.lstrip('@')}" if handle.strip() else f"channel/{channel_id}"


def flat_playlist(handle: str, channel_id: str, tab: str):
    """Runs under the SAME Python interpreter as this script (`sys.
    executable`) -- CLAUDE.md's pinned venv (/Users/mroconnell/Documents/
    rtr-deeplink/.venv/bin/python) is expected to be what invokes this
    file in the first place, so yt-dlp resolves from it rather than
    guessing at a relative venv path that would not survive being run
    from a worktree."""
    url = f"https://www.youtube.com/{channel_path(handle, channel_id)}/{tab}"
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "yt_dlp",
                "--flat-playlist",
                "--playlist-end",
                "30",
                "--print",
                "%(id)s|%(title)s|%(duration)s",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )
        combined = (proc.stdout or "") + (proc.stderr or "")
        if is_block_signature(combined):
            return None, "BLOCK"
        candidates = []
        for line in (proc.stdout or "").splitlines():
            parts = line.split("|")
            if len(parts) != 3:
                continue
            vid, title, dur = parts
            try:
                dur_f = float(dur)
            except ValueError:
                continue
            candidates.append((vid, title, dur_f))
        return candidates, None
    except subprocess.TimeoutExpired:
        return [], "timeout"
    except Exception as e:  # noqa: BLE001 -- report any failure, don't crash the sweep
        return [], str(e)


def pick_order(candidates):
    """Newest-first within the preferred 9-40 minute band, then
    shortest-first among everything else, per Ryan's stated rule."""
    eligible = [c for c in candidates if looks_like_real_meeting(c[1])]
    preferred = [c for c in eligible if PREFERRED_MIN <= c[2] <= PREFERRED_MAX]
    rest = sorted(
        (c for c in eligible if not (PREFERRED_MIN <= c[2] <= PREFERRED_MAX)),
        key=lambda c: c[2],
    )
    return preferred + rest


def load_already_covered_gov_ids() -> set:
    covered = set()
    if INVENTORY_CSV.exists():
        with INVENTORY_CSV.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                gid = r.get("gov_id")
                if gid:
                    covered.add(gid)
    return covered


def existing_tier3_urls() -> set:
    urls = set()
    if TIER3_QUEUE_FILE.exists():
        for line in TIER3_QUEUE_FILE.read_text(encoding="utf-8").splitlines():
            if line.strip():
                urls.add(line.split("\t", 1)[0])
    return urls


def existing_override_keys() -> set:
    keys = set()
    if TENANT_OVERRIDES_CSV.exists():
        with TENANT_OVERRIDES_CSV.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                keys.add((r.get("tenant_host", ""), r.get("match", "")))
    return keys


def append_pin(
    host: str, match: str, gov_id: str, evidence: str, seen_keys: set
) -> bool:
    key = (host, match)
    if key in seen_keys:
        return False
    is_new = not TENANT_OVERRIDES_CSV.exists()
    with TENANT_OVERRIDES_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "tenant_host",
                "match",
                "gov_id",
                "strength",
                "source",
                "evidence",
            ],
            lineterminator="\n",
        )
        if is_new:
            w.writeheader()
        w.writerow(
            {
                "tenant_host": host,
                "match": match,
                "gov_id": gov_id,
                "strength": "fallback",
                "source": "wo175_localview_recheck",
                "evidence": evidence,
            }
        )
    seen_keys.add(key)
    return True


def append_queue(video_url: str, seen_urls: set) -> bool:
    if video_url in seen_urls:
        return False
    with TIER3_QUEUE_FILE.open("a", encoding="utf-8") as f:
        f.write(video_url + "\n")
    seen_urls.add(video_url)
    return True


async def probe_one(video_url: str):
    return await probe_queue_entry(video_url, video_url=video_url, platform="youtube")


async def main() -> None:
    with RECHECK_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    targets = [r for r in rows if r["new_verdict"] in ("own-channel", "shared")]
    print(f"{len(targets)} own-channel/shared channels to process")

    already_covered = load_already_covered_gov_ids()
    seen_tier3 = existing_tier3_urls()
    seen_overrides = existing_override_keys()

    out_fields = [
        "gov_id",
        "handle",
        "verdict",
        "outcome",
        "video_id",
        "video_url",
        "video_title",
        "duration_seconds",
        "detail",
    ]
    out_rows = []
    consec_errors = 0

    for i, row in enumerate(targets):
        gov_id = row["gov_id"]
        handle = row["handle"]
        channel_id = row["channel_id"]
        verdict = row["new_verdict"]
        gov = government_for_id(gov_id)
        gov_name = gov.gov_name if gov else row["orig_name"]

        print(
            f"\n[{i + 1}/{len(targets)}] {handle} -> {gov_id} ({gov_name}) [{verdict}]"
        )

        if gov_id in already_covered:
            out_rows.append(
                {
                    "gov_id": gov_id,
                    "handle": handle,
                    "verdict": verdict,
                    "outcome": "already_covered",
                    "video_id": "",
                    "video_url": "",
                    "video_title": "",
                    "duration_seconds": "",
                    "detail": "gov_id already has an archived page",
                }
            )
            print("  already_covered")
            continue

        candidates, err = flat_playlist(handle, channel_id, "videos")
        time.sleep(2)
        if err == "BLOCK":
            print("BLOCK SIGNATURE -- stopping all YouTube calls.")
            break
        if err:
            consec_errors += 1
            print(f"  /videos error: {err}")
        else:
            consec_errors = 0

        if not candidates:
            candidates2, err2 = flat_playlist(handle, channel_id, "streams")
            time.sleep(2)
            if err2 == "BLOCK":
                print("BLOCK SIGNATURE -- stopping all YouTube calls.")
                break
            candidates = candidates2 or []

        ordered = pick_order(candidates)
        if not ordered:
            out_rows.append(
                {
                    "gov_id": gov_id,
                    "handle": handle,
                    "verdict": verdict,
                    "outcome": "no_on_mission_video",
                    "video_id": "",
                    "video_url": "",
                    "video_title": "",
                    "duration_seconds": "",
                    "detail": f"{len(candidates)} videos listed, none passed the "
                    "meeting title allow/blocklist",
                }
            )
            print("  no on-mission video on channel")
            continue

        accepted = None
        tried = 0
        for vid, title, dur in ordered:
            if tried >= MAX_CANDIDATES_TRIED:
                break
            tried += 1
            video_url = f"https://www.youtube.com/watch?v={vid}"
            try:
                result = await probe_one(video_url)
            except Exception as e:  # noqa: BLE001
                if is_block_signature(str(e)):
                    print("BLOCK SIGNATURE during probe -- stopping.")
                    accepted = "BLOCK"
                    break
                consec_errors += 1
                print(f"  probe error on {vid}: {e}")
                time.sleep(2)
                continue
            print(
                f"  probe {vid} ({title[:50]!r}, {dur:.0f}s) -> "
                f"{result.verdict} {result.reason or ''}"
            )
            time.sleep(2)
            if result.verdict in ("accept", "flag-long"):
                accepted = (vid, title, dur, result)
                break
        if accepted == "BLOCK":
            break

        if accepted is None:
            out_rows.append(
                {
                    "gov_id": gov_id,
                    "handle": handle,
                    "verdict": verdict,
                    "outcome": "rejected_by_probe",
                    "video_id": "",
                    "video_url": "",
                    "video_title": "",
                    "duration_seconds": "",
                    "detail": f"{tried} candidates tried, none probed accept",
                }
            )
            print("  rejected by probe, candidates exhausted")
            continue

        vid, title, dur, presult = accepted
        video_url = f"https://www.youtube.com/watch?v={vid}"
        queued = append_queue(video_url, seen_tier3)
        evidence = (
            f"{gov_name} -- WO-175 LocalView recheck, gov_id={gov_id}, title={title!r}"
        )
        append_pin("www.youtube.com", vid, gov_id, evidence, seen_overrides)
        if verdict == "own-channel" and handle.strip():
            # A channel-level pin is only ever matched against a
            # resolved video's real @handle (`page_hints_for()`'s
            # `channel` key -- see app/utils/gov_registry/resolver.py
            # and youtube.py's `_channel_handle()`), never a bare UC...
            # channel_id -- so skip this pin entirely when WO-171 never
            # resolved a handle for this channel; the per-video pin
            # above still keys the queued video correctly regardless.
            channel_match = f"channel=@{handle.lstrip('@')}"
            channel_evidence = f"{gov_name} -- WO-175 LocalView recheck, own-channel verdict, gov_id={gov_id}"
            append_pin(
                "www.youtube.com",
                channel_match,
                gov_id,
                channel_evidence,
                seen_overrides,
            )

        out_rows.append(
            {
                "gov_id": gov_id,
                "handle": handle,
                "verdict": verdict,
                "outcome": "queued" if queued else "queued_already_present",
                "video_id": vid,
                "video_url": video_url,
                "video_title": title,
                "duration_seconds": f"{dur:.0f}",
                "detail": presult.reason or "",
            }
        )
        print(f"  QUEUED {video_url}")

        if consec_errors >= 6:
            print("6 consecutive real errors -- stopping.")
            break

    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=out_fields, lineterminator="\n")
        w.writeheader()
        w.writerows(out_rows)
    print(f"\nWrote {len(out_rows)} rows to {OUT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
