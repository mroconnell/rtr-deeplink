"""Find stored source transcripts that carry sound tags (read-only).

    python scripts/find_named_speaker_transcripts.py [--out FILE] [--platform P]
        [--min-tags 3] [--include-youtube] [--limit N]

Run it from the Archive service's Render shell, not from a laptop against the
production database: it reads every source transcript's `segments` blob.
It writes one CSV row per page that has sound tags and changes nothing.

Which transcripts. Every version whose `source` is not "transcribed". Only
"transcribed" means our own AI transcription; "sourced" and "deduped" (the
roll-up cleanup of the same source captions) are the city's or its vendor's
captions. A page appears once, with the version that has the most tags.

What counts as a lead. A bracketed or parenthesised sound tag, such as
[GAVEL], [INAUDIBLE] or (bright music). Tags fall in three groups:

    room event   a person had to hear or see it: gavel, recess, off mic,
                 roll call, house at ease, pledge, closed session
    common       music, applause, laughter, inaudible, crosstalk. Weak
                 alone: some automatic captions write them too
    noise        rustling, scratching, throat clearing, door. Software that
                 labels sounds writes these; a captioner rarely does

A page is a lead when it has 2 or more room-event tags, or when room-event
plus common tags reach --min-tags (default 3). The
`noise_tags` column is a warning, not a filter: many of them suggest
software. Name labels are still counted but no longer flag a page, because
a name in front of the line also appears in video-call transcripts.

This is a score, not a verdict. Read the sample lines in the CSV before
trusting a row.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# [TEXT] or (TEXT), 3-40 characters, letters and spaces only. Whitespace is
# collapsed first, so a tag split over two lines of one cue still matches.
_TAG_RE = re.compile(r"[\[(]\s*([A-Za-z][A-Za-z ,'\-]{2,38}?)\s*[\])]")
_ROOM_WORDS = (
    "gavel", "recess", "roll call", "off mic", "house at ease", "house in",
    "pledge", "closed session", "no audio", "speaking spanish", "speaking",
    "ayes", "chanting", "moment of silence", "adjourn", "sounding",
)  # fmt: skip
_COMMON_WORDS = (
    "music", "applause", "laughter", "inaudible", "crosstalk", "cross talk",
    "unintelligible", "indistinct", "cheering", "booing",
)  # fmt: skip
_NOISE_WORDS = (
    "rustl", "scratch", "clear", "throat", "door", "clatter", "cough", "sigh",
    "mutter", "conversation", "typing", "chair", "footstep", "static",
    "sniff", "background", "microphone", "feedback", "beep", "click",
)  # fmt: skip
# Labels a machine assigns. Not names.
_GENERIC_RE = re.compile(r"^(?:[Ss]\d+|[Ss]peaker ?\d+|[Uu]nknown|[Mm]ale|[Ff]emale)$")
_NAME_RE = re.compile(
    r"^((?:[A-Z][A-Za-z.'\-]+)(?: [A-Za-z][A-Za-z.'\-]+){0,3}) ?:\s+\S"
)
_LABEL_RE = re.compile(r"^([A-Za-z][A-Za-z ]{0,12}\d?) ?:\s+\S")
_NOT_A_NAME = {
    "note", "notes", "published", "date", "time", "location", "motion",
    "action", "item", "agenda", "public comment", "result", "vote", "disclaimer",
}  # fmt: skip


def classify_tag(tag: str) -> Optional[str]:
    """Return "room", "common", "noise", or None for a bracketed phrase."""
    t = tag.lower().strip()
    if any(w in t for w in _ROOM_WORDS):
        return "room"
    if any(w in t for w in _COMMON_WORDS):
        return "common"
    if any(w in t for w in _NOISE_WORDS):
        return "noise"
    return None


def score_segments(segments: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Count the sound-tag and name-label signals in one transcript."""
    texts = [re.sub(r"\s+", " ", (s.get("text") or "")).strip() for s in segments]
    texts = [t for t in texts if t]
    kinds: Counter = Counter()
    groups: Counter = Counter()
    names: Counter = Counter()
    generic = 0
    samples: List[str] = []
    letters = upper = 0
    for t in texts:
        for m in _TAG_RE.finditer(t):
            g = classify_tag(m.group(1))
            if g:
                groups[g] += 1
                kinds[m.group(1).strip().upper()] += 1
                if g == "room" and len(samples) < 3:
                    samples.append(t[:90])
        for c in t:
            if c.isalpha():
                letters += 1
                upper += c.isupper()
        g = _LABEL_RE.match(t)
        if g and _GENERIC_RE.match(g.group(1)):
            generic += 1
            continue
        m = _NAME_RE.match(t)
        if m and not _GENERIC_RE.match(m.group(1).strip()):
            label = m.group(1).strip()
            if label.lower() not in _NOT_A_NAME:
                names[label.upper()] += 1
    n = len(texts)
    named = sum(names.values())
    return {
        "segments": n,
        "room_event_tags": groups["room"],
        "common_tags": groups["common"],
        "noise_tags": groups["noise"],
        "tag_kinds": "; ".join(f"{k} ({v})" for k, v in kinds.most_common(6)),
        "named_share": round(named / n, 3) if n else 0.0,
        "distinct_names": len(names),
        "generic_label_lines": generic,
        "all_caps_share": round(upper / letters, 2) if letters else 0.0,
        "samples": " | ".join(samples),
    }


