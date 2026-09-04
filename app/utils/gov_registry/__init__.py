"""`gov_id` -- one namespaced, deterministic identifier per government,
and the resolver that assigns it.

WO-98, 2026-09-02. Phase 1 of
`rtr-business/research/GOVERNMENT_IDENTITY_ARCHITECTURE.md`: the registry
data and a pure resolver module, scored against real data, with **no
schema change, no production write, and no change to any existing
adapter's or `finalize_jurisdiction()`'s behaviour**. Nothing in this
repo imports this package yet; `scripts/score_gov_registry.py` is its
only caller, and the scoring report is the deliverable.

The problem it exists to solve, measured: a government is identified today
by *its name as a string*, so one government fragments into several
(`/state/california` lists both "County of Fresno" and "Fresno County"),
nothing joins across the four tools that all have a "jurisdiction" field,
and -- worst -- a non-place government whose page mentions its host city
is silently filed under the *wrong* government (LADWP resolving as Los
Angeles, SANDAG as San Diego, Menlo Park Fire as Atherton; nine confirmed
tenants).

    gov_id                          issued by
    ------------------------------  --------------------------------------
    us:place:0627000                Census place GEOID
    us:county:06019                 county FIPS
    us:cousub:5502517200            county-subdivision GEOID (townships)
    us:state:06                     state FIPS (D1: one government/state)
    us:sd:0622710                   Census school-district GEOID
    ca:csd:3518013                  StatCan SGC census subdivision
    ca:cd:3521                      StatCan SGC census division
    ca:pr:35                        province/territory
    rtr:us:ca:west-county-...       minted -- no national code exists
    rtr:unknown:<tenant-host>       nothing extracted at all

Deterministic, not a surrogate key: deeplink is Postgres on Render,
discovery and upcoming are local SQLite, the feed is flat files, and
rtr-business is CSVs. Nothing shares a sequence, so an id every tool can
derive from `(type, name, state)` plus the same committed data files is
the only one all five can assign independently and still agree on.

**Import constraint, deliberate**: this package imports the standard
library, its own data files, and `app.utils.jurisdiction_enrich` -- and
nothing else from this repo. That is what lets it be lifted into its own
distribution later (decision D5) and imported by rtr-discovery and
rtr-upcoming through their existing seams. Keep it that way: if something
here needs a helper from `archive/`, copy it with a comment and a test
pinning the two together (see `display.slugify()`), don't reach across.
"""

from .classify import GOVERNMENT_TYPES, classify_government_type
from .display import display_name, hub_slug, slugify
from .tables import state_gov_id
from .registry import (
    Government,
    TenantOverride,
    government_for_id,
    governments,
    tenant_overrides,
)
from .resolver import (
    TIER_BLANK,
    TIER_INFERRED,
    TIER_PINNED,
    TIER_REGISTRY,
    TIER_UNRESOLVED,
    TIER_UNVERIFIED,
    GovernmentMatch,
    is_own_name,
    page_hints_for,
    resolve_government,
)

__all__ = [
    "GOVERNMENT_TYPES",
    "Government",
    "GovernmentMatch",
    "TIER_BLANK",
    "TIER_INFERRED",
    "TIER_PINNED",
    "TIER_REGISTRY",
    "TIER_UNRESOLVED",
    "TIER_UNVERIFIED",
    "TenantOverride",
    "classify_government_type",
    "display_name",
    "government_for_id",
    "is_own_name",
    "governments",
    "hub_slug",
    "page_hints_for",
    "resolve_government",
    "slugify",
    "state_gov_id",
    "tenant_overrides",
]
