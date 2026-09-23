"""Fixture-backed coverage for passive discovery v2's pure logic
(WO-282): sub-sitemap ranking, DNS-label handling, and phase-2's pure
scoring functions (`wo282_recon.hub_score`/`meeting_score`,
`wo282_classify.classify_record`/`dns_subdomain_candidates`). None of this
hits the network -- per CLAUDE.md's synthetic-test rule, that's the right
scope here: every real network path (DNS, sitemap/robots fetch, Wayback
CDX, Common Crawl, platform_fingerprints/detect_platform against a live
page) was verified by hand against real domains while building WO-273/
WO-282 (see docs/investigations/passive_discovery_full_scale.md), and only
the pure parsing/scoring branches are re-tested here to catch a future
regression.

WO-1019 (2026-09-23): this file replaces `test_wo273_passive_discovery.py`
now that WO-273's own scripts (`wo273_recon.py`/`wo273_classify.py`/
`wo273_targeted.py`) are retired -- their shared library logic (DNS/
archive/robots/sitemap/Wayback/Common-Crawl helpers, hub_score()/
meeting_score(), the fetch/scoring plumbing WO-282's own phase 3 reuses)
moved verbatim into `wo282_recon.py`/`wo282_targeted.py`, and every test
case that covered a moved function is kept here, updated to import the
WO-282 module instead. Three groups of the original file's tests are
deliberately NOT ported, because the code they tested was WO-273's own
CLI/orchestration logic, never imported by WO-282 or anything else, and
was retired along with wo273_*.py rather than moved (see WO-1019's
BACKLOG_DONE.md entry for the full reasoning):

  - `build_candidate_pool()`/`is_vendor_domain()` (wo273_recon.py's own
    jurisdiction_coverage.csv candidate-pool builder) -- WO-282's own
    population comes from a separate `wo282_population.csv`, built by a
    different process entirely, not this CLI.
  - `top_flagged_urls()`/`fetch_and_score()` (wo273_targeted.py's own
    per-kind best_hub_url/best_meeting_url ranking and fetch/confirm
    logic) -- superseded by `wo282_targeted.py`'s differently-shaped
    `process_with_candidates()`/`fetch_and_score_v2()`, which read a
    ranked `candidates_json` list from `wo282_classify.py` rather than
    per-kind best-url columns. `wo282_classify.classify_record()`'s own
    candidate-ranking behavior (including WO-273's #1275 DNS-subdomain
    addition) is covered directly below instead.
  - `wo273_classify.classify_record()`'s own confidence/best-url-column
    tests are replaced by `wo282_classify.classify_record()`'s
    equivalents, which use a single ranked `candidates_json` list instead
    of separate best_hub_url/best_meeting_url fields -- see the "#1275
    addendum" tests below, updated to read that shape.

Reject-reason strings and the flag-word lift numbers are the real, measured
values WO-273's brief and the conductor's state file specify (not
invented) -- see wo282_recon.py's own module-level comments for their
source.
"""

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import scripts.wo282_recon as wo282_recon  # noqa: E402
import scripts.wo282_classify as wo282_classify  # noqa: E402
import scripts.wo282_targeted as wo282_targeted  # noqa: E402


def test_rank_sub_sitemaps_prioritizes_pages_over_images():
    urls = [
        "https://example.gov/image-sitemap.xml",
        "https://example.gov/page-sitemap.xml",
        "https://example.gov/category-sitemap.xml",
        "https://example.gov/post-sitemap.xml",
    ]
    ranked = wo282_recon.rank_sub_sitemaps(urls)
    assert ranked[0] == "https://example.gov/page-sitemap.xml"
    assert ranked[1] == "https://example.gov/post-sitemap.xml"
    # De-prioritized (image/category) sort after every non-deprioritized entry.
    assert ranked[-1] in (
        "https://example.gov/image-sitemap.xml",
        "https://example.gov/category-sitemap.xml",
    )


def _meeting_path_regex_matches(url: str) -> bool:
    return bool(re.match(wo282_recon.MEETING_PATH_REGEX, url))


# WO-366 (2026-09-14): real URL examples for each of the six tokens Ryan
# asked to add to MEETING_PATH_REGEX (civicmedia | vod | event | stream |
# live | show). Every URL here is real, not invented -- see
# scripts/wo282_recon.py's own MEETING_PATH_REGEX comment for where each
# one is documented elsewhere in this repo. The "live" case uses a real,
# confirmed URL SHAPE (app/platforms/municode_meetings.py's Fair Oaks
# Ranch TX example, app/platforms/openmedia.py's Santa Barbara example)
# with a placeholder video id, since neither file records a concrete real
# id -- the regex under test only cares about the path token, not the id.
def test_meeting_path_regex_matches_civicmedia_token():
    # Hobart, IN's real CivicMedia page (app/platforms/civicmedia.py,
    # confirmed live 2026-09-13). Mixed case on purpose -- this is also
    # what motivated the regex's (?i) prefix (see its own comment).
    assert _meeting_path_regex_matches(
        "https://www.cityofhobart.org/CivicMedia?VID=326"
    )


