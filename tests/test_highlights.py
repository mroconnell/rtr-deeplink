"""Tests for the featured-snippet heuristic (archive/utils/highlights.py)
and the government-type classifier (archive/utils/gov_classify.py).

The snippet cases below are **frozen from real production transcripts**
-- each quote was produced by running the heuristic against the live
archive during a dry run on 2026-08-23, before any of it was wired into
a page (see BACKLOG.md's state/hub redesign entry). They are here to
catch the heuristic silently changing what it picks, which is the one
failure mode live-testing a single page will not surface: a scoring
tweak that improves one meeting and quietly ruins twenty.

Synthetic transcripts are used where the case being exercised is a
specific *logic branch* (an all-procedural meeting, a roll-up caption
repeat, an ALL-CAPS track) rather than realistic content -- the payload
shape is the real `{"start", "end", "text"}` segment schema every
adapter produces, and per this repo's convention each is commented with
what it is standing in for.
"""

from archive.db import crud
from archive.topics import TOPICS, TOPICS_BY_SLUG, topics_in
from archive.utils.gov_classify import AGENCY, CITY, COUNTY, SCHOOL, classify_government
from archive.utils.highlights import (
    clean_text,
    compute_highlight_payload,
    display_text,
    highlight_html,
    pick_highlight,
    pick_topic_moments,
    score_window,
)


def _segments(*texts, step=5.0):
    """Real segment schema, one line per segment."""
    return [
        {"start": i * step, "end": (i + 1) * step, "text": text}
        for i, text in enumerate(texts)
    ]


# --- clean_text / display_text -------------------------------------------


def test_clean_text_strips_caption_artifacts():
    assert "buzzer" not in clean_text("[ buzzer ] The council voted.")
    assert "»" not in clean_text("» The council voted.")
    assert ">>" not in clean_text(">> The council voted.")


def test_clean_text_normalizes_all_caps_track():
    # Several Granicus/Legistar caption feeds are entirely upper-case
    # (confirmed live on Los Angeles). Rendering that verbatim reads as
    # shouting and as boilerplate to a crawler.
    out = clean_text("THE DATA CENTER TOOK UP 43 GALLONS OF WATER. I AGREE.")
    assert out.startswith("The data center")
    assert "I agree" in out


def test_clean_text_leaves_ordinary_sentence_with_acronym_alone():
    text = "The EIR for the CEQA review was released."
    assert clean_text(text) == text


def test_clean_text_collapses_rollup_caption_repeat():
    # Roll-up ("scrolling ticker") captions restate the previous line in
    # the next cue. WO-34 fixed the four platform shapes of this at parse
    # time, but transcripts stored before that fix still carry the
    # residue -- confirmed live on Kapuskasing, ON.
    raw = "we're going to defer » we're going to defer this until such time"
    assert clean_text(raw).count("going to defer") == 1


def test_display_text_marks_partial_quotes():
    assert display_text("it was a long night").startswith("…")
    assert display_text("it was a long night").endswith("…")
    assert display_text("The vote was 4-1.") == "The vote was 4-1."


# --- scoring --------------------------------------------------------------


def test_procedural_window_scores_below_substantive_one():
    procedural = (
        "Motion to approve the consent calendar. Second. All in favor? Aye. "
        "Aye. Motion carries. Next item. Item number 12 on the agenda."
    )
    substantive = (
        "I am a resident of this neighborhood and I am concerned that the "
        "data center will use millions of gallons of water while families "
        "on my street are being asked to conserve."
    )
    assert score_window(substantive) > score_window(procedural)


def test_short_window_is_rejected():
    assert score_window("Thank you.") == -1.0


def test_repetitive_garble_is_penalized():
    garbled = " ".join(["okay"] * 60)
    assert score_window(garbled) < 0


def test_public_comment_bonus_applies():
    text = (
        "I am a resident of this neighborhood and I am deeply concerned "
        "about the cost of this project for the families on my street who "
        "already cannot afford their water bills or their property taxes."
    )
    assert score_window(text, after_public_comment=True) > score_window(text)


# --- pick_highlight -------------------------------------------------------


