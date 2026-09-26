"""Steps 2-4 of Ryan's 2026-09-25 spec: given real YouTube data already
fetched for one lead row, decide identity + on-mission + pick one meeting.
Pure judgment, no network calls -- the caller (drip lane or test harness)
does the fetching and passes in what came back, so this is unit-testable
and reusable from either place.
"""

import re
from dataclasses import dataclass
from typing import Optional

BODY_WORDS = (
    "council",
    "board",
    "commission",
    "committee",
    "trustees",
    "selectboard",
    "select board",
    "public hearing",
    "work session",
    "budget hearing",
    "budget session",
    "boe",
    "bos",
    "town board",
    "supervisors",
    "assembly",
)
# Abbreviations need a word boundary but are short enough to false-positive
# inside another word if not careful (e.g. "bos" inside a longer token) --
# \b already guards that in _word_hit below.

DATE_RE = re.compile(
    r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2}|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s*\d{0,4}"
    r"|\b20\d{2}\b)",
    re.I,
)

NON_MEETING_WORDS = (
    "promo",
    "graduation",
    "commencement",
    "playoff",
    "championship",
    "game",
    "concert",
    "recital",
    "ribbon cutting",
    "ribbon-cutting",
    "groundbreaking",
    "news",
    "newscast",
    "press conference",
    "interview",
    "parade",
    "festival",
    "tour of",
    "welcome to",
    "highlight",
    "sizzle reel",
    "tribute",
    "candidate forum",
    "meet the candidates",
    "swearing in",
    "swearing-in",
    "oath of office",
    "award",
    "recognition ceremony",
    "job fair",
)

SCHOOL_EVENT_WORDS = (
    "choir",
    "chorus",
    "band concert",
    "spring concert",
    "winter concert",
    "school play",
    "musical",
    "theater",
    "theatre",
    "talent show",
    "pep rally",
    "homecoming",
    "prom",
    "spelling bee",
    "science fair",
    "morning announcements",
    "sports",
    "football",
    "basketball",
    "volleyball",
    "wrestling",
    "cheerleading",
    "marching band",
    "graduation",
)

NOT_A_PUBLIC_BODY_WORDS = (
    "news",
    "tv station",
    "channel 9",
    "channel 7",  # local news stations often self-describe this way
    "chamber of commerce",
    "booster club",
    "boosters",
    "friends of the library",
)

WRONG_TYPE_WORDS = (
    ("school", "township"),
    ("school", "city"),  # a school channel vs a muni gov_id, checked contextually
)


def _word_hit(haystack_lower: str, phrase: str) -> bool:
    return re.search(r"\b" + re.escape(phrase) + r"\b", haystack_lower) is not None


def _norm_words(s):
    stop = {
        "city",
        "town",
        "village",
        "county",
        "township",
        "borough",
        "of",
        "the",
        "district",
        "school",
        "government",
        "official",
    }
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if w not in stop}


@dataclass
class IdentityVerdict:
    tier: str  # "strong" | "medium" | "wrong-government" | "needs-human"
    reason: str
    right_gov_name: Optional[str] = (
        None  # only set when the page itself names the right one
    )


def assess_identity(
    *,
    channel_title,
    channel_description,
    gov_name,
    gov_state,
    gov_kind,
    linked_from_gov_site: bool,
    kind: str,
) -> IdentityVerdict:
    """Step 2. `linked_from_gov_site` is True when the lead's own provenance
    (source_wo / note) already establishes it was found by walking the
    government's own website -- callers derive this from the CSV row, not
    from a network call."""
    ct = channel_title or ""
    ct_low = ct.lower()
    desc_low = (channel_description or "").lower()
    gov_words = _norm_words(gov_name)
    name_matches = bool(gov_words) and gov_words.issubset(_norm_words(ct))

    for w in NOT_A_PUBLIC_BODY_WORDS:
        if _word_hit(ct_low, w) or _word_hit(desc_low, w):
            return IdentityVerdict(
                "wrong-government",
                f"channel reads as a non-government body (matched {w!r})",
            )

    # About-page / description linking the gov's own domain is Strong on its
    # own (caller passes gov_domain-in-description as part of description
    # text already, via a substring the fetch step checked).
    about_links_gov = "GOVSITE_MATCH" in desc_low  # sentinel the caller sets

    if name_matches and (linked_from_gov_site or about_links_gov):
        return IdentityVerdict(
            "strong",
            "channel name matches the government and is linked from/links back to its own site",
        )

    if name_matches:
        return IdentityVerdict(
            "medium",
            "name matches in the channel name; no independent linkage confirmed yet",
        )

    return IdentityVerdict(
        "needs-human",
        "no clear name match and no site linkage -- could be a shared channel or an unrelated one; a person should look",
    )


@dataclass
class CandidateVerdict:
    bucket: str  # "meeting" | "not-a-meeting" | "school-event" | "embed-restricted" | "dead"
    reason: str
    has_body_word: bool = False
    has_date: bool = False


def assess_candidate(
    title, *, gov_kind: str, playable: bool = True
) -> CandidateVerdict:
    """Step 3, one video. `gov_kind` == 'school_district' triggers the
    stricter rule: ONLY a real board meeting counts, every other school
    upload (news, theater, choir, sports, band) is excluded regardless of
    how meeting-shaped its title otherwise looks."""
    t = title or ""
    t_low = t.lower()

    if not playable:
        return CandidateVerdict(
            "embed-restricted", "recorded only, per instruction -- never worked around"
        )

    if gov_kind == "school_district":
        for w in SCHOOL_EVENT_WORDS:
            if _word_hit(t_low, w):
                return CandidateVerdict(
                    "school-event", f"school event, not a board meeting (matched {w!r})"
                )

    for w in NON_MEETING_WORDS:
        if _word_hit(t_low, w):
            return CandidateVerdict("not-a-meeting", f"matched non-meeting word {w!r}")

    has_body = any(_word_hit(t_low, w) for w in BODY_WORDS)
    has_date = bool(DATE_RE.search(t))

    if has_body and has_date:
        return CandidateVerdict(
            "meeting", "has a body word and a date/session marker", True, True
        )
    if has_body:
        return CandidateVerdict(
            "meeting",
            "has a body word, no explicit date but a session name may substitute",
            True,
            False,
        )

    return CandidateVerdict(
        "not-a-meeting", "no governing-body word in the title", False, has_date
    )


def confidence_rank(cv: CandidateVerdict):
    """Higher is better. Step 4 (corrected 2026-09-25): pick the most
    AUTHORITATIVE candidate, never the shortest -- length plays no role at
    all here on purpose."""
    return (1 if cv.has_body_word else 0) + (1 if cv.has_date else 0)


def pick_best_meeting(candidates_with_titles, gov_kind):
    """candidates_with_titles: list of (video_id, title, duration_s, playable).
    Returns (video_id, title, CandidateVerdict) for the highest-confidence
    real meeting, or None if none of the given candidates is one."""
    scored = []
    for vid, title, dur, playable in candidates_with_titles:
        cv = assess_candidate(title, gov_kind=gov_kind, playable=playable)
        if cv.bucket == "meeting":
            scored.append((confidence_rank(cv), vid, title, cv))
    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    _, vid, title, cv = scored[0]
    return vid, title, cv
