"""The WO-191 video hand-check phrase list, `classify_video_hand_check()` --
lifted out of `scripts/wo174_pipeline.py` (WO-227, 2026-09-11) into a
shared place so `app/platforms/boxcast.py` can reuse it too, per CLAUDE.md's
platform-wrapper/reuse convention: this repo never duplicates a
phrase-list/classifier when a shared import is available instead.

`scripts/` has no top-level package the way `app/` does and `app/`
adapters must never depend on `scripts/` (the dependency only ever runs
the other way -- a sweep script imports the adapters it drives), so this
couldn't stay in `scripts/wo174_pipeline.py` once an adapter needed it
too. `scripts/wo174_pipeline.py` now imports `classify_video_hand_check`
from here instead of defining it locally -- every existing caller
(`scripts/wo216_access_ladder_sweep.py`, `scripts/wo217_handcheck.py`,
`tests/test_wo174_hand_check.py`, all of which import it off
`scripts.wo174_pipeline`) is unaffected, since that module still exposes
the same name.

Before a video is accepted, look at its own title/channel text for signs
it belongs to a DIFFERENT identifiable body (Kind A) or is real content
from what looks like this government's own channel but isn't a
deliberative meeting (Kind B). WO-191's own by-hand oEmbed audit of one
798-government batch found 8 of 80 "found" videos wrong on inspection,
every one from this exact gap: a school board, a state DOT district,
regional/multi-township commissions, a county assessor, and two
ceremonies/recruitment videos (see `BACKLOG_DONE.md`'s WO-191 entry for
the real, confirmed examples this phrase list is built from).

Deliberately conservative and phrase-based -- not a general classifier,
and it will not catch a mismatch that doesn't name itself in the
title/channel text (e.g. a proper-noun-only regional body whose name
doesn't contain any of these generic phrases). A miss here is not new
risk: WO-191's own by-hand oEmbed check remains the backstop this
doesn't replace, and every ingest this run makes is still available for
that same audit. A false trigger only costs one extra candidate-video
try (Kind B) or one skipped government whose real owner gets recorded
for a human to check (Kind A).
"""

import re

# Kind A: the title/channel names a different, identifiable body -- never
# this government's own meeting, regardless of gov_kind. Each phrase maps
# to a short, generic description of the likely real owner, for a human
# (WO-201's own cross-government cleanup) to follow up on -- these bodies
# mostly aren't in our own government registry at all (school districts,
# state DOT districts, and regional/multi-township commissions are a
# different KIND of entity than the general-purpose governments this
# project tracks), so no gov_id lookup is attempted here.
_HAND_CHECK_KIND_A_PHRASES = (
    ("school board", "the named school district's own board"),
    ("board of education", "the named school district's own board"),
    ("school committee", "the named school district's own committee"),
    ("board of assessors", "a county/regional assessor's office"),
    ("county assessor", "the named county's assessor's office"),
    (
        "department of transportation",
        "a state department of transportation district office",
    ),
    ("state police", "a state police barracks/troop, not a local government"),
    ("council of governments", "a regional council of governments"),
    (
        "regional planning commission",
        "a regional, multi-jurisdiction planning commission",
    ),
    (
        "metropolitan planning organization",
        "a regional metropolitan planning organization",
    ),
    ("river commission", "a regional, multi-jurisdiction river/watershed commission"),
    ("watershed commission", "a regional, multi-jurisdiction watershed commission"),
    ("interstate commission", "a multi-state regional commission"),
)

# Kind B: content that looks like it's from this government's own channel
# but isn't a deliberative meeting -- try the next candidate video
# instead of ingesting this one.
_HAND_CHECK_KIND_B_PHRASES = (
    "swearing in",
    "swearing-in",
    "oath of office",
    "inaugural ceremony",
    "ribbon cutting",
    "ribbon-cutting",
    "groundbreaking",
    "ground breaking",
    "why run for",
    "run for city council",
    "run for town council",
    "run for township",
    "candidate forum",
    "meet the candidates",
    "recruitment video",
    "award ceremony",
    "recognition ceremony",
)


# State DOT district/region channels are commonly named by gluing a
# state abbreviation straight onto "DOT" with no space or punctuation
# ("PennDOT District 6-0", "NYSDOT Region 8", "CTDOT District 3") --
# a plain word-bounded "department of transportation" phrase never
# matches that shape, so this is checked separately, unanchored at the
# start (deliberately, to match inside "penndot") but still requiring
# "district"/"region" right after "dot" so a state's OWN transportation
# department meeting doesn't get flagged if it somehow named itself with
# a full "Department of Transportation" phrase elsewhere (already caught
# by the phrase list above) while a completely unrelated word ending in
# "dot" (there are essentially none in real channel names) doesn't
# false-positive on the word "district"/"region" alone.
_STATE_DOT_CHANNEL_RE = re.compile(r"dot\s+(district|region)\b")


def _hand_check_phrase_hit(haystack_lower: str, phrase: str) -> bool:
    return re.search(r"\b" + re.escape(phrase) + r"\b", haystack_lower) is not None


def classify_video_hand_check(title, channel_text, gov_name, gov_kind):
    """Returns None (no concern), or (kind, reason) where kind is "A" or
    "B" -- see module comment above. `gov_name`/`gov_kind` are accepted
    for a future, more targeted check but unused by today's phrase list
    (every phrase here is already specific enough not to need them --
    e.g. "school board" never means THIS government's own board, whatever
    its name). `channel_text` is whatever channel-derived text the
    adapter already resolved (YouTube's `video_channel` handle plus its
    own validated `jurisdiction` guess -- see `resolve_candidate()`'s
    caller) -- no extra network call is made here, this only reads
    fields the resolve step already populated."""
    title_low = (title or "").lower()
    channel_low = (channel_text or "").lower()
    haystack = f"{title_low} {channel_low}"

    for phrase, owner_hint in _HAND_CHECK_KIND_A_PHRASES:
        if _hand_check_phrase_hit(haystack, phrase):
            return ("A", f"{owner_hint} (matched {phrase!r})")

    if _STATE_DOT_CHANNEL_RE.search(haystack):
        return (
            "A",
            "a state department of transportation district/region office "
            "(matched a 'DOT district/region'-shaped channel name)",
        )

    for phrase in _HAND_CHECK_KIND_B_PHRASES:
        if _hand_check_phrase_hit(title_low, phrase):
            return ("B", f"title suggests non-meeting content (matched {phrase!r})")

    return None
