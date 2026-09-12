"""Fixture-backed coverage for WO-273's pure logic: the candidate-pool
filter (`wo273_recon.build_candidate_pool`/`is_vendor_domain`), sub-sitemap
ranking, and phase-2/phase-3's pure scoring functions
(`wo273_classify.hub_score`/`meeting_score`, `wo273_targeted.
top_flagged_urls`/`name_matches`). None of this hits the network -- per
CLAUDE.md's synthetic-test rule, that's the right scope here: every real
network path (DNS, sitemap/robots fetch, Wayback CDX, Common Crawl,
platform_fingerprints/detect_platform against a live page) was verified by
hand against real domains while building this WO (see
docs/investigations/passive_discovery_full_scale.md), and only the pure
parsing/scoring branches are re-tested here to catch a future regression.

Reject-reason strings and the flag-word lift numbers are the real, measured
values this WO's brief and the conductor's state file specify (not
invented) -- see wo273_recon.py's own module-level comments for their
source.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import scripts.wo273_recon as wo273_recon  # noqa: E402
import scripts.wo273_classify as wo273_classify  # noqa: E402
import scripts.wo273_targeted as wo273_targeted  # noqa: E402


def _row(**overrides):
    base = {
        "country": "United States",
        "population_estimate": "12000",
        "domain": "example-gov.gov",
        "transcribed": "",
        "suspected_calendar_provider": "",
        "suspected_meeting_link_provider": "",
        "suspected_video_provider": "",
        "reject_reason": "no-platform-link-found",
    }
    base.update(overrides)
    return base


def test_build_candidate_pool_includes_nothing_found_row():
    pool, stats = wo273_recon.build_candidate_pool([_row()])
    assert len(pool) == 1
    assert stats["by_reason"] == {"no-platform-link-found": 1}


def test_build_candidate_pool_excludes_under_population_floor():
    pool, _ = wo273_recon.build_candidate_pool([_row(population_estimate="4999")])
    assert pool == []


def test_build_candidate_pool_excludes_already_transcribed():
    pool, _ = wo273_recon.build_candidate_pool([_row(transcribed="true")])
    assert pool == []


def test_build_candidate_pool_excludes_row_with_suspected_platform():
    pool, _ = wo273_recon.build_candidate_pool(
        [_row(suspected_meeting_link_provider="granicus")]
    )
    assert pool == []


def test_build_candidate_pool_excludes_reject_reason_outside_family():
    # "meeting-without-video" is a real §23 reject reason, but not in the
    # "nothing found" family this WO's brief scopes to.
    pool, _ = wo273_recon.build_candidate_pool(
        [_row(reject_reason="meeting-without-video")]
    )
    assert pool == []


def test_build_candidate_pool_excludes_vendor_host_domain():
    # A row whose OWN `domain` column is a meeting-platform host: the
    # platform IS the hostname, nothing to discover passively (this WO's
    # brief's population filter).
    pool, stats = wo273_recon.build_candidate_pool(
        [_row(domain="some-tenant.granicus.com")]
    )
    assert pool == []
    assert stats["vendor_excluded"] == 1


def test_is_vendor_domain_true_for_known_vendor_substring():
    assert wo273_recon.is_vendor_domain("pub-peelregion.escribemeetings.com")


def test_is_vendor_domain_false_for_ordinary_government_domain():
    # A real, unambiguous US city domain -- not a vendor host.
    assert not wo273_recon.is_vendor_domain("cityofpaloalto.org")


def test_rank_sub_sitemaps_prioritizes_pages_over_images():
    urls = [
        "https://example.gov/image-sitemap.xml",
        "https://example.gov/page-sitemap.xml",
        "https://example.gov/category-sitemap.xml",
        "https://example.gov/post-sitemap.xml",
    ]
    ranked = wo273_recon.rank_sub_sitemaps(urls)
    assert ranked[0] == "https://example.gov/page-sitemap.xml"
    assert ranked[1] == "https://example.gov/post-sitemap.xml"
    # De-prioritized (image/category) sort after every non-deprioritized entry.
    assert ranked[-1] in (
        "https://example.gov/image-sitemap.xml",
        "https://example.gov/category-sitemap.xml",
    )


def test_hub_score_scores_agendacenter_highest():
    # AgendaCenter is CivicPlus's own path shape and the single highest
    # measured hub-vocabulary lift (538, conductor_state.md "HUB LIFT").
    url = "https://example.gov/AgendaCenter"
    assert wo273_classify.hub_score(url) == 538.0


def test_hub_score_zero_for_dropped_noise_words():
    # "agenda" (singular), "calendar" and "government" are deliberately
    # excluded as near-noise flag words per the FLAG-WORD LIFT analysis.
    url = "https://example.gov/government/calendar/agenda"
    assert wo273_classify.hub_score(url) == 0.0


def test_hub_score_matches_bigram_of_commissioners():
    # "of-commissioners" bigram: 304x lift, the strongest bigram measured.
    url = "https://example.gov/board-of-commissioners/index"
    assert wo273_classify.hub_score(url) == 304.0


def test_meeting_score_scores_vendor_shape_token():
    url = "https://example.gov/MediaPlayer.php?view_id=5"
    assert wo273_classify.meeting_score(url) > 0


def test_classify_record_finds_vendor_host_platform():
    rec = {
        "domain": "example.gov",
        "state": "Ohio",
        "sitemap_urls": ["https://cityoftest.granicus.com/ViewPublisher.php?view_id=1"],
        "wayback_index": {"narrow_urls": []},
        "common_crawl": {"urls": []},
        "dns": {},
    }
    result = wo273_classify.classify_record(rec)
    assert result["platform"] == "granicus"
    assert result["confidence"] == "high"


def test_classify_record_none_when_nothing_flagged():
    rec = {
        "domain": "example.gov",
        "state": "Ohio",
        "sitemap_urls": ["https://example.gov/about-us", "https://example.gov/parks"],
        "wayback_index": {"narrow_urls": []},
        "common_crawl": {"urls": []},
        "dns": {},
    }
    result = wo273_classify.classify_record(rec)
    assert result["platform"] == ""
    assert result["confidence"] == "none"


def test_top_flagged_urls_ranks_platform_above_hub_and_meeting():
    row = {
        "platform": "civicplus",
        "platform_evidence_url": "https://example.gov/AgendaCenter",
        "hub_score": "22",
        "best_hub_url": "https://example.gov/agendas",
        "meeting_score": "8",
        "best_meeting_url": "https://example.gov/watch/5",
    }
    ranked = wo273_targeted.top_flagged_urls(row)
    assert ranked[0][0] == "https://example.gov/AgendaCenter"
    assert ranked[0][2] == "platform"
    assert len(ranked) == 3


def test_top_flagged_urls_empty_when_nothing_scored():
    row = {"platform": "", "hub_score": "0", "meeting_score": "0"}
    assert wo273_targeted.top_flagged_urls(row) == []


def test_name_matches_requires_both_city_and_state():
    html = "<html><body>Welcome to the City of Sparta, Tennessee</body></html>"
    assert wo273_targeted.name_matches(html, "Sparta", "Tennessee")
    assert not wo273_targeted.name_matches(html, "Sparta", "Ohio")
    assert not wo273_targeted.name_matches(
        "<html>nothing here</html>", "Sparta", "Tennessee"
    )
