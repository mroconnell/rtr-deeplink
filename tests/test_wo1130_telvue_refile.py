"""WO-1130: `scripts/backfill_gov_id.py` re-files TelVue pages filed
before WO-1100 under the government their own title names.

Before WO-1100 a whole-customer TelVue pin was applied first, and the
page's stored `jurisdiction` was rewritten to the pin's government. So a
re-resolve from that stored string only reproduced the pin. The backfill
now re-reads a TelVue page's name from its stored title, through the
same `meeting_name_from_title()` the adapter uses.

The URLs, titles and pins are real: the Centreville, Queen Anne's,
Derry and Pierre meetings from WO-1100's saved pages
(`tests/fixtures/telvue/wo1100/`), all five checked live in production
on 2026-09-26. Only each page's pre-WO-1100 filing is simulated (a
caller `gov_id` of the pin's government, which is what the old rung 1b
produced). Synthetic: media ids 1047512 and 1047513 (the override and
dry-run cases) are not real meetings; they only need to be distinct
pages on Queen Anne's real org token.
"""

import shutil
import sys

import pytest
from sqlalchemy import select

from archive.db import crud
from archive.db.engine import async_session
from archive.db.models import MeetingPage
from archive.utils import hub_aliases
from scripts import backfill_gov_id

QUEEN_ANNES = "us:county:24035"
CENTREVILLE = "us:place:2414950"
DERRY_TOWN = "us:cousub:3301517940"
DERRY_SCHOOLS = "us:sd:3302610"
PIERRE_CITY = "us:place:4649600"
PIERRE_SCHOOLS = "us:sd:4655260"

QA_TOKEN = "AbfNhigIqnG-4roGCxaFupXEKfme9dfT"
DERRY_TOKEN = "CXN6V2zmqTebSQfLjvlDzEql3BwiQh_l"
PIERRE_TOKEN = "5nQYx7H7WpbP8AVWnkzXsWu69pAXI7Yq"


@pytest.fixture(autouse=True)
def _private_alias_file(tmp_path, monkeypatch):
    # `--apply` retires hubs into `hub_slug_aliases.csv`; on this tiny
    # database every old hub looks unowned. Keep those writes off the
    # real file (same pattern as tests/test_hub_alias_repair.py).
    alias_file = tmp_path / "hub_slug_aliases.csv"
    shutil.copy(hub_aliases.ALIAS_FILE, alias_file)
    monkeypatch.setattr(hub_aliases, "ALIAS_FILE", alias_file)


async def _seed_old_filing(
    token: str, media_id: int, title: str, *, gov_id: str, confidence="pinned"
) -> str:
    url = f"https://videoplayer.telvue.com/player/{token}/media/{media_id}"
    result = await crud.ingest_resolution(
        {
            "platform": "telvue",
            "source_url": url,
            "title": title,
            "date": "2026-09-17",
            "jurisdiction": None,
            "video_url": None,
            "video_format": None,
            "segments": [],
            "agenda_items": [],
            "transcript_language": None,
            "transcript_warnings": [],
            "gov_id": gov_id,
        },
        url,
    )
    async with async_session() as session:
        page = (
            await session.execute(
                select(MeetingPage).where(MeetingPage.slug == result["slug"])
            )
        ).scalar_one()
        page.jurisdiction_confidence = confidence
        await session.commit()
    return result["slug"]


async def _run(monkeypatch, *extra) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["backfill_gov_id.py", "--hosts", "videoplayer.telvue.com", *extra],
    )
    await backfill_gov_id.main()


async def test_old_telvue_pages_move_to_the_government_their_title_names(
    monkeypatch,
):
    centreville = await _seed_old_filing(
        QA_TOKEN, 1047511, "Centreville Town Council || 09/17/2026", gov_id=QUEEN_ANNES
    )
    derry = await _seed_old_filing(
        DERRY_TOKEN, 1047520, "School Board Meeting", gov_id=DERRY_TOWN
    )
    pierre = await _seed_old_filing(
        PIERRE_TOKEN, 1045603, "Pierre School Board", gov_id=PIERRE_CITY
    )

    await _run(monkeypatch, "--apply")

    assert (await crud.get_page_by_slug(centreville))["gov_id"] == CENTREVILLE
    assert (await crud.get_page_by_slug(derry))["gov_id"] == DERRY_SCHOOLS
    assert (await crud.get_page_by_slug(pierre))["gov_id"] == PIERRE_SCHOOLS


async def test_a_title_naming_no_one_keeps_the_customer_pin(monkeypatch):
    slug = await _seed_old_filing(
        QA_TOKEN,
        1047333,
        "County Commissioners Meeting || 09/21/2026",
        gov_id=QUEEN_ANNES,
    )
    await _run(monkeypatch, "--apply")
    assert (await crud.get_page_by_slug(slug))["gov_id"] == QUEEN_ANNES


async def test_a_manual_override_is_never_moved(monkeypatch):
    slug = await _seed_old_filing(
        QA_TOKEN,
        1047512,
        "Centreville Town Council || 09/03/2026",
        gov_id=QUEEN_ANNES,
        confidence="manual_override",
    )
    await _run(monkeypatch, "--apply")
    assert (await crud.get_page_by_slug(slug))["gov_id"] == QUEEN_ANNES


async def test_dry_run_writes_nothing(monkeypatch):
    slug = await _seed_old_filing(
        QA_TOKEN,
        1047513,
        "Centreville Town Council || 08/20/2026",
        gov_id=QUEEN_ANNES,
    )
    await _run(monkeypatch)
    assert (await crud.get_page_by_slug(slug))["gov_id"] == QUEEN_ANNES
