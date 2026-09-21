"""WO-927: count the pages that SHOW a worse transcript than a HIDDEN
version they already hold. Read-only: it issues SELECTs only and writes
nothing to the database.

Why it exists. The Edina MN page showed speaker labels only ("S1:", "s2:")
while a hidden version of the same page held the real words (WO-926).
WO-927 measured how common that is from the outside, over public
transcript URLs (BACKLOG_DONE.md, WO-927): exact for the warning and
language rules, exact for the cue-count screen, but only a lower bound for
the label-only rule, because reading every multi-version page over the
public site would break the standing "no bulk workload" decision. Run
from the Archive service's Render Shell, this script reads the same
versions locally and gives the exact count for every rule.

What it does. It lists the pages that hold more than one TranscriptVersion
(a light GROUP BY, no segment blobs), then loads ONE page's versions at a
time, computes each version's numbers from its own cues and reports each
rule separately. Rules, all objective, never merged into one score:

  a_label_only     shown median words per cue < 3, hidden >= 5 (Edina shape)
  b_fewer_cues     shown has < 60% of a hidden version's cues and the
                   hidden version's last cue is later
  b2_fewer_words   rule b, and the hidden version has >= 1.25x the words
                   (separates a real loss from a different way of cutting
                   the same words into cues)
  c_shown_flagged  shown carries a garbled/hallucination/truncation warning
                   that the hidden version lacks
  d_language       shown carries a language-mismatch warning, the hidden
                   version does not and its language differs

A hidden version that is itself flagged garbled/hallucinated is never
"better". The video's own language is not stored, so rule d uses the shown
version's own "captions appear to be in ..." warning as the evidence.

Usage (Archive service Render Shell, repo root):
    python scripts/wo927_worse_shown_versions.py --out wo927_worse_shown_full.csv
    python scripts/wo927_worse_shown_versions.py --limit 50 --out /tmp/x.csv

Safe to stop: nothing is written to the database, and the CSV is flushed
after every page. It never promotes anything -- Ryan decides that.
"""

import argparse
import asyncio
import csv
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RULES = (
    "a_label_only",
    "b_fewer_cues",
    "b2_fewer_words",
    "c_shown_flagged",
    "d_language",
)


def _bad_flags(warnings) -> dict:
    text = " ".join(warnings or [])
    return {
        "bad": "looks garbled" in text or "hallucinated" in text,
        "trunc": "may end before" in text,
    }


def version_stats(segments) -> dict:
    words = [len(str(s.get("text", "")).split()) for s in segments or []]
    cues = len(words)
    return {
        "cues": cues,
        "words": sum(words),
        "median": statistics.median(words) if words else 0,
        "last": max((float(s.get("end", 0) or 0) for s in segments), default=0.0),
    }


def evaluate_page(versions: list[dict]) -> dict[str, list[int]]:
    """versions: dicts with id, is_default, language, source, warnings,
    segments. Returns {rule: [hidden version ids that beat the shown one]}."""
    shown = next((v for v in versions if v["is_default"]), None)
    if shown is None:
        return {}
    s_stats = version_stats(shown["segments"])
    s_flags = _bad_flags(shown["warnings"])
    s_lang_warn = [w for w in shown["warnings"] or [] if "appear to be in" in w]
    out: dict[str, list[int]] = {}
    for h in versions:
        if h is shown:
            continue
        h_stats = version_stats(h["segments"])
        h_flags = _bad_flags(h["warnings"])
        if h_flags["bad"]:
            continue  # a hidden version that is itself garbled is not better
        if s_stats["median"] < 3 and h_stats["median"] >= 5:
            out.setdefault("a_label_only", []).append(h["id"])
        if (
            h_stats["cues"]
            and s_stats["cues"] < 0.6 * h_stats["cues"]
            and h_stats["last"] > s_stats["last"]
        ):
            out.setdefault("b_fewer_cues", []).append(h["id"])
            if h_stats["words"] >= 1.25 * s_stats["words"]:
                out.setdefault("b2_fewer_words", []).append(h["id"])
        if (s_flags["bad"] or s_flags["trunc"]) and not h_flags["trunc"]:
            out.setdefault("c_shown_flagged", []).append(h["id"])
        h_lang_warn = [w for w in h["warnings"] or [] if "appear to be in" in w]
        if s_lang_warn and not h_lang_warn and shown["language"] != h["language"]:
            out.setdefault("d_language", []).append(h["id"])
    return out


async def run(out_path: str, limit: int | None) -> Counter:
    from sqlalchemy import func, select

    from archive.db.engine import async_session
    from archive.db.models import MeetingPage, TranscriptVersion

    async with async_session() as session:
        stmt = (
            select(TranscriptVersion.meeting_page_id)
            .group_by(TranscriptVersion.meeting_page_id)
            .having(func.count(TranscriptVersion.id) > 1)
            .order_by(TranscriptVersion.meeting_page_id)
        )
        page_ids = list((await session.execute(stmt)).scalars().all())
    if limit:
        page_ids = page_ids[:limit]
    print(f"{len(page_ids)} multi-version page(s) to read (read-only)", flush=True)

    tally: Counter = Counter()
    with open(out_path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "page_id",
                "slug",
                "platform",
                "rule",
                "shown_version_id",
                "better_hidden_version_ids",
            ]
        )
        for index, page_id in enumerate(page_ids, start=1):
            async with async_session() as session:
                page = (
                    await session.execute(
                        select(
                            MeetingPage.id, MeetingPage.slug, MeetingPage.platform
                        ).where(MeetingPage.id == page_id)
                    )
                ).one_or_none()
                rows = (
                    await session.execute(
                        select(
                            TranscriptVersion.id,
                            TranscriptVersion.is_default,
                            TranscriptVersion.language,
                            TranscriptVersion.source,
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
                    "language": r.language,
                    "source": r.source,
                    "warnings": r.transcript_warnings,
                    "segments": r.segments,
                }
                for r in rows
            ]
            tally["pages_read"] += 1
            result = evaluate_page(versions)
            shown = next((v["id"] for v in versions if v["is_default"]), "")
            for rule, hidden in result.items():
                tally[rule] += 1
                writer.writerow(
                    [
                        page.id,
                        page.slug,
                        page.platform,
                        rule,
                        shown,
                        ";".join(map(str, hidden)),
                    ]
                )
            fh.flush()
            if index % 100 == 0:
                print(f"  {index}/{len(page_ids)} {dict(tally)}", flush=True)
    return tally


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", default="wo927_worse_shown_full.csv")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv()
    tally = asyncio.run(run(args.out, args.limit))
    print("Rule counts (pages meeting each rule; a page can meet several):")
    print(f"  multi-version pages read: {tally['pages_read']}")
    for rule in RULES:
        print(f"  {rule}: {tally[rule]}")
    print(f"CSV: {args.out}")


if __name__ == "__main__":
    main()
