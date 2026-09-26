"""WO-1083: the TTL + single-flight cache in front of `crud._hub_groups()`
(`archive/db/hub_groups_cache.py`), built after the 2026-09-26 incident
where a crawler burst against `/j/<slug>` ran that function's uncached
GROUP BY dozens of times a second, exhausted the Postgres connection
pool, and took the whole Archive down (every route, not just `/j/`).

Two layers of test:

  * unit tests against `hub_groups_cache.get_or_compute()`/`invalidate()`
    directly, with a counting fake instead of real SQL -- hit, miss,
    expiry, and the single-flight guarantee (50 concurrent misses on one
    key run the underlying computation exactly once);
  * an integration test against `crud._hub_groups()` and
    `crud.get_jurisdiction_hub_data()` over the shared SQLite fixture,
    confirming a real ingest is visible immediately (the cache is
    invalidated, not just left to expire) and that `bypass_cache=True`
    always recomputes.

Every seeded jurisdiction here is a real, unambiguous place no other test
file uses (Nogales, AZ), so this file is order-independent against the
shared fixture DB the rest of the hub tests share (see
tests/test_jurisdiction_hubs.py's own docstring for why that matters).
"""

import asyncio
import os

import pytest

from archive.db import crud, hub_groups_cache


def setup_function(_fn):
    # Every test starts from a clean cache: an entry left over from a
    # previous test file (or a previous test in this one) would otherwise
    # make a "miss" assertion pass for the wrong reason.
    hub_groups_cache.invalidate()


def teardown_function(_fn):
    hub_groups_cache.invalidate()
    os.environ.pop("HUB_GROUPS_CACHE_TTL_SECONDS", None)


# --- Unit tests: hit / miss / expiry / single-flight ---------------------


@pytest.mark.asyncio
async def test_second_call_is_a_cache_hit_and_does_not_recompute():
    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        return {"n": calls}

    first = await hub_groups_cache.get_or_compute("t1", compute)
    second = await hub_groups_cache.get_or_compute("t1", compute)

    assert first == {"n": 1}
    assert second == {"n": 1}, "the second call should be served from cache"
    assert calls == 1


@pytest.mark.asyncio
async def test_invalidate_forces_a_fresh_compute():
    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        return {"n": calls}

    await hub_groups_cache.get_or_compute("t2", compute)
    hub_groups_cache.invalidate("t2")
    result = await hub_groups_cache.get_or_compute("t2", compute)

    assert result == {"n": 2}
    assert calls == 2


@pytest.mark.asyncio
async def test_invalidate_with_no_key_clears_every_entry():
    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        return calls

    await hub_groups_cache.get_or_compute("a", compute)
    await hub_groups_cache.get_or_compute("b", compute)
    hub_groups_cache.invalidate()

    await hub_groups_cache.get_or_compute("a", compute)
    await hub_groups_cache.get_or_compute("b", compute)

    assert calls == 4, "clearing with no key should drop every cached key"


@pytest.mark.asyncio
async def test_expired_entry_is_recomputed():
    os.environ["HUB_GROUPS_CACHE_TTL_SECONDS"] = "0.05"
    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        return calls

    first = await hub_groups_cache.get_or_compute("expiry", compute)
    await asyncio.sleep(0.15)
    second = await hub_groups_cache.get_or_compute("expiry", compute)

    assert first == 1
    assert second == 2, "a call after the TTL elapsed should see fresh data"
    assert calls == 2


@pytest.mark.asyncio
async def test_ttl_zero_disables_caching():
    os.environ["HUB_GROUPS_CACHE_TTL_SECONDS"] = "0"
    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        return calls

    await hub_groups_cache.get_or_compute("no-cache", compute)
    await hub_groups_cache.get_or_compute("no-cache", compute)

    assert calls == 2


@pytest.mark.asyncio
async def test_fifty_concurrent_misses_share_one_computation():
    """The single-flight guarantee this module exists for: a burst of
    concurrent requests hitting a cold (or just-expired) cache must not
    fan out into N real queries -- that fan-out is exactly what took the
    connection pool down on 2026-09-26."""
    calls = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def compute():
        nonlocal calls
        calls += 1
        started.set()
        # Hold every concurrent caller here until they've all arrived,
        # so this reproduces a real burst rather than 50 sequential
        # cache misses that happen not to overlap.
        await release.wait()
        return {"calls": calls}

    async def call():
        return await hub_groups_cache.get_or_compute("burst", compute)

    tasks = [asyncio.ensure_future(call()) for _ in range(50)]
    await started.wait()
    # Give every other task a chance to reach get_or_compute() and join
    # the in-flight future before it's released.
    await asyncio.sleep(0.05)
    release.set()
    results = await asyncio.gather(*tasks)

    assert calls == 1, "50 concurrent misses should run the query exactly once"
    assert all(r == {"calls": 1} for r in results)


