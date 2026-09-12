"""The frozen `/j/{slug}` per government -- WO-256, built from
`docs/investigations/hub_architecture_audit.md` §4.

Four questions, one test each:

  * does the 7-day/more-than-one-page gate hold on both sides?
  * does a frozen slug survive the government being renamed?
  * does a retired-slug alias still redirect with the freeze in place?
  * does the day-one backfill change any URL? (the answer has to be no:
    the freeze is *defined* as "whatever the site computes today", and
    this compares computed against stored over real registry rows.)

Real DB integration against the shared SQLite fixture, same pattern as
tests/test_jurisdiction_hubs.py. Every jurisdiction seeded here is a real
place no other test file uses, so counts stay stable whatever order the
suite runs in -- and every seeded meeting is DATED 2016, deliberately:
the fixture DB is shared and never reset, and a 2026-dated California
meeting seeded here pushed Napa's own page off `/state/california`'s
newest-first list, failing a test in tests/test_state_pages.py that has
nothing to do with hub slugs (found in the full suite, 2026-09-12, after
this file passed on its own).
"""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, update

import archive.main
from app.utils.gov_registry import classify, registry
from archive.db import crud, hub_slugs
from archive.db.engine import async_session
from archive.db.models import HubSlug, MeetingPage
from archive.utils.hub_aliases import hub_slug_aliases

client = TestClient(archive.main.app)


