"""Build caption and annotation files for the annotated-speech set (read-only).

    python scripts/build_speech_annotations.py SHORTLIST_CSV --out-dir DIR
        [--cache-dir DIR] [--base-url https://redtaperecordings.com]

Reads the picked rows of the shortlist (scripts/shortlist_human_captions.py),
reads each page's public transcript, and writes for every meeting:

    captions/<slug>.jsonl      the city's caption lines, untouched but for
                               email and phone redaction
    annotations/<slug>.jsonl   our labels, one per line, in a SEPARATE file

plus manifest.json (counts, rule version, redaction count, limits) and
README.md (field dictionary). The captions are never edited. Our labels point
into them by `caption_index` (the line number) and by time.

Every label here is a text-only heuristic (`source: "heuristic"`). Times are
the start time of the caption line, which trails the speech by a few seconds,
so they are coarse. A later pass can add audio-aligned times as another layer
without touching these files.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.find_named_speaker_transcripts import (  # noqa: E402
    _GENERIC_RE,
    _NOT_A_NAME,
    _TAG_RE,
    classify_tag,
)
from scripts.shortlist_human_captions import (  # noqa: E402
    _CUTOFF_RE,
    _LOST_WORDS,
    _OVERLAP_WORDS,
    _WHISPER_WORDS,
    fetch,
    parse_txt,
)

RULE_VERSION = "text_heuristics_v1"
LONG_TURN_SECONDS = 60.0
_SPEAKER_RE = re.compile(r"^(?:>>\s*)?([A-Za-z][A-Za-z.'\- ]{1,40}?)\s*:\s")
_TURN_RE = re.compile(r">>|»")
_TIME_LIMIT_RE = re.compile(
    r"\b(your time (is|has|ran)|time (is|has) (up|expired|elapsed)|time's up|"
    r"that'?s your time|timer|out of time)\b",
    re.I,
)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)"
)


def redact(text: str) -> Tuple[str, int]:
    """Replace emails and phone numbers; return the text and how many."""
    text, n1 = _EMAIL_RE.subn("[email redacted]", text)
    text, n2 = _PHONE_RE.subn("[phone redacted]", text)
    return text, n1 + n2


def _speaker(text: str) -> str | None:
    m = _SPEAKER_RE.match(text)
    if not m:
        return None
    label = m.group(1).strip()
    if _GENERIC_RE.match(label) or label.lower() in _NOT_A_NAME:
        return None
    return label


def annotate(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return our labels for one meeting. `segments` are {start, text}."""
    ann: List[Dict[str, Any]] = []
    n = len(segments)
    clean = [re.sub(r"\s+", " ", s["text"]).strip() for s in segments]

    def add(kind: str, i: int, j: int, **kw: Any) -> None:
        ann.append(
            {
                "kind": kind,
                "start": segments[i]["start"],
                "end": segments[j]["start"] if j < n else segments[i]["start"],
                "caption_index": i,
                "caption_index_end": min(j, n - 1),
                "source": "heuristic",
                "rule": RULE_VERSION,
                **kw,
            }
        )

    # Turns: every >> or », plus a leading typed name. A marker inside a line
    # starts its turn at that line's start (within_cue = true).
    turns: List[Tuple[int, str | None, bool]] = []
    for i, t in enumerate(clean):
        marks = list(_TURN_RE.finditer(t))
        spk = _speaker(t)
        if marks:
            for k, _ in enumerate(marks):
                turns.append((i, spk if k == 0 else None, bool(marks[k].start() > 0)))
        elif spk:
            turns.append((i, spk, False))
    if not turns and n:
        turns.append((0, None, False))
    for k, (i, spk, within) in enumerate(turns):
        j = turns[k + 1][0] if k + 1 < len(turns) else n - 1
        add(
            "turn",
            i,
            j,
            speaker=spk,
            speaker_label_source="typed_in_caption" if spk else "none",
            within_cue=within,
            confidence="medium" if spk else "low",
        )
        # A long turn followed by a chair line about the time limit.
        dur = segments[j]["start"] - segments[i]["start"]
        if dur >= LONG_TURN_SECONDS and j + 1 < n:
            nxt = " ".join(clean[j : j + 2])
            if _TIME_LIMIT_RE.search(nxt):
                add(
                    "speaker_cut_off",
                    i,
                    min(j + 2, n - 1),
                    turn_seconds=round(dur, 1),
                    evidence_rule="long_turn_then_time_limit_words",
                    confidence="low",
                )

    for i, t in enumerate(clean):
        # Bracketed sound tags.
        for m in _TAG_RE.finditer(t):
            label = m.group(1).strip()
            low = label.lower()
            group = classify_tag(label)
            if any(w in low for w in _OVERLAP_WORDS):
                kind = "overlap"
            elif any(w in low for w in _WHISPER_WORDS):
                kind = "whisper_or_side_talk"
            elif any(w in low for w in _LOST_WORDS):
                kind = "lost_speech"
            elif group:
                kind = "sound_event"
            else:
                continue
            add(kind, i, i, label=label.upper(), tag_group=group, confidence="high")
        # Sentences cut off by a dash.
        if _CUTOFF_RE.search(t):
            nxt = clean[i + 1] if i + 1 < n else ""
            by_other = bool(_TURN_RE.match(nxt)) or _speaker(nxt) is not None
            after = " ".join(clean[i + 1 : i + 3])
            if by_other and _TIME_LIMIT_RE.search(after):
                add(
                    "speaker_cut_off",
                    i,
                    min(i + 2, n - 1),
                    evidence_rule="dash_cut_then_time_limit_words",
                    confidence="medium",
                )
            add(
                "interruption" if by_other else "self_repair",
                i,
                min(i + 1, n - 1),
                evidence_rule="line_ends_with_dash",
                confidence="low",
            )
        # Pauses are NOT made from caption gaps: on 2026-10-10, 6 of 8 sampled
        # caption-gap pauses had no silence in the audio (caption lines appear
        # late or in bursts). Pauses come from the audio; see add_audio_pauses.py.
    ann.sort(key=lambda a: (a["start"], a["kind"]))
    for k, a in enumerate(ann):
        a["id"] = f"a{k:05d}"
    return ann


