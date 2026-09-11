"""Tests for `scripts/backfill_gov_id.py`'s WO-215 fix.

Rung 1b (WO-210, `app/utils/gov_registry/registry.py`'s `MULTI_GOV_HOSTS`)
answers tier `blank` -- gov_id `rtr:unknown:<host>` -- for EVERY page on a
shared host (YouTube, Vimeo, ClerkHQ, ...) that has no matching
per-video/channel/external-id pin, regardless of what identity the page
already carries. This backfill used to treat that answer as a real,
writable one:

  * defect 1 -- a page that already keyed to a real government at a tier
    the ladder produced BEFORE rung 1b existed (`registry`, `pinned`,
    `inferred`, `unverified`, `unresolved`) got overwritten with
    `rtr:unknown:<host>`;
  * defect 2 -- a `manual_override` row's `gov_id`/`gov_type` were
    rewritten too: only the jurisdiction string and the tier itself were
    protected here, not the identity.

Both confirmed live: a DRY RUN of this script against production
(2026-09-11) proposed exactly these downgrades on 825 (defect 1) and 228
(defect 2) real `www.youtube.com`/`youtube.com`/`youtu.be` rows before
this fix -- see `BACKLOG_DONE.md`'s WO-215 entry.

`boxcast.tv` is a real `MULTI_GOV_HOSTS` entry (`registry.py`) that no
other test file ingests a page against, chosen so `--hosts boxcast.tv`
here can never pick up another test's row and this suite's assertions
stay exact. Sioux Falls / Rapid City are the same real, registry-
confirmed South Dakota place ids `tests/test_ingest_gov_id.py` already
uses (`us_places.csv`) -- never invented.
"""

import sys

from sqlalchemy import select

from archive.db import crud
from archive.db.engine import async_session
from archive.db.models import MeetingPage
from scripts import backfill_gov_id

SIOUX_FALLS = "us:place:4659020"
RAPID_CITY = "us:place:4652980"


def _payload(**overrides) -> dict:
    payload = {
        "platform": "boxcast",
        "source_url": "https://boxcast.tv/channel/wo215-default",
        "external_id": "boxcast:wo215-default",
        "title": "Town Council Regular Meeting",
        "date": "2026-09-01",
        "jurisdiction": None,
        "video_url": None,
        "video_format": None,
        "segments": [],
        "agenda_items": [],
        "transcript_language": None,
        "transcript_warnings": [],
    }
    payload.update(overrides)
    return payload


async def _seed(
    source_url: str, external_id: str, *, gov_id: str, confidence: str
) -> str:
    """Create a page the ordinary way -- a caller-supplied `gov_id`,
    which short-circuits the ladder entirely
    (`archive/db/crud.py`'s `_caller_pinned_match()`) and always lands on
    tier `pinned` -- then hand-set the tier to simulate either a page
    keyed BEFORE rung 1b existed (`registry`) or a human override
    (`manual_override`), the two real shapes defect 1 and defect 2
    protect. Same pattern as
    tests/test_jurisdiction_backfill_apply.py's `_seed_stale()`.
    """
    result = await crud.ingest_resolution(
        _payload(source_url=source_url, external_id=external_id, gov_id=gov_id),
        source_url,
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


async def _get(slug: str) -> dict:
    return await crud.get_page_by_slug(slug)


async def _run_backfill(monkeypatch, report_path) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "backfill_gov_id.py",
            "--hosts",
            "boxcast.tv",
            "--apply",
            "--report",
            str(report_path),
        ],
    )
    await backfill_gov_id.main()


async def test_a_registry_tier_page_keeps_its_gov_id_when_the_fresh_answer_is_blank(
    tmp_path, monkeypatch
):
    """Defect 1. `boxcast.tv` has no matching per-video pin for this
    page, so a fresh resolve of ANY jurisdiction string on it lands on
    `blank` (rung 1b) -- "no matching pin," not "this page has no
    government." A page already keyed to Sioux Falls, SD at the
    `registry` tier must keep that id and that tier.
    """
    slug = await _seed(
        "https://boxcast.tv/channel/wo215-defect1",
        "boxcast:wo215-defect1",
        gov_id=SIOUX_FALLS,
        confidence="registry",
    )
    await _run_backfill(monkeypatch, tmp_path / "defect1.csv")
    page = await _get(slug)
    assert page["gov_id"] == SIOUX_FALLS
    assert page["jurisdiction_confidence"] == "registry"


async def test_a_manual_override_row_keeps_its_gov_id_regardless_of_the_fresh_tier(
    tmp_path, monkeypatch
):
    """Defect 2. A human already said this page is Rapid City, SD --
    the one tier this whole sweep must never recompute, gov_id/gov_type
    included. Previously only the jurisdiction string and the tier
    itself were protected here; gov_id/gov_type were rewritten the
    moment the fresh resolve (rung 1b, since `boxcast.tv` has no
    matching per-video pin) landed on `blank`.
    """
    slug = await _seed(
        "https://boxcast.tv/channel/wo215-defect2",
        "boxcast:wo215-defect2",
        gov_id=RAPID_CITY,
        confidence="manual_override",
    )
    await _run_backfill(monkeypatch, tmp_path / "defect2.csv")
    page = await _get(slug)
    assert page["gov_id"] == RAPID_CITY
    assert page["jurisdiction_confidence"] == "manual_override"
