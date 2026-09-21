"""Compare the old shown transcript with the newest hidden one, page by page.

WO-929, the "review" step of docs/RETRANSCRIPTION_QUEUE.md. After a page has
been transcribed again WITHOUT --promote, the new text sits on the page as a
hidden version and the old text is still what readers see. This prints, for
each page, the objective defect signals of both versions side by side, using
`scripts/wo928_version_quality.py`'s own definitions (dead air, loops, the
hallucination detector, roll-up, coarse cues). Quality is judged from the
text. Cue counts and word counts are never used as a quality signal: the old
Whisper text invents words over silence, and the voice-filtered text has
fewer of them and is not worse for it.

Read-only. It never promotes anything: a person reads the hint column, opens
the two SRT links if in doubt, and promotes with
POST /internal/transcript-version/promote (or re-runs the page with
--promote). Two reads per page from the public site (paced 1 per second) and
one read of /internal/export/pages for the version list.

Usage (from the repo root; the Archive token is read from .env):
    python scripts/retranscription_review.py --section PILOT
    python scripts/retranscription_review.py --page-ids 783,877
    python scripts/retranscription_review.py --section MAIN --count 10

Hint column:
    new-clean         the new version has no defect signal and reaches the
                      old version's last cue (within 5%)
    new-shorter       no defect signal, but it ends more than 5% before the
                      old one: check the SRT before promoting
    new-still-flagged the new version still shows a defect signal
    no-new-version    no hidden version newer than the shown one yet
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import certifi  # noqa: E402

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import requests  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from scripts.retranscription_queue_slice import (  # noqa: E402
    META_FILE,
    QUEUE_FILE,
    next_urls,
    parse_sections,
    read_meta,
)
from scripts.wo928_version_quality import defect_reasons, version_signals  # noqa: E402

TIMESTAMP = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+) --> (\d+):(\d+):(\d+)[,.](\d+)")
COVERAGE_TOLERANCE = 0.05


def parse_srt(text: str) -> list[dict]:
    segments = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.strip().split("\n")
        for i, line in enumerate(lines):
            m = TIMESTAMP.search(line)
            if m:
                g = [int(x) for x in m.groups()]
                start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
                end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
                segments.append(
                    {"start": start, "end": end, "text": " ".join(lines[i + 1 :])}
                )
                break
    return segments


def hint(old_sig: dict, new_sig: dict | None) -> str:
    if new_sig is None:
        return "no-new-version"
    if defect_reasons(new_sig):
        return "new-still-flagged"
    old_end = old_sig["last_cue_seconds"]
    if old_end and new_sig["last_cue_seconds"] < old_end * (1 - COVERAGE_TOLERANCE):
        return "new-shorter"
    return "new-clean"


def _read_version(base: str, slug: str, version_id: int) -> dict:
    """Signals for one version, from the public SRT (paced 1 read/second)."""
    time.sleep(1)
    r = requests.get(
        f"{base}/m/{slug}/transcript.srt",
        params={"version": version_id},
        timeout=120,
        headers={"User-Agent": "RTR-retranscription-review/1.0"},
    )
    r.raise_for_status()
    return version_signals(parse_srt(r.text))


def _describe(sig: dict) -> str:
    reasons = ",".join(defect_reasons(sig)) or "none"
    return (
        f"defects={reasons} dead_air={sig['dead_air_run']} "
        f"longest_run={sig['longest_run']} last_cue={sig['last_cue_seconds'] / 60:.1f}min"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--section", choices=["PILOT", "MAIN", "DRIP-MAC-ONLY"])
    ap.add_argument("--count", type=int, default=None)
    ap.add_argument("--page-ids", default=None, help="Comma-separated page ids")
    ap.add_argument("--env", default=None, help="Path to the .env holding the token")
    args = ap.parse_args()
    if not args.section and not args.page_ids:
        ap.error("give --section or --page-ids")

    if args.env:
        load_dotenv(args.env)
    else:
        load_dotenv()
    base = (os.environ.get("ARCHIVE_BASE_URL") or "").rstrip("/")
    token = os.environ.get("ARCHIVE_INGEST_TOKEN")
    if not base or not token:
        print("ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN not set (use --env).")
        return 1

    meta_rows, done = read_meta(META_FILE.read_text(encoding="utf-8"))
    by_page = {r["page_id"]: r for r in meta_rows}
    if args.page_ids:
        ids = [i.strip() for i in args.page_ids.split(",") if i.strip()]
    else:
        sections = parse_sections(QUEUE_FILE.read_text(encoding="utf-8"))
        urls = next_urls(sections, meta_rows, done, args.section, args.count)
        page_of = {r["url"]: r["page_id"] for r in meta_rows}
        ids = [page_of[u] for u in urls]
    if not ids:
        print("Nothing to review.")
        return 0

    resp = requests.get(
        f"{base}/internal/export/pages",
        params={"ids": ",".join(ids[:100]), "limit": 100},
        headers={"Authorization": f"Bearer {token}"},
        timeout=120,
    )
    resp.raise_for_status()
    pages = {str(p["id"]): p for p in resp.json()["pages"]}

    for pid in ids:
        page = pages.get(pid)
        if page is None:
            print(f"page {pid}: not found")
            continue
        slug = page["slug"]
        versions = page["versions"]
        shown = next((v for v in versions if v["is_default"]), None)
        hidden = sorted(
            (v for v in versions if not v["is_default"]),
            key=lambda v: v["created_at"],
            reverse=True,
        )
        if shown is None:
            print(f"page {pid}: no shown version")
            continue
        # The newest hidden Whisper version made after the shown one.
        new = next(
            (
                v
                for v in hidden
                if v["source"] == "transcribed"
                and shown is not None
                and v["created_at"] > shown["created_at"]
            ),
            None,
        )

        old_sig = _read_version(base, slug, shown["id"])
        new_sig = _read_version(base, slug, new["id"]) if new else None
        meta = by_page.get(pid, {})
        print(
            f"page {pid}  {slug}  ({meta.get('platform', '?')}, {meta.get('hours', '?')} h)"
        )
        print(f"  old shown v{shown['id']}: {_describe(old_sig)}")
        if new:
            print(f"  new hidden v{new['id']}: {_describe(new_sig)}")
            print(f"  new SRT: {base}/m/{slug}/transcript.srt?version={new['id']}")
        print(f"  hint: {hint(old_sig, new_sig)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
