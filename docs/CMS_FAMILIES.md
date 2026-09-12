# CMS families field guide (WO-154, 2026-09-10; WordPress family and
own-domain path pilot added by WO-176, 2026-09-10; GovOffice, Municipal
Impact and two state-hosted portal families added by WO-179,
2026-09-10; WordPress's near-universal `/feed/` rate and a small-sample
CivicPlus video-rate signal added by WO-197, 2026-09-11)

Read this before touching `scripts/cms_fingerprint.py` or
`app/utils/jurisdiction_data/cms_families.csv`. It explains what a
"CMS family" is for this repo, why it matters, and what each family
looks like, in plain terms.

## What this is for

About 9,600 governments in the research file are recorded
`no-platform-link-found`: their website loaded fine, but no plain
client saw a meeting or video link. Usually the reason is simple — the
site's menu is drawn by JavaScript, so a plain fetch never sees the
real link. Finding that link with a full browser (headless browsing)
works, but it is slow.

The cheaper idea, from Ryan: most government websites are not custom
software. A handful of companies build most of them — CivicPlus,
Revize, Granicus's "OpenCities" product, and a few more. If we can tell
which company built a given government's website from the page we
already fetched, we often already know, from other governments on the
same company's platform, where that company's meetings page usually
lives. Then a plain client can go straight there, instead of guessing
or paying for a slow headless browse.

`scripts/cms_fingerprint.py` reads one page's HTML and says which
company (family) built it, with the exact evidence that decided it.
`app/utils/jurisdiction_data/cms_families.csv` is the lookup table: for
each family, how it's recognised, where its meetings page usually is,
and how well the recognition rule actually worked when tested. This WO
(WO-154) built both. It does not use them yet — no ingest, no live
sweep. That is WO-155's job.

## How to read the numbers

Every family below was tested two ways:

- **Held-out recall**: take the real pages we found for a family, hide
  20% of them, and check whether the rule still recognises those hidden
  pages. All measured families passed 100% here, which is expected —
  the rules are simple pattern matches, not a trained model, so this
  number mainly confirms the rule doesn't depend on some accidental
  detail of the pages it was built from.
- **Precision proxy**: run each family's rule against every OTHER
  family's confirmed pages, and count false alarms. Two small "false
  alarms" turned up and both were real, not bugs: a CivicPlus site
  (Jackson, MO) and a Revize site (Kronenwetter, WI) that also happen to
  link out to Municode's meetings module in their footer. The rule
  correctly reports whichever vendor's marker it checks first — both
  are true statements about the same page.

A family with fewer than 6 confirmed pages was not split 80/20 — there
isn't enough data to make that measurement mean anything. Those
families are marked so, honestly, rather than given a number for show.

## The families

### CivicPlus

The most common family found in this round of training data (47 of the
213 pages fetched). Recognise it from any of: the footer text
"Government Websites by CivicPlus", a `cp-civicplusuniversity2.
civicplus.com` widget reference, or the site's own `/AgendaCenter` /
`CivicAlerts.aspx` module. Its meetings page is almost always
`/AgendaCenter` on the government's own domain (45 of 47 training
pages) — this is the strongest, most reliable pattern found. It
delegates video to itself in almost every case (CivicPlus sells both
the website CMS and the AgendaCenter meetings module).

### Revize

