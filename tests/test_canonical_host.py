"""app/utils/canonical_host.py: CivicPlus canonical-host recovery (Ryan, 2026-10-03)."""

import pytest

from app.utils import canonical_host as ch
from app.utils.canonical_host import FetchResult, recover_civicplus
from app.utils.robots_rules import Rule

VENDOR = "https://ma-ipswich.civicplus.com/AgendaCenter/ViewFile/Agenda/_09082026-8562"
LISTING = (
    '<html><a href="/AgendaCenter/ViewFile/Agenda/_09082026-8562">Agenda</a>'
    '<tr class="catAgendaRow"></tr></html>'
)


@pytest.fixture(autouse=True)
def _clean():
    ch.clear_cache()
    yield
    ch.clear_cache()


class Net:
    """A fake network: records every address asked for, answers from a table."""

    def __init__(self, pages=None, blocked=()):
        self.pages = pages or {}
        self.blocked = set(blocked)
        self.fetched = []
        self.robots_asked = []

    async def fetch(self, url):
        self.fetched.append(url)
        return self.pages.get(url)

    async def robots(self, url):
        self.robots_asked.append(url)
        if any(url.startswith(b) for b in self.blocked):
            return False, Rule(False, "/")
        return True, None


def html(text, status=200):
    return FetchResult(status, "text/html; charset=utf-8", text)


async def run(net, url=VENDOR, candidates=("ipswichma.gov",), **kw):
    return await recover_civicplus(
        url, candidates, fetch=net.fetch, robots=net.robots, **kw
    )


async def test_same_path_on_the_governments_own_domain_when_the_meeting_is_listed():
    net = Net({"https://ipswichma.gov/AgendaCenter": html(LISTING)})
    r = await run(net)
    assert r.recovered and r.evidence == "listed"
    assert (
        r.recovered_url
        == "https://ipswichma.gov/AgendaCenter/ViewFile/Agenda/_09082026-8562"
    )
    assert r.authority == "ipswichma.gov"


async def test_the_vendor_address_is_never_requested():
    net = Net({"https://ipswichma.gov/AgendaCenter": html(LISTING)})
    await run(net)
    assert not any("civicplus.com" in u for u in net.fetched + net.robots_asked)


async def test_path_and_query_are_kept_exactly():
    url = "https://ri-westerly.civicplus.com/AgendaCenter/ViewFile/Agenda/_06222016-26?html=true"
    listing = '<a href="/AgendaCenter/ViewFile/Agenda/_06222016-26">x</a><tr class="catAgendaRow">'
    net = Net({"https://westerlyri.gov/AgendaCenter": html(listing)})
    r = await run(net, url, ["westerlyri.gov"])
    assert (
        r.recovered_url
        == "https://westerlyri.gov/AgendaCenter/ViewFile/Agenda/_06222016-26?html=true"
    )


async def test_an_authority_whose_robots_disallows_the_address_is_skipped_and_the_www_twin_is_tried():
    net = Net(
        {"https://www.ipswichma.gov/AgendaCenter": html(LISTING)},
        blocked=["https://ipswichma.gov"],
    )
    r = await run(net)
    assert r.recovered and r.authority == "www.ipswichma.gov"
    assert r.skipped and r.skipped[0][0] == "ipswichma.gov"
    assert "robots.txt disallows" in r.skipped[0][1]


async def test_nothing_is_recovered_when_every_authority_disallows():
    net = Net(blocked=["https://ipswichma.gov", "https://www.ipswichma.gov"])
    r = await run(net)
    assert not r.recovered and len(r.skipped) == 2


async def test_a_site_that_is_not_civicplus_is_not_used():
    net = Net({"https://ipswichma.gov/AgendaCenter": html("<html>Welcome</html>")})
    r = await run(net)
    assert not r.recovered
    assert any("no CivicPlus AgendaCenter" in why for _, why in r.skipped)


async def test_an_older_meeting_is_accepted_when_the_exact_address_answers():
    net = Net(
        {
            "https://ipswichma.gov/AgendaCenter": html(
                '<tr class="catAgendaRow"></tr>'
            ),
            VENDOR.replace("ma-ipswich.civicplus.com", "ipswichma.gov"): FetchResult(
                200, "application/pdf", ""
            ),
        }
    )
    r = await run(net)
    assert r.recovered and r.evidence == "fetched"


