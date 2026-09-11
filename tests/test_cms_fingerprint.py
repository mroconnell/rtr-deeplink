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


def test_govoffice_domain_suffix():
    """Evansdale, IA -- fetched live 2026-09-10 while building WO-179's
    family-scale sweep. GovOffice's own domain IS the government's
    domain (govoffice.com/govoffice2.com/govoffice3.com), so this is a
    pure netloc check -- no content signature needed."""
    html = _fixture("govoffice_evansdale_ia_home.html")
    result = classify(html, url="https://evansdale.govoffice.com/")
    assert result.family == "govoffice"
    assert result.rule_id == "govoffice-domain-suffix"


def test_municipalimpact_domain_suffix():
    """Delhi, LA -- fetched live 2026-09-10. Same domain-is-the-vendor
    shape as GovOffice, on municipalimpact.com."""
    html = _fixture("municipalimpact_delhi_la_home.html")
    result = classify(html, url="https://townofdelhi.municipalimpact.com/")
    assert result.family == "municipalimpact"
    assert result.rule_id == "municipalimpact-domain-suffix"


def test_in_gov_towns_portal():
    """Georgetown, IN -- fetched live 2026-09-10. This town has no domain
    of its own; it's hosted directly at www.in.gov/towns/georgetown/,
    the state's own shared portal for small Indiana towns. The
    /towns/{slug}/meetings path on this real tenant is a populated
    agenda-PDF listing."""
    html = _fixture("in_gov_towns_portal_georgetown_in_meetings.html")
    result = classify(html, url="https://www.in.gov/towns/georgetown/meetings")
    assert result.family == "in_gov_towns_portal"
    assert "towns/georgetown" in result.evidence


def test_wv_local_gov_sharepoint_portal():
    """Williamstown, WV -- fetched live 2026-09-10. West Virginia's own
    shared SharePoint portal, local.wv.gov/{slug}/ -- confirmed real for
    3 towns during WO-179 (Williamstown, Madison, Fayetteville), all
    reached via this one shared host."""
    html = _fixture("wv_local_gov_williamstown_home.html")
    result = classify(html, url="https://local.wv.gov/williamstown/")
    assert result.family == "wv_local_gov"
    assert result.rule_id == "wv-local-gov-host"


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


def test_civiclive_asset_host_regex_does_not_catastrophically_backtrack():
    """Synthetic (hand-built), not a real fixture -- exercises a specific
    performance bug, not a new detection case; the civiclive-asset-host
    rule's own detection accuracy is already fixture-confirmed above and
    in `test_civiclive_asset_host_without_civiclive_domain`. Real
    incident, WO-179 (2026-09-10): `_rule_civiclive`'s original regex
    opened with an UNBOUNDED `[a-z0-9.-]*` immediately before a literal
    that usually fails to match -- classic catastrophic-backtracking
    shape. It hung for minutes on a REAL 10MB government homepage
    (Sherman, IL, `shermanil.org`, confirmed live 2026-09-10 during
    WO-179's own family-scale sweep) that had no civiclive signature at
    all but did have long runs of dot/dash/alphanumeric characters
    (inlined assets, hashes) for the old regex to backtrack across. This
    test reconstructs that same *shape* synthetically (a large block of
    exactly the adversarial character class, no real page content, since
    checking in a 10MB real fixture would be impractical) and asserts it
    resolves near-instantly -- proof the bounded-quantifier fix holds,
    without needing the actual 10MB page on file.
    """
    import time

    # 200KB of exactly the characters the vulnerable class matched, with
    # no "civiclive" substring anywhere -- big enough that the OLD regex
    # would have taken very much longer than 2 seconds (confirmed by hand
    # against the pre-fix pattern; the real 10MB page took minutes).
    adversarial_run = "a1.-" * 50_000
    html = f"<html><body>{adversarial_run}</body></html>"

    start = time.monotonic()
    result = classify(html, url="https://example-city.gov/")
    elapsed = time.monotonic() - start

    assert elapsed < 2.0, (
        f"classify() took {elapsed:.2f}s -- regression of the ReDoS fix"
    )
    assert result.family == "unknown"
