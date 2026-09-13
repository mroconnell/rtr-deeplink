"""WO-347 Part A: probe + finish (queue or defer) the 9 real, hand-checked
tier-3 candidates the tier-4 walker rerun found (see wo347_rerun_verify.csv
and this WO's BACKLOG_DONE.md entry for the hand-check writeup). Lebanon
city MO (event/461) is deliberately excluded -- jurisdiction_coverage.csv
already carries a correct video-no-captions-queued row for the same
government's same CivicClerk tenant (event/460), so "one meeting per
government" is already satisfied. Larned city KS (Vimeo, no obtainable
title even with the government's own domain as Referer) and Olmos Park
city TX (CivicClerk `video_url` is a genuine audio/mp3 file, confirmed by
a live Content-Type check, not video) are excluded for hand-read reasons,
not duration.

Adds a per-video (eScribe/CivicClerk: per-tenant, since those hosts are
one government each) or per-video (Town Hall Streams: shared host, pinned
by `location_id=<N>`) pin alongside the queue line, exactly like
scripts/wo345_apply_to_jc.py's own pins.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.queue_probe import (  # noqa: E402
    append_queue_line,
    finish_candidate,
    write_pin_row,
)

register_all_finders()

CANDIDATES = [
    dict(
        meeting_url="https://lenaweecomi.portal.civicclerk.com/event/2874/media",
        video_url="https://cpmedia.azureedge.net/lenaweecomi/48761e2cdf.mp4",
        source_url="https://lenaweecomi.portal.civicclerk.com/event/2874/media",
        platform="civicclerk",
        gov_id="us:county:26091",
        jurisdiction="Lenawee County, MI",
        title="Emergency 911 District Board",
        pin=dict(
            host="lenaweecomi.portal.civicclerk.com",
            match="",
            gov_id="us:county:26091",
            source="wo347",
            evidence=(
                "Lenawee County, MI -- WO-347 tier-4 walker rerun; verify_hub()'s "
                "CivicClerk listing walker found a real Emergency 911 District Board "
                "meeting (event/2874, 2026-09-10), video, no captions."
            ),
        ),
    ),
    dict(
        meeting_url="https://pub-amherst.escribemeetings.com/Meeting.aspx?Id=a3cbb212-f269-4682-a144-654f3c2382d4",
        video_url="https://cdn1.isilive.ca/vod/_definst_/mp4:amherst/lite_encoder_Planning%20Advisory%20Committee_2026-09-08-03-29.mp4/playlist.m3u8",
        source_url="https://pub-amherst.escribemeetings.com/Meeting.aspx?Id=a3cbb212-f269-4682-a144-654f3c2382d4",
        platform="escribe",
        gov_id="ca:csd:1211011",
        jurisdiction="Amherst, NS",
        title="Planning Advisory Committee",
        pin=dict(
            host="pub-amherst.escribemeetings.com",
            match="",
            gov_id="ca:csd:1211011",
            source="wo347",
            evidence=(
                "Amherst, NS -- WO-347 tier-4 walker rerun; verify_hub()'s eScribe "
                "listing walker found a real Planning Advisory Committee meeting "
                "(2026-09-08), video, no captions."
            ),
        ),
    ),
    dict(
        # WO-347's own newest real candidate (Id=d540b019..., 2026-09-09)
        # probed at 134.0 min, over the 90-min defer threshold. Per
        # CLAUDE.md's "long-only videos" rule, looked one meeting deeper
        # on the same eScribe tenant (scripts/wo347_long_lookdeeper.py):
        # the next 7 candidates ran 47.5-136.5 min, none under 40; queued
        # the shortest of those found, a real Committee of the Whole
        # meeting 2 months earlier on the same tenant.
        meeting_url="https://pub-chocolatetown.escribemeetings.com/Meeting.aspx?Id=2fd2d858-d945-43a6-a5d8-cd21d7e1b890",
        video_url="https://cdn1.isilive.ca/vod/_definst_/mp4:ststephen/Compact%20Encoder%201338_CoW_2026-07-08-04-54.mp4/playlist.m3u8",
        source_url="https://pub-chocolatetown.escribemeetings.com/Meeting.aspx?Id=2fd2d858-d945-43a6-a5d8-cd21d7e1b890",
        platform="escribe",
        gov_id="ca:csd:1302037",
        jurisdiction="St. Stephen, NB",
        title="Committee of the Whole",
        pin=dict(
            host="pub-chocolatetown.escribemeetings.com",
            match="",
            gov_id="ca:csd:1302037",
            source="wo347",
            evidence=(
                "St. Stephen, NB -- WO-347 tier-4 walker rerun; verify_hub()'s eScribe "
                "listing walker found a real Committee of the Whole meeting on the "
                "town's own tenant. Newest candidate (2026-09-09) probed at 134.0 min "
                "(over 90); looked one meeting deeper and queued a shorter real "
                "Committee of the Whole meeting (2026-07-08, 47.5 min) on the same "
                "tenant instead. Tenant name 'chocolatetown' is St. Stephen's own "
                "nickname (Canada's Chocolate Town)."
            ),
        ),
    ),
    dict(
        # Newest real candidate (id=76256, Plan Commission, 2026-08-25)
        # probed at 131.1 min, over 90. Looked deeper on the same tenant
        # (scripts/wo347_long_lookdeeper.py): id=75561 (Redevelopment
        # Commission, 2026-07-02) probed at 15.3 min -- inside the
        # preferred 9-40 min window.
        meeting_url="https://townhallstreams.com/stream.php?location_id=144&id=75561",
        video_url="https://cdn.townhallstreams.com/vod/_definst_/mp4:pittsboro_IN/2026-07-02_6223771_Redevelopment_Commission.mp4/playlist.m3u8",
        source_url="https://townofpittsboro.org/",
        platform="townhallstreams",
        gov_id="us:place:1860192",
        jurisdiction="Pittsboro, IN",
        title="Redevelopment Commission",
        pin=dict(
            host="townhallstreams.com",
            match="location_id=144",
            gov_id="us:place:1860192",
            source="wo347",
            evidence=(
                "Pittsboro town, IN -- WO-347 tier-4 walker rerun; CivicPlus "
                "ranking-fix preferred the real Town Hall Streams vendor link over "
                "the CivicPlus AgendaCenter aggregator. Newest candidate (Plan "
                "Commission, 2026-08-25) probed at 131.1 min (over 90); looked one "
                "meeting deeper and queued a shorter real Redevelopment Commission "
                "meeting (2026-07-02, 15.3 min) on the same tenant instead."
            ),
        ),
    ),
    dict(
        # Newest real candidate (Regular Council Meeting, 2026-09-01)
        # probed at 281.9 min. Looked one meeting deeper on the same
        # tenant (scripts/wo347_long_lookdeeper.py): the next 7 real
        # candidates ran 98.7-425.8 min -- nothing under 90 exists in
        # this sample. Per CLAUDE.md's "queue the shortest found" rule,
        # queued the shortest of those checked (Special Council Meeting,
        # 2026-07-27, 98.7 min) rather than the original 281.9-min one.
        meeting_url="https://pub-llbc.escribemeetings.com/Meeting.aspx?Id=d65f3cd3-1982-42b7-b26c-9ffc58820dad",
        video_url="https://cdn1.isilive.ca/vod/_definst_/mp4:laclabiche/Compact%20Encoder%201220_Special%20Council%20Meeting_2026-07-27-12-17.mp4/playlist.m3u8",
        source_url="https://pub-llbc.escribemeetings.com/Meeting.aspx?Id=d65f3cd3-1982-42b7-b26c-9ffc58820dad",
        platform="escribe",
        gov_id="ca:csd:4812037",
        jurisdiction="Lac la Biche County, AB",
        title="Special Council Meeting",
        pin=dict(
            host="pub-llbc.escribemeetings.com",
            match="",
            gov_id="ca:csd:4812037",
            source="wo347",
            evidence=(
                "Lac la Biche County, AB -- WO-347 tier-4 walker rerun; verify_hub()'s "
                "eScribe listing walker found a real Special Council Meeting "
                "(2026-07-27, 98.7 min), video, no captions -- shortest of 8 real "
                "candidates checked after the newest (281.9 min) went over the "
                "90-min threshold; nothing under 90 min was found on this tenant, "
                "so per CLAUDE.md's 'queue the shortest' rule this one was queued "
                "rather than deferred. Tenant 'llbc' matches the county's own "
                "initials."
            ),
        ),
    ),
    dict(
        meeting_url="https://pub-leduc-county.escribemeetings.com/Meeting.aspx?Id=7a7ead34-c154-4b36-afa9-ac932bd7d345",
        video_url="https://cdn1.isilive.ca/vod/_definst_/mp4:leduccounty/iSiLIVE%20Encoder%20749_CM_2026-09-08-03-29.mp4/playlist.m3u8",
        source_url="https://pub-leduc-county.escribemeetings.com/Meeting.aspx?Id=7a7ead34-c154-4b36-afa9-ac932bd7d345",
        platform="escribe",
        gov_id="ca:csd:4811012",
        jurisdiction="Leduc County, AB",
        title="Council meeting",
        pin=dict(
            host="pub-leduc-county.escribemeetings.com",
            match="",
            gov_id="ca:csd:4811012",
            source="wo347",
            evidence=(
                "Leduc County, AB -- WO-347 tier-4 walker rerun; verify_hub()'s "
                "eScribe listing walker found a real Council meeting (2026-09-08), "
                "video, no captions."
            ),
        ),
    ),
    dict(
        meeting_url="https://townhallstreams.com/stream.php?location_id=36&id=76337",
        video_url="https://cdn.townhallstreams.com/vod/_definst_/mp4:eliot_remote_meeting/2026-09-10_468582_Select_Board_Meeting_with_Owl_Remote.mp4/playlist.m3u8",
        source_url="https://eliotme.gov/",
        platform="townhallstreams",
        gov_id="us:cousub:2303122955",
        jurisdiction="Eliot, ME",
        title="Select Board Meeting with Owl Remote",
        pin=dict(
            host="townhallstreams.com",
            match="location_id=36",
            gov_id="us:cousub:2303122955",
            source="wo347",
            evidence=(
                "Eliot town, ME -- WO-347 tier-4 walker rerun; verify_hub()'s Town "
                "Hall Streams listing walker found a real Select Board meeting "
                "(2026-09-10), video, no captions."
            ),
        ),
    ),
    dict(
        meeting_url="https://townhallstreams.com/stream.php?location_id=53&id=76669",
        video_url="https://cdn.townhallstreams.com/vod/_definst_/mp4:boothbay/2026-09-09_2859555_BOS.mp4/playlist.m3u8",
        source_url="https://townofboothbay.org/",
        platform="townhallstreams",
        gov_id="us:cousub:2301506050",
        jurisdiction="Boothbay, ME",
        title="BOS (Board of Selectmen)",
        pin=dict(
            host="townhallstreams.com",
            match="location_id=53",
            gov_id="us:cousub:2301506050",
            source="wo347",
            evidence=(
                "Boothbay town, ME -- WO-347 tier-4 walker rerun; verify_hub()'s "
                "Town Hall Streams listing walker found a real Board of Selectmen "
                "meeting (2026-09-09), video, no captions."
            ),
        ),
    ),
    dict(
        # Newest real candidate (Capital Improvement Committee, 2026-09-09)
        # probed at 108.6 min, over 90. Looked deeper on the same tenant
        # (scripts/wo347_long_lookdeeper.py): id=73429 (Cemetery Trustees,
        # 2026-09-03) probed at 28.1 min -- inside the preferred window.
        meeting_url="https://townhallstreams.com/stream.php?location_id=107&id=73429",
        video_url="https://cdn.townhallstreams.com/vod/_definst_/mp4:hamptonfalls/2026-09-03_3962446_Cemetery_Trustees.mp4/playlist.m3u8",
        source_url="https://hamptonfalls.org/",
        platform="townhallstreams",
        gov_id="us:cousub:3301533460",
        jurisdiction="Hampton Falls, NH",
        title="Cemetery Trustees",
        pin=dict(
            host="townhallstreams.com",
            match="location_id=107",
            gov_id="us:cousub:3301533460",
            source="wo347",
            evidence=(
                "Hampton Falls town, NH -- WO-347 tier-4 walker rerun; verify_hub()'s "
                "Town Hall Streams listing walker found a real Capital Improvement "
                "Committee meeting on the town's own tenant. Newest candidate "
                "(2026-09-09) probed at 108.6 min (over 90); looked one meeting "
                "deeper and queued a shorter real Cemetery Trustees meeting "
                "(2026-09-03, 28.1 min) on the same tenant instead."
            ),
        ),
    ),
]

# Lac la Biche's own chosen candidate (98.7 min) is itself over the
# automatic 90-min defer threshold -- nothing shorter exists on this
# tenant among the 8 real candidates checked (scripts/
# wo347_long_lookdeeper.py; the rest ran 246-425 min). Per CLAUDE.md's
# "queue the shortest found, even over 90, once no shorter real
# alternative exists" rule (WO-345's Sand Lake NY precedent, 119.9 min),
# this one is queued directly rather than through finish_candidate()'s
# automatic >90-min defer path.
FORCE_QUEUE_GOV_IDS = {"ca:csd:4812037"}


async def main():
    for c in CANDIDATES:
        if c["gov_id"] in FORCE_QUEUE_GOV_IDS:
            queued = append_queue_line(c["meeting_url"], c["source_url"])
            pinned = write_pin_row(**c["pin"])
            print(
                f"{c['gov_id']} ({c['jurisdiction']}): action=force-queued "
                f"queued={queued} pinned={pinned} (over 90 min, no shorter "
                f"real alternative found -- queued anyway per CLAUDE.md)"
            )
            continue
        outcome = await finish_candidate(
            c["meeting_url"],
            video_url=c.get("video_url"),
            source_url=c["source_url"],
            platform=c["platform"],
            gov_id=c["gov_id"],
            jurisdiction=c["jurisdiction"],
            title=c["title"],
            pin=c["pin"],
            caller="wo347",
        )
        print(
            f"{c['gov_id']} ({c['jurisdiction']}): action={outcome.action} "
            f"duration={outcome.probe.duration_seconds} verdict={outcome.probe.verdict} "
            f"reason={outcome.probe.reason} queued={outcome.queued} pinned={outcome.pinned}"
        )


if __name__ == "__main__":
    asyncio.run(main())
