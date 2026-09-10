"""WO-154 (2026-09-10): fixture-backed coverage for scripts/cms_fingerprint.py.

Every fixture here is a real, raw-saved government page (see
tests/fixtures/cms_fingerprint/README.md for the source URL and date of
each). These are regression tests, not the "test against a real URL
first" step itself -- that live-testing already happened while building
the module (see scripts/cms_fingerprint.py's own rule comments and
~/Documents/rtr-business/research/wo154_methods_section.md for the full
evidence trail); these tests exist to catch a previously-confirmed
family silently breaking between sessions, the same role every other
platform's fixture suite already plays in this repo.
"""

from app.platforms import base
from scripts.cms_fingerprint import classify

from conftest import load_fixture


def _fixture(name: str) -> str:
    return load_fixture("cms_fingerprint", name)


def test_civicplus_footer_badge():
    html = _fixture("civicplus_eugene_or_agendacenter.html")
    result = classify(html, url="https://www.eugene-or.gov/AgendaCenter")
    assert result.family == "civicplus"
    assert result.rule_id == "civicplus-footer-badge"


def test_revize_cdn_asset():
    html = _fixture("revize_huron_sd_agendas_minutes.html")
    result = classify(
        html, url="https://cityofhuron.org/government/city_council/agendas_minutes.php"
    )
    assert result.family == "revize"
    assert "revize.com" in result.evidence


def test_opencities_generator_meta():
    html = _fixture("opencities_san_fernando_ca_home.html")
    result = classify(html, url="https://www.sanfernando.gov/Home")
    assert result.family == "opencities"
    assert "opencities" in result.evidence.lower()


def test_municode_web_meetings_link():
    html = _fixture("municode_web_kaukauna_wi_home.html")
    result = classify(html, url="https://kaukauna.gov")
    assert result.family == "municode_web"
    assert "municodemeetings.com" in result.evidence


def test_townweb_cdn_host():
    html = _fixture("townweb_glen_cove_ny_livestream.html")
    result = classify(
        html, url="https://glencoveny.gov/city-council-meeting-livestream"
    )
    assert result.family == "townweb"
    assert result.rule_id == "townweb-cdn-host"


def test_civiclive_asset_host_without_civiclive_domain():
    """Lynn, MA's own domain (lynnma.gov) carries no civiclive signature at
    all -- only the page's own asset host does. Confirms the family is
    detectable from content alone, not just the `*.hosted[2].civiclive.com`
    domain shape `detect_platform()` already checks."""
    html = _fixture("civiclive_lynn_ma_home.html")
    result = classify(html, url="https://www.lynnma.gov/")
    assert result.family == "civiclive"
    assert "civiclive.com" in result.evidence


def test_proudcity_known_domain_and_content_marker_agree():
    html = _fixture("proudcity_fairfax_ca_home.html")
    result = classify(html, url="https://townoffairfaxca.gov/")
    assert result.family == "proudcity"
    # The domain-list rule fires first (see RULES order) -- confirm the
    # content-only marker independently agrees when the domain check is
    # bypassed, so the family isn't only detectable via the curated list.
    from scripts.cms_fingerprint import _rule_proudcity

    content_only = _rule_proudcity(
        html, html.lower(), "", "https://townoffairfaxca.gov/"
    )
    assert content_only is not None
    assert content_only.family == "proudcity"


def test_unknown_when_no_rule_matches():
    result = classify(
        "<html><body>Just a plain page with nothing special.</body></html>"
    )
    assert result.family == "unknown"
    assert result.rule_id == "no-rule-matched"


def test_wo163_vendor_badge_is_a_cms_hint_never_a_platform_tenant():
    """The WO-163 false-positive case, real and load-bearing: Syracuse,
    NY's own page carries the exact `<meta name="generator" content=
    "OpenCities - https://granicus.com/product/opencities">` tag that
    app/platforms/base.py's CORPORATE_HOSTS_BY_PLATFORM check exists to
    stop from being read as a real granicus.com video tenant (WO-163,
    2026-09-10 -- see BACKLOG_DONE.md). Per Ryan's rule (WO-163): a
    vendor's own badge/mention says who built the website -- a real CMS
    hint -- even though the mention itself is never a tenant. This test
    confirms both halves at once on the SAME real page: cms_fingerprint
    correctly reads it as a useful "opencities" hint, while base.py's
    detect_platform() (already covered in tests/test_base.py) correctly
    does NOT read the mention itself as a granicus.com tenant.
    """
    html = _fixture("opencities_syracuse_ny_false_positive_case.html")
    result = classify(html, url="https://www.syr.gov/Home")
    assert result.family == "opencities"
    assert "opencities" in result.evidence.lower()

    # The corporate-marketing host itself (what the generator tag merely
    # *names*) is not a real per-government tenant -- exactly the WO-163
    # guarantee this fixture is borrowed to also exercise here.
    assert base.detect_platform("https://granicus.com/product/opencities") == "unknown"
