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

## WO-292 addendum: a second, school-specific vocabulary (2026-09-12)

This WO's own table above was measured on city/county homepage links
only -- see "What this sample cannot show." School board sites carry a
real, different vocabulary (`board`, `boe`, `simbli`, `boarddocs`,
`superintendent`, `livestream`), so WO-292 (the school-district pilot)
measured a second table the same way, rather than assuming the
city/county weights transfer.

**Positives**: every YouTube/Vimeo channel link found on the homepages
of 417 school districts already known (`jurisdiction_coverage.csv`'s
`suspected_video_provider`) to run one, plus the Archive's own 6
existing `us:sd:` page source URLs. **Homepages fetched**: 337 of 417
(80.8%) -- the rest were `blocked-plain-http` (mostly connection
timeouts) or one `blocked-browser-headers`; the vocabulary is built only
from the 337 that resolved, 35,348 outbound links recorded.
**Negatives**: every other outbound link on those same 337 homepages
(for the anchor-text tables), plus `derive_hop_weights.py`'s own
existing "any ordinary link" pool where available (for the path/vendor
tables). No network fetches happened past this one homepage pass --
`scripts/wo292_derive_school_hop_weights.py` (the measurement script)
and `scripts/wo292_fetch_vocab_homepages.py` (the fetch) are both
read-only against public pages, same politeness rules as WO-274's own
`derive_hop_weights.py`.

Output: `app/utils/jurisdiction_data/hop_link_weights_school.csv`, same
5-column shape (`vocabulary,token_or_bigram,kind,positives,negatives,
lift,weight`) so `_load_hop_weights()` reads it unchanged. Strongest
measured signal, path tokens:

| Vocabulary | Token | Positives | Negatives | Weight |
|---|---|---|---|---|
| school_hub_vendor | goto | 7 | 0 | 7.0 |
| school_hub_vendor | nsf | 21 | 2 | 7.0 |
| school_meeting_vendor | clip | 32 | 0 | 7.0 |
| school_meeting_vendor | mediaplayer | 12 | 0 | 7.0 |
| school_meeting_vendor | channel | 73 | 19 | 5.944 |
| school_hub_vendor | organization | 7 | 27 | 5.512 |

Strongest measured signal, anchor text:

| Vocabulary | Word | Positives | Negatives | Weight |
|---|---|---|---|---|
| school_channel_anchor_text | youtube | 84 | 11 | 7.0 |
| school_hub_anchor_text | regulation | 5 | 2 | 6.832 |
| school_hub_anchor_text | boarddocs | 6 | 4 | 6.411 |
| school_channel_anchor_text | channel | 20 | 5 | 6.381 |
| school_hub_anchor_text | agenda | 7 | 49 | 4.156 |

`_weights_for_gov(gov_id)` in `wo147_access_ladder_sweep.py` (added by
the WO-292 step-0 agent) ADDS this table to the default city/county one
for a `us:sd:` row -- per-token, the higher of the two measured weights
wins -- rather than replacing it, since a school site still carries real
city/county-style hub words too (agendas, minutes, meetings). A
non-`us:sd:` row is unaffected.

**What this sample cannot show**: same caution as the parent table --
337 homepages, all from districts ALREADY known to run a YouTube/Vimeo
channel, so this table says nothing about vocabulary lift on a district
with no known platform yet (exactly the population WO-292's own 1,000-
district pilot sweeps). See `research/wo292_report.csv`/the WO-292
`BACKLOG_DONE.md` entry for how the pilot's phase 2/3 scoring performed
using this table.

Files added: `scripts/wo292_fetch_vocab_homepages.py`,
`scripts/wo292_derive_school_hop_weights.py`,
`app/utils/jurisdiction_data/hop_link_weights_school.csv`.

## WO-327 addendum: a French vocabulary for Quebec (2026-09-13)

### Why

WO-323 (2026-09-12, ENUMERATION_METHODS §332) ran passive discovery v2
on 247 never-swept Canadian governments and confirmed 0 of 92 Quebec
sites, while Ontario came back 27 of 56 and Alberta 9 of 16. Real Quebec
homepages carry live "Conseil municipal", "Séances du conseil", "Ordre
du jour", "Procès-verbaux", "Webdiffusion" navigation -- but
`find_hop_links()`'s vocabulary (`hop_link_weights.csv`) is English-only
and scores none of it.

### The catch, and the method

