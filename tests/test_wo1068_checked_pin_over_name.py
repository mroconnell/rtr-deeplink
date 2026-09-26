"""WO-1068 (2026-09-25): a checked whole-host pin beats a name that matched
a different city, town, village or county; 15 wrong pins corrected.

Every case is a real Archive page from the 2026-09-25 export (page ids in
comments); the stored name is passed exactly as the page carried it. See
docs/investigations/whole_host_pin_mismatch_2026-09-25.md.
"""

import pytest

from app.utils.gov_registry.resolver import TIER_PINNED, resolve_government


def _resolve(name, host, path="/"):
    return resolve_government(name, tenant_host=host, path=path)


@pytest.mark.parametrize(
    "name, host, path, gov_id",
    [
        # Page 2407: Jackson County MO (Independence) read as the CO county.
        (
            "Jackson County, CO",
            "jacksonco.granicus.com",
            "/player/clip/6456",
            "us:county:29095",
        ),
        # Page 2047: Dallas County's Commissioners Court read as the city.
        (
            "Dallas, TX",
            "dallascounty.civicweb.net",
            "/Portal/MeetingInformation.aspx?Id=2108",
            "us:county:48113",
        ),
        # Page 426: a regional water authority read as the city of Tampa.
        (
            "Tampa, FL",
            "tampabaywater.granicus.com",
            "/player/clip/363",
            "rtr:us:fl:tampa-bay-water",
        ),
        # Page 3306: Newark NJ's Municipal Council read as Newark, CA.
        (
            "Newark, CA",
            "newark.granicus.com",
            "/MediaPlayer.php?clip_id=799&view_id=2",
            "us:place:3451000",
        ),
    ],
)
def test_checked_pin_beats_a_different_place(name, host, path, gov_id):
    match = _resolve(name, host, path)
    assert match.gov_id == gov_id
    assert match.tier == TIER_PINNED
    assert "WO-1068" in match.evidence


def test_school_district_on_a_city_site_keeps_its_own_id():
    # Page 747, albanyca.granicus.com (pinned to the city of Albany).
    match = _resolve(
        "Albany City Unified School District, CA",
        "albanyca.granicus.com",
        "/player/clip/1608?view_id=3",
    )
    assert match.gov_id == "us:sd:0601860"


def test_a_department_pin_does_not_displace_its_own_government():
    # Page 4726: humalertca.gov is pinned to a minted "Humboldt County
    # Sheriff" (type county); the county's Behavioral Health Board stays
    # on Humboldt County.
    match = _resolve("Humboldt County, CA", "humalertca.gov", "/AgendaCenter")
    assert match.gov_id == "us:county:06023"


def test_a_pin_no_person_checked_does_not_override_a_name():
    # reflect-townofwellfleet's pin (wo309b) was not marked checked in
    # WO-1075: the channel also carries Barnstable County shows. So a
    # namesake name match still wins there (page 5248, since re-filed by
    # hand, read "Wellfleet, NE").
    match = _resolve(
        "Wellfleet, NE",
        "reflect-townofwellfleet.cablecast.tv",
        "/internetchannel/show/3415",
    )
    assert match.gov_id == "us:place:3152085"


@pytest.mark.parametrize(
    "name, host, path, gov_id",
    [
        # WO-1075: pins re-checked live and marked checked. The bare
        # names are the adapters' own shapes for these misfiled pages.
        (
            "Ashland, WI",
            "ashlandcowi.portal.civicclerk.com",
            "/event/362/media",
            "us:county:55003",
        ),
        (
            "Dubuque, IA",
            "dubuquecountyia.portal.civicclerk.com",
            "/event/1548/media",
            "us:county:19061",
        ),
        (
            "Salt Lake City, UT",
            "saltlakecounty.portal.civicclerk.com",
            "/event/4172/media",
            "us:county:49035",
        ),
        (
            "Barnstable County, MA",
            "barnstable.cablecast.tv",
            "/internetchannel/show/12106",
            "us:place:2503690",
        ),
    ],
)
def test_rechecked_pins_now_beat_a_namesake(name, host, path, gov_id):
    assert _resolve(name, host, path).gov_id == gov_id


