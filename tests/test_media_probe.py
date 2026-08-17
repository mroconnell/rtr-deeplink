from app.platforms.media_probe import is_plausible_meeting_duration


def test_plausible_duration_bounds():
    assert not is_plausible_meeting_duration(60)  # 1 min, too short
    assert is_plausible_meeting_duration(30 * 60)  # 30 min, plausible
    assert is_plausible_meeting_duration(4 * 3600)  # 4 hours, plausible
    assert not is_plausible_meeting_duration(20 * 3600)  # 20 hours, implausible