def test_meeting_path_regex_matches_vod_token():
    # Castus's real vod URL shape (app/platforms/castus.py).
    assert _meeting_path_regex_matches(
        "https://cloud.castus.tv/vod/comm7tv/video/6a83b3f9d94c83000226f83d"
    )


def test_meeting_path_regex_matches_event_token():
    # ChampDS's real event URL shape (app/platforms/champds.py).
    assert _meeting_path_regex_matches("https://play.champds.com/atlantaga/event/1227")


def test_meeting_path_regex_matches_stream_token():
    # Granicus's own real CDN host, seen live in an ingested Yountville,
    # CA page's video_url (research/hub_sweep_wo126_export_pages.json).
    assert _meeting_path_regex_matches(
        "https://archive-stream.granicus.com/OnDemand/_definst_/"
        "mp4:swagitVideo/yountvilleca/5294f2f1-6b21-4b25-bea8-085e571bf3c9.mp4"
        "/playlist.m3u8"
    )


def test_meeting_path_regex_matches_live_token():
    # Real URL SHAPE confirmed for Fair Oaks Ranch, TX and Santa Barbara,
    # CA (see the module comment above) -- video id is a placeholder.
    assert _meeting_path_regex_matches(
        "https://www.youtube.com/live/dQw4w9WgXcQ?si=abc"
    )


def test_meeting_path_regex_matches_show_token_lincoln_internetchannel():
    # Lincoln, NE's own self-hosted Cablecast-template page (real, from
    # jurisdiction_coverage.csv's example_meeting_url for Lincoln city,
    # Nebraska).
    assert _meeting_path_regex_matches(
        "http://lnktv.lincoln.ne.gov/internetchannel/show/4442?channel=1"
    )


def test_meeting_path_regex_matches_show_token_cablecast_bare_show():
    # Cablecast's newer bare /show/{id} template, without the older
    # /internetchannel prefix (real, see README.md's Cablecast row and
    # BACKLOG.md's pgcps.cablecast.tv/show/3178 mention).
    assert _meeting_path_regex_matches("https://pgcps.cablecast.tv/show/3178")


def test_meeting_path_regex_still_matches_original_tokens():
    # The original token set (agenda/minutes/meeting/council/commission/
    # board/video/clip/player/watch) must still match after the widen --
    # this isn't a narrowing change.
    assert _meeting_path_regex_matches("https://example.gov/AgendaCenter")
    assert _meeting_path_regex_matches("https://example.gov/MediaPlayer.php?view_id=5")


def test_hub_score_scores_agendacenter_highest():
    # AgendaCenter is CivicPlus's own path shape and the single highest
    # measured hub-vocabulary lift (538, conductor_state.md "HUB LIFT").
    url = "https://example.gov/AgendaCenter"
    assert wo282_recon.hub_score(url) == 538.0


def test_hub_score_zero_for_dropped_noise_words():
    # "agenda" (singular), "calendar" and "government" are deliberately
    # excluded as near-noise flag words per the FLAG-WORD LIFT analysis.
    url = "https://example.gov/government/calendar/agenda"
    assert wo282_recon.hub_score(url) == 0.0


def test_hub_score_matches_bigram_of_commissioners():
    # "of-commissioners" bigram: 304x lift, the strongest bigram measured.
    url = "https://example.gov/board-of-commissioners/index"
    assert wo282_recon.hub_score(url) == 304.0


def test_meeting_score_scores_vendor_shape_token():
    url = "https://example.gov/MediaPlayer.php?view_id=5"
    assert wo282_recon.meeting_score(url) > 0


def test_classify_record_finds_vendor_host_platform():
    rec = {
        "domain": "example.gov",
        "state": "Ohio",
        "sitemap_urls": ["https://cityoftest.granicus.com/ViewPublisher.php?view_id=1"],
        "wayback_index": {"top_urls": []},
        "common_crawl": {"urls": []},
        "dns": {},
    }
    result = wo282_classify.classify_record(rec)
    assert result["platform"] == "granicus"
    assert result["confidence"] == "high"


