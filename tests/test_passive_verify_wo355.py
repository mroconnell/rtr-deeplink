"""Tests for WO-355's two rule changes to `app/platforms/passive_verify.py`
(Ryan, 2026-09-13), both shipped as opt-in keyword options on `verify_hub()`
so every existing caller/test (see `test_passive_verify.py`,
`test_passive_verify_wo348.py`) is unaffected by default.

1. "Walk deeper" -- `verify_hub(..., deep_walk=True)` reads up to
   `listing_limit` (default `DEEP_WALK_LISTING_LIMIT`, 15) listed meetings
   newest-first and COLLECTS up to `video_collect_limit` (default
   `DEEP_WALK_VIDEO_COLLECT_LIMIT`, 3) that carry video, instead of
   stopping at the first one -- `VerifyResult.video_candidates`.
2. "Hand-read deeper" -- `select_on_mission_candidate()` is the automatic
   half of the rule: checks the collected candidates in order with the
   same `classify_video_hand_check()` phrase list every other sweep
   script already uses as its pre-filter, and returns the first one that
   isn't flagged (a caller still has to actually read the title/channel
   itself -- see that function's own docstring).

The candidate titles below are SYNTHETIC (not captured from a live
listing) but follow the real `CalendarPageError` candidate-dict shape
`_walk_candidates()` already consumes in production, and the phrases used
("Ribbon Cutting", "School Board", a plain "City Council Regular Meeting")
are the same ones `app/utils/video_hand_check.py`'s real, already-shipped
Kind A/B phrase list matches on live data -- per CLAUDE.md's synthetic-
test convention, this exercises the deep-walk/hand-read wiring, not a new,
unconfirmed real-world shape.
"""

from app.platforms.base import CalendarPageError, register
from app.platforms.models import TranscriptSegment
from app.platforms.passive_verify import (
    DEEP_WALK_LISTING_LIMIT,
    DEEP_WALK_VIDEO_COLLECT_LIMIT,
    select_on_mission_candidate,
    verify_hub,
)

from aiohttp_mock import FakeResponse, mock_session

from test_passive_verify import _FakeFinder, _resolved  # noqa: E402

_BLAND_HUB_HTML = "<html><body><a href='/about'>About</a></body></html>"


async def test_deep_walk_collects_up_to_three_instead_of_stopping_at_first():
    # Newest-first: a promo clip (has video, no captions), then a real
    # council meeting (video+captions), then an older meeting (video, no
    # captions) -- deep_walk=True must not stop at the promo, it must
    # keep walking and collect all three (video_collect_limit defaults
    # to 3), newest-first, in video_candidates.
    fake = _FakeFinder(
        {
            "https://example.test/hub": CalendarPageError(
                "listing",
                candidates=[
                    {
                        "title": "Ribbon Cutting - New Fire Station",
                        "date": "2026-09-10",
                        "url": "https://example.test/m1",
                    },
                    {
                        "title": "City Council Regular Meeting",
                        "date": "2026-09-01",
                        "url": "https://example.test/m2",
                    },
                    {
                        "title": "City Council Regular Meeting",
                        "date": "2026-08-01",
                        "url": "https://example.test/m3",
                    },
                ],
            ),
            "https://example.test/m1": _resolved(
                video_url="https://cdn.example.test/promo.mp4",
                source_url="https://example.test/m1",
            ),
            "https://example.test/m2": _resolved(
                video_url="https://cdn.example.test/council.mp4",
                segments=[TranscriptSegment(start=0, end=1, text="hi")],
                source_url="https://example.test/m2",
            ),
            "https://example.test/m3": _resolved(
                video_url="https://cdn.example.test/older.mp4",
                source_url="https://example.test/m3",
            ),
        }
    )
    register(fake)

    routes = {
        "https://example.test/hub": FakeResponse(status=200, text=_BLAND_HUB_HTML)
    }
    with mock_session(routes):
        result = await verify_hub(
            "https://example.test/hub",
            platform_hint="fake_platform",
            deep_walk=True,
        )

    assert result.video_found is True
    assert len(result.video_candidates) == 3
    titles = [c["title"] for c in result.video_candidates]
    assert titles == [
        "Ribbon Cutting - New Fire Station",
        "City Council Regular Meeting",
        "City Council Regular Meeting",
    ]
    urls = [c["url"] for c in result.video_candidates]
    assert urls == [
        "https://example.test/m1",
        "https://example.test/m2",
        "https://example.test/m3",
    ]
    # Top-level fields still describe the FIRST (newest) collected
    # candidate, same shape a non-deep_walk caller already relies on.
    assert result.meeting_url == "https://example.test/m1"
    assert result.captions_found is False


