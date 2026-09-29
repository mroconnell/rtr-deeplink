"""WO-1167: meeting sites linked from governments' own CivicPlus websites.

A 2026-09-29 pre-pass read the homepage of 623 undecided CivicPlus sites
that list no meetings. 61 linked a meeting site on a platform we walk
that rtr-discovery didn't know. Each was then checked live; 60 named
their government (evidence in each row of `tenant_overrides.csv`).
"""

import pytest

from app.utils.gov_registry.resolver import resolve_government

PINS = [
    ("stormlake.granicus.com", "us:place:1975630"),
    ("newhavenin.portal.civicclerk.com", "us:place:1852992"),
    ("wilmertx.new.swagit.com", "us:place:4879576"),
    ("colusacoca.portal.civicclerk.com", "us:county:06011"),
    ("trinitycoca.portal.civicclerk.com", "us:county:06105"),
    ("desotobocc.legistar.com", "us:county:12027"),
    ("jacksoncoil.portal.civicclerk.com", "us:county:17077"),
    ("jodaviesscoil.portal.civicclerk.com", "us:county:17085"),
    ("pearlrivercoms.portal.civicclerk.com", "us:county:28109"),
    ("stanlyconc.portal.civicclerk.com", "us:county:37167"),
    ("essexvt.portal.civicclerk.com", "us:cousub:5000724175"),
    ("chippewacowi.portal.civicclerk.com", "us:county:55017"),
    ("shawanowi.civicweb.net", "us:place:5572925"),
    ("cheshirect.portal.civicclerk.com", "us:cousub:0914014160"),
    ("mcpcity.community.diligentoneplatform.com", "us:place:2043950"),
    ("northville.community.diligentoneplatform.com", "us:place:2658980"),
    ("rogersmn.portal.civicclerk.com", "us:place:2755186"),
    ("mauricerivertwpnj.portal.civicclerk.com", "us:cousub:3401144580"),
    ("abingtonpa.viebit.com", "us:cousub:4209100156"),
    ("huronsd.civicweb.net", "us:place:4631060"),
    ("imperialca.portal.civicclerk.com", "us:place:0636280"),
    ("arvadaco.portal.civicclerk.com", "us:place:0803455"),
    ("lajuntaco.portal.civicclerk.com", "us:place:0842110"),
    ("telluride.civicweb.net", "us:place:0876795"),
    ("alachuafl.portal.civicclerk.com", "us:place:1200375"),
    ("clermontfl.portal.civicclerk.com", "us:place:1212925"),
    ("myoldsmar.civicweb.net", "us:place:1251350"),
    ("romeoville.legistar.com", "us:place:1765442"),
    ("westmontil.portal.civicclerk.com", "us:place:1780645"),
    ("fortdodgeiowa.civicweb.net", "us:place:1928515"),
    ("newtonia.portal.civicclerk.com", "us:place:1956505"),
    ("cumberlandmd.portal.civicclerk.com", "us:place:2421325"),
    ("grossepointemi.portal.civicclerk.com", "us:place:2635540"),
    ("cottagegrovemn.portal.civicclerk.com", "us:place:2713456"),
    ("hibbingmn.portal.civicclerk.com", "us:place:2728790"),
    ("saintfrancismn.portal.civicclerk.com", "us:place:2756950"),
    ("gautierms.portal.civicclerk.com", "us:place:2826860"),
    ("oceanspringsms.portal.civicclerk.com", "us:place:2853520"),
    ("rockyhillnj.iqm2.com", "us:place:3464320"),
    ("sagharborny.granicus.com", "us:place:3664485"),
    ("sagharborny.iqm2.com", "us:place:3664485"),
    ("monroenc.portal.civicclerk.com", "us:place:3743920"),
    ("adaok.portal.civicclerk.com", "us:place:4000200"),
    ("cityofpendletonor.civicweb.net", "us:place:4157150"),
    ("foxchapelpa.portal.civicclerk.com", "us:place:4227120"),
    ("pigeonforgetn.portal.civicclerk.com", "us:place:4758080"),
    ("arcolatx.portal.civicclerk.com", "us:place:4803708"),
    ("ferris-texas.community.diligentoneplatform.com", "us:place:4825752"),
    ("redoaktx.portal.civicclerk.com", "us:place:4861196"),
    ("berryvilleva.portal.civicclerk.com", "us:place:5106968"),
    ("dupont.civicweb.net", "us:place:5318965"),
    ("quincy.civicweb.net", "us:place:5357115"),
    ("ridgefieldwa.portal.civicclerk.com", "us:place:5358410"),
    ("deforestwi.granicus.com", "us:place:5519350"),
    ("jacksonwi.portal.civicclerk.com", "us:place:5537675"),
    ("newberlinwi.portal.civicclerk.com", "us:place:5556375"),
    ("thiensvillewi.portal.civicclerk.com", "us:place:5579475"),
    ("southportland-gov.community.diligentoneplatform.com", "us:place:2371990"),
    ("cityofnewulm.civicweb.net", "us:place:2746042"),
    ("mcalesterok.portal.civicclerk.com", "us:place:4044800"),
    ("www.newhaven.in.gov", "us:place:1852992"),
]


@pytest.mark.parametrize("host, gov_id", PINS)
def test_the_site_resolves_to_its_government(host, gov_id):
    assert resolve_government(None, tenant_host=host, path="/").gov_id == gov_id
