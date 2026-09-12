# Hop-link scorer: re-weighted from measured data (WO-274)

Written 2026-09-12. Read this before touching `find_hop_links()`,
`_score_hop_candidate*()`, `HOP1_HINT_WORDS`, or
`app/utils/jurisdiction_data/hop_link_weights.csv` in
`scripts/wo147_access_ladder_sweep.py`.

## Why

`find_hop_links()` picks up to 8 links off a government's own homepage
that look like they lead to its meeting/agenda hub. Until WO-228
(2026-09-11) it kept the first 8 links matching any of 12 hand-picked
words (`HOP1_HINT_WORDS`); WO-228 added a scorer but kept the same 12
words as the candidate gate. This WO (2026-09-12) measured those words
against real data and found the list backwards: on a government's own
domain, "calendar" and singular "agenda" are near noise (lift 3.5x and
1.3x vs an ordinary link), "video"/"stream" almost never appear on a hub
page at all (7 of 957 real hubs), while the plural/role words the list
lacks are the strongest signal measured (agendas, meetings,
commissioners, boards, supervisors), and named platform paths are close
to perfect (AgendaCenter, Hyland's ViewMeeting/AgendaOnline).

This WO re-derives that measurement itself (`scripts/derive_hop_weights.py`,
reproducible, no network fetches) and ships a re-weighted scorer driven
by a data file rather than a hand-picked list.

## Method

Three separate positive URL sets, each measured against a pool of
ordinary links pulled from every real page WO-267 saved (713 pages: 180
homepages + 137 hub pages from WO-267's own positive sample, plus 396
negative-control homepages -- more than the 576 the brief anticipated;
see "Corrections to the brief" below):

- **`hub_firstparty`** (956 URLs): `jurisdiction_coverage.csv` rows with
  `transcribed=true`, `example_agenda_or_calendar_url` non-blank and not
  an internal `/m/<slug>` permalink, restricted to the government's own
  domain (not a known meeting-vendor host).
- **`meeting_firstparty`** (24 URLs): same population,
  `example_meeting_url`, first-party. Small on purpose -- most real
  meeting videos are vendor-hosted, not on the government's own domain.
- **`meeting_vendor`** (10,885 URLs): `example_meeting_url` on a
  vendor host, UNIONED with 8,483 real Archive page source URLs and
  2,259 real tier-3-queue URLs (both already-live population, not a
  fresh sample).
- **`hub_anchor_text`** (81 matched links): anchor TEXT of every link,
  across all 713 saved pages, whose href exactly matches (normalized
  host+path) a `hub_firstparty` URL. Small sample -- see caution below.

Each URL's path is tokenized (split on non-letters) plus its query
STRING NAMES (not values); adjacent-token bigrams are computed the same
way for the hub set. Lift = (rate in positives) / (rate in negatives),
+0.5 smoothing, support floor of 10 positive occurrences (5 for the
small anchor-text sample) before a token is trusted at all -- an absent
token scores 0 at runtime, it is never assumed negative.
`weight = log(lift)`, capped at +/-7.0. Output:
`app/utils/jurisdiction_data/hop_link_weights.csv` (185 rows).

## Corrections to the brief

- **713 real saved pages exist, not 576.** The brief's "Inputs on disk"
  section names 576; the actual count on disk
  (`wo267_raw/*_home.html` + `*_hub.html` + `wo267_raw_neg/*.html`) is
  713 (180 + 137 + 396). Used all 713 -- more real data, not less.
- **147 of the 180 positive homepages have a non-blank recorded
  hub/meeting URL** in `jurisdiction_coverage.csv` (via WO-267's own
  `best_url()` selection), not all 180 as the brief states. The
  remaining 33 are governments whose `transcribed=true` row still has
  no non-internal `example_meeting_url`/`example_agenda_or_calendar_url`
  at all (the row qualified for WO-267's sample via its `domain` field
  alone). All 180 are still used for the video-straight-from-homepage
  measurement (step 4), which doesn't need a recorded URL.
- Two real contamination/regression issues were found and fixed while
  building this table (both are true measured findings from real data,
  not hypothetical): see "Two real regressions this WO found and fixed"
  below.

## Full measured signal tables

`positives`/`negatives` = how many URLs on each side contain the token
at least once. `lift` = positive rate / negative rate. `weight` =
`log(lift)`, capped.

### HUB (first-party) token lift, vs 29,032 first-party ordinary links

| Token | Lift | Positives/Negatives | Weight |
|---|---|---|---|
| agendas | 15.5x | 125/246 | 2.74 |
| agendacenter | 12.0x | 281/714 | 2.48 |
| meetings | 11.5x | 70/186 | 2.44 |
| commissioners | 11.3x | 34/92 | 2.43 |
| supervisors | 9.4x | 12/40 | 2.24 |
| council | 8.3x | 116/426 | 2.12 |
| mayor | 7.3x | 24/102 | 1.98 |
| calendar | 5.8x | 83/439 | 1.75 |
| boards | 5.6x | 45/246 | 1.72 |
| minutes | 5.3x | 104/603 | 1.66 |
| commission | 4.8x | 25/160 | 1.57 |
| commissions | 4.6x | 29/196 | 1.52 |
| city | 3.5x | 105/909 | 1.26 |
| meeting | 3.4x | 30/273 | 1.22 |
| board | 2.6x | 66/766 | 0.97 |
| government | 2.0x | 136/2107 | 0.68 |
| town | 1.7x | 23/424 | 0.52 |
| committees | 1.7x | 10/191 | 0.51 |
| agenda | 1.0x | 20/609 | 0.02 |

**Plurals beat singulars by a wide margin** (agendas 15.5x vs agenda
1.0x -- the central finding this WO was commissioned to fix), and
"video"/"stream" don't appear in this table at all -- neither cleared
the 10-positive support floor (7 of 957 real hubs contain either word,
confirming the conductor's own HUB LIFT note in `conductor_state.md`).

### HUB (first-party) bigram lift

| Bigram | Lift | Positives/Negatives | Weight |
|---|---|---|---|
| board-commissioners | 51.8x | 14/8 | 3.95 |
| council-index | 42.5x | 17/12 | 3.75 |
| public-meetings | 22.5x | 11/15 | 3.11 |
| board-supervisors | 20.6x | 10/15 | 3.02 |
| agendas-minutes | 20.2x | 79/119 | 3.01 |
| city-council | 15.4x | 73/144 | 2.74 |
| government-board | 13.2x | 18/42 | 2.58 |
| calendar-aspx | 10.5x | 27/79 | 2.35 |
| government-city | 7.4x | 34/141 | 2.00 |
| boards-commissions | 6.4x | 20/97 | 1.85 |
| government-agendas | 5.0x | 11/69 | 1.61 |
| government-boards | 3.5x | 14/127 | 1.24 |

### MEETING (first-party) token lift, vs the same 29,032 first-party links

| Token | Lift | Positives/Negatives | Weight |
|---|---|---|---|
| viewmeeting | 29,625x | 12/0 | 7.00 (capped) |
| doctype | 29,625x | 12/0 | 7.00 (capped) |
| onbaseagendaonline | 251.4x | 10/49 | 5.53 |
| meetings | 92.1x | 14/186 | 4.52 |

Only 24 first-party meeting positives exist (most real meeting video is
vendor-hosted), so this table is thin -- but it's exactly the Hyland/
OnBase signal `docs/investigations/platform_fingerprints.md` already
confirmed: `AgendaOnline/Meetings/ViewMeeting` catches every real tenant
in that WO's sample regardless of hostname.

### MEETING (vendor-host) token lift, vs 31,754 ordinary links (any host)

| Token | Lift | Positives/Negatives | Weight |
|---|---|---|---|
| clip | 12,097x | 2073/0 | 7.00 (capped) |
| mediaplayer | 5,966x | 1022/0 | 7.00 (capped) |
| meetinginformation | 1,928x | 330/0 | 7.00 (capped) |
| splitview | 1,642x | 281/0 | 7.00 (capped) |
| meetingtemplateid | 1,018x | 174/0 | 6.93 |
| watch | 311.6x | 2937/27 | 5.74 |
| frame | 176.0x | 90/1 | 5.17 |

Named vendor-shape tokens are essentially a perfect signal, matching the
conductor's LIFT-over-ALL note.

### Anchor text for links matching a known hub URL (n=81 -- small sample, do not over-claim)

| Word | Lift | Positives/Negatives | Weight |
|---|---|---|---|
| agendas | 51.7x | 31/215 | 3.95 |
| commissioners | 36.2x | 6/63 | 3.59 |
| minutes | 30.8x | 26/304 | 3.43 |
| boards | 16.9x | 6/136 | 2.82 |
| meetings | 8.5x | 5/228 | 2.14 |
| council | 6.5x | 9/513 | 1.88 |
| board | 5.9x | 10/626 | 1.78 |
| meeting | 4.2x | 6/547 | 1.44 |
| of | 2.9x | 9/1176 | 1.05 |

81 real matched links is a real but small sample -- the vocabulary above
is directionally trustworthy (the words all make sense) but is missing
words a larger sample would surely add ("committee", "supervisors" as
anchor text specifically). This gap is exactly what caused one of the
two regressions below.

## Two real regressions this WO found and fixed while building the scorer

Both were caught by running the new scorer against the SAME real
fixture pages `tests/test_hub_link_ranking.py` already checks in, before
shipping -- not found by inspection.

1. **Calendar/alert-widget query params leaked into the HUB positive set
   as if they were real signal.** `jurisdiction_coverage.csv`'s own
   recorded `example_agenda_or_calendar_url` is not always a real
   meeting hub -- some rows still carry a bare calendar list-view or a
   CivicPlus "CivicAlerts" news-board page, a residual of the exact bug
   WO-228 describes fixing going forward (358 governments got a
   calendar-shaped hub recorded as a direct result of the OLD
   first-match scorer) that was never swept out of the research file
   afterward. Their `day=`/`month=`/`year=`/`CID=`/`AID=` query names
   scored as real hub vocabulary, which: (a) ranked Madison County TN's
   bare `calendar.aspx?...CID=...` list view above its own real dated
   committee entries, and (b) ranked a Cleveland County OK
   `CivicAlerts.aspx?AID=122` PRESS RELEASE ("Board of County
   Commissioners Response to Call for Special Election" -- a news item,
   not a meeting) above the government's real Legistar link, purely on
   anchor-text words ("board", "commissioners") that are real hub
   vocabulary but also just... ordinary bureaucratic prose. Fixed two
   ways: (1) a stoplist for the specific contaminated query-param names
   (`derive_hop_weights.py`'s `_STOPWORD_TOKENS`), and (2) anchor-text
   vocabulary can no longer, by itself, qualify a candidate -- a link
   needs real PATH or target-shape evidence too
   (`_score_hop_candidate_weighted()`'s qualification check). Both
   fixtures are now regression tests in `tests/test_hop_scorer_weighted.py`.
2. **A hand-added "vendor host" (`meetings.municode.com`, not measured
   data) turned out to be wrong.** Eustis FL's real Municode Meetings
   tenant homepage IS its own meeting listing (individual
   `city-commission-meeting-NN` entries sit directly on the fetched
   homepage) -- but `meetings.municode.com/adaHtmlDocument/...` links
   (an ADA-accessible MIRROR of the same entries, on a different
   subdomain) outranked the tenant's own real listing once treated as
   "a different platform found." Removed from the vendor-host list
   (never measured to begin with -- see the code comment in both
   `derive_hop_weights.py` and `wo147_access_ladder_sweep.py`). A
   related, NOT fixed in this diff, gap was found in the same
   investigation and filed to `BACKLOG.md` instead (see below).

## The measurement (the deliverable)

180 real saved government homepages (WO-267, fetched 2026-09-11-12), old
scorer (`legacy=True`, WO-228's word-list scorer) vs. new scorer
(WO-274's measured-weight scorer), both capped at 8 candidates.

### Table 1: old vs new scorer, top 8, counts of 180

| Result | Old (word list) | New (measured weights) | Denominator |
|---|---|---|---|
| Known hub URL in top 8 | 29 | 24 | of 73 homepages with a recorded hub URL |
| Known meeting URL in top 8 | 12 | 7 | of 127 homepages with a recorded meeting URL |
| Vendor-host or named first-party path link in top 8 | 95 | 123 | of 180 |

**The third row is the one that matters most for Ryan's actual goal**
(find a real meeting/video link, not necessarily reproduce the exact
URL string already on file): the new scorer finds a vendor-host or
named-path link on strictly MORE homepages than the old one, and never
fewer -- every one of the old scorer's 95 hits is also a new-scorer hit,
plus 28 more the old scorer missed. Zero regressions on this measure.

**The first two rows look like a regression and mostly aren't one.**
Inspecting every case where the old scorer matched the recorded URL and
the new one didn't (8 hub cases, 7 meeting cases) found:

- **All 8 hub "misses"** are the OLD scorer matching a recorded hub URL
  that is itself not a real meeting hub: a city commission's roster page
  ("Council-Members"), a "how local government works" explainer
  ("council_manager_form_of_government"), a job-openings page for board
  vacancies, an assessor's annual PDF calendar, an FAQ page, a specific
  city sub-commission's own page (not the general hub), a CivicAlerts
  press release, and one government (Lincoln, RI) whose recorded "hub"
  is literally just its bare homepage URL. None of these is a page a
  scorer *should* be chasing -- the new scorer correctly doesn't reach
  them.
- **6 of the 7 meeting "misses"** are governments whose recorded
  `example_meeting_url` is literally the bare root of a SuiteOne tenant
  domain (e.g. `https://camaswa.suiteonemedia.com/`) -- a known,
  documented WO-267 shortcut (`docs/investigations/platform_fingerprints.md`:
  "these supplemental fetches used the PLATFORM's own URL as both home
  and hub... finding each tenant's own separate civic homepage domain
  wasn't done"), not a real specific meeting page. The old scorer's
  "hit" on these is a coincidence: a same-page `#fragment` anchor link
  (which the old scorer doesn't filter out, and the new scorer correctly
  does) happens to normalize to the same bare domain.
- **1 of the 7** (Eustis FL) is the real `meetings.municode.com`
  regression described above, now partly mitigated (the bad candidate is
  gone) but the underlying `municode.com` marketing-apex gap is still
  open -- filed to `BACKLOG.md` rather than fixed in this diff, since
  the fix touches a constant shared by the legacy scorer this WO needs
  to keep byte-identical for its own comparison.

**Read together: neither drop reflects the new scorer performing worse
at the real job.** It reflects (a) the new scorer correctly not chasing
several genuinely wrong recorded ground-truth URLs, and (b) one open,
filed, narrow gap.

### Ceiling (any link on the page at all, not just the top 8), of 180

| What | Count |
|---|---|
| Homepages linking a meeting-vendor host or named first-party path directly, anywhere on the page | 146 |
| Homepages linking the recorded hub URL exactly, anywhere on the page | 34 (of 73 with a recorded hub) |

This is the honest ceiling: even a perfect scorer with an 8-link cap
cannot exceed 146 on the vendor/named-path measure, since only 146 of
180 homepages carry such a link at all. The new scorer's 123 top-8 hits
is 84% of that ceiling.

### Table 2: video straight from the homepage, of 180

| What | Count |
|---|---|
| Homepages with a `detect_platform()`-accepted link anywhere on the page | 127 |
| Of those, the MEETING-vocabulary-only scorer ranks that link's own URL #1 on the page | 54 |

127 of 180 (71%) of these positive-sample homepages link straight to a
real, resolver-recognized meeting/video URL without needing a second
hop at all. The meeting-vocabulary scorer (vendor-shape tokens only, no
hub words) picks that exact link first on 54 of those 127 (43%) --
meaning on the other 57%, a real video link exists on the page but
something else (a nav link, a different vendor-shaped link, a
generic-looking anchor) currently outscores it. Not chased further in
this WO; a real, worthwhile follow-up filed to `BACKLOG.md` would be
combining the hub-scorer and meeting-scorer passes into one ranked list
rather than two separate rankings.

## What this sample cannot show

The 180-homepage sample is every homepage WO-267 fetched *because* the
government was already known to have a working platform
(`transcribed=true`) -- it is biased toward governments whose site
already, in fact, links a platform somewhere. It cannot say how the new
scorer performs on a government with NO known platform at all (the
29,952-row unknown-platform population this whole access-ladder sweep
exists to work through) -- that would need a fresh, separate sample of
unknown-platform governments where a human independently confirms
whether a real platform link exists on the homepage, which is out of
scope for this WO.

## Files

- `scripts/derive_hop_weights.py` -- re-derive the tables above (no
  network fetches).
- `scripts/wo274_measure_hop_scorer.py` -- reproduce the before/after
  measurement above.
- `app/utils/jurisdiction_data/hop_link_weights.csv` -- the weight data
  `find_hop_links()`'s default scorer reads at import time.
- `scripts/wo147_access_ladder_sweep.py` -- `find_hop_links(html, url)`
  now uses the measured scorer by default; `legacy=True` gets the old
  WO-228 word-list scorer back verbatim.
- `tests/test_hop_scorer_weighted.py` -- new scorer's own tests
  (including both real regressions above as explicit regression tests).
- `tests/test_hub_link_ranking.py` -- unchanged behavior, now pinned to
  `legacy=True` explicitly (see its own WO-274 note) as the historical
  WO-228 record.
