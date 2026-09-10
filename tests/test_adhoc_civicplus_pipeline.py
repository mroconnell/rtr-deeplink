"""scripts/adhoc_civicplus_pipeline.py -- the WO-137 homepage-CivicClerk
fallback (2026-09-09).

Real, confirmed-live finding: a bare `{domain}/AgendaCenter` page raising
`NoVideoCandidateFound` does NOT always mean the government has no video.
Of a 30-government live sample of exactly this outcome (WO-127/WO-128's
own sweeps), 3 -- Arvada CO, Westfield IN, St. Joseph MO -- have an empty
or video-less AgendaCenter module while their own homepage links directly
to a CivicClerk portal, a platform this app already fully supports. Two
real shapes were confirmed live 2026-09-09:

  - St. Joseph MO's homepage links straight to a specific event
    (`stjosephmo.portal.civicclerk.com/event/1310/overview`) --
    `civicclerk.py`'s own `/event/(\\d+)` regex doesn't care about the
    trailing path segment, so this needs no extra lookup at all.
  - Arvada CO / Westfield IN's homepages link to just the bare portal
    root (`{tenant}.portal.civicclerk.com/`) -- confirmed live to be a
    client-rendered SPA with no server-rendered event list (a plain GET
    returns a ~1KB "You need to enable JavaScript" shell), so finding a
    real recent event needs the tenant's own public Events API instead.

The two small HTML snippets below are reconstructed, not raw-saved pages
(same convention `tests/fixtures/civicplus/README.md` already documents
for `agendacenter_listing.html`): each keeps only the real, confirmed-live
homepage link text and href (fetched 2026-09-09) around a minimal, made-up
page shell, since the real full homepage HTML for each city runs to
~100-200KB of unrelated nav/footer markup that has no bearing on what
`find_platform_link()` actually reads.

`synthetic_events_listing.json` is fully synthetic (Arvada/Westfield IN's
real Events API responses were never saved), but its schema is not
invented -- every field `civicclerk_latest_event_url()` reads
(`id`, `eventName`, `startDateTime`, `isDeleted`, `hasMedia`,
`mediaStreamPath`, `mediaSourcePathMp4`, `externalMediaUrl`) is copied
from `tests/fixtures/civicclerk/clovisca_event17.json`, a real, raw-saved
CivicClerk API response already used elsewhere in this suite. What's
unconfirmed: whether a real CivicClerk tenant's `/Events` odata listing
endpoint returns these same field names on each array element the way the
single-event endpoint does -- `scripts/nationwide_2404_ingest.py`'s own
`civicclerk_latest_event_url()` (this function's real, live-verified
source, copied per this repo's existing per-pipeline-script convention)
assumes so and has been run against production; this test only confirms
the parsing logic this script's own copy applies to that assumed shape,
not the assumption itself.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from conftest import load_fixture  # noqa: E402

from adhoc_civicplus_pipeline import (  # noqa: E402
    _is_specific_civicclerk_event_url,
    _looks_like_real_meeting,
    civicclerk_latest_event_url,
    homepage_civicclerk_fallback,
)

from aiohttp_mock import FakeResponse, mock_session  # noqa: E402

# Reconstructed from the real, confirmed-live homepage link text/href
# fetched 2026-09-09 (see this module's own docstring) -- everything
# outside the one <a> tag is made-up filler, not copied from the real
# page.
ARVADA_HOMEPAGE_HTML = """
<html><body>
<nav><a href="/157/City-Council">City Council</a></nav>
<a href="https://arvadaco.portal.civicclerk.com/">Meetings &amp; Agendas</a>
</body></html>
"""

ST_JOSEPH_HOMEPAGE_HTML = """
<html><body>
<nav><a href="/171/City-Council-Mayor">City Council &amp; Mayor</a></nav>
<a href="https://stjosephmo.portal.civicclerk.com/event/1310/overview">
  City Council Meeting August 17, 2026
