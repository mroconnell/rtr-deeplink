"""WO-908 (2026-09-19): unit coverage for wo908_headless_pilot.py's own
logic -- CSV loading, outcome bucketing, aggregation, and the
`direct_file` plausibility check. It deliberately does NOT mock
`run_access_ladder()` itself or the network layer: this script's whole
job is a live run against real government sites (that's the pilot), so
the only logic worth a fixture-backed regression test is the thin driver
code around it, per this repo's own convention that a synthetic test
exercises one already-real-confirmed logic branch rather than standing
in for "test against a real URL first."

Two real-fact fixtures used below, both pulled verbatim from WO-908's own
200-row candidate export (a real, random sample from the live Gov
Coverage dashboard, 2026-09-19) rather than invented:

* Dubois town, WY (`duboiswyoming.org`) and Calhoun County, FL
  (`calhouncountyfl.gov`) are real rows from that export.
* The `nps.gov` Yellowstone orientation-video URL in the
  `direct_file_hit_is_plausible()` tests below is the REAL hit this
  pilot's own first live smoke-test run found on Dubois town, WY's
  homepage (confirmed live 2026-09-19) -- not a hypothetical: Dubois,
  WY's site links out to National Park Service content, and a Yellowstone
  visitor-orientation `.mp4` on `nps.gov` matched `detect_platform()`'s
  `direct_file` category purely by file extension, with nothing to do
  with the town's own government. This is the concrete case
  `direct_file_hit_is_plausible()` exists to catch.
"""

import pytest

from scripts.wo908_headless_pilot import (
    BucketCounts,
    classify_bucket,
    direct_file_hit_is_plausible,
    load_candidates,
    summarize_by_gov_kind,
    tally_buckets,
    _registrable_domain,
)


# --- load_candidates() ----------------------------------------------------

_REAL_CANDIDATE_CSV_HEADER = (
    "gov_id,name,state,country,gov_kind,population,domain,reject_reason\n"
)
# Real rows, verbatim from WO-908's own 200-row candidate export.
_REAL_CANDIDATE_ROWS = (
    "38:5621415,Dubois town,WY,us,municipality,989,duboiswyoming.org,"
    "no-platform-link-found\n"
    "36:12013,Calhoun County,FL,us,county,13278,calhouncountyfl.gov,"
    "no-platform-link-found\n"
    # A blank population (real shape seen on several township rows in the
    # actual export, e.g. Three Lakes town, WI) -- load_candidates() must
    # keep it blank, never guess a number.
    "37:5508579700,Three Lakes town,WI,us,township,,"
    "townofthreelakeswi.gov,no-platform-link-found\n"
)


def test_load_candidates_reads_real_rows(tmp_path):
    csv_path = tmp_path / "candidates.csv"
    csv_path.write_text(_REAL_CANDIDATE_CSV_HEADER + _REAL_CANDIDATE_ROWS)

    rows = load_candidates(csv_path)

    assert len(rows) == 3
    assert rows[0].gov_id == "38:5621415"
    assert rows[0].name == "Dubois town"
    assert rows[0].domain == "duboiswyoming.org"
    assert rows[1].gov_kind == "county"
    # A blank population column is reported as an empty string, never
    # guessed at -- "Reports report; they never guess" (CLAUDE.md).
    assert rows[2].population == ""


def test_load_candidates_rejects_a_csv_missing_a_required_column(tmp_path):
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("gov_id,name,state,country,gov_kind,domain\n")

    with pytest.raises(ValueError, match="population"):
        load_candidates(csv_path)


# --- classify_bucket() -----------------------------------------------------
# rung_answered/access_mode values mirror LadderResult's own real
# vocabulary as defined in scripts/wo147_access_ladder_sweep.py's
# run_access_ladder() -- see that function's returns for each case
# reproduced here.


def test_classify_bucket_credits_the_rung_that_found_a_real_platform():
    assert classify_bucket("granicus", "plain") == "plain"
    assert classify_bucket("civicclerk", "browser-headers") == "browser-headers"
    assert classify_bucket("youtube", "headless") == "headless"


def test_classify_bucket_challenge_with_no_platform():
    assert classify_bucket(None, "challenge") == "challenge"


def test_classify_bucket_dead_covers_both_true_dead_ends_and_no_hit_found():
    # A true access dead-end (DNS failure, or blocked under both header
    # sets) -- LadderResult's own "dead"/"none" rung_answered values.
    assert classify_bucket(None, "dead") == "dead"
    assert classify_bucket(None, "none") == "dead"
    # A rung that was reached but found no platform link at all -- the
    # "reached, hop links checked, no platform link found" /
    # "headless reached the page, no platform link found" cases.
    assert classify_bucket(None, "plain") == "dead"
    assert classify_bucket(None, "browser-headers") == "dead"
    assert classify_bucket(None, "headless") == "dead"


