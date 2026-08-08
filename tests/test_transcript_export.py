from archive.utils.transcript_export import to_srt, to_txt

SEGMENTS = [
    {"start": 0.0, "end": 2.5, "text": "Good evening."},
    {"start": 3725.75, "end": 3730.0, "text": "Meeting adjourned."},
]


def test_to_srt_format():
    srt = to_srt(SEGMENTS)
    lines = srt.split("\n")
    assert lines[0] == "1"
    assert lines[1] == "00:00:00,000 --> 00:00:02,500"
    assert lines[2] == "Good evening."
    assert lines[3] == ""
    assert lines[4] == "2"
    assert lines[5] == "01:02:05,750 --> 01:02:10,000"
    assert lines[6] == "Meeting adjourned."


def test_to_txt_format():
    txt = to_txt(SEGMENTS)
    lines = txt.split("\n")
    assert lines[0] == "[0:00] Good evening."
    assert lines[1] == "[1:02:05] Meeting adjourned."


def test_to_txt_omits_hours_when_under_an_hour():
    assert to_txt([{"start": 65.0, "end": 66.0, "text": "hi"}]) == "[1:05] hi"
