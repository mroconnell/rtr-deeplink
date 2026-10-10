"""Align live captions to the audio, keep only verified stretches, cut clips.

    python scripts/align_captions_to_audio.py SET_DIR MEDIA_JSON
        --audio-out DIR --work-dir DIR [--only SLUG_PREFIX ...]

SET_DIR is the annotated-speech set (captions/ and annotations/ from
scripts/build_speech_annotations.py). MEDIA_JSON lists, per meeting, the
`slug`, `video_url` and `source` (the page whose host wants a normal Referer).

For each meeting it:
  1. downloads the audio over the span the captions cover (plus a margin),
     with a normal browser User-Agent and the source page's Referer;
  2. transcribes it with a local Whisper model in 10-minute pieces;
  3. matches the transcription to the captions window by window. Where the
     match breaks it searches nearby offsets again, so a one-time step in the
     captions (a gap, an edit) is found and followed;
  4. keeps only windows where the two clearly agree ("verified"), merges
     neighbours into stretches, and cuts one audio clip per stretch;
  5. writes annotations_aligned/<slug>.jsonl: the labels that fall inside a
     stretch, with audio-true times and the clip they belong to.

The captions are never edited. Everything it writes sits beside them. It makes
no YouTube requests (install() of scripts/youtube_fetch_guard.py is called).
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

WINDOW_S = 120.0
MARGIN_S = 1500.0
PIECE_S = 600.0
SEARCH_STEPS = (0, 10, 20, 40, 80, 160, 320, 640, 1000)
MIN_AGREE_TO_FOLLOW = 40.0  # follow the offset when at least this much agrees
VERIFIED_AGREE = 65.0
VERIFIED_MATCHED = 40
MIN_CLIP_S = 300.0
GAP_WINDOWS = 1
LAG_JUMP_S = 3.0
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
)


def norm(word: str) -> str:
    return re.sub(r"[^a-z0-9']", "", word.lower())


def caption_words(caps: List[Dict[str, Any]]) -> List[Tuple[str, float, int]]:
    """(word, caption line start, line index) for every spoken word."""
    out = []
    for i, c in enumerate(caps):
        text = re.sub(r"\[[^\]]*\]|\([^)]*\)|>>|»", " ", c["text"])
        for w in text.split():
            if norm(w):
                out.append((norm(w), float(c["start"]), i))
    return out


def match_window(
    asr: List[Tuple[str, float, float]], cap: List[Tuple[str, float, int]]
) -> Dict[str, Any]:
    """Match Whisper words to caption words. Returns agreement, lag and the
    caption-line -> audio-time map from the matched words."""
    a = [w for w, _, _ in asr]
    b = [w for w, _, _ in cap]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    matched = 0
    lags: List[float] = []
    lines: Dict[int, List[Tuple[float, float]]] = {}
    for bl in sm.get_matching_blocks():
        matched += bl.size
        if bl.size < 3:
            continue
        for k in range(bl.size):
            w = asr[bl.a + k]
            c = cap[bl.b + k]
            lines.setdefault(c[2], []).append((w[1], w[2]))
            if bl.size >= 4:
                lags.append(c[1] - w[1])
    return {
        "agree": 100.0 * matched / len(a) if a else 0.0,
        "matched": matched,
        "lag": statistics.median(lags) if len(lags) >= 8 else None,
        "lines": lines,
    }


def align_windows(
    words: List[Tuple[str, float, float]],
    cwords: List[Tuple[str, float, int]],
    duration: float,
) -> Tuple[List[Dict[str, Any]], Dict[int, Tuple[float, float]]]:
    """Walk the audio in windows, following the caption offset."""
    out: List[Dict[str, Any]] = []
    line_times: Dict[int, Tuple[float, float]] = {}
    off = 0.0  # caption time minus audio time
    t = 0.0
    wi = 0
    while t < duration:
        end = t + WINDOW_S
        while wi < len(words) and words[wi][1] < t:
            wi += 1
        wj = wi
        while wj < len(words) and words[wj][1] < end:
            wj += 1
        chunk = words[wi:wj]
        rec: Dict[str, Any] = {
            "audio_start": t,
            "audio_end": end,
            "asr_words": len(chunk),
        }
        if len(chunk) < 15:
            rec.update(agree=0.0, matched=0, lag=None, verified=False, reason="quiet")
            out.append(rec)
            t = end
            continue
        best = None
        for step in SEARCH_STEPS:
            for sign in (0,) if step == 0 else (1, -1):
                cand = off + sign * step
                lo, hi = t + cand - 60, end + cand + 90
                cw = [c for c in cwords if lo <= c[1] <= hi]
                if len(cw) < 15:
                    continue
                r = match_window(chunk, cw)
                if best is None or r["agree"] > best[0]["agree"]:
                    best = (r, cand)
            if best and best[0]["agree"] >= 75.0:
                break
        if best is None:
            rec.update(
                agree=0.0, matched=0, lag=None, verified=False, reason="no_captions"
            )
            out.append(rec)
            t = end
            continue
        r, cand = best
        lag = r["lag"] if r["lag"] is not None else cand
        if r["agree"] >= MIN_AGREE_TO_FOLLOW and r["lag"] is not None:
            off = r["lag"]
        verified = r["agree"] >= VERIFIED_AGREE and r["matched"] >= VERIFIED_MATCHED
        rec.update(
            agree=round(r["agree"], 1),
            matched=r["matched"],
            lag=round(lag, 1),
            verified=verified,
            reason="ok" if verified else "weak_match",
        )
        if verified:
            for li, spans in r["lines"].items():
                s = min(x[0] for x in spans)
                e = max(x[1] for x in spans)
                old = line_times.get(li)
                line_times[li] = (
                    min(s, old[0]) if old else s,
                    max(e, old[1]) if old else e,
                )
        out.append(rec)
        t = end
    return out, line_times


def coverage(windows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge verified windows into stretches. One weak window between two
    verified ones with nearly the same lag is bridged."""
    stretches: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    gap = 0
    for w in windows:
        if w["verified"]:
            if (
                cur
                and gap <= GAP_WINDOWS
                and abs(w["lag"] - cur["lags"][-1]) <= LAG_JUMP_S
            ):
                cur["end"] = w["audio_end"]
                cur["lags"].append(w["lag"])
            else:
                if cur:
                    stretches.append(cur)
                cur = {
                    "start": w["audio_start"],
                    "end": w["audio_end"],
                    "lags": [w["lag"]],
                }
            gap = 0
        elif cur:
            gap += 1
    if cur:
        stretches.append(cur)
    out = []
    for s in stretches:
        if s["end"] - s["start"] >= MIN_CLIP_S:
            out.append(
                {
                    "start": s["start"],
                    "end": s["end"],
                    "lag": round(statistics.median(s["lags"]), 1),
                }
            )
    return out


