"""A video whose own title is a camera or file name gets the fallback page
title "<government name> archive video[, Month YYYY]" (Ryan, 2026-09-21,
WO-931; BACKLOG.md's "A video whose own title is a camera or file name"
entry).

The 12 titles below are the real page titles that entry counted in the
2026-09-21 export (10,280 pages): Viebit 7, Granicus 3 (Laramie County,
WY), YouTube 2. The ingest tests use the same isolated-SQLite fixture as
test_gov_id_zip_recovery.py; their payloads are synthetic in shape only
(the same resolver-payload fields every ingest test uses), with a real
title and a real government id (Laramie County, WY = us:county:56021).
"""

import pytest

from app.utils.video_hand_check import (
    CANNOT_TELL,
    assess_video_candidate,
    is_placeholder_title,
)
from app.utils.video_titles import (
    fallback_video_title,
    is_file_name_title,
    page_title_for_video,
)
from archive.db import crud

REAL_FILE_NAME_TITLES = [
    # Viebit, raw uploaded file names.
    "NYCC-PV-CH-CHA_251218-163834.mp4",
    "NYCC-250-8-2_251218-120823.mp4",
    "8-18-26_Council-Meeting.mp4",
    "CC20260908.mp4",
    "DDA_Meeting_08_20_26.mp4",
    "9_8_26_Council_Meeting.mp4",
    "TBC_06_09_2026Mtg.mp4",
    # Granicus, date-only titles (Laramie County, WY).
    "20251021",
    "171205",
    "20260901",
    # YouTube.
    "7959635610958757251",
    "video1254656692",
]


@pytest.mark.parametrize("title", REAL_FILE_NAME_TITLES)
def test_all_twelve_real_file_name_titles_are_recognised(title):
    assert is_file_name_title(title)


@pytest.mark.parametrize("title", REAL_FILE_NAME_TITLES)
def test_the_gate_uses_the_same_test(title):
    assert is_placeholder_title(title)


@pytest.mark.parametrize(
    "title",
    [
        "City Council Meeting",
        "Regular Council Meeting - October 21, 2025",
        "Watch the budget hearing.mp4 here",
        "Board of Commissioners 2025",
        "",
        None,
    ],
)
def test_real_titles_are_not_file_names(title):
    assert not is_file_name_title(title)


def test_fallback_keeps_month_and_year_only():
    assert (
        fallback_video_title("Laramie County, WY", "2025-10-21")
        == "Laramie County, WY archive video, October 2025"
    )


def test_fallback_without_a_date():
    assert fallback_video_title("Laramie County, WY") == (
        "Laramie County, WY archive video"
    )
    assert fallback_video_title("Laramie County, WY", "not a date") == (
        "Laramie County, WY archive video"
    )


def test_no_government_name_keeps_the_source_title():
    # A blank is a finding: no name, no invented title.
    assert fallback_video_title(None, "2025-10-21") is None
    assert page_title_for_video("20251021", "", "2025-10-21") == "20251021"


def test_a_real_title_is_never_replaced():
    assert (
        page_title_for_video("City Council", "Laramie County, WY", "2025-10-21")
        == "City Council"
    )


def test_a_file_name_with_meeting_words_is_replaced_not_cleaned():
    # Default for the Viebit names that carry a date or meeting words:
    # the fallback, like the rest; never a meeting name built from them.
    assert (
        page_title_for_video(
            "8-18-26_Council-Meeting.mp4", "Laramie County, WY", "2026-08-18"
        )
        == "Laramie County, WY archive video, August 2026"
    )


def test_a_mp4_title_is_cannot_tell_in_the_gate_never_a_reject():
    verdict = assess_video_candidate(title="CC20260908.mp4", platform="vimeo")
    assert verdict.verdict == CANNOT_TELL
    assert verdict.reason == "placeholder_title"


def _payload(external_id, source_url, title, date="2025-10-21"):
    return {
        "platform": "granicus",
        "source_url": source_url,
        "external_id": external_id,
        "gov_id": "us:county:56021",
        "title": title,
        "date": date,
        "jurisdiction": "Laramie County, WY",
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": [],
        "agenda_items": [],
        "transcript_language": None,
        "transcript_warnings": [],
    }


async def test_ingest_gives_a_date_only_title_the_fallback():
    url = "https://laramiecounty-title-test.granicus.com/player/clip/1"
    result = await crud.ingest_resolution(
        _payload("granicus:laramie-title-test:1", url, "20251021"), url
    )
    page = await crud.get_page_by_slug(result["slug"])
    assert page["title"] == "Laramie County, WY archive video, October 2025"
    assert "20251021" not in result["slug"].replace("2025-10-21", "")


async def test_ingest_keeps_a_real_title():
    url = "https://laramiecounty-title-test.granicus.com/player/clip/2"
    result = await crud.ingest_resolution(
        _payload("granicus:laramie-title-test:2", url, "Board of Commissioners"),
        url,
    )
    page = await crud.get_page_by_slug(result["slug"])
    assert page["title"] == "Board of Commissioners"


async def test_reingest_with_a_file_name_title_keeps_the_stored_title():
    # A hand-fixed title (page 10200's shape, WO-925) must survive a
    # re-ingest that still carries the source's file name.
    url = "https://laramiecounty-title-test.granicus.com/player/clip/3"
    ext = "granicus:laramie-title-test:3"
    first = await crud.ingest_resolution(_payload(ext, url, "Board Meeting"), url)
    await crud.ingest_resolution(_payload(ext, url, "20251021"), url)
    page = await crud.get_page_by_slug(first["slug"])
    assert page["title"] == "Board Meeting"
