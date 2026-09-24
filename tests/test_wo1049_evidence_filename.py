"""WO-1049: meeting-evidence check misses filenames and Drive titles;
length-unknown finds demoted even with real evidence.

Real cases (conductor diagnosis, 2026-09-24):

- Bellerive Acres MO: a Google Drive video whose URL carries no title of
  its own, and whose real download link
  (`drive.usercontent.google.com/download?id=...`) wasn't recognized as a
  Drive link at all -- only `drive.google.com` was. File id
  `1GgmbtthXToVwIcy2p6xeEyVZj7OI0erB`, real Drive page title "(2026-09-22)
  City Council Special Meeting".
- Bound Brook NJ: a direct `.mp3` file
  (`https://boundbrook-nj.org/wp-content/uploads/2025/02/
  1-7-2025-Bound-Brook-Borough-Reorganization-Meeting-1.mp3`) that
  ffprobe can't read at all (`reject-dead`) -- demoted to a weak lead even
  though the filename itself names a real meeting.

Uses monkeypatched adapters/probes (no network), same pattern as
`tests/test_wo1024_meeting_finder_resolve.py` and
`tests/test_wo1041_meeting_evidence.py`.
"""

from __future__ import annotations

import pytest

from app.platforms.meeting_finder.models import (
    OUTCOME_VIDEO_LOW_CONFIDENCE,
    Candidate,
    FinderInput,
)
from app.platforms.meeting_finder.resolve import (
    _extract_drive_file_id,
    resolve_candidates,
)
from app.platforms.models import ResolvedMeeting
from app.utils.video_hand_check import decode_filename_text


def _finder_input(url: str, **overrides) -> FinderInput:
    fields = dict(url=url, gov_id=None, mode="pin", entry="resolve")
    fields.update(overrides)
    return FinderInput(**fields)


# --- decode_filename_text() / _extract_drive_file_id() -- pure helpers ----


def test_decode_filename_text_fixes_percent_encoded_word_boundary():
    """WO-1049 diagnosis 1: raw + merely-`unquote()`d text both fail
    `contains_word()`'s `\\b` match on "%20Council" -- the `0` and `C` are
    both `\\w` characters, so there's no boundary between them. Real
    shape: Bellerive Acres MO's file, percent-encoded."""
    from app.utils.video_hand_check import contains_word

    url = (
        "https://drive.google.com/uc?id=x&"
        "%282026-09-22%29%20City%20Council%20Special%20Meeting.mp4"
    )
    # The raw URL fails -- this is the bug being fixed.
    assert not contains_word(url.lower(), "council")
    decoded = decode_filename_text(url)
    assert contains_word(decoded.lower(), "council")


def test_decode_filename_text_fixes_underscore_joined_filename():
    """Synthetic (no real underscore-joined example confirmed yet -- see
    CLAUDE.md's synthetic-test rule): a hyphen alone is already a non-`\\w`
    character, so `contains_word()` finds a boundary around it with no
    decoding needed (confirmed live: Bound Brook NJ's real, hyphen-joined
    "...Reorganization-Meeting-1.mp3" already matches "meeting" raw). An
    UNDERSCORE is a `\\w` character in Python's `re` module, though, so a
    filename joined with underscores instead of hyphens has the exact same
    glued-word problem as the percent-encoded case above."""
    from app.utils.video_hand_check import contains_word

    url = "https://example.gov/files/2025_01_07_Reorganization_Meeting_1.mp3"
    assert not contains_word(url.lower(), "meeting")
    decoded = decode_filename_text(url)
    assert contains_word(decoded.lower(), "meeting")


def test_decode_filename_text_leaves_already_separable_hyphenated_names_matching():
    """Real shape (Bound Brook NJ, confirmed live): a hyphen-joined
    filename already matches without decoding, since a hyphen is not a
    `\\w` character -- decoding must not break this already-working case."""
    from app.utils.video_hand_check import contains_word

    url = (
        "https://boundbrook-nj.org/wp-content/uploads/2025/02/"
        "1-7-2025-Bound-Brook-Borough-Reorganization-Meeting-1.mp3"
    )
    assert contains_word(url.lower(), "meeting")
    decoded = decode_filename_text(url)
    assert contains_word(decoded.lower(), "meeting")


def test_decode_filename_text_none_for_none():
    assert decode_filename_text(None) is None


def test_extract_drive_file_id_classic_share_link():
    assert (
        _extract_drive_file_id(
            "https://drive.google.com/file/d/1GgmbtthXToVwIcy2p6xeEyVZj7OI0erB/view"
        )
        == "1GgmbtthXToVwIcy2p6xeEyVZj7OI0erB"
    )


