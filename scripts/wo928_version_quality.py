"""WO-928: a source- and era-aware, read-only comparison of the transcript
versions a page holds. It REPLACES scripts/wo927_worse_shown_versions.py,
whose rules b and b2 treated "more cues / more words" as "better".

Why the WO-927 rules were wrong. Our own Whisper transcripts before voice
activity filtering (Silero VAD, `vad_filter=True`, worker/transcription_
engine.py, 2026-08-18 on the local machine, merged 2026-08-20 08:17 PT for
the cloud worker) invented text over silence: repeated "Thank you.",
"Music", loops. That inflates cue and word counts. A newer Whisper version
with FEWER words is usually the cleaner one. Page 1624 (Hawaiian Gardens)
was promoted to a caption version because it had more words; 39.5% of its
cues repeated the cue before, and it was reverted.

What this script does instead. For every version it computes objective
defect signals from the text and reports each one separately, never merged
into one score. Cue count and word count are NEVER quality signals here;
words per minute is descriptive only.

  adjacent_dup_rate   share of cues whose text equals the cue before it
                      (normalised: lower case, single spaces)
  longest_run         longest run of near-identical consecutive cues, using
                      archive/utils/transcription_quality.py's own
                      `_repetition_runs` (0.85 similarity), the same tool
                      the hallucination audit uses
  dead_air_run        longest run (4+ cues) of near-identical cues spaced 20s
                      or more apart on average: the shape a silent stretch
                      makes when Whisper decodes it window by window ("Thank
                      you." every 30s for 13 minutes). VAD prevents exactly
                      this; a stutter loop of real speech has cues seconds
                      apart and does not match
  loop_signature      that module's own hallucination-loop rule
                      (`_has_hallucinated_repetition_run`): a run of 12+ or a
                      tiled run of 6+ over 10+ seconds
  detector_flag       `detect_hallucination_warnings()` fires (loop, long
                      character run, non-Latin ratio): the audit's own test
  rollup_ratio        roll-up overlap: scripts/dedupe_rollup_transcripts.py's
                      adjacent-line overlap ratio (caption roll-up shape)
  label_only          median words per cue under 3 (the Edina shape)
  coarse_cues         median words per cue 100 or more: a few huge blocks
                      (typically all-caps caption chunks) that cannot be
                      deep-linked; seen on 3 of the 48 hand-read pairs
  stock_phrase_rate   share of cues that are a stock silence hallucination
                      ("thank you", "thanks for watching", "music"...);
                      descriptive, shown beside the others
  flagged             the version already carries a garbled, hallucination
                      or truncation warning
  last_cue_seconds    time of the last cue (coverage against the video's
                      duration is only computed when a duration is supplied;
                      the Archive stores none on the page)

Era. A version's `created_at` is the day its TEXT was first stored on that
page: an identical re-push reuses the row (content hash), so it can never
make old text look new. It can still mislead in two directions: repaired
copies (`drop-segments`, roll-up de-duplication) are new rows made later from
older text, and nothing on a version row records the engine or the VAD
setting. So the era is a label with a known error, not a fact:
  pre     created before 2026-08-18 00:00 PT (VAD not yet in use anywhere)
  window  2026-08-18 00:00 PT .. 2026-08-19 21:00 UTC (mixed: some machines
          had VAD, others did not; 25% still show dead air)
  post    later (3% show dead air)
  n/a     not a Whisper version ('sourced' captions, 'deduped')
See BACKLOG_DONE.md WO-928 for the measured error.

Read-only. Explicit SELECTs only; one page at a time; never writes to the
database. Safe to stop: the CSV is flushed after every page. Run from the
Archive service's Render Shell (local to the database), never against the
production database from a laptop.

Usage (Archive Render Shell, repo root):
    python scripts/wo928_version_quality.py --out wo928_full.csv
    python scripts/wo928_version_quality.py --limit 50 --out /tmp/x.csv

Output: one row per (page, hidden version) pair for a multi-version page,
plus one row per single-version Whisper page from before VAD, each with
both versions' signals and the category (A/B/C below). It never promotes:
Ryan decides that.

Categories:
  A  shown is a pre-VAD/window Whisper version with a defect signal and a
     clean post-VAD Whisper version is hidden
  B  shown has a defect signal and a hidden version has none
  C  the shown version is a pre-VAD/window Whisper text (or a repaired copy
     of one) with a defect signal and no cleaner version is hidden (the
     re-transcription pool; includes single-version pages)
"""

