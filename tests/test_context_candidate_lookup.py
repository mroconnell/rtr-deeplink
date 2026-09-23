"""Read-only lookup on isolated SQLite, never network calls.

The database rows and contradictory combinations here are SYNTHETIC branch
payloads, not claims of real production conflicts or missing recordings.
Meeting facts/URLs come from the published Context examples recorded in
CONTEXT_PIPELINE_PLAN.md and fixture-verified platform URLs in test_granicus,
test_civicclerk and test_vimeo. No candidate Sheet has been supplied.
"""

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from archive.context.lookup import evaluate_candidate, recording_identity
from archive.db.models import Base, MeetingPage, MeetingPageUrlAlias, TranscriptVersion
from app.utils.url_normalize import normalize_url

SAN_DIEGO = (
    "city-of-san-diego-ca-2026-08-19-public-safety-and-livable-neighborhoods-committe"
)
INDIANAPOLIS = "indianapolis-in-2026-09-09-public-safety-criminal-justice-committee"
FOUNTAIN = "https://fountainvalley.granicus.com/MediaPlayer.php?clip_id=607"
SALISBURY = "https://vimeo.com/1212025580"
EMPORIA = "https://emporiaks.portal.civicclerk.com/event/585/media"


@pytest.fixture
async def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'lookup.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


async def page(db, *, slug=SAN_DIEGO, url=FOUNTAIN, **kwargs):
    identity = recording_identity(url)
    record = MeetingPage(
        slug=slug,
        source_url_normalized=normalize_url(url),
        platform=identity[0] if identity else "unknown",
        external_id=identity[1] if identity else None,
        **kwargs,
    )
    db.add(record)
    await db.commit()
    return record


@pytest.mark.parametrize(
    "url, expected",
    [
        (FOUNTAIN, ("granicus", "granicus:fountainvalley.granicus.com:607")),
        (
            "https://fountainvalley.granicus.com/player/clip/607",
            ("granicus", "granicus:fountainvalley.granicus.com:607"),
        ),
        (EMPORIA, ("civicclerk", "civicclerk:emporiaks.portal.civicclerk.com:585")),
        (SALISBURY, ("vimeo", "vimeo:1212025580")),
        (
            "https://player.vimeo.com/video/1212025580?h=abcdef",
            ("vimeo", "vimeo:1212025580"),
        ),
        (
            "https://www.youtube.com/watch?v=5LZqoNDRMYk",
            ("youtube", "youtube:5LZqoNDRMYk"),
        ),
        ("https://youtu.be/5LZqoNDRMYk", ("youtube", "youtube:5LZqoNDRMYk")),
    ],
)
def test_verified_recording_identifiers(url, expected):
    assert recording_identity(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://vimeo.com/event/1212025580",
        "https://vimeo.com/showcase/8925576",
        "https://fountainvalley.granicus.com/",
        "https://emporiaks.portal.civicclerk.com/",
        "https://www.youtube.com/embed/videoseries?list=5LZqoNDRMYk",
        # Synthetic adversarial URLs test host/path scoping, not real platform facts.
        "https://example.com/youtube.com/watch?v=5LZqoNDRMYk",
        "https://www.youtube.com/redirect?next=youtube.com/watch?v=5LZqoNDRMYk",
        "https://www.youtube.com/watch?v=5LZqoNDRMYk&v=zJKrMk-uuSw",
        "https://vimeo.com.evil.example/1212025580",
    ],
)
def test_listing_and_ambiguous_urls_have_no_recording_identity(url):
    assert recording_identity(url) is None


async def test_exact_slug_missing_metadata_matches_and_is_read_only(db):
    stored = await page(
        db, date="2026-08-19", gov_id="us:place:0666000", jurisdiction="San Diego, CA"
    )
    await db.refresh(stored)
    before = dict(stored.__dict__)
    result = await evaluate_candidate(
        [{"rtr_link": f"/m/{SAN_DIEGO}?t=9866"}], session=db
    )
    assert (result.outcome, result.next_action, result.meeting_page_id) == (
        "matched",
        "moment_needed",
        stored.id,
    )
    assert result.page_snapshot["has_transcript"] is False
    assert result.page_snapshot["duration_seconds"] is None
    assert dict(stored.__dict__) == before
    assert not db.new and not db.dirty
    assert await db.scalar(select(func.count()).select_from(TranscriptVersion)) == 0