def test_extract_drive_file_id_legacy_uc_link():
    assert (
        _extract_drive_file_id(
            "https://drive.google.com/uc?id=1GgmbtthXToVwIcy2p6xeEyVZj7OI0erB"
        )
        == "1GgmbtthXToVwIcy2p6xeEyVZj7OI0erB"
    )


def test_extract_drive_file_id_download_link():
    """Real shape confirmed live 2026-09-24 (Bellerive Acres MO) -- the
    one `_is_google_drive_url()` missed before this fix."""
    assert (
        _extract_drive_file_id(
            "https://drive.usercontent.google.com/download"
            "?id=1GgmbtthXToVwIcy2p6xeEyVZj7OI0erB&export=download&confirm=t"
        )
        == "1GgmbtthXToVwIcy2p6xeEyVZj7OI0erB"
    )


def test_extract_drive_file_id_not_a_drive_url():
    assert _extract_drive_file_id("https://example.com/video.mp4") is None
    assert _extract_drive_file_id(None) is None


# --- end-to-end: Drive download link title lookup --------------------------


@pytest.mark.asyncio
async def test_drive_download_link_title_is_fetched_and_used_as_evidence(monkeypatch):
    """Bellerive Acres MO, real shape: the candidate/adapter carry no
    title at all, and the only evidence is Drive's own file-page title,
    reached only because the download-link shape is now recognized."""
    from app.platforms import queue_probe
    from app.utils.video_hand_check import PASS, GateVerdict

    drive_url = (
        "https://drive.usercontent.google.com/download"
        "?id=1GgmbtthXToVwIcy2p6xeEyVZj7OI0erB&export=download&confirm=t"
    )
    meeting = ResolvedMeeting(
        platform="direct_file",
        source_url="https://belleriveacresmo.gov/agendas-minutes/",
        title=None,
        video_url=drive_url,
    )

    async def _fake_resolve_via_platform(url, *, allow_youtube=True):
        return meeting

    async def _fake_probe(*args, **kwargs):
        return queue_probe.ProbeResult(
            url=meeting.source_url,
            platform="direct_file",
            probe_method="ffprobe",
            duration_seconds=1800.0,
            date=None,
            size_bytes=None,
            verdict="accept",
            reason="",
            probe_seconds=0.1,
        )

    async def _fake_drive_title(file_id):
        assert file_id == "1GgmbtthXToVwIcy2p6xeEyVZj7OI0erB"
        return "(2026-09-22) City Council Special Meeting"

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
        "app.platforms.meeting_finder.resolve._fetch_drive_title", _fake_drive_title
    )
    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve._confirm_not_audio_only", _audio_ok
    )

    candidates = [Candidate(url=meeting.source_url, date=None, title=None)]
    result = await resolve_candidates(candidates, _finder_input(meeting.source_url))

    assert result.outcome is None
    assert result.tier == 3
    assert result.video_url == drive_url


# --- end-to-end: percent-encoded filename evidence --------------------------


