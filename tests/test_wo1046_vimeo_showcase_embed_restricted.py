"""WO-1046: Vimeo showcases embedded on a government page, and the case
where the video behind one is domain-restricted by its owner.

Real case (Ryan, 2026-09-24): Suffolk County NY's Legislature
(`scnylegislature.us`) reaches `.../1737/Video-Broadcast-and-Gallery`,
which embeds one Vimeo LIVE EVENT (`vimeo.com/event/4795861/embed`,
single-quoted `src`) and 14 real `vimeo.com/showcase/{id}/embed`
meeting archives. Confirmed live: the real meetings behind these
showcases are domain-restricted to `scnylegislature.us` -- Vimeo's own
oEmbed response 403s/`domain_status_code`-blocks anywhere else. See
`app/platforms/vimeo.py`'s `EMBED_DOMAIN_RESTRICTED_WARNING`.

`tests/fixtures/vimeo/suffolk_video_broadcast.html` is a real, unmodified
capture of that exact page taken live 2026-09-24.

Three things this WO fixed, each covered below:

1. Scan (`app/platforms/meeting_finder/scan.py`) must find every one of
   the 14 real showcases as its own media candidate, and must never treat
   the live-event embed as one (`test_scan_finds_every_showcase...`).
2. Resolve (`resolve.py`) must report a confirmed-but-restricted meeting
   as its own outcome (`embed-restricted`), not silently drop it or fold
   it into the generic "kept despite" bucket
   (`test_resolve_reports_embed_restricted...`).
3. The runner's own dedup (`_meeting_key`/`state.tried_meeting_keys`)
   must stop a page's own vimeo links from being re-walked as a "hop"
   after Scan already tried them with real page context -- the real bug
   this closes: a hop-based re-walk with no page context produced a
   worse duplicate "kept despite" entry (`source_url` pointing at the
   bare Vimeo showcase link instead of the real government page) that
   won the runner's own "first found wins" tie-break over Scan's better
   one (`test_runner_skips_a_hop_scan_already_tried`).
"""

from __future__ import annotations

import pytest

from app.platforms.meeting_finder import runner
from app.platforms.meeting_finder.fetch import FetchResult
from app.platforms.meeting_finder.hop import HopLink
from app.platforms.meeting_finder.identify import IdentifyResult
from app.platforms.meeting_finder.listing import _candidate_from_dict
from app.platforms.meeting_finder.models import (
    OUTCOME_EMBED_RESTRICTED,
    Candidate,
    FinderInput,
    ResolveResult,
)
from app.platforms.meeting_finder.resolve import _resolve_candidates_with_meeting
from app.platforms.meeting_finder.scan import _media_candidates_for_page
from app.platforms.models import ResolvedMeeting
from app.platforms.vimeo import EMBED_DOMAIN_RESTRICTED_WARNING
from conftest import load_fixture


def _finder_input(url: str, **overrides) -> FinderInput:
    fields = dict(url=url, gov_id=None, mode="pin", entry="resolve")
    fields.update(overrides)
    return FinderInput(**fields)


def test_scan_finds_every_showcase_and_skips_the_live_event():
    html = load_fixture("vimeo", "suffolk_video_broadcast.html")
    page_url = "https://www.scnylegislature.us/1737/Video-Broadcast-and-Gallery"

    media = _media_candidates_for_page(
        html, page_url, links_only=False, lister="media_scan"
    )

    urls = [c.url for c in media]
    # All 14 real showcase archives, confirmed live 2026-09-24.
    assert len(urls) == 14
    assert all(u.startswith("https://vimeo.com/showcase/") for u in urls)
    assert all(u.endswith("/embed") for u in urls)
    # The live event is never a media candidate (a different id space --
    # `detect_platform()` doesn't recognize `/event/{id}` at all).
    assert not any("vimeo.com/event/" in u for u in urls)
    # Every candidate carries the real government page as its source, not
    # a bare Vimeo URL.
    assert all(c.source_url == page_url for c in media)
    assert all(c.platform == "vimeo" for c in media)