@pytest.mark.asyncio
async def test_an_exception_is_not_cached_and_does_not_wedge_later_calls():
    attempts = 0

    async def flaky():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("boom")
        return "ok"

    with pytest.raises(RuntimeError):
        await hub_groups_cache.get_or_compute("flaky", flaky)

    # A failed compute must not leave a stale in-flight future behind --
    # the next call should try again, not hang or re-raise forever.
    result = await hub_groups_cache.get_or_compute("flaky", flaky)
    assert result == "ok"
    assert attempts == 2


# --- Integration: crud._hub_groups() / get_jurisdiction_hub_data() -------


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
        "segments": [{"start": 0, "end": 1, "text": "hub cache test"}],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }


async def _seed(external_id, **kwargs) -> str:
    url = f"https://example.com/hub-cache/{external_id}"
    result = await crud.ingest_resolution(_payload(external_id, url, **kwargs), url)
    return result["slug"]


@pytest.mark.asyncio
async def test_ingest_invalidates_the_cache_immediately():
    """A page ingested just now must show up on its hub on the very next
    request -- not up to HUB_GROUPS_CACHE_TTL_SECONDS later. This is the
    freshness guarantee the incident write-up promises: ingest/override
    paths invalidate rather than waiting out the TTL."""
    from archive.db.engine import async_session

    await _seed(
        "nogales-1",
        jurisdiction="Nogales, AZ",
        title="Nogales City Council",
        date="2026-03-01",
    )
    async with async_session() as session:
        groups = await crud._hub_groups(session)
    before = next((g for g in groups.values() if g["display"] == "Nogales, AZ"), None)
    assert before is not None
    assert before["page_count"] == 1

    # This second ingest must be visible immediately, not after the TTL.
    await _seed(
        "nogales-2",
        jurisdiction="Nogales, AZ",
        title="Nogales Planning Commission",
        date="2026-03-08",
    )
    async with async_session() as session:
        groups = await crud._hub_groups(session)
    after = next((g for g in groups.values() if g["display"] == "Nogales, AZ"), None)
    assert after is not None
    assert after["page_count"] == 2, (
        "ingest should invalidate the hub-groups cache, not wait out its TTL"
    )


@pytest.mark.asyncio
async def test_bypass_cache_always_recomputes():
    from archive.db.engine import async_session

    await _seed(
        "nogales-3",
        jurisdiction="Nogales, AZ",
        title="Nogales Parks Board",
        date="2026-03-15",
    )
    async with async_session() as session:
        # Prime the cache.
        await crud._hub_groups(session)

    # Mutate the underlying data WITHOUT going through a path that
    # invalidates the cache, to isolate bypass_cache from the ingest-side
    # invalidation tested above.
    hub_groups_cache._entries["hub_groups"].value["__marker__"] = "stale-probe"

    async with async_session() as session:
        cached = await crud._hub_groups(session)
        assert "__marker__" in cached, "sanity: this call should hit the cache"

        fresh = await crud._hub_groups(session, bypass_cache=True)
        assert "__marker__" not in fresh, (
            "bypass_cache=True should recompute rather than reuse the cache"
        )


@pytest.mark.asyncio
async def test_stale_cache_returns_page_count_get_jurisdiction_hub_data():
    """End-to-end through the same function `/j/{slug}` calls: a page
    added after the cache is warm doesn't appear until invalidated (here,
    via ingest's own invalidation, matching production behaviour) --
    documents the staleness trade-off in the same terms a reader would
    see it (total_pages on the hub page)."""
    await _seed(
        "nogales-4",
        jurisdiction="Nogales, AZ",
        title="Nogales Library Board",
        date="2026-03-22",
    )
    from archive.utils.jurisdiction_format import jurisdiction_hub_slug

    hub_slug = jurisdiction_hub_slug("Nogales, AZ")

    data = await crud.get_jurisdiction_hub_data(hub_slug)
    assert data is not None
    before_count = data["total_pages"]

    await _seed(
        "nogales-5",
        jurisdiction="Nogales, AZ",
        title="Nogales Traffic Commission",
        date="2026-03-29",
    )
    data = await crud.get_jurisdiction_hub_data(hub_slug)
    assert data["total_pages"] == before_count + 1, (
        "ingest's cache invalidation should be visible through the same "
        "function /j/{slug} calls"
    )
