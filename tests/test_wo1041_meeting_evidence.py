"""WO-1041: the "meeting evidence" check for a found video, and its wiring
into Resolve (direct_file/vimeo/"picked by: undated, lister order" finds),
List (a shared Granicus account's several view_ids) and Identify (an
off-site hop's destination).

Built from the real spot-check evidence cited in `app/utils/
video_hand_check.py`'s own WO-1041 section and in `BACKLOG_DONE.md`'s
WO-1041 entry: 10 real direct-file titles (0/10 real meetings unless long
or titled), 12 real Vimeo hand-check verdicts (3/12 real, all 3 with a
meeting/body word or a date), and the real Grass Valley/Nevada City/
Nevada County shared-Granicus-account case. Synthetic titles below reuse
those real shapes (marked per CLAUDE.md's synthetic-test rule) rather than
inventing new ones.
"""

from __future__ import annotations

import pytest

from app.platforms.meeting_finder.models import Candidate, FinderInput
from app.platforms.meeting_finder.resolve import resolve_candidates
from app.platforms.models import ResolvedMeeting
from app.utils.video_hand_check import (
    assess_meeting_evidence,
    contains_date_evidence,
    has_meeting_evidence_word,
    has_non_meeting_sign,
)

# --- assess_meeting_evidence() -------------------------------------------


def test_meeting_word_in_title_is_evidence():
    # Real (talihina.k12.ok.us hand-check case): a title WITH a meeting
    # word is real evidence, contrasted with the real reject just below.
    ev = assess_meeting_evidence("City Council Regular Meeting - 9/22/26")
    assert ev.has_evidence
    assert ev.reason.startswith("meeting_word:")


def test_real_non_meeting_vimeo_title_is_rejected():
    # Real, hand-checked (talihina.k12.ok.us, hc1_result.csv): a Vimeo
    # find whose title is a parent-app tutorial, not a meeting.
    ev = assess_meeting_evidence("ParentSquare Overview for Parents & Guardians")
    assert not ev.has_evidence
    assert ev.non_meeting_sign == "overview"


def test_date_alone_is_evidence():
    ev = assess_meeting_evidence("09/16/2026")
    assert ev.has_evidence
    assert ev.reason == "date"


def test_abbreviation_token_is_evidence():
    ev = assess_meeting_evidence("BOS 09.16.26 Recording")
    assert ev.has_evidence
    assert has_meeting_evidence_word("BOS Recording") == "BOS"


def test_lowercase_abbreviation_is_not_evidence():
    # "cc" in ordinary prose is not the CC abbreviation -- case-sensitive
    # whole-token match only.
    ev = assess_meeting_evidence("cc: the whole department")
    assert not ev.has_evidence


def test_long_direct_file_counts_even_with_bare_filename():
    # WO-1058 (was WO-1041, threshold lowered 45 -> 15 min): direct files
    # >= 15 min count as found even with no title/meeting word at all.
    ev = assess_meeting_evidence(
        "video1516165031.mp4", duration_seconds=50 * 60, is_direct_file=True
    )
    assert ev.has_evidence
    assert ev.reason == "long_direct_file(>=15min)"


def test_direct_file_in_15_to_45_minute_range_now_counts():
    # WO-1058 (Ryan, 2026-09-25): hand-checks found 21 of 28 direct files
    # in the 15-45 min range were real meetings -- the old 45 min floor
    # rejected these outright.
    ev = assess_meeting_evidence(
        "video1516165031.mp4", duration_seconds=20 * 60, is_direct_file=True
    )
    assert ev.has_evidence
    assert ev.reason == "long_direct_file(>=15min)"


def test_short_direct_file_with_no_evidence_is_rejected():
    # WO-1041 spot-check: direct files 0/10 unless long or titled -- a
    # short, bare-filename direct file has nothing to accept on.
    ev = assess_meeting_evidence(
        "IMG_4021.mp4", duration_seconds=5 * 60, is_direct_file=True
    )
    assert not ev.has_evidence


def test_non_meeting_sign_overrides_long_duration():
    # A non-meeting sign always wins, even on a long direct file.
    ev = assess_meeting_evidence(
        "Drone tour of downtown", duration_seconds=60 * 60, is_direct_file=True
    )
    assert not ev.has_evidence
    assert ev.non_meeting_sign == "drone"


