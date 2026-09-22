#!/usr/bin/env python3
"""WO-1010: sweep more meetings per Sliq Harmony state-legislature tenant
(and one Washington/TVW pick) for real depth beyond the single meeting per
state that WO-921/WO-1006 originally picked.

Each pick below was chosen by hand from a real listing read
(`scripts/wo1010_recon.py`'s output, one request per tenant, title+date
only) -- on-mission judged the same way WO-921/WO-1006's own hand-read
CSVs judge it (a real committee/floor session/legislatively-created
commission or task force of that legislature; NOT a state board, agency,
or authority that happens to publish through the same shared tenant --
Oklahoma's Senate tenant carries several of the latter: the Workforce
Commission, the 911 Management Authority, the Medical Marijuana
Authority, the Incentive Evaluation Commission -- all left out on
purpose, same as WO-921 leaving out Kansas's "Governor's Uniform Task
Force" and "Build Kansas Advisory Committee"; Nevada's PUCN, State Public
Works Board, SPCSA and the Private Investigators Licensing Board are the
same shape and are also left out).

A pick with real captions (`segments`) is ingested as a page (same
`scripts.bulk_ingest._ingest()` call WO-921/WO-1005 use). A pick with
video but no captions goes through `app.platforms.queue_probe.
finish_candidate()` -- the shared tier-3 finish step (probes duration,
appends the sidecar row, and queues/defers/rejects) rather than the
manual "skip and print a queue line" WO-921 used before that helper
existed. A pick with no playable video at all (real and common on New
Mexico -- streams flagged "not enabled") is skipped and reported, nothing
written anywhere.

    DATABASE_URL="sqlite+aiosqlite:////tmp/wo1010_scratch.db" PYTHONPATH=. \\
        .venv/bin/python scripts/wo1010_sweep.py --dry-run
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo1010_scratch.db" PYTHONPATH=. \\
        .venv/bin/python scripts/wo1010_sweep.py
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
from pathlib import Path

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv("/Users/mroconnell/Documents/rtr-deeplink/.env")

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import detect_platform, get_finder  # noqa: E402
from app.platforms.queue_probe import finish_candidate  # noqa: E402
from app.utils.url_normalize import normalize_url  # noqa: E402
from scripts.bulk_ingest import _ingest  # noqa: E402

register_all_finders()

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
OUT_CSV = RESEARCH_DIR / "wo1010_handread.csv"

_H = "https://sg001-harmony.sliq.net"
_P = "Harmony/en/PowerBrowser/PowerBrowserV3"


def _sliq_url(tenant: str, event_id: str) -> str:
    # Any date segment works -- the adapter rebuilds a stable source_url
    # from the meeting's own start date, see sliq_harmony.py's docstring.
    return f"{_H}/{tenant}/{_P}/20260101/-1/{event_id}"


# (gov_id, state, tenant, event_id) -- see this module's docstring for how
# each was hand-picked from a real listing read.
PICKS = [
    # Arkansas -- ALC (Arkansas Legislative Council) and its subcommittees.
    ("us:state:05", "Arkansas", "00284", "34486"),
    ("us:state:05", "Arkansas", "00284", "34485"),
    ("us:state:05", "Arkansas", "00284", "34482"),
    ("us:state:05", "Arkansas", "00284", "34480"),
    # Colorado
    ("us:state:08", "Colorado", "00327", "18952"),
    ("us:state:08", "Colorado", "00327", "18945"),
    ("us:state:08", "Colorado", "00327", "18918"),
    ("us:state:08", "Colorado", "00327", "18906"),
    # Delaware -- all 4 remaining real candidates (only 5 total exist).
    ("us:state:10", "Delaware", "00329", "6771"),
    ("us:state:10", "Delaware", "00329", "6769"),
    ("us:state:10", "Delaware", "00329", "6728"),
    ("us:state:10", "Delaware", "00329", "6722"),
    # Kansas -- no captions on any Kansas meeting read so far; tier-3 only.
    ("us:state:20", "Kansas", "00287", "22755"),
    ("us:state:20", "Kansas", "00287", "22728"),
    ("us:state:20", "Kansas", "00287", "22701"),
    ("us:state:20", "Kansas", "00287", "22661"),
    # New Mexico -- real interim committees; NM often has no recording
    # published at all (stream flagged not enabled), so more candidates
    # than final picks -- unresolvable ones are reported and skipped.
    ("us:state:35", "New Mexico", "00293", "81085"),
    ("us:state:35", "New Mexico", "00293", "81082"),
    ("us:state:35", "New Mexico", "00293", "81080"),
    ("us:state:35", "New Mexico", "00293", "81074"),
    # Oklahoma House
    ("us:state:40", "Oklahoma (House)", "00283", "56231"),
    ("us:state:40", "Oklahoma (House)", "00283", "56219"),
    ("us:state:40", "Oklahoma (House)", "00283", "56203"),
    ("us:state:40", "Oklahoma (House)", "00283", "56229"),
    # Oklahoma Senate
    ("us:state:40", "Oklahoma (Senate)", "00282", "82371"),
    ("us:state:40", "Oklahoma (Senate)", "00282", "82378"),
    ("us:state:40", "Oklahoma (Senate)", "00282", "82365"),
    ("us:state:40", "Oklahoma (Senate)", "00282", "82389"),
    # West Virginia
    ("us:state:54", "West Virginia", "00289", "59079"),
    ("us:state:54", "West Virginia", "00289", "59076"),
    ("us:state:54", "West Virginia", "00289", "59072"),
    ("us:state:54", "West Virginia", "00289", "59069"),
    # Maine -- video only, tier-3.
    ("us:state:23", "Maine", "00281", "28474"),
    ("us:state:23", "Maine", "00281", "28473"),
    ("us:state:23", "Maine", "00281", "28464"),
    ("us:state:23", "Maine", "00281", "28462"),
    # Iowa -- video only, tier-3; only 2 real candidates remain.
    ("us:state:19", "Iowa", "00285", "38039"),
    ("us:state:19", "Iowa", "00285", "38037"),
    # Nevada
    ("us:state:32", "Nevada", "00324", "18400"),
    ("us:state:32", "Nevada", "00324", "18344"),
    ("us:state:32", "Nevada", "00324", "18329"),
    ("us:state:32", "Nevada", "00324", "17962"),
    # Missouri -- only 5 real candidates remain.
    ("us:state:29", "Missouri", "00325", "15580"),
    ("us:state:29", "Missouri", "00325", "15578"),
    ("us:state:29", "Missouri", "00325", "15570"),
    # Virginia
    ("us:state:51", "Virginia", "00304", "21672"),
    ("us:state:51", "Virginia", "00304", "21655"),
    ("us:state:51", "Virginia", "00304", "21650"),
    ("us:state:51", "Virginia", "00304", "21645"),
    # Pennsylvania (House only) -- only 2 real candidates remain.
    ("us:state:42", "Pennsylvania", "00328", "1045"),
    ("us:state:42", "Pennsylvania", "00328", "1044"),
]

FIELDS = [
    "gov_id",
    "state",
    "tenant",
    "event_id",
    "url",
    "title",
    "date",
    "video_url",
    "segments",
    "meeting_body",
    "result",
    "page_url_or_queue_action",
]


async def main(dry: bool, only: str) -> None:
    rows = []
    async with aiohttp.ClientSession() as session:
        for gov_id, state, tenant, event_id in PICKS:
            url = _sliq_url(tenant, event_id)
            if only and only not in state:
                continue
            platform = detect_platform(url)
            try:
                res = await get_finder(platform).resolve(url)
            except Exception as e:
                print(f"[{state}] {event_id}: RESOLVE FAILED: {e}", flush=True)
                await asyncio.sleep(1.5)
                continue

            row = {
                "gov_id": gov_id,
                "state": state,
                "tenant": tenant,
                "event_id": event_id,
                "url": normalize_url(res.source_url or url),
                "title": res.title,
                "date": res.date,
                "video_url": res.video_url or "",
                "segments": len(res.segments or []),
                "meeting_body": res.meeting_body,
                "result": "dry-run",
                "page_url_or_queue_action": "",
            }
            print(
                f"[{state}] {event_id} {res.title!r} date={res.date} "
                f"video={bool(res.video_url)} segments={row['segments']}",
                flush=True,
            )

            if not res.video_url:
                row["result"] = "skipped: no video (stream not enabled/published)"
            elif dry:
                row["result"] = (
                    "dry-run: would ingest (captions)"
                    if res.segments
                    else "dry-run: would queue via finish_candidate (no captions)"
                )
            elif res.segments:
                payload = res.model_dump()
                payload["gov_id"] = gov_id
                try:
                    resp = await _ingest(
                        session, payload, normalize_url(res.source_url or url)
                    )
                except Exception as e:
                    row["result"] = f"ingest-failed: {e}"
                else:
                    if resp is None:
                        row["result"] = "ingest-failed"
                    else:
                        row["result"] = "created" if resp.get("created") else "existing"
                        row["page_url_or_queue_action"] = resp.get("url") or ""
                print(
                    f"  -> {row['result']} {row['page_url_or_queue_action']}",
                    flush=True,
                )
            else:
                outcome = await finish_candidate(
                    res.source_url or url,
                    video_url=res.video_url,
                    source_url=res.source_url or url,
                    platform=platform,
                    video_format=res.video_format,
                    gov_id=gov_id,
                    jurisdiction=res.jurisdiction or state,
                    title=res.title or "",
                    caller="wo1010_sweep",
                )
                row["result"] = f"finish_candidate: {outcome.action}"
                row["page_url_or_queue_action"] = outcome.action
                print(
                    f"  -> action={outcome.action} "
                    f"probe_verdict={outcome.probe.verdict}",
                    flush=True,
                )
            rows.append(row)
            await asyncio.sleep(2)

    if not dry:
        new = not OUT_CSV.exists()
        with open(OUT_CSV, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new:
                w.writeheader()
            w.writerows(rows)

    ingested = sum(1 for r in rows if r["result"] in ("created", "existing"))
    queued = sum(
        1
        for r in rows
        if r["result"].startswith("finish_candidate")
        and "queued" in r["page_url_or_queue_action"]
    )
    skipped = sum(1 for r in rows if r["result"].startswith("skipped"))
    print(
        f"\n{len(rows)} resolved, {ingested} ingested, {queued} queued, {skipped} skipped (no video)."
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default="", help="only picks whose state contains this")
    a = ap.parse_args()
    asyncio.run(main(a.dry_run, a.only))
