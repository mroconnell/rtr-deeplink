#!/usr/bin/env python3
"""WO-919: passive check on state-legislature vendor hubs learned during the
hand pass (a recon row's hub led to a real vendor tenant the recon table did
not name: Granicus for VA/NV/CO/TN/NY, Cablecast for RI, Invintus/AZ). Same
`verify_hub(..., deep_walk=True)` call as wo919_verify.py; results append to
research/wo919_hub_verify.csv with phase "passive-extra".

    DATABASE_URL="sqlite+aiosqlite:////tmp/wo919_scratch.db" \\
        .venv/bin/python scripts/wo919_extra_hubs.py URL [URL ...]
"""

from __future__ import annotations

import asyncio
import csv
import sys

import scripts.wo919_verify as base  # noqa: E402


async def main() -> None:
    with open(base.HUB_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=base.FIELDNAMES)
        for hub in sys.argv[1:]:
            out = await base.passive_one(hub)
            out["phase"] = "passive-extra"
            w.writerow(out)
            f.flush()
            print(
                f"{hub[:80]} -> {out['verdict']} tier={out['tier']} "
                f"plat={out['resolved_platform']} meeting={out['meeting_url'][:80]} {out['error'][:80]}",
                flush=True,
            )
            await asyncio.sleep(1.5)


if __name__ == "__main__":
    asyncio.run(main())
