"""WO-1058: calibration run D found WO-1054's shared-hub "this government
only" filter running on EVERY account, not just a confirmed shared hub --
21 of 68 regressions, none of them an actual shared hub (see BACKLOG_DONE.md
and pick.py's own module comment for the real Oak Park IL/Clarington ON/
etc. examples). Three things changed:

  1. `pick.filter_candidates_to_government()`'s weak (no place-type-word-
     required) pattern only runs when the caller says the account is a
     confirmed shared hub (`listing.is_known_shared_hub()`,
     `regional_tv_hubs.csv`) -- an ordinary account no longer treats a
     bare committee name ("Zoning Board", "Public Safety Committee") as
     evidence of a different government.
  2. "Keep at least one" (Ryan's rule): when the filter would otherwise
     reject every candidate, the best rejected one is kept as a labelled
     lead instead of an empty result.
  3. Every candidate dropped for naming a different place is described
     and returned as a `foreign_leads`/`other_gov_leads` entry -- a real,
     free link-first lead for whichever OTHER government it names.

Plus a smaller, related fix: `assess_meeting_evidence()`'s direct-file
length floor (`app/utils/video_hand_check.py`) moved 45 -> 15 minutes, and
a new `runner._handcheck_lead()` rule for how broadly to flag a weak find
worth a human's time.
"""

from __future__ import annotations

import pytest

from app.platforms.meeting_finder import listing, runner
from app.platforms.meeting_finder.models import (
    OUTCOME_HUB_OTHER_GOVERNMENT,
    Candidate,
    FinderInput,
    ResolveResult,
)
from app.platforms.meeting_finder.pick import (
    describe_foreign_candidate,
    filter_candidates_to_government,
)


def _cand(title, url="https://example.com/m"):
    return Candidate(url=url, title=title, date=None, platform="granicus")


# --- Rule 1: weak pattern only on a confirmed hub -----------------------


def test_ordinary_committee_names_are_never_treated_as_a_different_place():
    """Real Oak Park IL regression (calibration run D): an ordinary
    account's own committee-named meetings ("Zoning Board", "Public
    Safety Committee") share no word with the government's own name, but
    are not evidence of a different government -- only a real place-type
    phrase is."""
    candidates = [
        _cand("Zoning Board Regular Meeting"),
        _cand("Public Safety Committee Meeting"),
        _cand("Village Board Meeting"),
    ]
    kept, note, foreign = filter_candidates_to_government(candidates, "Oak Park")
    assert kept == candidates
    assert note is None
    assert foreign == []


def test_strict_mode_still_catches_the_same_committee_names_on_a_real_hub():
    """The weak pattern is still available -- just gated behind `strict`
    (a confirmed shared hub) -- so a hub that genuinely mixes in another
    government's own committee meeting is still caught when it matters."""
    own = _cand("Oak Park Village Board Meeting")
    other = _cand("Cohasset Public Safety Committee")
    kept, note, foreign = filter_candidates_to_government(
        [own, other], "Oak Park", strict=True
    )
    assert kept == [own]
    assert foreign == [other]


def test_strong_place_phrase_still_drops_a_different_government_non_strict():
    """WO-1058's fix narrows the filter, it doesn't remove it -- a title
    that STRONGLY names a different place (an explicit place-type word)
    is still dropped even off a hub known account."""
    own = _cand("Oak Park Village Board Meeting")
    other = _cand("Village of Cohasset Board Meeting")
    kept, note, foreign = filter_candidates_to_government([own, other], "Oak Park")
    assert kept == [own]
    assert [c.url for c in foreign] == [other.url]


# --- Rule 3: foreign candidates are described as leads -------------------


def test_describe_foreign_candidate_shape():
    cand = _cand("Cohasset City Council", url="https://example.com/cohasset-council")
    info = describe_foreign_candidate(cand)
    assert info["named_place"] == "cohasset"
    assert "council" in info["body_words"]
    assert info["title"] == "Cohasset City Council"
    assert info["url"] == "https://example.com/cohasset-council"


# --- is_known_shared_hub --------------------------------------------------


