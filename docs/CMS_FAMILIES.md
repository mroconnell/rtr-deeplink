# CMS families field guide (WO-154, 2026-09-10)

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

### Town Web

Recognise it from a `cdn.townweb.com` dns-prefetch link or a literal
`<meta name="author" content="Town Web | ...">` tag. Only 2 confirmed
training pages — too few to trust a meetings-page path pattern from,
and both of the pages found were livestream pages, not agenda listings.

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