@pytest.mark.asyncio
async def test_percent_encoded_video_url_filename_is_meeting_evidence(monkeypatch):
    """Diagnosis 1's exact real shape: `_meeting_evidence_texts()` used to
    pass `cand.url`/`result.video_url` raw -- the encoded filename's
    "%20Council" never matched. A direct-file candidate with NO title
    anywhere except the encoded filename must now resolve cleanly."""
    from app.platforms import queue_probe
    from app.utils.video_hand_check import PASS, GateVerdict

    video_url = (
        "https://belleriveacresmo.gov/wp-content/uploads/2026/09/"
        "%282026-09-22%29%20City%20Council%20Special%20Meeting.mp4"
    )
    meeting = ResolvedMeeting(
        platform="direct_file",
        source_url=video_url,
        title=None,
        video_url=video_url,
    )

    async def _fake_resolve_via_platform(url, *, allow_youtube=True):
        return meeting

    async def _fake_probe(*args, **kwargs):
        return queue_probe.ProbeResult(
            url=meeting.source_url,
            platform="direct_file",
            probe_method="ffprobe",
            duration_seconds=1200.0,
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

    candidates = [Candidate(url=video_url, date=None, title=None)]
    result = await resolve_candidates(candidates, _finder_input(video_url))

    assert result.outcome is None
    assert result.tier == 3
    assert result.video_url == video_url


# --- end-to-end: length-unknown video is a clean find with real evidence ---


@pytest.mark.asyncio
async def test_unmeasurable_direct_file_with_filename_evidence_is_a_clean_find(
    monkeypatch,
):
    """Bound Brook NJ, real shape: ffprobe can't read the `.mp3` at all
    (`reject-dead`), but the filename itself names a real meeting
    ("Reorganization Meeting"). Ryan's rule (2026-09-23): this is a real
    find (clean tier-3, duration unknown), not a weak lead."""
    from app.platforms import queue_probe
    from app.utils.video_hand_check import PASS, GateVerdict

    video_url = (
        "https://boundbrook-nj.org/wp-content/uploads/2025/02/"
        "1-7-2025-Bound-Brook-Borough-Reorganization-Meeting-1.mp3"
    )
    meeting = ResolvedMeeting(
        platform="direct_file",
        source_url=video_url,
        title=None,
        video_url=video_url,
    )

    async def _fake_resolve_via_platform(url, *, allow_youtube=True):
        return meeting

    async def _fake_probe(*args, **kwargs):
        return queue_probe.ProbeResult(
            url=meeting.source_url,
            platform="direct_file",
            probe_method="ffprobe",
            duration_seconds=None,
            date=None,
            size_bytes=None,
            verdict="reject-dead",
            reason="ffprobe couldn't read the media",
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
    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve._confirm_not_audio_only", _audio_ok
    )

    candidates = [Candidate(url=video_url, date=None, title=None)]
    result = await resolve_candidates(candidates, _finder_input(video_url))

    assert result.outcome is None
    assert result.tier == 3
    assert result.duration_seconds is None
    assert result.video_url == video_url


@pytest.mark.asyncio
async def test_unmeasurable_video_on_evidence_free_platform_is_a_clean_find(
    monkeypatch,
):
    """A platform that doesn't need meeting evidence at all (not
    direct_file/vimeo, no "undated, lister order" pick) -- a length-unknown
    video from it is a clean find outright, no evidence check needed."""
    from app.platforms import queue_probe
    from app.utils.video_hand_check import PASS, GateVerdict

    meeting = ResolvedMeeting(
        platform="viebit",
        source_url="https://x.viebit.com/event/2/media",
        title="random title with no meeting words",
        video_url="https://x.viebit.com/media/2.m3u8",
    )

    async def _fake_resolve_via_platform(url, *, allow_youtube=True):
        return meeting

    async def _fake_probe(*args, **kwargs):
        return queue_probe.ProbeResult(
            url=meeting.source_url,
            platform="viebit",
            probe_method="ffprobe",
            duration_seconds=None,
            date=None,
            size_bytes=None,
            verdict="reject-dead",
            reason="ffprobe couldn't read the media",
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
    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve._confirm_not_audio_only", _audio_ok
    )

    candidates = [
        Candidate(url=meeting.source_url, date="2026-09-08", title=meeting.title)
    ]
    result = await resolve_candidates(candidates, _finder_input(meeting.source_url))

    assert result.outcome is None
    assert result.tier == 3
    assert result.duration_seconds is None


@pytest.mark.asyncio
async def test_unmeasurable_video_with_no_evidence_at_all_stays_a_weak_lead(
    monkeypatch,
):
    """Contrast case: a direct-file candidate that's unmeasurable AND
    carries no meeting evidence anywhere (bare filename, no date/meeting
    word) stays exactly what it was before this fix -- a weak lead."""
    from app.platforms import queue_probe
    from app.utils.video_hand_check import PASS, GateVerdict

    video_url = "https://example.gov/files/video123.mp4"
    meeting = ResolvedMeeting(
        platform="direct_file",
        source_url=video_url,
        title=None,
        video_url=video_url,
    )

    async def _fake_resolve_via_platform(url, *, allow_youtube=True):
        return meeting

    async def _fake_probe(*args, **kwargs):
        return queue_probe.ProbeResult(
            url=meeting.source_url,
            platform="direct_file",
            probe_method="ffprobe",
            duration_seconds=None,
            date=None,
            size_bytes=None,
            verdict="reject-dead",
            reason="ffprobe couldn't read the media",
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
    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve._confirm_not_audio_only", _audio_ok
    )

    candidates = [Candidate(url=video_url, date=None, title=None)]
    result = await resolve_candidates(candidates, _finder_input(video_url))

    assert result.outcome == OUTCOME_VIDEO_LOW_CONFIDENCE
    assert "no meeting evidence" in result.low_confidence_reason


@pytest.mark.asyncio
async def test_measured_accepted_candidate_still_beats_an_unmeasurable_one(
    monkeypatch,
):
    """ "Still ordered after measured ones" -- when one candidate probes
    with a real, in-window duration, it wins over an unmeasurable one with
    real evidence, even though the unmeasurable one is now a clean find on
    its own."""
    from app.platforms import queue_probe
    from app.utils.video_hand_check import PASS, GateVerdict

    measured_meeting = ResolvedMeeting(
        platform="civicclerk",
        source_url="https://x.portal.civicclerk.com/event/1/media",
        title="City Council Meeting",
        video_url="https://x.portal.civicclerk.com/media/1.mp4",
    )
    unmeasurable_meeting = ResolvedMeeting(
        platform="viebit",
        source_url="https://x.viebit.com/event/2/media",
        title="City Council Meeting",
        video_url="https://x.viebit.com/media/2.m3u8",
    )

    async def _fake_resolve_via_platform(url, *, allow_youtube=True):
        return unmeasurable_meeting if "viebit" in url else measured_meeting

    async def _fake_probe(url, **kwargs):
        if "viebit" in url:
            return queue_probe.ProbeResult(
                url=url,
                platform="viebit",
                probe_method="ffprobe",
                duration_seconds=None,
                date=None,
                size_bytes=None,
                verdict="reject-dead",
                reason="ffprobe couldn't read the media",
                probe_seconds=0.1,
            )
        return queue_probe.ProbeResult(
            url=url,
            platform="civicclerk",
            probe_method="ffprobe",
            duration_seconds=1200.0,
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
    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve._confirm_not_audio_only", _audio_ok
    )

    candidates = [
        Candidate(
            url=unmeasurable_meeting.source_url,
            date="2026-09-09",
            title="City Council Meeting",
        ),
        Candidate(
            url=measured_meeting.source_url,
            date="2026-09-08",
            title="City Council Meeting",
        ),
    ]
    result = await resolve_candidates(
        candidates, _finder_input(unmeasurable_meeting.source_url), max_tries=6
    )

    assert result.outcome is None
    assert result.video_url == measured_meeting.video_url
    assert result.duration_seconds == 1200.0


# --- no-regression: a promo/decorative filename still demotes -------------


@pytest.mark.asyncio
async def test_promo_filename_still_demotes_not_a_clean_find(monkeypatch):
    """No-regression check (build brief): a decorative/promo filename like
    "Doodle.mp4" or "homepage_video_600.mp4" must still be REJECTED by the
    video gate before evidence is ever checked -- our new decoded-filename
    texts must not accidentally launder a promo clip into a real find."""
    from app.platforms import queue_probe
    from app.utils.video_hand_check import REJECT, GateVerdict

    video_url = "https://example.gov/assets/homepage_video_600.mp4"
    meeting = ResolvedMeeting(
        platform="direct_file",
        source_url=video_url,
        title=None,
        video_url=video_url,
    )

    async def _fake_resolve_via_platform(url, *, allow_youtube=True):
        return meeting

    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve.resolve_via_platform",
        _fake_resolve_via_platform,
    )
    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve.assess_video_candidate",
        lambda **kwargs: GateVerdict(REJECT, "decorative_filename:homepage"),
    )
    monkeypatch.setattr(
        queue_probe,
        "probe_queue_entry",
        lambda *a, **k: pytest.fail("gate-rejected video must never reach probing"),
    )

    candidates = [Candidate(url=video_url, date=None, title=None)]
    result = await resolve_candidates(candidates, _finder_input(video_url))

    assert result.outcome == OUTCOME_VIDEO_LOW_CONFIDENCE
    assert "gate rejected" in result.low_confidence_reason