The second most common family (27 of 213). Recognise it from an asset
host shaped `cms{N}.revize.com/revize/{tenant}/...` (visible in the
page's own logo image tag) or a `/revize/plugins/...` stylesheet path.
**Its meetings page path is not predictable** — every Revize government
picks its own URL under `/government/...`, with no single recurring
leaf name. A live test in this WO tried `/government/agendas_minutes.
php` and `/agendas-minutes` on 17 real Revize governments that had no
known meeting listing: **zero** produced a real listing. Instead,
Revize serves a real HTTP 200 "page not found" template for a
nonexistent URL — it echoes the guessed link back inside a generic
"Your Link Name" social-share widget rather than returning a 404. A
naive check that only looks for the word "agenda" on the resulting page
will misread that placeholder as a real hit, because Revize's site-wide
navigation (present on every page, real or not) always contains that
word. **Guessing a fixed path does not work for Revize.** The
government's own homepage nav usually names the real page in plain
text (e.g. "Agendas & Minutes"); following that real link is the
correct next step, not guessing a URL shape.

### OpenCities (Granicus GovAccess)

Recognise it from `<meta name="generator" content="OpenCities - https://
granicus.com/product/opencities">`. This is the exact tag
`app/platforms/base.py`'s WO-163 fix exists to stop from being
misread as a real `granicus.com` video tenant — that fix was correct
(the tag names the *website* vendor, not a per-government video
tenant), and this module reads the same tag correctly, as a CMS-family
hint. Its meetings page path is **not confirmed**: `/Council/Agendas-
and-Minutes` was tried live on two real OpenCities governments (San
Fernando, CA; Littleton, CO) and 404'd on both. Every OpenCities page
in this WO's training set delegates its video to Granicus, which makes
sense — OpenCities and Granicus are the same company.

### Municode's meetings module

Not a full website CMS — the government's own site can be built on
anything (WordPress, custom, even CivicPlus). What's recognisable and
useful is a footer or nav link to `https://{slug}.municodemeetings.
com/`. Once that link is found, the meetings page path problem is
already solved: it's the linked subdomain itself, no guessing needed.

### ProudCity

A WordPress-based government CMS with white-labeled domains (no shared
apex domain to key on) — recognise it from asset paths like
`proudcity.com/js/app.min.js`, a `proudcity-theme` CSS class, or an
upload path shaped `/proudcity/{tenant}/uploads/...`. `/meetings`
worked as a live guess on 1 of 2 real tenants tried (`townoffairfaxca.
gov`: 200; `cityofbelvedere.org`: 404) — promising but not yet
confirmed as universal. Delegates video to a plain YouTube iframe
embed per meeting (see `app/platforms/proudcity.py`).

### CivicLive

Recognise it from an asset host reference to `hosted.civiclive.com` or
`hosted2.civiclive.com`, or the footer credit "Powered by Civiclive" —
the government's own domain (e.g. `lynnma.gov`) usually carries no
civiclive signature at all, only the page's own assets do. Only 1 fresh
example was fetched in this WO's own sample; `app/platforms/civiclive.
py`'s own 2026-09-01 pilot (n=13, a separate, earlier, search-biased
sample) found real video on ~77% of tenants, mostly YouTube or
CivicClerk. A real, confirmed meetings-page path exists from that
earlier work: `/city_hall/agendas___minutes` (Auburn, WA).

**WO-176 (2026-09-10) tested that exact path live on the one other real
CivicLive tenant on file, Lynn MA (`lynnma.gov`), and it 404'd.** Same
lesson as Revize below: each CivicLive tenant appears to pick its own
meetings-page path, not a shared one — Auburn's path does not
generalise. Still only 2 real tenants total (1 confirmed, 1
disconfirmed), and WO-176's own random 600-government pilot sample
contained zero fresh CivicLive tenants at all (it's too rare a vendor
to show up by chance in a general no-platform-link sample). Testing
this family properly needs a targeted list of known CivicLive tenants,
not another random sample.

### Town Web

Recognise it from a `cdn.townweb.com` dns-prefetch link or a literal
`<meta name="author" content="Town Web | ...">` tag. Only 2 confirmed
training pages — too few to trust a meetings-page path pattern from,
and both of the pages found were livestream pages, not agenda listings.
WO-176 (2026-09-10) sampled 13 fresh Town Web tenants in its random
600-government pilot and found 2 real listings via the *generic* path
list (`/archive`, `/calendar` — not a Town Web-specific guess, since
none is confirmed). Still too few (n=13) to trust as a real rate.

### WordPress

Added WO-176 (2026-09-10). Recognise it from `<meta name="generator"
content="WordPress ...">`, a `/wp-content/` asset path, or a
`/wp-json/` REST API reference. **By far the most common single family
in WO-176's random 600-government sample: 175 of 600 (29%), ahead of
CivicPlus (23) and Revize (32) combined.** Unlike CivicPlus, there is
no one fixed meetings-page path — but **WordPress's own built-in search,
`/?s=agenda`, works at real scale**: tried on the 137 WordPress sites
whose full generic path/feed list (sitemap first, then `/calendar`,
`/events`, `/minutes`, `/agendas`, `/archive`, `/feed/`, ...) had
already come up empty, `/?s=agenda` alone found 35 more real listings —
25.5% of those leftover sites, each one spot-checked against real
WordPress post/category markup (e.g. a real `category-2027-board-of-
supervisors-agenda` class on a real post), not just the search page
echoing the word "agenda" back in its heading. Combined with the 38
hits the generic list itself found on WordPress sites before reaching
any WordPress-specific path, that's a **41.7% (73/175) total real-hit
rate for WordPress** across both passes — the highest of any family
this repo has measured a real rate for, CivicPlus included. Two other
guesses, `/category/agendas` and `/category/meetings`, were tried on
the same 137 leftover sites and found nothing — not confirmed, don't
rely on them. ProudCity (below) is itself a WordPress build and keeps
its own more specific family name/rule, checked first — this WordPress
rule is the fallback for every OTHER WordPress-built government site.

**WO-197 (2026-09-11) found a second, separate reason WordPress is worth
special treatment: its `/feed/` answers almost every time.** Checking
2,471 real "a listing page was found, but no video-platform link" sites
left over from WO-179 for direct video/audio and a working RSS/Atom/ICS
feed, WordPress sites answered a feed 82.3% of the time (1,354 of 1,645)
— by far the highest feed-hit rate of any family measured, and higher
than WordPress's own direct-hit rate for video (7.9%, 130 of 1,645).
This is exactly what WordPress's own architecture predicts (`/feed/` is
a built-in, always-on route on a stock install, not a per-tenant
choice), so treat a WordPress site's `/feed/` as close to a default
"yes" going into any future feed-based work, the same way `/AgendaCenter`
is treated as a default "yes" for CivicPlus. See
`scripts/wo197_media_scan.py`'s feed-detection step and
`~/Documents/rtr-business/research/wo197_report.csv` for the full,
per-government data this rate is drawn from.

**The same pass found a small-sample but striking video rate for
CivicPlus: 66.7% (12 of 18).** These are CivicPlus sites WO-174/179 had
already checked `/AgendaCenter` for and recorded as carrying no
recognised platform link — WO-197's direct media/one-hop scan found real
video or audio on two-thirds of the handful left over anyway, well above
every other family measured in this same pass (unknown 11.6%, OpenCities
23.1%, Town Web 6.0%, Revize 6.0%, GovOffice/Municipal Impact 0%). n=18
is too small to call this a confirmed rate — unlike the families above,
this one hasn't been checked against a second, independent sample yet —
but it's a real, live-measured signal that a CivicPlus page can carry
video (an embed, a direct file link, or a link one hop into a meeting
detail page) that isn't on `/AgendaCenter` itself, worth a larger,
CivicPlus-specific follow-up before treating it as settled either way.

### GovOffice

Added WO-179 (2026-09-10). Unlike every family above, the government's
own domain here IS the vendor's own shared domain
(`govoffice.com`/`govoffice2.com`/`govoffice3.com`) — recognised with
100% certainty from the domain alone, no content marker needed. About
220 governments in the UScityURL address list name one of these hosts
directly. **No single meetings-page path recurs across tenants** — 10
real tenants sampled live (Evansdale IA, Goodview MN, Ball LA, Vinton
TX, Hallowell ME, Pottsboro TX, Panhandle TX, Blountstown FL, Slayton
MN, Custer SD): only 2 of 10 carried an obvious meeting-word nav link on
the homepage (Evansdale: `/Boards-Commissions`; Vinton and Pottsboro:
individual meeting detail pages linked straight from the homepage news
feed, at a per-event URL shaped `index.asp?SEC=...&DE=...`, not a fixed
path). Same lesson as Revize: read the homepage nav and sitemap per
tenant rather than guessing a shared path. No video platform confirmed
on any of the 10 — every one sampled was agenda-only.

### Municipal Impact

Added WO-179 (2026-09-10). Same domain-is-the-vendor shape as GovOffice,
on `municipalimpact.com`. **This one DOES have a reliably recurring
meetings path** — `/agendas` and `/minutes` both confirmed live on 8 of
9 real tenants sampled (Town of Delhi LA, Town of Double Springs AL
[neither page built yet — a real content gap, not a path miss], Town of
Elton LA, Coal Hill AR, Americus KS, Fountain City IN, Village of Parks
LA, Frost TX, Collins IA — Village of Kirkwood IL returned
`site_not_found`, not yet provisioned). The strongest recurring-path hit
rate found for any family since CivicPlus's `/AgendaCenter`. No video
platform confirmed on any tenant sampled — these are the smallest towns
in the population, agenda-only every time.

### State-hosted templates

Added WO-179 (2026-09-10). Ryan's idea going in: several states host
small towns' websites directly (Colorado, West Virginia, Delaware,
Kentucky, Indiana, Utah, Minnesota's `.mn.us` municipal domains — about
400 governments combined per the UScityURL address list). **What a real
9-government sample across these states actually showed: "state-hosted"
is not one company.** Once fetched, most of these domains turn out to
already be a *known* family — `warsaw.in.gov` and `ci.mora.mn.us`
fingerprint as CivicPlus; `mtsterling.ky.gov`, `cityofaustin.in.gov`,
`camden.delaware.gov` and `bicknell.in.gov` fingerprint as WordPress.
Those get that family's own path rule (CivicPlus's `/AgendaCenter`,
WordPress's `/?s=agenda`) — no new rule needed. Only two genuinely new,
distinct portal templates turned up:

- **`in_gov_towns_portal`** — a town with *no domain of its own* is
  hosted directly at `www.in.gov/towns/{slug}/`, Indiana's own shared
  portal. Confirmed on Georgetown, IN: `/towns/{slug}/meetings` is a
  real, populated listing of agenda PDFs. Only 1 tenant confirmed so
  far; expected to generalise (the URL shape is the state's own
  routing, not a per-tenant guess) but not yet proven on a second one.
- **`wv_local_gov`** — West Virginia's own shared SharePoint portal,
  `local.wv.gov/{slug}/`. Confirmed real for 3 towns (Williamstown,
  Madison, Fayetteville), recognised by host (or by the `Microsoft
  SharePoint` generator tag plus a `cdn.wvegov.com` asset reference for
  a differently-aliased tenant). **No meetings-page path confirmed** —
  the nav is SharePoint script-rendered, and a plain fetch found zero
  meeting-word links on any of the 3 homepages tried. Route through the
  generic path/sitemap list, same honest treatment as CivicLive/Town
  Web above.

Neither Colorado's, Delaware's, Kentucky's, nor Utah's remaining
non-WordPress/non-CivicPlus governments produced enough of a distinct
pattern in this sample to name a third portal family — they fall back
to fingerprint-first-then-generic-list, same as any other unrecognised
site.

### Streamline

**Not built.** About 240 real government pages were checked for
"streamlinewebsites" or "streamline website solutions" during this
WO's training pass; every hit on the bare word "streamline" turned out
to be an unrelated use of the English word (analytics flags, marketing
copy, a different vendor's tagline), not the vendor. This family stays
absent from the signature table rather than guessing at a marker
nobody has actually seen. See `BACKLOG.md` for the open item.

## What this can't see yet

- A government whose site loaded fine in the training/negative fetch
  but returned a family none of these rules recognise (WordPress with a
  generic theme, Drupal, Wix, a hand-built site, or a real vendor this
  round didn't happen to sample) stays `unknown`. That's the correct,
  honest answer for those pages — not every government's website is
  built by one of a handful of companies, and this table doesn't
  pretend otherwise.
- A page behind a 403 or a human-verification gate was skipped, per
  this repo's standing politeness rules — it was never fetched, so it
  isn't in the family-distribution numbers below.
- Nothing here has been wired into the resolver or the coverage sweep.
  This is a data file and a script; WO-155 is where it gets used.

## Where the numbers come from

`~/Documents/rtr-business/research/wo154_methods_section.md` has the
full methods write-up: how the training set was assembled, the exact
80/20 split numbers, the 300-government negative sample's family
distribution, and the 30-government (actually 20 real, see that
file — see the caution there) path-guessing test.

`~/Documents/rtr-business/research/wo176_methods_section.md` has the
own-domain path-and-feed pilot's write-up: the 600-government sample
(WO-154's own 238 usable rows plus a fresh random 362, both drawn from
the same no-platform-link pool), the generic sitemap-and-path/feed
list tried on every site, the family-specific extra paths for
ProudCity/WordPress/CivicLive/OpenCities, and the funnel from
"recognised family" through to a real page live on the Archive today.

`~/Documents/rtr-business/research/wo179_methods_section.md` has the
family-scale sweep's write-up: WordPress's `/?s=agenda` method run at
scale over the full `wo174_candidates.csv` population, and how the
GovOffice/Municipal Impact/state-hosted families above were learned
(10 real tenants each) and then applied to the rest of that population.

`~/Documents/rtr-business/research/wo197_report.csv` has the per-
government data behind WO-197's own feed-rate and CivicPlus video-rate
numbers above: the 2,471 WO-179 "listing found, no platform link"
governments, checked for direct video/audio and a working feed, one row
each, with the CMS family carried over from `wo179_report.csv`.
