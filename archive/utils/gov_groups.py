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
