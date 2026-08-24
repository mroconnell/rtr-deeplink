"""WO-51: two independent additions.

1. A jurisdiction hub too thin to produce topic chips of its own borrows
   its state's -- labelled as the state's, and linking to the state page.
   The archive is wide and shallow (439 of 574 stateful jurisdictions had
   exactly one meeting when last measured), so "this hub has no chips" is
   the common case, not an edge one.

2. `/internal/topic-candidates`: what people searched for that
   `archive/topics.py` does not cover. The *human decision workflow*,
   which is the half that was missing -- not a reader-facing suggestion
   form, which collects the same signal at lower volume and records what
   people say they want rather than what they looked for.
"""

import pytest
from fastapi.testclient import TestClient

from archive.db import crud
from archive.db.engine import async_session
from archive.db.models import SearchQuery

TOKEN = "test-token"  # tests/conftest.py sets ARCHIVE_INGEST_TOKEN to this

# The fixture DB is shared across the whole session and never reset, so
# seeded jurisdictions leak into any test that reads state coverage.
# **Never seed ", WY"**: tests/test_state_pages.py reserves Wyoming as
# the state with zero indexable pages, and four of its tests fail if
# anything puts a meeting there. Found the hard way, 2026-08-24 --
# these tests passed alone and broke the full suite.


def _track(lines):
    return [
        {"start": 0.0, "end": 8.0, "text": "Roll call please, and we will begin."},
        {"start": 900.0, "end": 908.0, "text": lines[0]},
        {"start": 908.0, "end": 916.0, "text": lines[1]},
        {"start": 916.0, "end": 924.0, "text": lines[2]},
        {"start": 1700.0, "end": 1708.0, "text": "Any further business? Seeing none."},
        {"start": 1708.0, "end": 1716.0, "text": "So moved. The meeting is adjourned."},
    ]


async def _ingest(ext, jurisdiction, title, date, lines):
    url = f"https://example.granicus.com/player/clip/{ext}"
    await crud.ingest_resolution(
        {
            "platform": "granicus",
            "source_url": url,
            "external_id": f"granicus:{ext}",
            "title": title,
            "date": date,
            "jurisdiction": jurisdiction,
            "meeting_body": "City Council",
            "video_url": "https://example.com/v.m3u8",
            "video_format": "m3u8",
            "segments": _track(lines),
            "agenda_items": [],
            "transcript_language": "en",
            "transcript_warnings": [],
        },
        url,
    )


# --- 1. hub chip inheritance -------------------------------------------

_TOPICAL = [
    "the applicant is proposing a data center north of the interchange",
    "and the traffic study assumes no growth in truck volume at all,",
    "which seems optimistic given the warehouse approved last spring.",
]
_UNTOPICAL = [
    "I want to thank the volunteers who ran the summer reading tent",
    "and the folks who brought the folding chairs over on Saturday,",
    "it was a genuinely lovely afternoon and everybody had a nice time.",
]


async def test_thin_hub_borrows_its_states_chips():
    # A meeting in the state with real topics, in a *different* city...
    await _ingest("wo51-big", "City of Chiptown, ND", "Council", "2026-08-20", _TOPICAL)
    # ...and the thin hub itself, whose own meeting matches no topic.
    await _ingest(
        "wo51-thin", "City of Thinville, ND", "Council", "2026-08-19", _UNTOPICAL
    )

    data = await crud.get_jurisdiction_hub_data("thinville-nd")
    assert data is not None
    assert data["chips_inherited"] is True
    assert data["topic_chips"], "a thin hub should show its state's chips"
    assert any(c["slug"] == "data-centers" for c in data["topic_chips"])


async def test_hub_with_its_own_chips_does_not_inherit():
    await _ingest("wo51-own", "City of Ownchips, ND", "Council", "2026-08-18", _TOPICAL)

    data = await crud.get_jurisdiction_hub_data("ownchips-nd")
    assert data is not None
    assert data["chips_inherited"] is False
    assert any(c["slug"] == "data-centers" for c in data["topic_chips"])


async def test_inherited_chips_link_to_the_state_not_the_hub():
    """The hub has no meetings for those topics by construction, so a
    hub-local link would land on a guaranteed-empty page."""
    from archive.main import app as archive_app

    await _ingest("wo51-big2", "City of Chiptwo, VT", "Council", "2026-08-20", _TOPICAL)
    await _ingest(
        "wo51-thin2", "City of Thintwo, VT", "Council", "2026-08-19", _UNTOPICAL
    )

    with TestClient(archive_app) as client:
        body = client.get("/j/thintwo-vt").text

    assert "/state/" in body
    # Labelled honestly as the state's topics, not this government's --
    # and specifically in `.topic-chips-heading`, NOT the inline
    # `.topic-chips-label`, which CSS hides below 768px. On a phone that
    # would leave "Data centers 1" sitting on a town that never discussed
    # data centers (found in the browser, 2026-08-24).
    assert 'class="topic-chips-heading">Being discussed across' in body
    assert "topic-chips-label" not in body
    # ...and no hub-local topic link, which would be the empty page.
    assert "/j/thintwo-vt?topic=" not in body
    # The "All topics" chip is meaningless when nothing here is filtered.
    assert body.count(">All topics<") == 0


# --- 2. topic candidates -----------------------------------------------


async def _log(keyword, result_count):
    async with async_session() as session:
        session.add(SearchQuery(keyword=keyword, result_count=result_count))
        await session.commit()


async def test_topic_candidates_excludes_already_curated_phrases():
    await _log("zzyzxpipeline", 0)
    await _log("zzyzxpipeline", 0)
    await _log("data center", 12)  # already in archive/topics.py

    rows = await crud.topic_candidates()
    phrases = [r["phrase"] for r in rows]

    assert "zzyzxpipeline" in phrases
    assert "data center" not in phrases


async def test_zero_result_rate_is_reported():
    """Zero-result searches are the single best source of candidate
    topics -- a phrase people keep searching and never find is either a
    topic worth curating or a corpus gap worth filling."""
    for _ in range(3):
        await _log("zzyzxneverfound", 0)
    await _log("zzyzxneverfound", 4)

    row = next(
        r for r in await crud.topic_candidates() if r["phrase"] == "zzyzxneverfound"
    )
    assert row["searches"] == 4
    assert row["zero_result_searches"] == 3
    assert row["zero_result_rate"] == 0.75


async def test_noise_queries_are_skipped():
    await _log("a", 0)
    await _log("-", 0)
    phrases = [r["phrase"] for r in await crud.topic_candidates()]
    assert "a" not in phrases and "-" not in phrases


async def test_preview_counts_real_meetings_and_flags_curated_phrases():
    await _ingest(
        "wo51-preview", "City of Previewton, NV", "Council", "2026-08-17", _TOPICAL
    )

    preview = await crud.topic_candidate_preview("data center")
    assert preview["meeting_count"] >= 1
    assert preview["already_curated"] is True
    assert preview["sample"], "a human deciding needs to see real examples"

    empty = await crud.topic_candidate_preview("zzyzxabsolutelynothing")
    assert empty["meeting_count"] == 0
    assert empty["already_curated"] is False


@pytest.mark.parametrize("query", ["", "?phrase=data%20center"])
async def test_endpoint_requires_the_token(query):
    from archive.main import app as archive_app

    with TestClient(archive_app) as client:
        assert client.get(f"/internal/topic-candidates{query}").status_code == 404
        ok = client.get(
            f"/internal/topic-candidates{query}",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert ok.status_code == 200
