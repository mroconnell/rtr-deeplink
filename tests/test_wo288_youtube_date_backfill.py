import datetime

from scripts.wo288_youtube_date_backfill import (
    REASON_EXC_FUTURE_TITLE_YEAR,
    REASON_EXC_REVERSE_CLOCK_STAMP,
    REASON_OFF_BY_MORE,
    REASON_OFF_BY_ONE,
    classify_row,
)

# Real rows pulled from the live Archive DB during WO-288's own dry-run
# audit (2026-09-12) via a read-only query -- not invented. See
# BACKLOG_DONE.md's WO-288 entry for the full by-bucket counts and the
# 20-row hand spot check these were drawn from/found during.
TODAY = datetime.date(2026, 9, 12)


def test_off_by_more_real_fort_atkinson_row_applies_title_date():
    # Fort Atkinson, WI city council (page 3052, stored 2 days after the
    # title date) -- caption-confirmed live ("It is Tuesday, August
    # 18th, 2026, 7 p.m.") during the WO-288 spot check.
    result = classify_row(
        "Fort Atkinson City Council August 18, 2026", "2026-08-20", TODAY
    )
    assert result["bucket"] == "off_by_more"
    assert result["diff_days"] == 2
    assert result["proposed_date"] == "2026-08-18"
    assert result["apply"] is True
    assert result["reason"] == REASON_OFF_BY_MORE


def test_off_by_one_normal_direction_applies_title_date():
    # A synthetic but realistic off_by_one row in the expected direction
    # (stored = title + 1 day, the UTC-day-rollover shape rule 1
    # describes) -- shape confirmed real by 813 of 814 live off_by_one
    # rows in the WO-288 audit.
    result = classify_row("City Council Meeting - March 4, 2026", "2026-03-05", TODAY)
    assert result["bucket"] == "off_by_one"
    assert result["diff_days"] == 1
    assert result["proposed_date"] == "2026-03-04"
    assert result["apply"] is True
    assert result["reason"] == REASON_OFF_BY_ONE


def test_off_by_one_reverse_direction_with_clock_stamp_is_an_exception():
    # Real row, page 2041 (Las Vegas Planning Commission) -- the ONLY
    # off_by_one row (of 814) in the reverse direction, and its title
    # carries a raw upload-system clock stamp, not a stated meeting
    # date. Confirmed live during the WO-288 audit.
    result = classify_row(
        "Planning Commission - 8/12/2026 1:00:00 AM", "2026-08-11", TODAY
    )
    assert result["bucket"] == "off_by_one"
    assert result["diff_days"] == -1
    assert result["proposed_date"] is None
    assert result["apply"] is False
    assert result["reason"] == REASON_EXC_REVERSE_CLOCK_STAMP


def test_off_by_more_applies_title_date_after_spot_check():
    # Real row, page 7359 (Hideout, UT Town Council) -- confirmed live
    # by a burned-in on-screen recording timestamp reading
    # "2026-07-23 16:25:04", exactly matching the title.
    result = classify_row(
        "07/23/2026 Town Council Special Meeting", "2026-08-03", TODAY
    )
    assert result["bucket"] == "off_by_more"
    assert result["diff_days"] == 11
    assert result["proposed_date"] == "2026-07-23"
    assert result["apply"] is True
    assert result["reason"] == REASON_OFF_BY_MORE


def test_future_title_date_is_never_applied():
    # Real row, page 8539 (City of Bronson, MI) -- title says "August
    # 27, 2027". Confirmed live: the channel's other uploads are all
    # 2026, the video itself was uploaded "2 days ago" matching the
    # stored 2026-09-10, and the video carries no description -- a
    # title-authoring year typo, not a real future date.
    result = classify_row(
        "August 27, 2027 - Special City Council Meeting", "2026-09-10", TODAY
    )
    assert result["proposed_date"] is None
    assert result["apply"] is False
    assert result["reason"] == REASON_EXC_FUTURE_TITLE_YEAR


def test_future_title_date_exception_catches_near_term_dates_too():
    # Real row, page 9113 (Vermillion, SD City Council) -- YouTube's own
    # title metadata says "2026-09-17" but the VIDEO'S OWN on-screen
    # title card (confirmed live) reads "City Council / September 8,
    # 2026" -- exactly the already-stored date. The uploader mislabeled
    # the YouTube title, not the recording.
    result = classify_row("2026-09-17 City Council", "2026-09-08", TODAY)
    assert result["proposed_date"] is None
    assert result["apply"] is False
    assert result["reason"] == REASON_EXC_FUTURE_TITLE_YEAR


def test_already_correct_row_is_not_a_candidate():
    result = classify_row("City Council Meeting - March 4, 2026", "2026-03-04", TODAY)
    assert result is None


def test_no_parseable_title_date_is_not_a_candidate():
    result = classify_row("Regular City Council Meeting", "2026-03-04", TODAY)
    assert result is None


def test_year_only_off_row_still_applies_title_date_when_in_the_past():
    # Real row, page 4950 -- title states a full YEAR earlier than the
    # stored date ("Regular City Council Meeting - 3/5/2018", stored
    # 2019-03-05), a real archival-footage-uploaded-a-year-late shape,
    # not a typo (title year is in the past, not the future -- doesn't
    # trip the future-date exclusion).
    result = classify_row(
        "Regular City Council Meeting - 3/5/2018", "2019-03-05", TODAY
    )
    assert result["bucket"] == "off_by_more"
    assert result["proposed_date"] == "2018-03-05"
    assert result["apply"] is True
    assert result["reason"] == REASON_OFF_BY_MORE