def test_classify_record_none_when_nothing_flagged():
    rec = {
        "domain": "example.gov",
        "state": "Ohio",
        "sitemap_urls": ["https://example.gov/about-us", "https://example.gov/parks"],
        "wayback_index": {"top_urls": []},
        "common_crawl": {"urls": []},
        "dns": {},
    }
    result = wo282_classify.classify_record(rec)
    assert result["platform"] == ""
    assert result["confidence"] == "none"


def test_name_matches_requires_both_city_and_state():
    html = "<html><body>Welcome to the City of Sparta, Tennessee</body></html>"
    assert wo282_targeted.name_matches(html, "Sparta", "Tennessee")
    assert not wo282_targeted.name_matches(html, "Sparta", "Ohio")
    assert not wo282_targeted.name_matches(
        "<html>nothing here</html>", "Sparta", "Tennessee"
    )


# --- WO-278: the confirmation-rule correction --------------------------
#
# WO-273's original rule let a platform "confirm" purely because the URL
# THIS SCRIPT constructed (a guessed first-party-path template) matched
# its own path shape -- real, live-confirmed on 76 of 147 originally
# "confirmed" domains (e.g. marengocountyal.com "confirmed" hyland, iqm2
# AND civicweb off the same four-path probe; a real site runs one
# platform). These tests cover the fix's pure logic, moved into
# wo282_targeted.py verbatim (WO-1019): the catch-all body comparison and
# the same-domain check. (`fetch_and_score()`'s own source_kind-gated
# trust logic was WO-273-specific orchestration, not moved -- see this
# file's module docstring; wo282_targeted.py's `fetch_and_score_v2()`
# implements the equivalent catch-all-vs-confirmation gate its own way,
# via `catchall_signature()`/`is_catchall_match()`.)


def test_is_catch_all_response_true_on_size_match_to_reference():
    # Geneva County, AL's real, live-confirmed shape (url_shape_mining.md):
    # four different probed paths, same ~500-byte generic page every time.
    body = b"x" * 500
    refs = {"nonsense": (498, "deadbeef"), "homepage": None}
    assert wo282_targeted.is_catch_all_response(body, refs)


def test_is_catch_all_response_false_when_clearly_different_size():
    body = b"x" * 20000
    refs = {"nonsense": (500, "deadbeef"), "homepage": (510, "beefdead")}
    assert not wo282_targeted.is_catch_all_response(body, refs)


def test_is_catch_all_response_false_with_no_usable_reference():
    # A reference fetch failure records None -- the guard fails open
    # rather than blocking confirmation on a transient error.
    assert not wo282_targeted.is_catch_all_response(b"x" * 500, {"nonsense": None})


def test_is_same_domain_true_for_exact_and_subdomain():
    assert wo282_targeted.is_same_domain("marengocountyal.com", "marengocountyal.com")
    assert wo282_targeted.is_same_domain(
        "www.marengocountyal.com", "marengocountyal.com"
    )


def test_is_same_domain_false_for_a_different_vendor_host():
    assert not wo282_targeted.is_same_domain(
        "exampleville-ca.granicus.com", "exampleville.ca.gov"
    )


# --- registrable_label / label_is_guessable (WO-324's qc.primegov.com bug) ---
# Real domains from research/passive_neither_5-canada-ladder-only.csv and
# WO-324's report: a *.qc.ca government used to guess the label "qc", and
# qc.primegov.com genuinely resolves to PrimeGov's regional landing page.


def test_registrable_label_skips_canadian_province_suffix():
    assert wo282_recon.registrable_label("www.ville.sthonore.qc.ca") == "sthonore"
    assert wo282_recon.registrable_label("ville.sthonore.qc.ca") == "sthonore"
    assert wo282_recon.registrable_label("www.saint-lambert.ca") == "saint-lambert"
    assert wo282_recon.registrable_label("www.tweed.ca") == "tweed"
    assert wo282_recon.registrable_label("www.claresholm.ab.ca") == "claresholm"


def test_registrable_label_keeps_us_state_suffix_rule():
    assert wo282_recon.registrable_label("www.ci.buffalo.mn.us") == "buffalo"
    assert wo282_recon.registrable_label("baldwincountyal.gov") == "baldwincountyal"
    assert (
        wo282_recon.registrable_label("lincoln.ne.gov") == "ne"
    )  # unchanged: .gov is single-level


def test_label_is_guessable_rejects_province_codes_and_short_labels():
    assert not wo282_recon.label_is_guessable("qc")
    assert not wo282_recon.label_is_guessable("on")
    assert not wo282_recon.label_is_guessable("ab")
    assert not wo282_recon.label_is_guessable("x")
    assert wo282_recon.label_is_guessable("sthonore")
    assert wo282_recon.label_is_guessable("saint-lambert")


