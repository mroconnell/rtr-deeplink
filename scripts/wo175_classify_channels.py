"""WO-175 step 2: classify each of WO-171's 287 rejected LocalView
channels against the government it was assigned to, using the About
page signal wo175_fetch_about_pages.py collected.

Six verdicts (WO-175's work order, reusing WO-145's own "is this really
the same government" reasoning):

- `own-channel` -- the About page's own TITLE plainly names the
  government (the strongest signal: a channel's title is its own
  self-description, unlike a description or keyword field a third
  party could also stuff with a place name).
- `shared` -- the government's name shows up in the description or
  keywords (not the title) alongside real meeting language, or the
  title names the government but also reads as a community-media/
  access/news operation. Either way: a per-video pin only, never a
  channel-level one -- this channel is not certified to belong to the
  government the way `own-channel` is.
- `same-name-same-state-ambiguous` -- an official-government-shaped
  channel in the right state, but its title names a different place --
  a same-name collision for a human to resolve, not an automatic
  reject.
- `different-government` -- an official-government-shaped channel that
  names neither this government nor its state.
- `not-government` -- no tie to this government and no official marker
  at all (a person, a business, an unrelated channel).
- `unreachable` -- the About-page fetch failed or returned no channel
  metadata.
- `no-gov-id-assigned` -- WO-171's own place-decode step dropped this
  place for naming more than one government at once
  (wo171_localview_places.csv's `dropped_multi_city`); there is no
  single government to check the channel against, so no verdict beyond
  "hand-checked" is possible and no queueing action follows.

Writes rtr-business/research/wo175_channel_recheck.csv.

Usage:
    python scripts/wo175_classify_channels.py
"""

import csv
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.utils.gov_registry.registry import government_for_id  # noqa: E402

BUSINESS_RESEARCH = Path.home() / "Documents" / "rtr-business" / "research"
VERDICTS_CSV = BUSINESS_RESEARCH / "wo171_channel_verdicts.csv"
ABOUT_CSV = BUSINESS_RESEARCH / "wo175_about_fetch.csv"
OUT_CSV = BUSINESS_RESEARCH / "wo175_channel_recheck.csv"

GOV_SUFFIXES = [
    "consolidated government",
    "metropolitan government",
    "metro government",
    "unified government",
    "government",
    "corporation",
    "township",
    "borough",
    "village",
    "county",
    "parish",
    "town",
    "city",
    "cdp",
]

STOPWORDS = {"the", "of", "and", "a", "an"}

MEDIA_MARKERS = [
    "community media",
    "public access",
    "communications",
    "cable tv",
    "cable access",
    "access tv",
    " tv ",
    "news",
    "broadcast",
    "studio",
    "productions",
    "media group",
    "press",
    "tribune",
    "gazette",
    "journal",
    "peg ",
    "government access",
]

OFFICIAL_MARKERS = [
    "city of ",
    "town of ",
    "village of ",
    "township of ",
    "borough of ",
    "county of ",
    "city council",
    "town council",
    "village board",
    "town board",
    "county commission",
    "board of commissioners",
    "board of supervisors",
    "board of aldermen",
    "board of trustees",
    "board of selectmen",
    "select board",
    "selectboard",
    "municipal",
    "official channel",
    "government channel",
    "city hall",
    "county government",
    "board of education",
    "school district",
    "school board",
    "planning commission",
    "city government",
]

MEETING_WORDS = [
    "council",
    "commission",
    "board",
    "committee",
    "meeting",
    "meetings",
    "session",
    "hearing",
    "trustees",
    "supervisors",
    "assembly",
    "selectboard",
]

STATE_ABBR_TO_NAME = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
    "DC": "District of Columbia",
}


def _word_hit(text: str, word: str) -> bool:
    return re.search(r"\b" + re.escape(word) + r"\b", text) is not None


_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_ACRONYM_BOUNDARY_RE = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")


def split_camel_case(s: str) -> str:
    """A YouTube channel display name is often written with no spaces
    at all -- the exact bug WO-171 found and fixed for its own oEmbed-
    author check ("CityofTucson", "cityofminneapolis" were misread as a
    private person's name before that fix). This recheck's own title/
    description matching hits the identical shape: "JeffCityCouncil"
    (Jeffersonville city, IN's real council channel) reads as gibberish
    to a bare word-token match without this split. Inserts a space at
    every lower-to-upper letter transition, and also at an acronym-to-
    word boundary ("JCTVAccess" -> "JCTV Access") so a leading
    initialism doesn't swallow the real word after it. Does nothing to
    a bare all-caps acronym ("GCTVHD") or an all-lowercase handle
    ("wmpatv"), which is fine -- those have no case-boundary signal to
    recover."""
    s = _ACRONYM_BOUNDARY_RE.sub(" ", s or "")
    return _CAMEL_BOUNDARY_RE.sub(" ", s)


