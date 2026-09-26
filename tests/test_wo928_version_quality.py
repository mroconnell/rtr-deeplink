"""scripts/wo928_version_quality.py -- the source- and era-aware, read-only
comparison of a page's transcript versions (WO-928; it replaces WO-927's
cue/word-count rules).

The cue lists are synthetic on purpose: the facts (which real pages, what the
real defects looked like) live in BACKLOG_DONE.md and rtr-business
research/wo928_*. Each test builds the SHAPE of a defect confirmed on real
pages during the hand reads (a "Thank you." every 30 seconds across a silent
stretch, a stutter loop of one word a second apart, huge all-caps caption
blocks) plus its near-miss, and checks the classification. What is still
unconfirmed: the thresholds were set from 50 hand-read pairs, so a rare real
shape could sit outside them.
"""

import csv
import random
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import wo928_version_quality as Q  # noqa: E402
from archive.utils.transcription_quality import detect_hallucination_warnings  # noqa: E402

PRE = datetime(2026, 8, 12, tzinfo=timezone.utc)
POST = datetime(2026, 9, 5, tzinfo=timezone.utc)


def _sentence(seed, words):
    rng = random.Random(seed)
    return " ".join(
        "".join(
            rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(rng.randint(3, 8))
        )
        for _ in range(words)
    )


def speech(n, words=9, step=8, seed=0):
    """Cues whose texts are unlike each other (real speech is; a template
    like "item 1 word0 ..." would trip the repo's near-duplicate test)."""
    return [
        {
            "start": i * step,
            "end": i * step + 4,
            "text": _sentence(seed * 100000 + i, words),
        }
        for i in range(n)
    ]


def dead_air(n_speech=60, run=8):
    """Speech, then `run` copies of 'Thank you.' 30 seconds apart (silent
    stretch decoded window by window), then more speech."""
    cues = speech(n_speech)
    t = cues[-1]["end"] + 30
    for _ in range(run):
        cues.append({"start": t, "end": t + 1, "text": "Thank you."})
        t += 30
    for i in range(20):
        cues.append(
            {"start": t + i * 8, "end": t + i * 8 + 4, "text": _sentence(900000 + i, 8)}
        )
    return cues


def stutter(n_speech=60, run=14):
    """One real-speech word repeated a second apart (a decode loop)."""
    cues = speech(n_speech)
    t = cues[-1]["end"] + 5
    for i in range(run):
        cues.append({"start": t + i, "end": t + i + 1, "text": "Second."})
    return cues


def version(vid, default, source, created, segs, warnings=None):
    return {
        "id": vid,
        "is_default": default,
        "source": source,
        "created_at": created,
        "warnings": warnings or [],
        "segments": segs,
    }


PAGE = {"id": 1, "slug": "s"}


def test_era_boundaries_and_non_whisper():
    assert Q.era_of("transcribed", datetime(2026, 8, 17, tzinfo=timezone.utc)) == "pre"
    assert (
        Q.era_of("transcribed", datetime(2026, 8, 19, tzinfo=timezone.utc)) == "window"
    )
    assert Q.era_of("transcribed", datetime(2026, 8, 20, tzinfo=timezone.utc)) == "post"
    assert Q.era_of("sourced", PRE) == "n/a"
    assert Q.era_of("deduped", POST) == "n/a"


def test_dead_air_run_is_flagged_but_a_stutter_loop_is_not_dead_air():
    sig = Q.version_signals(dead_air())
    assert sig["dead_air_run"] >= 8
    assert "dead_air" in Q.defect_reasons(sig)
    stut = Q.version_signals(stutter())
    assert stut["dead_air_run"] == 0
    assert stut["loop_signature"] is True  # 14 in a row is the repo's own loop rule
    assert "loop" in Q.defect_reasons(stut)


def test_clean_speech_and_short_bursts_are_quiet():
    assert Q.defect_reasons(Q.version_signals(speech(200))) == []
    cues = speech(50)
    for i in range(3):  # three "Yes." in a row is a roll call, not a loop
        cues.append({"start": 500 + i, "end": 501 + i, "text": "Yes."})
    assert Q.defect_reasons(Q.version_signals(cues)) == []


def test_coarse_cues_are_flagged():
    big = [
        {"start": i * 300, "end": i * 300 + 299, "text": _sentence(i + 5000, 400)}
        for i in range(12)
    ]
    sig = Q.version_signals(big)
    assert sig["coarse_cues"] is True
    assert "coarse" in Q.defect_reasons(sig)