def test_picks_substantive_moment_over_procedure():
    segments = _segments(
        *(
            [
                "Calling the meeting to order.",
                "Roll call. Present. Present. Present.",
                "Motion to approve the minutes. Second. All in favor? Aye.",
                "Public comment is now open.",
                "I am a resident and I am concerned about the data center "
                "proposed on Elm Street, which will use millions of gallons "
                "of water while my neighbors were never notified.",
                "Thank you. Motion to adjourn.",
            ]
            * 3
        )
    )
    highlight = pick_highlight(segments)
    assert highlight is not None
    assert "data center" in highlight["text"]
    assert "data-centers" in highlight["topics"]
    # A real segment's own start, so /m/{slug}?t= lands on the moment.
    assert highlight["start"] in [s["start"] for s in segments]


def test_entirely_procedural_meeting_yields_no_highlight():
    # A page with nothing quotable must produce no row at all rather than
    # a bad quote -- every consumer renders fine without one.
    segments = _segments(
        *(["Motion. Second. All in favor? Aye. Motion carries. Next item."] * 40)
    )
    assert pick_highlight(segments) is None


def test_empty_and_missing_transcripts_are_safe():
    assert pick_highlight([]) is None
    assert pick_highlight(None) is None
    assert compute_highlight_payload(None)["highlight"] is None
    assert compute_highlight_payload([[]])["topic_moments"] == {}


def test_head_of_meeting_is_skipped():
    # Ceremony lives at the start; a naive "first substantive window"
    # pick lands there. The opening statement below is substantive but
    # inside the skipped head, so the later one must win.
    opening = (
        "Welcome everyone, I am concerned about the residents and families "
        "who have joined us tonight for this important budget discussion."
    )
    later = (
        "The consultant found the warehouse project would add four hundred "
        "truck trips a day past the elementary school, and residents in the "
        "area were never told about that impact."
    )
    segments = _segments(opening, *(["Filler discussion continues."] * 30), later)
    highlight = pick_highlight(segments)
    assert highlight is not None
    assert "warehouse" in highlight["text"]


# --- topic moments --------------------------------------------------------


def test_topic_moments_only_include_topics_actually_present():
    segments = _segments(
        *(
            [
                "The flock safety license plate reader contract is before us "
                "tonight and residents across the neighborhood have raised "
                "real privacy concerns about quietly building a permanent "
                "surveillance system without any public notice at all.",
                "Separately the affordable housing element update is on the "
                "agenda tonight and staff recommends approving the density "
                "bonus for the working families who need it most in this "
                "community, which residents have asked about repeatedly.",
            ]
            * 8
        )
    )
    moments = pick_topic_moments(segments)
    assert "surveillance-cameras" in moments
    assert "housing-development" in moments
    assert "cannabis" not in moments
    for moment in moments.values():
        assert isinstance(moment["start"], float)
        assert moment["text"]


def test_compute_payload_merges_versions_in_time_order():
    first = _segments("Filler one.", "Filler two.")
    second = [
        {
            "start": 500.0,
            "end": 520.0,
            "text": "Residents are concerned that the data center will raise "
            "electricity costs for families across the entire county.",
        }
    ] * 12
    payload = compute_highlight_payload([second, first])
    assert payload["highlight"] is not None
    assert "data-centers" in payload["topic_moments"]


# --- topic list -----------------------------------------------------------


def test_topic_slugs_are_unique_and_indexed():
    slugs = [t.slug for t in TOPICS]
    assert len(slugs) == len(set(slugs))
    assert set(slugs) == set(TOPICS_BY_SLUG)


def test_topics_in_requires_word_boundaries():
    # "flock" must not fire on "flocking", and a curated phrase must not
    # match as a substring of a longer word.
    assert "surveillance-cameras" not in topics_in("birds were flocking overhead")
    assert "surveillance-cameras" in topics_in("the flock cameras")


def test_procedural_text_matches_no_topics():
    assert topics_in("Motion to approve the consent calendar. Second.") == []


# --- highlight_html -------------------------------------------------------


def test_highlight_html_escapes_before_marking():
    out = highlight_html(
        "The data center & <script>alert(1)</script>", ["data-centers"]
    )
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    assert "<mark>data center</mark>" in out