</a>
</body></html>
"""

NO_VIDEO_HOMEPAGE_HTML = """
<html><body>
<nav><a href="/838/Agendas-Minutes">Council Agendas &amp; Minutes</a></nav>
<a href="https://www.facebook.com/apexnc">Facebook</a>
</body></html>
"""


def test_specific_event_url_detected_without_api_call():
    assert _is_specific_civicclerk_event_url(
        "https://stjosephmo.portal.civicclerk.com/event/1310/overview"
    )
    assert _is_specific_civicclerk_event_url(
        "https://stjosephmo.portal.civicclerk.com/event/1310/media"
    )
    assert not _is_specific_civicclerk_event_url(
        "https://arvadaco.portal.civicclerk.com/"
    )


async def test_homepage_link_to_specific_event_needs_no_api_call():
    # St. Joseph MO shape: the homepage link is already a specific event,
    # so this must resolve without ever calling the Events API.
    homepage_url = "https://stjosephmo.gov/"
    routes = {
        homepage_url: FakeResponse(
            status=200, text=ST_JOSEPH_HOMEPAGE_HTML, url=homepage_url
        )
    }
    with mock_session(routes):
        import aiohttp

        async with aiohttp.ClientSession() as session:
            url, reason = await homepage_civicclerk_fallback(session, "stjosephmo.gov")
    assert reason == ""
    assert url == "https://stjosephmo.portal.civicclerk.com/event/1310/overview"


async def test_homepage_link_to_bare_portal_root_uses_events_api():
    # Arvada CO shape: the homepage link is just the bare portal root, so
    # this must fall through to the tenant's own Events API and pick the
    # most recent real (past, has media, not deleted) event.
    homepage_url = "https://arvadaco.gov/"
    events_url = (
        "https://arvadaco.api.civicclerk.com/v1/Events"
        "?$orderby=startDateTime desc&$top=25"
    )
    filtered_url_prefix = "https://arvadaco.api.civicclerk.com/v1/Events?$filter="
    events_json = load_fixture("civicclerk", "synthetic_events_listing.json")

    def fake_get(self, url, **kwargs):
        key = str(url)
        if key == homepage_url:
            return FakeResponse(status=200, text=ARVADA_HOMEPAGE_HTML, url=key)
        if key.startswith(filtered_url_prefix):
            # Real tenants' Events API sometimes rejects the $filter form
            # with a 4xx -- civicclerk_latest_event_url() falls back to
            # the unfiltered `plain` query in that case, exercised here.
            return FakeResponse(status=400, text="", url=key)
        if key == events_url:
            return FakeResponse(status=200, text=events_json, url=key)
        raise AssertionError(f"unexpected request: {key}")

    from unittest import mock
    import aiohttp

    with mock.patch.object(aiohttp.ClientSession, "get", fake_get):
        async with aiohttp.ClientSession() as session:
            url, reason = await homepage_civicclerk_fallback(session, "arvadaco.gov")

    assert reason == ""
    # id 4021 is the newest real (media, not deleted) event in the fixture
    assert url == "https://arvadaco.portal.civicclerk.com/event/4021/media"


async def test_no_civicclerk_link_on_homepage_declines_cleanly():
    homepage_url = "https://apexnc.gov/"
    routes = {
        homepage_url: FakeResponse(
            status=200, text=NO_VIDEO_HOMEPAGE_HTML, url=homepage_url
        )
    }
    with mock_session(routes):
        import aiohttp

        async with aiohttp.ClientSession() as session:
            url, reason = await homepage_civicclerk_fallback(session, "apexnc.gov")
    assert url is None
    assert "no known-platform link" in reason


@pytest.mark.parametrize(
    "title,expected",
    [
        ("City Council Meeting", True),
        ("Planning Commission Work Session", True),
        ("Mayor's State of the City Address", False),
        ("Ribbon Cutting Ceremony", False),
    ],
)
def test_looks_like_real_meeting(title, expected):
    assert _looks_like_real_meeting(title) is expected


async def test_civicclerk_latest_event_url_skips_deleted_and_no_media_rows():
    events_url = (
        "https://exampletenant.api.civicclerk.com/v1/Events"
        "?$orderby=startDateTime desc&$top=25"
    )
    filtered_url_prefix = "https://exampletenant.api.civicclerk.com/v1/Events?$filter="
    events_json = load_fixture("civicclerk", "synthetic_events_listing.json")

    def fake_get(self, url, **kwargs):
        key = str(url)
        if key.startswith(filtered_url_prefix):
            return FakeResponse(status=400, text="", url=key)
        if key == events_url:
            return FakeResponse(status=200, text=events_json, url=key)
        raise AssertionError(f"unexpected request: {key}")

    from unittest import mock
    import aiohttp

    with mock.patch.object(aiohttp.ClientSession, "get", fake_get):
        async with aiohttp.ClientSession() as session:
            url, reason = await civicclerk_latest_event_url(
                session, "https://exampletenant.portal.civicclerk.com/"
            )
    assert reason == ""
    # Not id 4005 (isDeleted=true) even though it's chronologically most
    # recent in the fixture; not id 4019 (hasMedia=false either).
    assert url == "https://exampletenant.portal.civicclerk.com/event/4021/media"