async def test_stored_wrapper_alias_and_equivalent_urls_match(db):
    stored = await page(db)
    # Synthetic alias association using a real fixture's CivicPlus wrapper URL.
    wrapper = "https://nc-durham.civicplus.com/AgendaCenter/City-Council-4"
    db.add(
        MeetingPageUrlAlias(
            url_normalized=normalize_url(wrapper), meeting_page_id=stored.id
        )
    )
    await db.commit()
    result = await evaluate_candidate(
        [
            {"recording_url": wrapper},
            {"recording_url": FOUNTAIN},
            {
                "recording_url": "https://fountainvalley.granicus.com/player/clip/607?view_id=1"
            },
        ],
        session=db,
    )
    assert result.meeting_page_id == stored.id
    assert result.outcome == "matched"


async def test_tenant_namespace_never_cross_matches(db):
    await page(db)
    # Synthetic equal clip number on two real Granicus tenant namespaces.
    other = "https://cityoftacoma.granicus.com/player/clip/607"
    result = await evaluate_candidate([{"recording_url": other}], session=db)
    assert result.next_action == "ingest_needed"
    assert result.meeting_page_id is None


async def test_conflicting_rtr_and_source_links(db):
    await page(db)
    await page(db, slug=INDIANAPOLIS, url=SALISBURY)
    result = await evaluate_candidate(
        [{"rtr_link": f"/m/{SAN_DIEGO}", "recording_url": SALISBURY}], session=db
    )
    assert (result.outcome, result.next_action) == ("conflict", "conflict")
    assert len(result.possible_pages) == 2
    assert result.meeting_page_id is None


async def test_duplicate_platform_records_are_ambiguous(db):
    await page(db)
    await page(
        db, slug=INDIANAPOLIS, url="https://fountainvalley.granicus.com/player/clip/607"
    )
    result = await evaluate_candidate([{"recording_url": FOUNTAIN}], session=db)
    assert result.outcome == "ambiguous"
    assert result.next_action == "resolve_needed"
    assert len(result.possible_pages) == 2


@pytest.mark.parametrize(
    "field, value1, value2",
    [
        ("meeting_date", "2026-08-19", "2026-09-09"),
        (
            "meeting_body",
            "Public Safety and Livable Neighborhoods Committee",
            "Public Safety & Criminal Justice Committee",
        ),
        ("gov_id", "us:place:0666000", "us:place:1836003"),
        ("state", "CA", "IN"),
        ("jurisdiction", "San Diego", "Indianapolis"),
    ],
)
async def test_conflicting_active_metadata_cannot_match(db, field, value1, value2):
    await page(db)
    result = await evaluate_candidate(
        [
            {"recording_url": FOUNTAIN, field: value1},
            {"recording_url": FOUNTAIN, field: value2},
        ],
        session=db,
    )
    assert result.outcome == "conflict"
    assert result.meeting_page_id is None


async def test_date_disagrees_with_stored_record(db):
    await page(db, date="2026-08-19")
    result = await evaluate_candidate(
        [{"recording_url": FOUNTAIN, "meeting_date": "2026-09-09"}], session=db
    )
    assert result.outcome == "conflict"


async def test_consolidated_government_ids_are_equivalent(db):
    stored = await page(
        db,
        slug=INDIANAPOLIS,
        gov_id="us:place:1836003",
        jurisdiction="Indianapolis, IN",
    )
    result = await evaluate_candidate(
        [
            {
                "recording_url": FOUNTAIN,
                "gov_id": "us:county:18097",
                "jurisdiction": "Marion County",
            },
            {
                "gov_id": "us:place:1836003",
                "jurisdiction": "Indianapolis",
                "state": "IN",
            },
        ],
        session=db,
    )
    assert result.outcome == "matched"
    assert result.meeting_page_id == stored.id