def test_is_known_shared_hub_true_for_a_real_csv_row():
    # Centre County C-NET, regional_tv_hubs.csv -- the real College
    # Township/Bellefonte case this whole rule exists for.
    assert listing.is_known_shared_hub(
        "https://videoplayer.telvue.com/player/GNduNoua2rBThhw6N4PRP9OCSPf6B2ru/home"
    )


def test_is_known_shared_hub_false_for_an_ordinary_account():
    # Same TelVue HOST, different (unrelated, not-hand-confirmed) org
    # token -- host alone must not be enough for TelVue, since every real
    # customer shares one host.
    assert not listing.is_known_shared_hub(
        "https://videoplayer.telvue.com/player/some-other-real-towns-token/home"
    )
    assert not listing.is_known_shared_hub(
        "https://oak-park.granicus.com/ViewPublisher.php"
    )


# --- Rule 2: keep at least one, forced into the low-confidence bucket ----


@pytest.mark.asyncio
async def test_try_resolve_never_lets_a_foreign_gov_lead_become_a_clean_find(
    monkeypatch,
):
    """`_apply_gov_filter()`'s "keep at least one" hands `_try_resolve()`
    a candidate with `foreign_gov_hint` set -- even if Resolve comes back
    completely clean (real video, real captions), it must never become
    THIS government's own clean find. It's forced into the same
    low-confidence "kept despite" bucket every other fallback uses, at
    the lowest rank, so a genuine same-government find always wins."""
    lead = Candidate(
        url="https://videoplayer.telvue.com/player/tok/media/1",
        title="Borough of Bellefonte - Council",
        platform="telvue",
        source_phase="list",
        foreign_gov_hint=(
            "possibly another government's meeting on a shared hub: "
            "'Borough of Bellefonte - Council'"
        ),
    )

    async def fake_resolve(candidates, finder_input, *, max_tries):
        clean = ResolveResult(
            candidate=candidates[0],
            tier=1,
            platform="telvue",
            video_url=candidates[0].url,
            has_segments=True,
            duration_seconds=1800,
            outcome=None,
            note="",
        )
        return clean, None

    monkeypatch.setattr(runner, "_resolve_candidates_with_meeting", fake_resolve)

    state = runner._WalkState()
    finder_input = FinderInput(url="collegetownshippa.gov", gov_id="us:place:test")
    resolved = await runner._try_resolve([lead], finder_input, state, max_tries=6)

    assert resolved is False
    assert state.result is None
    assert state.low_confidence is not None
    rank, result, _meeting = state.low_confidence
    assert rank == runner._FOREIGN_GOV_LEAD_RANK
    assert result.outcome == OUTCOME_HUB_OTHER_GOVERNMENT
    assert "Bellefonte" in result.low_confidence_reason


# --- runner._handcheck_lead() ---------------------------------------------


def test_handcheck_lead_no_for_short_clip():
    flag, note = runner._handcheck_lead("Some Meeting", 30)
    assert flag == "no"
    assert note is None


def test_handcheck_lead_no_for_non_meeting_sign():
    flag, note = runner._handcheck_lead("Homepage Banner", 20 * 60)
    assert flag == "no"


def test_handcheck_lead_yes_for_unknown_length():
    flag, note = runner._handcheck_lead("Untitled", None)
    assert flag == "yes"


def test_handcheck_lead_yes_for_ordinary_long_enough_clip():
    flag, note = runner._handcheck_lead("Council Meeting", 12 * 60)
    assert flag == "yes"
    assert note is None


def test_handcheck_lead_80_min_is_strong_indicator_even_with_a_weak_title():
    """Ryan, 2026-09-25: hand-checks found every direct file >= 80 min (6
    of 6) was a real meeting, against three webinars/trainings all under
    63 min -- so at 80+ min a title word that would otherwise demote it
    ("training"/"webinar") no longer does."""
    flag, note = runner._handcheck_lead("Staff Training Session", 85 * 60)
    assert flag == "yes"
    assert note == "80+ min: strong meeting indicator"


def test_handcheck_lead_80_min_still_vetoed_by_a_decorative_asset_word():
    flag, note = runner._handcheck_lead("Homepage Hero Banner", 90 * 60)
    assert flag == "no"
    assert note is None
