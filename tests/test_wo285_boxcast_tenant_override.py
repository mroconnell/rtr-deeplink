"""WO-285 (2026-09-12): `scripts/wo134_confirmed_hits_ingest.py`'s shared
tier-3 pin path (`SHARED_HOST_PLATFORMS`/`maybe_write_tenant_override()`)
never covered BoxCast -- confirmed live by WO-258, which had to pin
Habersham County, GA's BoxCast broadcast by hand after
`wo134_confirmed_hits_ingest.py` queued it with no pin at all (zero
mentions of "boxcast" in that file before this fix). See BACKLOG_DONE.md's
WO-285 entry.

Real pin shape reused from tenant_overrides.csv's own hand-written
WO-258 row (host=boxcast.tv, match=channel=boxcast:<channel_id>) -- this
is the exact one this fix now produces automatically.
"""

import scripts.wo134_confirmed_hits_ingest as wo134
from app.platforms.models import ResolvedMeeting

HABERSHAM_GA_GOV_ID = "us:county:13137"
HABERSHAM_CHANNEL = "boxcast:dcj8qnxnnonndniok58o"


def _boxcast_result(*, video_channel=HABERSHAM_CHANNEL) -> ResolvedMeeting:
    # Real shape, WO-258: boxcast.py's own video_url is a signed HLS
    # playlist on a CDN host, never boxcast.tv itself.
    return ResolvedMeeting(
        platform="boxcast",
        source_url="https://boxcast.tv/view/commissioner-meeting-august-17-2026-abc123",
        video_url="https://cf-pull.boxcast.com/abc123/playlist.m3u8?sig=xyz",
        video_channel=video_channel,
    )


def test_boxcast_is_a_shared_host_platform():
    assert "boxcast" in wo134.SHARED_HOST_PLATFORMS


def test_tenant_override_host_is_the_stable_boxcast_tenant_host_not_the_cdn():
    result = _boxcast_result()
    assert wo134._tenant_override_host("boxcast", result, result.source_url) == (
        "boxcast.tv"
    )


def test_tenant_override_match_uses_video_channel_not_external_id():
    result = _boxcast_result()
    assert (
        wo134._tenant_override_match("boxcast", result, result.source_url)
        == f"channel={HABERSHAM_CHANNEL}"
    )


def test_tenant_override_match_is_none_without_a_distinct_video_channel():
    # CLAUDE.md's own rule: a BoxCast pin must key on the CHANNEL, never
    # a blank/account-wide match -- e.g. a direct /view/{broadcast} link
    # boxcast.py couldn't attribute to a distinct channel (BACKLOG.md's
    # WO-245 South Bay, FL entry is the real example of this gap).
    result = _boxcast_result(video_channel=None)
    assert wo134._tenant_override_match("boxcast", result, result.source_url) is None


def test_maybe_write_tenant_override_writes_the_real_habersham_pin(tmp_path):
    pins_path = tmp_path / "tenant_overrides.csv"
    wo134.TENANT_OVERRIDES_CSV = pins_path
    wo134._existing_overrides_cache = None
    result = _boxcast_result()

    wo134.maybe_write_tenant_override(
        "boxcast",
        result,
        result.source_url,
        HABERSHAM_GA_GOV_ID,
        "Habersham County, GA",
        "wo285_test",
    )

    rows = pins_path.read_text(encoding="utf-8").splitlines()
    assert rows[0] == "tenant_host,match,gov_id,strength,source,evidence"
    assert rows[1].startswith(
        f"boxcast.tv,channel={HABERSHAM_CHANNEL},{HABERSHAM_GA_GOV_ID},"
    )


def test_maybe_write_tenant_override_is_idempotent(tmp_path):
    pins_path = tmp_path / "tenant_overrides.csv"
    wo134.TENANT_OVERRIDES_CSV = pins_path
    wo134._existing_overrides_cache = None
    result = _boxcast_result()

    for _ in range(2):
        wo134.maybe_write_tenant_override(
            "boxcast",
            result,
            result.source_url,
            HABERSHAM_GA_GOV_ID,
            "Habersham County, GA",
            "wo285_test",
        )

    rows = pins_path.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 2  # header + exactly one pin row, not two
