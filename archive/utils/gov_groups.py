"""Sort a government into the sections a `/state/*` page lists it under,
from its `gov_type` -- the Census of Governments vocabulary the registry
already assigns (decision D7).

Replaces `gov_classify.py` (retired 2026-09-02, WO-99), which guessed the
same thing from a regex over the display string and got it wrong in ways
a reader could see. Run on 2026-09-02, that module filed "Broward County
Public Schools, FL" and "West County Wastewater District, CA" under
**Counties & regions** (its county regex ran first) and "Minnesota
Senate, MN" under **Cities & towns** (its default) -- and the live
`/state/all-50` page showed ~17 "X County Public Schools" rows sitting
under the counties heading. It disagreed with the registry on 388 of the
5,929 rows in the 2026-09-02 scoring run.

Nothing here guesses. `MeetingPage.gov_type` is written at ingest from
the resolved registry row, so this is a lookup, and the only judgement
left is which types share a heading:

* `municipality` and `township` are one section, because a reader looking
  for their town does not know or care whether Census codes it as a place
  or a county subdivision -- the New England / upper-Midwest town is a
  `cousub` and its neighbours are places.
* `state` gets its own heading rather than sitting among agencies:
  decision D1 makes the State of X one government whose chambers and
  departments are `meeting_body` rows, so it is the largest government on
  its own state page, not a special district.
* `other` -- and a NULL `gov_type`, which is a page the resolver declined
  to key -- is "Other public bodies" rather than being folded into
  agencies. Calling an unidentified government an agency would be the
  same guess this module exists to stop making.
"""

from __future__ import annotations

from typing import Optional

from app.utils.gov_registry import classify_government_type

from .jurisdiction_format import is_canadian_abbr, state_abbr_from_jurisdiction

STATE = "state"
COUNTY = "county"
CITY = "city"
SCHOOL = "school"
AGENCY = "agency"
COURT = "court"
OTHER = "other"

# Display order and headings for the grouped list. Biggest government
# first, then the two general-purpose levels a reader is most likely to
# be looking for, then the special-purpose ones.
GROUP_ORDER = (STATE, COUNTY, CITY, SCHOOL, AGENCY, COURT, OTHER)
GROUP_LABELS = {
    STATE: "State government",
    COUNTY: "Counties & regions",
    CITY: "Cities & towns",
    SCHOOL: "School districts",
    AGENCY: "Agencies & special districts",
    COURT: "Courts",
    OTHER: "Other public bodies",
}

# Census-of-Governments `gov_type` -> section key.
_SECTIONS = {
    "state": STATE,
    "county": COUNTY,
    "municipality": CITY,
    "township": CITY,
    "school_district": SCHOOL,
    "special_district": AGENCY,
    "court": COURT,
    "other": OTHER,
}


def group_for_gov_type(gov_type: Optional[str]) -> str:
    """The section a `gov_type` belongs to. An unrecognised or missing
    type is OTHER, never a guess at a more specific one."""
    return _SECTIONS.get((gov_type or "").strip().lower(), OTHER)


def group_for_page(gov_type: Optional[str], jurisdiction: Optional[str]) -> str:
    """The section one PAGE's government belongs to, falling back to its
    name when the page has no stored `gov_type`.

    A stored type is always preferred and is never second-guessed. The
    fallback exists for the one state where every page has none: between
    the migration adding the column and
    `scripts/backfill_gov_id.py` finishing. Measured before this existed,
    by rendering `origin/main` and this branch against the same 14-page
    pre-WO-99 database: hubs, `/j/`, `/coverage` and `sitemap.xml` came
    out byte-identical, but `/state/*`'s whole government list collapsed
    into one "Other public bodies" section, because `gov_type` was NULL
    on every row. That is a visible downgrade on a live, indexed page for
    however long the gap between deploying and backfilling turns out to
    be, and it is avoidable.

    The fallback is the registry's OWN classifier, run on the display
    name -- not a revival of `gov_classify.py`. Two differences that
    matter: it is the merged rule set that gets "Broward County Public
    Schools" and "Minnesota Senate" right, and it returns None rather
    than defaulting to "city" when a name says nothing conclusive, so an
    unclassifiable government still reads "Other public bodies" instead
    of being asserted to be a city.
    """
    if gov_type:
        return group_for_gov_type(gov_type)
    if not jurisdiction:
        return OTHER
    abbr = state_abbr_from_jurisdiction(jurisdiction)
    country = "ca" if is_canadian_abbr(abbr) else "us"
    # The trailing ", ON" comes off first, the same way the resolver's own
    # `_split_state()` does before classifying. Several rules anchor on
    # the END of the name: "Peel Region" is a Canadian upper-tier
    # government by `_CA_UPPER_TIER_RE`'s `region$`, and "Peel Region, ON"
    # is not.
    name = jurisdiction[: -(len(abbr) + 2)].rstrip(" ,") if abbr else jurisdiction
    return group_for_gov_type(
        classify_government_type(name or jurisdiction, country=country)
    )
