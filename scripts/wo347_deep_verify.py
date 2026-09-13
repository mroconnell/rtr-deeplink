import asyncio
import os
import sys
import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.platforms import register_all_finders
from app.platforms.passive_verify import verify_hub

register_all_finders()

TARGETS = [
    ("fernie.ca", "https://fernie.civicweb.net/", "civicweb"),
    (
        "ferristexas.gov",
        "https://ferris-texas.community.diligentoneplatform.com/Portal/MeetingSchedule.aspx",
        "civicweb",
    ),
    (
        "shady-shores.com",
        "https://tx-shadyshores2.civicplus.com/AgendaCenter",
        "civicplus",
    ),
    ("plainsboronj.com", "https://www.plainsboronj.com/AgendaCenter", "civicplus"),
    (
        "ecmetro.org (real domain emigration.utah.gov)",
        "https://emigration.utah.gov/agendacenter",
        "civicplus",
    ),
    (
        "lowersaucontownship.org",
        "https://lowersaucontownship.community.diligentoneplatform.com/Portal/MeetingSchedule.aspx",
        "civicweb",
    ),
    (
        "upperprovmcpa.gov",
        "https://upperprovidencetwppa.portal.civicclerk.com/",
        "civicclerk",
    ),
    (
        "doylestownpa.iqm2.com",
        "https://doylestownpa.iqm2.com/Citizens/default.aspx",
        "iqm2",
    ),
]


async def main():
    for label, url, hint in TARGETS:
        try:
            res = await verify_hub(url, platform_hint=hint)
            print(
                f"{label}: verdict={res.verdict} tier={res.tier} meeting_found={res.meeting_found} video_found={res.video_found} meeting_url={res.meeting_url}"
            )
            print(f"    evidence: {res.evidence[:250]}")
        except Exception as e:
            print(f"{label}: EXCEPTION {type(e).__name__}: {e}")


asyncio.run(main())