@pytest.mark.parametrize(
    "host, path, gov_id",
    [
        # Corrected whole-host pins, each checked live 2026-09-25.
        ("clark.granicus.com", "/player/clip/8133", "us:county:32003"),
        ("durham.granicus.com", "/player/clip/3301", "us:place:3719000"),
        ("eustis.civicweb.net", "/Portal/", "us:place:1221350"),
        ("douglascounty.legistar.com", "/Calendar.aspx", "us:county:08035"),
        ("victoria.granicus.com", "/player/clip/1", "us:place:2767036"),
        ("grandrapidscity.primegov.com", "/Portal/", "us:place:2634000"),
        ("cityofvernon.primegov.com", "/Portal/", "us:place:0682422"),
        # Two hosts carrying several governments, one pin per view.
        ("nevco.granicus.com", "/player/clip/7893", "us:county:06057"),
        (
            "nevco.granicus.com",
            "/MediaPlayer.php?clip_id=8355&view_id=2",
            "us:place:0650874",
        ),
        (
            "nevco.granicus.com",
            "/player/clip/6406?redirect=true&view_id=4",
            "us:place:0630798",
        ),
        ("burbank.granicus.com", "/player/clip/10931", "us:place:0608954"),
        (
            "burbank.granicus.com",
            "/MediaPlayer.php?clip_id=7784&view_id=4",
            "us:sd:0606450",
        ),
        (
            "burbank.granicus.com",
            "/MediaPlayer.php?clip_id=7784&view_id=40",
            "us:place:0608954",
        ),
    ],
)
def test_corrected_pins(host, path, gov_id):
    assert _resolve(None, host, path).gov_id == gov_id


def test_a_page_that_names_its_own_type_keeps_it():
    # napa.granicus.com is pinned to Napa County; "City of Napa, CA" is
    # the city's meeting (the same string test_ingest_promotion.py uses).
    match = _resolve("City of Napa, CA", "napa.granicus.com", "/player/clip/1")
    assert match.gov_id == "us:place:0650258"


def test_a_name_that_is_not_the_pins_namesake_keeps_its_own_government():
    # Page 1961: Broward MPO's page read as the town of Davie. Davie is
    # not a namesake of the MPO, so the rule leaves it (the page itself
    # was re-filed by hand); a county's channel can carry other
    # governments' meetings.
    match = _resolve(
        "Davie, FL", "browardmpo.new.swagit.com", "/videos/29818/transcript"
    )
    assert match.gov_id == "us:place:1216475"


# --- WO-1074 (2026-09-25): Ryan's calls on LAWA and M-NCPPC ---


@pytest.mark.parametrize(
    "name, host, path, gov_id",
    [
        # Page 361: an M-NCPPC Planning Board meeting whose stored name
        # read "Montgomery County, MD".
        (
            "Montgomery County, MD",
            "mncppc.granicus.com",
            "/player/clip/3287",
            "rtr:us:md:maryland-national-capital-park-and-planning-commission",
        ),
        # WO-1075: the Prince George's side of M-NCPPC (pages 1253, 2268
        # had no government).
        (
            "The Maryland-National Capital Park & Planning Commission",
            "mncppc.iqm2.com",
            "/Citizens/SplitView.aspx?MeetingID=1",
            "rtr:us:md:maryland-national-capital-park-and-planning-commission",
        ),
        # LAWA is its own government, like LADWP, never the City of LA.
        (
            "Los Angeles, CA",
            "lawa.granicus.com",
            "/player/clip/1256",
            "rtr:us:ca:l-a-world-airports-board-of-airport-commissioners",
        ),
    ],
)
def test_lawa_and_mncppc_hosts_are_their_own_governments(name, host, path, gov_id):
    assert _resolve(name, host, path).gov_id == gov_id


# ---------------------------------------------------------------------------
# WO-1100 (2026-09-26): on TelVue the pin naming a whole customer (its org
# token) is the fallback, not the first answer. WO-1068 above made a
# checked pin beat a namesake; this is the other direction, and only on
# TelVue, where every customer carries more than one government.
#
# The names are what telvue.py now returns for rtr-discovery's 8 saved
# media pages (tests/fixtures/telvue/wo1100/, captured 2026-09-25);
# tests/test_telvue.py checks the adapter half on the same pages.

_TELVUE = "videoplayer.telvue.com"
_DERRY = "/player/CXN6V2zmqTebSQfLjvlDzEql3BwiQh_l/media/"
_KALAMAZOO = "/player/2bm0gzQWeVRzdCgvjXziXKwO3icSKh05/media/"
_QUEEN_ANNES = "/player/AbfNhigIqnG-4roGCxaFupXEKfme9dfT/media/"
_PIERRE = "/player/5nQYx7H7WpbP8AVWnkzXsWu69pAXI7Yq/media/"


