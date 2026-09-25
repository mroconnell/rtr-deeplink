"""WO-1060: fix the "other-government lead" extraction WO-1058 shipped.

A review of WO-1058's own live output (`scratchpad/wo1058/other_gov_leads_
after/`, a real Meeting Finder run over `after_verdicts.csv.jsonl`) found
the extraction, not just the match step, was the problem: of 9
"confident" leads, all 9 were Galesburg IL's OWN meetings ("Galesburg, IL
City Council" -- "IL" extracted as if it were a different place, because
it happens to sit immediately before "City"); of 144 hand-read rows, the
dominant `named_place`s were bare meeting-descriptor words a too-loose
pattern mistook for a place ("regular" x70, "recessed ..." x27, "special"
x14, several bare dates) -- only ONE real lead ("The School Board of
Nassau County, Florida" x6) was buried in that noise.

Two things changed, both in `app/platforms/meeting_finder/pick.py`:

  1. `describe_foreign_candidate()` now requires an explicit place-TYPE
     word (City/Town/Township/Borough/Village/County/Parish/School
     District/ISD/USD) after stripping meeting/procedural noise words
     first -- never the bare "any capitalized word before Council/Board"
     pattern that produced the noise above. Returns `None` (no lead at
     all) rather than a dict when nothing real is left.
  2. It never records a lead that's just the SEARCHED government's own
     name or state resurfacing (`gov_name`/`gov_state`, both optional) --
     an exact-match check only, since a real different government can
     share a name PREFIX with the searched one (Nassau County, FL vs.
     Nassau County School District, FL) without being the same one.

`scripts/meeting_finder_other_gov_leads.py`'s `match_lead()` was also
changed to re-derive `named_place`/state from each lead's own `title`
via `describe_foreign_candidate()` (rather than trust an already-written
`named_place`, the exact field this bug lived in), using the searched
government's own name/state from the JSONL row's `identity_expected_
gov_id`. A school-district body (`hub_harvest._guessed_body_type()`) gets
its own resolver retry: a bare "Nassau, FL" resolves to the COUNTY
government by default; "Nassau County School District, FL" resolves
(REGISTRY tier) to the real school district.

**Ryan's review of this PR (2026-09-25) found a second, deeper bug the
first pass missed**: the live row searching `nassau.k12.fl.us`
(`us:sd:1201350`, Nassau County School District, FL) got its OWN Swagit
meetings ("The School Board of Nassau County, Florida") REJECTED by
`filter_candidates_to_government()` as a different government --
`_place_core("Nassau County School District, FL")` only drops ONE
trailing type word ("district"), landing on "nassau county school",
while the title's own extracted core is bare "nassau" -- a granularity
mismatch, not a real different place. The lead step then "confidently"
matched the rejected candidate back to `us:sd:1201350` -- the government
being searched. Two more fixes:

  3. `filter_candidates_to_government()` (`gov_state`, new optional
     param) now recognizes the 4 real "X County's school district"
     shapes ("School Board of X County[, State]", "X County School
     Board", "X County Board of Education", "X County Schools") and
     handles them specially: when the SEARCHED government IS that
     county's own school district (name + state match), the candidate is
     KEPT (its own meeting, never a lead); otherwise -- including a
     search for the plain COUNTY government of the very same name -- it
     is ALWAYS foreign (a lead to the school district), since a county
     and its own school district are different real governments even
     though they share a name.
  4. `match_lead()` also drops a lead outright (returns `None`) whenever
     the resolver's own match turns out to be the government being
     searched -- checked by `gov_id`, never by name -- as a defense-in-
     depth safety net that also cleans up a lead a run recorded BEFORE
     fix 3 landed (this script can only re-describe a candidate that was
     already dropped by the OLD code; it can't un-drop it).
"""

from __future__ import annotations

from app.platforms.meeting_finder.models import Candidate
from app.platforms.meeting_finder.pick import (
    describe_foreign_candidate,
    filter_candidates_to_government,
)
from scripts.hub_harvest import HubRow
from scripts.meeting_finder_other_gov_leads import match_lead


def _cand(title: str, url: str = "https://example.com/m") -> Candidate:
    return Candidate(url=url, title=title, date=None, platform="granicus")


# --- describe_foreign_candidate(): the extraction gate ---------------------


def test_galesburg_own_meeting_is_no_lead():
    """Real regression: Galesburg IL's OWN account, searched AS Galesburg
    -- "IL" (its own state) must never become a lead just because it sits
    next to "City"."""
    cand = _cand(
        "September 21 2026 - Galesburg, IL City Council meeting - Sep 21, 2026"
    )
    info = describe_foreign_candidate(
        cand, gov_name="Galesburg (city), IL", gov_state="IL"
    )
    assert info is None


