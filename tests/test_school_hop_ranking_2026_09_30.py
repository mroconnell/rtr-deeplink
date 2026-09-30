"""School-hop ranking fixes from the 250-district eval (2026-09-30).

Evidence: research/school_hop_eval_2026-09-30 (business workspace) and its
rerun_2026-09-30. Pages below are small synthetic nav pages shaped after the
real cases named in each test, not captured payloads.
"""

from __future__ import annotations

from app.platforms.meeting_finder import runner
from app.platforms.meeting_finder.fetch import FetchResult
from app.platforms.meeting_finder.hop import (
    _school_vocabulary_bonus,
    rank_hops,
)

BASE = "https://www.exampleusd.org/"


def _page(html: str) -> FetchResult:
    return FetchResult(
        requested_url=BASE,
        final_url=BASE,
        status=200,
        html=html,
        access_mode="plain",
        outcome=None,
        challenge=False,
        wayback_timestamp=None,
        links_only=False,
        elapsed_ms=0,
    )


def _scores(html: str, **kw) -> dict:
    return {h.url: h.score for h in rank_hops(_page(html), limit=50, **kw)}


# ---- 1. bare hero-video files ----------------------------------------------


def test_hero_video_file_is_penalized_and_leaves_top3():
    html = """<html><body><video autoplay><source src="/media/hero-loop.mp4"></video>
    <nav><a href="/board/meetings">Board Meetings</a>
    <a href="/about-us/board-of-education">Board of Education</a>
    <a href="/agendas-minutes">Agendas and Minutes</a></nav></body></html>"""
    video = BASE + "media/hero-loop.mp4"
    for school in (False, True):
        urls = [h.url for h in rank_hops(_page(html), school=school, limit=20)]
        assert urls[0] != video, (school, urls)
        assert video not in urls[:3], (school, urls)


def test_hero_video_penalty_does_not_need_school_mode():
    # Finalsite-style resources host: not a meeting vendor.
    src = "https://resources.finalsite.net/videos/t_video_mp4_1080/v1751281344/x/y/homepage-hero.mp4"
    html = f'<video><source src="{src}"></video><a href="/board/meetings">Board</a>'
    assert _scores(html).get(src, 0) < 20
    assert (
        _scores('<video src="/files/background.webm"></video>')[
            BASE + "files/background.webm"
        ]
        < 20
    )


def test_meeting_looking_video_file_not_penalized():
    hero = _scores('<video src="/media/hero.mp4"></video>')[BASE + "media/hero.mp4"]
    for name in (
        "/media/board-meeting-2026.mp4",
        "/media/council-session.mp4",
        "/media/regular-meeting.m4v",
        "/media/special.webm",
        "/media/agenda-item.mp4",
        "/media/09-15-2026.mp4",
        "/media/2026-09-15-recording.mp4",
        "/media/20260915.mp4",
    ):
        named = _scores(f'<video src="{name}"></video>')[BASE + name.lstrip("/")]
        assert named > hero + 20, name


def test_long_numeric_id_in_path_is_not_a_date():
    src = "https://resources.finalsite.net/videos/v1751281344/abc/hero.mp4"
    assert _scores(f'<video src="{src}"></video>').get(src, 0) < 20


def test_video_file_link_with_anchor_text_not_penalized():
    linked = _scores('<a href="/m/clip.mp4">Watch the clip</a>')
    assert linked[BASE + "m/clip.mp4"] > 30  # keeps the direct-file bonus


def test_vendor_hosted_media_not_penalized():
    vimeo = "https://player.vimeo.com/video/123456789"
    s = _scores(
        f'<iframe src="{vimeo}"></iframe>'
        '<video src="https://cityofx.granicus.com/videos/hero.mp4"></video>'
    )
    assert s[vimeo] > 30
    assert s["https://cityofx.granicus.com/videos/hero.mp4"] > 30


# ---- 2. narrow the bare Board bonus ----------------------------------------


def test_board_bonus_only_for_whole_board_anchor():
    for ok in (
        "Board",
        "School Board",
        "Board of Education",
        "Board of Trustees",
        "Governing Board",
        "The School Board",
        " Board of Directors ",
    ):
        assert _school_vocabulary_bonus(ok, BASE + "fs/pages/1") == 10.0, ok
    for bad in (
        "School Board Policy",
        "Contact the School Board",
        "Student School Board Members",
        "Board of Education Elections",
        "School Board Candidates",
    ):
        assert _school_vocabulary_bonus(bad, BASE + "fs/pages/1") == 0.0, bad