def test_classify_bucket_empty_string_platform_counts_as_not_found():
    # run_access_ladder() only ever sets platform to a real string or
    # None, but this pilot's own report CSV round-trips through csv.
    # DictReader, where a blank cell reads back as "" -- classify_bucket()
    # is also exercised directly against LadderResult.platform (which is
    # None, never ""), so both falsy shapes must behave the same way.
    assert classify_bucket("", "plain") == "dead"


# --- tally_buckets() / summarize_by_gov_kind() -----------------------------


def test_tally_buckets_counts_each_bucket():
    counts = tally_buckets(
        ["plain", "plain", "dead", "challenge", "headless", "browser-headers"]
    )
    assert counts == BucketCounts(
        plain=2, browser_headers=1, headless=1, challenge=1, dead=1
    )
    assert counts.total == 6
    assert counts.found_total == 4  # plain + browser-headers + headless


def test_tally_buckets_rejects_an_unknown_bucket_value():
    with pytest.raises(ValueError, match="unknown bucket"):
        tally_buckets(["plain", "not-a-real-bucket"])


def test_summarize_by_gov_kind_breaks_down_by_kind_present_only():
    rows = [
        {"gov_kind": "county", "bucket": "plain"},
        {"gov_kind": "county", "bucket": "dead"},
        {"gov_kind": "municipality", "bucket": "dead"},
        {"gov_kind": "municipality", "bucket": "dead"},
        {"gov_kind": "municipality", "bucket": "headless"},
    ]

    summary = summarize_by_gov_kind(rows)

    assert set(summary) == {"overall", "county", "municipality"}
    assert summary["overall"].total == 5
    assert summary["overall"].found_total == 2  # 1 plain + 1 headless
    assert summary["county"].total == 2
    assert summary["county"].plain == 1
    assert summary["municipality"].total == 3
    assert summary["municipality"].headless == 1
    # A gov_kind that never appears in the rows (e.g. "township" here)
    # must not show up at all -- "don't force a breakdown" on a bucket
    # with no data (WO-908's own brief).
    assert "township" not in summary


def test_summarize_by_gov_kind_on_empty_rows():
    assert summarize_by_gov_kind([]) == {"overall": BucketCounts()}


# --- direct_file plausibility ----------------------------------------------


def test_registrable_domain_strips_www_and_subdomains():
    assert _registrable_domain("www.duboiswyoming.org") == "duboiswyoming.org"
    assert _registrable_domain("duboiswyoming.org") == "duboiswyoming.org"
    assert _registrable_domain("sub.calhouncountyfl.gov") == "calhouncountyfl.gov"


def test_direct_file_hit_rejects_the_real_dubois_wy_false_positive():
    # The real, live-confirmed false positive this check exists for (see
    # module docstring): Dubois town, WY's own homepage links out to the
    # National Park Service, and a Yellowstone orientation video on
    # nps.gov matched detect_platform()'s direct_file category by file
    # extension alone.
    nps_video_url = (
        "https://www.nps.gov/nps-audiovideo/legacy/yell/"
        "A35E7E79-CDF6-74D8-26332556B9F2D5E2/"
        "yell-Orientationnocaptions2_1280x720.mp4"
    )
    assert not direct_file_hit_is_plausible("duboiswyoming.org", nps_video_url)


def test_direct_file_hit_accepts_a_same_domain_video():
    # The real shape direct_file.py was built for (Palisade CO, Dundee
    # OR, Cayuga Heights NY -- see that module's own docstring): a bare
    # video file served straight from the government's own domain.
    assert direct_file_hit_is_plausible(
        "duboiswyoming.org",
        "https://www.duboiswyoming.org/files/Council_2026-08-01.mp4",
    )
    # Matches even with a www./bare-domain mismatch between the two sides.
    assert direct_file_hit_is_plausible(
        "www.duboiswyoming.org",
        "https://duboiswyoming.org/files/Council_2026-08-01.mp4",
    )


def test_direct_file_hit_accepts_known_file_sharing_hosts():
    # Real confirmed shapes from direct_file.py's own docstring: Kemmerer
    # city, WY (Google Drive) and Enterprise city, OR (Dropbox) both
    # legitimately host real meeting recordings off their own domain.
    assert direct_file_hit_is_plausible(
        "kemmererwy.gov", "https://drive.google.com/file/d/abc123/view"
    )
    assert direct_file_hit_is_plausible(
        "enterpriseor.gov",
        "https://www.dropbox.com/scl/fi/xyz/2025-09-09-City-Council-Recording.mp4",
    )


def test_direct_file_hit_rejects_an_unrelated_third_party_domain():
    assert not direct_file_hit_is_plausible(
        "calhouncountyfl.gov", "https://www.youtube.com/some-unrelated-file.mp4"
    )
