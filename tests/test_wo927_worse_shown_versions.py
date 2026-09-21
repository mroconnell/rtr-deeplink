"""scripts/wo927_worse_shown_versions.py -- the read-only count of pages that
show a worse transcript than a hidden version they hold (WO-927).

The rule maths is tested on hand-built cue lists shaped like the real
cases WO-927 measured over public transcript URLs (Edina-style speaker
labels only; cue-count difference with the same words; garbled shown
version). Synthetic on purpose: the facts (which pages) live in
BACKLOG_DONE.md; this checks each rule fires on its shape and stays quiet
on its near-miss. The database test seeds a tiny SQLite Archive and
confirms the run finds the seeded page and writes nothing.
"""

import csv
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from wo927_worse_shown_versions import evaluate_page, run  # noqa: E402


def cues(n, words, step=10):
    return [
        {"start": i * step, "end": (i + 1) * step, "text": " ".join(["w"] * words)}
        for i in range(n)
    ]


def ver(vid, default, segs, warnings=None, language="en"):
    return {
        "id": vid,
        "is_default": default,
        "language": language,
        "source": "sourced",
        "warnings": warnings or [],
        "segments": segs,
    }


def test_label_only_shown_version_is_rule_a():
    shown = ver(1, True, cues(247, 1))  # "S1:" style, one token per cue
    hidden = ver(2, False, cues(247, 9))
    assert evaluate_page([shown, hidden])["a_label_only"] == [2]


def test_ordinary_transcripts_trigger_nothing():
    assert (
        evaluate_page([ver(1, True, cues(100, 8)), ver(2, False, cues(100, 8))]) == {}
    )


def test_cue_chunking_difference_is_b_but_not_b2():
    # Same words, cut into 3x as many cues: rule b fires, rule b2 does not.
    shown = ver(1, True, cues(100, 30))
    hidden = ver(2, False, cues(300, 10, step=10))
    hidden["segments"] = hidden["segments"][:300]
    result = evaluate_page([shown, hidden])
    assert result["b_fewer_cues"] == [2]
    assert "b2_fewer_words" not in result


def test_real_word_loss_is_b2():
    shown = ver(1, True, cues(20, 8))
    hidden = ver(2, False, cues(200, 8, step=10))
    result = evaluate_page([shown, hidden])
    assert result["b2_fewer_words"] == [2]


def test_hidden_version_that_is_garbled_is_never_better():
    garbled = ["This transcript looks garbled at the source (not a parsing b..."]
    shown = ver(1, True, cues(247, 1))
    hidden = ver(2, False, cues(247, 9), warnings=garbled)
    assert evaluate_page([shown, hidden]) == {}


def test_shown_flagged_and_hidden_clean_is_rule_c():
    warn = ["This transcript looks like it may be hallucinated by the tra..."]
    shown = ver(1, True, cues(50, 8), warnings=warn)
    hidden = ver(2, False, cues(50, 8))
    assert evaluate_page([shown, hidden])["c_shown_flagged"] == [2]


def test_language_mismatch_warning_and_different_language_is_rule_d():
    warn = ["These captions appear to be in 'es', not 'en' -- no matching-..."]
    shown = ver(1, True, cues(50, 8), warnings=warn, language="es")
    hidden = ver(2, False, cues(50, 8), language="en")
    assert evaluate_page([shown, hidden])["d_language"] == [2]


async def test_run_finds_seeded_page_and_writes_nothing(tmp_path):
    from sqlalchemy import func, select

    from archive.db.engine import async_session
    from archive.db.models import MeetingPage, TranscriptVersion

    tag = uuid.uuid4().hex[:10]
    async with async_session() as session:
        page = MeetingPage(
            slug=f"wo927-{tag}",
            platform="testplat",
            source_url_normalized=f"wo927:{tag}",
        )
        session.add(page)
        await session.flush()
        for is_default, n_words, h in ((True, 1, "a"), (False, 9, "b")):
            session.add(
                TranscriptVersion(
                    meeting_page_id=page.id,
                    language="en",
                    source="sourced",
                    is_default=is_default,
                    segments=cues(247, n_words),
                    content_hash=f"{tag}{h}",
                )
            )
        await session.commit()
        page_id = page.id

    async with async_session() as session:
        before = (
            await session.execute(select(func.count(TranscriptVersion.id)))
        ).scalar_one()

    out = tmp_path / "out.csv"
    tally = await run(str(out), None)
    with open(out) as fh:
        mine = [r for r in csv.DictReader(fh) if r["page_id"] == str(page_id)]
    assert [r["rule"] for r in mine] == ["a_label_only"]
    assert tally["a_label_only"] >= 1

    async with async_session() as session:
        after = (
            await session.execute(select(func.count(TranscriptVersion.id)))
        ).scalar_one()
    assert after == before
