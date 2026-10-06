"""Tests for scripts/pin_audit_name_rules.py.

Registry facts are REAL: Sunnyside WA (us:place:5368750) vs Sunnyside NL
(ca:csd:1001277), and Newark NJ (us:place:3451000) vs Newark NY
(us:place:3649891). The AuditData is SYNTHETIC and hand-built: the pins echo
the real tenant_overrides rows of the 2026-10-05 Sunnyside case, and the
pages and titles are invented for the rule under test.
"""

from scripts import pin_audit_core as core
from scripts import pin_audit_name_rules as nr
from scripts.pin_audit_core import AuditData, Page, Pin

WA = "us:place:5368750"
NL = "ca:csd:1001277"
NJ = "us:place:3451000"  # Newark NJ
NY = "us:place:3649891"  # Newark NY


def pin(host, gov, match="", source="", store=core.STORE_OVERRIDE, ref="", **kw):
    return Pin(store, host, match, gov, source=source, ref=ref or f"t:{host}", **kw)


def page(pid, gov, host, title="", stored="", channel="", video=""):
    return Page(pid, gov, title, stored, f"https://{host}/m/{pid}", video, host,
                "", channel)  # fmt: skip


def data(pins, pages=()):
    d = AuditData(pins=list(pins), pages=list(pages))
    core.build_indexes(d)
    return d


# ---------------------------------------------------------------- name_slug


def test_name_slug_real_examples():
    cases = [
        (pin("wa-sunnyside2.civicplus.com", WA), "sunnyside"),
        (pin("pub-peelregion.escribemeetings.com", WA), "peelregion"),
        (pin("cityofx.granicus.com", WA), "x"),
        (pin("sunnysidewa.gov", WA), "sunnysidewa"),
        (pin("www.youtube.com", WA, match="channel=@cityofsunnysidewa"), "sunnysidewa"),
        (pin("www.youtube.com", WA, match="channel=@bevcamgovernment1337"), "bevcamgovernment"),
        (pin("www.youtube.com", WA, match="buPsnmbebnk"), ""),
        (pin("youtube.com", WA), ""),
        (pin("play.champds.com", WA, match="/atlantaga/"), "atlantaga"),
        (pin("sunnyside.primegov.com", NL), "sunnyside"),
    ]  # fmt: skip
    for p, want in cases:
        assert nr.name_slug(p) == want, (p.host, p.match)


# ---------------------------------------------------------------- R1


def sunnyside_pins(primegov_source=""):
    return [
        pin("sunnyside.primegov.com", NL, source=primegov_source, ref="pg"),
        pin("sunnyside.granicus.com", WA, source="step0_leads", ref="gr"),
        pin("wa-sunnyside2.civicplus.com", WA, source="step0_dns_full_2026-09-27", ref="cp"),
    ]  # fmt: skip


def test_r1_sunnyside_split_is_high_with_two_agreeing_pins():
    ps = sunnyside_pins()
    flags = nr.rule_r1_same_name_split(data(ps), [ps[0]])
    assert len(flags) == 1
    f = flags[0]
    assert f.rule == "R1" and f.severity == "high"
    assert f.other_gov_id == WA
    assert (
        "sunnyside.primegov.com" in f.detail and "NL" in f.detail and "WA" in f.detail
    )


def test_r1_single_ordinary_pin_on_each_side_is_not_flagged():
    # Two same-named governments on different hosts are normal; with one pin
    # on each side and no sweep or Ryan source, there is nothing to say.
    ps = sunnyside_pins()[:2]
    assert nr.rule_r1_same_name_split(data(ps), [ps[0]]) == []


def test_r1_sweep_pin_with_one_twin_pin_is_medium():
    ps = sunnyside_pins(primegov_source="step0_dns_full_2026-09-27")[:2]
    flags = nr.rule_r1_same_name_split(data(ps), [ps[0]])
    assert [f.severity for f in flags] == ["medium"]


def test_r1_high_when_sweep_pin_meets_ryan_stated_twin():
    ps = sunnyside_pins(primegov_source="step0_dns_full_2026-09-27")[:2]
    ps[1] = pin("sunnyside.granicus.com", WA, source="ryan_stated", ref="gr")
    flags = nr.rule_r1_same_name_split(data(ps), [ps[0]])
    assert [f.severity for f in flags] == ["high"]