@pytest.mark.asyncio
async def test_doodle_filename_is_non_meeting_evidence_even_decoded(monkeypatch):
    """Same no-regression concern, at the evidence layer rather than the
    gate: an unmeasurable "Doodle.mp4"-shaped filename must still be
    treated as non-meeting evidence once decoded, not accidentally waved
    through."""
    from app.platforms import queue_probe
    from app.utils.video_hand_check import PASS, GateVerdict

    video_url = "https://example.gov/assets/Community-Doodle-Contest.mp4"
    meeting = ResolvedMeeting(
        platform="direct_file",
        source_url=video_url,
        title=None,
        video_url=video_url,
    )

    async def _fake_resolve_via_platform(url, *, allow_youtube=True):
        return meeting

    async def _fake_probe(*args, **kwargs):
        return queue_probe.ProbeResult(
            url=meeting.source_url,
            platform="direct_file",
            probe_method="ffprobe",
            duration_seconds=None,
            date=None,
            size_bytes=None,
            verdict="reject-dead",
            reason="ffprobe couldn't read the media",
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
    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve._confirm_not_audio_only", _audio_ok
    )

    candidates = [Candidate(url=video_url, date=None, title=None)]
    result = await resolve_candidates(candidates, _finder_input(video_url))

    assert result.outcome == OUTCOME_VIDEO_LOW_CONFIDENCE
    assert "no meeting evidence" in result.low_confidence_reason
