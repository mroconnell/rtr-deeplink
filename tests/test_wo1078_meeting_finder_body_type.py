"""WO-1078: the body-name/government-TYPE agreement step.

Real, measured problem (2026-09-26 hand-check of a no-platform-signature
Meeting Finder run, `other_gov_rows.csv`/`all_verdicts.csv` in that
session's scratchpad): a school district's own search kept landing on a
DIFFERENT government's meeting (almost always a town/city sharing the
same TV/streaming account) because the candidate's title named a body of
a clearly different government TYPE ("Town Council", "Common Council",
"County Commissioners") and nothing checked that.

Every title used below is a REAL title from that hand-check (not
invented) -- see `app/utils/gov_body_types.py`'s own module docstring for
the full accounting. Two tests (`test_synthetic_*`) are marked SYNTHETIC
per CLAUDE.md's synthetic-test rules: the shape is real (a school
district's own body sharing a listing with a real other-government body),
but the specific pairing is hand-built to exercise the "keep at least one
/ try the next candidate" behavior in one place rather than waiting for a
second live example.
"""

from app.platforms.meeting_finder.listing import ListResult, _apply_gov_filter
from app.platforms.meeting_finder.models import Candidate
from app.platforms.meeting_finder.pick import (
    describe_foreign_candidate,
    filter_candidates_to_government,
)
from app.utils import gov_body_types


# ---------------------------------------------------------------------
# gov_body_types.py itself
# ---------------------------------------------------------------------


def test_match_body_type_phrase_finds_known_phrases():
    assert gov_body_types.match_body_type_phrase("Town Council 9/22/2026")[0] == (
        "town council"
    )
    assert gov_body_types.match_body_type_phrase("Common Council - 6/9/2026")[0] == (
        "common council"
    )
    assert gov_body_types.match_body_type_phrase("Regular Meeting") is None


def test_ambiguous_bodies_never_match():
    """Ryan's brief (2026-09-26): these must never trigger the gate."""
    for title in (
        "Planning Commission Meeting",
        "Zoning Board of Appeals - September 24, 2026.mp4",
        "Finance Committee Regular Meeting",
        "Board of Trustees Meeting",
        "Regular Meeting",
    ):
        assert gov_body_types.match_body_type_phrase(title) is None, title


def test_body_type_disagreement_real_school_district_vs_city():
    # Real: cumberland.k12.wi.us (us:sd:5503090) -- Cumberland, WI's
    # school district search found the CITY's Common Council video.
    hit = gov_body_types.body_type_disagreement(
        "Common Council - 6/9/2026", "school_district"
    )
    assert hit is not None
    phrase, expected_types, owner_hint = hit
    assert phrase == "common council"
    assert "municipality" in expected_types
    assert "school_district" not in expected_types


def test_body_type_agreement_real_school_committee_on_shared_channel():
    # Real: lincnet.org's own "School Committee 09.10.26" video, found on
    # the TOWN's shared Castus channel -- must NOT be rejected.
    assert (
        gov_body_types.body_type_disagreement(
            "School Committee 09.10.26", "school_district"
        )
        is None
    )


def test_shac_is_the_school_districts_own_body_not_a_state_body():
    # Real approve rows in all_verdicts.csv: pisd.net, romaisd.com,
    # pgisd.net, paisd.org, borgerisd.net, caddomillsisd.org,
    # nechesisd.com, taylorisd.org, bellevueisd.org, bradyisd.org -- every
    # one an ISD's own School Health Advisory Council recording.
    assert (
        gov_body_types.body_type_disagreement("SHAC Meeting 2-5-25", "school_district")
        is None
    )
    assert (
        gov_body_types.body_type_disagreement("SHAC Meeting 2-5-25", "county")
        is not None
    )


def test_no_disagreement_without_gov_type():
    assert gov_body_types.body_type_disagreement("Town Council 9/22/2026", None) is None


# ---------------------------------------------------------------------
# pick.filter_candidates_to_government() / describe_foreign_candidate()
# ---------------------------------------------------------------------


def test_filter_drops_real_other_government_body_type_mismatch():
    # Real: glastonburyus.org (us:sd:0901620) -- exactly the example named
    # in the WO-1078 brief.
    candidates = [
        Candidate(url="https://x/1", title="Town Council 9/22/2026", date=None)
    ]
    kept, drop_note, foreign = filter_candidates_to_government(
        candidates, "Glastonbury School District", gov_type="school_district"
    )
    assert kept == []
    assert len(foreign) == 1
    assert drop_note is not None


def test_filter_keeps_own_school_committee_on_shared_channel():
    # Real: lincnet.org -- must stay found even on a shared town channel.
    candidates = [
        Candidate(url="https://x/1", title="School Committee 09.10.26", date=None)
    ]
    kept, drop_note, foreign = filter_candidates_to_government(
        candidates,
        "Lincoln-Sudbury Regional School District",
        gov_type="school_district",
    )
    assert len(kept) == 1
    assert foreign == []
    assert drop_note is None