def label_audio_times(
    ann: Dict[str, Any],
    line_times: Dict[int, Tuple[float, float]],
    stretches: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Audio-true times for one label, or None if it is outside every stretch."""
    i, j = ann["caption_index"], ann["caption_index_end"]
    for k, s in enumerate(stretches):
        lag = s["lag"]
        a0 = line_times[i][0] if i in line_times else ann["start"] - lag
        a1 = line_times[j][1] if j in line_times else ann["end"] - lag
        if a1 < a0:
            a1 = a0
        if s["start"] <= a0 and a1 <= s["end"]:
            return {
                "audio_start": round(a0, 2),
                "audio_end": round(a1, 2),
                "clip_index": k,
                "clip_start": round(a0 - s["start"], 2),
                "clip_end": round(a1 - s["start"], 2),
                "time_basis": "matched_words" if i in line_times else "stretch_lag",
            }
    return None


def _run(
    cmd: List[str], env: Dict[str, str], timeout: int
) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)


def download_audio(
    m: Dict[str, Any], dest: Path, seconds: float, env: Dict[str, str]
) -> bool:
    if dest.exists() and dest.stat().st_size > 100000:
        return True
    o = urlparse(m.get("source") or m["video_url"])
    hdr = f"User-Agent: {_UA}\r\nReferer: {o.scheme}://{o.netloc}/\r\n"
    dest.parent.mkdir(parents=True, exist_ok=True)
    p = _run(
        ["ffmpeg", "-y", "-v", "error", "-headers", hdr, "-i", m["video_url"],
         "-t", str(seconds), "-vn", "-c:a", "copy", str(dest)],
        env, 7200,
    )  # fmt: skip
    return dest.exists() and dest.stat().st_size > 100000 and not p.returncode


def transcribe(
    audio: Path, duration: float, model: Any, env: Dict[str, str]
) -> List[Tuple[str, float, float]]:
    words: List[Tuple[str, float, float]] = []
    t = 0.0
    piece = audio.parent / "piece.m4a"
    while t < duration:
        _run(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", str(audio),
              "-t", str(PIECE_S), "-vn", "-c:a", "copy", str(piece)], env, 600)  # fmt: skip
        if not piece.exists() or piece.stat().st_size < 3000:
            break
        try:
            segs, _ = model.transcribe(
                str(piece),
                language="en",
                word_timestamps=True,
                beam_size=1,
                vad_filter=True,
            )
            for s in segs:
                for w in s.words:
                    if norm(w.word):
                        words.append((norm(w.word), t + w.start, t + w.end))
        except Exception as exc:  # a silent piece can make the library raise
            print(f"    piece at {t:.0f}s skipped: {type(exc).__name__}", flush=True)
        t += PIECE_S
    return words


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("set_dir")
    ap.add_argument("media_json")
    ap.add_argument("--audio-out", required=True)
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--only", nargs="*", default=[])
    ap.add_argument("--keep-full-audio", action="store_true")
    ap.add_argument("--redo", action="store_true", help="redo meetings already aligned")
    args = ap.parse_args()

    import certifi

    import youtube_fetch_guard

    youtube_fetch_guard.install()
    env = dict(os.environ, SSL_CERT_FILE=certifi.where(), HF_HUB_OFFLINE="1")
    os.environ.update(env)
    from faster_whisper import WhisperModel

    model = WhisperModel(
        "small", device="cpu", compute_type="int8", local_files_only=True
    )
    sdir, work, aout = Path(args.set_dir), Path(args.work_dir), Path(args.audio_out)
    (sdir / "annotations_aligned").mkdir(exist_ok=True)
    (sdir / "alignment").mkdir(exist_ok=True)
    aout.mkdir(parents=True, exist_ok=True)
    media = json.load(open(args.media_json))
    summary = []
    for m in media:
        slug = m["slug"]
        if args.only and not slug.startswith(tuple(args.only)):
            continue
        cap_path = sdir / "captions" / f"{slug}.jsonl"
        if not cap_path.exists() or not m.get("video_url"):
            continue
        if not args.redo and (sdir / "alignment" / f"{slug}.json").exists():
            print(f"[{slug[:50]}] already aligned, skipping", flush=True)
            continue
        t_begin = time.time()
        caps = [json.loads(line) for line in open(cap_path)]
        span = caps[-1]["start"]
        wdir = work / slug[:50]
        full = wdir / "full.m4a"
        print(f"[{slug[:50]}] span {span / 3600:.2f} h", flush=True)
        if not download_audio(m, full, span + MARGIN_S, env):
            print("    download failed", flush=True)
            summary.append({"slug": slug, "error": "download_failed"})
            continue
        wcache = wdir / "words.json"
        if wcache.exists():
            words = [tuple(x) for x in json.load(open(wcache))]
        else:
            dur = float(
                _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                      "-of", "csv=p=0", str(full)], env, 120).stdout.strip() or 0)  # fmt: skip
            words = transcribe(full, dur, model, env)
            json.dump(words, open(wcache, "w"))
        duration = (words[-1][2] if words else 0.0) + WINDOW_S
        windows, line_times = align_windows(words, caption_words(caps), duration)
        stretches = coverage(windows)
        clips = []
        for k, s in enumerate(stretches):
            name = f"{slug[:60]}__{k:02d}.m4a"
            _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{s['start']:.2f}", "-i", str(full),
                  "-t", f"{s['end'] - s['start']:.2f}", "-vn", "-c:a", "copy", str(aout / name)], env, 600)  # fmt: skip
            clips.append({**s, "file": name})
        n_lab = n_kept = 0
        with open(sdir / "annotations_aligned" / f"{slug}.jsonl", "w") as out:
            for line in open(sdir / "annotations" / f"{slug}.jsonl"):
                a = json.loads(line)
                n_lab += 1
                t = label_audio_times(a, line_times, stretches)
                if t:
                    n_kept += 1
                    t["clip"] = clips[t["clip_index"]]["file"]
                    out.write(
                        json.dumps({**a, **t, "layer": "audio_aligned_v1"}) + "\n"
                    )
        json.dump(
            {"slug": slug, "windows": windows, "stretches": clips},
            open(sdir / "alignment" / f"{slug}.json", "w"),
        )
        hours = sum(c["end"] - c["start"] for c in clips) / 3600
        tot = sum(1 for w in windows if w["asr_words"] >= 15)
        ok = sum(1 for w in windows if w["verified"])
        rec = {"slug": slug, "verified_hours": round(hours, 2), "clips": len(clips),
               "windows_verified": ok, "windows_with_speech": tot,
               "labels": n_lab, "labels_kept": n_kept,
               "minutes_spent": round((time.time() - t_begin) / 60, 1)}  # fmt: skip
        print("    " + json.dumps(rec), flush=True)
        summary.append(rec)
        if not args.keep_full_audio:
            full.unlink(missing_ok=True)
    json.dump(summary, open(sdir / "alignment_summary.json", "w"), indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