@pytest.mark.parametrize("count", [1, 2])
async def test_metadata_suggestions_never_exact_even_one_page(db, count):
    await page(db, date="2026-08-19", gov_id="us:place:0666000")
    if count == 2:
        await page(
            db,
            slug=INDIANAPOLIS,
            url=SALISBURY,
            date="2026-08-19",
            gov_id="us:place:0666000",
        )
    result = await evaluate_candidate(
        [
            {
                "gov_id": "us:place:0666000",
                "meeting_date": "2026-08-19",
                "meeting_body": "Public Safety and Livable Neighborhoods Committee",
            }
        ],
        session=db,
    )
    assert len(result.possible_pages) == count
    assert result.next_action == "resolve_needed"
    assert result.meeting_page_id is None


@pytest.mark.parametrize(
    "claim, action",
    [
        ({}, "resolve_needed"),
        ({"recording_url": "https://www.sandiego.gov/"}, "resolve_needed"),
        ({"recording_url": "https://vimeo.com/showcase/8925576"}, "resolve_needed"),
        ({"recording_url": SALISBURY}, "ingest_needed"),
        ({"rtr_link": f"/m/{SAN_DIEGO}"}, "resolve_needed"),
        (
            {
                "gov_id": "us:place:0666000",
                "meeting_date": "2026-08-19",
                "meeting_body": "Public Safety and Livable Neighborhoods Committee",
            },
            "recording_needed",
        ),
    ],
)
async def test_missing_identifiers_are_not_archive_absence(db, claim, action):
    result = await evaluate_candidate([claim], session=db)
    assert result.next_action == action


async def test_different_unarchived_recordings_conflict(db):
    result = await evaluate_candidate(
        [
            {"recording_url": "https://youtu.be/5LZqoNDRMYk"},
            {"recording_url": "https://www.youtube.com/shorts/zJKrMk-uuSw"},
        ],
        session=db,
    )
    assert result.next_action == "conflict"


async def test_unknown_competing_url_blocks_existing_match(db):
    await page(db)
    result = await evaluate_candidate(
        [
            {"recording_url": FOUNTAIN},
            {"recording_url": "https://www.sandiego.gov/"},
        ],
        session=db,
    )
    assert result.next_action == "resolve_needed"
    assert result.meeting_page_id is None


async def test_old_slug_remains_evidence_but_exact_recording_can_match(db):
    stored = await page(db)
    result = await evaluate_candidate(
        [{"recording_url": FOUNTAIN, "rtr_link": f"/m/{INDIANAPOLIS}"}], session=db
    )
    assert result.meeting_page_id == stored.id
    assert any(e["kind"] == "unresolved_rtr_link" for e in result.evidence)


async def test_database_failure_propagates_for_store_to_mark_failed(db):
    async with db.bind.begin() as connection:
        await connection.run_sync(MeetingPageUrlAlias.__table__.drop)
    with pytest.raises(OperationalError):
        await evaluate_candidate([{"recording_url": FOUNTAIN}], session=db)


async def test_lookup_never_flushes_callers_pending_writes(db):
    await page(db)
    pending = MeetingPage(
        slug=INDIANAPOLIS, platform="vimeo", source_url_normalized=SALISBURY
    )
    db.add(pending)
    result = await evaluate_candidate([{"recording_url": FOUNTAIN}], session=db)
    assert result.outcome == "matched"
    assert pending.id is None
    assert pending in db.new


async def test_metadata_suggestion_count_is_bounded(db):
    # Synthetic duplicates of a real published date/government test the cap;
    # these rows do not assert that 25 such meetings actually happened.
    for index in range(25):
        await page(
            db,
            slug=f"{SAN_DIEGO}-{index}",
            date="2026-08-19",
            gov_id="us:place:0666000",
        )
    result = await evaluate_candidate(
        [{"gov_id": "us:place:0666000", "meeting_date": "2026-08-19"}], session=db
    )
    assert len(result.possible_pages) == 20
    assert result.next_action == "resolve_needed"