def test_r1_silent_when_the_pin_has_its_own_company():
    # NL has a second pin of its own, so the same name on two governments is
    # not a contradiction.
    ps = sunnyside_pins() + [pin("sunnyside.escribemeetings.com", NL, ref="esc")]
    assert nr.rule_r1_same_name_split(data(ps), [ps[0]]) == []


def test_r1_own_domain_is_not_judged():
    ps = sunnyside_pins()
    ps[0] = pin("sunnyside.gov", NL)
    assert nr.rule_r1_same_name_split(data(ps), [ps[0]]) == []


def test_r1_ryan_stated_pin_is_never_high():
    ps = sunnyside_pins(primegov_source="ryan_stated")
    ps.append(pin("sunnyside.civicweb.net", WA, ref="cw"))
    flags = nr.rule_r1_same_name_split(data(ps), [ps[0]])
    assert [f.severity for f in flags] == ["medium"]


def test_r1_negative_control_two_newarks_on_different_hosts():
    # Real facts: ny-newark.civicplus.com (NY) and newark.granicus.com (NJ)
    # are both live pins. The explicit state in the civicplus host settles it.
    ps = [
        pin("ny-newark.civicplus.com", NY, source="step0_dns_full_2026-09-27"),
        pin("newark.granicus.com", NJ, source="landing_page"),
    ]
    d = data(ps)
    assert nr.rule_r1_same_name_split(d, [ps[0]]) == []
    assert not [
        f for f in nr.rule_r1_same_name_split(d, [ps[1]]) if f.severity == "high"
    ]
    assert nr.rule_r2_state_word(d, ps) == []


def test_r1_skips_when_the_address_states_its_own_state():
    ps = [
        pin("wa-sunnyside2.civicplus.com", WA, source="step0_dns_full_2026-09-27"),
        pin("sunnyside.primegov.com", NL, source="ryan_stated"),
    ]
    assert nr.rule_r1_same_name_split(data(ps), [ps[0]]) == []


def test_r1_ignores_unrelated_names():
    ps = [pin("sunnyside.primegov.com", NL), pin("newark.granicus.com", NJ)]
    assert nr.rule_r1_same_name_split(data(ps), ps) == []


def test_r1_ignores_archive_pages_as_the_other_side():
    ps = [
        pin("sunnyside.primegov.com", NL),
        pin("sunnyside.example.org", WA, store=core.STORE_ARCHIVE),
    ]
    assert nr.rule_r1_same_name_split(data(ps), [ps[0]]) == []


# ---------------------------------------------------------------- R2


def test_r2_hyphen_code_names_other_state():
    p = pin("wa-sunnyside2.civicplus.com", NL)
    f = nr.rule_r2_state_word(data([p]), [p])
    assert len(f) == 1 and f[0].severity == "high"
    assert f[0].other_gov_id == WA
    assert "WA" in f[0].detail


def test_r2_glued_code_on_handle_and_on_domain():
    p1 = pin("www.youtube.com", NL, match="channel=@cityofsunnysidewa")
    p2 = pin("sunnysidewa.gov", NL)
    for p in (p1, p2):
        f = nr.rule_r2_state_word(data([p]), [p])
        assert len(f) == 1 and f[0].other_gov_id == WA


def test_r2_full_state_name():
    p = pin("sunnysidewashington.org", NL)
    f = nr.rule_r2_state_word(data([p]), [p])
    assert len(f) == 1 and "WA" in f[0].detail


def test_r2_glued_co_means_county_not_colorado():
    p = pin("montgomeryco.net", "us:county:18107")  # Montgomery County, IN (real)
    assert nr.rule_r2_state_word(data([p]), [p]) == []


def test_r2_no_fire_when_state_matches_or_absent():
    ok = [
        pin("wa-sunnyside2.civicplus.com", WA),
        pin("sunnysidewa.gov", WA),
        pin("sunnyside.primegov.com", NL),
    ]
    assert nr.rule_r2_state_word(data(ok), ok) == []


def test_r2_two_letters_that_are_part_of_the_name_do_not_fire():
    # "bend" + "or" would be Oregon only if what is left equals the name;
    # "sunnysideor" does, but "sunnysidexor" (not the name) must not.
    p = pin("sunnysidexor.gov", NL)
    assert nr.rule_r2_state_word(data([p]), [p]) == []


