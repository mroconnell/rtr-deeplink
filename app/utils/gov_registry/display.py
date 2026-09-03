"""The display rule (architecture doc §4) and the hub slug.

The point of the table below is that the display name is generated *from
the registry row*, never from the string an adapter happened to extract.
That is what collapses "County of Fresno, CA" and "Fresno County, CA"
into one hub: they resolve to the same `us:county:06019`, and this module
renders that id one way.

| gov_type            | display                                  |
| ------------------- | ---------------------------------------- |
| municipality        | `{Name}, {ST}`                           |
| ... name collides   | `{Name} ({lsad}), {ST}`                  |
| county              | `{Name} County, {ST}` (suffix form)      |
| township            | `{Name} Township, {ST}`                  |
| school_district     | official name + `, {ST}`                 |
| special_district    | official name + `, {ST}`                 |
| state               | `State of {Name}`                        |
| Canadian            | `{Name}, {PR}`                           |
| rtr:unknown         | `Unidentified government ({host})`       |
"""

import re
from typing import Optional

from . import tables
from .classify import COUNTY, MUNICIPALITY, STATE, TOWNSHIP
from .registry import Government

# Census spells a general-purpose government's name with exactly one
# lowercase generic type word on the end: "Fresno city", "Cottage Grove
# village", "Caledonia charter township". For a place the word is noise
# in the display form (§4's municipality row is a bare name); for a
# county subdivision it is the display form (§4's township row keeps it),
# so it is title-cased rather than dropped.
_TRAILING_TYPE_RE = re.compile(
    r"\s+((?:charter\s+|urban\s+|unified\s+)?"
    r"(?:city|town|township|village|borough|municipality|plantation|"
    r"gore|grant|location|purchase|reservation|district|precinct|"
    r"CDP|comunidad|zona urbana))$"
)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """Byte-identical to `archive/utils/slugify.slugify_text()`.

    Reimplemented rather than imported: this package must stay importable
    with nothing from the rest of the repo but `jurisdiction_enrich`, so
    it can be lifted into its own distribution later (D5). The rule is
    three lines and has not changed since the slug scheme shipped;
    `tests/test_gov_registry.py` pins the two against each other so a
    future edit to either side fails loudly instead of silently splitting
    every `/j/` slug in two.
    """
    return _NON_ALNUM.sub("-", (text or "").lower()).strip("-")


def _split_type_word(census_name: str) -> tuple[str, str]:
    """ "Cottage Grove village" -> ("Cottage Grove", "village"). Returns
    ("...", "") when the name carries no generic type word (school
    districts, special districts, Canadian CSDs)."""
    m = _TRAILING_TYPE_RE.search(census_name)
    if not m:
        return census_name, ""
    return census_name[: m.start()].strip(), m.group(1).strip()


def _titled_type_word(word: str) -> str:
    return " ".join(part.capitalize() for part in word.split())


def display_name(gov: Government) -> str:
    """The one display form for a government row."""
    if gov.gov_id.startswith("rtr:unknown:"):
        host = gov.gov_id[len("rtr:unknown:") :]
        return f"Unidentified government ({host})"

    state = (gov.state or "").upper()
    suffix = f", {state}" if state else ""

    if gov.gov_type == STATE:
        # The chamber or agency is the meeting body, not the identity
        # (decision D1) -- "State of Minnesota", body "Senate".
        return f"State of {gov.gov_name}"

    if gov.gov_type == COUNTY:
        # Census already spells counties in suffix form ("Fresno County",
        # "Orleans Parish"), which is §4's majority-convention choice, so
        # the name passes through. A Canadian census division does not
        # ("Peel"), and is left as the bare name its own province uses.
        return f"{gov.gov_name}{suffix}"

    if gov.gov_type == TOWNSHIP:
        base, word = _split_type_word(gov.gov_name)
        if word:
            return f"{base} {_titled_type_word(word)}{suffix}"
        return f"{gov.gov_name}{suffix}"

    if gov.gov_type == MUNICIPALITY:
        base, word = _split_type_word(gov.gov_name)
        if word and tables.name_is_ambiguous_in_state(base, state):
            # Two real governments in one state share this name -- the
            # Cottage Grove village/town case. The LSAD word is data from
            # the Census table, not a parse of "Village of".
            return f"{base} ({word}){suffix}"
        return f"{base}{suffix}"

    # school_district / special_district / court / other: the official
    # name is already the right display, and shortening it would be
    # guessing. §6 of JURISDICTION_METADATA_PLAN.md's caution applies --
    # "West County Wastewater District, CA" is correct and readable, and
    # a placeholder or a badge would be misleading, not informative.
    return f"{gov.gov_name}{suffix}"


def hub_slug(gov: Government) -> Optional[str]:
    """The `/j/{slug}` for a government.

    Same rule as `archive/utils/jurisdiction_format.jurisdiction_hub_slug()`
    -- slugify of the display form -- so most existing hub slugs survive
    the migration unchanged (decision D6 accepts that a handful change,
    with 301s). The `(village)` parentheses slugify to a hyphen the same
    way any punctuation does: "cottage-grove-village-wi".
    """
    return slugify(display_name(gov)) or None
