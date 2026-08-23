"""The curated topic list behind the state/hub pages' topic chips.

**This file is meant to be edited by hand.** It is the one place that
decides which phrases get counted, ranked into chips, and highlighted
inside transcript snippets -- add a row when a subject starts showing up
in local-government news, delete one that stops earning its place.

Why curated rather than discovered: an unsupervised "trending terms"
pass over council transcripts surfaces `item`, `supervisor`, `motion`
-- the vocabulary of procedure, not of subject matter. Ranking a
*curated* list by real corpus hits per state gets the useful half of
"trending" (which of these subjects is live in this state right now)
without the noise. Round 2 can re-rank this same list by real visitor
searches once `search_queries` has data; the list itself stays curated.

Each topic is `(slug, label, patterns)`:

* `slug`    -- the `?topic=` URL value. Stable: changing it breaks any
               link Google has already indexed, so prefer adding a new
               topic to renaming one.
* `label`   -- the chip's display text, sentence case.
* `patterns`-- phrases matched case-insensitively on word boundaries
               against the transcript. Include the plural and the
               common transcription variants; Whisper reliably nails
               concrete noun phrases ("data center", "license plate
               reader") and reliably mangles acronyms said quickly, so
               prefer spelled-out phrases over initialisms.

Keep `patterns` specific enough that a hit means the meeting really
discussed the subject. "police" alone matches every consent calendar in
America, which is why the public-safety topics below are phrased around
the *contested* thing (surveillance, use of force) rather than the
department name.
"""

from __future__ import annotations

import re
from typing import NamedTuple, Optional


class Topic(NamedTuple):
    slug: str
    label: str
    patterns: tuple[str, ...]
    # Pinned topics always get a chip when they have at least one meeting
    # behind them, even if they rank below the count cutoff. These are the
    # subjects worth surfacing because they are *newsworthy*, not because
    # they are frequent -- the frequent ones (property taxes, libraries)
    # win on count anyway and need no help. Still never rendered at zero:
    # a chip leading to an empty page is worse than no chip.
    pinned: bool = False


TOPICS: tuple[Topic, ...] = (
    Topic(
        "data-centers",
        "Data centers",
        ("data center", "data centers", "data centre", "hyperscale", "server farm"),
        pinned=True,
    ),
    # Split out of surveillance-cameras 2026-08-23: Flock is a specific,
    # named vendor that residents show up to speak about by name, and
    # burying it inside a generic "surveillance cameras" chip hid the
    # thing people actually search for. The bare "flock" pattern was
    # checked against the real corpus before shipping -- 131 meetings
    # mention it and all 14 stored highlights containing it are about the
    # company, not birds -- so the obvious false positive does not happen
    # here in practice. "flocks" is included because transcription
    # reliably produces it ("the flocks safety cameras", confirmed live).
    Topic(
        "flock-cameras",
        "Flock cameras",
        (
            "flock",
            "flocks",
            "flock safety",
            "flock camera",
            "flock cameras",
            "flock system",
            "flock contract",
        ),
        pinned=True,
    ),
    Topic(
        "surveillance-cameras",
        "Surveillance cameras",
        (
            # Flock terms stay here as well as in the dedicated
            # `flock-cameras` topic above: Flock *is* surveillance, a
            # strict subset, so a reader clicking either chip should find
            # these meetings. Topics deliberately overlap -- a meeting
            # carries a moment per matching topic, and the split exists
            # to give Flock its own findable chip, not to narrow what
            # counts as surveillance.
            "flock",
            "flocks",
            "flock safety",
            "license plate readers",
            "automated license plate",
            "surveillance camera",
            "surveillance cameras",
            "facial recognition",
            "ring camera",
        ),
    ),
    Topic(
        "homelessness",
        "Homelessness",
        (
            "homeless",
            "homelessness",
            "encampment",
            "encampments",
            "unhoused",
            "shelter beds",
            "transitional housing",
        ),
    ),
    Topic(
        "housing-development",
        "Housing & development",
        (
            "affordable housing",
            "housing element",
            "accessory dwelling",
            "density bonus",
            "mixed use development",
            "housing production",
        ),
    ),
    Topic(
        "rent-tenants",
        "Rent & tenants",
        (
            "rent control",
            "rent stabilization",
            "tenant protection",
            "tenant protections",
            "just cause eviction",
            "eviction moratorium",
            "displacement",
        ),
    ),
    Topic(
        "property-taxes",
        "Property taxes",
        (
            "property tax",
            "property taxes",
            "parcel tax",
            "assessed value",
            "tax rate",
            "transfer tax",
            "sales tax measure",
        ),
    ),
    Topic(
        "budget-shortfall",
        "Budget shortfalls",
        (
            "budget deficit",
            "budget shortfall",
            "structural deficit",
            "reserve fund",
            "layoffs",
            "hiring freeze",
            "furlough",
        ),
    ),
    Topic(
        "policing",
        "Policing & oversight",
        (
            "use of force",
            "police oversight",
            "police accountability",
            "body camera",
            "body cameras",
            "police budget",
            "civilian oversight",
        ),
    ),
    Topic(
        "immigration",
        "Immigration enforcement",
        (
            "sanctuary city",
            "sanctuary policy",
            "immigration enforcement",
            "immigration and customs",
            "deportation",
            "border patrol",
        ),
    ),
    Topic(
        "wildfire",
        "Wildfire & emergency",
        (
            "wildfire",
            "wildfires",
            "fire hazard",
            "defensible space",
            "evacuation route",
            "evacuation routes",
            "fuel reduction",
            "red flag warning",
        ),
    ),
    Topic(
        "water",
        "Water supply",
        (
            "water rate",
            "water rates",
            "water supply",
            "groundwater",
            "drought",
            "water district",
            "reclaimed water",
            "sewer rate",
        ),
    ),
    Topic(
        "traffic-safety",
        "Traffic & street safety",
        (
            "traffic calming",
            "road diet",
            "bike lane",
            "bike lanes",
            "crosswalk",
            "pedestrian safety",
            "speed limit",
            "vision zero",
            "roundabout",
        ),
    ),
    Topic(
        "parking",
        "Parking",
        (
            "parking requirement",
            "parking requirements",
            "parking minimum",
            "parking minimums",
            "parking garage",
            "permit parking",
            "parking meter",
        ),
    ),
    Topic(
        "short-term-rentals",
        "Short-term rentals",
        (
            "short term rental",
            "short-term rental",
            "short term rentals",
            "vacation rental",
            "vacation rentals",
            "airbnb",
        ),
    ),
    Topic(
        "cannabis",
        "Cannabis",
        ("cannabis", "dispensary", "dispensaries", "marijuana", "cultivation permit"),
    ),
    Topic(
        "warehouses",
        "Warehouses & logistics",
        (
            "warehouse",
            "warehouses",
            "distribution center",
            "logistics center",
            "truck route",
            "truck traffic",
        ),
    ),
    Topic(
        "clean-energy",
        "Solar & battery storage",
        (
            "battery storage",
            "battery energy storage",
            "solar farm",
            "solar array",
            "rooftop solar",
            "microgrid",
            "electric vehicle charging",
        ),
    ),
    Topic(
        "schools",
        "Schools",
        (
            "school board",
            "school district",
            "enrollment decline",
            "declining enrollment",
            "school closure",
            "school closures",
            "curriculum",
        ),
    ),
    Topic(
        "libraries-parks",
        "Libraries & parks",
        (
            "library hours",
            "library branch",
            "park improvement",
            "park improvements",
            "playground",
            "community center",
            "open space",
        ),
    ),
    Topic(
        "elections",
        "Elections & districting",
        (
            "district map",
            "redistricting",
            "ballot measure",
            "voter turnout",
            "campaign finance",
            "ranked choice",
        ),
    ),
)