async def test_default_deep_walk_off_still_stops_at_first_video():
    # Without deep_walk, behavior is byte-for-byte the WO-333/341
    # original: stop at the first candidate with video, never touch the
    # rest, video_candidates stays empty.
    fake = _FakeFinder(
        {
            "https://example.test/hub2": CalendarPageError(
                "listing",
                candidates=[
                    {
                        "title": "Ribbon Cutting - New Fire Station",
                        "date": "2026-09-10",
                        "url": "https://example.test/n1",
                    },
                    {
                        "title": "City Council Regular Meeting",
                        "date": "2026-09-01",
                        "url": "https://example.test/n2",
                    },
                ],
            ),
            "https://example.test/n1": _resolved(
                video_url="https://cdn.example.test/promo.mp4",
                source_url="https://example.test/n1",
            ),
            "https://example.test/n2": _resolved(
                video_url="https://cdn.example.test/council.mp4",
                source_url="https://example.test/n2",
            ),
        }
    )
    register(fake)

    routes = {
        "https://example.test/hub2": FakeResponse(status=200, text=_BLAND_HUB_HTML)
    }
    with mock_session(routes):
        result = await verify_hub(
            "https://example.test/hub2", platform_hint="fake_platform"
        )

    assert result.video_found is True
    assert result.meeting_url == "https://example.test/n1"
    assert result.video_candidates == []
    assert "n2" not in "".join(fake.calls)


async def test_deep_walk_respects_listing_limit_of_15():
    # 20 listed candidates, none with video except the 16th -- with the
    # default listing_limit (DEEP_WALK_LISTING_LIMIT == 15), the walk
    # must never reach the 16th, and the honest verdict is "no video",
    # not a false negative reported as an error.
    assert DEEP_WALK_LISTING_LIMIT == 15
    assert DEEP_WALK_VIDEO_COLLECT_LIMIT == 3

    candidates = [
        {
            "title": f"Meeting {i}",
            "date": f"2026-09-{i:02d}",
            "url": f"https://example.test/deep{i}",
        }
        for i in range(1, 21)
    ]
    script = {
        "https://example.test/hub3": CalendarPageError("listing", candidates=candidates)
    }
    for i in range(1, 21):
        video_url = "https://cdn.example.test/v16.mp4" if i == 16 else None
        script[f"https://example.test/deep{i}"] = _resolved(
            video_url=video_url, source_url=f"https://example.test/deep{i}"
        )
    fake = _FakeFinder(script)
    register(fake)

    routes = {
        "https://example.test/hub3": FakeResponse(status=200, text=_BLAND_HUB_HTML)
    }
    with mock_session(routes):
        result = await verify_hub(
            "https://example.test/hub3",
            platform_hint="fake_platform",
            deep_walk=True,
        )

    assert result.video_found is False
    assert result.meeting_found is True
    assert result.candidates_checked == 15
    assert result.video_candidates == []
    assert "deep16" not in "".join(fake.calls)


