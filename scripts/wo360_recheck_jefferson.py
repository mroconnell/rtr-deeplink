"""One-off recheck: `jeffersoncountywv.org` (bare, no www) 404s for real;
`www.jeffersoncountywv.org` is the working site. Confirmed live via a
direct fetch while investigating `wo360_verify.py`'s fetch_failed result
for Jefferson County. This script re-runs `verify_hub()` against the
working www host so the government gets a real verdict instead of a
stale "domain is broken" one, and the finding (the county corrections
file's `jeffersoncountywv.org` needs a www prefix) is noted in
BACKLOG.md separately.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.passive_verify import verify_hub  # noqa: E402

register_all_finders()


async def main():
    result = await verify_hub(
        "https://www.jeffersoncountywv.org",
        name="Jefferson County",
        state="West Virginia",
        deep_walk=True,
    )
    print("verdict:", result.verdict)
    print("tier:", result.tier)
    print("meeting_found:", result.meeting_found)
    print("video_found:", result.video_found)
    print("captions_found:", result.captions_found)
    print("meeting_url:", result.meeting_url)
    print("platform:", result.platform)
    print("evidence:", (result.evidence or "")[:400])


asyncio.run(main())
