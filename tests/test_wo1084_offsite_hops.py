"""WO-1084: the access ladder's hop step no longer follows a link off the
government's own site unless it goes to a known meeting-platform host.

The host pairs below are real, from WO-1077's hand-read of 737 ladder
finds (BACKLOG_DONE.md): Wickliffe city, KY's state-template site
(`wickliffe.ky.gov`) hopped to `www.kentucky.gov/policies/...` and was
credited the Commonwealth's `kygov` YouTube channel; McMinn County, TN
hopped to UT Extension's county page. The page HTML in the last two tests
is synthetic (hand-written anchors), exercising only the hop filter on top
of the already fixture-tested scorer; the hosts in it are real.
"""

import pytest

from scripts.wo147_access_ladder_sweep import _is_offsite_hop, find_hop_links


@pytest.mark.parametrize(
    "netloc, base",
    [
        ("www.kentucky.gov", "wickliffe.ky.gov"),
        ("utextension.tennessee.edu", "www.mcminncountytn.gov"),
        ("www.sos.mo.gov", "www.madisoncountymo.us"),
        ("co.boone.in.us", "co.hendricks.in.us"),
    ],
)
def test_off_site_non_platform_hosts_are_refused(netloc, base):
    assert _is_offsite_hop(netloc, base) is True


@pytest.mark.parametrize(
    "netloc, base",
    [
        ("wickliffe.ky.gov", "wickliffe.ky.gov"),  # same host
        ("cityofmarina.org", "www.cityofmarina.org"),  # www form
        ("agenda.cityofmarina.org", "www.cityofmarina.org"),  # own subdomain
        ("www.in.gov", "www.in.gov"),  # a county page on the state host
        ("colusacoca.portal.civicclerk.com", "www.countyofcolusa.org"),  # vendor
        ("vimeo.com", "www.fairportny.gov"),  # platform host
        ("", "www.fairportny.gov"),  # relative link resolved elsewhere
    ],
)
def test_own_site_and_platform_hosts_are_allowed(netloc, base):
    assert _is_offsite_hop(netloc, base) is False


def test_find_hop_links_drops_the_state_footer_hop():
    html = """
    <html><body>
      <nav><a href="/Pages/Meetings.aspx">Council Meetings</a></nav>
      <footer>
        <a href="https://www.kentucky.gov/policies/Pages/default.aspx">Policies</a>
        <a href="https://www.kentucky.gov/government/Pages/meetings.aspx">State meetings</a>
      </footer>
    </body></html>
    """
    links = find_hop_links(html, "https://wickliffe.ky.gov/Pages/default.aspx")
    assert all("kentucky.gov" not in u for u in links)
    assert "https://wickliffe.ky.gov/Pages/Meetings.aspx" in links


def test_find_hop_links_keeps_a_vendor_hop():
    html = """
    <html><body>
      <nav><a href="https://colusacoca.portal.civicclerk.com/">Agendas &amp; Minutes</a></nav>
    </body></html>
    """
    links = find_hop_links(html, "https://www.countyofcolusa.org/")
    assert "https://colusacoca.portal.civicclerk.com/" in links