`jurisdiction_coverage.csv` holds 1,288 Quebec rows and ZERO with
`transcribed=true`, so WO-274's method (pull a positive set from
already-transcribed governments' recorded hub/meeting URLs) has no
French positives to pull. This WO built the positive set by hand
instead: every one of WO-323's 92 saved Quebec homepages
(`~/Documents/rtr-business/research/wo323_recon.jsonl`, already
fetched, no new network calls for this step) was scored against real
French council-vocabulary phrases and the printed top candidate read by
hand for every row (`scripts/wo327_hand_label_quebec_hubs.py`) --
70 of 92 produced a real hub link, 3 fetched with no qualifying link, 19
were unreachable (SSL certificate failures / 403s -- an access problem,
not a content one). Two real false positives were caught and fixed
during the hand-read: Terrebonne's "Figurants pour photos et vidéos"
(a casting call for a promotional shoot, not a meeting) and Albanel's
"CONSEIL" nav link, which actually resolves to a councillor-roster/bio
page, not a session page -- the same distinction this doc's own Table 1
draws for an English "Council-Members" roster page.

One more polite hop past each of the 70 hub URLs
(`scripts/wo327_fetch_quebec_hub_links.py`, plain HTTP, honest headers,
2s apart, never fetching youtube.com/youtu.be) found only 2 real
archived meeting videos (Mirabel and Canton de Hatley, both Vimeo) plus
one live Microsoft Teams meeting-join link (Saint-Jacques-le-Mineur --
a recurring live link, not an archived meeting, not counted) and 25
YouTube channel/video leads, recorded to `research/youtube_channel_
leads.csv` with `verified=false` per CLAUDE.md's "YouTube is a drip
lead" rule, never fetched. 2 real meeting URLs is far short of this
WO's own >= 15 floor for building a separate `meeting_firstparty_fr`
vocabulary, so that vocabulary was not built -- see
`scripts/derive_hop_weights_fr.py`'s module docstring.

### Hand-label result, of the 92 Quebec homepages

| Result | Count of 92 | What it means |
|---|---|---|
| Hub link found and confirmed by hand | 70 | Real council-session/minutes/webcast page identified |
| Homepage fetched, no qualifying link found | 3 | Site has no visible meeting/session navigation |
| Homepage unreachable | 19 | SSL certificate failure or HTTP 403 -- access problem |

### Measured vocabulary (the deliverable)

Positives: the 70 hand-confirmed hub URLs. Negatives: every other
outbound link on the same 92 homepages (5,755 ordinary links). Same
method as WO-274's `derive_hop_weights.py` (log-lift, +0.5 smoothing,
capped at +/-7.0), but with a much smaller support floor (3 positive
occurrences, not 10) since the whole positive sample is 70 URLs, not
956 -- `scripts/derive_hop_weights_fr.py`'s own comment states this
explicitly as a real, deliberate scale difference, not an oversight.

**Top path tokens, `hub_firstparty_fr`:**

| Token | Lift | Positives/Negatives | Weight |
|---|---|---|---|
| diffusion | 105.0x | 4/3 | 4.65 |
| seances | 104.2x | 41/32 | 4.65 |
| proces | 27.2x | 20/61 | 3.30 |
| verbaux | 27.2x | 20/61 | 3.30 |
| conseil | 23.7x | 38/132 | 3.17 |
| democratique | 12.0x | 4/30 | 2.49 |
| municipal | 6.4x | 10/133 | 1.86 |
| calendrier | 6.3x | 9/123 | 1.84 |

**Top bigrams:**

| Bigram | Lift | Positives/Negatives | Weight |
|---|---|---|---|
| ville-seances | 571.5x | 3/0 | 6.35 |
| democratique-seances | 190.5x | 3/1 | 5.25 |
| seances-conseil | 154.8x | 27/14 | 5.04 |
| diffusion-des | 114.3x | 3/2 | 4.74 |
| des-seances | 95.8x | 13/11 | 4.56 |
| proces-verbaux | 27.2x | 20/61 | 3.30 |
| conseil-municipal | 12.3x | 10/69 | 2.51 |

**Top anchor-text words** (accents stripped, see below):

| Word | Lift | Positives/Negatives | Weight |
|---|---|---|---|
| diffusion | 145.3x | 3/1 | 4.98 |
| seances | 106.2x | 43/25 | 4.67 |
| proces | 29.5x | 22/47 | 3.38 |
| conseil | 26.7x | 40/94 | 3.28 |
| calendrier | 10.9x | 12/71 | 2.39 |
| ordre | 8.9x | 3/24 | 2.19 |

Notably, "webdiffusion" never clears the support floor as its own
token -- real Quebec homepages overwhelmingly write it as two
tokenizable words ("Diffusion des séances", `/diffusion-des-seances`),
not the single compound the brief's own prose used. The measured
vocabulary reflects what real pages actually contain, not the
assumption.

