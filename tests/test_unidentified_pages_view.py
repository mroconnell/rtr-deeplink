"""GET /internal/unidentified-pages -- WO-256, the audit's §6.

The per-host view of every archived page with no government yet, which
replaces the "pull the export and grep it" step every identity work order
has repeated by hand. Read-only, token-gated, no schema change.

Real DB integration against the shared SQLite fixture. Hosts here are
`*-wo256v.test`-shaped so they cannot collide with another test file's
seeds, and every meeting is dated 2016 so it can never displace another
file's page from a newest-first list.
"""

import os

from fastapi.testclient import TestClient
from sqlalchemy import update

import archive.main
from archive.db import crud
from archive.db.engine import async_session
from archive.db.models import MeetingPage

client = TestClient(archive.main.app)
TOKEN = os.environ.get("ARCHIVE_INGEST_TOKEN", "test-token")
AUTH = {"Authorization": f"Bearer {TOKEN}"}

SINGLE_HOST = "singlegov-wo256v.test"
SHARED_HOST = "twogovs-wo256v.test"


def _payload(external_id, url, *, jurisdiction, title, platform="granicus"):
    return {
        "platform": platform,
        "source_url": url,
        "external_id": external_id,
        "title": title,
        "date": "2016-04-05",
        "jurisdiction": jurisdiction,
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": [{"start": 0, "end": 1, "text": "unidentified view test"}],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }


async def _seed(external_id, url, **kwargs) -> str:
    result = await crud.ingest_resolution(_payload(external_id, url, **kwargs), url)
    return result["slug"]


async def _set_gov_id(slug: str, gov_id) -> None:
    async with async_session() as session:
        await session.execute(
            update(MeetingPage).where(MeetingPage.slug == slug).values(gov_id=gov_id)
        )
        await session.commit()


async def _seed_all():
    # A host with exactly one real government and two un-keyed pages --
    # the cheap case the audit counted 161 of.
    await _seed(
        "granicus:unid-single-keyed",
        f"https://{SINGLE_HOST}/1",
        jurisdiction="Hurricane, UT",
        title="Hurricane City Council",
    )
    blank = await _seed(
        "granicus:unid-single-blank",
        f"https://{SINGLE_HOST}/2",
        jurisdiction="Hurricane, UT",
        title="Hurricane work session",
    )
    await _set_gov_id(blank, None)
    placeholder = await _seed(
        "granicus:unid-single-placeholder",
        f"https://{SINGLE_HOST}/3",
        jurisdiction="Hurricane, UT",
        title="Hurricane special meeting",
    )
    await _set_gov_id(placeholder, f"rtr:unknown:{SINGLE_HOST}")

    # A host with two real governments: nobody adopts, somebody has to pin.
    await _seed(
        "granicus:unid-shared-a",
        f"https://{SHARED_HOST}/a",
        jurisdiction="Enoch, UT",
        title="Enoch City Council",
    )
    await _seed(
        "granicus:unid-shared-b",
        f"https://{SHARED_HOST}/b",
        jurisdiction="Parowan, UT",
        title="Parowan City Council",
    )
    stray = await _seed(
        "granicus:unid-shared-stray",
        f"https://{SHARED_HOST}/stray",
        jurisdiction="Enoch, UT",
        title="Shared host work session",
    )
    await _set_gov_id(stray, None)

    # A multi-government host: per-video pin only, never by host.
    yt = await _seed(
        "youtube:unid-yt",
        "https://www.youtube.com/watch?v=wo256view1",
        jurisdiction="",
        title="Unidentified YouTube meeting",
        platform="youtube",
    )
    await _set_gov_id(yt, "rtr:unknown:www.youtube.com")
    return {"blank": blank, "placeholder": placeholder, "stray": stray, "yt": yt}


async def test_the_view_is_token_gated_and_404s_without_one():
    r = client.get("/internal/unidentified-pages")
    assert r.status_code == 404
    assert client.get("/internal/unidentified-pages", headers=AUTH).status_code == 200


async def test_a_single_government_host_names_the_government_that_adopts_it():
    await _seed_all()
    r = client.get(f"/internal/unidentified-pages?host={SINGLE_HOST}", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["total_hosts"] == 1
    row = body["hosts"][0]
    assert row["host"] == SINGLE_HOST
    assert row["pages"] == 2
    assert (row["blank_gov_id"], row["placeholder_gov_id"]) == (1, 1)
    assert row["multi_government_host"] is False
    assert row["already_keyed_governments"] == ["us:place:4937170"]  # Hurricane, UT
    assert row["adopted_by"] == "us:place:4937170"
    # Examples carry enough to recognise the government by eye.
    assert row["examples"] and set(row["examples"][0]) >= {
        "slug",
        "title",
        "source_url",
        "gov_id",
    }


async def test_a_host_with_two_governments_adopts_nobody():
    await _seed_all()
    row = client.get(
        f"/internal/unidentified-pages?host={SHARED_HOST}", headers=AUTH
    ).json()["hosts"][0]
    assert len(row["already_keyed_governments"]) == 2
    assert row["adopted_by"] is None


async def test_a_multi_government_host_is_flagged_and_never_adopted():
    await _seed_all()
    row = client.get(
        "/internal/unidentified-pages?host=www.youtube.com", headers=AUTH
    ).json()["hosts"][0]
    assert row["multi_government_host"] is True
    assert row["adopted_by"] is None


async def test_hosts_are_ordered_biggest_first_and_totals_add_up():
    await _seed_all()
    body = client.get("/internal/unidentified-pages", headers=AUTH).json()
    counts = [h["pages"] for h in body["hosts"]]
    assert counts == sorted(counts, reverse=True)
    assert body["total_pages"] == sum(counts)
    assert body["total_hosts"] == len(body["hosts"])
    hosts = {h["host"] for h in body["hosts"]}
    assert {SINGLE_HOST, SHARED_HOST, "www.youtube.com"} <= hosts
