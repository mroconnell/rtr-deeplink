"""scripts/dedupe_rollup_transcripts.py -- the write-path half of WO-34:
finding already-archived pages whose *stored* transcript still holds
duplicated roll-up ("scrolling ticker") caption text, and rewriting them.

Everything here is offline. The sweep runs against a fake in-memory Archive
(`FakeArchive` below) rather than aiohttp -- what's under test is the
detection, the candidate bounds, the safety gates and the ingest+promote
ordering, not HTTP.

The detection tests are *not* synthetic. They replay the four real caption
files WO-34 was built against, plus its named negative control, through the
exact production path this script depends on:

    parse_vtt/parse_srt(real file)   -- what the pre-WO-34 adapter stored,
                                        one segment per raw cue
      -> to_srt(...)                 -- what GET /m/{slug}/transcript.srt
                                        returns for that page today
      -> parse_stored_srt(...)       -- this script's probe
      -> looks_affected(...)         -- the same detector the fix gates on

Every fixture is a verbatim excerpt of a live-fetched file (see
BACKLOG_DONE.md's WO-34 entry for provenance);
`granicus/jacksonville_clip7447_captions.vtt` was fetched 2026-08-22 from
`jaxcityc.granicus.com/videos/7447/captions.vtt` -- CLAUDE.md names that
clip as the negative control precisely because it is the same platform as
Tacoma with ordinary, non-roll-up captions.
"""

import json
import sys
from pathlib import Path

import pytest
from conftest import load_fixture

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from archive.utils.transcript_export import to_srt  # noqa: E402
from app.utils.vtt_parser import parse_srt, parse_vtt  # noqa: E402
from dedupe_rollup_transcripts import (  # noqa: E402
    CONFIDENT_ROLLUP_RATIO,
    DETECTOR_GATE_RATIO,
    ROLLUP_PLATFORMS,
    WO34_SHIP_DATE,
    State,
    build_parser,
    confidence_band,
    looks_affected,
    parse_stored_srt,
    preview_dedupe,
    rewrite_page,
    rewrite_verdict,
    rollup_ratio,
    select_candidates,
    source_host,
    total_chars,
)

# (fixture dir, filename, parser) for the four structurally different real
# roll-up cue shapes WO-34 fixed, and the real tracks that must stay
# untouched. Named exactly as CLAUDE.md names them.
ROLLUP_FIXTURES = [
    ("granicus", "tacoma_clip7460_captions.vtt", parse_vtt),
    ("civicclerk", "antiochca_event18_captions.srt", parse_srt),
    ("escribe", "essexcounty_rcc_20251203_captions.vtt", parse_vtt),
    ("youtube", "phila_education_5LZqoNDRMYk_captions.vtt", parse_vtt),
]

NON_ROLLUP_FIXTURES = [
    # CLAUDE.md's named negative control: same platform as Tacoma, ordinary
    # captions that must come through untouched.
    ("granicus", "jacksonville_clip7447_captions.vtt", parse_vtt),
    ("granicus", "simivalley_clip2840_captions.vtt", parse_vtt),
    # Genuinely garbled at the source (WO-34 measured its junk fragments at
    # 0.048, the worst non-roll-up score of 18 real files) -- the case the
    # detector's 4-character floor exists to keep out.
    ("granicus", "fountainvalley_clip607_captions.vtt", parse_vtt),
    ("escribe", "peel_region_captions.vtt", parse_vtt),
]


def stored_segments(directory: str, name: str, parser) -> list[dict]:
    """What a pre-WO-34 ingest stored for this caption file: one segment per
    raw cue, with no dedupe. `parse_vtt`/`parse_srt` is exactly the call the
    adapters made before `dedupe_rollup_cues()` was wired into the shared
    dispatch."""
    return parser(load_fixture(directory, name))


def through_the_probe(segments: list[dict]) -> list[dict]:
    """Round-trip stored segments the way this script actually sees them:
    out through the page's SRT export and back through its own reader."""
    return parse_stored_srt(to_srt(segments))


