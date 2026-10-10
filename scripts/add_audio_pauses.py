"""Replace caption-gap pauses with pauses measured from the audio (local files).

    python scripts/add_audio_pauses.py SET_DIR WORK_DIR

On 2026-10-10 a sample of 8 caption-gap "pause" labels showed that 6 had no
silence in the audio: caption lines appear late or in bursts, so a gap
between lines is not a gap in speech. This script:

  * deletes every `pause` label from annotations/<slug>.jsonl (caption-time
    layer) and annotations_aligned/<slug>.jsonl (audio layer);
  * adds new `pause` labels to the audio layer from the speech model's own
    word times: any silence of at least MIN_GAP seconds between two spoken
    words inside a verified stretch.

WORK_DIR holds <slug>/words.json from scripts/align_captions_to_audio.py.
Words come from a model run with voice-activity filtering, so a gap means
"no speech words": it can be silence, applause, music or room noise. The
label says so (`kind: pause`, `what: gap_between_spoken_words`).
"""

from __future__ import annotations

import glob
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

RULE = "whisper_word_gaps_v1"
MIN_GAP = 1.0
LONG_GAP = 4.0


def audio_pauses(
    words: List[List[Any]], stretches: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Gaps of at least MIN_GAP seconds between consecutive words, kept only
    when both words lie inside the same stretch."""
    out: List[Dict[str, Any]] = []
    for k, s in enumerate(stretches):
        ws = [w for w in words if s["start"] <= w[1] and w[2] <= s["end"]]
        for a, b in zip(ws, ws[1:]):
            gap = b[1] - a[2]
            if gap >= MIN_GAP:
                out.append(
                    {
                        "kind": "pause",
                        "what": "gap_between_spoken_words",
                        "audio_start": round(a[2], 2),
                        "audio_end": round(b[1], 2),
                        "seconds": round(gap, 2),
                        "long": gap >= LONG_GAP,
                        "clip_index": k,
                        "clip_start": round(a[2] - s["start"], 2),
                        "clip_end": round(b[1] - s["start"], 2),
                        "source": "audio_word_gaps",
                        "rule": RULE,
                        "confidence": "medium",
                        "layer": "audio_aligned_v1",
                    }
                )
    return out


def main() -> int:
    sdir, work = Path(sys.argv[1]), Path(sys.argv[2])
    removed_cap = removed_aligned = added = 0
    for ap in sorted(glob.glob(str(sdir / "alignment" / "*.json"))):
        al = json.load(open(ap))
        slug = al["slug"]
        wp = next(iter(glob.glob(str(work / (slug[:50] + "*") / "words.json"))), None)
        if not wp:
            print(f"  no word times for {slug[:40]}", file=sys.stderr)
            continue
        words = json.load(open(wp))
        # Caption-time layer: drop the unreliable pause labels.
        cp = sdir / "annotations" / f"{slug}.jsonl"
        rows = [json.loads(line) for line in open(cp)]
        keep = [r for r in rows if r["kind"] != "pause"]
        removed_cap += len(rows) - len(keep)
        with open(cp, "w") as fh:
            for r in keep:
                fh.write(json.dumps(r) + "\n")
        # Audio layer: drop them too, then add the measured ones.
        ap2 = sdir / "annotations_aligned" / f"{slug}.jsonl"
        rows = [json.loads(line) for line in open(ap2)]
        keep = [r for r in rows if r["kind"] != "pause"]
        removed_aligned += len(rows) - len(keep)
        clips = [c["file"] for c in al["stretches"]]
        new = audio_pauses(words, al["stretches"])
        for p in new:
            p["clip"] = clips[p["clip_index"]]
        merged = keep + new
        merged.sort(key=lambda r: (r["audio_start"], r["kind"]))
        for i, r in enumerate(merged):
            r["id"] = f"b{i:05d}"
        with open(ap2, "w") as fh:
            for r in merged:
                fh.write(json.dumps(r) + "\n")
        added += len(new)
    print(f"Caption-layer pause labels removed: {removed_cap}")
    print(f"Audio-layer pause labels removed: {removed_aligned}")
    print(f"Audio-measured pause labels added: {added}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
