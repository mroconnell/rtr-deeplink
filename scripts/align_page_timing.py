"""Correct a page's caption times to match its video (A4, WO-1960).

    python scripts/align_page_timing.py --ids 4143 9001 [--apply]
        [--work-dir /tmp/align_timing] [--report /tmp/align_timing.csv]

For each Archive page id it:
  1. reads the page and its default version's segments over HTTP
     (`GET /internal/export/pages?ids=N&include_segments=true`), never a
     database connection;
  2. downloads the meeting's audio from the city's own media host, with the
     source page's Referer, and transcribes it with a local Whisper model in
     10-minute pieces (`scripts/align_captions_to_audio.py`'s own
     `download_audio()` and `transcribe()`; the words are cached, so a rerun
     is cheap);
  3. walks the audio in 2-minute windows with that script's
     `align_windows()`, which follows a step in the offset;
  4. moves each caption line to the audio time its own words matched at
     (an unmatched line follows its matched neighbours; a match far from
     its neighbours is dropped as a false one), keeping every word and
     field and the lines' order;
  5. checks the result by matching again: the corrected captions must line
     up within MAX_RESIDUAL_S over the same windows;
  6. sends it to `POST /internal/transcript-version/add-time-corrected`
     (a dry run unless --apply). The Archive refuses any change but times,
     adds the copy as a "time-corrected" version, and promotes it. The
     source captions stay one `?version=` away.

Skips a page whose captions are already within MIN_SHIFT_S everywhere, a
page where too few windows match (the captions may not be this meeting's,
as on Dunnellon FL), YouTube pages (this is not the drip Mac), and pages
whose video is an embed page rather than media. It makes no YouTube
requests (`youtube_fetch_guard.install()`). Run it from a Mac with
`faster-whisper`'s `small` model cached and ffmpeg installed.

Reads ARCHIVE_BASE_URL and ARCHIVE_INGEST_TOKEN from .env; the token is
only ever put in an Authorization header.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

# The lowest share of speech windows that must match before a page is
# corrected; below this the captions may not belong to this recording.
MIN_VERIFIED_FRACTION = 0.5
# A page whose verified offsets all sit within this is left alone: live
# captions normally lag 1 to 6 s, and that is not what this fixes.
MIN_SHIFT_S = 6.0
# After correcting, the median remaining line offset must be within this,
# and 90% of lines within MAX_WINDOW_RESIDUAL_S.
MAX_RESIDUAL_S = 2.0
MAX_WINDOW_RESIDUAL_S = 6.0
MARGIN_S = 1500.0
_SKIP_FORMATS = {"youtube", "vimeo", "viebit", "champds"}
NOTE = (
    "The times in this transcript were moved to match the video, using the "
    "meeting's own audio. The text is the source's captions, unchanged; the "
    'source times are kept in the "sourced" version.'
)
REPORT_FIELDS = [
    "page_id",
    "slug",
    "platform",
    "decision",
    "segments",
    "windows_with_speech",
    "windows_verified",
    "lag_median",
    "lag_min",
    "lag_max",
    "residual_median",
    "residual_max",
    "segments_moved",
    "server",
    "minutes",
]


def segment_offsets(
    segments: List[Dict[str, Any]], windows: List[Dict[str, Any]]
) -> List[Optional[float]]:
    """The offset (caption time minus audio time) to remove from each
    segment: the lag of the verified window whose caption span covers the
    segment's start, else of the nearest verified window. None when no
    window is verified."""
    spans: List[Tuple[float, float, float]] = [
        (w["audio_start"] + w["lag"], w["audio_end"] + w["lag"], w["lag"])
        for w in windows
        if w.get("verified") and w.get("lag") is not None
    ]
    if not spans:
        return [None] * len(segments)
    out: List[Optional[float]] = []
    for seg in segments:
        s = float(seg["start"])
        inside = [lag for lo, hi, lag in spans if lo <= s < hi]
        if inside:
            out.append(inside[0])
            continue
        nearest = min(spans, key=lambda sp: min(abs(s - sp[0]), abs(s - sp[1])))
        out.append(nearest[2])
    return out


# A matched line whose offset is further than this from the median of its
# neighbours' is treated as a false match (a phrase said twice).
OUTLIER_S = 30.0
NEIGHBOURS = 5


def good_line_offsets(
    segments: List[Dict[str, Any]], line_times: Dict[int, Tuple[float, float]]
) -> Dict[int, float]:
    """{line index: caption start minus the audio time of the line's first
    matched word}, without lines whose offset is further than OUTLIER_S
    from the median of their NEIGHBOURS on both sides (a false match; a
    real step in the offset agrees with one side).

    Measured per line, not per window, on purpose: align_windows() dates
    every word of a caption line at the line's start, so on long lines
    (Cablecast posts lines covering up to a minute of speech) a word said
    late in a line reads as a large lag although the line itself starts on
    time. Cambridge MA's 2026-06-18 page showed window lags of -6 to -304 s
    and line offsets of -1 to +2 s."""
    raw = {
        i: float(segments[i]["start"]) - t[0]
        for i, t in line_times.items()
        if 0 <= i < len(segments)
    }
    keys = sorted(raw)
    good: Dict[int, float] = {}
    for n, i in enumerate(keys):
        left = [raw[k] for k in keys[max(0, n - NEIGHBOURS) : n]]
        right = [raw[k] for k in keys[n + 1 : n + 1 + NEIGHBOURS]]
        # A real step agrees with one side; a false match with neither.
        sides = [statistics.median(x) for x in (left, right) if x]
        if not sides or any(abs(raw[i] - m) <= OUTLIER_S for m in sides):
            good[i] = raw[i]
    return good


def line_offsets(
    segments: List[Dict[str, Any]], line_times: Dict[int, Tuple[float, float]]
) -> List[Optional[float]]:
    """Per-segment offset (caption start minus audio start) from the lines
    `align_windows()` matched word by word, which follows a recording with
    pieces cut out, where one lag per window cannot (Cambridge MA school
    committee, 2026-06-18: window lags from -6 s to -304 s, each window
    matching at 95%+). Outliers against their neighbours are dropped; an
    unmatched line takes its matched neighbours' offset, interpolated by
    caption time between them. None everywhere when nothing matched."""
    good = good_line_offsets(segments, line_times)
    if not good:
        return [None] * len(segments)
    idx = sorted(good)
    out: List[Optional[float]] = []
    pos = 0
    for i, seg in enumerate(segments):
        while pos < len(idx) and idx[pos] < i:
            pos += 1
        if pos < len(idx) and idx[pos] == i:
            out.append(good[i])
            continue
        prev = idx[pos - 1] if pos > 0 else None
        nxt = idx[pos] if pos < len(idx) else None
        if prev is None or nxt is None:
            out.append(good[prev if nxt is None else nxt])
            continue
        a, b = float(segments[prev]["start"]), float(segments[nxt]["start"])
        f = 0.0 if b <= a else (float(seg["start"]) - a) / (b - a)
        out.append(good[prev] + f * (good[nxt] - good[prev]))
    return out


def keep_order(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Clamp starts so they never go backwards (the transcript is read in
    order), and keep each end at or after its start."""
    last = 0.0
    for seg in segments:
        if seg["start"] < last:
            seg["start"] = last
        if seg.get("end") is not None and seg["end"] < seg["start"]:
            seg["end"] = seg["start"]
        last = seg["start"]
    return segments