def test_filter_never_gates_body_type_check_behind_governing_body_keywords():
    """Real, measured gap this WO fixed: `GOVERNING_BODY_KEYWORDS`
    (council/commission/board/committee/hearing, whole-word only) misses
    "County Commissioners" (no bare "commission"/"board" word) and
    "Redevelopment and Housing Authority" (no keyword at all) -- both
    real other_gov_rows.csv titles (qacps.org, harrisonburg.k12.va.us).
    The body-type check must run before, not after, that gate."""
    for title, gov_name in (
        (
            "County Commissioners Meeting || 09/21/2026",
            "Queen Anne's County Public Schools",
        ),
        (
            "Harrisonburg Redevelopment and Housing Authority on 2026-09-16",
            "Harrisonburg City Public Schools",
        ),
    ):
        candidates = [Candidate(url="https://x/1", title=title, date=None)]
        kept, drop_note, foreign = filter_candidates_to_government(
            candidates, gov_name, gov_type="school_district"
        )
        assert kept == [], title
        assert len(foreign) == 1, title


def test_describe_foreign_candidate_body_type_lead_has_no_place_name():
    # Real: cumberland.k12.wi.us's "Common Council - 6/9/2026" names no
    # place at all -- the OLD place-name-only describe() would have
    # returned None for this title with no gov_type given.
    candidate = Candidate(
        url="https://x/1", title="Common Council - 6/9/2026", date=None
    )
    assert (
        describe_foreign_candidate(candidate, gov_name="Cumberland School District")
        is None
    )
    described = describe_foreign_candidate(
        candidate, gov_name="Cumberland School District", gov_type="school_district"
    )
    assert described is not None
    assert described["reason"] == "body_type_mismatch"
    assert described["body_phrase"] == "common council"
    assert "municipality" in described["other_gov_types"]


def test_zero_false_rejects_on_real_approve_titles():
    """A sample of REAL `approve` titles from all_verdicts.csv (2026-09-26
    hand-check) that must never be rejected by the new step."""
    real_approved_school_district_titles = (
        "shacmeeting2021-12-15_1.mp3",
        "SHAC Meeting 2-5-25.m4a",
        "",  # real approve rows: Google Drive board links carry no title at all
    )
    for title in real_approved_school_district_titles:
        candidates = [Candidate(url="https://x/1", title=title, date=None)]
        kept, drop_note, foreign = filter_candidates_to_government(
            candidates, "Some School District", gov_type="school_district"
        )
        assert kept == candidates, title
        assert foreign == [], title


# ---------------------------------------------------------------------
# listing._apply_gov_filter(): "keep at least one" / "try the next
# candidate in the same listing" (SYNTHETIC pairing, real body/type shape)
# ---------------------------------------------------------------------


def test_synthetic_other_candidate_in_same_listing_still_found():
    """SYNTHETIC pairing (real shapes: a Town Council video + a School
    Committee video sharing one hub, the same real situation lincnet.org
    is an example of) -- when List's own account carries BOTH a foreign
    body-type video and the searched district's own, the district's own
    must still be returned, not just recorded as a miss."""
    result = ListResult(
        candidates=[
            Candidate(
                url="https://hub/town-council",
                title="Town Council 9/22/2026",
                date="2026-09-22",
            ),
            Candidate(
                url="https://hub/school-committee",
                title="School Committee 09.10.26",
                date="2026-09-10",
            ),
        ],
        lister="synthetic",
        outcome=None,
        note=None,
    )
    filtered = _apply_gov_filter(
        result,
        "Example Regional School District",
        "https://hub.example.com/",
        gov_type="school_district",
    )
    assert [c.url for c in filtered.candidates] == ["https://hub/school-committee"]
    assert len(filtered.foreign_leads) == 1
    assert filtered.foreign_leads[0]["body_phrase"] == "town council"


def test_synthetic_all_foreign_still_keeps_one_labelled_lead():
    """SYNTHETIC (real shape, Ryan's 'never throw a meeting away' rule):
    when EVERY candidate on the account is a different government's body,
    the best one is still returned, marked, rather than an empty result."""
    result = ListResult(
        candidates=[
            Candidate(
                url="https://hub/town-council",
                title="Town Council 9/22/2026",
                date="2026-09-22",
            ),
        ],
        lister="synthetic",
        outcome=None,
        note=None,
    )
    filtered = _apply_gov_filter(
        result,
        "Example Regional School District",
        "https://hub.example.com/",
        gov_type="school_district",
    )
    assert len(filtered.candidates) == 1
    assert filtered.candidates[0].foreign_gov_hint
    assert filtered.outcome is not None
