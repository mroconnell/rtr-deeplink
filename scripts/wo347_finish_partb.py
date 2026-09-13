"""WO-347 Part B: queue the one real false-negative video the 60-
government audit sample found -- Upper Providence township, PA
(us:cousub:4204579248), previously recorded `no-meeting-nor-video`.
`verify_hub()`'s CivicClerk listing walker found a real event whose
CivicClerk jurisdiction field reads 'Phoenixville, PA' (a postal-address
quirk, not the real government -- same pattern as WO-345's North
Hempstead/Manhasset pin), but the video itself delegates to Swagit
(tenant `uprovmontco` = Upper Providence, Montgomery County), whose own
adapter resolves `jurisdiction='Upper Providence, PA'` directly --
confirms this is genuinely the township's own meeting. Real Sep 02, 2026
Planning Commission meeting, 81.6 min (accepted, under the 90-min defer
threshold).
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
from app.platforms.queue_probe import finish_candidate  # noqa: E402

register_all_finders()


async def main():
    outcome = await finish_candidate(
        "https://uprovmontco.new.swagit.com/videos/399867",
        video_url=(
            "https://archive-stream.granicus.com/OnDemand/_definst_/"
            "mp4:swagitVideo/uprovmontco/6a0b9bfc-8944-4c8d-a08d-5810f0b2fdcc.mp4/"
            "playlist.m3u8"
        ),
        source_url="https://upperprovidencetwppa.portal.civicclerk.com/event/1908/media",
        platform="swagit",
        gov_id="us:cousub:4204579248",
        jurisdiction="Upper Providence, PA",
        title="Sep 02, 2026 Planning Commission",
        pin=dict(
            host="uprovmontco.new.swagit.com",
            match="",
            gov_id="us:cousub:4204579248",
            source="wo347",
            evidence=(
                "Upper Providence township, PA -- WO-347 Part B audit sample "
                "(stratum: nothing-walkable). verify_hub()'s CivicClerk listing "
                "walker on upperprovidencetwppa.portal.civicclerk.com found a real "
                "Planning Commission meeting (event/1908, 2026-09-02); the "
                "CivicClerk event's own jurisdiction field reads 'Phoenixville, PA' "
                "(a postal-address quirk -- Upper Providence Township's mailing "
                "address, not a different government), but the video delegates to "
                "Swagit tenant 'uprovmontco' (Upper Providence, Montgomery County), "
                "whose own adapter resolves jurisdiction='Upper Providence, PA' "
                "directly -- confirms the real owner. 81.6 min, accepted."
            ),
        ),
        caller="wo347",
    )
    print(
        f"action={outcome.action} duration={outcome.probe.duration_seconds} "
        f"verdict={outcome.probe.verdict} queued={outcome.queued} pinned={outcome.pinned}"
    )


if __name__ == "__main__":
    asyncio.run(main())