def deduped_tacoma() -> list[dict]:
    """A real, non-roll-up transcript to stand in for a good fresh resolve --
    the actual output today's parser produces from the real Tacoma file.
    Deliberately not hand-written filler: a run of identical invented lines
    scores as roll-up itself (every adjacent pair overlaps completely), which
    is a fine property of the detector but a useless stand-in for "clean"."""
    return preview_dedupe(
        through_the_probe(
            stored_segments("granicus", "tacoma_clip7460_captions.vtt", parse_vtt)
        )
    )


# --- the probe's SRT reader ----------------------------------------------


@pytest.mark.parametrize("directory,name,parser", ROLLUP_FIXTURES + NON_ROLLUP_FIXTURES)
def test_parse_stored_srt_round_trips_a_real_transcript_export(directory, name, parser):
    """`GET /m/{slug}/transcript.srt` -> `parse_stored_srt()` must give back
    exactly the segments the Archive holds, or every number this script
    reports is measured against something other than the real page."""
    stored = stored_segments(directory, name, parser)
    assert stored, "fixture produced no cues"

    restored = through_the_probe(stored)

    assert len(restored) == len(stored)
    for original, back in zip(stored, restored):
        assert back["text"] == original["text"].strip()
        assert back["start"] == pytest.approx(original["start"], abs=0.001)
        assert back["end"] == pytest.approx(original["end"], abs=0.001)


def test_parse_stored_srt_survives_a_truncated_or_malformed_block():
    """A probe's whole job is to survive whatever a real row contains, so a
    block with no timing line is skipped rather than raised on."""
    body = (
        "1\n00:00:01,000 --> 00:00:02,000\nreal cue\n\n"
        "2\nthis block has no timing line at all\n\n"
        "3\n00:00:03,000 --> 00:00:04,000\nanother real cue\n\n"
        "4\n00:00:05,000 -->"  # truncated mid-write
    )
    segments = parse_stored_srt(body)
    assert [s["text"] for s in segments] == ["real cue", "another real cue"]


def test_parse_stored_srt_keeps_a_multi_line_segment_intact():
    """Two of WO-34's four real shapes put two caption lines in one cue, and
    the line -- not the cue -- is the detector's unit, so a multi-line
    segment must survive the export round trip with its newline."""
    body = "1\n00:00:01,000 --> 00:00:02,000\nfirst line\nsecond line\n"
    assert parse_stored_srt(body)[0]["text"] == "first line\nsecond line"


# --- detection, against the real files --------------------------------------


@pytest.mark.parametrize("directory,name,parser", ROLLUP_FIXTURES)
def test_real_rollup_tracks_are_flagged_through_the_probe(directory, name, parser):
    stored = stored_segments(directory, name, parser)
    assert looks_affected(through_the_probe(stored)) is True
    ratio, pairs = rollup_ratio(through_the_probe(stored))
    # WO-34 measured >= 0.401 on every real roll-up track it fixed; the
    # 0.20 gate has margin on both sides of a real gap.
    assert ratio >= 0.20, f"{name} scored {ratio:.3f}, under the detector's gate"
    assert pairs > 0


@pytest.mark.parametrize("directory,name,parser", NON_ROLLUP_FIXTURES)
def test_real_non_rollup_tracks_are_never_flagged(directory, name, parser):
    """The one outcome that would do damage. Jacksonville clip 7447 is the
    control CLAUDE.md names: same platform as Tacoma, ordinary captions."""
    stored = stored_segments(directory, name, parser)
    restored = through_the_probe(stored)
    ratio, _pairs = rollup_ratio(restored)
    assert looks_affected(restored) is False, f"{name} was flagged at {ratio:.3f}"
    assert ratio < 0.20


def test_preview_matches_what_the_production_parser_would_produce():
    """The dry run's "after" is `dedupe_rollup_cues()` over the *stored*
    segments. That is only honest if it reproduces what the real adapter
    path produces from the same file -- which it does, because an affected
    page's stored segments are the raw cues."""
    from app.utils.vtt_parser import parse_captions_by_extension

    content = load_fixture("granicus", "tacoma_clip7460_captions.vtt")
    production, _text = parse_captions_by_extension(
        "https://cityoftacoma.granicus.com/videos/7460/captions.vtt", content
    )
    preview = preview_dedupe(through_the_probe(parse_vtt(content)))

    assert [s["text"] for s in preview] == [s["text"] for s in production]


