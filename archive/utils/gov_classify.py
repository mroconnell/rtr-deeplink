"""Sort a government into County / City / School district / Agency.

The state pages list every government in a state, and at 222 rows for
California alone one alphabetical wall is not something a reader
navigates -- they arrive knowing whether they want a county board, a
city council, or a school board. Grouping by kind turns that wall into
three short, scannable lists.

Two sources, in order of trust:

1. **`MeetingPage.meeting_body`** -- the entity name split off a
   "<Entity> of <Jurisdiction>" title by
   `app/utils/jurisdiction_enrich.py` ("Housing Authority", "City
   Council", "Board of Supervisors"). This is real structured data and
   beats guessing from a name, so it wins when it says something
   conclusive. It is null on most pages today, which is exactly why the
   fallback below exists rather than this being the only path.
2. **The jurisdiction string itself** -- "Napa County, CA" is a county
   whatever its meeting bodies are called.

Deliberately conservative: anything that doesn't clearly signal a
county or a school district lands in CITY, because "city" is both the
commonest case and the least misleading thing to be wrong about. A
special district misfiled as a city is a mild inaccuracy; a city
misfiled as a county reads as an error.
"""

from __future__ import annotations

import re
from typing import Optional

COUNTY = "county"
CITY = "city"
SCHOOL = "school"
AGENCY = "agency"

# Display order and headings for the grouped list.
GROUP_ORDER = (COUNTY, CITY, SCHOOL, AGENCY)
GROUP_LABELS = {
    COUNTY: "Counties & regions",
    CITY: "Cities & towns",
    SCHOOL: "School districts",
    AGENCY: "Agencies & special districts",
}

_COUNTY_RE = re.compile(
    r"\b(?:county|counties|parish|regional municipality|region|"
    r"county of|board of supervisors|county commission|"
    r"regional district|regional council)\b",
    re.IGNORECASE,
)
_SCHOOL_RE = re.compile(
    r"\b(?:usd|esd|isd|cusd|uhsd|school district|schools?|unified|"
    r"board of education|board of trustees|college|university|"
    r"community college|academy)\b",
    re.IGNORECASE,
)
_AGENCY_RE = re.compile(
    r"\b(?:authority|agency|district|commission|council of governments|"
    r"transit|transportation|water|sanitary|sanitation|utility|utilities|"
    r"port of|airport|housing authority|library system|fire protection|"
    r"metropolitan|association of governments|sandag|mta|rta)\b",
    re.IGNORECASE,
)
# Checked before _AGENCY_RE: these are ordinary municipal signals that
# would otherwise be dragged into "agency" by a word like "district"
# ("Council District 4") or "water" (a city's own water department).
_CITY_RE = re.compile(
    r"\b(?:city|town|village|municipality|city council|town council|"
    r"city of|town of|borough council|planning commission)\b",
    re.IGNORECASE,
)


def classify_government(
    jurisdiction: Optional[str], meeting_body: Optional[str] = None
) -> str:
    """One of COUNTY / CITY / SCHOOL / AGENCY.

    `meeting_body` is consulted first but only for the two kinds it can
    settle on its own (a county board, a school board); a body of "City
    Council" attached to a county's page would be contradictory, so
    county-ness is re-checked against the jurisdiction name regardless.
    """
    name = jurisdiction or ""
    body = meeting_body or ""

    # A county in the *name* is decisive -- "Napa County" is a county
    # whether its body is a Board of Supervisors or a Planning
    # Commission. Checked before the body so a generic body string can
    # never override an explicit name.
    if _COUNTY_RE.search(name):
        return COUNTY
    if _SCHOOL_RE.search(name):
        return SCHOOL
    # Body as a tiebreaker only where the name said nothing.
    if body:
        if _COUNTY_RE.search(body):
            return COUNTY
        if _SCHOOL_RE.search(body):
            return SCHOOL
    if _CITY_RE.search(name):
        return CITY
    if _AGENCY_RE.search(name):
        return AGENCY
    if body and _AGENCY_RE.search(body) and not _CITY_RE.search(body):
        return AGENCY
    return CITY
