"""`scripts/split_hub_slug.py` -- WO-316, the tool that gives a second (or
third) government sharing a hub slug its own permanent one. Built for the
three real collisions WO-310 measured live (Middletown Township PA,
Yarmouth NS, Lunenburg NS -- see the script's own module docstring and
`docs/investigations/hub_architecture_audit.md` §8).

Real DB integration against the shared SQLite fixture, same pattern as
`tests/test_hub_slug_freeze.py`. This file uses the SAME real Nova Scotia
gov_ids as the actual WO-316 production run (`ca:cd:1202`, `ca:csd:1202004`,
`ca:csd:1202006`, `ca:csd:1206001`, `ca:csd:1206006`) -- not a synthetic
stand-in -- because the collision here is REAL and lives in the national
`ca_csd.csv`/`ca_cd.csv` tables themselves: a Canadian census division and
a Canadian census subdivision both display as a bare `"{Name}, {PR}"`
(`app/utils/gov_registry/display.py`'s COUNTY/MUNICIPALITY branches), so
two distinct real governments sharing the name "Yarmouth" or "Lunenburg"
compute the identical live slug with no forcing required -- exactly what
`scripts/split_hub_slug.py`'s docstring and BACKLOG.md's entry describe.
This test file only ever touches the isolated SQLite test database
(`archive.db.engine` reads `DATABASE_URL`, set by `tests/conftest.py`
before any import) -- never the real production Archive.
"""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

import archive.main
from archive.db import crud
from archive.db.engine import async_session
from archive.db.models import HubSlug
from scripts.split_hub_slug import (
    decide_keeper,
    overall_keeper,
    run_split,
    slug_has_distinguisher,
)

client = TestClient(archive.main.app)