def test_highlight_html_merges_overlapping_topic_spans():
    # "flock safety" belongs to one topic; overlapping matches from two
    # topics must not produce nested <mark> elements.
    out = highlight_html(
        "The flock safety cameras and the data center",
        ["surveillance-cameras", "data-centers"],
    )
    assert "<mark><mark>" not in out
    assert out.count("<mark>") == out.count("</mark>")


def test_highlight_html_ignores_unknown_topic_slug():
    out = highlight_html("The council met.", ["not-a-real-topic"])
    assert "<mark>" not in out


# --- government classification -------------------------------------------


def test_classify_counties_cities_schools_agencies():
    assert classify_government("Napa County, CA") == COUNTY
    assert classify_government("Peel Region, ON") == COUNTY
    assert classify_government("City of Napa, CA", "City Council") == CITY
    assert classify_government("Berkeley, CA") == CITY
    assert classify_government("Los Angeles USD, CA") == SCHOOL
    assert classify_government("Cerritos College, CA") == SCHOOL
    assert classify_government("East Bay Regional Park District, CA") == AGENCY
    assert classify_government("Sandag, CA") == AGENCY


def test_name_beats_body_for_county():
    # A generic body string must never override an explicit county name.
    assert classify_government("Napa County, CA", "Planning Commission") == COUNTY


def test_body_used_only_when_name_is_silent():
    assert classify_government("Springfield", "Board of Education") == SCHOOL


def test_unknown_government_falls_back_to_city():
    # Documented conservative default: a special district misfiled as a
    # city is a mild inaccuracy; a city misfiled as a county reads as an
    # error.
    assert classify_government("Somewhereville") == CITY
    assert classify_government(None) == CITY


# --- coherence guards -----------------------------------------------------
#
# Every string below is a snippet this heuristic ACTUALLY PRODUCED against
# the live archive on 2026-08-23, kept verbatim. The "bad" ones reached a
# rendered page during in-browser verification and are why
# _repetition_penalty() exists; the "good" ones are from the same render
# and are the reason its thresholds are where they are rather than
# tighter. Tuning this scoring without re-running these is how a fix for
# one meeting silently ruins twenty.

_REAL_BAD_SNIPPETS = {
    # Mission Viejo, CA -- one content word is 24% of the passage.
    "hammered_word": (
        "so, my question is related to personal data. so, I guess on part of "
        "this packet, page 15 of 44, it talks about the personal data and it "
        "says personal data includes personal data, personal information, "
        "personally identifiable"
    ),
    # San Diego, CA -- interleaved roll-up caption restating a phrase out
    # of order ("Five flock data will").
    "interleaved_rollup": (
        "The police captain who Five, flock data will be a target for federal "
        "agencies like ICE and CBP. aggressively pushed Flock then went on to "
        "work for Flock after retiring Five flock data will You argue with "
        "that guardrails will suffice"
    ),
}

_REAL_GOOD_SNIPPETS = {
    # Note "as well as" appearing twice: a repeated all-function-word
    # trigram must NOT be penalized, which is why the phrase guard
    # requires content words.
    "monterey": (
        "As well as concerns about neighborhood safety for pedestrians and "
        "family members, due to public nuisance disruptions, regarding trash, "
        "noise, as well as safety and wildfire evacuation or the "
        "vulnerability of the surrounding Dominic Forest."
    ),
    # "data center" three times is the actual subject, not a stutter.
    "los_angeles": (
        "Equivalent to 16 barrels of oil, a data center in lake tahoe has cut "
        "electricity to power near by data centers. Data center took up 43 "
        "gallons of water and residents were forced into a drought and they "
        "had to suffer the consequences."
    ),
    "long_beach": (
        "So impact fees are within a larger source of revenue. You know, we "
        "have the page and the budget book that talks about the largest "
        "revenue sources, but we actually have, you know, more than 30 "
        "different revenue sources as a city."
    ),
    "sacramento": (
        "Sacramento needs to roll back these egregious fees, reduce the "
        "services these departments require, restrain departments from "
        "arbitrarily imposing new fees, and greatly increase public funding "
        "to support events like mine."
    ),
}


def test_real_garbled_snippets_are_penalized():
    from archive.utils.highlights import _repetition_penalty

    for name, text in _REAL_BAD_SNIPPETS.items():
        assert _repetition_penalty(text) > 0, name


