"""WO-1181 (2026-10-05): a caller-supplied gov_id naming the county row of
a consolidated city-county is redirected to the government the Archive
uses (consolidated_governments.csv), and Dixon USD's Granicus view is
pinned to the school district.

Real cases, synthetic payloads: page 11283 (Nashville's Metropolitan
Council, 2026-09-15) landed under Davidson County TN us:county:47037
because an ingest sent that id; the consolidated row says the Archive uses
us:place:4752006. Page 5308 (clip 1913, "Dixon USD Board Meeting") landed
under Dixon city because the only pin on dixon-ca.granicus.com was the
whole-host city pin. The payload shape follows
test_untitled_meeting_heading.py; the ids and hosts are the real ones.
"""

import pytest

from archive.db import crud

NASHVILLE_PLACE = "us:place:4752006"
DAVIDSON_COUNTY = "us:county:47037"


async def _ingest(external_id: str, url: str, **overrides) -> dict:
    payload = {
        "platform": "granicus",
        "source_url": url,
        "external_id": external_id,
        "title": "Metropolitan Council",
        "date": "2026-09-15",
        "jurisdiction": None,
        "video_url": f"{url}#video",
        "video_format": "mp4",
        "segments": [],
        "agenda_items": [],
        "transcript_language": None,
        "transcript_warnings": [],
    }
    payload.update(overrides)
    return await crud.ingest_resolution(payload, url)


async def _gov_id(slug: str) -> str:
    page = await crud.get_page_by_slug(slug)
    return page["gov_id"]


def test_canonical_gov_id_redirects_only_consolidated_county_rows():
    assert crud._canonical_gov_id(DAVIDSON_COUNTY) == NASHVILLE_PLACE
    assert crud._canonical_gov_id(NASHVILLE_PLACE) == NASHVILLE_PLACE
    assert crud._canonical_gov_id("us:county:48367") == "us:county:48367"
    assert crud._canonical_gov_id("  ") is None
    assert crud._canonical_gov_id(None) is None


async def test_caller_county_id_for_a_consolidated_city_county_lands_on_the_city():
    url = "https://nashville.granicus.com/player/clip/990001"
    result = await _ingest("wo1181-a", url, gov_id=DAVIDSON_COUNTY)
    assert await _gov_id(result["slug"]) == NASHVILLE_PLACE


async def test_county_id_for_a_page_already_under_the_city_is_not_a_409():
    url = "https://nashville.granicus.com/player/clip/990002"
    first = await _ingest("wo1181-b", url, gov_id=NASHVILLE_PLACE)
    # Before WO-1181 this raised GovernmentMismatch (the 409 Find Meeting hit).
    again = await _ingest("wo1181-b", url, gov_id=DAVIDSON_COUNTY)
    assert again["slug"] == first["slug"]
    assert await _gov_id(again["slug"]) == NASHVILLE_PLACE


async def test_override_with_a_consolidated_county_id_writes_the_city_id():
    url = "https://nashville.granicus.com/player/clip/990003"
    result = await _ingest("wo1181-c", url)
    page = await crud.get_page_by_slug(result["slug"])
    out = await crud.override_jurisdiction(
        ids={page["id"]}, gov_id=DAVIDSON_COUNTY, dry_run=True
    )
    assert out["gov_id"] == NASHVILLE_PLACE


@pytest.mark.parametrize(
    "path, expected",
    [
        # view 3 is Dixon USD's board meetings (clip 1913)
        ("player/clip/991913?view_id=3", "us:sd:0611280"),
        # any other view stays on the whole-host city pin
        ("player/clip/991821?view_id=1", "us:place:0619402"),
    ],
)
async def test_dixon_granicus_view_3_is_the_school_district(path, expected):
    url = f"https://dixon-ca.granicus.com/{path}"
    result = await _ingest(
        f"wo1181-dixon-{path}", url, title="Dixon USD Board Meeting", date="2026-08-20"
    )
    assert await _gov_id(result["slug"]) == expected