def is_lead(score: Dict[str, Any], min_tags: int) -> bool:
    if score["room_event_tags"] >= 2:
        return True
    return score["room_event_tags"] + score["common_tags"] >= min_tags


def is_youtube(video_url: Optional[str]) -> bool:
    u = (video_url or "").lower()
    return "youtube.com" in u or "youtu.be" in u


COLUMNS = [
    "slug", "platform", "jurisdiction", "date", "video_host", "version_id",
    "version_source", "room_event_tags", "common_tags", "noise_tags",
    "tag_kinds", "named_share", "distinct_names", "segments",
    "generic_label_lines", "all_caps_share", "samples",
]  # fmt: skip


async def run(args: argparse.Namespace) -> int:
    from urllib.parse import urlparse

    from sqlalchemy import select

    from archive.db.engine import async_session
    from archive.db.models import MeetingPage, TranscriptVersion

    best: Dict[int, Dict[str, Any]] = {}
    seen_pages = set()
    skipped_youtube = 0
    versions_read = 0
    last_id = 0
    async with async_session() as db:
        while True:
            q = (
                select(MeetingPage, TranscriptVersion)
                .join(
                    TranscriptVersion,
                    TranscriptVersion.meeting_page_id == MeetingPage.id,
                )
                .where(
                    MeetingPage.id > last_id,
                    TranscriptVersion.source != "transcribed",
                )
                .order_by(MeetingPage.id)
                .limit(50)
            )
            if args.platform:
                q = q.where(MeetingPage.platform == args.platform)
            batch = (await db.execute(q)).all()
            if not batch:
                break
            for page, version in batch:
                last_id = max(last_id, page.id)
                if not args.include_youtube and is_youtube(page.video_url):
                    if page.id not in seen_pages:
                        skipped_youtube += 1
                        seen_pages.add(page.id)
                    continue
                seen_pages.add(page.id)
                versions_read += 1
                s = score_segments(version.segments or [])
                if not is_lead(s, args.min_tags):
                    continue
                row = {
                    "slug": page.slug,
                    "platform": page.platform,
                    "jurisdiction": page.jurisdiction,
                    "date": page.date,
                    "video_host": urlparse(page.video_url or "").netloc,
                    "version_id": version.id,
                    "version_source": version.source,
                    **s,
                }
                key = s["room_event_tags"] * 10 + s["common_tags"]
                old = best.get(page.id)
                if old is None or key > old["_key"]:
                    row["_key"] = key
                    best[page.id] = row
            db.expire_all()
            if args.limit and len(seen_pages) >= args.limit:
                break
    rows = sorted(best.values(), key=lambda r: -r["_key"])
    with open(args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"Pages read (not YouTube): {len(seen_pages) - skipped_youtube}")
    print(f"Source versions read: {versions_read}")
    print(f"Skipped, video on YouTube: {skipped_youtube}")
    print(f"Pages that are sound-tag leads: {len(rows)}")
    with_room = sum(1 for r in rows if r["room_event_tags"] > 0)
    print(f"  of those, with at least one room-event tag: {with_room}")
    by_platform = Counter(r["platform"] for r in rows)
    for p, c in by_platform.most_common():
        print(f"  {p}: {c}")
    print(f"Written to {args.out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default="sound_tag_leads.csv")
    ap.add_argument("--platform")
    ap.add_argument("--min-tags", type=int, default=3)
    ap.add_argument("--include-youtube", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="stop after N pages read")
    return asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
