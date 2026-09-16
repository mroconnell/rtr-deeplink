"""Which pages a `/j/` hub shows -- WO-256, the audit's §5 rule.

A hub shows every page keyed to its own government, plus an un-keyed page
**only** when that page shares a tenant host with an already-keyed page of
the same government and the host is not a `MULTI_GOV_HOSTS` host. Never by
raw jurisdiction text.

The cases below are the ones
`docs/investigations/hub_architecture_audit.md` measured against the real
2026-09-11 export, reproduced at test scale:

  * Orem UT / Tooele UT / Box Elder County UT / Caledonia Township MI --
    four real hubs carrying 47 pages of unrelated `rtr:unknown` YouTube
    video that matched on raw text alone. Excluded now.
  * 31 un-keyed pages (20 blank, 11 placeholder) that sit on a host with
    exactly one real government on it. Included now.

Real DB integration against the shared SQLite fixture. Every jurisdiction
seeded here is a real place no other test file uses, and every meeting is
dated 2016 so it can never displace another test file's page from a
newest-first list (see tests/test_hub_slug_freeze.py's docstring for the
one that bit).
"""

from sqlalchemy import select, update

from archive.db import crud
from archive.db.engine import async_session
from archive.db.models import MeetingPage

# Orem's own Granicus tenant -- a single-government host. The YouTube host
# is in MULTI_GOV_HOSTS and must never adopt anything.
OREM_HOST = "https://oremut.granicus.com"
OREM_GOV_ID = "us:place:4957300"


