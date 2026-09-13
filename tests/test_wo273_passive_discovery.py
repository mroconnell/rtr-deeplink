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


# --- WO-278: the confirmation-rule correction --------------------------
#
# WO-273's original rule let a platform "confirm" purely because the URL
# THIS SCRIPT constructed (a guessed first-party-path template) matched
# its own path shape -- real, live-confirmed on 76 of 147 originally
# "confirmed" domains (e.g. marengocountyal.com "confirmed" hyland, iqm2
# AND civicweb off the same four-path probe; a real site runs one
# platform). These tests cover the fix's pure logic: the catch-all body
# comparison, the same-domain check, and fetch_and_score()'s
# source_kind-gated trust of a matched URL's own text.


def test_is_catch_all_response_true_on_size_match_to_reference():
    # Geneva County, AL's real, live-confirmed shape (url_shape_mining.md):
    # four different probed paths, same ~500-byte generic page every time.
    body = b"x" * 500
    refs = {"nonsense": (498, "deadbeef"), "homepage": None}
    assert wo273_targeted.is_catch_all_response(body, refs)


def test_is_catch_all_response_false_when_clearly_different_size():
    body = b"x" * 20000
    refs = {"nonsense": (500, "deadbeef"), "homepage": (510, "beefdead")}
    assert not wo273_targeted.is_catch_all_response(body, refs)


def test_is_catch_all_response_false_with_no_usable_reference():
    # A reference fetch failure records None -- the guard fails open
    # rather than blocking confirmation on a transient error.
    assert not wo273_targeted.is_catch_all_response(b"x" * 500, {"nonsense": None})


def test_is_same_domain_true_for_exact_and_subdomain():
    assert wo273_targeted.is_same_domain("marengocountyal.com", "marengocountyal.com")
    assert wo273_targeted.is_same_domain(
        "www.marengocountyal.com", "marengocountyal.com"
    )


def test_is_same_domain_false_for_a_different_vendor_host():
    assert not wo273_targeted.is_same_domain(
        "exampleville-ca.granicus.com", "exampleville.ca.gov"
    )


def test_fetch_and_score_first_party_probe_never_confirms_from_url_text_alone(
    monkeypatch,
):
    # The exact bug: a catch-all answers a guessed AgendaOnline path with
    # its own generic shell (which names the government, is >=800 bytes,
    # but never says "agendaonline"/"viewmeeting" anywhere) -- must not
    # confirm hyland just because the URL we ourselves built has that path
    # shape.
    catch_all_body = (
        "<html><body>Welcome to Example County, Alabama</body></html>" + "filler " * 200
    )

    class FakeResp:
        def __init__(self, status_code, text, url):
            self.status_code = status_code
            self.text = text
            self.content = text.encode("utf-8")
            self.url = url

    def fake_polite_fetch(url, method="GET"):
        return FakeResp(200, catch_all_body, url)

    monkeypatch.setattr(wo273_targeted, "polite_fetch", fake_polite_fetch)
    monkeypatch.setattr(
        wo273_targeted, "try_wayback_archived_body", lambda url: (None, False)
    )

    refs = wo273_targeted.fetch_domain_reference("examplecounty.al.us")
    result = wo273_targeted.fetch_and_score(
        "https://examplecounty.al.us/AgendaOnline/Meetings/ViewMeeting",
        "Example County",
        "Alabama",
        "examplecounty.al.us",
        refs,
        "first_party_probe",
    )
    assert result["platform_confirmed"] == ""
    assert result["catch_all"] is True


def test_fetch_and_score_hub_sourced_url_still_confirms_via_its_own_shape(
    monkeypatch,
):
    # A phase-2 "hub" URL (independently found in a real sitemap, not
    # guessed by this script) is the pattern docs/investigations/
    # platform_fingerprints.md says IS valid confirmation -- unaffected by
    # this WO's fix.
    granicus_body = (
        "<html><body>City of Example, California -- Council Meeting"
        + "agenda " * 200
        + "</body></html>"
    )
    homepage_body = "<html><body>Exampleville homepage</body></html>"

    class FakeResp:
        def __init__(self, status_code, text, url):
            self.status_code = status_code
            self.text = text
            self.content = text.encode("utf-8")
            self.url = url

    def fake_polite_fetch(url, method="GET"):
        if "rtr-probe-" in url or url.rstrip("/").endswith(".gov"):
            return FakeResp(200, homepage_body, url)
        return FakeResp(200, granicus_body, url)

    monkeypatch.setattr(wo273_targeted, "polite_fetch", fake_polite_fetch)
    monkeypatch.setattr(
        wo273_targeted, "try_wayback_archived_body", lambda url: (None, False)
    )

    refs = wo273_targeted.fetch_domain_reference("exampleville.ca.gov")
    result = wo273_targeted.fetch_and_score(
        "https://exampleville-ca.granicus.com/player/clip/42",
        "Example",
        "California",
        "exampleville.ca.gov",
        refs,
        "hub",
    )
    assert result["platform_confirmed"] == "granicus"
    assert result["catch_all"] is False