async def test_an_older_meeting_that_is_not_there_is_not_recovered():
    net = Net({"https://ipswichma.gov/AgendaCenter": html('<tr class="catAgendaRow">')})
    r = await run(net)
    assert not r.recovered
    assert any("not found there" in why for _, why in r.skipped)


async def test_the_agenda_center_page_itself_needs_only_the_civicplus_structure():
    net = Net({"https://ipswichma.gov/AgendaCenter": html('<tr class="catAgendaRow">')})
    r = await run(
        net, "https://ma-ipswich.civicplus.com/AgendaCenter", ["ipswichma.gov"]
    )
    assert r.recovered and r.evidence == "structure"


async def test_a_non_civicplus_address_returns_nothing():
    r = await run(Net(), "https://www.ipswichma.gov/AgendaCenter")
    assert not r.recovered and r.reason == "not a CivicPlus vendor address"


async def test_no_candidate_domain_returns_a_plain_reason():
    r = await run(Net(), candidates=["", "civicplus.com", "10.1.2.3"])
    assert not r.recovered and "no candidate domain" in r.reason


async def test_the_listing_is_read_once_per_authority():
    net = Net({"https://ipswichma.gov/AgendaCenter": html(LISTING)})
    await run(net)
    await run(net, VENDOR.replace("_09082026-8562", "_09082026-8562") + "?x=1")
    assert net.fetched.count("https://ipswichma.gov/AgendaCenter") == 1


def test_helpers():
    assert ch.is_civicplus_vendor_url("https://sd-beadlecounty.civicplus.com/x")
    assert not ch.is_civicplus_vendor_url("https://x.hosted.civiclive.com/x")
    assert ch.meeting_token(VENDOR) == "_09082026-8562"
    assert ch._authorities(["https://www.Example.gov/a", "example.gov"]) == [
        "www.example.gov",
        "example.gov",
    ]


async def test_the_default_fetch_reads_a_long_page_to_the_end():
    """Real bug found 2026-10-03 against live servers: reading one buffered chunk missed a
    meeting token far down a long AgendaCenter page, so evidence fell to "fetched"."""
    from aiohttp import web
    from aiohttp.test_utils import TestServer

    token = "_09102026-105"
    body = "<html>" + ("<tr class='catAgendaRow'>x</tr>" * 20000) + token + "</html>"

    async def handler(request):
        return web.Response(text=body, content_type="text/html")

    app = web.Application()
    app.router.add_get("/AgendaCenter", handler)
    server = TestServer(app)
    await server.start_server()
    try:
        got = await ch._default_fetch(str(server.make_url("/AgendaCenter")))
    finally:
        await server.close()
    assert got is not None and got.status == 200
    assert token in got.text


def test_the_authority_table_finds_a_governments_own_domain():
    assert "ipswichma.gov" in ch.authorities_for_tenant("ma-ipswich.civicplus.com")
    assert "ipswichma.gov" in ch.authorities_for_tenant(
        "https://ma-ipswich.civicplus.com/AgendaCenter"
    )
    assert ch.authorities_for_tenant("no-such-place.civicplus.com") == []


async def test_the_cache_keeps_tokens_not_whole_pages_and_expires(monkeypatch):
    net = Net({"https://ipswichma.gov/AgendaCenter": html(LISTING)})
    cache = ch._Cache()
    await run(net, cache=cache)
    entry = cache.listings["ipswichma.gov"]
    assert "_09082026-8562" in entry.tokens and entry.is_civicplus
    assert not hasattr(entry, "text")

    fetched_before = net.fetched.count("https://ipswichma.gov/AgendaCenter")
    await run(net, cache=cache)  # inside the hour: no second read
    assert net.fetched.count("https://ipswichma.gov/AgendaCenter") == fetched_before

    real = ch.time.monotonic
    monkeypatch.setattr(ch.time, "monotonic", lambda: real() + 4000)
    await run(net, cache=cache)  # after the hour: read again
    assert net.fetched.count("https://ipswichma.gov/AgendaCenter") == fetched_before + 1


def test_the_cache_is_capped(monkeypatch):
    monkeypatch.setattr(ch, "_LISTING_MAX", 3)
    cache = ch._Cache()
    for i in range(6):
        cache.put(f"gov{i}.example", LISTING)
    assert len(cache.listings) == 3