def test_menomonee_falls_shape_meetings_beats_board_policy_and_contact():
    html = """<nav>
    <a href="/fs/pages/1">School Board Policy</a>
    <a href="/fs/pages/2">Contact the School Board</a>
    <a href="/fs/pages/3">Student School Board Members</a>
    <a href="/fs/pages/4">Meetings</a>
    <a href="/fs/pages/5">School Board</a></nav>"""
    urls = [h.url for h in rank_hops(_page(html), school=True, limit=20)]

    def pos(n):
        u = BASE + f"fs/pages/{n}"
        return urls.index(u) if u in urls else 99

    assert pos(4) == 0, urls
    assert pos(5) == 1, urls
    # The three look-alikes no longer get the bare-Board bonus.
    assert pos(1) > pos(5) and pos(2) > pos(5) and pos(3) > pos(5)


# ---- 3. school-only penalties ----------------------------------------------

NOT_MEETING = [
    ("Board Policy", "/board/policy"),
    ("Policies", "/fs/pages/11"),
    ("Contact the Board", "/fs/pages/12"),
    ("Board Members", "/fs/pages/13"),
    ("Member Bios", "/fs/pages/14"),
    ("Board Elections", "/fs/pages/15"),
    ("Board Calendar", "/fs/pages/16"),
    ("Public Records", "/fs/pages/17"),
    ("Employment", "/fs/pages/18"),
    ("Budget", "/fs/pages/19"),
    ("Bond Information", "/fs/pages/20"),
]


def test_school_penalizes_non_meeting_board_links_by_anchor_and_path():
    # A path with a meeting word, so the link is scored even without the
    # penalty; only the penalized word differs between the two.
    neutral = _scores('<a href="/board/meeting-info">Board Info</a>', school=True)
    assert BASE + "board/meeting-info" in neutral
    for anchor, path in NOT_MEETING:
        html = f'<a href="/board/meeting-info{path}">{anchor}</a>'
        u = BASE + "board/meeting-info" + path
        off = _scores(html)
        on = _scores(html, school=True)
        # Penalty is school-only: school mode never lifts these links above
        # city scoring by more than the (<= +10) board bonus it removes.
        assert on.get(u, -999) < off.get(u, 999) or u not in on, anchor
    # Path words count even when the anchor is opaque.
    s = _scores(
        '<a href="/board/meeting-info/policy">Info</a>'
        '<a href="/board/meeting-info/news">Info</a>',
        school=True,
    )
    assert s[BASE + "board/meeting-info/policy"] < s[BASE + "board/meeting-info/news"]


def test_penalty_only_with_school_true(monkeypatch):
    from app.platforms.meeting_finder import hop

    url = BASE + "board/meeting-info/policy"
    assert hop._school_not_meetings_penalty("Info", url) == -10.0
    assert hop._school_not_meetings_penalty("Info", BASE + "board/news") == 0.0

    def boom(*a, **k):
        raise AssertionError("school penalty used with school=False")

    monkeypatch.setattr(hop, "_school_not_meetings_penalty", boom)
    rank_hops(_page(f'<a href="{url}">Board Policy</a>'), limit=5)


def test_meeting_phrase_link_with_penalized_word_is_left_alone():
    html = '<a href="/board/calendar">Board Meeting Calendar</a>'
    on = _scores(html, school=True)
    assert on[BASE + "board/calendar"] > 20


# ---- 4. "Meetings" and "Meeting Videos" ---------------------------------------


def test_meetings_and_meeting_videos_get_phrase_bonus():
    assert _school_vocabulary_bonus("Meetings", BASE + "fs/pages/1") == 16.0
    assert _school_vocabulary_bonus(" Meeting ", BASE + "fs/pages/1") == 16.0
    assert _school_vocabulary_bonus("Meeting Videos", BASE + "fs/pages/1") == 16.0
    # Whole anchor only.
    assert _school_vocabulary_bonus("Meetings Policy Handbook", BASE + "x") == 0.0
    # Only in school mode: city scoring gets no extra bonus for it.
    html = '<a href="/fs/pages/4">Meetings</a>'
    assert _scores(html, school=True)[BASE + "fs/pages/4"] == (
        _scores(html)[BASE + "fs/pages/4"] + 16.0
    )


# ---- 5. runner follows 5 siblings for schools --------------------------------


def test_runner_school_sibling_limit_is_five():
    assert runner._MAX_SIBLING_HOPS_PER_PAGE == 3
    assert runner._MAX_SIBLING_HOPS_PER_PAGE_SCHOOL == 5
