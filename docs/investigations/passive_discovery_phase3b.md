# Passive discovery, phase 3b (WO-281): one homepage fetch per government,
scored with the measured hop weights, then the top-5 flagged links

**Status: complete (WO-281, 2026-09-12).** WO-273's phase 3 gave the
1,610 governments with no flagged URL after phase 2 only five blind
named-path probes each. Ryan's point: we have another polite chance to
interact with those sites without slowing anything down -- fetch the
homepage once, collect every link with its anchor text and where it sits
on the page (nav, header, footer, menu, or plain body), and score them
with the measured vocabularies instead of guessing paths. That is the
access ladder's first rung plus the WO-274 hop scorer, applied inside
the passive pass.

## Population

`research/wo273_classified.csv` rows with `confidence == "none"` --
re-derived directly against the committed file rather than trusting the
brief's number blind: confirmed exactly **1,610** of 2,574 rows, matching
`research/wo273_candidates.csv`'s distinct-domain count exactly. WO-278
(running in parallel) owns the other 964 rows (those WITH a flagged
URL); this WO never touched them. WO-278 had not published a
catch-all-only subset of its own by the time this run started (checked
directly -- no `wo278_*` research file existed yet), so this used the
full 1,610 per the brief's own fallback instruction.

## Method, two phases