@pytest.mark.asyncio
async def test_resolve_reports_embed_restricted_kept_despite(monkeypatch):
    """A candidate that resolves to a confirmed real meeting (a dated,
    titled row a Vimeo showcase's own CalendarPageError handed back) but
    that Vimeo's oEmbed refuses to serve outside the government's domain
    must come back as OUTCOME_EMBED_RESTRICTED, not silently dropped and
    not folded into the generic OUTCOME_VIDEO_LOW_CONFIDENCE bucket."""

    async def fake_resolve_via_platform(url, *, allow_youtube=True):
        assert url == "https://vimeo.com/1225746580/979e0c1d46"
        return ResolvedMeeting(
            platform="vimeo",
            source_url=url,
            external_id="vimeo:1225746580",
            video_warnings=[EMBED_DOMAIN_RESTRICTED_WARNING],
        )

    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve.resolve_via_platform",
        fake_resolve_via_platform,
    )

    candidates = [
        Candidate(
            url="https://vimeo.com/1225746580/979e0c1d46",
            title="09/09/2026 General Meeting of the Legislature",
            date="2026-09-09",
            source_phase="list",
            lister="adapter_list",
            source_url="https://www.scnylegislature.us/1737/Video-Broadcast-and-Gallery",
        )
    ]

    result, meeting = await _resolve_candidates_with_meeting(
        candidates, _finder_input(candidates[0].url), max_tries=6
    )

    assert result.outcome == OUTCOME_EMBED_RESTRICTED
    assert result.video_url is None
    assert result.tier is None
    assert result.candidate is not None
    assert (
        result.candidate.source_url
        == "https://www.scnylegislature.us/1737/Video-Broadcast-and-Gallery"
    )
    assert result.low_confidence_rank is not None
    assert result.low_confidence_rank < 0  # ranked ahead of the 0-3 generic ranks


@pytest.mark.asyncio
async def test_resolve_prefers_a_clean_find_over_an_embed_restricted_one(monkeypatch):
    """Ryan's "date orders, never eliminates" rule applies here too: an
    embed-restricted candidate must not stop Resolve from trying (and
    preferring) a later, cleanly-playable one."""

    async def fake_resolve_via_platform(url, *, allow_youtube=True):
        if url == "https://vimeo.com/1225746580/979e0c1d46":
            return ResolvedMeeting(
                platform="vimeo",
                source_url=url,
                video_warnings=[EMBED_DOMAIN_RESTRICTED_WARNING],
            )
        return ResolvedMeeting(
            platform="vimeo",
            source_url=url,
            video_url="https://player.vimeo.com/video/1224983103",
            segments=[],
        )

    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve.resolve_via_platform",
        fake_resolve_via_platform,
    )

    async def fake_confirm_not_audio_only(video_url):
        return True

    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve._confirm_not_audio_only",
        fake_confirm_not_audio_only,
    )

    async def fake_probe_queue_entry(*args, **kwargs):
        from app.platforms import queue_probe

        return queue_probe.ProbeResult(
            url="https://player.vimeo.com/video/1224983103",
            platform="vimeo",
            probe_method="ffprobe",
            duration_seconds=1800,
            date="2026-09-03",
            size_bytes=None,
            verdict="accept",
            reason="",
            probe_seconds=1.0,
        )

    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve.queue_probe.probe_queue_entry",
        fake_probe_queue_entry,
    )
    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve.queue_probe.is_plausible",
        lambda probe: True,
    )

    candidates = [
        Candidate(
            url="https://vimeo.com/1225746580/979e0c1d46",
            title="09/09/2026 General Meeting of the Legislature",
            date="2026-09-09",
        ),
        Candidate(
            url="https://vimeo.com/1224983103/f9bea0351f",
            title="09/03/2026 Special Meeting Of the Legislature",
            date="2026-09-03",
        ),
    ]

    result, _meeting = await _resolve_candidates_with_meeting(
        candidates, _finder_input(candidates[0].url), max_tries=6
    )

    assert result.outcome is None
    assert result.video_url == "https://player.vimeo.com/video/1224983103"


def test_listing_candidate_prefers_page_url_for_vimeo_over_account_url():
    """WO-1046: `account_url` for a Vimeo showcase found via Identify's
    rule-1 URL-host match IS the showcase link itself (`vimeo.com/
    showcase/{id}/embed`) -- not a page worth pointing a reader at. When
    `page_url` (the real government page Identify found it embedded on)
    is available, prefer it."""
    row = {"url": "https://vimeo.com/1225746580/979e0c1d46", "title": "t", "date": "d"}

    cand = _candidate_from_dict(
        row,
        platform="vimeo",
        account_url="https://vimeo.com/showcase/12045632/embed",
        lister="adapter_list",
        page_url="https://www.scnylegislature.us/1737/Video-Broadcast-and-Gallery",
    )
    assert (
        cand.source_url
        == "https://www.scnylegislature.us/1737/Video-Broadcast-and-Gallery"
    )

    # No page_url given (existing callers, every other platform): behaves
    # exactly as before, falling back to account_url.
    cand_no_page = _candidate_from_dict(
        row,
        platform="vimeo",
        account_url="https://vimeo.com/showcase/12045632/embed",
        lister="adapter_list",
    )
    assert cand_no_page.source_url == "https://vimeo.com/showcase/12045632/embed"

    # Only special-cased for vimeo -- a Legistar/Tampa/Wistia/Municode
    # account_url IS already a real, useful page.
    cand_legistar = _candidate_from_dict(
        row,
        platform="legistar",
        account_url="https://x.legistar.com/Calendar.aspx",
        lister="adapter_list",
        page_url="https://x.gov/meetings",
    )
    assert cand_legistar.source_url == "https://x.legistar.com/Calendar.aspx"