def _payload(external_id, url, *, jurisdiction, title, platform="granicus"):
    return {
        "platform": platform,
        "source_url": url,
        "external_id": external_id,
        "title": title,
        "date": "2016-02-03",
        "jurisdiction": jurisdiction,
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": [{"start": 0, "end": 1, "text": "hub inclusion rule test"}],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }


async def _seed(external_id, url, **kwargs) -> str:
    result = await crud.ingest_resolution(_payload(external_id, url, **kwargs), url)
    return result["slug"]


async def _set_identity(slug: str, gov_id, jurisdiction=None) -> None:
    """Write an identity the resolver would not produce on its own.

    A blank-`gov_id` page is a real, measured state (198 of 8,222 pages)
    but it is the tier the resolver DECLINES to key, which a test payload
    cannot reliably provoke -- so it is set directly, the same way other
    test files set a column ingest does not expose.
    """
    values = {"gov_id": gov_id}
    if jurisdiction is not None:
        values["jurisdiction"] = jurisdiction
    async with async_session() as session:
        await session.execute(
            update(MeetingPage).where(MeetingPage.slug == slug).values(**values)
        )
        await session.commit()


async def _seed_orem():
    """Three real Orem pages on Orem's own Granicus tenant, plus the two
    un-keyed shapes the audit measured."""
    for i in range(3):
        await _seed(
            f"granicus:incl-orem-{i}",
            f"{OREM_HOST}/incl/{i}",
            jurisdiction="Orem, UT",
            title=f"Orem City Council {i}",
        )
    # The contamination case: an unrelated video on a MULTI_GOV_HOSTS host
    # whose stored jurisdiction text happens to read "Orem, UT".
    contaminant = await _seed(
        "youtube:incl-orem-yt",
        "https://www.youtube.com/watch?v=wo256incl1",
        jurisdiction="Orem, UT",
        title="Some other Orem video",
        platform="youtube",
    )
    await _set_identity(contaminant, "rtr:unknown:www.youtube.com")
    # The inclusion case: a blank-id page on Orem's own tenant host.
    adoptable = await _seed(
        "granicus:incl-orem-unkeyed",
        f"{OREM_HOST}/incl/unkeyed",
        jurisdiction="Orem, UT",
        title="Orem Work Session (unkeyed)",
    )
    await _set_identity(adoptable, None)
    return contaminant, adoptable


async def test_an_unknown_youtube_page_no_longer_rides_a_real_hub_by_text():
    contaminant, _adoptable = await _seed_orem()
    data = await crud.get_jurisdiction_hub_data("orem-ut")
    assert data is not None
    slugs = {p["slug"] for p in data["pages"]}
    assert contaminant not in slugs, (
        "an rtr:unknown YouTube page joined a real government's hub by raw text"
    )


async def test_an_unkeyed_page_on_the_governments_own_host_is_included():
    _contaminant, adoptable = await _seed_orem()
    data = await crud.get_jurisdiction_hub_data("orem-ut")
    assert data is not None
    slugs = {p["slug"] for p in data["pages"]}
    assert adoptable in slugs, (
        "a blank-gov_id page on this government's own single-government "
        "tenant host was not adopted"
    )
    # Three keyed pages plus the one adopted page, and nothing else.
    assert len(slugs) == 4


async def test_a_multi_government_host_adopts_nothing():
    """WO-210's rule, kept as the source of truth: `MULTI_GOV_HOSTS` hosts
    are never keyed by host, so an un-keyed page on one is never adopted
    even when a real government already has pages on that same host."""
    await _seed_orem()
    # Orem also publishes on YouTube -- a keyed page on the shared host.
    await _seed(
        "youtube:incl-orem-real-yt",
        "https://www.youtube.com/watch?v=wo256incl2",
        jurisdiction="Orem, UT",
        title="Orem City Council on YouTube",
        platform="youtube",
    )
    adoption, _unkeyed = await _unkeyed_membership()
    assert "www.youtube.com" not in adoption
    assert adoption.get("oremut.granicus.com") == OREM_GOV_ID


async def test_a_host_with_two_real_governments_adopts_nothing():
    """A shared tenant this code cannot split. Two governments on one
    host means no adoption at all -- guessing between them is exactly the
    failure the host rule exists to prevent."""
    host = "https://sharedtenant-wo256.granicus.com"
    await _seed(
        "granicus:incl-shared-a",
        f"{host}/a",
        jurisdiction="Ephraim, UT",
        title="Ephraim City Council",
    )
    await _seed(
        "granicus:incl-shared-b",
        f"{host}/b",
        jurisdiction="Manti, UT",
        title="Manti City Council",
    )
    stray = await _seed(
        "granicus:incl-shared-stray",
        f"{host}/stray",
        jurisdiction="Ephraim, UT",
        title="Shared tenant work session",
    )
    await _set_identity(stray, None)
    adoption, _unkeyed = await _unkeyed_membership()
    assert "sharedtenant-wo256.granicus.com" not in adoption
    data = await crud.get_jurisdiction_hub_data("ephraim-ut")
    assert data is not None
    assert stray not in {p["slug"] for p in data["pages"]}


async def test_an_unadopted_unkeyed_page_keeps_its_own_raw_text_hub():
    """No live URL disappears under the new rule. A page nothing adopts,
    whose slug no real government owns, still gets the hub its own stored
    text has always given it -- which is what its own /m/ page links to."""
    slug = await _seed(
        "granicus:incl-orphan",
        "https://orphan-wo256.granicus.com/1",
        jurisdiction="Wales, UT",
        title="Wales Town Council",
    )
    await _set_identity(slug, None)
    data = await crud.get_jurisdiction_hub_data("wales-ut")
    assert data is not None
    assert slug in {p["slug"] for p in data["pages"]}
    assert crud.hub_slug_for_page(None, "Wales, UT") == "wales-ut"


async def test_the_host_condition_does_not_match_a_lookalike_domain():
    """`https://{host}%` alone would match `https://oremut.granicus.com.
    elsewhere.test/...`. The condition is three explicit shapes for that
    reason -- checked against a real row rather than by reading the SQL."""
    await _seed_orem()
    lookalike = await _seed(
        "granicus:incl-lookalike",
        "https://oremut.granicus.com.elsewhere-wo256.test/1",
        jurisdiction="Orem, UT",
        title="Lookalike host meeting",
    )
    await _set_identity(lookalike, None)
    async with async_session() as session:
        matched = (
            await session.execute(
                select(MeetingPage.slug).where(
                    crud._host_url_condition({"oremut.granicus.com"})
                )
            )
        ).scalars()
        assert lookalike not in set(matched)


async def _unkeyed_membership():
    async with async_session() as session:
        return await crud._unkeyed_membership(session)