def test_regular_city_council_is_no_lead():
    """Real hand-read noise (70 of 144 rows in the WO-1058 run): a bare
    meeting-descriptor word ("Regular") is never a place, even sitting
    right next to a real place-type word ("City")."""
    cand = _cand("Recessed Regular City Council Meeting, Tuesday, September 8, 2026")
    assert describe_foreign_candidate(cand) is None


def test_bare_committee_name_is_still_no_lead():
    """Unchanged from WO-1058: a bare committee/descriptor name with no
    place-type word at all is never evidence of anywhere."""
    cand = _cand("Zoning Board Regular Meeting")
    assert describe_foreign_candidate(cand) is None


def test_nassau_county_school_board_extracts_county_and_state():
    cand = _cand("The School Board of Nassau County, Florida")
    info = describe_foreign_candidate(cand)
    assert info is not None
    assert info["named_place"] == "nassau"
    assert info["place_type"] == "county"
    assert info["state"] == "FL"
    assert "board" in info["body_words"]


def test_nassau_lead_survives_against_a_different_search_by_name_alone():
    """`describe_foreign_candidate()` itself only ever excludes an EXACT
    name/state match -- it doesn't know about the "X County's school
    district" special case (that lives in `filter_candidates_to_
    government()`, tested below), so on its own it still describes this
    title as a lead when the searched government's name doesn't exactly
    equal it (a real, separate government -- Nassau County, FL -- can
    share this name prefix without being the same government)."""
    cand = _cand("The School Board of Nassau County, Florida")
    info = describe_foreign_candidate(
        cand, gov_name="Nassau County, FL", gov_state="FL"
    )
    assert info is not None
    assert info["named_place"] == "nassau"


# --- filter_candidates_to_government(): the "X County's school district"
# special case (Ryan's review, 2026-09-25) -----------------------------


def test_nassau_school_board_is_kept_as_its_own_meeting_when_searching_the_district():
    """The real regression: Nassau County School District, FL's OWN
    meeting must never be rejected as a different government."""
    cand = _cand(
        "The School Board of Nassau County, Florida",
        url="https://nassaucountysd.new.swagit.com/videos/400594",
    )
    kept, note, foreign = filter_candidates_to_government(
        [cand], "Nassau County School District, FL", gov_state="FL"
    )
    assert kept == [cand]
    assert foreign == []
    assert note is None


def test_nassau_school_board_is_a_foreign_lead_when_searching_the_county():
    """Searching the PLAIN COUNTY government of the same name: the same
    title now names a DIFFERENT real government (the school district),
    even though the county name matches exactly -- a county and its own
    school district are different governments."""
    cand = _cand(
        "The School Board of Nassau County, Florida",
        url="https://nassaucountysd.new.swagit.com/videos/400594",
    )
    kept, note, foreign = filter_candidates_to_government(
        [cand], "Nassau County, FL", gov_state="FL"
    )
    assert kept == []
    assert foreign == [cand]
    assert note is not None


def test_nassau_school_board_different_state_is_still_foreign():
    """A real, different Nassau County (NY, not FL) -- the state check
    matters, not just the name."""
    cand = _cand(
        "The School Board of Nassau County, Florida",
        url="https://nassaucountysd.new.swagit.com/videos/400594",
    )
    kept, note, foreign = filter_candidates_to_government(
        [cand], "Nassau County School District, NY", gov_state="NY"
    )
    assert kept == []
    assert foreign == [cand]


def test_county_schools_shape_also_recognized():
    """The 4th real shape Ryan named: "X County Schools" (no "board"/
    "district"/"education" word at all)."""
    cand = _cand(
        "Nassau County Schools Special Meeting",
        url="https://nassaucountysd.new.swagit.com/videos/1",
    )
    kept, _note, foreign = filter_candidates_to_government(
        [cand], "Nassau County School District, FL", gov_state="FL"
    )
    assert kept == [cand]
    assert foreign == []


def test_state_college_borough_extracts_full_two_word_name():
    cand = _cand("Borough of State College - Council")
    info = describe_foreign_candidate(cand, gov_name="College Township", gov_state="PA")
    assert info is not None
    assert info["named_place"] == "state college"
    assert info["place_type"] == "borough"


def test_cohasset_city_council_extracts_cleanly():
    cand = _cand("Cohasset City Council")
    info = describe_foreign_candidate(cand, gov_name="Nashwauk", gov_state="MN")
    assert info is not None
    assert info["named_place"] == "cohasset"
    assert info["place_type"] == "city"


# --- match_lead(): the full offline matcher, real hub rows ------------------