def test_budget_in_title_is_evidence_even_without_governing_body_word():
    # WO-1041 brief's Robstown "State of the Budget" case.
    ev = assess_meeting_evidence(
        "State of the Budget", duration_seconds=25 * 60, is_direct_file=True
    )
    assert ev.has_evidence
    assert "budget" in ev.reason


def test_short_presentation_is_a_weak_lead_even_with_a_date():
    ev = assess_meeting_evidence(
        "Budget Presentation 09/16/2026", duration_seconds=4 * 60
    )
    assert not ev.has_evidence
    assert ev.non_meeting_sign == "short_presentation_or_intro"


def test_html5_fallback_text_is_rejected():
    ev = assess_meeting_evidence(
        "Your browser does not support the video tag. autoplay muted loop"
    )
    assert not ev.has_evidence
    assert ev.non_meeting_sign == "html5_fallback_text"


def test_contains_date_evidence_recognizes_recorder_stamp():
    assert contains_date_evidence("REC_260916_1830.mp4")


def test_has_non_meeting_sign_word_boundary():
    # "concert" must not false-positive on an unrelated word containing it.
    assert has_non_meeting_sign("Fall concert at the auditorium") == "concert"
    assert has_non_meeting_sign("City Council Meeting") is None


# --- resolve.py wiring: direct_file / vimeo / "undated, lister order" ----


def _finder_input(url: str, **overrides) -> FinderInput:
    fields = dict(url=url, gov_id=None, mode="pin", entry="resolve")
    fields.update(overrides)
    return FinderInput(**fields)


@pytest.mark.asyncio
async def test_vimeo_find_with_no_evidence_is_demoted_not_a_clean_find(monkeypatch):
    """Real shape (WO-1041 spot-check, ParentSquare/Aumentum-style Vimeo
    finds): a Vimeo tier-3 find whose title carries no meeting word/date is
    kept as a last resort, never a clean tier-3 success."""
    from app.platforms import queue_probe
    from app.utils.video_hand_check import PASS, GateVerdict

    meeting = ResolvedMeeting(
        platform="vimeo",
        source_url="https://vimeo.com/362598038",
        title="ParentSquare Overview for Parents & Guardians",
        video_url="https://player.vimeo.com/video/362598038",
    )

    async def _fake_resolve_via_platform(url, *, allow_youtube=True):
        return meeting

    async def _fake_probe(*args, **kwargs):
        return queue_probe.ProbeResult(
            url=meeting.source_url,
            platform="vimeo",
            probe_method="ffprobe",
            duration_seconds=200.0,
            date=None,
            size_bytes=None,
            verdict="accept",
            reason="",
            probe_seconds=0.1,
        )

    async def _audio_ok(url):
        return True

    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve.resolve_via_platform",
        _fake_resolve_via_platform,
    )
    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve.assess_video_candidate",
        lambda **kwargs: GateVerdict(PASS, "ok"),
    )
    monkeypatch.setattr(queue_probe, "probe_queue_entry", _fake_probe)
    monkeypatch.setattr(queue_probe, "is_plausible", lambda probe: True)
    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve._confirm_not_audio_only", _audio_ok
    )

    candidates = [Candidate(url=meeting.source_url, date=None, title=meeting.title)]
    result = await resolve_candidates(candidates, _finder_input(meeting.source_url))

    from app.platforms.meeting_finder.models import OUTCOME_VIDEO_LOW_CONFIDENCE

    assert result.outcome == OUTCOME_VIDEO_LOW_CONFIDENCE
    assert "no meeting evidence" in result.note


