"""WO-267 (2026-09-12): fixture-backed coverage for
scripts/platform_fingerprints.py.

Every fixture here is a real, raw-saved government page (see
tests/fixtures/platform_fingerprints/README.md for the source URL and
date of each, and docs/investigations/platform_fingerprints.md for the
full measurement -- hit rates, false-positive rates, and which signals
did NOT clear the bar). These are regression tests for the measured
signature table, the same role every other platform's fixture suite
already plays in this repo -- they don't replace the live measurement
that happened while building platform_signatures.csv.
"""

from scripts.platform_fingerprints import (
    classify_site_builder,
    fingerprint,
    load_signatures,
)

from conftest import load_fixture


def _fixture(name: str) -> str:
    return load_fixture("platform_fingerprints", name)


def test_signatures_load_and_are_all_kept_quality():
    """Every shipped row cleared the WO-267 bar (hit_rate >= 0.90 and
    false_positive_rate <= 0.05 per docs/investigations/
    platform_fingerprints.md) -- a future edit that sneaks a weaker
    signal into the CSV without updating this test is exactly the kind
    of silent regression this file exists to catch."""
    sigs = load_signatures()
    assert len(sigs) >= 25  # 28 as of 2026-09-12; a generous floor
    for sig in sigs:
        assert sig.hit_rate >= 0.90, sig
        assert sig.false_positive_rate <= 0.05, sig


def test_granicus_player_clip_path():
    html = _fixture("granicus_liberty_hill_tx_player_clip.html")
    matches = fingerprint(
        html, url="https://libertyhilltx.granicus.com/player/clip/694"
    )
    platforms = {p for p, _, _ in matches}
    assert "granicus" in platforms
    signal_ids = {s for _, s, _ in matches}
    assert "granicus-player-clip-path" in signal_ids
    assert "granicus-vendor-host" in signal_ids


def test_civicclerk_portal_host_matches_via_url_not_body():
    """A real CivicClerk portal page is a client-side-only JS shell (see
    the fixture README) -- the body text never spells out
    "civicclerk.com" or "portal.civicclerk.com", so this only matches
    because fingerprint() searches the page's own URL too, the same way
    detect_platform() classifies by URL."""
    html = _fixture("civicclerk_lincoln_ri_event_media.html")
    url = "https://lincolnri.portal.civicclerk.com/event/5463/media"
    matches = fingerprint(html, url=url)
    signal_ids = {s for _, s, _ in matches}
    assert "civicclerk-portal-host" in signal_ids
    # Confirms the body-only claim above: stripping the URL should lose it.
    matches_no_url = fingerprint(html, url="")
    assert "civicclerk-portal-host" not in {s for _, s, _ in matches_no_url}


def test_civicweb_meetinginformation_path():
    html = _fixture("civicweb_quesnel_bc_meetinginformation.html")
    url = "https://quesnel.civicweb.net/Portal/MeetingInformation.aspx?Id=1796"
    matches = fingerprint(html, url=url)
    signal_ids = {s for _, s, _ in matches}
    assert "civicweb-portal-meetinginfo-path" in signal_ids
    assert "civicweb-vendor-host" in signal_ids


def test_iqm2_citizens_path():
    html = _fixture("iqm2_colonie_ny_citizens_splitview.html")
    url = "http://colonieny.iqm2.com/Citizens/SplitView.aspx?Format=Minutes&MeetingID=1083&Mode=Video"
    matches = fingerprint(html, url=url)
    signal_ids = {s for _, s, _ in matches}
    assert "iqm2-citizens-path" in signal_ids


def test_escribe_pub_subdomain():
    html = _fixture("escribe_peelregion_on_pub_subdomain.html")
    url = (
        "https://pub-peelregion.escribemeetings.com/Meeting.aspx?"
        "Agenda=Agenda&Id=c129beef-a3cf-49ae-827d-27c6b3a547a5&lang=English"
    )
    matches = fingerprint(html, url=url)
    signal_ids = {s for _, s, _ in matches}
    assert "escribe-pub-subdomain" in signal_ids
    assert "escribe-vendor-host" in signal_ids


def test_swagit_videos_path():
    html = _fixture("swagit_middleburg_va_videos.html")
    url = "https://middleburgva.new.swagit.com/videos/344455"
    matches = fingerprint(html, url=url)
    signal_ids = {s for _, s, _ in matches}
    assert "swagit-videos-path" in signal_ids


def test_hyland_agendaonline_path_beats_bare_hostname():
    """The WO's central finding: a real Hyland/OnBase tenant commonly
    runs on its own custom domain with no hylandcloud.com anywhere on
    the page -- hyland-vendor-host (rejected, 10% hit rate in the real
    measurement) would miss this page; the path shape
    (hyland-agendaonline-path, kept, 100% hit rate) does not."""
    html = _fixture("hyland_santa_barbara_ca_agendaonline.html")
    url = "https://docs.santabarbaraca.gov/OnBaseAgendaOnline/Meetings/ViewMeeting?doctype=1&id=1184"
    matches = fingerprint(html, url=url)
    platforms_and_signals = {(p, s) for p, s, _ in matches}
    assert ("hyland", "hyland-agendaonline-path") in platforms_and_signals
    # hyland-vendor-host isn't in platform_signatures.csv at all (it was
    # rejected) -- confirm it simply can't appear as a match.
    assert not any(s == "hyland-vendor-host" for _, s, _ in matches)
    # The real host itself has nothing to do with hylandcloud.com.
    assert "hylandcloud.com" not in url
    assert "hylandcloud.com" not in html.lower()


def test_municode_meetings_vendor_host():
    html = _fixture("municode_meetings_douglas_mi.html")
    url = "https://douglas-mi.municodemeetings.com/bc-citycouncil/page/regular-meeting-city-council-91"
    matches = fingerprint(html, url=url)
    signal_ids = {s for _, s, _ in matches}
    assert "municode-meetings-vendor-host" in signal_ids


def test_fingerprint_returns_nothing_for_an_unrelated_page():
    html = (
        "<html><body><h1>Welcome to a town with no meeting platform</h1></body></html>"
    )
    matches = fingerprint(html, url="https://example-town.gov/")
    assert matches == []


def test_classify_site_builder_delegates_to_cms_fingerprint():
    """WO-267 measures PLATFORM signals, not website CMS family --
    WO-154/WO-179's scripts/cms_fingerprint.py already does that, and
    this module calls it directly rather than duplicating rules."""
    html = _fixture("municode_meetings_douglas_mi.html")
    result = classify_site_builder(html, url="https://douglas-mi.municodemeetings.com/")
    # Not asserting a specific family here -- only that delegation works
    # and returns the same kind of object cms_fingerprint.classify() does.
    assert hasattr(result, "family")
    assert hasattr(result, "rule_id")
