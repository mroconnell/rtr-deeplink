"""Score and shortlist human-captioned meetings for an annotated-speech set.

    python scripts/shortlist_human_captions.py SLUGS_FILE [--out FILE]
        [--target-hours 35] [--base-url https://redtaperecordings.com]
        [--cache-dir DIR]

SLUGS_FILE has one page slug per line (the Tier A list from
find_named_speaker_transcripts.py). The script reads each page's public
plain-text transcript (`/m/<slug>/transcript.txt`), scores it, and picks the
best pages until the target number of hours is reached. It changes nothing.

The public export keeps one start time per line and no end time, so durations
are the last line's start, a little short of the true length. Pauses are
estimated as the gap to the next line minus the time the words take to say at
2.7 words a second, so they are coarse.

Reads only our own site. A short delay keeps the requests polite.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.find_named_speaker_transcripts import (  # noqa: E402
    _GENERIC_RE,
    _NAME_RE,
    _NOT_A_NAME,
    _TAG_RE,
    classify_tag,
)

_LINE_RE = re.compile(r"^\[(?:(\d+):)?(\d+):(\d\d)\]\s?(.*)$")
_OVERLAP_WORDS = (
    "crosstalk", "cross talk", "multiple voices", "overlapping",
    "talking over", "simultaneous", "speaking at once",
)  # fmt: skip
_LOST_WORDS = (
    "inaudible", "indiscernible", "unintelligible", "indistinct",
    "off mic", "no audio", "unclear",
)  # fmt: skip
_WHISPER_WORDS = (
    "whisper", "side conversation", "aside", "background talking",
    "private conversation", "talking in background",
)  # fmt: skip
_CUTOFF_RE = re.compile(r"(--|\u2014|\u2013|\s-)\s*$")
_WORDS_PER_SECOND = 2.7
_PAUSE_SECONDS = 4.0
_MIN_HOURS = 0.33


def parse_txt(text: str) -> List[Dict[str, Any]]:
    """Parse the public transcript.txt (`[m:ss] text`, text may wrap)."""
    segs: List[Dict[str, Any]] = []
    for line in text.split("\n"):
        m = _LINE_RE.match(line)
        if m:
            h = int(m.group(1) or 0)
            start = h * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            segs.append({"start": float(start), "text": m.group(4)})
        elif segs and line.strip():
            segs[-1]["text"] += "\n" + line
    return segs


def _turns_in(text: str) -> int:
    """Turn changes in one caption line: each `>>` or `»`, plus a leading
    typed name. A `>>` can sit in the middle of a line, not only at its start."""
    t = re.sub(r"\s+", " ", text).strip()
    n = len(re.findall(r">>|»", t))
    m = _NAME_RE.match(t)
    if m:
        label = m.group(1).strip()
        if not _GENERIC_RE.match(label) and label.lower() not in _NOT_A_NAME:
            n += 1
    return n


def features(segments: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Numbers used to rank a page. No judgement beyond the counts."""
    n = len(segments)
    last = segments[-1]["start"] if n else 0.0
    hours = last / 3600.0
    room_kinds, overlap, lost = set(), 0, 0
    groups = {"room": 0, "common": 0, "noise": 0}
    letters = upper = turns = pauses = cutoffs = whispers = 0
    for i, s in enumerate(segments):
        text = re.sub(r"\s+", " ", s["text"]).strip()
        turns += _turns_in(text)
        if _CUTOFF_RE.search(text):
            cutoffs += 1
        for m in _TAG_RE.finditer(text):
            g = classify_tag(m.group(1))
            kind = m.group(1).strip().lower()
            if g:
                groups[g] += 1
                if g == "room":
                    room_kinds.add(kind)
            if any(w in kind for w in _OVERLAP_WORDS):
                overlap += 1
            if any(w in kind for w in _LOST_WORDS):
                lost += 1
            if any(w in kind for w in _WHISPER_WORDS):
                whispers += 1
        for c in text:
            if c.isalpha():
                letters += 1
                upper += c.isupper()
        if i + 1 < n:
            gap = segments[i + 1]["start"] - s["start"]
            say = len(text.split()) / _WORDS_PER_SECOND
            if gap - say > _PAUSE_SECONDS:
                pauses += 1
    per_hour = (lambda x: round(x / hours, 2)) if hours > 0 else (lambda x: 0.0)
    return {
        "segments": n,
        "hours": round(hours, 2),
        "room_kinds": len(room_kinds),
        "room_tags": groups["room"],
        "noise_tags": groups["noise"],
        "overlap_tags": overlap,
        "lost_speech_tags": lost,
        "lost_per_hour": per_hour(lost),
        "turn_share": round(min(turns / n, 1.0), 3) if n else 0.0,
        "turns_per_hour": per_hour(turns),
        "cutoffs": cutoffs,
        "whisper_tags": whispers,
        "pauses_per_hour": per_hour(pauses),
        "all_caps_share": round(upper / letters, 2) if letters else 0.0,
    }


