"""Try CivicPlus canonical-host recovery on one vendor address (read-only, polite).

    python scripts/civicplus_canonical_host.py URL DOMAIN [DOMAIN ...]

Prints the recovered address, which authority served it, and the evidence (`listed`,
`fetched` or `structure`), or why nothing was recovered. It never requests the vendor
address. See app/utils/canonical_host.py. Candidate domains come from the caller: a research
row's `domain` and `alternate_domains`.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.utils.canonical_host import recover_civicplus  # noqa: E402


async def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    result = await recover_civicplus(sys.argv[1], sys.argv[2:], delay_s=2.6)
    print(f"original : {result.original_url}")
    if result.recovered:
        print(f"use      : {result.recovered_url}")
        print(f"authority: {result.authority}   evidence: {result.evidence}")
    else:
        print(f"nothing recovered: {result.reason}")
    for authority, why in result.skipped:
        print(f"skipped  : {authority}: {why}")
    return 0 if result.recovered else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
