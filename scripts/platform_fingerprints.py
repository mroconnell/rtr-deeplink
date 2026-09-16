#!/usr/bin/env python3
"""WO-267 (2026-09-12): measured platform-fingerprint matcher.

`detect_platform()` (`app/platforms/base.py`) and the access ladder's own
`_PLATFORM_ALIASES` (`scripts/wo147_access_ladder_sweep.py`) only
recognize a platform when a vendor HOSTNAME appears on the page. That
misses first-party embeds (CivicWeb's `Portal/MeetingInformation.aspx`,
IQM2's `/Citizens/`, a Hyland/OnBase tenant on its own custom domain with
no `hylandcloud.com` anywhere on the page) and narrower path shapes that
are *more* reliable than the bare hostname once a fetch has already
happened (Granicus's `/player/clip/{id}`, eScribe's
`pub-{tenant}.escribemeetings.com`).

This module is ONE thing: given a page's HTML, response headers, and the
URL it came from, return every matching signal with its OWN measured
hit-rate/false-positive-rate as a confidence score. It does not fetch
anything itself (`fetch_once()` is a thin honest-headers helper, same
convention as `cms_fingerprint.fetch_once()`). It does not decide a
page's site-builder/CMS family either -- `scripts/cms_fingerprint.py`
already does that (WO-154/WO-179) and this module calls it directly
(`classify_site_builder()` below) rather than duplicating those rules.

Every signal in `app/utils/jurisdiction_data/platform_signatures.csv` was
measured against a real, live-fetched sample (WO-267, 2026-09-12): each
row's `hit_rate` is how often the pattern matched a positive sample of
real governments already known to use that platform (10 per platform
where the research file had that many `transcribed=true` rows; fewer are
noted in `docs/investigations/platform_fingerprints.md`), and
`false_positive_rate` is how often it matched a combined negative set
(~200 governments with a DIFFERENT known platform, ~200 with no known
platform). Only signals with hit_rate >= 0.90 and false_positive_rate
<= 0.05 are in this file -- weaker candidates are logged as leads in the
docs, not silently dropped and not silently included.

Matching is a plain regex search over (HTML body + the page's own final
URL), the same approach `cms_fingerprint.classify()` uses -- not a DOM
walk. A signal belonging to the page's OWN host (e.g. a `pub-<tenant>.
escribemeetings.com` tenant whose body text never happens to spell out
its own hostname) still counts as a hit via the URL half of that
search text, the same way `detect_platform()` itself classifies by URL.

WO-270 (2026-09-12) measured a battery of WordPress-specific candidate
signals (a literal video-host link on the front page, in `/feed/`, in
the REST posts-search endpoint, and in site search; custom post types;
plugin/theme/`/wp-json/` namespace names) against 127 WordPress
governments with a known video and 150 confirmed no-video. None cleared
the 90%/5% bar, so no `platform=wordpress` rows or new `kind` values
were added here -- see `docs/investigations/platform_fingerprints.md`'s
WO-270 addendum and `~/Documents/rtr-business/research/
ENUMERATION_METHODS.md` §295 for the full near-miss numbers (the
closest: a literal `youtube.com` link on the front page, 65% hit / 7%
false-positive) before spending more effort on a WordPress-specific
signal here.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

try:
    import requests
except ImportError:  # pragma: no cover - CLI-only dependency
    requests = None

SIGNATURES_CSV = (
    Path(__file__).resolve().parent.parent
    / "app"
    / "utils"
    / "jurisdiction_data"
    / "platform_signatures.csv"
)

HONEST_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-encoding": "gzip, deflate",
    "accept-language": "en-US,en;q=0.9",
    "user-agent": (
        "rtr-upcoming/0.1 (Red Tape Recordings public-agenda reader; "
        "+https://redtaperecordings.com/about)"
    ),
}
REQUEST_TIMEOUT = 10


@dataclass(frozen=True)
class Signature:
    platform: str
    signal_id: str
    kind: str
    pattern: str
    hit_rate: float
    false_positive_rate: float
    needs_render: bool
    sample_size: int
    measured_on: str
    description: str
    regex: "re.Pattern"


@dataclass(frozen=True)
class Match:
    platform: str
    signal_id: str
    confidence: float  # == the signal's own measured hit_rate
    kind: str
    description: str


def load_signatures(path: Path = SIGNATURES_CSV) -> List[Signature]:
    """Loads and compiles every row of platform_signatures.csv.

    A row with an unparseable regex is skipped with a printed warning
    rather than raising -- this is a measurement artifact file edited by
    hand/by future WOs, and one bad row should not take down every other
    platform's matching.
    """
    sigs: List[Signature] = []
    if not path.exists():
        return sigs
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                regex = re.compile(row["pattern"], re.I)
            except re.error as exc:  # pragma: no cover - defensive
                print(
                    f"platform_fingerprints: bad pattern in {row!r}: {exc}",
                    file=sys.stderr,
                )
                continue
            sigs.append(
                Signature(
                    platform=row["platform"],
                    signal_id=row["signal_id"],
                    kind=row["kind"],
                    pattern=row["pattern"],
                    hit_rate=float(row["hit_rate"]),
                    false_positive_rate=float(row["false_positive_rate"]),
                    needs_render=row["needs_render"].strip().lower() == "true",
                    sample_size=int(row["sample_size"]),
                    measured_on=row["measured_on"],
                    description=row["description"],
                    regex=regex,
                )
            )
    return sigs


_SIGNATURES_CACHE: Optional[List[Signature]] = None


def _signatures() -> List[Signature]:
    global _SIGNATURES_CACHE
    if _SIGNATURES_CACHE is None:
        _SIGNATURES_CACHE = load_signatures()
    return _SIGNATURES_CACHE


def fingerprint(
    html: str, headers: Optional[dict] = None, url: str = ""
) -> List[Tuple[str, str, float]]:
    """Returns every matching (platform, signal_id, confidence) triple.

    `confidence` is the signal's own measured hit_rate from
    platform_signatures.csv -- not a combined/Bayesian score across
    multiple matching signals on the same page (a page can and does match
    more than one signal for the same platform, e.g. both a vendor
    hostname and a first-party path; the caller decides how to combine
    them, same as detect_platform()'s callers already decide what to do
    with an "unknown" answer).

    Response headers are accepted for a future `kind=response_header`
    signal (none measured yet -- see the docs' "what the sample could
    not cover" section) and are unused today; HTML body text and the
    page's own final URL are concatenated before matching, so a signal
    tied to the page's OWN host (rather than a link/asset reference
    inside the body) still matches -- the same convention
    `docs/investigations/platform_fingerprints.md`'s measurement pass
    used.
    """
    text = f"{html}\n{url}"
    out: List[Tuple[str, str, float]] = []
    for sig in _signatures():
        if sig.regex.search(text):
            out.append((sig.platform, sig.signal_id, sig.hit_rate))
    return out


def classify_site_builder(html: str, url: str = ""):
    """Delegates to scripts/cms_fingerprint.classify() for the
    site-builder/CMS-family question -- WO-267 measures PLATFORM
    (meeting/video host) signals, not website CMS family, and
    WO-154/WO-179 already built and measured that separately. Returns
    that module's own FingerprintResult (family="unknown" when nothing
    matched)."""
    # Local import (same convention as scripts/wo147_access_ladder_sweep.py
    # importing scripts.wo134_confirmed_hits_ingest): keeps this module
    # importable standalone (`python scripts/platform_fingerprints.py ...`)
    # without requiring cms_fingerprint's own dependencies up front.
    try:
        from scripts import cms_fingerprint
    except ImportError:  # running as `python scripts/platform_fingerprints.py`
        import cms_fingerprint  # type: ignore[no-redef]

    return cms_fingerprint.classify(html, url=url)


def fetch_once(url: str, timeout: int = REQUEST_TIMEOUT):
    if requests is None:  # pragma: no cover
        raise RuntimeError("requests is not installed")
    return requests.get(url, headers=HONEST_HEADERS, timeout=timeout)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Fetch one URL and report every matching platform signal (and site-builder family)."
    )
    ap.add_argument("url")
    ap.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = ap.parse_args()

    resp = fetch_once(args.url)
    matches = fingerprint(resp.text, dict(resp.headers), str(resp.url))
    builder = classify_site_builder(resp.text, url=str(resp.url))

    if args.json:
        print(
            json.dumps(
                {
                    "url": str(resp.url),
                    "status": resp.status_code,
                    "platform_matches": [
                        {"platform": p, "signal_id": s, "confidence": c}
                        for p, s, c in matches
                    ],
                    "site_builder": {
                        "family": builder.family,
                        "rule_id": builder.rule_id,
                        "evidence": builder.evidence,
                    },
                }
            )
        )
        return

    print(f"{args.url} -> {resp.status_code} (final: {resp.url})")
    if matches:
        print("Platform signals matched:")
        for p, s, c in sorted(matches, key=lambda m: -m[2]):
            print(f"  {p:<20} {s:<35} confidence={c:.3f}")
    else:
        print("No measured platform signal matched.")
    print(f"Site builder: {builder.family} (rule={builder.rule_id})")
    if builder.evidence:
        print(f"  evidence: {builder.evidence}")


if __name__ == "__main__":
    main()