def test_tacoma_preview_reproduces_wo34s_own_measurement():
    """Not a made-up threshold: WO-34 measured the full live Tacoma file at
    21,240 cues -> 1,168 segments, 859K -> 100K characters. The same ratio
    has to come out of this script's preview path, since the whole dry-run
    report is built on it. (The fixture is a trimmed excerpt, so the counts
    differ -- the shape of the reduction is what's asserted.)"""
    stored = through_the_probe(
        stored_segments("granicus", "tacoma_clip7460_captions.vtt", parse_vtt)
    )
    after = preview_dedupe(stored)
    assert len(after) < len(stored) / 5
    assert total_chars(after) < total_chars(stored) / 2


def test_looks_affected_is_false_for_an_empty_transcript():
    assert looks_affected([]) is False


def test_the_three_largest_wo34_shapes_land_in_the_matched_band():
    """WO-34 measured every real roll-up track at >= 0.401 on the *full*
    files. These fixtures are trimmed excerpts, and the ratio is
    excerpt-length-sensitive -- Essex County's 18-cue excerpt scores 0.294
    against 0.401 for the real 11,627-cue file, and Fountain Valley's scores
    0.062 against 0.048 -- so only the three excerpts long enough to
    reproduce the real reading are asserted here. Every one of the four is
    still asserted to be *flagged* above, which is what actually matters."""
    for directory, name, parser in (
        ("granicus", "tacoma_clip7460_captions.vtt", parse_vtt),
        ("civicclerk", "antiochca_event18_captions.srt", parse_srt),
        ("youtube", "phila_education_5LZqoNDRMYk_captions.vtt", parse_vtt),
    ):
        ratio, _pairs = rollup_ratio(
            through_the_probe(stored_segments(directory, name, parser))
        )
        assert confidence_band(ratio) == "matched", f"{name} scored {ratio:.3f}"


def test_the_borderline_band_is_reporting_only_not_a_second_gate():
    """Both bands are real findings. The first production sweep (2026-08-22)
    found genuine catches at 0.20-0.25 -- e.g. a YouTube auto-caption track
    re-emitting each speaker-change line as both '>>' and '»' -- so this
    split must never quietly become an apply threshold."""
    assert confidence_band(0.25) == "borderline"
    assert confidence_band(CONFIDENT_ROLLUP_RATIO) == "matched"
    assert build_parser().parse_args([]).min_ratio == DETECTOR_GATE_RATIO


# --- candidate selection ---------------------------------------------------


def _page(slug, platform="granicus", created_at="2026-01-01T00:00:00+00:00", url=None):
    return {
        "slug": slug,
        "title": slug,
        "platform": platform,
        "source_url_normalized": url
        or f"https://example.granicus.com/player/clip/{slug}",
        "created_at": created_at,
    }


def test_only_the_four_rollup_platforms_are_candidates():
    """WO-34 confirmed exactly these four serve roll-up captions. A Swagit or
    Cablecast page is not a candidate, which is most of what keeps this from
    being a corpus-wide sweep."""
    pages = [_page(p, platform=p) for p in ("granicus", "swagit", "escribe", "iqm2")]
    assert {p["slug"] for p in select_candidates(pages)} == {"granicus", "escribe"}
    assert ROLLUP_PLATFORMS == {"granicus", "civicclerk", "escribe", "youtube"}


def test_pages_archived_after_wo34_shipped_are_excluded():
    pages = [
        _page("before", created_at="2026-08-20T23:59:00+00:00"),
        _page("after", created_at="2026-08-21T00:00:01+00:00"),
    ]
    assert [p["slug"] for p in select_candidates(pages)] == ["before"]


def test_a_page_with_no_created_at_is_kept_not_dropped():
    """The date bound exists to remove provably-unaffected pages. An unknown
    ingest date is not proof of anything, and an Archive build older than
    this PR doesn't return the field at all -- so it must never silently
    exclude a page."""
    explicit_null = [_page("null-date", created_at=None)]
    assert [p["slug"] for p in select_candidates(explicit_null)] == ["null-date"]

    absent = [_page("absent-date")]
    del absent[0]["created_at"]
    assert [p["slug"] for p in select_candidates(absent)] == ["absent-date"]


