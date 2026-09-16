# WO-333: a shared verification step that walks a confirmed hub to a real meeting (2026-09-13)

## Why

WO-331 (2026-09-13) ran 26 governments already known to have real,
live, captioned video through the exact `wo3NN_resolve_diagnostic.py`
pipeline the WO-320-327 sweeps use, to check whether that pipeline can
still find video it already knows exists. Of the 15 governments where
phase 3 confirmed a real platform link, the sweep's own unmodified
`resolve()` call found video on only 1. This WO builds the fix: one
shared step (`app/platforms/passive_verify.py`'s `verify_hub()`),
importable by every `wo3NN_resolve_diagnostic.py`-style sweep script,
that walks from a confirmed hub URL to a specific, real meeting and
reports three separable facts -- `meeting_found`, `video_found`,
`captions_found` -- plus a `tier` (Ryan's vocabulary, 2026-09-13; see
below).

## Three root causes, all confirmed live

1. **A hub/listing URL is not one specific meeting.** `resolve()` on a
   CivicPlus AgendaCenter, a Granicus agenda-feed link, an eScribe
   "Published Meetings" root, etc. can return completely empty (no
   video, no title, no agenda items) even though the page genuinely
   lists real meetings -- most adapters were only ever built to resolve
   one already-known meeting URL, not to walk a listing.
2. **A government using an "aggregator" platform (CivicPlus, CivicWeb,
   Legistar, PrimeGov, Municode Meetings, Chicago ELMS) for its agendas
   often uses a completely different real video vendor for its actual
   video**, linked or embedded on the same page. The aggregator gets
   confirmed and video-checked; the real vendor link is never reached.
3. **The old pipeline's own "unsupported"/"no candidate" verdicts hide a
   real listing.** WO-331's handcheck classified `detect_platform() ->
   unknown` as `UNSUPPORTED` and gave up, even when the confirmed page
   plainly embeds a known platform's widget (an iQM2 citizen portal, an
   eScribe API call, a ChampDS player) that a real HTML scan finds in one
   more fetch.

## The fix: `verify_hub(hub_url, platform_hint=None)`

`app/platforms/passive_verify.py`. Given a hub URL (and, when known, the
platform phase 3 guessed), it:

1. **Never fetches a youtube.com/youtu.be URL.** A YouTube embed found
   anywhere along the walk -- as the hub itself, a listing candidate, or
   an adapter's own internal delegation -- is recorded as a
   `youtube_lead` verdict (tier 2) and never actually fetched. Two real,
   DIFFERENT chokepoints had to be patched to make this hold, both found
   live during this WO's own test run (see "A real safety bug, caught
   live" below).
2. If the hub URL isn't itself a recognized platform URL, fetches it
   once and uses `find_platform_link()` (already existing) to find a
   real embedded/linked platform -- fixing root cause #3.
3. Calls that platform's `resolve()`. On `CalendarPageError`, walks the
   real candidate pick-list newest-first (fixing root cause #1 for every
   platform that already raises it: CivicPlus, CivicLive, Legistar,
   Municode Meetings, Vimeo, Wistia, Tampa, AZ Legislature). On a
   resolve() that comes back completely empty, or a platform-specific
   listing walker exists (Granicus's real video-mode RSS feed; ChampDS's
   search API; CivicWeb's `MeetingTypeList.aspx` + `/api/videolink/`;
   Legistar's public `webapi.legistar.com`), walks that instead -- also
   fixing root cause #1 for platforms with no `CalendarPageError`.
4. **Ranking fix** (root cause #2): when the platform reached is a known
   aggregator and it found no video, separately checks the SAME hub page
   for a real, non-aggregator video-vendor link and prefers it.
5. **First-party agenda page fix** (a second loss point found by Breadth/
   WO-332 the same day, from the ladder side: 10 of 10 registry-sampled
   "no-meeting-nor-video" rows checked by hand were wrong, 8 of 10
   because the access ladder's own success test is "a vendor platform
   link", so a first-party "Agendas & Minutes" page is invisible to it).
   When no vendor link is found anywhere, tries a short list of
   guessable first-party agenda paths (`/agendacenter`, `/AgendaCenter`,
   `/agendas-minutes`, ...) on the same host; a real page found this way
   is credited as `meeting_found=True` (tier 4), never "no meeting" --
   and if its own markup is recognizably CivicPlus (white-labeled
   tenants never redirect to a `*.civicplus.com` host, so
   `detect_platform()` alone can't tell), delegates into the real
   CivicPlus walk instead of stopping at "unknown platform."

### Verdict vocabulary / tier mapping

`meeting_found` is real only once real listing rows or a real resolved
page were actually seen. `video_found`/`captions_found` are only true
once a specific meeting's own `resolve()` returned a real `video_url`/
`segments`. `VerifyResult.tier` (a derived property) maps onto Ryan's
vocabulary (2026-09-13): tier 1 = video + captions this app can fetch
itself; tier 2 = video whose captions are YouTube's (a lead, never
fetched here); tier 3 = video, no captions we can fetch (a tier-3 queue
candidate); tier 4 = meeting found, no video; `None` (a separate "no
meeting found" outcome) when the hub lists nothing at all.

## A real safety bug, caught live during this WO's own verification run

Running `verify_hub()` against WO-331's own 15 confirmed controls
(before any fix) surfaced a genuine "never fetch YouTube" violation:
Crest Hill, IL (Municode Meetings) and, after the Legistar listing
walker was added, Ann Arbor, MI (a2gov.org, Legistar) both resulted in a
**real yt-dlp fetch actually happening** -- 1,859 real caption segments
pulled from `https://www.youtube.com/embed/lUBYUBtMOJw` for a2gov's City
Council meeting. Root cause: `legistar.py` (and, per CLAUDE.md, also
`primegov.py`) don't delegate to YouTube via `YouTubeAssetFinder.
resolve()` -- the path an earlier version of this module's guard
patched -- they call `YouTubeAssetFinder.resolve_video_id(video_id,
source_url)` **directly**, a different method entirely, specifically so
they can pass the delegating page's own `source_url` through. The fix
(`_youtube_resolve_guard()`) now patches both `YouTubeAssetFinder.
resolve` and `YouTubeAssetFinder.resolve_video_id`, scoped to the
duration of one `verify_hub()` call (restored afterward, so a legitimate
caller elsewhere -- the YouTube drip -- is unaffected). Regression tests
for both chokepoints are in `tests/test_passive_verify.py`
(`test_internal_youtube_delegation_is_a_lead_never_fetched` and
`test_internal_youtube_delegation_via_resolve_video_id_is_a_lead`).
Re-verified live after the fix: the identical a2gov walk now stops at
`BLOCKED (correctly guarded): https://www.youtube.com/watch?v=lUBYUBtMOJw`
with zero real segments returned.

## Results on WO-331's 15 phase-3-confirmed controls

| Government | Platform reached | Before (WO-331, unaided) | After (this WO) | Tier |
|---|---|---|---|---|
| a2gov.org | legistar -> youtube | RESOLVED, no video | youtube_lead | 2 |
| ci.forest-lake.mn.us | iqm2 -> youtube | CALENDAR_PAGE | youtube_lead | 2 |
| cresthill.gov | municode_meetings -> youtube | UNSUPPORTED | youtube_lead | 2 |
| franklinnh.gov | civicplus -> vimeo | RESOLVE_FAILED | calendar_page, video+captions | 1 |
| knoxvilletn.gov | iqm2 | UNSUPPORTED | resolved_empty, no meeting | -- |
| maurycounty-tn.gov | champds | UNSUPPORTED | listing walk, video | 3 |
| monroecounty-fl.gov | civicplus | RESOLVE_FAILED (checked 0) | empty_listing, no meeting | -- |
| plymouthmi.gov | civiclive | RESOLVED, video+captions | resolved, video+captions | 1 |
| pwcva.gov | granicus | UNSUPPORTED | listing walk, video | 3 |
| qac.gov | telvue | CALENDAR_PAGE | calendar_page, video+captions | 1 |
| troy-nh.us | townhallstreams | RESOLVED, no video | resolved_empty, no meeting | -- |
| victoria.ca | escribe | UNSUPPORTED | resolved, no video | 4 |
| webbcountytx.gov | civicplus | RESOLVE_FAILED (checked 0) | empty_listing, no meeting | -- |
| www.co.jefferson.wa.us | civicplus | RESOLVE_FAILED (checked 5) | no_video_in_listing | 4 |
| www.niagarafalls.ca | civicweb -> youtube | UNSUPPORTED | listing walk -> youtube_lead | 2 |

**Unaided video found: 1 of 15 (before) -> 9 of 15 (after).**

## Platforms now fully programmatic hub -> tier (no hand step beyond the standard hand-read-before-ingest gate)

CivicPlus (raised retry limit), TelVue, CivicLive (unmodified, already
worked), ChampDS, Granicus (new listing walker), Legistar (new listing
walker), iQM2 (at least this shape), Municode Meetings, CivicWeb (new
listing walker) -- each reached a real tier 1/2/3 verdict on its own
control government with zero manual intervention.

## Platforms that still need a hand step (this WO's own remaining gap)

- **iQM2**, a different tenant shape (Knoxville, TN) -- `resolved_empty`,
  no listing walker match; the confirmed page has no meeting id the
  generic scan or a bespoke walker could find yet.
- **CivicPlus, wrong starting URL** (Monroe County FL, Webb County TX) --
  phase 3's own confirmed URL wasn't a real AgendaCenter listing at all
  (a `/Boards-Committees` page, a `/Pay` page); `_probe_first_party_
  agenda_pages()` tries a canonical `/AgendaCenter` guess but Monroe
  County's own tenant 404s there, and Webb County's real listing needed
  a category parameter this WO didn't chase down.
- **CivicPlus, video one hop deeper** (Jefferson County WA) -- 15 real
  rows checked, genuinely no direct video link in any `td.media`; the
  real vendor (a direct file per WO-331) is reachable only by following
  an individual row's agenda/minutes document, not built this WO.
- **Town Hall Streams** (Troy, NH) -- no listing walker; `resolve()` on
  the confirmed town-hub URL returns empty.
- **eScribe** (Victoria, BC) -- `resolve()` finds a real page (title
  "eSCRIBE Published Meetings") but no video; no listing walker built to
  drill into a specific committee's own meeting list.

These five are logged in `BACKLOG.md` as the residual, prioritized by
the row counts in WO-331's own report (`ENUMERATION_METHODS.md` §337).

## No-regression check

20 real meeting URLs previously confirmed (independently of this WO) to
have no video -- 10 Cablecast, 10 PrimeGov, from `research/
cablecast_confirmed_no_video.txt` / `research/
primegov_confirmed_no_video.txt` -- rerun through `verify_hub()`. 18 of
20 stayed `video_found=False`. The 2 that flipped (both Cablecast:
`champaign.cablecast.tv/show/5943`, `fargo.cablecast.tv/show/13514`)
were checked against the real, UNMODIFIED `CablecastAssetFinder.
resolve()` directly (no `passive_verify` code involved at all) and
confirmed to independently find the same real video -- the source
content changed since that list was compiled, not a regression this WO
introduced.

## Prior art (found partway through this WO, credited here)

`~/Documents/rtr-business/research/meeting_url_finder.py` (from
ENUMERATION_METHODS.md's Step 2/Step 3 runs, §93/§142/§144) already had
real, validated per-tenant listing lookups for CivicClerk, CivicWeb and
Legistar, built and run at scale in an earlier wave of work on a
different population. This WO's `_civicweb_walker()` and
`_legistar_walker()` are direct ports of `find_civicweb_meeting()` and
`find_legistar_meeting()` from that file, credited in their own
docstrings -- found only after independently hitting the same CivicWeb
"no obvious listing endpoint" gap the hard way. `docs/
BREADTH_SWEEP_BRIEF.md`'s own "The method, in order" section separately
documents rtr-discovery's enumerator reading Granicus's `mode=videos`
feed before its agenda table -- the same real Granicus behavior this
WO's `granicus.py` `list_recent_video_meetings()` independently
confirmed and implemented for the resolver's own `app/platforms/`
pipeline (a different codebase from rtr-discovery, so not directly
importable, but the same underlying platform behavior).

A CivicClerk listing walker (`find_civicclerk_meeting()`'s own
`{tenant}.api.civicclerk.com/v1/Events` + `EventsMedia/{id}` pattern) is
not yet ported into `passive_verify.py` -- logged in `BACKLOG.md` as the
next platform to add (66 rows in WO-331's own row-count estimate).