# --- registrable_label / label_is_guessable (WO-324's qc.primegov.com bug) ---
# Real domains from research/passive_neither_5-canada-ladder-only.csv and
# WO-324's report: a *.qc.ca government used to guess the label "qc", and
# qc.primegov.com genuinely resolves to PrimeGov's regional landing page.


def test_registrable_label_skips_canadian_province_suffix():
    assert wo273_recon.registrable_label("www.ville.sthonore.qc.ca") == "sthonore"
    assert wo273_recon.registrable_label("ville.sthonore.qc.ca") == "sthonore"
    assert wo273_recon.registrable_label("www.saint-lambert.ca") == "saint-lambert"
    assert wo273_recon.registrable_label("www.tweed.ca") == "tweed"
    assert wo273_recon.registrable_label("www.claresholm.ab.ca") == "claresholm"


def test_registrable_label_keeps_us_state_suffix_rule():
    assert wo273_recon.registrable_label("www.ci.buffalo.mn.us") == "buffalo"
    assert wo273_recon.registrable_label("baldwincountyal.gov") == "baldwincountyal"
    assert (
        wo273_recon.registrable_label("lincoln.ne.gov") == "ne"
    )  # unchanged: .gov is single-level


def test_label_is_guessable_rejects_province_codes_and_short_labels():
    assert not wo273_recon.label_is_guessable("qc")
    assert not wo273_recon.label_is_guessable("on")
    assert not wo273_recon.label_is_guessable("ab")
    assert not wo273_recon.label_is_guessable("x")
    assert wo273_recon.label_is_guessable("sthonore")
    assert wo273_recon.label_is_guessable("saint-lambert")


def test_dns_lookup_never_guesses_a_vendor_tenant_from_a_province_code(monkeypatch):
    # dig() is stubbed: any vendor-label host resolves (as qc.primegov.com
    # really does), but a *.qc.ca government must never reach that lookup.
    asked = []

    def fake_dig(rtype, host):
        asked.append(host)
        return ["203.0.113.1"] if rtype == "A" else []

    monkeypatch.setattr(wo273_recon, "dig", fake_dig)
    out = wo273_recon.dns_lookup("ville.sthonore.qc.ca")
    vendor_hosts = [d["host"] for d in out["resolving_vendor_labels"]]
    assert "qc.primegov.com" not in asked
    assert "sthonore.primegov.com" in asked
    assert all(not h.startswith("qc.") for h in vendor_hosts)


def test_registrable_label_steps_past_generic_us_infixes():
    # *.k12.xx.us, ci.x.xx.us, co.x.xx.us, www.x.xx.us shapes from the research file
    assert wo273_recon.registrable_label("www.somerset.k12.pa.us") == "somerset"
    assert wo273_recon.registrable_label("district.k12.wi.us") == "district"
    assert wo273_recon.registrable_label("ci.kelso.wa.us") == "kelso"
    assert wo273_recon.registrable_label("www.co.lake.il.us") == "lake"
    assert wo273_recon.registrable_label("co.lake.il.us") == "lake"
    assert wo273_recon.registrable_label("www.ci.buffalo.mn.us") == "buffalo"
    assert not wo273_recon.label_is_guessable("k12")
    assert not wo273_recon.label_is_guessable("www")


def test_wo268_copy_agrees_with_wo273_on_every_shape():
    import scripts.wo268_passive_discovery as wo268

    for d in (
        "www.ville.sthonore.qc.ca",
        "www.saint-lambert.ca",
        "www.claresholm.ab.ca",
        "www.somerset.k12.pa.us",
        "ci.kelso.wa.us",
        "www.co.lake.il.us",
        "www.ci.buffalo.mn.us",
        "baldwincountyal.gov",
        "lincoln.ne.gov",
    ):
        assert wo268.registrable_label(d) == wo273_recon.registrable_label(d), d