def _payload(external_id, url, *, jurisdiction, title, date, gov_id):
    return {
        "platform": "granicus",
        "source_url": url,
        "external_id": external_id,
        "title": title,
        "date": date,
        "jurisdiction": jurisdiction,
        "gov_id": gov_id,
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": [{"start": 0, "end": 1, "text": "hub split test"}],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }


async def _seed(external_id, **kwargs) -> str:
    url = f"https://example.com/hub-split/{external_id}"
    result = await crud.ingest_resolution(_payload(external_id, url, **kwargs), url)
    return result["slug"]


async def _row(gov_id: str):
    async with async_session() as session:
        return (
            await session.execute(
                select(
                    HubSlug.hub_slug, HubSlug.first_seen_at, HubSlug.frozen_at
                ).where(HubSlug.gov_id == gov_id)
            )
        ).first()


# --- pure logic --------------------------------------------------------------


def test_slug_has_distinguisher_recognizes_the_named_tokens():
    assert slug_has_distinguisher(
        "middletown-township-bucks-county-pa", "middletown-township-pa", "PA"
    )
    assert slug_has_distinguisher("municipality-of-yarmouth-ns", "yarmouth-ns", "NS")
    assert slug_has_distinguisher("town-of-lunenburg-ns", "lunenburg-ns", "NS")
    assert not slug_has_distinguisher("yarmouth-ns-2", "yarmouth-ns", "NS")


def test_slug_has_distinguisher_state_suffix_must_be_new():
    # Both slugs already end "-ns" -- adding nothing new must not count.
    assert not slug_has_distinguisher("yarmouth-town-ns", "yarmouth-ns", "NS")
    # Two occurrences of the code where the old slug had one DOES count.
    assert slug_has_distinguisher("ns-yarmouth-ns", "yarmouth-ns", "NS")


def test_decide_keeper_more_pages_wins():
    keeper, reason = decide_keeper(("a", 5, None), ("b", 1, None))
    assert keeper == "a"
    assert "more pages" in reason


def test_decide_keeper_ties_fall_to_older_first_seen():
    now = datetime.now(timezone.utc)
    older = now - timedelta(days=10)
    keeper, reason = decide_keeper(("a", 1, now), ("b", 1, older))
    assert keeper == "b"
    assert "older first_seen_at" in reason


def test_decide_keeper_full_tie_prefers_sibling():
    now = datetime.now(timezone.utc)
    keeper, reason = decide_keeper(("a", 1, now), ("b", 1, now))
    assert keeper == "b"
    assert "tied" in reason


def test_overall_keeper_picks_the_group_winner_not_a_pairwise_loser():
    """The real bug this fixes, found running the tool against production
    for Yarmouth NS: a target can LOSE a pairwise check against a
    co-loser (another subdivision that also doesn't deserve the slug)
    while still being correct to split off, because the TRUE keeper is a
    third contender neither pairwise check considers alone. `county` is
    the oldest (true keeper); `town` and `district` are both younger and
    neither should block the other from being split off.
    """
    now = datetime.now(timezone.utc)
    county = ("county", 1, now - timedelta(days=30))
    district = ("district", 1, now - timedelta(days=2))
    town = ("town", 1, now - timedelta(days=1))
    keeper, _ = overall_keeper([town, county, district])
    assert keeper == "county"
    keeper, _ = overall_keeper([district, county, town])
    assert keeper == "county"


def test_overall_keeper_ignores_a_dead_zero_page_sibling():
    """The other real bug this fixes: a retired, zero-page sibling (e.g.
    Middletown Township PA's old `rtr:us:pa:middletown-township` minted
    id) must never win contention just because its `first_seen_at`
    predates every real contender -- it renders nothing."""
    now = datetime.now(timezone.utc)
    dead = ("dead-old-mint", 0, now - timedelta(days=365))
    real_a = ("real-a", 1, now - timedelta(days=10))
    real_b = ("real-b", 1, now - timedelta(days=1))
    keeper, reason = overall_keeper([real_b, dead, real_a])
    assert keeper == "real-a"
    assert "dead-old-mint" not in reason


# --- the tool, end to end, against the REAL colliding governments -----------


async def test_split_writes_a_distinct_frozen_slug_and_touches_nothing_else():
    """Yarmouth County, NS (`ca:cd:1202`) and the Municipal District of
    Yarmouth, NS (`ca:csd:1202004`) are two real, distinct governments
    that both display as "Yarmouth, NS" today (no registry override
    needed -- this is the live bug WO-310 measured), so they collide on
    `yarmouth-ns` with no forcing. Splitting the municipal district off
    must leave the county's hub untouched and give the district its own,
    separately-rendering hub.
    """
    gov_county = "ca:cd:1202"  # Yarmouth County, NS
    gov_district = "ca:csd:1202004"  # Municipal District of Yarmouth, NS

    await _seed(
        "granicus:wo316-yarmouth-county-1",
        jurisdiction="Yarmouth County, NS",
        title="Yarmouth County Council",
        date="2016-02-01",
        gov_id=gov_county,
    )
    await _seed(
        "granicus:wo316-yarmouth-district-1",
        jurisdiction="Yarmouth, NS",
        title="Municipal District of Yarmouth Council",
        date="2016-02-01",
        gov_id=gov_district,
    )

    row_county = await _row(gov_county)
    row_district = await _row(gov_district)
    assert row_county is not None and row_district is not None
    assert row_county[0] == row_district[0] == "yarmouth-ns", (
        "both real governments must be computing the same live slug today "
        "-- if this fails, the underlying collision this tool exists for "
        "no longer reproduces and the test needs a new pair"
    )

    new_slug = "municipality-of-yarmouth-ns"
    result = await run_split(gov_district, new_slug, apply=False, force=False)
    assert result["ok_to_write"] is True
    assert result["written"] is False
    assert result["current_slug"] == "yarmouth-ns"
    assert any(s["gov_id"] == gov_county for s in result["siblings"])

    result = await run_split(gov_district, new_slug, apply=True, force=False)
    assert result["written"] is True

    # The district moved; the county's row was never touched.
    row_county_after = await _row(gov_county)
    row_district_after = await _row(gov_district)
    assert row_county_after[0] == "yarmouth-ns", "the sibling's row must be untouched"
    assert row_district_after[0] == new_slug
    assert row_district_after[2] is not None, "the split row must be frozen immediately"

    # End to end: each hub now renders only its own page.
    r_old = client.get("/j/yarmouth-ns")
    r_new = client.get(f"/j/{new_slug}")
    assert r_old.status_code == 200
    assert r_new.status_code == 200
    assert "Yarmouth County Council" in r_old.text
    assert "Municipal District of Yarmouth Council" not in r_old.text
    assert "Municipal District of Yarmouth Council" in r_new.text
    assert "Yarmouth County Council" not in r_new.text

    # Yarmouth is really a THREE-way collision (BACKLOG.md's own
    # correction of the original audit): the Town of Yarmouth
    # (`ca:csd:1202006`) still shares `yarmouth-ns` with the county at
    # this point. Splitting the town off must not be falsely blocked by
    # a pairwise comparison against the district (already moved off, not
    # even a sibling any more) -- this is the exact real bug found
    # running this tool against production for WO-316.
    gov_town = "ca:csd:1202006"  # Town of Yarmouth, NS
    await _seed(
        "granicus:wo316-yarmouth-town-1",
        jurisdiction="Yarmouth, NS",
        title="Town of Yarmouth Council",
        date="2016-02-01",
        gov_id=gov_town,
    )
    row_town = await _row(gov_town)
    assert row_town[0] == "yarmouth-ns"

    town_slug = "town-of-yarmouth-ns"
    result = await run_split(gov_town, town_slug, apply=True, force=False)
    assert result["ok_to_write"] is True
    assert result["written"] is True

    row_county_final = await _row(gov_county)
    row_district_final = await _row(gov_district)
    row_town_final = await _row(gov_town)
    assert row_county_final[0] == "yarmouth-ns", "the county was never touched"
    assert row_district_final[0] == new_slug, (
        "the district's split earlier is untouched"
    )
    assert row_town_final[0] == town_slug


async def test_split_refuses_without_a_real_collision():
    gov_id = "us:county:06035"  # Lassen County, CA -- real, unrelated, no collision
    await _seed(
        "granicus:wo316-split-lonely-1",
        jurisdiction="Lassen County, CA",
        title="Lonely County Council",
        date="2016-02-02",
        gov_id=gov_id,
    )
    result = await run_split(
        gov_id, "municipality-of-wo316-lonely-ca", apply=True, force=False
    )
    assert result["ok_to_write"] is False
    assert result["written"] is False
    row = await _row(gov_id)
    assert row[0] != "municipality-of-wo316-lonely-ca"


async def test_split_refuses_when_target_should_keep_the_slug():
    """The Municipal District of Lunenburg, NS (`ca:csd:1206001`) and the
    Town of Lunenburg, NS (`ca:csd:1206006`) are the second real pair --
    both display as "Lunenburg, NS" and collide on `lunenburg-ns` with no
    forcing. Giving the district two pages and the town one, then asking
    to split the DISTRICT (the one with more pages) off must refuse.
    """
    gov_district = "ca:csd:1206001"  # Municipal District of Lunenburg, NS
    gov_town = "ca:csd:1206006"  # Town of Lunenburg, NS

    await _seed(
        "granicus:wo316-lunenburg-district-1",
        jurisdiction="Lunenburg, NS",
        title="Lunenburg District Council 1",
        date="2016-02-03",
        gov_id=gov_district,
    )
    await _seed(
        "granicus:wo316-lunenburg-district-2",
        jurisdiction="Lunenburg, NS",
        title="Lunenburg District Council 2",
        date="2016-02-04",
        gov_id=gov_district,
    )
    await _seed(
        "granicus:wo316-lunenburg-town-1",
        jurisdiction="Lunenburg, NS",
        title="Lunenburg Town Council 1",
        date="2016-02-03",
        gov_id=gov_town,
    )

    row_district = await _row(gov_district)
    row_town = await _row(gov_town)
    assert row_district[0] == row_town[0] == "lunenburg-ns"

    # gov_district has 2 pages, gov_town has 1 -- splitting the district
    # (the one with MORE pages) off the shared slug is backwards per the
    # stated rule.
    result = await run_split(
        gov_district, "district-of-wo316-lunenburg-ns", apply=True, force=False
    )
    assert result["ok_to_write"] is False
    assert result["written"] is False


async def test_split_refuses_a_new_slug_with_no_distinguisher():
    gov_town = "ca:csd:1206006"  # Town of Lunenburg, NS

    # A cosmetic-only new slug (no county/municipality-of-/town-of-/etc.,
    # and no NEW state/province token) must be refused even though a real
    # collision exists -- reuses the rows the previous test already seeded
    # (module-level shared test DB, same pattern as test_hub_slug_freeze.py).
    result = await run_split(gov_town, "lunenburg-ns-2", apply=True, force=False)
    assert result["ok_to_write"] is False
    assert result["written"] is False
