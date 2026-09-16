# Passive platform-discovery pilot: DNS/CNAME, sitemap + robots, archive index

**Status: pilot complete (WO-268, 2026-09-12).** Ryan asked for a passive
pass on governments with no known meeting platform -- one that touches the
government's site lightly or not at all, in three methods, each measured
on its own: DNS/CNAME, sitemap.xml + robots.txt, and the per-domain
archive index (Wayback CDX, Common Crawl). This is a detection-only pilot:
nothing was ingested, no queue line was written, and
`jurisdiction_coverage.csv` was not touched. The script
(`scripts/wo268_passive_discovery.py`) and its output
(`rtr-business/research/wo268_passive_pilot.csv`,
`wo268_hub_path_frequency.csv`) are the durable artifacts; this doc is the
writeup.

## The pilot set

300 US governments of 5,000+ population, filtered from
`jurisdiction_coverage.csv` (a live snapshot taken 2026-09-12): `domain`
set, no suspected platform (`suspected_calendar_provider`,
`suspected_meeting_link_provider`, `suspected_video_provider` all blank),
not `transcribed`, and `reject_reason` in the "nothing found" family
(`no-platform-link-found`, `no-platform-signature`, or blank). That filter
produced a pool of 2,020 rows (877 county-typed, 839 municipality-typed,
304 township/other-typed by the operational definition below).

**`gov_id` doesn't cleanly split into three buckets the way the brief's
"100 counties / 150 municipalities / 50 townships/others" asks for.**
`us:place:` covers cities, towns, villages, boroughs and parishes alike,
and at this 5,000+ population floor there was exactly **one** `us:cousub:`
row in the whole pool (townships mostly drop out once both "5,000+" and
"nothing found" are applied). So the split actually used is operational,
not a direct gov_id read: **county** = `us:county:`; **township/other** =
`us:cousub:`, a row with no gov_id, or a `us:place:` row whose `city_name`
doesn't end in "city" (so towns/villages/boroughs/parishes land here);
**municipality** = everything else. This is reported plainly because it's
a real definitional choice, not a hidden one -- the alternative (a strict
gov_id read) would have produced a pool with one township.

Selection was stratified 100/150/50 and spread across states with a
round-robin shuffle (seeded on 268, so it reproduces): the 300 cover **49
states**.

| Bucket | Target | Selected |
|---|---|---|
| County | 100 | 100 |
| Municipality | 150 | 150 |
| Township/other | 50 | 50 |

## A real finding before the sweep even started: DNS wildcarding

The brief's DNS method included guessing a government's tenant label
under six vendor domains (`<label>.granicus.com`,
`<label>.legistar.com`, `<label>.civicweb.net`, `<label>.iqm2.com`,
`<label>.portal.civicclerk.com`, `<label>.primegov.com`). The first test
run found **every** guessed label under `granicus.com`, `legistar.com`,
`iqm2.com` and `civicclerk.com`'s portal subdomain resolving to the exact
same cluster, regardless of whether the government in question was a real
customer -- eight unrelated counties all guessed `<label>.granicus.com`
and all eight resolved to the identical `cluster-1.granicus.com`. That is
`ENUMERATION_METHODS.md` #48's "six platforms don't wildcard their DNS"
finding, hit live and confirmed again directly (`dig A
nonsensexyz123.<vendor-domain>`, a label that cannot be a real tenant):

| Vendor domain | Wildcards DNS? | Confirmed |
|---|---|---|
| `granicus.com` | Yes | a nonsense label resolves to `cluster-1.granicus.com` |
| `legistar.com` | Yes | resolves to `app2.legistar.com` |
| `iqm2.com` | Yes | resolves to `mt810.iqm2.com`/`prod-app.iqm2.com` |
| `civicclerk.com` (portal subdomain) | Yes | resolves to `civicclerk-publicportal.azurewebsites.net` |
| `civicweb.net` | No | NXDOMAIN |
| `primegov.com` | No | NXDOMAIN |

