"""Tests for app/platforms/host_recognition.py, WO-1015 part A (2026-09-23).

The hostnames below are all real, already-confirmed hosts recorded
elsewhere in this repo (module docstrings, README.md's "Supported
platforms" table, or existing test fixtures) -- not invented shapes, per
CLAUDE.md's synthetic-test rules. Comments cite where each one is
confirmed real.
"""

from app.platforms.host_recognition import (
    FIRST_PARTY_PROBE_PATHS,
    UNSUPPORTED_PLATFORMS,
    VENDOR_WEB_HOST_HINTS,
    platform_for_host,
    platform_for_path,
    platform_for_url,
    web_host_hint_for_host,
)


def test_recognizes_host_only_platforms_via_detect_platform():
    # cityoftacoma.granicus.com -- Tacoma WA, cited in CLAUDE.md's caption
    # roll-up sample list.
    assert platform_for_host("cityoftacoma.granicus.com") == ("granicus", True)
    # maricopa.legistar.com -- confirmed real, legistar.py's own docstring.
    assert platform_for_host("maricopa.legistar.com") == ("legistar", True)
    # NYC Council's own custom-domain Legistar instance -- base.py's own
    # docstring.
    assert platform_for_host("legistar.council.nyc.gov") == ("legistar", True)
    # antiochca.portal.civicclerk.com -- Antioch CA, CLAUDE.md caption
    # roll-up sample list.
    assert platform_for_host("antiochca.portal.civicclerk.com") == (
        "civicclerk",
        True,
    )
    # ca-westlakevillage.civicplus.com -- confirmed real, civicplus.py's
    # own docstring.
    assert platform_for_host("ca-westlakevillage.civicplus.com") == (
        "civicplus",
        True,
    )
    # slc.primegov.com -- confirmed real, primegov.py's own docstring.
    assert platform_for_host("slc.primegov.com") == ("primegov", True)
    # dallascounty.civicweb.net -- confirmed real, civicweb.py's own
    # docstring (Dallas County, TX).
    assert platform_for_host("dallascounty.civicweb.net") == ("civicweb", True)
    # eatwp.diligent.community -- Eatwp Township, PA, base.py's own
    # docstring (WO-348).
    assert platform_for_host("eatwp.diligent.community") == ("civicweb", True)
    # cortez.open.media -- Cortez, CO, openmedia.py's own docstring.
    assert platform_for_host("cortez.open.media") == ("open_media", True)
    # santabarbaraca.ompnetwork.org -- Santa Barbara CA, base.py's own
    # docstring (WO-46).
    assert platform_for_host("santabarbaraca.ompnetwork.org") == (
        "open_media",
        True,
    )
    # auburn.hosted.civiclive.com / cityoflynn.hosted2.civiclive.com --
    # both confirmed real: civiclive.py's own docstring (Auburn WA), and
    # tests/fixtures/cms_fingerprint/civiclive_lynn_ma_home.html (Lynn, MA).
    assert platform_for_host("auburn.hosted.civiclive.com") == ("civiclive", True)
    assert platform_for_host("cityoflynn.hosted2.civiclive.com") == (
        "civiclive",
        True,
    )
    # bristol-ri.municodemeetings.com -- Bristol, RI, cited in CLAUDE.md.
    assert platform_for_host("bristol-ri.municodemeetings.com") == (
        "municode_meetings",
        True,
    )
    # www.youtube.com / youtu.be -- generic hosts, both go through
    # detect_platform()'s own "youtube.com" / "youtu.be" branch.
    assert platform_for_host("www.youtube.com") == ("youtube", True)
    assert platform_for_host("youtu.be") == ("youtube", True)


def test_recognizes_path_dependent_adapters_by_host_alone():
    # detroit-vod.cablecast.tv -- Detroit MI, cablecast.py's own docstring.
    # A bare host has no /show/{id} path, so detect_platform() itself
    # would say "unknown" -- this is exactly the gap _HOST_ONLY_PLATFORMS
    # closes.
    assert platform_for_host("detroit-vod.cablecast.tv") == ("cablecast", True)
    # boxcast.tv itself -- real tenants (Wilmington OH etc, boxcast.py's
    # own docstring) live on the bare vendor domain, path-tenanted.
    assert platform_for_host("boxcast.tv") == ("boxcast", True)
    # go.boarddocs.com -- the one real BoardDocs host, boarddocs.py's own
    # `_HOST` constant (reused directly, not hand-copied).
    assert platform_for_host("go.boarddocs.com") == ("boarddocs", True)
    # player.invintus.com -- invintus.py's own docstring.
    assert platform_for_host("player.invintus.com") == ("invintus", True)
    # cloud.castus.tv -- Billings, MT, castus.py's own docstring.
    assert platform_for_host("cloud.castus.tv") == ("castus", True)
    # tucsonaz.hylandcloud.com -- Tucson AZ, base.py's own docstring.
    # hylandcloud.com is not NECESSARY to identify a Hyland tenant (two of
    # three known real tenants live on other domains -- see the next
    # test), but every real *.hylandcloud.com host seen so far IS a
    # genuine Hyland customer, so it's a safe SUFFICIENT host signal
    # (conductor review, 2026-09-23).
    assert platform_for_host("tucsonaz.hylandcloud.com") == ("hyland", True)