def name_tokens(s: str) -> set:
    s = re.sub(r"[^a-z0-9\s]", " ", split_camel_case(s).lower())
    return {t for t in s.split() if t and t not in STOPWORDS}


def _fuzzy_prefix_hit(gov_core: set, title_tokens: set) -> bool:
    """A title token that is an exact prefix of a long core-name token
    (e.g. "Jeff" of "Jeffersonville") -- a common informal abbreviation
    shape. Requires the token to be >=3 chars and the core name >=6, so
    a short coincidence ("Al" of "Alabama") can't fire. Deliberately
    weaker evidence than `title_name_hit` -- routes to the
    same-name-same-state-ambiguous "needs a human" bucket, never
    straight to own-channel/shared."""
    for gc in gov_core:
        if len(gc) < 6:
            continue
        for t in title_tokens:
            if len(t) >= 3 and gc.startswith(t):
                return True
    return False


_PLACE_OF_RE = re.compile(
    r"\b(?:city|town|village|township|borough|county) of "
    r"([a-z][a-z']*(?:[\s.-]+[a-z][a-z']*)?)"
)


def _named_conflicting_place(combined: str, gov_core: set) -> str:
    """A real, confirmed-live false-positive class this recheck's own
    broad any_name_hit rule hit: @losbanos406, assigned to "California
    City city, CA", has keywords "City of Los Banos California" --
    gov_core {"california","city"} is technically a subset of that
    text (both words appear), but the explicit phrase names a
    DIFFERENT real California city (Los Banos), not California City.
    Extracts every "<city/town/village/township/borough/county> of
    <name>" phrase in the text and returns the first whose own words
    share nothing with gov_core -- a named, different, real place, not
    a coincidental token overlap. Returns "" when no such conflicting
    phrase exists (the normal case)."""
    for m in _PLACE_OF_RE.finditer(combined):
        phrase_tokens = name_tokens(m.group(1))
        if phrase_tokens and gov_core and not (phrase_tokens & gov_core):
            return m.group(1).strip()
    return ""


def core_gov_tokens(gov_name: str) -> set:
    """Strips only a single TRAILING gov-type suffix -- the registry's
    own naming convention is "<place name> <type>" (e.g. "Jefferson
    City city", "Oklahoma City city"), so the type word is always the
    last token, never one to strip anywhere it appears in the string.
    A blind `\\bcity\\b` removal everywhere silently ate the "City" that
    is part of the real place name for every place whose own name
    contains a gov-type word -- Jefferson City, Oklahoma City, Garden
    City, Carson City, Cedar City -- turning "Jefferson City city" into
    just {"jefferson"} and making its real "JCTVAccess"-shaped channel
    unmatchable even after the acronym split above catches "JCTV
    Access". Confirmed live 2026-09-10 building this classifier."""
    n = (gov_name or "").strip().lower()
    for suf in sorted(GOV_SUFFIXES, key=len, reverse=True):
        pattern = rf"\s+{re.escape(suf)}$"
        if re.search(pattern, n):
            n = re.sub(pattern, "", n)
            break
    return name_tokens(n)