Output: `app/utils/jurisdiction_data/hop_link_weights_fr.csv`, 43 rows,
same 5-column shape (`vocabulary,token_or_bigram,kind,positives,
negatives,lift,weight`) `_load_hop_weights()` already reads.

### Accent handling

Two real, confirmed data-quality issues had to be handled before the
table above was trustworthy:

1. **Mojibake.** 2 of the 92 pages' anchor text decoded as
   "SÃ©ances"/"SÃ©ance" instead of "Séances"/"Séance" -- real UTF-8
   bytes for an accented character, misread one byte at a time as
   Latin-1. Left unfixed, tokenizing "SÃ©ances" manufactures two fake
   tokens ("sa", "ances") purely from the encoding artifact, and "ances"
   cleared the support floor on that noise alone. Fixed with a
   round-trip repair (`s.encode("latin1").decode("utf-8")`,
   `derive_hop_weights_fr.fix_mojibake()`), applied before tokenizing.
2. **Real accents.** Anchor text is genuinely accented ("Séances",
   "Procès-verbaux"); URL paths are not (Quebec sites overwhelmingly use
   unaccented, hyphenated path segments -- confirmed against all 70 real
   hub URLs). Anchor tokens are NFD-normalized and stripped of combining
   marks before matching. A side-by-side comparison of stripped vs.
   accent-kept lift on the same sample (printed by
   `derive_hop_weights_fr.py`, "Accent handling comparison") shows every
   accented variant matching its stripped form's lift closely or falling
   below the support floor on its own spelling variant -- stripping
   pools real signal that would otherwise split across spelling variants
   (WordPress vs. custom-CMS templates spell "séance"/"seance"
   differently on real pages in this sample). **Decision: ship the
   accent-stripped vocabulary only** -- no accented form is kept
   separately in the output CSV.

### Language rule: when does a `ca:` row get the French vocabulary?

`looks_french(html_text)` in `wo147_access_ladder_sweep.py`: the page's
own `<html lang>` attribute when present, else a French/English
function-word density comparison on the first 20KB. Three candidate
rules were measured against the SAME 73 fetched Quebec + 52 fetched
Ontario real homepages from WO-323's recon (both populations already on
disk, no new fetches needed for this measurement):

| Rule | QC correctly detected French | ON correctly NOT detected French |
|---|---|---|
| `<html lang>` alone (61 of 73 QC pages had one at all) | 57 of 61 | 52 of 52 |
| Function-word density alone | 62 of 73 | 51 of 52 |
| **Shipped: `<html lang>` if present, else density** | **65 of 73** | **52 of 52** |

The shipped rule is the only one of the three with ZERO Ontario false
positives while also covering the most real Quebec pages. Of the 8
Quebec pages the shipped rule still misses, most are genuinely
defensible: Stanbridge East and Nemaska are real anglophone Quebec
municipalities whose homepages are, in fact, primarily English (not a
miss at all), and 2 (`piopolis.quebec`, `val-racine.com`) have a
`<html lang="en">` attribute that is simply wrong on a page that is
otherwise overwhelmingly French by word count -- a `<html lang>` value
can itself be stale/wrong on a real site, which is exactly why the
density check exists as a fallback rather than the sole rule; it was
not widened to override a present-but-wrong `lang` attribute in this
pass, since doing so cost 1 real Ontario false positive
(`townshipofmorley.ca`, a bilingual page) when tested. **No Ontario
regression on either the 92-homepage Quebec population's own English
control rows or on the separate 52-homepage Ontario population** -- see
`tests/test_hop_scorer_french.py` for the pinned regression tests
(`test_ontario_homepage_scoring_is_byte_identical_with_and_without_
gov_id`, checked against all 52 real Ontario homepages while building
this WO, not just the one committed fixture).

### Wiring

`_weights_for_gov(gov_id, *, html_text="")` in
`wo147_access_ladder_sweep.py` now merges in the French table when
`gov_id` starts `ca:` AND `looks_french(html_text)` is true -- same
per-token "higher of the two measured weights wins" rule the WO-292
school-vocabulary merge already uses, so a Quebec homepage still gets
credit for any English/named-platform tokens too (AgendaCenter, php,
index). A non-`ca:` row, or a `ca:` row whose page is not detected
French, is completely unaffected -- `find_hop_links()`'s existing
`gov_id` keyword parameter already threads through; only the new
`html_text` keyword on `_score_hop_candidate_weighted()`/
`_weights_for_gov()` is new plumbing. The English weights file itself
was not touched.

