# Title identity rules

Built 2026-09-30. Code: `app/utils/title_identity.py`. Tests:
`tests/test_title_identity.py`. Measurement: `scripts/eval_title_identity.py`,
results in `reports/title_identity_eval_2026-09-30/`.

## What it does and why

Enumeration keeps asking one question: which government and which public
body does this title, playlist, gallery or channel belong to, and is it a
meeting at all? A frontier model answered it each time. On 2026-09-30 a
hand-read of 400+ census proposals rejected 50. Every reject broke a
simple rule. This module writes those rules down.

`classify_title(title, *, channel_name, channel_handle, station_state,
station_county_fips, known_gov_ids)` returns a `TitleVerdict` with
`meeting` (True, False or None), `body`, `gov_id`, `gov_kind`,
`confidence` (high, medium, low) and `reasons`. It also carries
`meeting_confidence` and `identity_confidence`, because the meeting call
and the government call can differ in strength. `confidence` is the
weaker of the two.

A blank is a finding. `meeting=None`, `gov_id=None` or `confidence=low`
means a model or a person must read it. The function never fills a gap.

## The rules

| Rule | What it stops |
|---|---|
| Body words (council, board, commission, selectboard, school committee, trustees, authority, town meeting, commissioners court ...) make a meeting | Nothing; this is the yes side |
| Non-meeting words (tour, sheriff town hall, party or candidate events, "presents", "corner" shows, debrief, rewind, sports, church, parent meetings, recreation department, the access station's own annual meeting ...) make it False | Shows filed as meetings |
| A named body wins over a topic word (tourism, sheriff, sports in a committee name) | Real committees called shows |
| Body plus meeting word plus a conflicting word (candidate, tour) is left unsettled | Both wrong answers |
| Words that are also English (Agenda, Council, Center, Union, Economy ...) never match a place alone; they need a type cue ("Town of X") or a match in `known_gov_ids` | "Economy PA", "Center township" |
| A type cue that does not fit the place ("Center City" vs Center township) rules the place out | Wrong township |
| Tokens inside a body phrase ("City Council") are never a place | "Council city, ID" |
| A school body maps only to a school district (`us:sd:`) or to none | A school board filed under a town |
| A county board of education is a county office, not the local unified district | Santa Clara County vs Santa Clara USD |
| If the title names a place the rules cannot settle, the single-known-government fallback does not run | Silent wrong guesses |
| A channel that names another state, a Canadian province, or another place blocks the mapping | Salmon Arm BC filed as Council ID |
| Legislature, senate, state board and court titles map to the state or to none; "Legislative Session" alone maps to none (could be a county legislature) | A legislature filed under a city |
| Special-district words: an existing registry id wins; else the body is the district and the government is the same-named local government (Ryan's rule); else none | Districts filed under the wrong city |

It reuses `gov_body_types.match_body_type_phrase` to decide county versus
school kind, and the `gov_registry` tables and `governments.csv` for names
and existing special-district ids. It reads no network and no database.

## Measured results

Full tables: `reports/title_identity_eval_2026-09-30/README.md`.

What was tested and why. Three label sets. First, 8,920 US Archive pages
(all real meetings), to measure how often it says "meeting" and returns
the page's own government. Second, the 2026-09-30 census hand-read, to
measure whether it catches what a person rejected and agrees with what a
person accepted. Third, all 27,814 census list titles, to count how many
it settles without a model.

| Question | Result |
|---|---|
| Archive pages it calls a meeting | 95.2% (8,493 of 8,920) |
| Archive pages it calls not a meeting | 0.5% (41); a hand-read of the distinct titles found about 4 real meetings among 58, the rest true non-meetings already in the Archive |
| Archive pages it cannot tell | 4.3% (386) |
| Government matches the page, state known, when one is returned | 97.1% (2,242 of 2,308) |
| Same, at high identity confidence | 97.7% (1,891 of 1,935) |
| Hand-rejected non-meetings caught | 13 of 15 |
| Hand-rejected wrong-government items caught | 12 of 12 |
| Hand-accepted items contradicted | 2 of 304; 212 agree; 90 left to a model |

Share of the 27,814 census list titles:

| Result | Count of titles | Share |
|---|---|---|
| Meeting yes/no settled at high confidence | 6,323 | 22.7% |
| Not a meeting, high confidence | 3,082 | 11.1% |
| Meeting and government, high confidence | 1,135 | 4.1% |
| Meeting, government not settled at high confidence | 5,098 | 18.3% |
| No body, meeting or non-meeting word at all | 18,494 | 66.5% |

Hand audit of the classifier's own calls (2026-09-30, 40 random titles
per group, read by Claude):

| Group | Wrong of 40 |
|---|---|
| Said not a meeting at high confidence | 1 (a committee on "Sports"; since fixed) |
| Said meeting with a government at high confidence | 0 visibly wrong |
| No evidence, left as a blank | 3 to 5 looked like real meetings (a council on aging, a fire district, a budget review). Two rules were added; the rest stay blank |

The last row is why "no evidence" stays a blank and is not turned into
"not a meeting": roughly one in ten of those titles may be a meeting.
Of those 18,494 titles, the census script had already flagged 16,060 as
off-mission. A caller that wants fewer model reads can treat
`NO_EVIDENCE_REASON` titles that the script also flags as "not a meeting"
and sample-check them. That is a caller decision, not made here.

## Caution

The rules were written from the 2026-09-30 rejects and tuned against the
same Archive and census data. There is no held-out set. The audit above
is the only independent read, and it is small. The non-meeting labels are
only 15 hand-rejected items. Treat the catch rate as an estimate.

The Archive contains real non-meetings (candidate forums, concerts,
graduations, state-of-the-city talks). The classifier rightly says "not a
meeting" for most of them, and the eval counts those as errors, so the
0.5% is an upper bound.

## Known gaps

- Shared stations: a generic "School Committee" or "Planning Commission"
  on a station with several governments stays unsettled unless the site
  or channel name names the place. 90 of 304 hand-accepted items are
  here. A model or the gallery's site context must decide.
- New England and New York towns and villages of one name (Red Hook town
  vs village): the type cue decides; without one the result is unsettled
  or medium.
- "Council on Aging" is a real board and a programs playlist. It is
  treated as a meeting unless the title says programs, classes or trips.
  One census reject ("Wenham Council On Aging") is missed.
- A real meeting that names candidates with no meeting word ("School
  Committee Superintendent Candidate Interview") is called not a meeting.
- Abbreviations (USBE, LA, EDA, TMAC) are not expanded.
- Canadian and non-US names are not mapped; the classifier returns no
  government for them.
- Special districts that have no registry id are filed under the local
  government by Ryan's rule; nothing mints new `rtr:` ids here.

## How to run

```
.venv/bin/python scripts/eval_title_identity.py --out reports/title_identity_eval_2026-09-30
```

The script reads the rtr-business census folder (`--research`, default the
session worktree path) and the two `apply_shared_station_census_*` scripts
for the hand-read REJECT lists (`--apply-dir`).
