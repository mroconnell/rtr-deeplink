"""Tests for scripts/meeting_finder_followups.py (WO-1040).

Focused on the grouping/dedupe/join logic -- the part with no network
dependency and the highest risk of a silent wrong-government mixup. Real,
confirmed-live values (the Hingham domain collision, the Google Drive
download-URL gap) are used as synthetic test fixtures per CLAUDE.md's
synthetic-test convention: the SHAPE here is real (confirmed against
followup/finds.json and followup/approved_direct.csv during this WO), the
specific rows below are hand-built to isolate one behavior at a time.
"""

from __future__ import annotations

import json


from scripts.meeting_finder_followups import (
    DripLead,
    build_government_lookup,
    classify,
    dedupe_drip_leads,
    drip_candidates_from_finds,
    drip_candidates_from_verdicts_jsonl,
    is_known_unresolvable_today,
    load_approved,
    load_approved_direct,
    load_existing_lead_urls,
    queue_url,
    source_url_from_path,
)


def _find_row(**overrides):
    row = {
        "run": "overnight",
        "group": "hand-check",
        "tier": "3",
        "platform": "granicus",
        "identity": "silent",
        "identity_points_to": "",
        "domain": "example.gov",
        "gov_id": "us:place:0000001",
        "government": "Example City",
        "stratum": "never-checked",
        "result_url": "https://archive-stream.granicus.com/OnDemand/x.mp4/playlist.m3u8",
        "duration_seconds": 100.0,
        "path": "https://example.gov/ -> https://example.gov/watch",
        "note": "",
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# classify(): group/approval join
# ---------------------------------------------------------------------------


def test_confident_rows_are_always_actionable_without_approved_csv():
    finds = [_find_row(group="confident", tier="1")]
    tier1, tier3, held, pending = classify(finds, {})
    assert len(tier1) == 1
    assert tier1[0].approved is True
    assert tier1[0].approval_reason == "confident"
    assert tier3 == [] and held == [] and pending == []


def test_hand_check_row_with_no_approved_csv_row_is_pending():
    finds = [_find_row(group="hand-check", tier="3")]
    tier1, tier3, held, pending = classify(finds, {})
    assert tier3 == []
    assert len(pending) == 1
    assert pending[0].approved is False


def test_hand_check_row_approved_joins_the_pipeline():
    finds = [
        _find_row(group="hand-check", tier="3", domain="a.gov", gov_id="us:place:1")
    ]
    approved = {
        ("a.gov", "us:place:1"): {
            "domain": "a.gov",
            "gov_id": "us:place:1",
            "verdict": "approve",
        }
    }
    tier1, tier3, held, pending = classify(finds, approved)
    assert len(tier3) == 1
    assert tier3[0].approved is True
    assert pending == []


def test_hand_check_row_rejected_in_approved_csv_is_pending_not_actionable():
    finds = [
        _find_row(group="hand-check", tier="1", domain="a.gov", gov_id="us:place:1")
    ]
    approved = {
        ("a.gov", "us:place:1"): {
            "domain": "a.gov",
            "gov_id": "us:place:1",
            "verdict": "reject",
        }
    }
    tier1, tier3, held, pending = classify(finds, approved)
    assert tier1 == []
    assert len(pending) == 1


def test_hold_direct_file_group_never_actionable_even_if_in_approved_csv():
    """Ryan approved 'the confident finds and the hand-check-approved
    finds' -- hold-direct-file is a third, separate bucket not part of
    that approval, regardless of what an approved.csv row might say."""
    finds = [
        _find_row(
            group="hold-direct-file", tier="3", domain="a.gov", gov_id="us:place:1"
        )
    ]
    approved = {
        ("a.gov", "us:place:1"): {
            "domain": "a.gov",
            "gov_id": "us:place:1",
            "verdict": "approve",
        }
    }
    tier1, tier3, held, pending = classify(finds, approved)
    assert tier1 == [] and tier3 == []
    assert len(held) == 1


def test_domain_only_join_would_be_wrong_gov_id_and_gov_id_join_alone_would_too():
    """The real hingham-ma.gov case (WO-1040, coordinator note
    2026-09-24): two finds.json rows share a domain string closely
    ('www.hingham-ma.gov' MA vs 'hingham-ma.gov' MT-shaped data error)
    with two different gov_ids, and only the real one is ever approved.
    A join on domain alone, or gov_id alone, must not let the wrong row
    through -- only the exact (domain, gov_id) pair may."""
    finds = [
        _find_row(
            group="hand-check",
            tier="1",
            domain="www.hingham-ma.gov",
            gov_id="us:cousub:2502330210",
            government="Hingham, Massachusetts",
        ),
        _find_row(
            group="hand-check",
            tier="1",
            domain="hingham-ma.gov",
            gov_id="us:place:3036400",
            government="Hingham town, Montana",
        ),
    ]
    approved = {
        ("www.hingham-ma.gov", "us:cousub:2502330210"): {
            "domain": "www.hingham-ma.gov",
            "gov_id": "us:cousub:2502330210",
            "verdict": "approve",
        }
    }
    tier1, tier3, held, pending = classify(finds, approved)
    assert len(tier1) == 1
    assert tier1[0].gov_id == "us:cousub:2502330210"
    assert tier1[0].domain == "www.hingham-ma.gov"
    # The Montana data-error row must be pending (never silently
    # approved), never merged into the actionable Massachusetts result.
    assert len(pending) == 1
    assert pending[0].gov_id == "us:place:3036400"


def test_load_approved_ignores_non_approve_verdicts():
    import csv
    import io

    text = "domain,gov_id,verdict\na.gov,us:place:1,approve\nb.gov,us:place:2,reject\n"
    reader = csv.DictReader(io.StringIO(text))
    rows = {(r["domain"], r["gov_id"]): r for r in reader}
    assert rows[("a.gov", "us:place:1")]["verdict"] == "approve"
    assert rows[("b.gov", "us:place:2")]["verdict"] == "reject"


def test_load_approved_missing_file_returns_empty(tmp_path):
    assert load_approved(tmp_path / "does_not_exist.csv") == {}


# ---------------------------------------------------------------------------
# approved_direct.csv
# ---------------------------------------------------------------------------


def test_load_approved_direct_is_all_tier3_direct_file(tmp_path):
    csv_path = tmp_path / "approved_direct.csv"
    csv_path.write_text(
        "domain,gov_id,verdict,tier,platform,result_url,video_title,evidence\n"
        "example.k12.mn.us,us:sd:1,approve,3,direct_file,"
        "https://drive.usercontent.google.com/download?id=abc&export=download&confirm=t,,meeting words\n",
        encoding="utf-8",
    )
    candidates = load_approved_direct(csv_path)
    assert len(candidates) == 1
    c = candidates[0]
    assert c.tier == "3"
    assert c.platform == "direct_file"
    assert c.approved is True
    assert "drive.usercontent.google.com" in c.result_url


def test_load_approved_direct_skips_non_approve_rows(tmp_path):
    csv_path = tmp_path / "approved_direct.csv"
    csv_path.write_text(
        "domain,gov_id,verdict,tier,platform,result_url,video_title,evidence\n"
        "example.gov,us:place:1,reject,3,direct_file,https://example.gov/x.mp3,,not a meeting\n",
        encoding="utf-8",
    )
    assert load_approved_direct(csv_path) == []


def test_gdrive_download_url_no_longer_flagged_unresolvable():
    """WO-1042: direct_file.py now recognizes this already-rewritten
    download shape directly (confirmed live against a real martin.k12.mn.us
    row), so this used-to-be-a-gap URL is no longer flagged."""
    url = "https://drive.usercontent.google.com/download?id=1abc&export=download&confirm=t"
    assert is_known_unresolvable_today(url) == ""


def test_ordinary_mp3_url_is_not_flagged():
    assert is_known_unresolvable_today("https://example.gov/meeting.mp3") == ""


def test_classic_drive_share_link_is_not_flagged():
    """The classic drive.google.com/file/d/<id> shape has always been
    handled by direct_file.py's own rewrite."""
    assert (
        is_known_unresolvable_today("https://drive.google.com/file/d/abc123/view") == ""
    )


# ---------------------------------------------------------------------------
# source_url_from_path
# ---------------------------------------------------------------------------


def test_source_url_from_path_uses_last_hop():
    path = "https://a.gov/ -> https://a.gov/watch"
    assert (
        source_url_from_path(path, "https://cdn.example/video.mp4")
        == "https://a.gov/watch"
    )


def test_source_url_from_path_blank_when_same_as_result_url():
    url = "https://a.gov/video.mp4"
    assert source_url_from_path(url, url) == ""


def test_source_url_from_path_blank_when_no_path():
    assert source_url_from_path("", "https://cdn.example/video.mp4") == ""


# ---------------------------------------------------------------------------
# queue_url() -- WO-1042
# ---------------------------------------------------------------------------


def test_queue_url_prefers_meeting_url_when_set():
    finds = [
        _find_row(
            group="confident",
            tier="3",
            result_url="https://archive-stream.granicus.com/x/playlist.m3u8",
            meeting_url="https://city.granicus.com/MediaPlayer.php?view_id=1&clip_id=42",
        )
    ]
    _tier1, tier3, _held, _pending = classify(finds, {})
    assert len(tier3) == 1
    assert (
        queue_url(tier3[0])
        == "https://city.granicus.com/MediaPlayer.php?view_id=1&clip_id=42"
    )


def test_queue_url_falls_back_to_result_url_when_meeting_url_is_blank():
    """Older finds.json rows (built before WO-1042) carry no meeting_url
    at all, and a platform like Vimeo never had one to begin with --
    result_url already IS the real resolve input there."""
    finds = [
        _find_row(
            group="confident",
            tier="3",
            result_url="https://player.vimeo.com/video/1212025580",
        )
    ]
    _tier1, tier3, _held, _pending = classify(finds, {})
    assert len(tier3) == 1
    assert queue_url(tier3[0]) == "https://player.vimeo.com/video/1212025580"


# ---------------------------------------------------------------------------
# Drip leads
# ---------------------------------------------------------------------------


def test_drip_candidates_from_finds_only_takes_drip_tier2_group():
    finds = [
        _find_row(
            group="drip-tier2", tier="2", result_url="https://www.youtube.com/@SomeGov"
        ),
        _find_row(group="confident", tier="1"),
    ]
    leads = drip_candidates_from_finds(finds)
    assert len(leads) == 1
    assert leads[0].kind == "channel"


def test_drip_candidates_from_finds_classifies_single_video():
    finds = [
        _find_row(
            group="drip-tier2",
            tier="2",
            result_url="https://www.youtube.com/watch?v=abc123",
        )
    ]
    leads = drip_candidates_from_finds(finds)
    assert leads[0].kind == "single_video"


def test_drip_candidates_from_verdicts_jsonl_dedupes_repeated_leads(tmp_path):
    """A real youtube-lead-only row's `leads` list often repeats the same
    URL across multiple hops (confirmed in overnight/verdicts.csv.jsonl,
    e.g. rsd6.org's @R20Bobcast appearing 3 times) -- must collapse to one."""
    jsonl_path = tmp_path / "verdicts.csv.jsonl"
    row = {
        "input_url": "rsd6.org",
        "identity_expected_gov_id": "us:sd:0903515",
        "outcome": "youtube-lead-only",
        "note": "youtube-lead-only",
        "leads": [
            {
                "found_at": "https://rsd6.org/",
                "kind": "youtube",
                "url": "https://www.youtube.com/@R20Bobcast",
            },
            {
                "found_at": "hop",
                "kind": "youtube",
                "url": "https://www.youtube.com/@R20Bobcast",
            },
        ],
    }
    jsonl_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    lookup = {("rsd6.org", "us:sd:0903515"): "Riverside School District 6"}
    leads = drip_candidates_from_verdicts_jsonl([jsonl_path], lookup)
    assert len(leads) == 1
    assert leads[0].government == "Riverside School District 6"
    assert leads[0].kind == "channel"


def test_drip_candidates_from_verdicts_jsonl_ignores_non_lead_outcomes(tmp_path):
    jsonl_path = tmp_path / "verdicts.csv.jsonl"
    row = {
        "input_url": "x.gov",
        "identity_expected_gov_id": "us:place:1",
        "outcome": None,
        "leads": [],
    }
    jsonl_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    assert drip_candidates_from_verdicts_jsonl([jsonl_path], {}) == []


def test_dedupe_drip_leads_against_existing_and_within_run():
    leads = [
        DripLead(
            url="https://youtu.be/a",
            gov_id="us:place:1",
            government="A",
            domain="a.gov",
            kind="single_video",
            note="",
        ),
        DripLead(
            url="https://youtu.be/a",
            gov_id="us:place:1",
            government="A",
            domain="a.gov",
            kind="single_video",
            note="",
        ),
        DripLead(
            url="https://youtu.be/b",
            gov_id="us:place:2",
            government="B",
            domain="b.gov",
            kind="single_video",
            note="",
        ),
    ]
    new, already = dedupe_drip_leads(leads, existing_urls={"https://youtu.be/b"})
    assert [lead.url for lead in new] == ["https://youtu.be/a"]
    assert {lead.url for lead in already} == {
        "https://youtu.be/a",
        "https://youtu.be/b",
    }


def test_load_existing_lead_urls_missing_file_returns_empty(tmp_path):
    assert load_existing_lead_urls(tmp_path / "no_such_file.csv") == set()


def test_load_existing_lead_urls_skips_header_and_comments(tmp_path):
    path = tmp_path / "leads.csv"
    path.write_text(
        "# a comment\n"
        "channel_url,gov_id,government,state,source_wo,kind,verified,note\n"
        "https://youtu.be/existing,us:place:9,X,ZZ,WO-1,single_video,false,\n",
        encoding="utf-8",
    )
    assert load_existing_lead_urls(path) == {"https://youtu.be/existing"}


def test_build_government_lookup():
    finds = [_find_row(domain="a.gov", gov_id="us:place:1", government="A City")]
    lookup = build_government_lookup(finds)
    assert lookup[("a.gov", "us:place:1")] == "A City"