### Real example: before vs. after, on real saved pages

| Government | Old top candidate (no French vocab) | New top candidate (French vocab) |
|---|---|---|
| Mirabel, QC | YouTube channel link | `mirabel.ca/seances-conseil` (real council-session hub) |
| Saint-Georges, QC | YouTube channel link | `saint-georges.ca/.../calendrier-des-seances-du-conseil-municipal` |
| Saint-Calixte, QC | A youtu.be link | `saint-calixte.ca/municipalite/mairie/seances-du-conseil` |

### Before/after on the 92 Quebec rows: reclassification (offline, no network)

Re-running phase 2 (`scripts/wo327_rerun_quebec_phases.py`, a French-
aware, gov_id-passing rewrite of `wo323_classify.py`'s own
`homepage_candidates()` -- see `BACKLOG.md`'s new entry: neither
`wo323_classify.py` nor `wo324_classify.py` ever passed `gov_id` into
`find_hop_links()` at all, so this rewrite was required just to exercise
the vocabulary, not optional) on the same 92 recon rows:

| Result | Count of 92 | What it means |
|---|---|---|
| Top-ranked homepage candidate changed | 50 | The French vocabulary picked a materially different (and, hand-checked, better) link |
| Top-ranked candidate unchanged | 42 | Same link either way (mostly: a known vendor platform was already found by DNS/URL-shape, independent of hop-link scoring) |

Of the 50 changed rows, the OLD top-1 candidate was overwhelmingly noise
that happened to outrank everything under English-only scoring: a room-
rental page, a bizpal permit portal, a Twitter share link, an
`etatcivil.gouv.qc.ca` government-of-Quebec vital-records page, and a
YouTube channel link (which is real signal, just not as directly useful
as the government's own session-hub page) -- see the full list in
`research/wo327_qc323_reclassified.csv` vs. WO-323's own committed
`research/wo323_classified.csv`.

### A second real bug found and excluded, not by this WO's own testing but flagged by the conductor mid-run

WO-324's separate 258-row Quebec population measured 66-70 false
PrimeGov "confirmations": `wo273_recon.py`'s DNS tenant-guess took the
SECOND-TO-LAST label of a domain as a guessed vendor subdomain -- for
any `*.qc.ca` government that label is literally "qc", and
`qc.primegov.com` genuinely resolves (to PrimeGov's own regional
"OneMeeting Quebec" landing page, not any tenant). This WO's own 92-row
rerun hit the identical bug independently (23 of 92 rows) before the
conductor's message arrived. WO-328 (merged to `main`, #1111) fixed
`registrable_label()` upstream; this WO's rerun used a hand-exclusion
first (never trust a `qc.primegov.com` hit as evidence) and then, once
WO-328 landed, re-queried DNS for the affected domains with the FIXED
label (`scripts/wo327_refix_qc_primegov.py`) -- see the report for
which of the 23 domains had a DIFFERENT real vendor host once queried
with the correct label instead of just having the false one removed.

### Rerun results (phases 2-3, live)

See the WO-327 `BACKLOG_DONE.md` entry for the final funnel tables (hub-
scorer rerun on WO-323's 92 rows, WO-324's 258 `deferred-french-vocab`
rows, and the qc.primegov.com refix) -- kept there rather than
duplicated here, per this repo's own rule that a `BACKLOG_DONE.md` entry
carries the numbers a builder needs and this doc carries the
measurement method and reasoning behind them.

### Files

- `scripts/wo327_hand_label_quebec_hubs.py` -- hand-label the hub link
  on WO-323's 92 saved Quebec homepages (no network calls).
- `scripts/wo327_fetch_quebec_hub_links.py` -- one polite hop past each
  hand-labelled hub, looking for a real meeting/video link.
- `scripts/derive_hop_weights_fr.py` -- derive the French vocabulary
  from the hand labels (no network calls).
- `app/utils/jurisdiction_data/hop_link_weights_fr.csv` -- the shipped
  weight data.
- `scripts/wo147_access_ladder_sweep.py` -- `looks_french()`,
  `_weights_for_gov()`'s French branch.
- `scripts/wo327_rerun_quebec_phases.py` -- French-aware, gov_id-passing
  rerun of phases 2-3 for a Quebec recon population.
- `scripts/wo327_refix_qc_primegov.py` -- re-derive the DNS vendor-label
  guess for rows the qc.primegov.com bug hit, using WO-328's fix.
- `tests/test_hop_scorer_french.py` -- real-fixture tests (Mirabel,
  Saint-Georges, Adelaide-Metcalfe ON).
