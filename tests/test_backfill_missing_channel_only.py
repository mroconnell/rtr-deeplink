"""Tests for scripts/backfill_archived_pages.py's --missing-channel-only
flag (WO-295), and its combination with the script's pre-existing
--platform/--url-contains/--limit flags.

These exercise `filter_pages()` directly against plain, hand-built dicts
shaped like a real `list_all_page_urls()` row (see
tests/test_backfill_page_urls.py for the real, seeded-SQLite-backed
source of that shape) -- no live Archive, DB, or resolve needed, since
filtering a list of dicts has no DB dependency of its own. The values
below (video ids, channel handles) are synthetic placeholders, same
reasoning as tests/test_backfill_video_channel.py's docstring: there is
no geographic/identity fact here to get wrong, just a join/filter to
verify.
"""

from scripts.backfill_archived_pages import filter_pages


def _page(slug: str, *, platform="youtube", video_channel=None, url=None) -> dict:
    return {
        "slug": slug,
        "title": f"Meeting {slug}",
        "platform": platform,
        "source_url_normalized": url or f"https://www.youtube.com/watch?v={slug}",
        "created_at": "2026-09-01T00:00:00+00:00",
        "video_channel": video_channel,
    }


def test_missing_channel_only_keeps_null_and_blank_drops_populated():
    pages = [
        _page("null-channel", video_channel=None),
        _page("blank-channel", video_channel=""),
        _page("whitespace-channel", video_channel="   "),
        _page("has-channel", video_channel="@RealTownCouncil"),
    ]

    result = filter_pages(pages, missing_channel_only=True)

    slugs = {p["slug"] for p in result}
    assert slugs == {"null-channel", "blank-channel", "whitespace-channel"}


def test_missing_channel_only_tolerates_a_missing_key_entirely():
    # A defensive case, not one this script's own data source produces --
    # list_all_page_urls() always includes the key (see
    # test_backfill_page_urls.py) -- but filter_pages() shouldn't KeyError
    # if some other future caller hands it a dict without it.
    pages = [{"slug": "no-key", "platform": "youtube", "source_url_normalized": "x"}]

    result = filter_pages(pages, missing_channel_only=True)

    assert [p["slug"] for p in result] == ["no-key"]


def test_missing_channel_only_off_keeps_everything():
    pages = [
        _page("null-channel", video_channel=None),
        _page("has-channel", video_channel="@RealTownCouncil"),
    ]

    result = filter_pages(pages, missing_channel_only=False)

    assert len(result) == 2


def test_missing_channel_only_combines_with_platform():
    # This is the real intended usage (WO-295's docstring): every affected
    # page is YouTube, so --platform youtube --missing-channel-only should
    # drop a non-YouTube page with no channel, not just a YouTube page
    # that already has one.
    pages = [
        _page("yt-missing", platform="youtube", video_channel=None),
        _page("yt-has-channel", platform="youtube", video_channel="@Town"),
        _page("swagit-missing", platform="swagit", video_channel=None),
    ]

    result = filter_pages(pages, platform="youtube", missing_channel_only=True)

    assert [p["slug"] for p in result] == ["yt-missing"]


def test_missing_channel_only_combines_with_url_contains_and_limit():
    pages = [
        _page(
            "match-1",
            video_channel=None,
            url="https://www.youtube.com/watch?v=aaa1",
        ),
        _page(
            "match-2",
            video_channel=None,
            url="https://www.youtube.com/watch?v=aaa2",
        ),
        _page(
            "no-match",
            video_channel=None,
            url="https://www.youtube.com/watch?v=zzz1",
        ),
        _page(
            "match-but-has-channel",
            video_channel="@Town",
            url="https://www.youtube.com/watch?v=aaa3",
        ),
    ]

    result = filter_pages(
        pages, url_contains="v=aaa", missing_channel_only=True, limit=1
    )

    assert [p["slug"] for p in result] == ["match-1"]


def test_no_filters_returns_pages_unchanged():
    pages = [_page("a"), _page("b")]

    result = filter_pages(pages)

    assert result == pages