def test_dns_lookup_never_guesses_a_vendor_tenant_from_a_province_code(monkeypatch):
    # dig() is stubbed: any vendor-label host resolves (as qc.primegov.com
    # really does), but a *.qc.ca government must never reach that lookup.
    asked = []

    def fake_dig(rtype, host):
        asked.append(host)
        return ["203.0.113.1"] if rtype == "A" else []

    monkeypatch.setattr(wo282_recon, "dig", fake_dig)
    out = wo282_recon.dns_lookup("ville.sthonore.qc.ca")
    vendor_hosts = [d["host"] for d in out["resolving_vendor_labels"]]
    assert "qc.primegov.com" not in asked
    assert "sthonore.primegov.com" in asked
    assert all(not h.startswith("qc.") for h in vendor_hosts)


def test_registrable_label_steps_past_generic_us_infixes():
    # *.k12.xx.us, ci.x.xx.us, co.x.xx.us, www.x.xx.us shapes from the research file
    assert wo282_recon.registrable_label("www.somerset.k12.pa.us") == "somerset"
    assert wo282_recon.registrable_label("district.k12.wi.us") == "district"
    assert wo282_recon.registrable_label("ci.kelso.wa.us") == "kelso"
    assert wo282_recon.registrable_label("www.co.lake.il.us") == "lake"
    assert wo282_recon.registrable_label("co.lake.il.us") == "lake"
    assert wo282_recon.registrable_label("www.ci.buffalo.mn.us") == "buffalo"
    assert not wo282_recon.label_is_guessable("k12")
    assert not wo282_recon.label_is_guessable("www")


def test_wo268_copy_agrees_with_wo282_on_every_shape():
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
        assert wo268.registrable_label(d) == wo282_recon.registrable_label(d), d


# --- WO-273 addendum, PR #1275 (2026-09-21): A-record-only guessed
# subdomains (live.pomonaca.gov). Ported here against
# wo282_classify.classify_record() with the #1275 rule folded in as a
# candidate-building step (WO-1019, 2026-09-23) -- see
# wo282_classify.py's own "WO-273 addendum" comment for why the
# candidates_json shape (a single ranked list) replaces WO-273's
# separate best_hub_url/best_meeting_url/meeting_method fields.


def _dns_rec(*subs):
    return {
        "domain": "pomonaca.gov",
        "dns": {
            "resolving_subdomains": [
                {
                    "subdomain": label,
                    "host": f"{label}.pomonaca.gov",
                    "cname": "",
                    "a": ["47.176.139.71"],
                    "family": "",
                    "likely_own_domain_wildcard": wild,
                }
                for label, wild in subs
            ]
        },
    }


def test_a_record_only_video_subdomain_becomes_meeting_candidate():
    row = wo282_classify.classify_record(_dns_rec(("live", False)))
    candidates = json.loads(row["candidates_json"])
    assert candidates[0]["url"] == "https://live.pomonaca.gov/"
    assert candidates[0]["source"] == "dns-subdomain"
    assert candidates[0]["kind"] == "meeting-detail"
    assert row["confidence"] == "medium"
    assert row["platform"] == ""


def test_meetings_style_subdomain_becomes_hub_candidate():
    row = wo282_classify.classify_record(_dns_rec(("meetings", False)))
    candidates = json.loads(row["candidates_json"])
    assert candidates[0]["url"] == "https://meetings.pomonaca.gov/"
    assert candidates[0]["source"] == "dns-subdomain"
    assert candidates[0]["kind"] == "hub"
    assert row["confidence"] == "medium"


def test_own_domain_wildcard_subdomain_is_ignored():
    row = wo282_classify.classify_record(_dns_rec(("live", True)))
    assert row["candidates_json"] == "[]"
    assert row["confidence"] == "none"


def test_real_url_outscores_dns_subdomain_candidate():
    rec = _dns_rec(("live", False))
    rec["sitemap_urls"] = ["https://pomonaca.gov/mediaplayer.php?clip=1"]
    row = wo282_classify.classify_record(rec)
    candidates = json.loads(row["candidates_json"])
    # The real sitemap URL and the DNS-subdomain guess score a tie under
    # this file's own medium-confidence floor (20.0 each here) -- the
    # real, independently-found URL ranks first because all_candidates is
    # built from sitemap/Wayback/homepage URLs before DNS-subdomain
    # candidates are added, and ranking is a stable sort (see
    # wo282_classify.py's own "#1275 addendum" comment).
    assert candidates[0]["url"] == "https://pomonaca.gov/mediaplayer.php?clip=1"
    assert candidates[0]["source"] == "sitemap"
