from archive.utils.segment_time import format_segment_time


def test_format_segment_time_sub_hour():
    # The common case -- must not regress while fixing the hour-rollover bug.
    assert format_segment_time(125) == "2:05"


def test_format_segment_time_hour_rollover():
    # Real confirmed bug: archive/templates/meeting_page.html used to
    # render this with a naive "%d:%02d"|format(seconds // 60, seconds %
    # 60), which has no hour rollover at all. 21887 seconds is really
    # 6:04:47 (confirmed against the <video> element's own native
    # controls), but the old template math produced the literal string
    # "364:47" (21887 // 60 == 364, 21887 % 60 == 47).
    assert format_segment_time(21887) == "6:04:47"


def test_format_segment_time_zero():
    assert format_segment_time(0) == "0:00"


def test_format_segment_time_exact_hour():
    assert format_segment_time(3600) == "1:00:00"


def test_format_segment_time_pads_minutes_and_seconds_within_hour():
    assert format_segment_time(3661) == "1:01:01"


def test_format_segment_time_none_defaults_to_zero():
    assert format_segment_time(None) == "0:00"


def test_format_segment_time_truncates_fractional_seconds():
    assert format_segment_time(125.9) == "2:05"