def _page(url: str, *, html: str = "<html></html>") -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        status=200,
        html=html,
        access_mode="plain",
        outcome=None,
        challenge=False,
        wayback_timestamp=None,
        links_only=False,
        elapsed_ms=1,
    )


def _identify_blank(
    url: str, *, platform=None, account_url=None, page=None
) -> IdentifyResult:
    return IdentifyResult(
        input_url=url,
        final_url=url,
        platform=platform,
        account_url=account_url,
        supported=None,
        web_host_hint=None,
        signals=[],
        youtube_leads=[],
        outcome=None,
        guess_queue_row=None,
        page=page if page is not None else _page(url),
    )


@pytest.mark.asyncio
async def test_runner_skips_a_hop_scan_already_tried(monkeypatch):
    """Real bug this closes (Suffolk County NY, conductor review,
    2026-09-24): Scan finds a Vimeo showcase embedded on the CURRENT page
    (real page context, so `source_url` is the real government page) and
    resolves it to `OUTCOME_EMBED_RESTRICTED` -- but the SAME showcase
    link also ranks as a "hop" on the very same page, and the old code
    re-walked it via Identify->List with no page context at all
    (`source_url` falls back to the bare showcase link). Since both
    resolve to the same `_meeting_key`-ranked outcome, the runner's own
    cross-fork tie-break ("first found wins") let the WORSE, second one
    win. The fix: a hop whose `_meeting_key()` Scan's own `_try_resolve()`
    call already registered is skipped, so the SAME account is never
    Identified/Listed a second time with worse context."""
    showcase_url = "https://vimeo.com/showcase/12045632/embed"
    page_url = "https://www.scnylegislature.us/1737/Video-Broadcast-and-Gallery"

    identified = []

    async def fake_identify(url, fetcher, *, platform_hint=None, page=None):
        identified.append(url)
        if url == showcase_url:
            # This must never be called -- Scan already tried this exact
            # link with real page context.
            return _identify_blank(url, platform="vimeo", account_url=showcase_url)
        return _identify_blank(url, page=_page(url))

    async def fake_scan_page(page, fetcher, **kwargs):
        from app.platforms.meeting_finder.scan import ScanResult

        if page.requested_url != page_url:
            return ScanResult()
        return ScanResult(
            media_candidates=[
                Candidate(
                    url=showcase_url,
                    platform="vimeo",
                    source_phase="scan",
                    lister="media_scan",
                    source_url=page_url,
                    has_video_hint=True,
                )
            ]
        )

    def fake_rank_hops(page, **kwargs):
        if page.requested_url != page_url:
            return []
        return [
            HopLink(url=showcase_url, score=50.0, anchor="", reason=""),
        ]

    async def fake_resolve(candidates, finder_input, *, max_tries):
        if candidates and candidates[0].url == showcase_url:
            return (
                ResolveResult(
                    candidate=Candidate(
                        url="https://vimeo.com/1225746580/979e0c1d46",
                        title="09/09/2026 General Meeting of the Legislature",
                        source_url=page_url,
                    ),
                    tier=None,
                    platform="vimeo",
                    video_url=None,
                    has_segments=False,
                    duration_seconds=None,
                    outcome=OUTCOME_EMBED_RESTRICTED,
                    note="kept despite: embed restricted",
                    low_confidence_reason="embed restricted",
                    low_confidence_rank=-1,
                ),
                None,
            )
        return (
            ResolveResult(
                candidate=None,
                tier=None,
                platform=None,
                video_url=None,
                has_segments=False,
                duration_seconds=None,
                outcome="no-meeting-nor-video",
                note="nothing found",
            ),
            None,
        )

    monkeypatch.setattr(runner, "identify", fake_identify)
    monkeypatch.setattr(runner, "scan_page", fake_scan_page)
    monkeypatch.setattr(runner, "rank_hops", fake_rank_hops)
    monkeypatch.setattr(runner, "_resolve_candidates_with_meeting", fake_resolve)

    fi = FinderInput(url=page_url, entry="identify")
    row = await runner.run_one(fi, run_id="wo1046-suffolk-dedup", max_hops=2)

    # The showcase is never Identified a second time as its own hop
    # target -- Scan's own (better) resolve already covered it.
    assert identified.count(showcase_url) == 0
    assert row.outcome == OUTCOME_EMBED_RESTRICTED
    # The real government page, not the bare Vimeo showcase link.
    assert row.meeting_url == page_url
    assert row.meeting_title == "09/09/2026 General Meeting of the Legislature"
