"""Rate each audio-measured pause by how much quieter it is than the speech
just before it (local files; changes only annotations_aligned/).

    python scripts/rate_pauses_by_energy.py SET_DIR AUDIO_DIR [--workers 4]

A pause from scripts/add_audio_pauses.py is a gap with no spoken words as
heard by a speech model. That can be silence, a breath, room noise, applause
or speech the model missed. This adds `quieter_by_db`: the mean level of the
10 seconds of audio before the gap minus the mean level inside the gap, from
ffmpeg's volumedetect. A large number means a real quiet moment; a number near
zero means the gap is as loud as speech.

confidence is then set: high at 8 dB or more, medium from 3 up to 8, low below
3. A sample of 24 on 2026-10-10 gave 10 at 8 dB or more, 6 within 2 dB.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Optional

HIGH_DB = 8.0
MEDIUM_DB = 3.0


def confidence_for(db: Optional[float]) -> str:
    if db is None:
        return "low"
    if db >= HIGH_DB:
        return "high"
    return "medium" if db >= MEDIUM_DB else "low"


def mean_db(clip: str, t0: float, dur: float) -> Optional[float]:
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-ss", f"{max(t0, 0):.2f}",
         "-t", f"{dur:.2f}", "-i", clip, "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    )  # fmt: skip
    m = re.search(r"mean_volume:\s*(-?[\d.]+)", p.stderr)
    return float(m.group(1)) if m else None


def rate(job: Dict) -> Optional[float]:
    gap = mean_db(job["clip"], job["clip_start"], job["seconds"])
    ref = mean_db(job["clip"], job["clip_start"] - 10, min(10, job["clip_start"]))
    if gap is None or ref is None:
        return None
    return round(ref - gap, 1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("set_dir")
    ap.add_argument("audio_dir")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    for path in sorted(
        glob.glob(str(Path(args.set_dir) / "annotations_aligned" / "*.jsonl"))
    ):
        rows = [json.loads(line) for line in open(path)]
        idx = [
            i
            for i, r in enumerate(rows)
            if r["kind"] == "pause" and r.get("source") == "audio_word_gaps"
        ]
        jobs = [
            {"clip": str(Path(args.audio_dir) / rows[i]["clip"]),
             "clip_start": rows[i]["clip_start"], "seconds": rows[i]["seconds"]}
            for i in idx
        ]  # fmt: skip
        with ThreadPoolExecutor(args.workers) as ex:
            vals = list(ex.map(rate, jobs))
        for i, v in zip(idx, vals):
            rows[i]["quieter_by_db"] = v
            rows[i]["confidence"] = confidence_for(v)
        with open(path, "w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        hi = sum(1 for i in idx if rows[i]["confidence"] == "high")
        print(
            f"{Path(path).stem[:44]:44} pauses {len(idx):4}  high confidence {hi:4}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
