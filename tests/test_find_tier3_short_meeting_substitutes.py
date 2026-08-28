"""Tests for scripts/find_tier3_short_meeting_substitutes.py.

The load-bearing claim under test is the module docstring's discovery
that CivicClerk's `durationMin` field holds seconds despite its name --
proven here from the committed Emporia KS fixture pair (real API
response + real caption file for the same event), not from synthetic
data. The candidate-filtering tests are synthetic but reuse the real
fixture's field shapes (isDeleted/hasMedia/durationMin/startDateTime/
id), per CLAUDE.md's synthetic-test rule; what remains unconfirmed live
is only which OData filter dialect each CivicClerk tenant accepts, and
the script handles that with a client-side past-date re-filter either
way (see cc_list_past_events)."""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import find_tier3_short_meeting_substitutes as f3s  # noqa: E402

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "civicclerk"


def _emporia_event() -> dict:
    return json.loads((FIXTURES / "emporiaks_event585.json").read_text())


def test_duration_min_is_seconds_confirmed_by_real_caption_file():
    # The one real datapoint behind the whole cheap-classification path:
    # the API's durationMin and the same event's committed caption file
    # must agree to within a caption cue's slack.
    event = _emporia_event()
    api_seconds = f3s.cc_duration_seconds(event)
    assert api_seconds == 16821.0

    tail = f3s.srt_tail_seconds((FIXTURES / "emporiaks_585_captions.srt").read_text())
    assert tail is not None
    assert abs(tail - api_seconds) < 2.0


def test_unpopulated_duration_min_is_none_not_zero():
    # clovisca event 20 has real media but durationMin=0 -- 0 must read
    # as "unknown, fall back to ffprobe", never as a zero-length meeting.
    event = json.loads((FIXTURES / "clovisca_event20.json").read_text())
    assert f3s.cc_duration_seconds(event) is None
    assert f3s.cc_media_path(event) == (
        "https://cpmedia.azureedge.net/clovisca/f32a4ab02f.mp4"
    )


def test_short_window_bounds():
    assert not f3s.in_short_window(599)
    assert f3s.in_short_window(600)
    assert f3s.in_short_window(3000)
    assert not f3s.in_short_window(3001)


def test_classify_duration():
    assert f3s.classify_duration(None) == "probe_failed"
    assert f3s.classify_duration(90 * 60) == "not_long"
    assert f3s.classify_duration(90 * 60 + 1) == "long"


def test_cc_past_candidates_filters_and_orders():
    # Synthetic listing reusing the real Events field shapes (see module
    # docstring). Facts are real-shaped: ids/dates only.
    base = _emporia_event()

    def event(id_, start, *, deleted=False, has_media=True):
        e = dict(base)
        e.update(
            {
                "id": id_,
                "startDateTime": start,
                "isDeleted": deleted,
                "hasMedia": has_media,
            }
        )
        if not has_media:
            e.update(
                {
                    "mediaStreamPath": "",
                    "mediaSourcePathMp4": "",
                    "externalMediaUrl": "",
                }
            )
        return e

    now_iso = "2026-08-28T00:00:00Z"
    events = [
        event(1, "2026-08-01T18:00:00Z"),
        event(2, "2026-08-15T18:00:00Z"),
        event(3, "2026-09-15T18:00:00Z"),  # future: scheduled, no video yet
        event(4, "2026-08-20T18:00:00Z", deleted=True),
        event(5, "2026-08-21T18:00:00Z", has_media=False),
        event(6, "2026-08-10T18:00:00Z"),  # already queued (excluded below)
    ]
    picked = f3s.cc_past_candidates(events, exclude_ids={"6"}, now_iso=now_iso)
    assert [e["id"] for e in picked] == [2, 1]  # newest first, others filtered


def test_cc_url_helpers():
    url = "https://losaltoshillsca.portal.civicclerk.com/event/4354/media"
    assert f3s.cc_event_id(url) == "4354"
    assert f3s.tenant_of(url) == "losaltoshillsca.portal.civicclerk.com"
    assert (
        f3s.cc_api_base("losaltoshillsca.portal.civicclerk.com")
        == "https://losaltoshillsca.api.civicclerk.com/v1"
    )
    assert (
        f3s.cc_portal_url("losaltoshillsca.portal.civicclerk.com", 99)
        == "https://losaltoshillsca.portal.civicclerk.com/event/99/media"
    )


def test_legistar_url_helpers():
    # A real queue row's shape (a2gov, tier3_auto_transcription_queue.txt).
    url = (
        "https://a2gov.legistar.com/MeetingDetail.aspx?ID=1251581"
        "&GUID=3959006D-C1DA-4BED-A747-C43A0384D9D4&Options=info%7C&Search="
    )
    assert f3s.legistar_url_id(url) == "1251581"
    assert f3s.legistar_client("a2gov.legistar.com") == "a2gov"


def test_srt_tail_handles_missing_cues():
    assert f3s.srt_tail_seconds("no cues here") is None
    text = "1\n00:00:01,000 --> 00:00:04,500\nhi\n\n2\n00:10:00,000 --> 00:12:30,250\nbye\n"
    assert f3s.srt_tail_seconds(text) == 750.25


def test_hms():
    assert f3s.hms(16821) == "4:40:21"
    assert f3s.hms(750.25) == "12:30"