def test_real_good_snippets_are_not_penalized():
    from archive.utils.highlights import _repetition_penalty

    for name, text in _REAL_GOOD_SNIPPETS.items():
        assert _repetition_penalty(text) == 0, name


def test_garbled_snippet_loses_to_a_clean_rival_in_the_same_meeting():
    """The guard has to change a *ranking*, not clear an absolute bar.

    Scores are only ever compared within one meeting (_candidate_windows
    sorts that meeting's own windows), so asserting "every bad snippet
    scores below every good one" across different meetings would be
    testing something the code never asks -- and would fail on a
    perfectly good short quote that simply has fewer substantive words
    than a long garbled one. What matters is that when a garbled window
    and a clean one compete, the clean one wins.
    """
    clean_rival = (
        "Residents came here tonight because the flock camera contract was "
        "signed without any public hearing, and they want to know what "
        "happens to the data on their families."
    )
    for name, text in _REAL_BAD_SNIPPETS.items():
        assert score_window(text) < score_window(clean_rival), name


def test_generic_data_mention_is_not_treated_as_substance():
    # "data" alone matched every "personal data"/"data entry" aside and
    # was what floated the Mission Viejo snippet to the top of a live
    # page; the substantive list carries "evidence"/"impact report"
    # instead.
    generic = (
        "I would like to ask about the personal data mentioned on page "
        "fifteen of the packet that was handed out to us before tonight."
    )
    substantive = (
        "Residents told us the impact report was never shared, and the "
        "evidence shows the project will cost families far more than the "
        "estimate the consultant presented to this body."
    )
    assert score_window(substantive) > score_window(generic)


# --- ingest-path safety ---------------------------------------------------


async def test_highlight_write_failure_cannot_lose_a_transcript():
    """A broken highlight write must not take the ingest down with it.

    `_refresh_meeting_highlight()` runs inside the *ingest* transaction,
    so an unguarded failure there would roll back the transcript too --
    trading a missing snippet for a lost transcript. And on Postgres a
    plain `try/except` is not enough: a failed statement poisons the
    surrounding transaction until rollback, so the caller's `commit()`
    would fail regardless. The SAVEPOINT is what makes the guarantee
    real, and this test is what proves it.

    Simulates the failure by dropping the table out from under the write
    -- the same shape as the write failing for any other reason (a
    migration not yet applied, a constraint violation, a bad value).
    """
    from sqlalchemy import select, text

    from archive.db.engine import async_session
    from archive.db.models import MeetingPage

    async with async_session() as session:
        page = MeetingPage(
            slug="highlight-savepoint-probe",
            platform="youtube",
            external_id="highlight-savepoint-probe",
            source_url_normalized="https://example.test/highlight-savepoint-probe",
            title="Savepoint probe",
            jurisdiction="Probeville, CA",
        )
        session.add(page)
        await session.flush()
        page_id = page.id

        segments = [
            {
                "start": float(i * 5),
                "end": float(i * 5 + 5),
                "text": "Residents are deeply concerned that the data center "
                "will raise electricity costs for families across this county "
                "while the impact report was never shared with anyone.",
            }
            for i in range(30)
        ]

        await session.execute(text("DROP TABLE meeting_highlights"))
        # Must not raise, and must leave the transaction usable.
        await crud._refresh_meeting_highlight(session, page, [segments])
        await session.commit()

    # The page survived the failed highlight write -- the whole point.
    async with async_session() as session:
        found = (
            await session.execute(
                select(MeetingPage.id).where(MeetingPage.id == page_id)
            )
        ).scalar_one_or_none()
        assert found == page_id
        # Restore the table for any test that runs after this one (the
        # fixture DB is shared across the file and not reset per test).
        await session.execute(text(CREATE_MEETING_HIGHLIGHTS_SQL))
        await session.commit()


CREATE_MEETING_HIGHLIGHTS_SQL = """
CREATE TABLE meeting_highlights (
    meeting_page_id INTEGER NOT NULL PRIMARY KEY REFERENCES meeting_pages(id) ON DELETE CASCADE,
    start_seconds FLOAT NOT NULL,
    text TEXT NOT NULL,
    topics JSON NOT NULL,
    topic_moments JSON NOT NULL,
    topics_version INTEGER NOT NULL,
    computed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""