def main() -> None:
    with VERDICTS_CSV.open(newline="", encoding="utf-8") as f:
        verdicts = list(csv.DictReader(f))
    rejected = [r for r in verdicts if r["verdict"] == "rejected"]

    about_by_channel = {}
    if ABOUT_CSV.exists():
        with ABOUT_CSV.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                about_by_channel[r["channel_id"]] = r

    out_rows = []
    counts: dict = {}

    for row in rejected:
        cid = row["channel_id"]
        handle = row["handle"]
        gov_id = row["gov_id"].strip()
        about = about_by_channel.get(cid)

        result = {
            "channel_id": cid,
            "handle": handle,
            "gov_id": gov_id,
            "orig_name": row["name"],
            "orig_state": row["state"],
            "orig_oembed_author": row["oembed_author"],
            "about_title": "",
            "about_description": "",
            "new_verdict": "",
            "reasoning": "",
        }

        if not gov_id:
            result["new_verdict"] = "no-gov-id-assigned"
            result["reasoning"] = (
                "dropped_multi_city in wo171_localview_places.csv -- no single "
                f"government to check against ({row['name']!r})"
            )
            out_rows.append(result)
            counts[result["new_verdict"]] = counts.get(result["new_verdict"], 0) + 1
            continue

        gov = government_for_id(gov_id)
        gov_name = gov.gov_name if gov else row["name"]
        gov_state = gov.state if gov else row["state"]
        result["orig_name"] = gov_name
        result["orig_state"] = gov_state

        if about is None or about.get("error"):
            result["new_verdict"] = "unreachable"
            result["reasoning"] = (about or {}).get(
                "error"
            ) or "no About-page fetch on file"
            out_rows.append(result)
            counts[result["new_verdict"]] = counts.get(result["new_verdict"], 0) + 1
            continue

        title = about.get("title", "")
        desc = about.get("description", "")
        kw = about.get("keywords", "")
        result["about_title"] = title
        result["about_description"] = desc
        combined = split_camel_case(f"{title} {desc} {kw}").lower()

        gov_core = core_gov_tokens(gov_name)
        title_tokens = name_tokens(title)
        desc_kw_tokens = name_tokens(f"{desc} {kw}")
        all_tokens = title_tokens | desc_kw_tokens

        title_name_hit = bool(gov_core) and gov_core <= title_tokens
        any_name_hit = bool(gov_core) and gov_core <= all_tokens

        state_full = STATE_ABBR_TO_NAME.get(gov_state, "").lower()
        state_hit = bool(state_full) and state_full in combined
        state_abbr_hit = bool(gov_state) and re.search(
            rf"\b{re.escape(gov_state.lower())}\b", combined
        )

        has_media_marker = any(m in combined for m in MEDIA_MARKERS)
        has_official_marker = any(m in combined for m in OFFICIAL_MARKERS)
        has_meeting_word = any(_word_hit(combined, w) for w in MEETING_WORDS)

        conflict_place = (
            _named_conflicting_place(combined, gov_core) if not title_name_hit else None
        )
        # A single-word core name (very common for a one-word town name,
        # e.g. "Seminole") also matches a same-named but categorically
        # DIFFERENT real government -- confirmed live: @Seminole Nation
        # of Oklahoma's own tribal-nation channel matched "Seminole
        # city, OK"'s gov_core token on the word "seminole" alone.
        # A tribal nation is a real, separate sovereign government, not
        # this municipality, regardless of the name overlap.
        competing_entity = any(
            _word_hit(combined, w) for w in ("nation", "tribe", "tribal")
        )

        if conflict_place:
            result["new_verdict"] = "different-government"
            result["reasoning"] = (
                f"about-page explicitly names {conflict_place!r} as a 'city/town/"
                f"county of' place, which shares no words with {gov_name!r} -- "
                "a real, named different government (this gov's own name tokens "
                "may also appear elsewhere in the text, e.g. the state name, but "
                "that is coincidental next to this explicit, conflicting name)"
            )
        elif competing_entity:
            result["new_verdict"] = "different-government"
            result["reasoning"] = (
                f"about-page reads as a tribal nation/tribe, not {gov_name!r}'s own "
                f"municipal government -- a real, separate government despite the "
                f"name-token overlap (title={title!r})"
            )
        elif title_name_hit and has_media_marker:
            result["new_verdict"] = "shared"
            result["reasoning"] = (
                f"about-page title itself names {gov_name!r} but reads as a "
                "community/media/access channel, not a plain government account "
                f"(title={title!r})"
            )
        elif title_name_hit:
            result["new_verdict"] = "own-channel"
            result["reasoning"] = (
                f"about-page TITLE itself plainly names {gov_name!r} (title={title!r})"
            )
        elif any_name_hit and (has_meeting_word or has_official_marker):
            result["new_verdict"] = "shared"
            result["reasoning"] = (
                f"about-page title does not name {gov_name!r} (title={title!r}, "
                "likely a private/community operator), but its description/keywords "
                "do name it -- alongside real meeting language or an explicit "
                "'city of'/'county of' phrase -- per-video pin only "
                f"(description={desc[:120]!r}, keywords={kw[:120]!r})"
            )
        elif has_official_marker and (state_hit or state_abbr_hit):
            result["new_verdict"] = "same-name-same-state-ambiguous"
            result["reasoning"] = (
                f"official-government-shaped channel in {gov_state}, but title "
                f"{title!r} does not name {gov_name!r} -- possible same-name "
                "collision, needs a human"
            )
        elif has_official_marker and _fuzzy_prefix_hit(gov_core, title_tokens):
            result["new_verdict"] = "same-name-same-state-ambiguous"
            result["reasoning"] = (
                f"about-page reads as an official government channel; title "
                f"{title!r} does not exactly name {gov_name!r} but a title word is a "
                "plausible abbreviation of it (e.g. 'Jeff' / 'Jeffersonville') -- "
                "needs a human, not an automatic reject"
            )
        elif has_official_marker:
            result["new_verdict"] = "different-government"
            result["reasoning"] = (
                "about-page reads as an official government channel but names "
                f"neither {gov_name!r} nor {gov_state} (title={title!r})"
            )
        else:
            result["new_verdict"] = "not-government"
            result["reasoning"] = (
                f"about-page title/description ({title!r} / {desc[:80]!r}) shows no "
                f"tie to {gov_name!r} and no official-government marker"
            )

        out_rows.append(result)
        counts[result["new_verdict"]] = counts.get(result["new_verdict"], 0) + 1

    fieldnames = [
        "channel_id",
        "handle",
        "gov_id",
        "orig_name",
        "orig_state",
        "orig_oembed_author",
        "about_title",
        "about_description",
        "new_verdict",
        "reasoning",
    ]
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        w.writeheader()
        w.writerows(out_rows)

    print(f"Wrote {len(out_rows)} rows to {OUT_CSV}")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