import argparse
import asyncio
import csv
import statistics
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from archive.utils.transcription_quality import (  # noqa: E402
    _CHAR_RUN_RE,
    _HALLUCINATION_ABSOLUTE_RUN_LENGTH,
    _HALLUCINATION_MIN_ALPHA_CHARS_FOR_SCRIPT_CHECK,
    _HALLUCINATION_MIN_SEGMENTS_FOR_REPETITION_CHECK,
    _HALLUCINATION_NON_LATIN_RATIO_THRESHOLD,
    _HALLUCINATION_REPETITION_RUN_RATIO_THRESHOLD,
    _HALLUCINATION_TILED_COVERAGE_RATIO,
    _HALLUCINATION_TILED_MIN_SECONDS,
    _HALLUCINATION_TILED_RUN_LENGTH,
    _normalize_for_repetition,
    _repetition_runs,
    _run_span_and_coverage,
)

# 2026-08-18 00:00 PT (UTC-7): Ryan confirms VAD was in use on the local
# machine from the 18th; the commit reached `main` (and so the cloud worker)
# on 2026-08-20 08:17:41 PT. Measured from the text itself (WO-928): the
# "dead air" hallucination (see dead_air_run) was on 27% of Whisper versions
# stored before 08-18, 25% between 08-18 and 08-19 21:00 UTC, and 3% after,
# so the effective cutover is 2026-08-19 21:00 UTC, not the 18th.
VAD_LOCAL_START = datetime(2026, 8, 18, 7, 0, tzinfo=timezone.utc)
VAD_EFFECTIVE_START = datetime(2026, 8, 19, 21, 0, tzinfo=timezone.utc)
# A repaired copy shares at least this share of its cues (same start second and
# text) with the older version it was made from.
DERIVED_SHARE = 0.9

# Duplicated from archive/db/crud.py on purpose: importing crud pulls the
# whole app; these substrings are pinned by tests there.
GARBLED_MARKER = "looks garbled at the source"
HALLUCINATION_MARKER = "hallucinated by the transcription model"
TRUNCATION_MARKERS = (
    "36,000 lines, a known limit",
    "the transcription was interrupted",
    "may end before the meeting did",
)

STOCK_PHRASES = frozenset(
    {
        "thank you",
        "thank you.",
        "thanks for watching",
        "thanks for watching!",
        "thanks for watching.",
        "music",
        "[music]",
        "(music)",
        "bye",
        "bye.",
        "you",
        "thank you very much.",
        "thank you for watching.",
    }
)

# Signals thresholds. Set from the WO-928 hand-read calibration (see
# BACKLOG_DONE.md); the runs come from the repo's own definitions.
ADJACENT_DUP_DEFECT_RATE = 0.10
LABEL_ONLY_MEDIAN_WORDS = 3
COARSE_MEDIAN_WORDS = 100
DEAD_AIR_MIN_GAP_SECONDS = 20.0
DEAD_AIR_DEFECT_RUN = 4
ROLLUP_DEFECT_RATIO = 0.20  # scripts/dedupe_rollup_transcripts.DETECTOR_GATE_RATIO


