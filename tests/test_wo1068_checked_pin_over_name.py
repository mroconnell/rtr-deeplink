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
