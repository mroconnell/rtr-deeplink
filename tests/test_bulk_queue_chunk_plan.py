"""WO-98: scripts/bulk_queue_transcription_backlog.py must build a chunk plan
for a multi-clip meeting, not probe the first clip and call it the meeting.

Real gap, found 2026-09-03 while re-creating the three jobs WO-95 failed.
This script probed `result.video_url` directly -- which for a multi-clip
Swagit meeting is only the FIRST clip -- so every multi-clip meeting it
queued got a job whose probed_duration_seconds and total_chunks covered a
fraction of the real meeting. Nothing failed: the job ran to "completion"
against a partial transcript.

That matters more for this script than for the other paths because it is
the one built to be pointed at the backlog in bulk (see its own module
docstring), so a silent per-meeting shortfall multiplies.

The durations below are the real probed values from Belfast ME
(belfastme.new.swagit.com/videos/01092019-1637, old job 1444): a 3h18m
meeting across 6 clips, whose first clip is 45.3s. That contrast is the
point -- 45s vs 11,914s is the size of the error this test pins.
"""

import pytest

from app.platforms import media_probe
from app.platforms.models import ResolvedMeeting, VideoSegment

FIRST_CLIP_SECONDS = 45.3
REAL_MEETING_SECONDS = 11914.0


def _multi_clip_result():
    return ResolvedMeeting(
        platform="swagit",
        source_url="https://belfastme.new.swagit.com/videos/01092019-1637",
        video_url="https://x/clip1.m3u8",  # the FIRST clip only
        video_format="m3u8",
        video_segments=[
            VideoSegment(url="https://x/clip1.m3u8", seq=2, title="Call to order"),
            VideoSegment(url="https://x/clip2.m3u8", seq=4, title="Business"),
        ],
    )


@pytest.mark.asyncio
async def test_multi_clip_meeting_reports_the_summed_duration_not_the_first_clip(
    monkeypatch,
):
    durations = {
        "https://x/clip1.m3u8": FIRST_CLIP_SECONDS,
        "https://x/clip2.m3u8": REAL_MEETING_SECONDS - FIRST_CLIP_SECONDS,
    }

    async def _probe(url, *, source_page_url):
        return durations[url]

    monkeypatch.setattr(media_probe, "probe_duration", _probe)

    duration, plan = await media_probe.probe_duration_and_chunk_plan(
        _multi_clip_result(),
        source_page_url="https://belfastme.new.swagit.com/videos/01092019-1637",
        max_chunk_seconds=450,
    )

    assert duration == pytest.approx(REAL_MEETING_SECONDS)
    assert duration != pytest.approx(FIRST_CLIP_SECONDS)
    assert plan is not None
    # The long second clip is sub-split, so this is many more chunks than
    # the two clips alone (WO-95).
    assert len(plan) > 2
    assert all(e["duration"] <= 450 for e in plan)
    assert all("media_start" in e for e in plan)


@pytest.mark.asyncio
async def test_single_video_meeting_is_unchanged_and_gets_no_plan(monkeypatch):
    """The overwhelming majority of meetings -- must behave exactly as the
    plain probe_duration() call this replaced."""

    async def _probe(url, *, source_page_url):
        return 3600.0

    monkeypatch.setattr(media_probe, "probe_duration", _probe)

    result = ResolvedMeeting(
        platform="granicus",
        source_url="https://x.granicus.com/player/clip/1",
        video_url="https://x/whole.m3u8",
        video_format="m3u8",
    )
    duration, plan = await media_probe.probe_duration_and_chunk_plan(
        result,
        source_page_url="https://x.granicus.com/player/clip/1",
        max_chunk_seconds=300,
    )
    assert duration == 3600.0
    assert plan is None


def test_bulk_queue_sends_chunk_plan_in_its_create_job_body():
    """The gap was not only in probing -- the create-job body had no
    chunk_plan key at all, so even a correctly-built plan would not have
    reached the Archive. Pins both halves."""
    import inspect
    import scripts.bulk_queue_transcription_backlog as bq

    src = inspect.getsource(bq)
    assert '"chunk_plan": chunk_plan' in src, (
        "bulk_queue's create-job body must send the chunk plan"
    )
    assert "probe_duration_and_chunk_plan" in src, (
        "bulk_queue must use the shared multi-clip-aware probe"
    )
