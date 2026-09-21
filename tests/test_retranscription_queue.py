"""Guards on the WO-929 re-transcription queue.

`scripts/retranscription_queue.txt` lists archived pages that already have a
transcript (older Whisper text with a defect) and are to be transcribed again
by hand on a local machine. It is a different thing from the tier-3 queue
(pages with no transcript), which a workflow advances automatically. Three
ways this could go wrong, each of which these tests turn into a failed build:

1. A URL sits in both queues. The tier-3 feeder would then ingest or pop a
   page this queue means to re-transcribe by hand, or the two runs would
   transcribe the same meeting twice.
2. Something starts reading this file automatically (a workflow, a feed
   script, the cloud worker, a glob over `scripts/*queue*`). The queue is
   meant to be run only by a person, with a person comparing old and new
   text before anything is promoted.
3. The file and its sidecar drift apart (a line with no sidecar row, or the
   reverse), so a re-run cannot be audited.

Shape-only, like tests/test_transcription_queue_files.py: nothing here
touches the network or asks whether a meeting is still live.
"""

import csv
import re
from pathlib import Path

import pytest

from app.utils.url_normalize import normalize_url
from scripts.retranscription_queue_slice import (
    finished_page_ids,
    next_urls,
    parse_sections,
    read_meta,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
QUEUE = REPO_ROOT / "scripts" / "retranscription_queue.txt"
META = REPO_ROOT / "scripts" / "retranscription_queue_meta.csv"
TIER3_FILES = [
    REPO_ROOT / "scripts" / "tier3_auto_transcription_queue.txt",
    REPO_ROOT / "scripts" / "granicus_auto_transcription_queue.txt",
    REPO_ROOT / "scripts" / "tier3_long_meetings_deferred.txt",
    REPO_ROOT / "scripts" / "tier3_auto_transcription_queue_probe.csv",
]
META_FIELDS = [
    "url",
    "page_id",
    "slug",
    "platform",
    "hours",
    "shown_version_id",
    "defect_signal",
    "priority_rank",
    "section",
    "route",
]
SECTIONS = ["PILOT", "MAIN", "DRIP-MAC-ONLY"]
YOUTUBE_MARKERS = ("youtube", "youtu.be", "googlevideo", "ytimg")


def _sections() -> dict[str, list[str]]:
    return parse_sections(QUEUE.read_text(encoding="utf-8"))


def _all_urls() -> list[str]:
    return [u for urls in _sections().values() for u in urls]


def _meta_rows() -> list[dict]:
    return read_meta(META.read_text(encoding="utf-8"))[0]


def test_sections_are_well_formed_and_in_order():
    text = QUEUE.read_text(encoding="utf-8")
    sections = parse_sections(text)  # raises on an unclosed/duplicate section
    assert list(sections) == SECTIONS
    # The count in each start marker matches the lines inside it.
    for name, urls in sections.items():
        marker = re.search(rf"^# === SECTION: {name} \((\d+) pages, ", text, re.M)
        assert marker and int(marker.group(1)) == len(urls), name
    assert len(sections["PILOT"]) == 5


def test_every_url_is_unique_bare_and_normalised():
    urls = _all_urls()
    assert urls, "queue is empty"
    assert len(urls) == len(set(urls)), "duplicate URL in the queue"
    for u in urls:
        assert "\t" not in u and " " not in u, f"not a bare URL: {u!r}"
        assert u.startswith(("http://", "https://")), u
        assert normalize_url(u) == u, f"not normalised: {u}"


def test_no_url_is_in_a_tier3_file():
    mine = set(_all_urls())
    clash = []
    for path in TIER3_FILES:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").split("\n"):
            if not line.strip() or line.startswith("#"):
                continue
            # A queue line is `url<TAB>source_url...`; the sidecar is CSV
            # with the url first. Check every field that looks like a URL.
            fields = line.split("\t") if path.suffix == ".txt" else line.split(",")
            for field in fields:
                if field.startswith("http") and normalize_url(field) in mine:
                    clash.append((path.name, field))
    assert not clash, f"URLs in both this queue and a tier-3 file: {clash[:5]}"


def test_meta_header_and_rows_match_queue_lines():
    with META.open(encoding="utf-8") as f:
        header = next(csv.reader(f))
    assert header == META_FIELDS
    rows = _meta_rows()
    urls = _all_urls()
    assert [r["url"] for r in rows] == urls, "sidecar rows differ from queue lines"
    section_of = {u: s for s, us in _sections().items() for u in us}
    assert len({r["page_id"] for r in rows}) == len(rows), "duplicate page id"
    assert len({r["slug"] for r in rows}) == len(rows), "duplicate slug"
    ranks = [int(r["priority_rank"]) for r in rows]
    assert ranks == list(range(1, len(rows) + 1)), "priority_rank is not 1..N in order"
    for r in rows:
        assert r["section"] == section_of[r["url"]]
        assert r["route"] == (
            "drip-mac" if r["section"] == "DRIP-MAC-ONLY" else "local"
        )
        assert float(r["hours"]) > 0
        assert r["shown_version_id"].isdigit() and r["page_id"].isdigit()
        assert r["defect_signal"], "every queued page has a defect signal"


def test_youtube_pages_are_only_in_the_drip_mac_section():
    """A YouTube-hosted page may only be in the drip-Mac-only section, and
    nothing else may be there. No other machine may resolve YouTube."""
    sections = _sections()
    for section, urls in sections.items():
        for u in urls:
            is_yt = any(m in u.lower() for m in YOUTUBE_MARKERS)
            if section != "DRIP-MAC-ONLY":
                assert not is_yt, f"YouTube URL outside the drip section: {u}"
    for r in _meta_rows():
        if r["section"] == "DRIP-MAC-ONLY":
            assert r["route"] == "drip-mac"


def test_pilot_is_first_and_ranked_before_main():
    rows = _meta_rows()
    sections = [r["section"] for r in rows]
    assert sections == sorted(sections, key=SECTIONS.index)


def test_done_records_are_well_formed():
    """`# done,<page_id>,<date>,<new_version_id>,<verdict>` lines, if any."""
    text = META.read_text(encoding="utf-8")
    page_ids = {r["page_id"] for r in _meta_rows()}
    _rows, done = read_meta(text)
    for rec in done:
        assert len(rec) == 5, rec
        assert rec[1] in page_ids, f"done record for an unknown page: {rec}"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", rec[2]), rec
        assert rec[4] in {"promoted", "kept-old", "failed"}, rec


# --- nothing reads this file automatically ------------------------------

# Files that may name the queue. Everything else in code and workflows may
# not. The slice helper is a manual tool (a person runs it), and the build
# script for this test lives in the same set.
ALLOWED_TO_NAME_QUEUE = {
    "scripts/retranscription_queue_slice.py",
    "scripts/retranscription_review.py",
    "tests/test_retranscription_queue.py",
}
CODE_GLOBS = ["scripts/**/*.py", "app/**/*.py", "archive/**/*.py", "worker/**/*.py"]
WORKFLOW_GLOBS = [".github/workflows/*.yml", ".github/workflows/*.yaml"]


def _repo_files(patterns):
    for pat in patterns:
        for p in REPO_ROOT.glob(pat):
            if p.is_file() and ".venv" not in p.parts:
                yield p


def test_no_code_or_workflow_names_the_queue():
    hits = []
    for p in _repo_files(CODE_GLOBS + WORKFLOW_GLOBS):
        rel = p.relative_to(REPO_ROOT).as_posix()
        if rel in ALLOWED_TO_NAME_QUEUE:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if "retranscription_queue" in text:
            hits.append(rel)
    assert not hits, f"these files name the re-transcription queue: {hits}"


# A glob that would sweep this file up along with the tier-3 queues, in an
# automatic script or workflow: `scripts/*queue*`, `*.txt` over scripts/, a
# `queue` wildcard in a `git add`.
GLOB_PATTERNS = [
    # A wildcard under scripts/ (`scripts/*queue*`, `scripts/*.txt`).
    re.compile(r"""scripts/\*"""),
    re.compile(r"""scripts/[^\s"']*queue[^\s"']*\*"""),
    re.compile(r"""scripts/[^\s"']*\*[^\s"']*(queue|\.txt)"""),
    # A queue-named wildcard ending in .txt (`*queue*.txt`, `queue*.txt`).
    re.compile(r"""[\w*-]*queue[\w*-]*\*[\w*-]*\.txt""", re.I),
    re.compile(r"""\*[\w*-]*queue[\w*-]*\.txt""", re.I),
    # A blanket `git add` in an automatic workflow would commit this file too.
    re.compile(r"git add\s+(-A|\.|--all)(\s|$)"),
]


def test_no_script_or_workflow_globs_over_queue_files():
    hits = []
    for p in _repo_files(CODE_GLOBS + WORKFLOW_GLOBS):
        rel = p.relative_to(REPO_ROOT).as_posix()
        if rel == "tests/test_retranscription_queue.py":
            continue
        # Only automatic code matters; this scans workflows and scripts.
        if not (rel.startswith(".github/workflows/") or rel.startswith("scripts/")):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for pat in GLOB_PATTERNS:
            m = pat.search(text)
            if m:
                hits.append((rel, m.group(0)))
    assert not hits, f"broad file patterns that could reach the queue: {hits}"


def test_the_two_auto_feeders_name_only_their_own_files():
    """The feeders pop from named files. Each must name its own queue and not
    a wildcard, so the re-transcription queue is out of their reach."""
    for rel, own in [
        ("scripts/feed_tier3_auto_transcription.py", "tier3_auto_transcription_queue"),
        (
            "scripts/feed_granicus_auto_transcription.py",
            "granicus_auto_transcription_queue",
        ),
    ]:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert own in text, rel
        assert "retranscription" not in text, rel


# --- the slice helper ----------------------------------------------------


def test_slice_helper_skips_finished_pages_and_respects_count():
    sections = {"MAIN": ["u1", "u2", "u3", "u4"]}
    meta = [{"url": f"u{i}", "page_id": str(i)} for i in range(1, 5)]
    done = [
        ["done", "1", "2026-09-22", "9001", "promoted"],
        ["done", "2", "2026-09-22", "9002", "failed"],
        ["done", "3", "2026-09-22", "9003", "kept-old"],
    ]
    assert finished_page_ids(done) == {"1", "3"}
    # 1 and 3 are finished; 2 failed so it stays in line.
    assert next_urls(sections, meta, done, "MAIN", None) == ["u2", "u4"]
    assert next_urls(sections, meta, done, "MAIN", 1) == ["u2"]


@pytest.mark.parametrize(
    "bad",
    [
        "# === SECTION: A (1 pages, 1.0 hours) ===\nhttp://x\n",  # never closed
        "http://x\n",  # URL outside any section
        "# === SECTION: A (0 pages, 0.0 hours) ===\n# === END SECTION: B ===\n",
    ],
)
def test_parse_sections_rejects_malformed_files(bad):
    with pytest.raises(ValueError):
        parse_sections(bad)


# --- the review helper ---------------------------------------------------

SRT = """1
00:00:00,000 --> 00:00:05,000
Good evening everyone.

2
00:01:00,000 --> 00:01:10,500
The meeting will come to order.
"""


def test_review_parses_srt_and_hints_from_text_not_counts():
    from scripts.retranscription_review import hint, parse_srt
    from scripts.wo928_version_quality import version_signals

    segs = parse_srt(SRT)
    assert [s["text"] for s in segs] == [
        "Good evening everyone.",
        "The meeting will come to order.",
    ]
    assert segs[1]["end"] == 70.5

    old = version_signals(segs)
    assert hint(old, None) == "no-new-version"
    # Fewer cues and fewer words is fine when the text is clean and reaches
    # the same last cue: cue count is never a quality signal.
    fewer = version_signals(segs[1:])
    assert hint(old, fewer) == "new-clean"
    # A version that ends well before the old one is only a hint to look.
    short = version_signals(segs[:1])
    assert hint(old, short) == "new-shorter"
    # Four+ near-identical cues 20s+ apart is the silence signature.
    dead = version_signals(
        [
            {"start": i * 30.0, "end": i * 30.0 + 2, "text": "Thank you."}
            for i in range(6)
        ]
    )
    assert hint(old, dead) == "new-still-flagged"