def test_select_on_mission_candidate_skips_flagged_and_returns_first_clean():
    candidates = [
        {
            "title": "Ribbon Cutting - New Fire Station",
            "date": "2026-09-10",
            "url": "https://example.test/m1",
            "platform": "fake_platform",
            "captions_found": False,
        },
        {
            "title": "City Council Regular Meeting",
            "date": "2026-09-01",
            "url": "https://example.test/m2",
            "platform": "fake_platform",
            "captions_found": True,
        },
    ]
    chosen, skipped = select_on_mission_candidate(candidates, gov_name="Example City")
    assert chosen["url"] == "https://example.test/m2"
    assert len(skipped) == 1
    assert skipped[0]["url"] == "https://example.test/m1"
    assert skipped[0]["hand_check_kind"] == "B"


def test_select_on_mission_candidate_skips_kind_a_wrong_body():
    candidates = [
        {
            "title": "Example School Board Meeting",
            "date": "2026-09-10",
            "url": "https://example.test/m1",
            "platform": "fake_platform",
            "captions_found": False,
        },
        {
            "title": "City Council Regular Meeting",
            "date": "2026-09-01",
            "url": "https://example.test/m2",
            "platform": "fake_platform",
            "captions_found": True,
        },
    ]
    chosen, skipped = select_on_mission_candidate(candidates)
    assert chosen["url"] == "https://example.test/m2"
    assert skipped[0]["hand_check_kind"] == "A"


def test_select_on_mission_candidate_returns_none_when_all_flagged():
    candidates = [
        {"title": "Ribbon Cutting", "url": "https://example.test/m1"},
        {"title": "Swearing In Ceremony", "url": "https://example.test/m2"},
    ]
    chosen, skipped = select_on_mission_candidate(candidates)
    assert chosen is None
    assert len(skipped) == 2


def test_select_on_mission_candidate_empty_list():
    chosen, skipped = select_on_mission_candidate([])
    assert chosen is None
    assert skipped == []


async def test_deep_walk_plus_hand_read_end_to_end_promo_then_wrong_body_then_real():
    # Full pipeline: deep_walk collects 3 candidates (promo, a Kind-A
    # wrong-body video, and a real council meeting third) --
    # select_on_mission_candidate() must skip the first two and land on
    # the third, matching Ryan's rule 2 ("check the collected videos in
    # order until one looks on-mission").
    fake = _FakeFinder(
        {
            "https://example.test/hub4": CalendarPageError(
                "listing",
                candidates=[
                    {
                        "title": "Ribbon Cutting - New Fire Station",
                        "date": "2026-09-10",
                        "url": "https://example.test/e1",
                    },
                    {
                        "title": "Example School Board Meeting",
                        "date": "2026-09-05",
                        "url": "https://example.test/e2",
                    },
                    {
                        "title": "City Council Regular Meeting",
                        "date": "2026-09-01",
                        "url": "https://example.test/e3",
                    },
                ],
            ),
            "https://example.test/e1": _resolved(
                video_url="https://cdn.example.test/e1.mp4",
                source_url="https://example.test/e1",
            ),
            "https://example.test/e2": _resolved(
                video_url="https://cdn.example.test/e2.mp4",
                source_url="https://example.test/e2",
            ),
            "https://example.test/e3": _resolved(
                video_url="https://cdn.example.test/e3.mp4",
                segments=[TranscriptSegment(start=0, end=1, text="hi")],
                source_url="https://example.test/e3",
            ),
        }
    )
    register(fake)

    routes = {
        "https://example.test/hub4": FakeResponse(status=200, text=_BLAND_HUB_HTML)
    }
    with mock_session(routes):
        result = await verify_hub(
            "https://example.test/hub4",
            platform_hint="fake_platform",
            deep_walk=True,
            name="Example City",
        )

    assert len(result.video_candidates) == 3
    chosen, skipped = select_on_mission_candidate(
        result.video_candidates, gov_name="Example City"
    )
    assert chosen["url"] == "https://example.test/e3"
    assert chosen["captions_found"] is True
    assert len(skipped) == 2
    assert skipped[0]["hand_check_kind"] == "B"
    assert skipped[1]["hand_check_kind"] == "A"