def test_recognizes_wistia_and_vimeo_via_their_own_host_predicates():
    # amsva.wistia.com -- RegionalWebTV/AMS Virginia, wistia.py's own
    # docstring (WO-161).
    assert platform_for_host("amsva.wistia.com") == ("wistia", True)
    # bare vimeo.com -- real meetings live at vimeo.com/{id}, e.g.
    # vimeo.com/1212025580 (Salisbury, NC, CLAUDE.md's sample list).
    assert platform_for_host("vimeo.com") == ("vimeo", True)
    # Marketing/infra hosts must not be claimed.
    assert platform_for_host("www.wistia.com") == (None, None)
    assert platform_for_host("fast.wistia.com") == (None, None)


def test_unsupported_vendor_returns_supported_false():
    # novusagenda.com -- named explicitly in CLAUDE.md's WO-1015 brief as
    # a known vendor with no rtr-deeplink adapter.
    assert platform_for_host("novusagenda.com") == ("novusagenda", False)
    assert ("novusagenda.com", "novusagenda") in UNSUPPORTED_PLATFORMS


def test_granicusgovaccess_is_a_web_host_hint_not_a_platform_match():
    # Ryan's decision, 2026-09-23, verbatim: "granicusgovaccess.net is a
    # hint/signature for granicus platform sometimes but it is in fact a
    # web host." platform_for_host() must NOT return it as a match --
    # only web_host_hint_for_host() may, and it names "granicus".
    assert platform_for_host("granicusgovaccess.net") == (None, None)
    assert web_host_hint_for_host("granicusgovaccess.net") == "granicus"
    assert ("granicusgovaccess.net", "granicus") in VENDOR_WEB_HOST_HINTS
    # A real Akamai edgekey CNAME target still hints correctly even though
    # granicusgovaccess.net sits as a MIDDLE label, not the host's own
    # suffix -- confirmed live in a real Alameda, CA CNAME chain (see
    # BACKLOG_DONE.md's WO-1015 entry). Matched by substring, same
    # semantics the old VENDOR_SUFFIXES list already used for this entry.
    assert web_host_hint_for_host("san-h2.granicusgovaccess.net.edgekey.net") == (
        "granicus"
    )
    assert web_host_hint_for_host("foo.granicusgovaccess.net") == "granicus"


def test_web_host_hint_is_none_for_unrelated_hosts():
    assert web_host_hint_for_host("cityoftacoma.granicus.com") is None
    assert web_host_hint_for_host("") is None


def test_seattle_channel_is_deliberately_not_recognized_by_host():
    # Seattle Channel: the host is a general broadcast site, not a
    # single-purpose vendor domain (seattlechannel.py's own docstring
    # scopes the real check to /videos?videoid= for this reason).
    assert platform_for_host("seattlechannel.org") == (None, None)


def test_hyland_on_a_non_hylandcloud_domain_is_not_recognized_by_host():
    # detect_platform()'s own Hyland branch matches on the
    # /Meetings/ViewMeeting path alone, no netloc check at all -- real
    # confirmed tenants on domains OTHER than hylandcloud.com
    # (mccobagenda.databankcloud.com, agendanet.saccounty.gov, base.py's
    # own docstring) have no host signal a hostname-only helper can use.
    assert platform_for_host("mccobagenda.databankcloud.com") == (None, None)
    assert platform_for_host("agendanet.saccounty.gov") == (None, None)


def test_bare_civiclive_and_boarddocs_apex_are_not_real_tenant_hosts():
    # Neither bare apex is a real per-government tenant host -- the real
    # tenant hosts are the hosted/hosted2 and go. subdomains respectively,
    # both already covered above.
    assert platform_for_host("civiclive.com") == (None, None)
    assert platform_for_host("boarddocs.com") == (None, None)


def test_platform_for_url_uses_the_urls_own_host():
    assert platform_for_url("https://cityoftacoma.granicus.com/player/clip/1") == (
        "granicus",
        True,
    )


def test_platform_for_host_is_case_and_trailing_dot_insensitive():
    assert platform_for_host("CityOfTacoma.Granicus.com") == ("granicus", True)
    assert platform_for_host("cityoftacoma.granicus.com.") == ("granicus", True)


