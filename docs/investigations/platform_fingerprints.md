# Platform fingerprints: measured signals beyond a vendor hostname (WO-267)

Written 2026-09-12. Read this before touching `scripts/platform_fingerprints.py`,
`app/utils/jurisdiction_data/platform_signatures.csv`, or before building
WO-268 (the passive one-fetch pass over domains with no known platform).

## Why

Platform discovery is a weak point: tens of thousands of government
domains in the research file have no known platform. The existing
ladder (`scripts/wo147_access_ladder_sweep.py`'s `_PLATFORM_ALIASES`,
and `app/platforms/base.py`'s `detect_platform()`) only recognizes a
platform when a vendor HOSTNAME appears on the fetched page. That
misses first-party embeds (CivicWeb's `Portal/MeetingInformation.aspx`,
IQM2's `/Citizens/`), site builders that predict a platform (CivicPlus,
Municode's meetings module), and narrower path shapes that are often
*more* reliable than the bare hostname once a page has already been
fetched.

This WO measured real candidate signals against a real sample, kept the
ones that clear a 90% hit / 5% false-positive bar, and shipped them as a
reusable matcher (`scripts/platform_fingerprints.py`) driven by a data
file (`app/utils/jurisdiction_data/platform_signatures.csv`) so WO-268
can use them without re-deriving anything. This file also records the
site-builder/CMS-family overlap with `scripts/cms_fingerprint.py`
(WO-154/WO-179) -- a related, already-built, already-measured piece
this WO reuses rather than duplicates.

## Method, and where it differs from the brief's numbers

The brief asked for "10 per platform" (stage 1, ~300 fetches) and 200 +
200 negative-set governments (stage 2, ~300-400 fetches). What was
actually run:

- **Stage 1 positives**: built from `jurisdiction_coverage.csv` rows
  with `transcribed=true` and a known platform
  (`suspected_meeting_link_provider`, falling back to
  `suspected_video_provider`), stratified to up to 10 governments per
  platform, fetching the government's own recorded `domain` (home) and
  its recorded `example_meeting_url` (hub) -- falling back to
  `example_agenda_or_calendar_url` when `example_meeting_url` turned out
  to be this app's own internal `/m/<slug>` permalink rather than an
  external page (a real data shape in the file: once a meeting is
  ingested, that column sometimes gets overwritten with our own
  resolved URL instead of the source one -- worth fixing at the source
  separately; filed below). **323 real fetches**, 171 distinct
  governments.
- **Platforms with fewer than 10 in the `transcribed=true` pool**:
  wistia (8), legistar/youtube (9/10 -- one candidate's pages failed to
  fetch), telvue (4 in the pool, 3 fetched), boarddocs (3), clerkbase
  (2), boxcast (2), champds/suiteone/municode/civiclive/aurora_tv/
  open_media/seattle_channel/invintus/destinyhosted/granicus.com/
  civicclerk.com/civicplus.com (0-1). For champds, suiteone, boxcast,
  townhallstreams and utah_pmn -- all legitimately real platforms this
  repo already has adapters for, just not represented at all or barely
  in the `transcribed=true` pool -- real, confirmed-live sample URLs were
  pulled directly from each adapter's own docstring instead (the same
  "test against a real URL first" sources the adapters themselves were
  built from): champds (Atlanta GA, `play.champds.com/atlantaga/event/
  1227`, n=1), suiteone (6 of its own confirmed tenants: Pacific Grove
  CA, Lorain OH, Tuscaloosa AL, Camas WA, Holladay UT, St Marys GA),
  boxcast (Atlantic City NJ's real `acnj.gov/pages/meeting-recordings`
  and Wilmington OH's real `boxcast.tv/channel/...` link, n=2 beyond the
  2 already in the CSV pool -> n=4), townhallstreams (3 of the real URLs
  already in `tests/test_townhallstreams.py`: Lisbon ME, Out of the Blue
  ME, New Boston NH), utah_pmn (2 of the real URLs in
  `tests/test_utah_pmn.py`: Alpine town and Grand County, UT). **These
  supplemental fetches used the PLATFORM's own URL as both "home" and
  "hub" for champds/suiteone/townhallstreams/utah_pmn** (time-boxed --
  finding each tenant's own separate civic homepage domain wasn't done)
  -- see "What this sample could not cover" below for what that means
  for reading their numbers. Boardocs and Simbli have no adapter in this
  repo (agenda-document platforms without a video path of their own, the
  same category as AgendaCenter) and were not sampled.
- **Stage 2 negatives**: 220 governments with a different known platform
  (home page only), 220 with no known platform (home page only, random
  from the 29,952-row unknown-platform pool) -- **~440 real fetches**,
  matching the brief's "~300-400" reasonably closely even though stage 1
  came in a bit under "~300" once internal-URL rows were filtered out.
- **Total: 768 real polite fetches** across both stages plus the
  supplemental platform samples, all via the same access ladder
  (`scripts/wo147_access_ladder_sweep.py`'s HONEST_HEADERS, then
  BROWSER_HEADERS only after a 403 or dropped connection, stopping at
  any `CHALLENGE_MARKERS` hit -- 2 plain Cloudflare "just a moment"
  challenges and 2 `sgcaptcha` challenges were hit and NOT retried past,
  per CLAUDE.md's standing decision). No headless fetching was used --
  see "the JS-drawn sample claim" below for why the brief's ask to
  compare against headless on 2-3 named JS-drawn samples could not be
  carried out as described.
- Every raw fetched page is saved under this session's private scratch
  directory, not the repo, per the WO's instructions -- only the
  trimmed, real fixtures under `tests/fixtures/platform_fingerprints/`
  and the measured signature table are committed.

## The single most important caveat: confirmation vs. discovery

A "first-party path" signal (Granicus `/player/clip/{id}`, CivicWeb
`Portal/MeetingInformation.aspx`, IQM2 `/Citizens/...`) was measured
against **the hub page**, which in this sample IS the platform URL the
research file already recorded for that government. Matching that URL's
own shape against itself is real confirmation value (once a candidate
URL is already found -- by the hop-link scorer, by a human, by a CDX
lead -- does its own shape agree it's genuinely that platform, rather
than a different one with a similar host) but it is **not** evidence
that the same signal can be found by blindly fetching an UNKNOWN
government's own homepage, which is exactly what WO-268 needs.

The table below reports three separate hit rates for this reason:
**any** (home or hub, whichever matched -- closest to the brief's literal
"hits of 10" ask), **home** (home page only, including a government
whose own recorded `domain` already IS the vendor tenant host -- common
for governments with no separate site of their own on file), and
**home, distinct domain** (home page only, restricted to governments
whose recorded domain is NOT itself the vendor host -- the real test of
"can a blind fetch of an unrelated site reveal this platform," with `n`
shown since it is often small or zero). Read the distinct-domain column
before trusting any "home" number as discovery evidence.

## Full measured signal table

`hit` = any-page hit rate (the brief's literal criterion). `home` = home
page hit rate including trivial same-host cases. `distinct n` = home
page hit rate restricted to a genuinely separate recorded domain, with
the sample size in parentheses (a blank dash means zero such
governments existed in this sample). `FP` = combined false-positive rate
against ~220 different-platform + ~220 unknown-platform governments.
**Kept** signals (hit >= 0.90 AND FP <= 0.05) are what
`platform_signatures.csv` ships; everything else is a lead, not
discarded data.

| Platform | Signal | Kind | Hit (of N) | Home | Distinct-domain home (n) | FP | Kept? |
|---|---|---|---|---|---|---|---|
| granicus | granicus-vendor-host | vendor_hostname | 1.000 (10) | 1.000 | 1.000 (1) | 0.038 | **yes** |
| granicus | granicus-player-clip-path | first_party_path | 0.900 (10) | 0.000 | 0.000 (1) | 0.000 | **yes** |
| granicus | granicus-viewpublisher | first_party_path | 0.000 (10) | 0.000 | -- (0) | 0.003 | no -- zero real hits; the classic ViewPublisher.php UI seems to have aged out of this sample entirely |
| granicus | granicus-mediaplayer | first_party_path | 0.000 (10) | 0.000 | -- (0) | 0.000 | no -- same as above |
| legistar | legistar-vendor-host | vendor_hostname | 0.889 (9) | 0.889 | -- (0) | 0.003 | no -- **1 hit short of the bar on a 9-government sample (8/9); a sample-size artifact, not a real deficiency. Recommend re-testing at n=10+ before discarding.** |
| legistar | legistar-calendar-path | first_party_path | 0.889 (9) | 0.889 | -- (0) | 0.152 | no -- FP far over bar: `Calendar.aspx` is a generic ASP.NET page name plenty of non-Legistar sites also use |
| legistar | legistar-meetingdetail-path | first_party_path | 0.333 (9) | 0.000 | -- (0) | 0.000 | no -- too rare; most hub URLs in this sample were `Calendar.aspx` listings, not single-meeting pages |
| civicclerk | civicclerk-vendor-host | vendor_hostname | 1.000 (10) | 0.900 | 0.667 (3) | 0.008 | **yes** |
| civicclerk | civicclerk-portal-host | first_party_path | 1.000 (10) | 0.800 | 0.333 (3) | 0.008 | **yes** |
| civicclerk | civicclerk-event-media-path | first_party_path | 0.900 (10) | 0.000 | 0.000 (3) | 0.000 | **yes** |
| civicweb | civicweb-vendor-host | vendor_hostname | 1.000 (10) | 1.000 | 1.000 (1) | 0.011 | **yes** |
| civicweb | civicweb-portal-meetinginfo-path | first_party_path | 0.900 (10) | 0.000 | 0.000 (1) | 0.000 | **yes** |
| iqm2 | iqm2-vendor-host | vendor_hostname | 0.900 (10) | 0.889 | 0.000 (1) | 0.003 | **yes** |
| iqm2 | iqm2-citizens-path | first_party_path | 0.900 (10) | 0.889 | 0.000 (1) | 0.003 | **yes** (brief-named path) |
| iqm2 | iqm2-splitview-path | first_party_path | 0.800 (10) | 0.111 | 0.000 (1) | 0.000 | no -- below hit bar |
| iqm2 | iqm2-detail-meeting-path | first_party_path | 0.900 (10) | 0.444 | 0.000 (1) | 0.000 | **yes** |
| escribe | escribe-vendor-host | vendor_hostname | 1.000 (10) | 1.000 | -- (0) | 0.000 | **yes** |
| escribe | escribe-meeting-agenda-path | first_party_path | 1.000 (10) | 0.000 | -- (0) | 0.000 | **yes** |
| escribe | escribe-pub-subdomain | first_party_path | 1.000 (10) | 1.000 | -- (0) | 0.000 | **yes** |
| primegov | primegov-vendor-host | vendor_hostname | 0.700 (10) | 0.500 | n/a | 0.000 | no -- see caution below: 3 of 10 "primegov" rows actually delegated to Granicus/YouTube |
| primegov | primegov-portal-meeting-path | first_party_path | 0.500 (10) | 0.000 | n/a | 0.000 | no |
| swagit | swagit-vendor-host | vendor_hostname | 1.000 (10) | 1.000 | -- (0) | 0.003 | **yes** |
| swagit | swagit-videos-path | first_party_path | 1.000 (10) | 0.000 | -- (0) | 0.000 | **yes** |
| cablecast | cablecast-vendor-host | vendor_hostname | 0.700 (10) | 0.700 | n/a | 0.000 | no -- 3 of 10 recorded rows didn't show cablecast.tv on either page; sample composition issue, see caution |
| cablecast | cablecast-show-path | first_party_path | 0.100 (10) | 0.000 | n/a | 0.000 | no |
| telvue | telvue-vendor-host | vendor_hostname | 1.000 (3) | 0.333 | 0.333 (3) | 0.003 | **yes** (n=3 only) |
| telvue | telvue-videoplayer-path | first_party_path | 1.000 (3) | 0.333 | 0.333 (3) | 0.003 | **yes** (n=3 only) |
| champds | champds-vendor-host | vendor_hostname | 1.000 (1) | -- | -- | 0.000 | **yes** (n=1 only -- see caveat) |
| champds | champds-event-path | first_party_path | 1.000 (1) | -- | -- | 0.000 | **yes** (n=1 only) |
| clerkbase | clerkbase-vendor-host | vendor_hostname | 1.000 (2) | 1.000 | -- (0) | 0.000 | **yes** (n=2 only) |
| municode_meetings | municode-meetings-vendor-host | vendor_hostname | 1.000 (10) | 0.900 | 0.500 (2) | 0.003 | **yes** |
| hyland | hyland-vendor-host | vendor_hostname | 0.100 (10) | 0.167 | 0.200 (5) | 0.000 | no -- **the central finding of this WO**: most real Hyland/OnBase tenants run on their own custom domain (`onbase.comptoncity.org`, `meetings.muni.org`), not `hylandcloud.com` -- the bare-hostname check `detect_platform()` relies on today misses 9 of 10 real tenants in this sample |
| hyland | hyland-agendaonline-path | first_party_path | 1.000 (10) | 0.167 | 0.200 (5) | 0.000 | **yes** -- the fix for the line above: the `AgendaOnline/Meetings/ViewMeeting` path shape catches all 10 regardless of hostname |
| wistia | wistia-vendor-host | vendor_hostname | 1.000 (8) | 0.000 | 0.000 (7) | 0.000 | **yes** (confirmation-only: 0 of 7 distinct-domain homepages show it -- see caution) |
| wistia | wistia-medias-path | first_party_path | 1.000 (8) | 0.000 | 0.000 (7) | 0.000 | **yes** (same caveat) |
| vimeo | vimeo-vendor-host | vendor_hostname | 0.700 (10) | 0.400 | n/a | 0.005 | no -- same delegation-dilution issue as PrimeGov/Cablecast |
| vimeo | vimeo-player-host | first_party_path | 0.300 (10) | 0.200 | n/a | 0.003 | no |
| boxcast | boxcast-vendor-host | vendor_hostname | 0.750 (4) | 0.750 | n/a | 0.000 | no -- close, but n=4 is too small and one real miss (the ProudCity `video_style=external` delegation case) keeps it under the bar |
| suiteone | suiteone-vendor-host | vendor_hostname | 1.000 (6) | 1.000 | -- (0) | 0.000 | **yes** (see caveat: "home" here is the platform's own tenant root, not a separate civic domain) |
| utah_pmn | utah-pmn-path | first_party_path | 1.000 (2) | 1.000 | 1.000 (2) | 0.003 | **yes** (n=2 only; genuinely distinct-domain by construction -- Utah PMN is never on the government's own site) |
| townhallstreams | townhallstreams-vendor-host | vendor_hostname | 1.000 (3) | 1.000 | -- (0) | 0.000 | **yes** (n=3 only; caveat as suiteone) |
| townhallstreams | townhallstreams-stream-path | first_party_path | 1.000 (3) | 1.000 | -- (0) | 0.000 | **yes** (same caveat) |
| youtube | youtube-iframe-embed | asset_or_embed | 0.111 (9) | 0.111 | 0.111 (9) | 0.026 | no -- a real `<iframe>` embed of a meeting video is rare on the literal homepage |
| youtube | youtube-watch-or-live-link | asset_or_embed | 0.778 (9) | 0.778 | 0.778 (9) | 0.173 | no -- **FP far over bar**: a bare YouTube channel/watch link on a homepage is common for reasons that have nothing to do with meetings (promotional videos, a school district's own channel, a parks department) |
| youtube | youtube-short-link | asset_or_embed | 0.000 (9) | 0.000 | 0.000 (9) | 0.026 | no |
| civicplus | civicplus-agendacenter-path | first_party_path | 0.900 (10) | 0.900 | 0.900 (10) | 0.074 | no -- close; see caution below, this is really a site-builder signal mislabeled as a platform signal |
| civicplus | civicplus-footer-badge | asset_or_embed | 0.000 (10) | 0.000 | 0.000 (10) | 0.008 | no -- the literal footer text isn't universal even on real AgendaCenter tenants (matches `cms_fingerprint.py`'s own finding) |

28 of 47 measured signals cleared the bar and are in
`app/utils/jurisdiction_data/platform_signatures.csv`.

## Cautions on specific platforms

- **PrimeGov, Vimeo, Cablecast all scored below the hit bar for the same
  underlying reason**: CLAUDE.md's own platform-wrapper rule says
  PrimeGov embeds a YouTube video and CivicPlus/Legistar delegate to
  Granicus -- the research file's `suspected_meeting_link_provider`
  label on a row doesn't always agree with what the row's own
  `example_meeting_url` actually resolves to once delegation happens.
  Concretely: 3 of this sample's 10 "primegov" rows had a Granicus or
  bare YouTube hub URL, not a `primegov.com` one. This is a real,
  confirmed labeling looseness in the research file, not a defect in
  the vendor hostname itself — re-deriving this signal from a sample
  filtered to rows where the label and the URL actually agree is worth
  doing before concluding PrimeGov's own hostname is unreliable.
- **Legistar's own vendor hostname missed the bar by one government in a
  9-row sample (8/9 = 88.9%)** -- almost certainly a small-sample
  rounding artifact rather than a real problem; worth a larger re-run
  before treating Legistar as a weak signal.
- **CivicPlus's `/AgendaCenter` path is conceptually a SITE-BUILDER
  signal, not a platform signal** -- it correctly identifies "this
  government's agenda site runs CivicPlus" on 90% of this sample, but
  since CivicPlus never hosts video itself (it always delegates to
  Granicus/YouTube/CivicClerk/PrimeGov -- see CLAUDE.md's
  platform-wrapper rule), testing it against a "different platform"
  negative set penalizes it for correctly firing on a CivicPlus site
  whose *video* happens to be hosted elsewhere. `scripts/
  cms_fingerprint.py` already carries this exact rule
  (`civicplus-path-shape`, `app/utils/jurisdiction_data/
  cms_families.csv`'s civicplus row) with its own, more appropriate
  `usual_video_platform` column rather than a false-positive rate
  against a single platform label. **Recommendation: treat
  `/AgendaCenter` as a site-builder signal (already shipped, in
  `cms_fingerprint.classify()`) with no separate platform-signature
  entry, rather than re-measuring it here against a criterion it was
  never the right fit for.**
- **Wistia's embed is real, but not on the literal homepage** -- 0 of 7
  distinct-domain homepages in this sample showed it, even though the
  signal is 100% reliable once you're looking at the right sub-page
  (typically a `/council` or `/agenda-center` page, not the bare
  domain root). A one-fetch pass of only the root homepage (WO-268's
  stated plan) will miss this platform's real first-party embeds
  entirely; it needs either a second hop to an agenda/council-shaped
  link (the hop-link scorer WO-228 already built) or it stays a
  confirmation-only signal.
- **champds, suiteone, boxcast, townhallstreams, utah_pmn all have a
  real but thin sample (1-6 governments)**, pulled from each adapter's
  own confirmed-live docstring rather than the research file (which had
  0-3 `transcribed=true` rows for any of them). For champds, suiteone
  and townhallstreams specifically, the "home" page fetched was the
  PLATFORM's own URL, not a separate government homepage -- there was
  no time in this pass to find each tenant's own civic domain, so their
  "home"/"distinct-domain" numbers above are not evidence of real
  first-party embedding and should not be read as such; treat their
  `keep=yes` status as "the vendor hostname reliably appears on the
  platform's own page" (already true by construction) rather than "this
  is discoverable from an unrelated government site."
- **BoardDocs and Simbli were not sampled at all** -- neither has an
  adapter in this repo (both are agenda-document platforms, the same
  category as AgendaCenter, without a video path of their own), and the
  research file has only 3 `boarddocs` rows total, none with a real
  BoardDocs URL (all 3 examples in the CSV were actually YouTube links
  found alongside a BoardDocs agenda page).

## The JS-drawn sample claim (corrected)

The brief named "2-3 known JS-drawn sites (Waldwick NJ EvoGov, Farmington
MO Duda, Davison MI)" to compare plain vs. headless fetching on. Checking
these against the live data before building anything against them (per
CLAUDE.md's "a brief claim is a lead, not a spec" rule) found none of the
three actually demonstrates a clean plain-fetch-misses/headless-finds
case:

- **Waldwick, NJ**: a plain fetch of `waldwicknj.gov` returns 200 with
  101KB of real HTML that already contains a `youtube` reference in the
  static markup -- not a page with no visible meeting link at all.
- **Davison city, MI**: already has a real CivicPlus link on file
  (`cityofdavisonmi.gov/Archive.aspx?AMID=60`, `reject_reason=
  meeting-without-video`) -- the platform link was already FOUND, not
  missing. This is not a "no platform link found" case either.
- **Farmington, MO**: genuinely unresolved, but differently than
  described -- `BACKLOG.md`'s existing `[HUMAN]` entry for this exact
  government says BOTH a plain fetch AND a real headless browser failed
  to reproduce the 16 agenda PDFs Ryan saw on `/city-council`, returning
  an identical 155,691-byte Duda page with no agenda text either way.
  That is not a plain-fails/headless-succeeds case; it's an open mystery
  (a different URL, a session-gate, or a site change) already tracked
  and not solved by this WO.

**No genuine plain-vs-headless comparison was available from the brief's
named examples**, so none was fabricated. `docs/COVERAGE_HANDOVER.md`'s
own breakthrough #1 (a headless pass found a platform on 41% of
previously-rejected large governments, JS-rendered navigation, not
firewalls) remains the standing, already-measured evidence that
headless recovers real cases a plain fetch misses -- this WO did not
have a confirmed case to add a platform-signature-specific data point to
that finding, and says so rather than inventing one. **Every signal kept
in `platform_signatures.csv` is marked `needs_render=false`** because
every one of them was found via a plain fetch; no signal in this pass
was confirmed to require rendering.

## Site-builder overlap with `scripts/cms_fingerprint.py`

Site-builder/CMS-family fingerprinting already exists (WO-154/WO-179) --
this WO reused `cms_fingerprint.classify()` directly against all 172
successfully-fetched home pages rather than inventing new rules.

Overall family distribution across the 172 home pages:

| Site builder | Count | Share of 172 |
|---|---|---|
| unknown (no existing rule matched) | 92 | 53.5% |
| civicplus | 37 | 21.5% |
| wordpress | 20 | 11.6% |
| municode_web | 9 | 5.2% |
| revize | 7 | 4.1% |
| opencities | 5 | 2.9% |
| civiclive | 2 | 1.2% |

**Site builder predicts platform clearly in exactly two cases** in this
sample: `municode_web` (9 of 10 `municode_meetings` platform rows) and
`civicplus` (trivially, 10 of 10 `civicplus`-labeled rows, plus it's the
single most common family seen on OTHER platforms' home pages too --
37 total, spread across cablecast, legistar, telvue, wistia, youtube,
boxcast, invintus, civicclerk.com). For every other platform in this
sample, the home page's CMS family is either `unknown` (most of escribe,
swagit, iqm2, suiteone, townhallstreams, utah_pmn, hyland) or spread
thinly across the generic families (wordpress/revize/opencities), so
"site builder predicts platform" does **not** generalize as a broad rule
here beyond the two cases above -- worth knowing before leaning on it for
WO-268's design. The 53.5% `unknown` rate also isn't a WO-267 finding so
much as a restatement of `cms_fingerprint.py`'s own documented gap (most
government sites still run a CMS that module has no rule for yet).

## What this sample could not cover

- **No genuine render-vs-plain comparison** (see above) -- the brief's
  named JS-drawn examples didn't hold up under verification.
- **Response headers, cookies, and CDN-ish header signals were collected
  (`*.headers.json` sidecar files alongside every saved raw page) but no
  candidate signal of that kind cleared measurement** -- every kept
  signal in this pass is either a vendor hostname or a path shape found
  in HTML/URL text. A header-based signal (a CDN `cf-ray`/`x-served-by`
  pattern specific to one vendor, a cookie name) is a real, unexplored
  lead for a follow-up, not ruled out by this pass.
- **champds/suiteone/boxcast/townhallstreams/utah_pmn's "home page"
  numbers are platform-URL-only, not genuine government-homepage
  coverage** (see cautions above) -- a future pass should find each
  sampled tenant's own separate civic domain before trusting their
  "distinct-domain home" numbers.
- **BoardDocs and Simbli** have no adapter and essentially no real
  sample in the research file; not covered at all.
- **A research-file data-quality gap found along the way, not fixed
  here**: `suspected_meeting_link_provider`/`suspected_video_provider`
  sometimes stores a raw domain-shaped value (`civicplus.com`,
  `civicclerk.com`, `youtu.be`, `vimeo.com`, `granicus.com`,
  `youtube.com/embed`, `legistar.com`, `champds.com`) instead of the
  normalized short platform key (`civicplus`, `civicclerk`, `youtube`,
  …) -- 67 rows across the whole file as of 2026-09-12. This silently
  splits a platform's population across two label spellings in any
  `Counter`/groupby over these columns (confirmed while building this
  WO's candidate sampler). Filed in `BACKLOG.md`.

## Recommended signal set for WO-268

Use `app/utils/jurisdiction_data/platform_signatures.csv` as-is (28
signals) via `scripts/platform_fingerprints.py`'s `fingerprint()` for a
first pass over the unknown-platform population, but weight a match by
which column above actually has evidence for that platform:

1. **Trust a home-page match outright** for the platforms with a real
   distinct-domain home hit rate > 0 in this pass: civicclerk (0.667),
   municode_meetings (0.500), hyland's `agendaonline-path` (0.200),
   telvue (0.333), utah_pmn (1.000, n=2). These are the platforms where
   this WO actually demonstrated a signal found by fetching a page that
   had no prior reason to be suspected.
2. **Treat a home-page match as a lead needing one more hop**, not a
   confirmed platform, for civicweb/granicus/iqm2/wistia -- their
   distinct-domain sample was 0-1 governments (too thin to trust) or (for
   wistia) showed zero home-page hits despite a 100% hub-confirmed
   signal. Route these through the existing hop-link scorer
   (`find_hop_links()`/`looks_like_document_hub()`, WO-228) before
   trusting a bare regex hit on the homepage alone.
3. **Don't expect a signal at all from escribe, swagit, clerkbase,
   champds, suiteone, townhallstreams** on a genuinely unrelated
   homepage -- this pass has zero evidence either way for these
   (distinct-domain n=0), because every sampled government's own
   recorded domain already WAS the platform tenant host. These
   platforms' tenants may simply not keep a separate civic site at all
   often enough to matter, or this sample just didn't catch one -- a
   dedicated check (pick 10 of these tenants and look up their city's
   OWN domain independently, then fetch THAT) is real, scoped follow-up
   work, not a rerun of this same candidate builder.
4. **Run `cms_fingerprint.classify()` alongside the platform matcher**
   (already wired via `classify_site_builder()`) and use the two strong
   site-builder correlations above (municode_web, civicplus) as a
   platform hint when the platform matcher alone finds nothing.
5. **PrimeGov/Vimeo/Cablecast/Boxcast/YouTube/Legistar have no validated
   signal from this pass** -- re-derive from a cleaner sample (labels
   that actually agree with their own hub URL, a bigger n for the small
   ones) before relying on any of their numbers above; don't silently
   promote a rejected signal into production matching on the strength
   of this table alone.