@pytest.mark.asyncio
async def test_vimeo_find_with_meeting_word_is_a_clean_find(monkeypatch):
    """Contrast case: a real meeting-shaped Vimeo title still resolves
    cleanly (WO-1041 spot-check: all 3/12 real Vimeo finds had a meeting
    word or a date)."""
    from app.platforms import queue_probe
    from app.utils.video_hand_check import PASS, GateVerdict

    meeting = ResolvedMeeting(
        platform="vimeo",
        source_url="https://vimeo.com/1183202055",
        title="Central Bucks School Board Regular Meeting",
        video_url="https://player.vimeo.com/video/1183202055",
    )

    async def _fake_resolve_via_platform(url, *, allow_youtube=True):
        return meeting

    async def _fake_probe(*args, **kwargs):
        return queue_probe.ProbeResult(
            url=meeting.source_url,
            platform="vimeo",
            probe_method="ffprobe",
            duration_seconds=1100.0,
            date=None,
            size_bytes=None,
            verdict="accept",
            reason="",
            probe_seconds=0.1,
        )

    async def _audio_ok(url):
        return True

    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve.resolve_via_platform",
        _fake_resolve_via_platform,
    )
    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve.assess_video_candidate",
        lambda **kwargs: GateVerdict(PASS, "ok"),
    )
    monkeypatch.setattr(queue_probe, "probe_queue_entry", _fake_probe)
    monkeypatch.setattr(queue_probe, "is_plausible", lambda probe: True)
    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve._confirm_not_audio_only", _audio_ok
    )

    candidates = [Candidate(url=meeting.source_url, date=None, title=meeting.title)]
    result = await resolve_candidates(candidates, _finder_input(meeting.source_url))

    assert result.outcome is None
    assert result.tier == 3
    assert result.video_url == meeting.video_url


@pytest.mark.asyncio
async def test_granicus_platform_is_not_gated_by_meeting_evidence(monkeypatch):
    """A dedicated meeting platform (not in `_EVIDENCE_REQUIRED_PLATFORMS`)
    is unaffected -- the evidence check is only for direct_file/vimeo/the
    weakest pick.py bucket."""
    from app.utils.video_hand_check import PASS, GateVerdict

    meeting = ResolvedMeeting(
        platform="granicus",
        source_url="https://x.granicus.com/clip/1",
        title="Untitled",
        segments=[{"start": 0, "end": 1, "text": "hi"}],
    )

    async def _fake_resolve_via_platform(url, *, allow_youtube=True):
        return meeting

    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve.resolve_via_platform",
        _fake_resolve_via_platform,
    )
    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve.assess_video_candidate",
        lambda **kwargs: GateVerdict(PASS, "ok"),
    )

    candidates = [
        Candidate(url=meeting.source_url, date="2026-09-08", title="Untitled")
    ]
    result = await resolve_candidates(candidates, _finder_input(meeting.source_url))
    assert result.outcome is None
    assert result.has_segments is True


# --- listing.py: shared Granicus account, several view_ids ---------------


@pytest.mark.asyncio
async def test_granicus_shared_account_picks_view_id_matching_gov_name(monkeypatch):
    """Real case (WO-1041 MULTIGOV_BRIEF follow-up): nevco.granicus.com
    hosts Nevada City (view_id=2), Nevada County (view_id=3) and Grass
    Valley (view_id=4) each under their own populated view_id/RSS channel.
    Given `gov_name="Grass Valley city, California"`, discovery must pick
    view_id=4, not the first populated one."""
    from app.platforms.meeting_finder import listing
    from app.platforms.meeting_finder.fetch import FetchResult

    channel_titles = {
        2: "Nevada City Council",
        3: "Nevada County Board of Supervisors",
        4: "Grass Valley City Council",
    }

    class _FakeFetcher:
        async def fetch(self, url, need_links=False):
            view_id = int(url.split("view_id=")[1].split("&")[0])
            title = channel_titles.get(view_id)
            html = (
                f"<rss><channel><title>{title}</title>"
                f"<item>real meeting</item></channel></rss>"
                if title
                else "<rss><channel><title>empty</title></channel></rss>"
            )
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

    result = await listing._granicus_discover_view_id(
        "https://nevco.granicus.com/",
        _FakeFetcher(),
        gov_name="Grass Valley city, California",
    )
    assert result == "https://nevco.granicus.com/ViewPublisher.php?view_id=4"


