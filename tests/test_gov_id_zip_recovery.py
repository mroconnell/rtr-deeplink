"""Real DB integration tests for `_resolve_page_government()`'s
`meeting_location`/`title` state recovery (archive/db/crud.py) -- a
first-time tenant with a bare jurisdiction name and no prior Archive
history used to land on `unresolved`/`unverified` even when the resolver
payload's own fields carried a usable state. Found investigating a
2026-09 HTTP wildcard sweep. Two independent real gaps, same underlying
`resolve_government(signals=...)` mechanism, fixed together:

- `meeting_location`: Legistar's "Meeting location" field is often a real
  street address with a zip (`ResolvedMeeting.meeting_location`'s own
  docstring, confirmed live on Alameda, CA).
- `title`: a Legistar meeting delegated to its video platform gets a
  title like "City of Appleton, WI - Live Video" while `jurisdiction` for
  the same meeting is just "City of Appleton" -- the state is on the
  page, just not in the field gov_id resolution read before this fix.

See BACKLOG_DONE.md for the write-up.

Same isolated-SQLite fixture pattern as test_ingest_promotion.py.
"""

from archive.db import crud


def _payload(
    external_id: str,
    source_url: str,
    *,
    jurisdiction,
    meeting_location=None,
    title="City Council",
):
    return {
        "platform": "legistar",
        "source_url": source_url,
        "external_id": external_id,
        "title": title,
        "date": "2026-01-01",
        "jurisdiction": jurisdiction,
        "meeting_location": meeting_location,
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": [],
        "agenda_items": [],
        "transcript_language": None,
        "transcript_warnings": [],
    }


async def test_bare_name_with_zip_in_meeting_location_resolves_to_registry_gov_id():
    # "City of Alameda" alone (no state) is a real, confirmed-ambiguous
    # US place name -- Alameda, CA is the real one; without recovery this
    # landed on `unresolved`. The zip is Alameda, CA's real one.
    url = "https://alameda-zip-recovery-test.legistar.com/MeetingDetail.aspx?ID=1"
    result = await crud.ingest_resolution(
        _payload(
            "legistar:alameda-zip-recovery-test:1",
            url,
            jurisdiction="City of Alameda",
            meeting_location="City Hall, 2263 Santa Clara Avenue, Alameda CA 94501",
        ),
        url,
    )
    page = await crud.get_page_by_slug(result["slug"])
    assert page["gov_id"] == "us:place:0600562"


async def test_bare_name_without_meeting_location_stays_unresolved():
    # Same bare name, no address to recover a state from -- must not
    # mint or guess a gov_id.
    url = "https://alameda-no-location-test.legistar.com/MeetingDetail.aspx?ID=1"
    result = await crud.ingest_resolution(
        _payload(
            "legistar:alameda-no-location-test:1",
            url,
            jurisdiction="City of Alameda",
        ),
        url,
    )
    page = await crud.get_page_by_slug(result["slug"])
    assert not page["gov_id"]


async def test_bare_name_with_state_in_title_resolves_to_registry_gov_id():
    # Appleton is a real, confirmed-ambiguous US place name (WI, ME, MN
    # all have one) -- Appleton, WI is the real one here, and it's the
    # delegated video title that says so, not the bare jurisdiction
    # string.
    url = "https://appleton-title-recovery-test.legistar.com/MeetingDetail.aspx?ID=1"
    result = await crud.ingest_resolution(
        _payload(
            "legistar:appleton-title-recovery-test:1",
            url,
            jurisdiction="City of Appleton",
            title="City of Appleton, WI - Live Video",
        ),
        url,
    )
    page = await crud.get_page_by_slug(result["slug"])
    assert page["gov_id"] == "us:place:5502375"


async def test_bare_name_with_plain_title_stays_unresolved():
    # Same bare name, a title with no state anywhere in it -- must not
    # mint or guess a gov_id.
    url = "https://appleton-no-title-state-test.legistar.com/MeetingDetail.aspx?ID=1"
    result = await crud.ingest_resolution(
        _payload(
            "legistar:appleton-no-title-state-test:1",
            url,
            jurisdiction="City of Appleton",
            title="Live Video",
        ),
        url,
    )
    page = await crud.get_page_by_slug(result["slug"])
    assert not page["gov_id"]


async def test_meeting_location_without_a_zip_does_not_crash():
    # Legistar sometimes has a meeting-type/room descriptor instead of a
    # real address (Mesa AZ, Naperville -- see ResolvedMeeting.
    # meeting_location's own docstring) -- must degrade to no recovery,
    # not raise.
    url = "https://no-zip-location-test.legistar.com/MeetingDetail.aspx?ID=1"
    result = await crud.ingest_resolution(
        _payload(
            "legistar:no-zip-location-test:1",
            url,
            jurisdiction="City of Alameda",
            meeting_location="Regular Meeting",
        ),
        url,
    )
    page = await crud.get_page_by_slug(result["slug"])
    assert not page["gov_id"]