def test_an_explicit_slug_short_circuits_both_bounds():
    """`--slug` is a human naming a page on purpose, including one on a
    platform that never serves roll-up or archived after the cutoff."""
    pages = [
        _page("swagit-page", platform="swagit", created_at="2026-09-01T00:00:00+00:00")
    ]
    picked = select_candidates(pages, slugs={"swagit-page"})
    assert [p["slug"] for p in picked] == ["swagit-page"]


def test_host_filter_narrows_further():
    pages = [
        _page("a", url="https://cityoftacoma.granicus.com/player/clip/7460"),
        _page("b", url="https://jaxcityc.granicus.com/player/clip/7447"),
    ]
    picked = select_candidates(pages, host_contains="cityoftacoma")
    assert [p["slug"] for p in picked] == ["a"]


def test_candidates_come_back_newest_first():
    """list_all_page_urls() returns oldest-first; a run cut short by --limit
    should fix the pages most likely to be read next."""
    pages = [_page("oldest"), _page("newest")]
    assert [p["slug"] for p in select_candidates(pages)] == ["newest", "oldest"]


def test_source_host_never_raises_on_a_malformed_url():
    assert source_host(None) == "(none)"
    assert source_host("") == "(none)"
    assert source_host("not a url") == "(unparseable)"


# --- the safety gates ------------------------------------------------------


def _segments(text: str) -> list[dict]:
    return [{"start": 0.0, "end": 1.0, "text": text}]


def test_verdict_accepts_a_real_dedupe():
    ok, reason = rewrite_verdict(
        stored_chars=859278,
        fresh=_segments("x" * 100246),
        min_retained=0.05,
    )
    assert ok is True
    # Tacoma's real retained ratio, the tightest real case known.
    assert "0.117" in reason


def test_verdict_refuses_an_empty_resolve():
    ok, reason = rewrite_verdict(stored_chars=1000, fresh=[], min_retained=0.05)
    assert ok is False
    assert "no segments" in reason


def test_verdict_refuses_when_the_fresh_resolve_is_still_rollup():
    """If today's parser did not fix this track, the stored transcript is no
    worse than what we'd replace it with -- so leave it alone."""
    fresh = through_the_probe(
        stored_segments("granicus", "tacoma_clip7460_captions.vtt", parse_vtt)
    )
    ok, reason = rewrite_verdict(
        stored_chars=total_chars(fresh) * 10, fresh=fresh, min_retained=0.05
    )
    assert ok is False
    assert "still scores as roll-up" in reason


def test_verdict_refuses_a_transcript_that_did_not_shrink():
    ok, reason = rewrite_verdict(
        stored_chars=1000, fresh=_segments("y" * 1000), min_retained=0.05
    )
    assert ok is False
    assert "only ever removes text" in reason


def test_verdict_refuses_an_implausibly_small_resolve():
    """The truncated/half-fetched-source tripwire. 0.05 sits below the
    tightest real case (Tacoma's 0.117) on purpose."""
    ok, reason = rewrite_verdict(
        stored_chars=100000, fresh=_segments("z" * 100), min_retained=0.05
    )
    assert ok is False
    assert "--min-retained" in reason


def test_verdict_refuses_when_the_stored_side_had_no_characters():
    ok, reason = rewrite_verdict(
        stored_chars=0, fresh=_segments("real text"), min_retained=0.05
    )
    assert ok is False
    assert "no characters" in reason


# --- resume state ----------------------------------------------------------


def test_state_round_trips(tmp_path):
    path = tmp_path / "state.json"
    state = State(path, "https://archive.example")
    state.record_applied("slug-a", {"version_id": 7, "detail": "done"})
    state.record_failure("slug-b", "resolve failed")
    state.save()

    reloaded = State.load(path, "https://archive.example")
    assert reloaded.done("slug-a") and reloaded.done("slug-b")
    assert reloaded.applied["slug-a"]["version_id"] == 7
    assert reloaded.failed["slug-b"]["attempts"] == 1


def test_state_from_a_different_archive_is_ignored(tmp_path):
    """Guard, not paranoia: slugs from a staging Archive would silently mark
    real production pages as already done."""
    path = tmp_path / "state.json"
    state = State(path, "https://staging.example")
    state.record_applied("slug-a", {})
    state.save()

    assert State.load(path, "https://production.example").applied == {}