def _payload(external_id, url, *, jurisdiction, title, date):
    return {
        "platform": "granicus",
        "source_url": url,
        "external_id": external_id,
        "title": title,
        "date": date,
        "jurisdiction": jurisdiction,
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": [{"start": 0, "end": 1, "text": "hub slug freeze test"}],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }


async def _seed(external_id, **kwargs) -> str:
    url = f"https://example.com/hub-freeze/{external_id}"
    result = await crud.ingest_resolution(_payload(external_id, url, **kwargs), url)
    return result["slug"]


async def _backdate(gov_id: str, days: int) -> None:
    """Move a government's freeze clock back, the way the real one moves
    -- by the calendar, which a test cannot wait for."""
    async with async_session() as session:
        await session.execute(
            update(HubSlug)
            .where(HubSlug.gov_id == gov_id)
            .values(first_seen_at=datetime.now(timezone.utc) - timedelta(days=days))
        )
        await session.commit()


async def _row(gov_id: str):
    async with async_session() as session:
        return (
            await session.execute(
                select(
                    HubSlug.hub_slug, HubSlug.first_seen_at, HubSlug.frozen_at
                ).where(HubSlug.gov_id == gov_id)
            )
        ).first()


# --- the gate --------------------------------------------------------------


async def test_ingest_records_a_government_but_does_not_freeze_it_yet():
    """A brand-new government gets its row (the clock starts) and stays
    unfrozen, so the early pin/identity churn can still move its slug."""
    await _seed(
        "granicus:freeze-colma-1",
        jurisdiction="Colma, CA",
        title="Colma City Council",
        date="2016-01-05",
    )
    row = await _row("us:place:0614736")
    assert row is not None, "ingest recorded no hub_slugs row"
    assert row[0] == "colma-ca"
    assert row[2] is None, "a first-day government must not be frozen"


async def test_the_gate_needs_seven_days_AND_more_than_one_page():
    """Both halves of Ryan's gate, each tested on its own side. One page
    at eight days old does not freeze; the second page does."""
    await _seed(
        "granicus:freeze-colma-2",
        jurisdiction="Colma, CA",
        title="Colma Planning Commission",
        date="2016-01-12",
    )
    gov_id = "us:place:0614736"

    # Old enough, but check the page count half first by asking the gate
    # about a government that has a row and a single page.
    await _seed(
        "granicus:freeze-tehama-1",
        jurisdiction="Tehama, CA",
        title="Tehama City Council",
        date="2016-01-05",
    )
    await _backdate("us:place:0678106", days=8)
    async with async_session() as session:
        assert await hub_slugs.apply_gate(session, "us:place:0678106") is False
        await session.commit()
    assert (await _row("us:place:0678106"))[2] is None

    # Too new, with two pages: the other side of the gate.
    async with async_session() as session:
        assert await hub_slugs.apply_gate(session, gov_id) is False
        await session.commit()
    assert (await _row(gov_id))[2] is None

    # Both halves satisfied.
    await _backdate(gov_id, days=8)
    async with async_session() as session:
        assert await hub_slugs.apply_gate(session, gov_id) is True
        await session.commit()
    row = await _row(gov_id)
    assert row[2] is not None
    assert row[0] == "colma-ca"


async def test_an_unknown_placeholder_id_never_gets_a_stored_slug():
    """`rtr:unknown:<host>` is "we don't know whose meeting this is", not
    a government -- it has no hub today and must never get a stored one."""
    async with async_session() as session:
        await hub_slugs.record_government(
            session, "rtr:unknown:example.com", "example-com"
        )
        await session.commit()
    assert await _row("rtr:unknown:example.com") is None
    assert hub_slugs.frozen_hub_slug("rtr:unknown:example.com") is None


# --- what the freeze buys --------------------------------------------------


async def test_a_frozen_slug_survives_a_display_name_change(monkeypatch):
    """The case the freeze exists for. On 2026-09-11 one backfill run
    retired 35 hubs, 12 of them wrongly, because a government's slug was
    recomputed from its current name. With the slug frozen, the name can
    change and the URL cannot.
    """
    gov_id = "us:place:0665028"  # San Bruno, CA -- real, only used here
    await _seed(
        "granicus:freeze-sanbruno-1",
        jurisdiction="San Bruno, CA",
        title="San Bruno City Council",
        date="2016-01-05",
    )
    await _seed(
        "granicus:freeze-sanbruno-2",
        jurisdiction="San Bruno, CA",
        title="San Bruno Planning Commission",
        date="2016-01-12",
    )
    await _backdate(gov_id, days=8)
    async with async_session() as session:
        assert await hub_slugs.apply_gate(session, gov_id) is True
        await session.commit()
        await hub_slugs.refresh(session, force=True)

    # Now rename the government, exactly as a registry correction or the
    # WO-243 resolver regression would.
    renamed = registry.Government(
        gov_id=gov_id,
        gov_name="Town of San Bruno",
        gov_type=classify.MUNICIPALITY,
        state="CA",
    )
    monkeypatch.setattr(crud, "registry_governments", lambda: {gov_id: renamed})

    # The live computation moved...
    assert crud.live_hub_slug(gov_id, "San Bruno, CA") == "town-of-san-bruno-ca"
    # ...and the URL did not.
    assert crud.hub_slug_for_page(gov_id, "San Bruno, CA") == "san-bruno-ca"
    # The DISPLAY name is not frozen -- only the URL is.
    assert (
        crud.effective_jurisdiction(gov_id, "San Bruno, CA") == "Town of San Bruno, CA"
    )

    # End to end: the bookmarked URL still serves, the renamed one does not
    # exist (a rename after a freeze costs one alias row, by design).
    assert client.get("/j/san-bruno-ca").status_code == 200
    assert client.get("/j/town-of-san-bruno-ca").status_code == 404


async def test_a_retired_slug_alias_still_redirects_with_the_freeze_in_place():
    """`hub_slug_aliases.csv` carries forward unchanged -- the audit's §4
    says so, and the reader path still tries it after the frozen lookup
    and the live computation both miss. Read from the real committed file,
    same as tests/test_hub_aliases.py."""
    aliases = hub_slug_aliases()
    assert aliases, "the committed alias file is empty"
    # Any alias whose target is a hub with no live pages in THIS test
    # database still redirects -- the 301 is decided before any page
    # lookup, which is the property being checked.
    old_slug = sorted(aliases)[0]
    r = client.get(f"/j/{old_slug}", follow_redirects=False)
    assert r.status_code == 301
    assert r.headers["location"] == f"/j/{aliases[old_slug]}"


async def test_day_one_backfill_is_a_no_op_for_every_live_url():
    """§4's "Migration size" claim, checked rather than asserted: the
    frozen slug is DEFINED as today's computed slug, so recording and
    freezing every government in this database must leave every page's
    hub URL byte-identical.

    Seeds eight real registry rows first -- six small CA cities plus a
    county under BOTH of its real spellings, which is exactly the case
    `_hub_identity()`'s registry lookup exists to merge -- then runs over
    every government in the database, this file's and any other test
    file's alike.
    """
    for i, jurisdiction in enumerate(
        [
            "Orland, CA",
            "Biggs, CA",
            "Gustine, CA",
            "Dos Palos, CA",
            "Firebaugh, CA",
            "Huron, CA",
            "County of Glenn, CA",
            "Glenn County, CA",
        ]
    ):
        await _seed(
            f"granicus:freeze-dayone-{i}",
            jurisdiction=jurisdiction,
            title=f"{jurisdiction} City Council",
            date="2016-01-05",
        )
    async with async_session() as session:
        rows = (
            await session.execute(
                select(MeetingPage.gov_id, MeetingPage.jurisdiction)
                .where(MeetingPage.gov_id.is_not(None))
                .distinct()
            )
        ).all()
    governments = [
        (gov_id, jurisdiction)
        for gov_id, jurisdiction in rows
        if hub_slugs._usable(gov_id)
    ]
    assert len(governments) >= 7, "too few real governments seeded to mean anything"

    before = {
        gov_id: crud.hub_slug_for_page(gov_id, jurisdiction)
        for gov_id, jurisdiction in governments
    }
    async with async_session() as session:
        # Clear the rows ingest wrote as it went, so this really is the
        # one-time backfill's own situation: no rows at all, every
        # `first_seen_at` supplied from the government's oldest page. With
        # the rows left in place the insert is a no-op (ON CONFLICT DO
        # NOTHING, by design -- a clock once started is never restarted),
        # and nothing would freeze.
        await session.execute(delete(HubSlug))
        await session.commit()
    hub_slugs.reset_cache()
    async with async_session() as session:
        for gov_id, jurisdiction in governments:
            await hub_slugs.record_government(
                session,
                gov_id,
                crud.live_hub_slug(gov_id, jurisdiction),
                first_seen_at=datetime.now(timezone.utc) - timedelta(days=30),
            )
        await session.commit()
        await hub_slugs.refresh(session, force=True)

    after = {
        gov_id: crud.hub_slug_for_page(gov_id, jurisdiction)
        for gov_id, jurisdiction in governments
    }
    assert after == before

    # Exactly the governments with more than one page froze, and no
    # others. Without this the test would pass for the wrong reason -- a
    # backfill that froze nothing at all also changes no URL.
    async with async_session() as session:
        counts = dict(
            (
                await session.execute(
                    select(MeetingPage.gov_id, func.count())
                    .where(MeetingPage.gov_id.is_not(None))
                    .group_by(MeetingPage.gov_id)
                )
            ).all()
        )
    frozen = hub_slugs.frozen_hub_slugs()
    assert {g for g, _ in governments if g in frozen} == {
        g for g, _ in governments if counts.get(g, 0) >= hub_slugs.FREEZE_MIN_PAGES
    }
    assert frozen, "the backfill froze nothing at all"

    # Unfreeze again. The fixture DB is shared by the whole suite and not
    # reset per test (see tests/conftest.py), and leaving every government
    # frozen would make a later test's registry monkeypatch silently
    # meaningless rather than failing loudly.
    async with async_session() as session:
        await session.execute(update(HubSlug).values(frozen_at=None))
        await session.commit()
    hub_slugs.reset_cache()
