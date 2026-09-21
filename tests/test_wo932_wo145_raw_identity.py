"""WO-932: the raw-page identity check, ported into WO-145's shared sweep.

The BACKLOG entry "A tenant with no video content never runs the identity
conflict checks" describes two real guesses from the WO-168 pilot
(2026-09-10) that no automated check caught, because a tenant with meetings
but no embeddable video never reaches `resolved_ok`:

- `pub-woodstock.escribemeetings.com`, guessed for Woodstock town, CT; its
  real content is the City of Woodstock, ONTARIO ("The Corporation of the
  City of Woodstock ... County of Oxford").
- `pub-lakewood.escribemeetings.com`, guessed for Lakewood city, CO; its real
  content is "Township Of Lakewood, County Of Ocean, State Of New Jersey".

The page text below is built by hand around those two real sentences (the
whole page was never saved). The Livingston County, MI row is WO-168's real
false-positive regression: the row's own state appears only as an address
abbreviation ("Howell MI 48843").

`scripts/wo145_api_first_sweep.py` imports rtr-discovery (`discovery.ledger`),
which CI does not have, so these tests skip there. They run on a machine with
`~/Documents/rtr-discovery` checked out, which is where the sweeps run.
"""

import sqlite3

import pytest

try:
    import scripts.wo145_api_first_sweep as w145
except Exception:  # noqa: BLE001 -- the rtr-discovery checkout is not installed
    w145 = None

pytestmark = pytest.mark.skipif(
    w145 is None, reason="needs the rtr-discovery checkout (wo145 imports `discovery`)"
)


class _Resp:
    def __init__(self, status, html):
        self.status = status
        self._html = html

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def text(self, errors="replace"):
        return self._html


class _Session:
    def __init__(self, html, status=200):
        self._html = html
        self._status = status
        self.fetched = []

    def get(self, url, **kwargs):
        self.fetched.append(url)
        return _Resp(self._status, self._html)


def _cand(name, state, kind="municipality", platform="escribe", gov_id="test:wo932"):
    return w145.Cand(
        gov_id=gov_id,
        name=name,
        state=state,
        country="us",
        gov_kind=kind,
        population="",
        domain="",
        known_platform=platform,
        platform_norm=platform,
        hub_url="",
        test_status="",
        reject_reason="",
        discovery_tenant="",
    )


WOODSTOCK_ON = (
    "<html><title>Meetings</title><body>The Corporation of the City of "
    "Woodstock. Council Meeting. County of Oxford. Agenda. Minutes.</body></html>"
)
LAKEWOOD_NJ = (
    "<html><title>Meeting Calendar</title><body>Township Of Lakewood, County Of "
    "Ocean, State Of New Jersey. Township Committee Meeting.</body></html>"
)
LIVINGSTON_MI = (
    "<html><title>Board of Commissioners</title><body>Livingston County "
    "Administration Building 304 E. Grand River, Board Chambers, Howell MI 48843 "
    "Board of Commissioners meeting.</body></html>"
)


async def test_the_woodstock_ontario_page_is_refused_for_woodstock_connecticut():
    verdict, detail = await w145.raw_candidate_identity_check(
        _Session(WOODSTOCK_ON),
        "https://pub-woodstock.escribemeetings.com/x",
        _cand("Woodstock", "CT"),
    )
    assert verdict is False
    assert "Woodstock" in detail


async def test_the_lakewood_new_jersey_page_is_refused_for_lakewood_colorado():
    verdict, detail = await w145.raw_candidate_identity_check(
        _Session(LAKEWOOD_NJ),
        "https://pub-lakewood.escribemeetings.com/x",
        _cand("Lakewood", "CO"),
    )
    assert verdict is False
    assert "New Jersey" in detail


async def test_livingston_county_michigan_is_not_a_false_conflict():
    verdict, _detail = await w145.raw_candidate_identity_check(
        _Session(LIVINGSTON_MI),
        "https://example.invalid/x",
        _cand("Livingston County", "MI", kind="county", platform="civicclerk"),
    )
    assert verdict is not False


async def test_an_unreachable_page_is_inconclusive_not_a_conflict():
    verdict, detail = await w145.raw_candidate_identity_check(
        _Session("", status=503), "https://example.invalid/x", _cand("Woodstock", "CT")
    )
    assert verdict is None
    assert "unverified" in detail


def test_wo168_still_exposes_the_function_under_its_old_name():
    import scripts.wo168_gated_tenant_guess as w168

    assert w168.raw_candidate_identity_check is w145.raw_candidate_identity_check


# process_enumerator_platform: the tail that used to say "no-video-found" ------


class _FakeLedger:
    """Just enough of discovery.ledger.Ledger for the queries
    `process_enumerator_platform()` makes. One real-shaped candidate row: a
    listed meeting on the tenant, never resolved."""

    def __init__(self, netloc, url):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            "CREATE TABLE candidates (tenant_netloc TEXT, url_normalized TEXT, "
            "status TEXT, status_reason TEXT, resolved_json TEXT, "
            "resolve_attempts INTEGER, date TEXT)"
        )
        self.conn.execute(
            "INSERT INTO candidates VALUES (?, ?, 'new', NULL, NULL, 0, '2026-09-01')",
            (netloc, url),
        )

    def upsert_tenant(self, netloc, platform):
        pass

    def set_tenant_gov_id(self, netloc, gov_id, state_abbr=None):
        pass


class _Seeds:
    def writerow(self, row):
        pass


async def _run_tail(monkeypatch, cand, netloc, html):
    async def ok_identity(session, host, c):
        return True, "confirmed"

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(w145, "check_tenant_identity", ok_identity)
    monkeypatch.setattr(w145, "enumerate_candidates", noop)
    monkeypatch.setattr(w145, "resolve_candidates", noop)
    url = f"https://{netloc}/Meeting.aspx?Id=00000000-0000-0000-0000-000000000000"
    rep = w145.Report(cand.gov_id, cand.name, cand.state, cand.gov_kind, "")
    return await w145.process_enumerator_platform(
        _Session(html),
        _FakeLedger(netloc, url),
        cand,
        netloc,
        "guess",
        rep,
        None,
        _Seeds(),
    )


async def test_a_no_video_tenant_with_another_governments_content_is_refused(
    monkeypatch,
):
    rep = await _run_tail(
        monkeypatch,
        _cand("Woodstock", "CT"),
        "pub-woodstock.escribemeetings.com",
        WOODSTOCK_ON,
    )
    assert rep.reject_reason == "wrong-domain-mapping"
    assert rep.outcome == "skipped"


async def test_a_no_video_tenant_that_reads_as_the_right_government_is_left_alone(
    monkeypatch,
):
    # Livingston County, MI's own page (WO-168's real false-positive case):
    # nothing on it names another government, so the old "no-video-found"
    # answer stands. Inconclusive or confirmed is never a mismatch.
    rep = await _run_tail(
        monkeypatch,
        _cand("Livingston County", "MI", kind="county"),
        "pub-livingston.escribemeetings.com",
        LIVINGSTON_MI,
    )
    assert rep.reject_reason == "no-video-found"