def test_state_ignores_an_unreadable_file(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{ not json")
    assert State.load(path, "https://archive.example").applied == {}


def test_a_success_clears_an_earlier_failure(tmp_path):
    state = State(tmp_path / "s.json", "https://archive.example")
    state.record_failure("slug", "transient")
    state.record_applied("slug", {"version_id": 1})
    assert "slug" not in state.failed


# --- CLI -------------------------------------------------------------------


def test_dry_run_is_the_default():
    args = build_parser().parse_args([])
    assert args.apply is False
    assert args.created_before == WO34_SHIP_DATE
    assert args.min_retained == 0.05
    # The default rewrites everything the detector flagged -- the confidence
    # split is a reporting aid, not a second gate.
    assert args.min_ratio == DETECTOR_GATE_RATIO


def test_apply_is_opt_in_and_slug_is_repeatable():
    args = build_parser().parse_args(["--apply", "--slug", "a", "--slug", "b"])
    assert args.apply is True
    assert args.slug == ["a", "b"]


# --- the write path, against a fake Archive --------------------------------


class FakeResolved:
    """Stands in for a ResolvedMeeting: only `.segments` (pydantic-ish) and
    `.model_dump()` are used by rewrite_page()."""

    def __init__(self, segments):
        self.segments = [_FakeSegment(s) for s in segments]

    def model_dump(self):
        return {
            "platform": "granicus",
            "source_url": "https://cityoftacoma.granicus.com/player/clip/7460",
            "segments": [s.model_dump() for s in self.segments],
        }


class _FakeSegment:
    def __init__(self, data):
        self._data = data

    def model_dump(self):
        return dict(self._data)


class FakeArchive:
    """Records the calls rewrite_page() makes, in order, and serves the
    post-push verification read."""

    def __init__(self, after_push):
        self.calls = []
        self.after_push = after_push
        self.next_version_id = 42


@pytest.fixture
def fake_archive(monkeypatch):
    import dedupe_rollup_transcripts as script

    archive = FakeArchive(after_push=[])

    async def _push(session, payload, url):
        archive.calls.append(("ingest", url, len(payload.get("segments", []))))
        return {"slug": "the-slug", "version_id": archive.next_version_id}

    async def _promote(session, slug, version_id):
        archive.calls.append(("promote", slug, version_id))
        return {"ok": True}

    async def _fetch(session, slug):
        archive.calls.append(("verify", slug, None))
        return archive.after_push

    monkeypatch.setattr(script, "push_ingest", _push)
    monkeypatch.setattr(script, "promote_version", _promote)
    monkeypatch.setattr(script, "fetch_stored_transcript", _fetch)
    return archive


def _patch_resolver(monkeypatch, resolved):
    """rewrite_page() imports get_finder/detect_platform inside the function
    (deliberately -- see its comment), so the patch has to land on
    app.platforms.base itself."""
    import app.platforms.base as base

    class _Finder:
        async def resolve(self, url):
            if isinstance(resolved, Exception):
                raise resolved
            return resolved

    monkeypatch.setattr(base, "detect_platform", lambda url: "granicus")
    monkeypatch.setattr(base, "get_finder", lambda platform: _Finder())


def _finding(stored_chars=859278):
    return {
        "slug": "the-slug",
        "source_url": "https://cityoftacoma.granicus.com/player/clip/7460",
        "stored_chars": stored_chars,
        "stored_segments": 21240,
        "before_sample": [],
    }


async def test_rewrite_pushes_then_promotes_then_verifies(monkeypatch, fake_archive):
    """Ordering is the whole point. `crud._is_real_improvement()` will not
    auto-promote a fresh push over a default that already has segments and a
    language -- which is exactly a roll-up page -- so an ingest without a
    promote would file the fixed transcript as a version nobody ever sees."""
    clean = deduped_tacoma()
    fake_archive.after_push = clean
    _patch_resolver(monkeypatch, FakeResolved(clean))

    result = await rewrite_page(
        None, _finding(stored_chars=total_chars(clean) * 8), min_retained=0.05
    )

    assert result["ok"] is True
    assert [c[0] for c in fake_archive.calls] == ["ingest", "promote", "verify"]
    assert fake_archive.calls[1][1:] == ("the-slug", 42)


async def test_a_refused_rewrite_never_touches_the_archive(monkeypatch, fake_archive):
    """The gate runs before any write, so a page the resolve came back wrong
    for is left exactly as it is -- no ingest, no promote."""
    _patch_resolver(monkeypatch, FakeResolved([]))

    result = await rewrite_page(None, _finding(), min_retained=0.05)

    assert result["ok"] is False and result["refused"] is True
    assert fake_archive.calls == []


async def test_a_still_rollup_resolve_is_refused(monkeypatch, fake_archive):
    """If the fresh resolve is still duplicated, replacing the stored one
    buys nothing and risks a regression -- refuse and report."""
    still_broken = through_the_probe(
        stored_segments("granicus", "tacoma_clip7460_captions.vtt", parse_vtt)
    )
    _patch_resolver(monkeypatch, FakeResolved(still_broken))

    result = await rewrite_page(
        None, _finding(stored_chars=total_chars(still_broken) * 10), min_retained=0.05
    )

    assert result["refused"] is True
    assert "still scores as roll-up" in result["detail"]
    assert fake_archive.calls == []


async def test_a_page_that_still_looks_rollup_after_the_push_is_reported(
    monkeypatch, fake_archive
):
    """The last gate: the page's own export is re-read after the promote."""
    clean = deduped_tacoma()
    _patch_resolver(monkeypatch, FakeResolved(clean))
    fake_archive.after_push = through_the_probe(
        stored_segments("granicus", "tacoma_clip7460_captions.vtt", parse_vtt)
    )

    result = await rewrite_page(
        None, _finding(stored_chars=total_chars(clean) * 8), min_retained=0.05
    )

    assert result["ok"] is False
    assert "still scores as roll-up" in result["detail"]
    assert [c[0] for c in fake_archive.calls] == ["ingest", "promote", "verify"]


async def test_a_failed_resolve_is_a_page_level_outcome_not_a_crash(
    monkeypatch, fake_archive
):
    """These are real government websites; a dead source is routine and must
    not stop the sweep."""
    _patch_resolver(monkeypatch, RuntimeError("HTTP 503 from the source"))

    result = await rewrite_page(None, _finding(), min_retained=0.05)

    assert result["ok"] is False
    assert "resolve failed" in result["detail"]
    assert fake_archive.calls == []


async def test_rewrite_registers_the_adapters_before_asking_for_a_finder(
    monkeypatch, fake_archive
):
    """Real bug, caught during this script's own live verification: `base.py`'s
    finder registry is a module-level dict that stays *empty* until
    `register_all_finders()` runs, and the only thing that normally calls it is
    `app/main.py` at import time. This script deliberately doesn't import
    `app.main` (it needs the ingest response's `version_id`, which
    `archive_client.push()` throws away), so without its own explicit call
    every single page failed with "No asset finder for platform 'granicus'".

    Tested by emptying the registry first -- if `rewrite_page()` ever stops
    registering, it can only come back "unsupported platform"."""
    import app.platforms.base as base
    from app.platforms.granicus import GranicusAssetFinder

    clean = deduped_tacoma()

    async def _resolve(self, url):
        return FakeResolved(clean)

    monkeypatch.setattr(GranicusAssetFinder, "resolve", _resolve)
    monkeypatch.setattr(base, "_REGISTRY", {})
    fake_archive.after_push = clean

    result = await rewrite_page(
        None, _finding(stored_chars=total_chars(clean) * 8), min_retained=0.05
    )

    assert "unsupported platform" not in result["detail"]
    assert result["ok"] is True


async def test_a_finding_with_no_source_url_is_skipped(fake_archive):
    finding = _finding()
    finding["source_url"] = None
    result = await rewrite_page(None, finding, min_retained=0.05)
    assert result["ok"] is False
    assert "no stored source URL" in result["detail"]


# --- the report file is the artifact a human reviews -----------------------


def test_report_findings_carry_everything_apply_needs(tmp_path):
    """`--apply --from-report` reads this file back, so a finding has to be
    self-sufficient: the URL to re-resolve and the stored character count
    the size gate compares against."""
    finding = _finding()
    report = {"base_url": "https://archive.example", "findings": [finding]}
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report))

    loaded = json.loads(path.read_text())["findings"][0]
    assert loaded["source_url"] and loaded["stored_chars"] and loaded["slug"]