def test_r2_state_word_that_is_a_place_in_the_pins_own_state_does_not_fire():
    # SYNTHETIC pin, real ids: Wilkes County GA (us:county:13317). Washington
    # is a real Georgia city (us:place:1380704), so "washingtonwilkes" is a
    # local place name, not Washington State.
    p = pin("washingtonwilkes.org", "us:county:13317", source="research_row")
    assert nr.rule_r2_state_word(data([p]), [p]) == []
    # Positive control: Sunnyside NL has no Washington place, so this still fires.
    q = pin("sunnysidewashington.org", NL)
    assert len(nr.rule_r2_state_word(data([q]), [q])) == 1


# ---------------------------------------------------------------- R5 / R6


def test_r5_titles_name_the_twin_state():
    p = pin("sunnyside.primegov.com", NL)
    pages = [
        page("1", NL, "sunnyside.primegov.com", "Council Meeting", "Sunnyside, WA"),
        page("2", NL, "sunnyside.primegov.com", "Planning (WA) agenda"),
    ]
    f = nr.rule_r5_title_names_twin(data([p], pages), [p])
    assert len(f) == 1 and f[0].severity == "medium" and f[0].other_gov_id == WA
    assert "2 saved" in f[0].detail


def test_r5_no_fire_when_a_title_names_own_state_or_none_name_a_state():
    p = pin("sunnyside.primegov.com", NL)
    mixed = [
        page("1", NL, "sunnyside.primegov.com", "Council", "Sunnyside, WA"),
        page("2", NL, "sunnyside.primegov.com", "Council", "Sunnyside, NL"),
    ]
    plain = [page("3", NL, "sunnyside.primegov.com", "Regular Council Meeting")]
    assert nr.rule_r5_title_names_twin(data([p], mixed), [p]) == []
    assert nr.rule_r5_title_names_twin(data([p], plain), [p]) == []


def test_r5_keyed_pin_uses_channel_pages_and_pin_title():
    p = pin("www.youtube.com", NL, match="channel=@cityofsunnysidewa")
    pages = [
        page(
            "1",
            NL,
            "x.org",
            "Sunnyside, Washington council",
            channel="@CityOfSunnysideWA",
        )
    ]
    f = nr.rule_r5_title_names_twin(data([p], pages), [p])
    assert len(f) == 1
    q = pin("reflect.example.org", NL, title="Sunnyside, WA council")
    assert len(nr.rule_r5_title_names_twin(data([q]), [q])) == 1


def test_r5_washington_county_is_not_a_state():
    p = pin("sunnyside.primegov.com", NL)
    pages = [
        page("1", NL, "sunnyside.primegov.com", "Joint meeting, Washington County")
    ]
    assert nr.rule_r5_title_names_twin(data([p], pages), [p]) == []


def test_r6_sweep_pin_with_twin_and_no_content_is_a_note():
    p = pin("sunnyside.primegov.com", NL, source="step0_dns_full_2026-09-27")
    f = nr.rule_r6_risky_source_no_content(data([p]), [p])
    assert len(f) == 1 and f[0].severity == "note"


def test_r6_no_fire_with_content_or_safe_source_or_no_twin():
    p = pin("sunnyside.primegov.com", NL, source="step0_dns_full_2026-09-27")
    pg = [page("1", NL, "sunnyside.primegov.com", "Council")]
    assert nr.rule_r6_risky_source_no_content(data([p], pg), [p]) == []
    safe = pin("sunnyside.primegov.com", NL, source="ryan_stated")
    assert nr.rule_r6_risky_source_no_content(data([safe]), [safe]) == []
    lone = pin(
        "zzqx.primegov.com", "us:place:0000000", source="step0_dns_full_2026-09-27"
    )
    assert nr.rule_r6_risky_source_no_content(data([lone]), [lone]) == []


def test_rules_list():
    assert [r.__name__ for r in nr.RULES] == [
        "rule_r1_same_name_split",
        "rule_r2_state_word",
        "rule_r5_title_names_twin",
        "rule_r6_risky_source_no_content",
    ]