@pytest.mark.parametrize(
    "name, path, gov_id",
    [
        # Were wrong: the whole-customer pin filed them under the town or
        # the county.
        (
            "Derry Cooperative School District, NH",  # School Board Meeting
            _DERRY + "1047520",
            "us:sd:3302610",
        ),
        (
            "Pierre School District 32-2, SD",  # Pierre School Board
            _PIERRE + "1045603",
            "us:sd:4655260",
        ),
        # "Centreville Town Council || 09/17/2026": the adapter reads
        # "Centreville" with no state; the pins' state (MD) is added.
        ("Centreville", _QUEEN_ANNES + "1047511", "us:place:2414950"),
        # Was blank: no pin for the station, but its two one-video pins
        # are both Michigan.
        ("Kalamazoo County, MI", _KALAMAZOO + "1045901", "us:county:26077"),
        # Were right and stay right.
        ("Derry, NH", _DERRY + "1046119", "us:cousub:3301517940"),
        ("Pierre, SD", _PIERRE + "1047373", "us:place:4649600"),
    ],
)
def test_telvue_meetings_own_name_goes_before_the_customer_pin(name, path, gov_id):
    assert _resolve(name, _TELVUE, path).gov_id == gov_id


def test_telvue_generic_title_still_uses_the_customer_pin():
    # "County Commissioners Meeting || 09/21/2026" names no place: the
    # adapter returns no name and the Queen Anne's County pin decides.
    match = _resolve(None, _TELVUE, _QUEEN_ANNES + "1047333")
    assert (match.gov_id, match.tier) == ("us:county:24035", TIER_PINNED)


def test_telvue_name_that_matches_the_pin_keeps_the_pinned_tier():
    match = _resolve("Pierre, SD", _TELVUE, _PIERRE + "1047373")
    assert match.tier == TIER_PINNED


def test_telvue_oshtemo_stays_blank_because_its_name_only_mints():
    # "Oshtemo Township - Planning Commission - September 24, 2026
    # Meeting". The Census row is "Oshtemo charter township", and the
    # ladder does not match "Oshtemo Township, MI" to it (it mints), so
    # the name identifies nobody and the unpinned station stays blank.
    match = _resolve("Oshtemo Township", _TELVUE, _KALAMAZOO + "1047784")
    assert match.gov_id == "rtr:unknown:videoplayer.telvue.com"


@pytest.mark.parametrize(
    "name, path, gov_id",
    [
        # A name in another state never beats the pin. Synthetic name
        # (Centreville, VA is a real place) on the real QACTV page.
        ("Centreville, VA", _QUEEN_ANNES + "1047511", "us:county:24035"),
        # Narrower pins still win: Derry's school-board media pin, and
        # Kalamazoo's one-video City of Kalamazoo pin (WO-1060). Names
        # synthetic, chosen to disagree with the pin.
        ("Derry, NH", _DERRY + "951693", "us:sd:3302610"),
        ("Kalamazoo County, MI", _KALAMAZOO + "1041369", "us:place:2642160"),
    ],
)
def test_telvue_pins_the_name_cannot_beat(name, path, gov_id):
    match = _resolve(name, _TELVUE, path)
    assert (match.gov_id, match.tier) == (gov_id, TIER_PINNED)


def test_telvue_station_with_no_state_from_pins_stays_blank():
    # RVTV's pins are playlist pins that carry no org token, so no state
    # is fixed and the name is not used (tests/test_tenant_key.py's
    # WO-1057 case, unchanged).
    match = _resolve(
        "Grants Pass, OR",
        _TELVUE,
        "/player/w9sPsSE7vna3XTN_39bs1rEXjVWF0kfP/media/1047347",
    )
    assert match.gov_id == "rtr:unknown:videoplayer.telvue.com"


def test_other_multi_gov_hosts_keep_the_whole_tenant_pin_first():
    # Control: a ChampDS whole-customer pin (Atlanta) still wins over a
    # different name. WO-1100 is TelVue only. Synthetic name.
    match = _resolve("Fulton County, GA", "play.champds.com", "/atlantaga/event/1")
    assert (match.gov_id, match.tier) == ("us:place:1304000", TIER_PINNED)


def test_every_telvue_station_name_agrees_with_its_customer_pin():
    """telvue.py's hand-checked station names are applied when a title
    names no place. On a customer with a whole-customer pin they now reach
    the resolver before the pin, so each must name the pin's government,
    or a generic title would move off the pin (13 of 13 agree, 2026-09-26)."""
    from app.platforms.telvue import _KNOWN_ORG_TOKEN_JURISDICTIONS
    from app.utils.gov_registry import registry
    from app.utils.tenant_key import pin_tenant_key

    pins = {}
    for row in registry.tenant_overrides().get(_TELVUE, []):
        token = pin_tenant_key(_TELVUE, row.match)
        if token:
            pins.setdefault(token, set()).add(row.gov_id)
    checked = 0
    for token, name in _KNOWN_ORG_TOKEN_JURISDICTIONS.items():
        if token in pins:
            checked += 1
            assert resolve_government(name).gov_id in pins[token], (token, name)
    assert checked >= 13
