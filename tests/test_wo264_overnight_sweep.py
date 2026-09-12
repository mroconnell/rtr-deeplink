"""Fixture-backed coverage for WO-264's new pure parsing logic (domain-label
guessing, video-candidate scanning, and the vendor-tenant name/state check)
-- the ladder itself (`run_access_ladder`) is imported unchanged from
`scripts/wo147_access_ladder_sweep.py`, already covered by that module's own
tests, and not re-tested here per CLAUDE.md's "reuse, do not rewrite" rule.

All HTML/URL shapes below are synthetic (hand-written, not fetched from a
real page) -- per CLAUDE.md's synthetic-test rule, that's fine here because
each one exercises one specific parsing branch (a domain-label edge case, a
video-host match, a name/state text match) rather than standing in for a
real platform sample. The government/state names used are real, unambiguous
US places (Sparta, TN; Adams County, ID) -- not invented -- matching the
same rule's "facts must be real" half.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import scripts.wo264_overnight_sweep as wo264  # noqa: E402


def test_domain_label_bare_domain():
    assert wo264.domain_label("spartatn.gov") == "spartatn"


def test_domain_label_strips_www():
    assert wo264.domain_label("www.spartatn.gov") == "spartatn"


def test_domain_label_skips_generic_first_label():
    # Real shape from this WO's own population CSV: county governments
    # recorded under a `co.<name>.<state>.us` domain -- the bare first
    # label ("co") is never a usable DNS-guess label on its own.
    assert wo264.domain_label("co.adams.id.us") == "adams"


def test_domain_label_empty_input():
    assert wo264.domain_label("") == ""


def test_label_variants_includes_brief_shapes():
    variants = wo264.label_variants("hartleytx.gov", "TX")
    assert variants[0] == "hartleytx"
    assert "cityofhartleytx" in variants
    assert "townofhartleytx" in variants
    # base already ends with the state abbreviation -- no <label><st> variant
    assert "hartleytxtx" not in variants


def test_label_variants_no_domain_no_variants():
    assert wo264.label_variants("", "TX") == []


def test_label_variants_no_double_prefix():
    # Real, confirmed-live shape this population's own domains carry
    # (cityofiowafalls.com, townofmiddlebury.in.gov): the domain's own
    # label already starts with "cityof"/"townof" -- blindly prepending
    # it again produced a nonsense "cityofcityofiowafalls" guess before
    # this guard was added.
    variants = wo264.label_variants("cityofiowafalls.com", "IA")
    assert "cityofcityofiowafalls" not in variants
    assert variants[0] == "cityofiowafalls"
    assert "cityofiowafallsia" in variants


def test_find_video_candidates_matches_known_hosts():
    html = (
        '<a href="https://youtu.be/abc123XYZ">Watch the meeting</a>'
        '<a href="/agenda.pdf">Agenda</a>'
        '<iframe src="https://player.vimeo.com/video/555"></iframe>'
    )
    urls = wo264.find_video_candidates(html, "https://example.gov/meetings")
    assert "https://youtu.be/abc123XYZ" in urls
    assert "https://player.vimeo.com/video/555" in urls
    assert not any(u.endswith("agenda.pdf") for u in urls)


def test_find_video_candidates_matches_direct_file_extension():
    html = '<a href="/media/2026-09-01-council.mp4">Download video</a>'
    urls = wo264.find_video_candidates(html, "https://example.gov/meetings")
    assert urls == ["https://example.gov/media/2026-09-01-council.mp4"]


def test_find_video_candidates_none_found():
    html = "<a href='/agenda.pdf'>Agenda</a><a href='/minutes.pdf'>Minutes</a>"
    assert wo264.find_video_candidates(html, "https://example.gov/meetings") == []


def test_tenant_names_this_government_real_match():
    html = (
        "<html><body>Welcome to the City of Sparta, Tennessee "
        "official government site</body></html>"
    )
    reason = wo264._tenant_names_this_government(html, "Sparta city", "TN")
    assert reason is not None
    assert "sparta" in reason


def test_tenant_names_this_government_state_abbr_alone():
    html = "<html><body>Adams County, ID Board of Commissioners</body></html>"
    reason = wo264._tenant_names_this_government(html, "Adams County", "ID")
    assert reason is not None


def test_tenant_names_this_government_name_only_rejected():
    # Real false-positive shape this check guards against: a vendor demo
    # tenant that happens to share a name-word but names no matching
    # state anywhere on the page.
    html = "<html><body>Welcome to Sparta -- a generic demo site</body></html>"
    assert wo264._tenant_names_this_government(html, "Sparta city", "TN") is None


def test_tenant_names_this_government_state_only_rejected():
    html = "<html><body>Welcome to Tennessee's finest county fair</body></html>"
    assert wo264._tenant_names_this_government(html, "Sparta city", "TN") is None


def test_normalize_domain_strips_scheme_and_path():
    assert wo264.normalize_domain("https://www.foo.gov/bar?x=1") == "www.foo.gov"


def test_split_list_semicolon_delimited():
    assert wo264._split_list("vintoniowa.net; cityofvinton.org") == [
        "vintoniowa.net",
        "cityofvinton.org",
    ]


def test_split_list_blank():
    assert wo264._split_list("") == []
    assert wo264._split_list(None) == []


def test_vendor_cooloff_trips_after_six_consecutive_failures():
    cooloff = wo264.VendorCooloff()
    for _ in range(wo264.CONSECUTIVE_VENDOR_FAILURES_HALT - 1):
        cooloff.record("granicus", True)
        assert not cooloff.blocked("granicus")
    cooloff.record("granicus", True)
    assert cooloff.blocked("granicus")
    # a different vendor family is unaffected
    assert not cooloff.blocked("legistar")


def test_vendor_cooloff_resets_on_success():
    cooloff = wo264.VendorCooloff()
    for _ in range(wo264.CONSECUTIVE_VENDOR_FAILURES_HALT - 1):
        cooloff.record("legistar", True)
    cooloff.record("legistar", False)
    cooloff.record("legistar", True)
    assert not cooloff.blocked("legistar")


def test_build_domain_attempts_dedupes_and_caps():
    cand = {
        "domain": "https://spartatn.gov/",
        "hub_url": "",
        "alternate_domains": "spartatn.gov; spartatn.com; another.gov",
        "alternate_urls": "",
    }
    attempts = wo264._build_domain_attempts(cand)
    assert len(attempts) == wo264.MAX_DOMAIN_ATTEMPTS_PER_GOV
    domains = [a[0] for a in attempts]
    assert domains[0] == "spartatn.gov"
    assert domains.count("spartatn.gov") == 1
    assert attempts[0][1] is False
    assert all(a[1] is True for a in attempts[1:])


def test_build_domain_attempts_empty_domain_falls_back_to_alternate():
    cand = {
        "domain": "",
        "hub_url": "",
        "alternate_domains": "onlyalt.gov",
        "alternate_urls": "",
    }
    attempts = wo264._build_domain_attempts(cand)
    assert attempts == [("onlyalt.gov", True, "")]