@pytest.mark.asyncio
async def test_granicus_shared_account_falls_back_to_first_populated_without_gov_name():
    from app.platforms.meeting_finder import listing
    from app.platforms.meeting_finder.fetch import FetchResult

    channel_titles = {2: "Nevada City Council", 4: "Grass Valley City Council"}

    class _FakeFetcher:
        async def fetch(self, url, need_links=False):
            view_id = int(url.split("view_id=")[1].split("&")[0])
            title = channel_titles.get(view_id)
            html = (
                f"<rss><channel><title>{title}</title>"
                f"<item>real meeting</item></channel></rss>"
                if title
                else "<rss><channel><title>empty</title></channel></rss>"
            )
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

    result = await listing._granicus_discover_view_id(
        "https://nevco.granicus.com/", _FakeFetcher()
    )
    # First populated view_id in range is 2 (Nevada City) -- unchanged
    # behavior from before WO-1041 when no gov_name is supplied.
    assert result == "https://nevco.granicus.com/ViewPublisher.php?view_id=2"


# --- identify.py: destination check on an off-site hop --------------------


@pytest.mark.asyncio
async def test_off_site_vendor_link_naming_a_different_government_is_flagged(
    monkeypatch,
):
    """Real shape (WO-1041 brief item 4): Auburn SD's own site links a
    Granicus tenant that is actually Hooksett, NH's -- the destination
    account URL shares no distinctive word with "Auburn"."""
    from app.platforms.meeting_finder import identify as identify_mod
    from app.platforms.meeting_finder.fetch import FetchResult

    html = '<html><body><a href="https://hooksettnh.granicus.com/">Watch Meetings</a></body></html>'
    page = FetchResult(
        requested_url="https://auburnsd.example.gov/",
        final_url="https://auburnsd.example.gov/",
        status=200,
        html=html,
        access_mode="plain",
        outcome=None,
        challenge=False,
        wayback_timestamp=None,
        links_only=False,
        elapsed_ms=1,
    )

    class _FakeFetcher:
        async def fetch(self, url, need_links=True):
            return page

    result = await identify_mod.identify(
        "https://auburnsd.example.gov/",
        _FakeFetcher(),
        page=page,
        gov_name="Auburn School District",
    )
    assert result.platform == "granicus"
    assert result.destination_mismatch is not None


@pytest.mark.asyncio
async def test_off_site_vendor_link_naming_this_government_is_not_flagged():
    from app.platforms.meeting_finder import identify as identify_mod
    from app.platforms.meeting_finder.fetch import FetchResult

    html = '<html><body><a href="https://grassvalley.granicus.com/">Watch Meetings</a></body></html>'
    page = FetchResult(
        requested_url="https://grassvalleyca.example.gov/",
        final_url="https://grassvalleyca.example.gov/",
        status=200,
        html=html,
        access_mode="plain",
        outcome=None,
        challenge=False,
        wayback_timestamp=None,
        links_only=False,
        elapsed_ms=1,
    )

    class _FakeFetcher:
        async def fetch(self, url, need_links=True):
            return page

    result = await identify_mod.identify(
        "https://grassvalleyca.example.gov/",
        _FakeFetcher(),
        page=page,
        gov_name="Grass Valley city, California",
    )
    assert result.platform == "granicus"
    assert result.destination_mismatch is None


@pytest.mark.asyncio
async def test_no_gov_name_means_no_destination_check():
    """Backward compatibility: every existing caller (runner.py doesn't
    pass gov_name/gov_domain yet) gets identical behavior to before
    WO-1041."""
    from app.platforms.meeting_finder import identify as identify_mod
    from app.platforms.meeting_finder.fetch import FetchResult

    html = '<html><body><a href="https://hooksettnh.granicus.com/">Watch Meetings</a></body></html>'
    page = FetchResult(
        requested_url="https://auburnsd.example.gov/",
        final_url="https://auburnsd.example.gov/",
        status=200,
        html=html,
        access_mode="plain",
        outcome=None,
        challenge=False,
        wayback_timestamp=None,
        links_only=False,
        elapsed_ms=1,
    )

    class _FakeFetcher:
        async def fetch(self, url, need_links=True):
            return page

    result = await identify_mod.identify(
        "https://auburnsd.example.gov/", _FakeFetcher(), page=page
    )
    assert result.destination_mismatch is None