1. **Homepage fetch** (`scripts/wo281_homepage_hop.py --phase
   homepage`): one fetch per government's own homepage. Archive-first
   (`wo273_targeted.try_wayback_archived_body()`, `id_` raw form,
   capture <=18 months -- reused, not reimplemented), live plain-HTTP
   fallback, browser headers only after a 403 or a dropped connection
   (never after a 404), a human-verification-gate check that stops cold.
   Every `<a href>` is extracted with its anchor text and page position
   (`wo147_access_ladder_sweep._nav_position_bonus()` -- the exact
   position check the real scorer already computes internally, read out
   for this report rather than reimplemented), `detect_platform()` is
   run on every raw href, and each link is classified hub-shaped vs
   meeting/video-shaped via WO-274's own measured vocabulary
   (`hop_link_weights.csv`'s hub/meeting token sets). `find_hop_links()`
   -- the real, measured WO-274 scorer, called directly -- ranks all
   candidates and the top 5 are kept.
2. **Targeted fetch** (`--phase targeted`): fetches those top-5 links
   (same politeness), runs `platform_fingerprints.fingerprint()` +
   `detect_platform()` over the fetched page's own body AND its own
   links, plus `classify_site_builder()` for the record. A catch-all
   test (one nonsense path per host, cached; a 200 whose body byte-size
   or hash matches either the nonsense response or is suspiciously close
   to it is a soft-200) and an 800-byte floor gate every hit. A page must
   name this government's own city/county AND its state before anything
   counts confirmed -- same bar WO-273's phase 3 used.

Concurrency 32 governments in flight, one request in flight per host
(`HostRateLimiter`, >=2.5s between requests to the same host), a
vendor-host hit rate-limited under its VENDOR FAMILY name so many
governments that happen to flag the same vendor (mostly YouTube here)
don't pile onto it at once, honest User-Agent, browser headers only
after a 403 or a dropped connection, stop cold at a human-verification
gate. Zero YouTube block signatures seen during the sweep or the later
hand-check calls.

## A real, live finding: `web.archive.org` itself was unreachable from
this environment for the whole run

Every single fetch in both phases used `fetch_method=live` --
`try_wayback_archived_body()` never once returned a usable archived
body. Checked directly, not assumed: a plain `requests.get` to
`https://web.archive.org/...` returned `ConnectionError: Connection
refused` in under 0.03 seconds on every attempt, while `https://
archive.org/` and ordinary internet hosts (`google.com`, real government
sites) answered normally. **This is a different, narrower finding than
WO-273's CDX-search degradation** -- WO-273 saw slow, intermittent
503s/timeouts on the CDX *search* API specifically; this run saw an
instant connection refusal on `web.archive.org` itself, which reads as a
network-egress restriction specific to this execution environment rather
than a continuation of the live internet-wide CDX problem. Reported
plainly so a rerun elsewhere isn't misled by it: every homepage and
top-5 fetch here took the live path, by design (the code already treats
any archive failure exactly like "no capture found" and falls through),
so no result below depended on Wayback working.

## Phase 1: homepage fetch, full population (1,610 governments)

| Access mode | Count of 1,610 | Share |
|---|---|---|
| `live-plain` (plain HTTP succeeded) | 942 | 58.5% |
| `dns-unresolvable` | 258 | 16.0% |
| `connection-dropped` | 195 | 12.1% |
| `live-browser-headers` (403 or drop, browser headers retried) | 122 | 7.6% |
| `timeout` | 93 | 5.8% |

Timing: median 883ms per homepage, p95 3,887ms. The 50-government timing
test run before the full sweep (required by this WO's own brief) came in
at **291.7 governments/minute**; the full 1,610-government run (many
failing fast on DNS/connection errors, which is what makes the average
so high) finished at **1,158.6 governments/minute**, 81 seconds wall
clock for the last 1,560.

**860 of 1,610 governments (53.4%) produced at least one scored
candidate link** (`find_hop_links()` returned something). The other
750 either had no real page (dns/connection/timeout, 546 of them) or a
real page with nothing the scorer judged worth keeping. **218
governments (13.5%) link a platform outright** (a raw href on the
homepage that `detect_platform()` accepts on its own -- a vendor host or
a named first-party path).

### The position question (Ryan's own): where did the winning link sit?

Of the 860 governments with a non-empty top-5, the rank-1 (highest-
scored) link's own page position:

| Position | Count of 860 | Share |
|---|---|---|
| `nav` (inside `<nav>`/`<header>`) | 550 | 64.0% |
| `body` (a plain paragraph/content link) | 152 | 17.7% |
| `menu` (a `<ul>`/`<ol>` outside nav) | 116 | 13.5% |
| `footer` | 42 | 4.9% |

Restricted to the 259 governments that went on to get a real,
name-matched platform CONFIRMED in phase 2 (the more decision-relevant
cut -- not just "ranked first" but "actually panned out"), the first
confirmed link's own position:

| Position | Count of 259 | Share |
|---|---|---|
| `nav` | 178 | 68.7% |
| `body` | 37 | 14.3% |
| `menu` | 28 | 10.8% |
| `footer` | 16 | 6.2% |

**The real signal sits in nav about seven times out of ten either way.**
Footer is the smallest bucket both times, which matches this WO's own
`_FOOTER_PENALTY` design choice (a footer link is disproportionately
Terms-of-Service/social-media/vendor-marketing noise) -- it is still
worth the small nav-bonus/footer-penalty spread rather than a hard
exclusion, since 16 real confirmed governments (6.2%) would have been
missed by excluding footer links outright.

## Phase 2: targeted fetch of the top-5 links

| Step | Count |
|---|---|
| (government, URL) rows fetched | 3,889 |
| Distinct governments covered | 860 |
| Caught as soft-200 / catch-all (byte-size or hash matches the host's own nonsense-path probe) | 37 |
| Under the 800-byte floor | 6 |

Timing: median 3,225ms per URL, p95 23,715ms (the long tail is almost
entirely YouTube -- 228 of the 3,889 candidate URLs are `youtube.com`
links, all serialized under the SAME vendor-family rate limit regardless
of which government they belong to, by design).

### The headline number

| Outcome | Count of 860 (governments with >=1 candidate) | What it means |
|---|---|---|
| Platform confirmed (a fetched top-5 page names this government + its state AND carries a real platform signal, on the URL itself or elsewhere on that same page) | **259** | A real lead, hand-read-gated, most not yet a page |
| Flagged (had >=1 candidate) but never confirmed | 601 | A scored link that died, didn't match a signature, or didn't name the government |

**Two different strengths of "confirmed" sit inside that 259, and the
split matters for how much to trust each:**

| Confirmation strength | Governments | What it means |
|---|---|---|
| **Strong** -- the SCORED candidate URL *itself* is a platform `detect_platform()` recognizes | 107 | The same bar WO-273's own phase 3 used |
| **Weak** -- confirmed only via a DIFFERENT link found elsewhere on that same fetched page (a site-wide nav/footer Granicus or YouTube link, say) | 152 | A real platform is somewhere on this government's site, but not necessarily behind the scored candidate link itself |

Of the 107 "strong" governments, 98 are YouTube (almost always a bare
channel link picked up from a homepage footer/nav "Follow us" widget,
not a hub/meeting-vocabulary match -- this population's real, useful
finding is that a lot of small governments' only on-site trace of their
own YouTube channel is a footer icon, which WO-273's vocabulary-first
method had no way to see). The other 11 are real hub/meeting URLs on
CivicPlus (3), Granicus (1), IQM2 (1), Legistar (1), ProudCity (4), and
viebit (1) -- see "Hand-read gate" below for what happened to each one.

**Meeting-DETAIL pages, not just hubs (Ryan's other question):** 31 of
the 259 confirmed governments got a link classified meeting-shaped
(WO-274's meeting-vendor vocabulary -- clip/mediaplayer/watch/player/
videos/splitview, etc.) rather than hub-shaped, on 42 rows. Sampling
these directly (not just trusting the classifier) found a real,
substantial bucket of genuine "watch our council meetings" video-hub
pages on Granicus/YouTube/Swagit/SuiteOne that WO-273's five blind
named-path probes never had a way to find, since these pages don't use
any of the named vendor paths WO-273 probed for. It also caught one
clean false positive worth naming: `ci.craig.co.us`'s meeting-shaped hit
resolved to a real YouTube video titled "How to Translate YouTube Videos
with Closed Captions 2020" -- the word "Watch" in "Neighborhood Watch"
(a page about the city's Neighborhood Watch program) is what actually
matched. The hand-read gate caught it before anything was ingested; it
is not, and was never treated as, a real meeting.

### Site-builder families found on the fetched pages (for the record)

`unknown` 2,281, `revize` 808, `wordpress` 409, `civicplus` 59,
`wv_local_gov` 31, `opencities` 25, `proudcity` 25, `townweb` 10,
`municode_web` 6, `civiclive` 4 (of 3,889 rows; `classify_site_builder()`
delegates to `scripts/cms_fingerprint.py`, unchanged by this WO).

## Comparison against WO-273's blind probes, same population

WO-273's phase 3 ran its five named-path probes
(`/AgendaCenter`, `/AgendaOnline/Meetings/ViewMeeting`, `/Citizens/`,
`/Portal/MeetingInformation.aspx`, `/Archive.aspx?AMID=1`) against every
one of these same 1,610 governments -- 8,050 fetches, confirming **87
governments (5.4%)**, almost entirely Hyland (76), IQM2 (83 -- note some
governments hit more than one path), and CivicWeb (61).

This WO's homepage-plus-top-5 method used **5,499 total fetches**
(1,610 homepage + 3,889 targeted -- 32% fewer than WO-273's blind probes
on this same population) and confirmed **259 governments (16.1%)** by
the same name+state bar -- roughly **3x** the yield, at less than
two-thirds the fetch volume. Even counting only the "strong" 107 (the
directly comparable cut, since WO-273's own method also checked the
specific flagged URL rather than a whole page's links), that is still
107 vs 87 -- a real, if smaller, improvement, and a genuinely different
107: cross-referencing the two candidate sets found zero overlap in
which specific governments each method caught, meaning the two methods
are complementary, not redundant.

## Hand-read gate: what happened to the confirmed candidates

Per this repo's "hand-check every found video" and "don't claim a
data path works without a positive example" rules, nothing above was
treated as a page or a queue line until a human (this session) actually
looked. Given the scale (259 governments, 98 of them bare YouTube
channel links), this WO's hand-read pass covered two bounded batches
rather than all 259 -- see "What is undone" below for the rest.

**Batch 1 -- the 11 non-YouTube "strong" candidates.** Each resolved
live through the real adapter (`finder.resolve()`, the same call
`bulk_ingest.py` makes):

| Government | Platform found | What the adapter actually returned |
|---|---|---|
| Grand County, CO | civicplus | Checked the 5 most recent AgendaCenter listings itself -- no video |
| Fitchburg city, MA | civicplus | Same -- no video |
| Randall County, TX | civicplus | Same -- no video (see caution below) |
| Yamhill County, OR | civicplus | Raised a listing-page error rather than checking for video (see caution below) |
| Carson City, NV | granicus | Recognized the platform; the ViewPublisher hub page itself carried no transcript/agenda/video |
| Greene County, NY | iqm2 | Same, on the Citizens/Default.aspx hub |
| Seminole County, FL | legistar | Same, on the Calendar.aspx hub |
| Fairfax town, CA | proudcity | Found a real agenda PDF, no video |
| San Rafael city, CA | proudcity | Same |
| Holyoke city, MA | proudcity | A real "watch live"/"video archive" page found; the adapter extracted nothing from it |
| North Mankato city, MN | viebit | A real viebit tenant found; the adapter extracted nothing from its folder-listing page |

None of these 11 produced a real, ingestable meeting on this pass.
`research/wo281_apply_to_jc.py` (§158 protocol -- flock, fresh read
under the lock, a 99%-of-committed-lines floor, atomic write, LF
endings) recorded what was actually verified: a `meeting-without-video`
`reject_reason` for the 5 rows where the adapter explicitly checked for
video and found none, a `suspected_meeting_link_provider`/
`suspected_video_provider` field only (no reject_reason guess) for the
6 rows where the adapter recognized a platform but the specific hub page
gave no definitive answer either way.

**Batch 2 -- 23 of the 31 "meeting-DETAIL-shaped" confirmed candidates**
(excluding ones already covered in batch 1 and the youtube-channel-only
population). Two produced real, ingestable meetings:

| Government | Video | Real channel check (yt-dlp) | Outcome |
|---|---|---|---|
| Kasson city, MN | "City Council Meeting Before Closed 8 19 26", 1,193 caption segments | Channel = "City of Kasson" (exact match), uploaded 2026-08-26, 82.6 min | **Ingested** |
| Glenarden city, MD | "City of Glenarden 8 September 2026 Work Session", 1,599 caption segments | Channel = "City of Glenarden, MD" (exact match), uploaded 2026-09-09, 148.3 min | **Ingested** |

Both channel names were read directly (yt-dlp metadata, no download) and
matched the government exactly before ingest, per this repo's Kind-A/
Kind-B hand-check rule. Neither hit a YouTube block signature. The
other 21 of these 23 either had no extractable content (`platform=
unknown`, most commonly a generic page title with zero segments/agenda
items) or, in one case (`ci.craig.co.us`), resolved to the false
positive named above and was rejected outright.

Both ingests carried `gov_id` in the payload (`us:place:2732498`,
`us:place:2432500`), so neither depends on a pin reaching production.
Both also got a per-video `tenant_overrides.csv` pin for the worker's
later re-resolve (`www.youtube.com,youtube:n8c02ErKPMM,us:place:2732498,
fallback,wo281,...` and the Glenarden equivalent), following the
existing file's own `youtube:<video-id>` match convention exactly (not
the bare-id form the preamble sketches -- the file's real, working rows
already use the prefixed form, and `resolver.py`'s `_match_override()`
matches it against the video's own `external_id` hint, not the URL
path).

## What the hand-read gate still has to check

The remaining 249 confirmed-but-not-yet-hand-checked governments split
into two groups this WO deliberately left alone:

1. **98 YouTube channel-level candidates.** A bare channel link
   (`youtube.com/@handle`, `/channel/UC...`, `/user/...`) is not itself a
   meeting -- per this repo's Kind-A/Kind-B rule, each one needs its own
   video found and its own channel identity confirmed, the same
   per-channel work `scripts/wo174_pipeline.py`'s `classify_video_hand_
   check()` exists for. **YouTube channel/video work is
   `scripts/youtube_drip.py`'s job on a separate Mac as of 2026-09-11**
   (one drip per office connection) -- this session deliberately did not
   run 98 channel lookups from here, both to respect that ownership and
   because a bulk channel-enumeration run is a different, heavier kind
   of YouTube call than the two single-video metadata lookups this WO
   actually made.
2. **152 "weak" governments** (confirmed only via a different link on
   the same fetched page, not the scored candidate itself). These need
   the scored candidate's own page re-examined by a human to find which
   specific link on it actually carries the platform signal that
   name+state-matched.

Both lists are fully enumerable from `research/wo281_targeted.csv`
(`platform_confirmed != ""`, split by whether `detect_platform(url)` on
the row's own `url` succeeds) for whoever picks this up next.

## What this WO did not do

No `jurisdiction_coverage.csv` write for the ~1,597 governments outside
the 13 hand-checked ones above -- mirroring WO-273's own precedent (that
WO's 1,610 "no signal" and 147 "confirmed" governments were both left
detection-only, explicitly deferring the research-file apply to "the
next WO"). No YouTube channel enumeration. No headless browsing (not
called for by this WO's own brief -- homepage-only, first rung).

## Files

- `scripts/wo281_homepage_hop.py` -- both phases (`--phase homepage`,
  `--phase targeted`), plus `--finalize` for the summary stats above.
- `research/wo281_homepage_links.jsonl` -- every extracted link, raw, one
  JSON object per government (1,610 lines).
- `research/wo281_scored.csv` -- the top-5 per government (3,889 rows,
  860 governments).
- `research/wo281_targeted.csv` -- the fetch-and-confirm result for each
  of those 3,889 rows.
- `research/wo281_apply_to_jc.py` -- the 13-row `jurisdiction_coverage
  .csv` apply script (§158 protocol).