def _hubs():
    return [
        # `x.telvue.com` (not the real `videoplayer.telvue.com`), same
        # convention `tests/test_hub_harvest.py` already uses (see its
        # `test_school_district_does_not_collide_with_same_named_city`):
        # the REAL TelVue host is a registered `MULTI_GOV_HOSTS` entry
        # that requires a per-video/tenant_overrides.csv PIN to resolve
        # at all (`app/utils/gov_registry/registry.py`) -- an orthogonal
        # resolver policy this WO doesn't touch, unrelated to whether the
        # place-name EXTRACTION itself is correct, which is what this
        # test exercises.
        HubRow(
            hub="Centre County C-NET",
            platform="telvue",
            url="https://x.telvue.com/player/tok/home",
            region_state="PA",
            notes="",
        ),
        HubRow(
            hub="Iron Range TV Cablecast",
            platform="cablecast_remix",
            url="https://reflect-ictv.cablecast.tv/",
            region_state="MN",
            notes="",
        ),
    ]


def test_match_lead_nassau_school_board_is_confident_when_searched_by_the_county():
    """A real, different search subject (Nassau COUNTY, not its own
    school district) stumbling on this video via a shared hub gets a
    real, correct, confident lead to the school district."""
    lead = {
        "url": "https://nassaucountysd.new.swagit.com/videos/400594",
        "title": "The School Board of Nassau County, Florida",
        "date": None,
        "hub_host": "nassaucountysd.new.swagit.com",
        "_gov_id": "us:county:12089",
        "_gov_name": "Nassau County, FL",
        "_gov_state": "FL",
    }
    result = match_lead(lead, hubs=[])
    assert result is not None
    assert result.confidence == "confident"
    assert result.matched_gov_id == "us:sd:1201350"
    assert "School District" in result.matched_gov_name


def test_match_lead_drops_lead_that_resolves_back_to_the_searched_government():
    """Ryan's review, 2026-09-25: the real bug this PR shipped with --
    the searched government (Nassau County School District, FL) got its
    OWN meeting recorded as a "confident" lead pointing back at itself.
    This is a defense-in-depth safety net checked by `gov_id`, never by
    name -- deliberately exercised here with a `_gov_name` that does NOT
    contain any of `_SCHOOL_RELATED_GOV_WORDS` ("Nassau, FL", a plausible
    bare/legacy registry alias), so `describe_foreign_candidate()`'s own
    county-school-body exclusion (tested above) does NOT catch it either
    -- proving the `gov_id` check catches a case name-based reasoning
    misses, not just re-testing the same fix twice."""
    lead = {
        "url": "https://nassaucountysd.new.swagit.com/videos/400594",
        "title": "The School Board of Nassau County, Florida",
        "date": None,
        "hub_host": "nassaucountysd.new.swagit.com",
        "_gov_id": "us:sd:1201350",
        "_gov_name": "Nassau, FL",
        "_gov_state": "FL",
    }
    result = match_lead(lead, hubs=[])
    assert result is None


def test_match_lead_state_college_is_confident():
    lead = {
        "url": "https://x.telvue.com/player/tok/media/1",
        "title": "Borough of State College - Council",
        "date": None,
        "hub_host": "x.telvue.com",
        "_gov_name": "College Township",
        "_gov_state": "PA",
    }
    result = match_lead(lead, hubs=_hubs())
    assert result.confidence == "confident"
    assert "State College" in result.matched_gov_name


def test_match_lead_cohasset_is_confident():
    lead = {
        "url": "https://reflect-ictv.cablecast.tv/show/54",
        "title": "Cohasset City Council",
        "date": None,
        "hub_host": "reflect-ictv.cablecast.tv",
        "_gov_name": "Nashwauk",
        "_gov_state": "MN",
    }
    result = match_lead(lead, hubs=_hubs())
    assert result.confidence == "confident"
    assert "Cohasset" in result.matched_gov_name


def test_match_lead_galesburg_own_meeting_produces_no_named_place():
    lead = {
        "url": "https://galesburg.granicus.com/MediaPlayer.php?view_id=7&clip_id=1857",
        "title": (
            "September 21 2026 - Galesburg, IL City Council meeting - Sep 21, 2026"
        ),
        "date": "2026-09-21",
        "hub_host": "galesburg.granicus.com",
        "_gov_name": "Galesburg (city), IL",
        "_gov_state": "IL",
    }
    result = match_lead(lead, hubs=[])
    assert result.confidence == "hand_read"
    assert result.named_place == ""
    assert (
        result.reason
        == "no lead: title names no real different place, or only the government being searched"
    )


def test_match_lead_regular_council_produces_no_named_place():
    lead = {
        "url": "https://www.cityoflagunaniguel.org/AgendaCenter/ViewFile/Agenda/x",
        "title": (
            "Agenda and Staff Reports for Regular City Council Meeting on "
            "September 15, 2026 - 7:00 p.m."
        ),
        "date": "2026-09-15",
        "hub_host": "www.cityoflagunaniguel.org",
        "_gov_name": None,
        "_gov_state": None,
    }
    result = match_lead(lead, hubs=[])
    assert result.confidence == "hand_read"
    assert result.named_place == ""