FIELDS = {
    "id": "Label number within the meeting (a00000, a00001, ...).",
    "kind": "turn | speaker_cut_off | overlap | lost_speech | whisper_or_side_talk | sound_event | interruption | self_repair ",
    "start": "Seconds from the first caption line. Start time of the caption line (coarse).",
    "end": "Seconds. Start of the line where the label ends.",
    "caption_index": "Zero-based line number in captions/<slug>.jsonl where the label starts.",
    "caption_index_end": "Line number where it ends.",
    "source": "Always 'heuristic' in this layer: a rule over the caption text, not a person.",
    "rule": "Rule set version, so a better rule can be added as a new layer.",
    "confidence": "high | medium | low. Our rating of the rule, not of the audio.",
    "speaker": "(turn) Name typed in the caption, if any; null otherwise.",
    "speaker_label_source": "(turn) typed_in_caption | none.",
    "within_cue": "(turn) true when the marker sits inside a caption line, so the true start is later.",
    "label": "(tag kinds) The tag as the captioner wrote it, upper-cased.",
    "tag_group": "(tag kinds) room | common | noise.",
    "turn_seconds": "(speaker_cut_off) Length of the turn that ended.",
    "evidence_rule": "(some kinds) Which rule fired.",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("shortlist_csv")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--cache-dir")
    ap.add_argument("--base-url", default="https://redtaperecordings.com")
    args = ap.parse_args()
    out = Path(args.out_dir)
    (out / "captions").mkdir(parents=True, exist_ok=True)
    (out / "annotations").mkdir(parents=True, exist_ok=True)
    cache = Path(args.cache_dir) if args.cache_dir else None
    picked = [
        r for r in csv.DictReader(open(args.shortlist_csv)) if r["picked"] == "True"
    ]
    meetings, redactions, totals = [], 0, Counter()
    for r in picked:
        slug = r["slug"]
        text = fetch(args.base_url, slug, cache)
        segs = parse_txt(text or "")
        if not segs:
            print(f"  no captions for {slug}", file=sys.stderr)
            continue
        with open(out / "captions" / f"{slug}.jsonl", "w") as fh:
            for i, s in enumerate(segs):
                t, n = redact(s["text"])
                redactions += n
                s["text"] = t
                fh.write(
                    json.dumps({"index": i, "start": s["start"], "text": t}) + "\n"
                )
        ann = annotate(segs)
        kinds = Counter(a["kind"] for a in ann)
        totals.update(kinds)
        with open(out / "annotations" / f"{slug}.jsonl", "w") as fh:
            for a in ann:
                fh.write(json.dumps(a) + "\n")
        meetings.append(
            {
                "slug": slug,
                "source_page": f"{args.base_url}/m/{slug}",
                "caption_lines": len(segs),
                "hours_at_last_line": round(segs[-1]["start"] / 3600, 2),
                "labels": dict(kinds),
            }
        )
    manifest = {
        "rule_version": RULE_VERSION,
        "meetings": meetings,
        "label_totals": dict(totals),
        "total_hours_at_last_line": round(
            sum(m["hours_at_last_line"] for m in meetings), 1
        ),
        "email_and_phone_redactions": redactions,
        "limits": [
            "Times are caption-line start times; live captions trail speech by a few seconds.",
            "All labels are text heuristics. None was made by listening to audio.",
            "Captions carry no emotion, character or whisper information beyond tags a captioner chose to write.",
            "Overlap is only labelled where the captioner wrote a crosstalk-style tag.",
        ],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    rows = "\n".join(f"| `{k}` | {v} |" for k, v in FIELDS.items())
    (out / "README.md").write_text(
        "# Annotated speech set: caption and annotation files\n\n"
        "Captions are the city's live captions (emails and phone numbers redacted). "
        "Annotations are in separate files and point into the captions by line number "
        "and time. Nothing here is a human label made by listening; see manifest.json.\n\n"
        "| Field | Meaning |\n|---|---|\n" + rows + "\n"
    )
    print(f"Meetings written: {len(meetings)}")
    print(f"Hours at last caption line: {manifest['total_hours_at_last_line']}")
    print(f"Label counts: {dict(totals)}")
    print(f"Email/phone redactions: {redactions}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