def test_empty_host_is_unrecognized():
    assert platform_for_host("") == (None, None)
    assert platform_for_host("   ") == (None, None)


def test_sliq_harmony_recognized_by_host_alone():
    # WO-1021, 2026-09-23. sg001-harmony.sliq.net -- sliq_harmony.py's
    # own module docstring:
    # the one shared real host found by the vendor scan. is_sliq_harmony_
    # url() itself needs a real `/{tenant}/Harmony/...` path to confirm a
    # tenant (a hostname-only caller never has one), but the host is a
    # single-purpose vendor domain, same reasoning as Hyland's
    # hylandcloud.com above.
    assert platform_for_host("sg001-harmony.sliq.net") == ("sliq_harmony", True)
    # sg002-harmony.sliq.net / sg004-harmony.sliq.net -- sliq_harmony.py's
    # own docstring: confirmed live to be full mirrors of the same host,
    # not separate tenant pools (WO-1006).
    assert platform_for_host("sg002-harmony.sliq.net") == ("sliq_harmony", True)
    assert platform_for_host("sg004-harmony.sliq.net") == ("sliq_harmony", True)
    # A MEDIA host (sg002-live.sliq.net) has no "harmony" in the name and
    # is deliberately not matched -- sliq_harmony.py's own `_HOST_RE`
    # comment.
    assert platform_for_host("sg002-live.sliq.net") == (None, None)


def test_wo1018_unsupported_platforms_synced():
    # rtr-business's research/UNSUPPORTED_PLATFORMS.md (WO-1018,
    # 2026-09-23) reported these five host domains as known vendors with
    # no rtr-deeplink adapter -- confirmed (WO-1021) that none of the
    # five has an app/platforms/ adapter file.
    assert platform_for_host("simbli.eboardsolutions.com") == ("simbli", False)
    assert platform_for_host("novusagenda.com") == ("novusagenda", False)
    assert platform_for_host("agendasuite.org") == ("agendasuite", False)
    assert platform_for_host("video.ibm.com") == ("ibm_video_streaming", False)
    assert platform_for_host("portal.laserfiche.com") == (
        "laserfiche_cloud",
        False,
    )
    for host in (
        "simbli.eboardsolutions.com",
        "novusagenda.com",
        "agendasuite.org",
        "video.ibm.com",
        "portal.laserfiche.com",
    ):
        assert any(h == host for h, _p in UNSUPPORTED_PLATFORMS)


def test_platform_for_path_covers_detect_platform_native_branches():
    # CivicPlus AgendaCenter and Hyland AgendaOnline are already netloc-
    # independent branches inside detect_platform() (base.py) --
    # platform_for_path() picks them up via a neutral placeholder host,
    # rather than re-deriving the match. Real self-hosted examples cited
    # in base.py's own comments: welcometoatmore.com/AgendaCenter,
    # tucsonaz.hylandcloud.com-shaped /Meetings/ViewMeeting paths.
    assert platform_for_path("/AgendaCenter") == "civicplus"
    assert platform_for_path("/AgendaCenter/ViewFile/Minutes/_1") == "civicplus"
    assert platform_for_path("/BoardofSupervisors/Meetings/ViewMeeting") == "hyland"
    assert platform_for_path("/Meetings/ViewMeeting?id=1") == "hyland"


def test_platform_for_path_explicit_signatures():
    # The four path shapes base.py's detect_platform() does NOT (yet)
    # recognize without a netloc match -- moved verbatim from
    # wo282_recon.py's old _PATH_SHAPE_PLATFORMS (WO-1021).
    assert platform_for_path("/Citizens/SplitView.aspx?Mode=Video") == "iqm2"
    assert (
        platform_for_path("/Portal/MeetingInformation.aspx?Org=Cal&Id=1")
        == "civicclerk"
    )
    assert platform_for_path("/Archive.aspx?AMID=12345") == "legistar"
    assert platform_for_path("/ViewPublisher.php?view_id=2") == "granicus"
    assert platform_for_path("/MediaPlayer.php?meeting_id=3") == "granicus"


def test_platform_for_path_unrecognized():
    assert platform_for_path("/some/random/path") is None
    assert platform_for_path("") is None


def test_first_party_probe_paths_are_the_two_native_path_only_shapes():
    # wo282_targeted.py's fallback-ladder rung 3 blindly probes these --
    # they must stay exactly the two detect_platform()-native path-only
    # shapes (see platform_for_path's own test above), not the four
    # explicit-signature-only entries (those are never worth blind-
    # probing, only confirming a URL already in hand -- see
    # FIRST_PARTY_PROBE_PATHS's own comment in host_recognition.py).
    assert FIRST_PARTY_PROBE_PATHS == (
        "/AgendaCenter",
        "/AgendaOnline/Meetings/ViewMeeting",
    )