def _aware(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def era_of(source: str, created_at) -> str:
    """'pre' | 'window' | 'post' | 'n/a' -- a labelled guess, see module doc."""
    if source != "transcribed":
        return "n/a"
    created = _aware(created_at)
    if created is None:
        return "unknown"
    if created < VAD_LOCAL_START:
        return "pre"
    if created < VAD_EFFECTIVE_START:
        return "window"
    return "post"


def _has(warnings, *needles) -> bool:
    text = " ".join(warnings or [])
    return any(n in text for n in needles)


def _detector_flag(segs, longest_run, loop) -> bool:
    """Same verdict as `detect_hallucination_warnings(segs)` (that module's
    own rules and constants) computed from the runs already in hand; the
    non-Latin check only asks `unicodedata` about non-ASCII letters (every
    ASCII letter is Latin), which is the difference between seconds and
    minutes on a 3,000-cue meeting. A test pins the two together."""
    n = len(segs)
    if not n:
        return False
    if n >= _HALLUCINATION_MIN_SEGMENTS_FOR_REPETITION_CHECK and (
        loop or longest_run / n >= _HALLUCINATION_REPETITION_RUN_RATIO_THRESHOLD
    ):
        return True
    sample = "".join(str(s.get("text") or "") for s in segs)
    if _CHAR_RUN_RE.search(sample):
        return True
    alpha = [c for c in sample if c.isalpha()]
    if len(alpha) < _HALLUCINATION_MIN_ALPHA_CHARS_FOR_SCRIPT_CHECK:
        return False
    non_latin = sum(
        1 for c in alpha if not c.isascii() and "LATIN" not in unicodedata.name(c, "")
    )
    return non_latin / len(alpha) >= _HALLUCINATION_NON_LATIN_RATIO_THRESHOLD


def version_signals(segments, warnings=None, duration_seconds=None) -> dict:
    """Every signal for one version, reported separately."""
    segs = [s for s in (segments or []) if isinstance(s, dict)]
    texts = [_normalize_for_repetition(str(s.get("text") or "")) for s in segs]
    words = [len(t.split()) for t in texts]
    n = len(segs)
    last = max((float(s.get("end", 0) or 0) for s in segs), default=0.0)
    adjacent = sum(1 for i in range(1, n) if texts[i] and texts[i] == texts[i - 1])
    runs = _repetition_runs(segs) if n >= 2 else []
    longest = max((length for _s, length in runs), default=0)
    median = statistics.median(words) if words else 0
    dead_air = 0
    loop = False
    for start, length in runs:
        run = segs[start : start + length]
        if length >= 4:
            starts = [float(x.get("start", 0) or 0) for x in run]
            if (starts[-1] - starts[0]) / (length - 1) >= DEAD_AIR_MIN_GAP_SECONDS:
                dead_air = max(dead_air, length)
        if length >= _HALLUCINATION_ABSOLUTE_RUN_LENGTH:
            loop = True
        elif length >= _HALLUCINATION_TILED_RUN_LENGTH:
            span, coverage = _run_span_and_coverage(run)
            if (
                span >= _HALLUCINATION_TILED_MIN_SECONDS
                and coverage >= _HALLUCINATION_TILED_COVERAGE_RATIO
            ):
                loop = True
    loop = bool(loop and n >= _HALLUCINATION_MIN_SEGMENTS_FOR_REPETITION_CHECK)
    detector_flag = _detector_flag(segs, longest, loop)
    stock = sum(1 for t in texts if t in STOCK_PHRASES)
    ratio = 0.0
    if n >= 2:
        try:
            from scripts.dedupe_rollup_transcripts import rollup_ratio

            ratio = rollup_ratio(segs)[0]
        except Exception:  # noqa: BLE001 - descriptive only
            ratio = 0.0
    total_words = sum(words)
    signals = {
        "cues": n,
        "last_cue_seconds": round(last, 1),
        "words_per_minute": round(total_words / (last / 60), 1) if last else 0.0,
        "adjacent_dup_rate": round(adjacent / (n - 1), 3) if n > 1 else 0.0,
        "longest_run": longest,
        "dead_air_run": dead_air,
        "loop_signature": loop,
        "detector_flag": detector_flag,
        "rollup_ratio": round(ratio, 3),
        "label_only": bool(n and median < LABEL_ONLY_MEDIAN_WORDS),
        "coarse_cues": bool(n and median >= COARSE_MEDIAN_WORDS),
        "median_words_per_cue": median,
        "stock_phrase_rate": round(stock / n, 3) if n else 0.0,
        "flagged": _has(warnings, GARBLED_MARKER, HALLUCINATION_MARKER)
        or _has(warnings, *TRUNCATION_MARKERS),
        "coverage": (round(last / duration_seconds, 3) if duration_seconds else None),
    }
    return signals


def defect_reasons(sig: dict) -> list[str]:
    """Which objective signals mark this version defective. Each named
    separately; deliberately no score."""
    out = []
    if sig["adjacent_dup_rate"] >= ADJACENT_DUP_DEFECT_RATE:
        out.append("adjacent_dup")
    if sig["dead_air_run"] >= DEAD_AIR_DEFECT_RUN:
        out.append("dead_air")
    if sig["loop_signature"]:
        out.append("loop")
    if sig["label_only"]:
        out.append("label_only")
    if sig["coarse_cues"]:
        out.append("coarse")
    if sig["rollup_ratio"] >= ROLLUP_DEFECT_RATIO:
        out.append("rollup")
    if sig["flagged"]:
        out.append("flagged")
    return out


def classify_pair(shown: dict, hidden: dict) -> list[str]:
    """Categories (A, B) for one shown/hidden pair. Each dict has `source`,
    `era`, `sig`. Never compares cue or word counts."""
    cats = []
    s_def = defect_reasons(shown["sig"])
    h_def = defect_reasons(hidden["sig"])
    if not s_def or h_def:
        return cats
    cats.append("B")
    if (
        shown["source"] == "transcribed"
        and shown["era"] in ("pre", "window")
        and hidden["source"] == "transcribed"
        and hidden["era"] == "post"
    ):
        cats.append("A")
    return cats


def classify_single(version: dict) -> list[str]:
    if (
        version["source"] == "transcribed"
        and version["era"] in ("pre", "window")
        and defect_reasons(version["sig"])
    ):
        return ["C"]
    return []


FIELDS = [
    "page_id",
    "slug",
    "category",
    "shown_id",
    "shown_source",
    "shown_era",
    "shown_defects",
    "hidden_id",
    "hidden_source",
    "hidden_era",
    "hidden_defects",
    "shown_signals",
    "hidden_signals",
    "shown_derived_from",
]


def _detail(v) -> str:
    sig = v["sig"]
    return (
        f"dead_air={sig['dead_air_run']} longest_run={sig['longest_run']} "
        f"dup={sig['adjacent_dup_rate']} rollup={sig['rollup_ratio']} "
        f"median_words={sig['median_words_per_cue']} wpm={sig['words_per_minute']}"
    )


def _row_for(page, category, shown, hidden):
    return {
        "page_id": page["id"],
        "slug": page["slug"],
        "category": category,
        "shown_id": shown["id"],
        "shown_source": shown["source"],
        "shown_era": shown["era"],
        "shown_defects": ";".join(defect_reasons(shown["sig"])),
        "hidden_id": hidden["id"] if hidden else "",
        "hidden_source": hidden["source"] if hidden else "",
        "hidden_era": hidden["era"] if hidden else "",
        "hidden_defects": ";".join(defect_reasons(hidden["sig"])) if hidden else "",
        "shown_signals": _detail(shown),
        "hidden_signals": _detail(hidden) if hidden else "",
        "shown_derived_from": shown["derived_from"],
    }


def _cue_keys(segments) -> set:
    return {
        (
            round(float(seg.get("start", 0) or 0)),
            _normalize_for_repetition(str(seg.get("text") or "")),
        )
        for seg in segments or []
        if isinstance(seg, dict)
    }


def derived_share(new_segments, old_segments) -> float:
    """Share of `new_segments` cues that also appear (same start second, same
    text) in `old_segments`. A repaired copy made by the seam-duplication or
    loop-collapse tools scores 1.0 against the version it came from; a fresh
    re-transcription scores near 0 (measured on 77 real pairs, WO-928: 55
    at 1.0 and 12 under 0.15; the rest are a third version on the page)."""
    new = _cue_keys(new_segments)
    if not new:
        return 0.0
    return len(new & _cue_keys(old_segments)) / len(new)


def resolve_eras(enriched: list[dict]) -> None:
    """Adds `era_effective` and `derived_from` to each dict in place. A
    Whisper version that is a repaired copy of an older Whisper version on the
    same page takes that version's era: `created_at` says when the copy was
    made, not when the text was transcribed (106 copies were made 2026-08-31
    05:07-05:09 UTC from pre-VAD text)."""
    whisper = [v for v in enriched if v["source"] == "transcribed"]
    whisper.sort(key=lambda v: str(v["created_at"]))
    for v in enriched:
        v["era_effective"] = v["era"]
        v["derived_from"] = ""
    for i, v in enumerate(whisper):
        for older in whisper[:i]:
            if str(older["created_at"]) == str(v["created_at"]):
                continue
            if derived_share(v["segments"], older["segments"]) >= DERIVED_SHARE:
                v["derived_from"] = older["id"]
                v["era_effective"] = older["era_effective"]
                break


def evaluate_page(page: dict, versions: list[dict]) -> list[dict]:
    """versions: dicts with id, is_default, source, created_at, warnings,
    segments. Returns CSV rows (possibly none). Pure: no I/O."""
    enriched = []
    for v in versions:
        enriched.append(
            {
                "id": v["id"],
                "is_default": v["is_default"],
                "source": v["source"],
                "era": era_of(v["source"], v.get("created_at")),
                "created_at": v.get("created_at"),
                "segments": v["segments"],
                "sig": version_signals(v["segments"], v.get("warnings")),
            }
        )
    resolve_eras(enriched)
    for v in enriched:
        v["era"] = v["era_effective"]  # classification uses the effective era
    shown = next((v for v in enriched if v["is_default"]), None)
    if shown is None:
        return []
    hidden = [v for v in enriched if v is not shown]
    rows = []
    if not hidden:
        for cat in classify_single(shown):
            rows.append(_row_for(page, cat, shown, None))
        return rows
    for h in hidden:
        for cat in classify_pair(shown, h):
            rows.append(_row_for(page, cat, shown, h))
    if not any(r["category"] in ("A", "B") for r in rows):
        # Nothing hidden is cleaner: a pre-VAD Whisper text with a defect on
        # its own still belongs in the re-transcription pool.
        for cat in classify_single(shown):
            rows.append(_row_for(page, cat, shown, None))
    return rows


async def run(
    out_path: str, limit: int | None, *, only_page_ids: list[int] | None = None
) -> Counter:
    """`only_page_ids` restricts the read to those pages. The command line
    never passes it; it lets the test read its own seeded page instead of
    every page in the suite's shared database (WO-1084)."""
    from sqlalchemy import select

    from archive.db.engine import async_session
    from archive.db.models import MeetingPage, TranscriptVersion

    async with async_session() as session:
        stmt = select(TranscriptVersion.meeting_page_id).distinct()
        if only_page_ids is not None:
            stmt = stmt.where(TranscriptVersion.meeting_page_id.in_(only_page_ids))
        page_ids = sorted(set((await session.execute(stmt)).scalars().all()))
    if limit:
        page_ids = page_ids[:limit]
    print(f"{len(page_ids)} page(s) with versions to read (read-only)", flush=True)

    tally: Counter = Counter()
    with open(out_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        for index, page_id in enumerate(page_ids, start=1):
            async with async_session() as session:
                page = (
                    await session.execute(
                        select(MeetingPage.id, MeetingPage.slug).where(
                            MeetingPage.id == page_id
                        )
                    )
                ).one_or_none()
                rows = (
                    await session.execute(
                        select(
                            TranscriptVersion.id,
                            TranscriptVersion.is_default,
                            TranscriptVersion.source,
                            TranscriptVersion.created_at,
                            TranscriptVersion.transcript_warnings,
                            TranscriptVersion.segments,
                        ).where(TranscriptVersion.meeting_page_id == page_id)
                    )
                ).all()
            if page is None:
                continue
            versions = [
                {
                    "id": r.id,
                    "is_default": r.is_default,
                    "source": r.source,
                    "created_at": r.created_at,
                    "warnings": r.transcript_warnings,
                    "segments": r.segments,
                }
                for r in rows
            ]
            tally["pages_read"] += 1
            if len(versions) > 1:
                tally["multi_version_pages"] += 1
            for row in evaluate_page({"id": page.id, "slug": page.slug}, versions):
                writer.writerow(row)
                tally[f"category_{row['category']}"] += 1
            fh.flush()
            if index % 200 == 0:
                print(f"  {index}/{len(page_ids)} {dict(tally)}", flush=True)
    return tally


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", default="wo928_full.csv")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv()
    tally = asyncio.run(run(args.out, args.limit))
    print(f"pages read: {tally['pages_read']}")
    for cat in ("A", "B", "C"):
        print(f"  category {cat}: {tally[f'category_{cat}']} row(s)")
    print(f"CSV: {args.out}")


if __name__ == "__main__":
    main()
