"""Tests for scripts/repoint_page.py -- the general version of the
Santa Barbara/Pittsburg repoint method documented in BACKLOG_DONE.md's
"Four archived pages pointed at agenda systems with no video" entry, now
used for Sarasota County, FL's `egenda.scgov.net` -> Granicus repoint
(WO-89, 2026-08-31).

The network calls (resolving `new_url` through the real adapter registry,
POSTing to the real Archive) are stubbed the same way
test_dedupe_rollup_transcripts.py stubs its own script's network
functions -- this only exercises `repoint()`'s own logic: that the OLD
url (not the new one) is what gets normalized and sent as
`input_url_normalized`, and that --dry-run never reaches the network at
all.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import repoint_page as script  # noqa: E402

OLD_URL = (
    "https://egenda.scgov.net/OnBaseAgendaOnline/Meetings/ViewMeeting?doctype=1&id=1968"
)
NEW_URL = "https://sarasotacounty.granicus.com/player/clip/6960?view_id=52"


def _resolved(**overrides):
    defaults = dict(
        platform="granicus",
        title="County Commission - 2026 — BCC-Regular",
        date="2026-08-25",
        jurisdiction="Sarasota County, FL",
        video_url="https://archive-stream.granicus.com/.../playlist.m3u8",
        segments=[],
        agenda_items=[],
        agenda_link=None,
        transcript_warnings=[],
        video_warnings=[],
    )
    defaults.update(overrides)
    ns = SimpleNamespace(**defaults)
    ns.model_dump = lambda: dict(defaults)
    return ns


def _patch_resolver(monkeypatch, resolved):
    class _Finder:
        async def resolve(self, url):
            if isinstance(resolved, Exception):
                raise resolved
            return resolved

    monkeypatch.setattr(script, "detect_platform", lambda url: "granicus")
    monkeypatch.setattr(script, "get_finder", lambda platform: _Finder())


async def test_dry_run_never_calls_ingest(monkeypatch):
    _patch_resolver(monkeypatch, _resolved())

    async def _boom(session, payload, input_url_normalized):  # pragma: no cover
        raise AssertionError("dry-run must not push to the Archive")

    monkeypatch.setattr(script, "_ingest", _boom)

    result = await script.repoint(OLD_URL, NEW_URL, dry_run=True)

    assert result["status"] == "dry-run"
    assert (
        result["video_url"] == "https://archive-stream.granicus.com/.../playlist.m3u8"
    )


async def test_live_run_sends_the_old_url_normalized_not_the_new_one(monkeypatch):
    # The entire point of a repoint: the resolved payload comes from
    # NEW_URL, but the Archive is told to attach it to OLD_URL's
    # normalized form, so crud._find_existing_page() updates the existing
    # (already-archived, video-less) page in place instead of creating a
    # second one.
    _patch_resolver(monkeypatch, _resolved())
    seen = {}

    async def _fake_ingest(session, payload, input_url_normalized):
        seen["input_url_normalized"] = input_url_normalized
        seen["payload"] = payload
        return {"slug": "sarasota-county-fl-2026-08-25-bcc-regular", "created": False}

    monkeypatch.setattr(script, "_ingest", _fake_ingest)

    result = await script.repoint(OLD_URL, NEW_URL, dry_run=False)

    assert result["status"] == "repointed"
    assert result["created"] is False
    assert seen["input_url_normalized"] == script.normalize_url(OLD_URL)
    assert seen["input_url_normalized"] != script.normalize_url(NEW_URL)
    assert seen["payload"]["platform"] == "granicus"


async def test_a_calendar_page_new_url_is_refused(monkeypatch):
    from app.platforms.base import CalendarPageError

    _patch_resolver(
        monkeypatch, CalendarPageError(message="multiple meetings", candidates=[])
    )

    result = await script.repoint(OLD_URL, NEW_URL, dry_run=True)

    assert result["status"] == "failed"
    assert "calendar page" in result["detail"]


async def test_a_resolve_with_nothing_worth_ingesting_is_skipped(monkeypatch):
    # Real, narrower version of Sarasota's own Aug 25 meeting: video
    # exists, but no segments/agenda/agenda_link either -- still worth
    # ingesting because of the video alone, so this only covers the case
    # where even that is missing.
    _patch_resolver(
        monkeypatch,
        _resolved(video_url=None, segments=[], agenda_items=[], agenda_link=None),
    )

    result = await script.repoint(OLD_URL, NEW_URL, dry_run=True)

    assert result["status"] == "skipped"


async def test_a_video_only_result_is_still_worth_repointing(monkeypatch):
    # The real Sarasota case (WO-89): clip 6960's own captions.vtt is
    # genuinely blank (confirmed live 2026-08-31 -- a very recent
    # meeting, likely not yet processed by Granicus's own captioning),
    # but the real video itself is exactly what this page was missing.
    _patch_resolver(
        monkeypatch,
        _resolved(
            segments=[],
            agenda_items=[],
            agenda_link=None,
            transcript_warnings=[
                "Caption file was blank, so we don't have a transcript for this meeting yet — you can request one be generated from the audio below."
            ],
        ),
    )

    result = await script.repoint(OLD_URL, NEW_URL, dry_run=True)

    assert result["status"] == "dry-run"
    assert result["video_url"]
