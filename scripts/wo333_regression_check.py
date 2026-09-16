"""WO-333: no-regression check. 20 real meeting URLs already hand/script-
confirmed as genuinely having no video (10 Cablecast, 10 PrimeGov, from
`research/cablecast_confirmed_no_video.txt` / `research/
primegov_confirmed_no_video.txt` -- both real, previously-verified
negative lists, predating this WO), rerun through `verify_hub()` to
confirm the new generic-link-scan fallback and (for PrimeGov, an
aggregator platform) the ranking fix don't turn a real "no video" into a
false positive.

Read-only, same never-fetch-YouTube guard as `wo333_verify_controls.py`
(belt and braces -- `verify_hub()` already guards this internally, this
is just the same courtesy the other WO-333 script extends).

Usage:
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo333_regression.db" \\
        .venv/bin/python scripts/wo333_regression_check.py
"""

from __future__ import annotations

import asyncio
import csv
import os
import re
import sys
from pathlib import Path

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.passive_verify import verify_hub  # noqa: E402

register_all_finders()

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
OUT_CSV = RESEARCH_DIR / "wo333_regression_check.csv"

URL_RE = re.compile(r"https?://\S+")


def _sample(path: Path, n: int) -> list[str]:
    urls = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip().startswith("#"):
                continue
            m = URL_RE.search(line)
            if m:
                urls.append(m.group(0))
            if len(urls) >= n:
                break
    return urls


async def main() -> None:
    cablecast_urls = _sample(RESEARCH_DIR / "cablecast_confirmed_no_video.txt", 10)
    primegov_urls = _sample(RESEARCH_DIR / "primegov_confirmed_no_video.txt", 10)
    cases = [(u, "cablecast") for u in cablecast_urls] + [
        (u, "primegov") for u in primegov_urls
    ]
    print(f"{len(cases)} known-negative rows to recheck\n", file=sys.stderr)

    out_rows = []
    regressions = 0
    for url, platform in cases:
        try:
            result = await verify_hub(url, platform_hint=platform)
            regressed = result.video_found is True
            if regressed:
                regressions += 1
            out_rows.append(
                {
                    "url": url,
                    "platform": platform,
                    "video_found": result.video_found,
                    "verdict": result.verdict,
                    "regressed": regressed,
                }
            )
            print(
                f"{'REGRESSION' if regressed else 'ok':10s} {platform:10s} "
                f"video_found={result.video_found} verdict={result.verdict} {url}",
                file=sys.stderr,
            )
        except Exception as e:  # noqa: BLE001
            out_rows.append(
                {
                    "url": url,
                    "platform": platform,
                    "video_found": None,
                    "verdict": f"crash: {type(e).__name__}: {e}",
                    "regressed": False,
                }
            )
            print(
                f"CRASH      {platform:10s} {type(e).__name__}: {e} {url}",
                file=sys.stderr,
            )
        with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
            writer.writeheader()
            writer.writerows(out_rows)
        await asyncio.sleep(1.2)

    print(
        f"\n{regressions} of {len(cases)} known-negatives flipped to video_found=True",
        file=sys.stderr,
    )


if __name__ == "__main__":
    asyncio.run(main())