TOPICS_BY_SLUG: dict[str, Topic] = {t.slug: t for t in TOPICS}

# v2 (2026-08-23): split `flock-cameras` out of `surveillance-cameras`.
#
# Bumped whenever the phrase lists above change in a way that should
# invalidate every stored highlight (see MeetingHighlight.topics_version):
# a meeting whose stored topic moments were computed under an older list
# is recomputed by scripts/backfill_meeting_highlights.py rather than
# silently keeping stale topic tags. Adding a whole new Topic row counts;
# fixing a typo in a `label` does not.
TOPICS_VERSION = 2


def _compile(topic: Topic) -> re.Pattern:
    # Word-boundary alternation, longest-first so "short-term rental"
    # wins over a hypothetical "rental". \b works on the hyphenated
    # variants because the hyphen is itself a boundary character.
    alts = sorted(topic.patterns, key=len, reverse=True)
    return re.compile(
        r"\b(?:" + "|".join(re.escape(a) for a in alts) + r")\b", re.IGNORECASE
    )


_COMPILED: dict[str, re.Pattern] = {t.slug: _compile(t) for t in TOPICS}


def topic_pattern(slug: str) -> re.Pattern:
    """The compiled matcher for one topic slug. KeyError for an unknown
    slug -- callers taking a slug from a URL should check TOPICS_BY_SLUG
    first and 404/ignore, never pass user input straight in."""
    return _COMPILED[slug]


def topics_in(text: str) -> list[str]:
    """Slugs of every topic whose phrases appear in `text`, in TOPICS
    order (i.e. curation order, not match order)."""
    if not text:
        return []
    return [t.slug for t in TOPICS if _COMPILED[t.slug].search(text)]


_ANY_TOPIC: Optional[re.Pattern] = None


def any_topic_pattern() -> re.Pattern:
    """One combined alternation over every curated phrase.

    For *scoring* a candidate window the only question is how many topic
    phrases it contains, not which -- and running 20 separate patterns to
    answer that dominated the profile on long meetings (tens of thousands
    of windows each). Built lazily and cached; topics_in() still gives
    the per-topic breakdown wherever that is what's actually needed."""
    global _ANY_TOPIC
    if _ANY_TOPIC is None:
        phrases = sorted(
            {phrase for topic in TOPICS for phrase in topic.patterns},
            key=len,
            reverse=True,
        )
        _ANY_TOPIC = re.compile(
            r"\b(?:" + "|".join(re.escape(p) for p in phrases) + r")\b",
            re.IGNORECASE,
        )
    return _ANY_TOPIC
