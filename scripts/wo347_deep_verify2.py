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
    (
        "eatwp.org (real civicweb)",
        "https://eatwp.diligent.community/Portal/MeetingTypeList.aspx",
        "civicweb",
    ),
    ("silverbeach.ca", "https://www.silverbeach.ca/council/minutes", None),
    ("sundancebeach.ca", "https://www.sundancebeach.ca/council/minutes", None),
    (
        "hinckleytown.org",
        "https://hinckleytown.utah.gov/Town%20Government/Town%20Council%20Agenda.html",
        None,
    ),
    ("woodruff.utah.gov", "https://woodruff.utah.gov/meetings/", None),
]


async def main():
    for label, url, hint in TARGETS:
        try:
            res = await verify_hub(url, platform_hint=hint)
            print(
                f"{label}: verdict={res.verdict} tier={res.tier} meeting_found={res.meeting_found} video_found={res.video_found}"
            )
            print(f"    evidence: {res.evidence[:250]}")
        except Exception as e:
            print(f"{label}: EXCEPTION {type(e).__name__}: {e}")


asyncio.run(main())