def shift_segments(
    segments: List[Dict[str, Any]], offsets: List[Optional[float]]
) -> List[Dict[str, Any]]:
    """Copies of `segments` with start/end moved by their offset, every
    other key untouched. Never below 0."""
    out = []
    for seg, off in zip(segments, offsets):
        new = dict(seg)
        if off:
            new["start"] = round(max(0.0, float(seg["start"]) - off), 3)
            if seg.get("end") is not None:
                new["end"] = round(max(new["start"], float(seg["end"]) - off), 3)
        out.append(new)
    return out


MIN_MATCHED_LINES = 0.3


def _p90(xs: List[float]) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(0.9 * len(xs)))]


def decide(
    windows: List[Dict[str, Any]],
    segments: int,
    before: Dict[int, float],
    after: Optional[Dict[int, float]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """("correct" | a skip reason, numbers for the report). `before` and
    `after` are good_line_offsets() for the stored and the corrected
    segments; `windows` only says how much of the audio matched at all."""
    speech = [w for w in windows if w.get("asr_words", 0) >= 15]
    verified = [w for w in speech if w.get("verified")]
    info: Dict[str, Any] = {
        "windows_with_speech": len(speech),
        "windows_verified": len(verified),
    }
    offs = list(before.values())
    if offs:
        info.update(
            lag_median=round(statistics.median(offs), 1),
            lag_min=round(min(offs), 1),
            lag_max=round(max(offs), 1),
        )
    if not speech:
        return "skip: no speech found", info
    if len(verified) / len(speech) < MIN_VERIFIED_FRACTION:
        return "skip: too few windows match the audio", info
    if len(offs) < MIN_MATCHED_LINES * segments:
        return "skip: too few caption lines match the audio", info
    if _p90([abs(x) for x in offs]) < MIN_SHIFT_S:
        return "skip: already aligned", info
    if after is None:
        return "correct", info
    res = [abs(x) for x in after.values()]
    if res:
        info.update(
            residual_median=round(statistics.median(res), 1),
            residual_max=round(_p90(res), 1),
        )
    if len(res) < 0.8 * len(offs):
        return "skip: the corrected times no longer match as well", info
    if statistics.median(res) > MAX_RESIDUAL_S or _p90(res) > MAX_WINDOW_RESIDUAL_S:
        return "skip: still off after correcting", info
    return "correct", info


def _download(
    media: Dict[str, Any], dest: Path, seconds: float, env: Dict[str, str]
) -> str:
    """align_captions_to_audio.download_audio()'s ffmpeg command, but
    returning ffmpeg's own error ("" on success) instead of a bare False."""
    import subprocess
    from urllib.parse import urlparse

    from align_captions_to_audio import _UA

    if dest.exists() and dest.stat().st_size > 100000:
        return ""
    o = urlparse(media.get("source") or media["video_url"])
    hdr = f"User-Agent: {_UA}\r\nReferer: {o.scheme}://{o.netloc}/\r\n"
    try:
        p = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-headers", hdr, "-i", media["video_url"],
             "-t", str(seconds), "-vn", "-c:a", "copy", str(dest)],
            capture_output=True, text=True, env=env, timeout=7200,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        return "ffmpeg timed out"
    if p.returncode or not dest.exists() or dest.stat().st_size <= 100000:
        lines = (p.stderr or "").strip().splitlines()
        return (lines[-1] if lines else f"exit {p.returncode}")[:200]
    return ""


def _get_json(base: str, token: str, path: str) -> Any:
    import urllib.request

    req = urllib.request.Request(
        base.rstrip("/") + path, headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())


def _post_json(base: str, token: str, path: str, body: dict) -> Tuple[int, Any]:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        raw = e.read() or b""
        try:
            return e.code, json.loads(raw or b"{}")
        except ValueError:
            # e.g. a 404 page from an Archive that predates this route
            return e.code, {"body": raw[:200].decode("utf-8", "replace")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ids", nargs="+", type=int, required=True, help="page ids")
    ap.add_argument("--apply", action="store_true", help="write and promote")
    ap.add_argument("--work-dir", type=Path, default=Path("/tmp/align_timing"))
    ap.add_argument("--report", type=Path, default=None, help="per-page CSV")
    args = ap.parse_args()

    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
    import youtube_fetch_guard

    youtube_fetch_guard.install()
    from align_captions_to_audio import align_windows, caption_words, transcribe

    base = os.environ["ARCHIVE_BASE_URL"]
    token = os.environ["ARCHIVE_INGEST_TOKEN"]
    env = dict(os.environ, SSL_CERT_FILE=certifi.where(), HF_HUB_OFFLINE="1")
    os.environ.update(env)
    from faster_whisper import WhisperModel

    model = WhisperModel(
        "small", device="cpu", compute_type="int8", local_files_only=True
    )
    args.work_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for pid in args.ids:
        t0 = time.time()
        page = (
            _get_json(
                base,
                token,
                f"/internal/export/pages?ids={pid}&include_segments=true&limit=1",
            ).get("pages")
            or [None]
        )[0]
        row: Dict[str, Any] = {"page_id": pid}
        if page is None:
            rows.append({**row, "decision": "skip: no such page"})
            continue
        slug = page["slug"]
        row.update(slug=slug, platform=page.get("platform"))
        default = next(
            (v for v in page.get("versions") or [] if v.get("is_default")), None
        )
        segs = page.get("default_version_segments") or []
        fmt = (page.get("video_format") or "").lower()
        video_url = page.get("video_url") or ""
        why = None
        if not default or not segs:
            why = "skip: no transcript"
        elif default.get("source") not in ("sourced", "deduped"):
            why = f"skip: default version is {default.get('source')}"
        elif fmt in _SKIP_FORMATS or "youtube" in video_url or "youtu.be" in video_url:
            why = "skip: video is not a media file"
        elif not video_url:
            why = "skip: no video"
        if why:
            rows.append({**row, "decision": why, "segments": len(segs)})
            print(f"[{slug[:60]}] {why}", flush=True)
            continue
        row["segments"] = len(segs)
        wdir = args.work_dir / slug[:60]
        wdir.mkdir(parents=True, exist_ok=True)
        wcache = wdir / "words.json"
        if wcache.exists():
            words = [tuple(x) for x in json.load(open(wcache))]
        else:
            span = max(float(s.get("end") or s["start"]) for s in segs)
            media = {
                "video_url": video_url,
                "source": page.get("source_url_normalized"),
            }
            full = wdir / "full.m4a"
            print(f"[{slug[:60]}] downloading {span / 3600:.2f} h of audio", flush=True)
            err = _download(media, full, span + MARGIN_S, env)
            if err:
                rows.append({**row, "decision": f"skip: audio download failed ({err})"})
                print(f"[{slug[:60]}] audio download failed: {err}", flush=True)
                continue
            import subprocess

            dur = float(
                subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(full)],
                    capture_output=True, text=True, env=env, timeout=120,
                ).stdout.strip() or 0
            )  # fmt: skip
            print(f"[{slug[:60]}] transcribing {dur / 3600:.2f} h", flush=True)
            words = transcribe(full, dur, model, env)
            json.dump(words, open(wcache, "w"))
            full.unlink(missing_ok=True)
        duration = (words[-1][2] if words else 0.0) + 120.0
        windows, line_times = align_windows(words, caption_words(segs), duration)
        before = good_line_offsets(segs, line_times)
        decision, info = decide(windows, len(segs), before)
        new_segs = None
        if decision == "correct":
            offs = line_offsets(segs, line_times)
            if all(o is None for o in offs):
                offs = segment_offsets(segs, windows)
            new_segs = keep_order(shift_segments(segs, offs))
            _, after_lines = align_windows(words, caption_words(new_segs), duration)
            after = good_line_offsets(new_segs, after_lines)
            decision, info = decide(windows, len(segs), before, after)
        row.update(info)
        if decision == "correct":
            row["segments_moved"] = sum(
                1 for a, b in zip(segs, new_segs) if a.get("start") != b.get("start")
            )
            status, resp = _post_json(
                base,
                token,
                "/internal/transcript-version/add-time-corrected",
                {
                    "slug": slug,
                    "base_version_id": default["id"],
                    "segments": new_segs,
                    "note": NOTE,
                    "promote": True,
                    "dry_run": not args.apply,
                },
            )
            row["server"] = f"{status} {json.dumps(resp)[:200]}"
            row["decision"] = (
                ("corrected" if args.apply else "would correct")
                if status == 200
                else "server refused"
            )
        else:
            row["decision"] = decision
        row["minutes"] = round((time.time() - t0) / 60, 1)
        print(f"[{slug[:60]}] {json.dumps(row)}", flush=True)
        rows.append(row)
    if args.report:
        with open(args.report, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=REPORT_FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