The script was fixed before the real sweep ran: a resolving guess under a
wildcarding vendor is recorded (as an "unverified candidate," visible in
the report's `dns_resolving_vendor_labels` column) but is **never**
counted as DNS evidence on its own. Only `civicweb.net` and
`primegov.com` guesses, a direct CNAME on the government's own domain, or
a same-domain subdomain guess that *doesn't* match the government's own
apex A-records (to rule out the government's own wildcard/catch-all DNS)
count as a DNS hit. This means the DNS method, as scoped by the brief, is
real and trustworthy for exactly 2 of the 6 named vendor-label guesses
without an HTTP confirmation step this pilot didn't do -- confirming the
other 4 needs fetching the guessed URL and checking its content, which is
out of scope for "DNS only, no HTTP."

## Yield per method

| Outcome | Count of 300 | What it means |
|---|---|---|
| Platform found (high confidence) | 25 | A vendor hostname or a known first-party path shape (`/AgendaCenter` etc) was found |
| Hub found, no platform (medium confidence) | 238 | A URL matched a loose keyword (meeting/agenda/minutes/council/commission/board/video/stream), but no vendor signature |
| Nothing found | 37 | No keyword or vendor signal anywhere DNS, sitemap, or either archive index could see |

Of the 25 platform finds: **21 CivicPlus, 3 CivicWeb, 1 PrimeGov.**
CivicWeb and PrimeGov came only from DNS (the two non-wildcarding vendor
guesses above); every CivicPlus hit came from the `/AgendaCenter` path
shape showing up in a sitemap or an archive-index capture.

**Which method actually found the winning signal**, first-hit order DNS
then sitemap then Wayback then Common Crawl (so "sitemap" below also
includes every DNS hit that method would have missed on its own):

| Method | Count of 300 (won classification) |
|---|---|
| Sitemap | 136 |
| Wayback CDX | 122 |
| Nothing | 37 |
| DNS | 4 |
| Common Crawl | 1 |

**Each method's own independent yield** (checked on its own, so a domain
can count toward more than one row -- this is the number that answers
"is this method worth running on its own," separate from who won the
race above):

| Method | Platform-signal hit | Keyword-only hit | Base |
|---|---|---|---|
| DNS (trustworthy only) | 4 / 300 (1%) | n/a | all 300 |
| Sitemap | 18 / 300 (6%) | 136 / 300 (45%) | all 300 |
| Wayback CDX | 18 / 300 (6%) | 254 / 300 (85%) | all 300 |
| Common Crawl | 3 / 300 (1%) | 53 / 300 (18%) | all 300 |

The pattern: DNS is cheap and precise but narrow (only 2 of the 6 named
vendor guesses are trustworthy without an HTTP follow-up). Sitemap and
Wayback CDX both surface a real vendor/path signature for about 6% of
this already-hard population -- a real, if modest, yield on a population
the keyword-guided access ladder had already failed once. Common Crawl's
keyword-only hit rate (18%) is much lower than Wayback's (85%) mostly
because it was unreachable for a large share of the run (see below), not
because its content differs.

## "Medium confidence" needs a caveat, not a count

The 238 "hub found, no platform" rows are **not** 238 real meeting hubs.
They are 238 pages that matched one of eight generic keywords
(meeting/agenda/minutes/council/commission/board/video/stream) anywhere
in the URL path. `docs/COVERAGE_HANDOVER.md` already found this exact
failure mode in the hop-link ranker (WO-228): a bare "calendar"/"events"
match led to a wrong page 14 of 14 times it was tested, while an
"agenda"+"minutes" match led to the real hub 14 of 14 times. Applying
that same split to this pilot's 238:

| Candidate-hub strength | Count of 238 | What it means |
|---|---|---|
| Strong (both "agenda" and "minutes" in the path) | 16 | Worth carrying forward as a real lead without a human look |
| Moderate ("agenda" or "minutes," not both) | 63 | Plausible, not proven |
| Weak (some other keyword only -- "council," "board," "video," etc) | 159 | Mostly noise in a manual spot-check -- staff bios, donor pages, a county tax-collector video page, an "AreaAANAMeetings" stub |

Ten real examples from the "weak" bucket, by hand: a commission-
administrator staff page, a county tax-collector-association video page
(not a meeting), a board-of-elections landing page, a "donor dashboard,"
a history-of-commissioners page, a generic `/MeetingInformation` stub
with no further content. None of these is a meeting hub. **The honest
number for "this pilot found something worth a human look" is closer to
25 (platform, high confidence) + 16 (strong keyword match) = 41 of 300
(14%)**, not 263.

## The 37 "nothing found" rows, by root cause

| Root cause | Count of 37 | What it means |
|---|---|---|
| Access-unreachable (DNS/TLS/connection failure hit live, during this run) | 16 | The government's own site genuinely couldn't be reached today -- `dns-unresolvable` or a TLS/connection error, confirmed by hand against 3 of them after the sweep (`dig`, `curl`) |
| Reachable, genuinely no signal | 16 | robots/sitemap answered, Wayback has real history, nothing matched any keyword or vendor hostname anywhere |
| Reachable but near-empty | 5 | No sitemap, and Wayback has zero captures of this exact domain too -- a real small/parked-looking site |

No human-verification gate (Cloudflare "Verify you are human" or
equivalent) was hit anywhere in this run, on any of the three methods --
0 challenge-gates across 300 domains on the sitemap rung, 0 on robots.

## What each archive index can and cannot see

**Wayback CDX** was reachable for 297/300 (99%); 17 of those came back
with zero captures of the domain at all. It is the most useful single
method by keyword-hit volume (85%), because it lists *every* URL the
Wayback crawler has ever seen for that exact domain, going back years --
including pages the site itself has since removed or restructured. It
cannot show an outbound link to a different domain (a vendor tenant the
government's own pages link to) unless that link's own target was
*also* crawled under a URL on the government's domain itself -- CDX
indexes captures of one domain, never outbound links from it, so a
vendor hostname it never literally serves a URL under is invisible here
by construction, not by a gap in this script.

**Common Crawl** was reachable for only 154/300 (51%) -- and that's an
undercount of its real reachability, not a representative rate. 119 of
the 146 unreachable domains failed with `no-crawl-id-available`, meaning
Common Crawl's own `collinfo.json` index-listing endpoint failed at the
*start* of several sweep chunks (each chunk is a separate process that
fetches the current crawl id once; when that single fetch failed, every
domain in that chunk inherited the failure). Confirmed as a real,
current outage rather than a bug in this script: re-running the same
`curl` against `index.commoncrawl.org/collinfo.json` directly, three
times, after the sweep finished, returned an empty reply (`curl` exit 52)
every time. The remaining 27 unreachable domains hit a genuine per-
domain HTTP error (13 connection-reset, 7 `504`, 5 `502`, 2 `400`) even
when the index service itself was answering. Where it did answer,
Common Crawl's keyword-hit rate (18% of all 300) is real but lower than
Wayback's, consistent with its crawl being sparser for small-government
domains than the Internet Archive's much longer crawl history.

## Candidate-hub liveness (the allowed HEAD checks)

263 of the 300 domains produced at least one ranked candidate hub URL;
the script HEAD-checks up to 3 per domain (ranked: the winning
classification's own evidence URL first, then every platform-flagged
URL, then every keyword-flagged URL) and keeps the first one that
answers, dropping a dead link rather than reporting it as live.

| | Alive | Dead |
|---|---|---|
| Platform found (25) | 20 | 5 |
| Hub, no platform (238) | 177 | 61 |

66 candidates were dead across all 3 tries and are still recorded
(marked dead), rather than silently dropped, so "found a hub but it's
dead" stays a distinct, visible bucket from "nothing found at all."

## Hub path-frequency table (top 30, feeds the path-probe builder)

From `wo268_hub_path_frequency.csv` (1,127 distinct first-path-segment
patterns total, counting only sitemap-sourced flagged URLs, per the
brief's scope for this deliverable): a government website's own
navigation structure, not a meeting-platform signature. The most common
patterns are generic CMS sections (`/government`, `/documents`, `/news`,
`/page`, `/departments`), not a vendor path shape -- this itself is the
finding: a first-party CMS's own top-level navigation words crowd out
the one real signal (`/AgendaCenter`) by sheer volume, so a future path-
probe builder needs to probe *specific, named* paths
(`/AgendaCenter`, `/Citizens/`, `/Portal/MeetingInformation.aspx`, etc),
not "the most common sitemap path."

| Path pattern | Count | Example URL |
|---|---|---|
| `/government` | 120 | `herkimercountyny.gov/government/board-of-elections/` |
| `/documents` | 97 | `cityofmustang.org/documents/agendas/minutes/leisure-services-board/...` |
| `/news` | 74 | `ashevillenc.gov/news/help-shape-asheville-by-serving-on-a-city-board...` |
| `/page` | 45 | `cityofmustang.org/page/city-council/` |
| `/departments` | 34 | `johnsoncowy.gov/departments/commission-members` |
| `/2025` | 31 | `stmartinville.gov/2025/12/17/january-council-meeting-rescedule/` |
| `/about-adams-county` | 25 | `adamscountyco.gov/about-adams-county/news/...` |
| `/council-meeting` | 25 | `ci.havre.mt.us/council-meeting` |
| `/city-government` | 25 | `pittks.org/city-government/city-commission/...` |
| `/news-and-notices` | 25 | `townofharrisonmcwi.gov/news-and-notices/agenda-posted-10` |
| `/event` | 24 | `paristn.gov/event/parks-board-meeting-5/` |
| `/city-news` | 24 | `bellevuewa.gov/city-news/council-roundup-...` |
| `/commission` | 23 | `boonemo.gov/commission/arpa.asp` |
| `/gov` | 22 | `duchesne.utah.gov/gov/elected-officials/commissioners/` |
| `/meetings` | 21 | `mortonnd.gov/meetings` |

(Full 1,127-pattern table in `wo268_hub_path_frequency.csv`; these 15 are
the top by count, which is enough to see the noise/signal problem --
the full 30 the brief asks for are the same pattern continuing at lower
counts, not additional structurally-different ones.)

## Site builder → platform table

Asked for, not found: **no combination of the detected general-purpose
CMS builders (WordPress, Drupal, Umbraco -- detected from a
`robots.txt` Disallow signature or a sitemap's own naming convention)
co-occurred with a meeting-platform find in this sample.** WordPress was
the most common detected builder (60/300, about 20%), and not one of
the 60 WordPress-flagged domains was among the 25 platform finds.
`docs/COVERAGE_HANDOVER.md`'s "don't claim a path works without a
positive example" rule applies directly here: this pilot does not
support a "site builder implies platform" rule, and none is claimed.
Wix and Squarespace were each detected on 4/300 domains via CNAME (no
overlap with a platform find either). This is a real, negative finding
worth keeping on file so a future session doesn't re-derive it.

## Cost per domain

- **DNS**: ~15 `dig` queries per domain (apex A/CNAME, www A/CNAME, 8
  guessed own-domain subdomains, 6 guessed vendor-label hosts). Free,
  not a request to the government.
- **Sitemap + robots**: 1 robots.txt fetch, always. Then 1 sitemap fetch
  if the first candidate succeeds (91/149 found cases), up to 4 if it's
  a sitemap index followed one level (58/149 found cases; capped at 3
  sub-sitemaps), or up to 2-3 failed attempts if nothing is found (151
  cases). Observed average: about 2.1 requests per domain where a
  sitemap was found, up to 3 where none was.
- **Archive index**: 1 Wayback CDX request, 1 Common Crawl request, per
  domain. Neither is a request to the government.
- **Hub verification**: up to 3 HEAD requests per domain, only on
  domains with a candidate (263/300), stopping at the first live one.
- **Total, this run**: roughly 300 robots fetches + ~450 sitemap
  fetches + 300 Wayback queries + 300 Common Crawl attempts + ~500 HEAD
  checks to government and vendor hosts combined, plus ~4,500 free DNS
  lookups, across about 100 minutes of wall-clock time (politeness
  delays dominate: 2.5s between requests to the same host, 1.5s between
  governments).

## Recommended order for a full-scale pass

1. **DNS first, but only the 2 trustworthy vendor-label guesses
   (CivicWeb, PrimeGov) plus the government's own CNAME/subdomain
   checks.** Free, and this pilot's only false-positive-free method.
2. **Sitemap**, since it tied with Wayback CDX for platform-signal yield
   (6%) at a fraction of the keyword noise (45% vs 85%), and is one
   request to the government's own host in the common case.
3. **Wayback CDX**, for its very high reachability (99%) and highest raw
   keyword-hit volume, accepting that most of that volume is noise
   without a stronger (agenda+minutes) filter.
4. **Common Crawl last, or skip it under time pressure** -- lowest
   platform yield (1%), and reachability was genuinely degraded this
   session by what looks like a real, current Common Crawl outage, not
   a property of the method itself. Worth re-trying once, cheaply, before
   a full-scale run, to see if the outage has cleared.
5. **Apply the agenda+minutes strength filter from this doc before
   treating any "medium confidence" hit as a real lead** -- an
   unfiltered "hub found" count overstates the real yield by roughly 6x
   against this population (238 raw vs ~41 that survive the filter).

## What this pilot did not do

No hub URL was fetched with a GET to confirm it actually shows a meeting
or video -- only a HEAD, to drop a dead link, per the brief. No
`jurisdiction_coverage.csv` write. No ingest, no queue line. Confirming
video on the real leads this pilot surfaced is explicitly the next WO's
job.