def test_detector_flag_matches_the_repos_own_detector():
    samples = [
        dead_air(),
        stutter(),
        speech(100),
        speech(30) + [{"start": 999, "end": 1000, "text": "a" * 40}],
        [
            {
                "start": i,
                "end": i + 1,
                "text": "Ffdame i'r I'r euel ㅎㅎㅎㅎㅎ 이것 " * 3,
            }
            for i in range(40)
        ],
    ]
    for cues in samples:
        assert Q.version_signals(cues)["detector_flag"] is bool(
            detect_hallucination_warnings(cues)
        )


def test_more_cues_is_never_better_a_clean_short_version_beats_a_looping_long_one():
    # WO-927's rule b would have promoted the hidden one (more cues, more words).
    shown = version(1, True, "transcribed", POST, speech(60))
    hidden = version(2, False, "transcribed", PRE, dead_air(n_speech=400, run=30))
    assert Q.evaluate_page(PAGE, [shown, hidden]) == []


def test_category_a_pre_vad_shown_with_dead_air_and_clean_post_hidden():
    shown = version(1, True, "transcribed", PRE, dead_air())
    hidden = version(2, False, "transcribed", POST, speech(80))
    rows = Q.evaluate_page(PAGE, [shown, hidden])
    assert sorted(r["category"] for r in rows) == ["A", "B"]
    assert rows[0]["hidden_id"] == 2


def test_category_b_shown_coarse_captions_hidden_clean_whisper():
    big = [
        {"start": i * 300, "end": i * 300 + 299, "text": _sentence(i + 5000, 400)}
        for i in range(12)
    ]
    shown = version(1, True, "sourced", POST, big)
    hidden = version(2, False, "transcribed", POST, speech(80))
    rows = Q.evaluate_page(PAGE, [shown, hidden])
    assert [r["category"] for r in rows] == ["B"]


def test_a_repaired_copy_takes_its_parents_era_and_is_not_a_win():
    parent = dead_air()
    copy = parent[:-2]  # the repair tool drops a couple of cues, keeps the rest
    shown = version(2, True, "transcribed", POST, copy)  # made after VAD
    hidden = version(1, False, "transcribed", PRE, parent)  # the pre-VAD text
    rows = Q.evaluate_page(PAGE, [shown, hidden])
    assert [r["category"] for r in rows] == ["C"]  # pre-VAD text, nothing cleaner
    assert rows[0]["shown_era"] == "pre"
    assert rows[0]["shown_derived_from"] == 1


def test_category_c_single_pre_vad_version_with_defect_only():
    rows = Q.evaluate_page(PAGE, [version(1, True, "transcribed", PRE, dead_air())])
    assert [r["category"] for r in rows] == ["C"]
    assert (
        Q.evaluate_page(PAGE, [version(1, True, "transcribed", PRE, speech(90))]) == []
    )
    assert (
        Q.evaluate_page(PAGE, [version(1, True, "transcribed", POST, dead_air())]) == []
    )


async def test_run_classifies_a_seeded_page_and_writes_nothing(tmp_path):
    from sqlalchemy import func, select

    from archive.db.engine import async_session
    from archive.db.models import MeetingPage, TranscriptVersion

    tag = uuid.uuid4().hex[:10]
    async with async_session() as session:
        page = MeetingPage(
            slug=f"wo928-{tag}",
            platform="testplat",
            source_url_normalized=f"wo928:{tag}",
        )
        session.add(page)
        await session.flush()
        for is_default, created, cues, h in (
            (True, PRE, dead_air(), "a"),
            (False, POST, speech(80), "b"),
        ):
            session.add(
                TranscriptVersion(
                    meeting_page_id=page.id,
                    language="en",
                    source="transcribed",
                    is_default=is_default,
                    segments=cues,
                    content_hash=f"{tag}{h}",
                    created_at=created,
                )
            )
        await session.commit()
        page_id = page.id

    async with async_session() as session:
        before = (
            await session.execute(select(func.count(TranscriptVersion.id)))
        ).scalar_one()

    out = tmp_path / "out.csv"
    # Only this test's page: a full run read every page other test modules
    # left in the shared DB (WO-1084). The same read path, CSV write and
    # read-only guarantee are exercised either way.
    tally = await Q.run(str(out), None, only_page_ids=[page_id])
    with open(out) as fh:
        rows = list(csv.DictReader(fh))
    assert {r["page_id"] for r in rows} == {str(page_id)}
    assert sorted(r["category"] for r in rows) == ["A", "B"]
    assert tally["pages_read"] == 1
    assert tally["category_A"] == 1

    async with async_session() as session:
        after = (
            await session.execute(select(func.count(TranscriptVersion.id)))
        ).scalar_one()
    assert after == before