def eligible(f: Dict[str, Any]) -> bool:
    return f["hours"] >= _MIN_HOURS and f["room_kinds"] >= 2 and f["turn_share"] >= 0.05


def score(f: Dict[str, Any]) -> float:
    s = 2.0 * min(f["room_kinds"], 5)
    s += 0.5 * min(f["overlap_tags"], 10)
    s += 2.0 if f["turn_share"] >= 0.15 else 0.0
    s += 0.1 * min(f["cutoffs"], 20)
    s += 0.5 * min(f["whisper_tags"], 6)
    s -= 0.3 * min(f["lost_per_hour"], 20)
    s -= 3.0 if f["noise_tags"] > 5 else 0.0
    return round(s, 2)


def fingerprint(segments: List[Dict[str, Any]]) -> str:
    """Same text -> same fingerprint, so a page filed twice counts once."""
    head = " ".join(s["text"] for s in segments[:40])
    return hashlib.sha1(re.sub(r"\s+", " ", head).encode()).hexdigest()[:12]


def pick(rows: List[Dict[str, Any]], target_hours: float) -> List[Dict[str, Any]]:
    """Best score first; skip duplicates; stop at the target hours."""
    chosen, seen, total = [], set(), 0.0
    for r in sorted(rows, key=lambda r: -r["score"]):
        if not r["eligible"] or r["fingerprint"] in seen:
            continue
        if total >= target_hours:
            break
        seen.add(r["fingerprint"])
        chosen.append(r)
        total += r["hours"]
    return chosen


def fetch(base: str, slug: str, cache: Optional[Path]) -> Optional[str]:
    path = cache / f"{slug}.txt" if cache else None
    if path and path.exists():
        return path.read_text(errors="replace")
    url = f"{base}/m/{slug}/transcript.txt"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "rtr-shortlist/1"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        print(f"  could not read {slug}: {exc}", file=sys.stderr)
        return None
    if path:
        path.write_text(text)
    time.sleep(0.5)
    return text


COLUMNS = [
    "picked", "score", "slug", "hours", "room_kinds", "room_tags",
    "overlap_tags", "cutoffs", "whisper_tags", "turns_per_hour", "lost_speech_tags", "lost_per_hour", "turn_share",
    "pauses_per_hour", "noise_tags", "all_caps_share", "segments",
    "eligible", "fingerprint",
]  # fmt: skip


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("slugs_file")
    ap.add_argument("--out", default="shortlist.csv")
    ap.add_argument("--target-hours", type=float, default=35.0)
    ap.add_argument("--base-url", default="https://redtaperecordings.com")
    ap.add_argument("--cache-dir")
    args = ap.parse_args()
    cache = Path(args.cache_dir) if args.cache_dir else None
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, Any]] = []
    for slug in [s.strip() for s in open(args.slugs_file) if s.strip()]:
        text = fetch(args.base_url, slug, cache)
        if not text:
            continue
        segs = parse_txt(text)
        if not segs:
            continue
        f = features(segs)
        rows.append(
            {
                "slug": slug,
                **f,
                "eligible": eligible(f),
                "score": score(f),
                "fingerprint": fingerprint(segs),
            }
        )
    chosen = {r["slug"] for r in pick(rows, args.target_hours)}
    for r in rows:
        r["picked"] = r["slug"] in chosen
    rows.sort(key=lambda r: (-int(r["picked"]), -r["score"]))
    with open(args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    hours = sum(r["hours"] for r in rows if r["picked"])
    print(f"Pages scored: {len(rows)}")
    print(f"Eligible: {sum(1 for r in rows if r['eligible'])}")
    print(
        f"Picked: {len(chosen)} pages, {hours:.1f} hours (target {args.target_hours})"
    )
    print(f"Written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