# ------------------------------------------- real false positives, fixed
# Each case below fired in the first full run and was a false alarm.

OREGON_CITY_OR = "us:place:4155200"  # real: "Oregon City city", OR
OREGON_VILLAGE_WI = "us:place:5560200"  # real: "Oregon village", WI
PINE_TWP_PA = "us:cousub:4200360272"  # real: Pine township, PA (Indiana County)


def test_a_city_word_inside_the_real_name_is_not_cut_off():
    # oregon-city.granicus.com is Oregon City, not Oregon (WI).
    ps = [
        pin("oregon-city.granicus.com", OREGON_CITY_OR, source="step0_dns_full_2026-09-27"),
        pin("wi-oregonvillage.civicplus.com", OREGON_VILLAGE_WI, ref="a"),
        pin("oregonwi.civicweb.net", OREGON_VILLAGE_WI, ref="b"),
    ]  # fmt: skip
    assert nr.rule_r1_same_name_split(data(ps), [ps[0]]) == []


def test_a_county_name_after_the_town_is_not_a_state_name():
    # pinetownshipindianacounty.com is Pine township in Indiana COUNTY, PA.
    p = pin("pinetownshipindianacounty.com", PINE_TWP_PA)
    assert nr.rule_r2_state_word(data([p]), [p]) == []


def test_a_county_address_is_not_split_against_a_city():
    # Real ids: Durham County NC (us:county:37063) vs Durham city OR.
    ps = [
        pin("durhamcounty.granicus.com", "us:county:37063", source="step0_dns_full_2026-09-27"),
        pin("durhamoregon.gov", "us:place:4121250", ref="a"),
        pin("or-durham.civicplus.com", "us:place:4121250", ref="b"),
    ]  # fmt: skip
    assert nr.rule_r1_same_name_split(data(ps), [ps[0]]) == []


def test_trailing_hyphen_co_is_county_not_colorado():
    p = pin("hamilton-co.org", "us:county:39061")  # real: Hamilton County, OH
    assert nr.rule_r2_state_word(data([p]), [p]) == []


def test_r2_glued_code_on_dot_org_is_only_medium():
    p = pin("sunnysidewa.org", NL)
    f = nr.rule_r2_state_word(data([p]), [p])
    assert [x.severity for x in f] == ["medium"]
    q = pin("sunnysidewa.gov", NL)
    assert [x.severity for x in nr.rule_r2_state_word(data([q]), [q])] == ["high"]


def test_r1_silent_when_a_second_store_agrees_on_the_same_host():
    ps = [
        pin("sunnyside.primegov.com", NL, source="step0_dns_full_2026-09-27"),
        pin("sunnyside.primegov.com", NL, store=core.STORE_RESEARCH, ref="r"),
        pin("sunnyside.granicus.com", WA, source="ryan_stated", ref="g"),
    ]
    assert nr.rule_r1_same_name_split(data(ps), [ps[0]]) == []


def test_r2_other_country_code_and_school_district_do_not_fire():
    # garfieldtownship-bc.com: Garfield township, MI (real us:cousub id below)
    # -- "bc" is not British Columbia here.
    p = pin("garfieldtownship-bc.com", "us:cousub:2601731540")
    assert nr.rule_r2_state_word(data([p]), [p]) == []
    # @HillsboroSD is a school district, not South Dakota.
    q = pin("www.youtube.com", "us:place:4134100", match="channel=@HillsboroSD")
    assert nr.rule_r2_state_word(data([q]), [q]) == []


def test_r1_vendor_country_prior_silences_cross_border_twin():
    # Synthetic: eScribe tenants are almost all Canadian, so Sussex NB on
    # eScribe against Sussex village WI is the expected shape, not a split.
    sussex_nb = "ca:csd:1305021"
    ps = [pin("sussex.escribemeetings.com", sussex_nb, source="wildcard_http_sweep_2")]
    ps += [
        pin(f"x{i}.escribemeetings.com", "ca:csd:3523008", ref=f"e{i}")
        for i in range(25)
    ]
    ps += [
        pin("sussexwi.gov", "us:place:5578750", ref="a"),
        pin("wi-sussex.civicplus.com", "us:place:5578750", ref="b"),
    ]
    assert nr.rule_r1_same_name_split(data(ps), [ps[0]]) == []
