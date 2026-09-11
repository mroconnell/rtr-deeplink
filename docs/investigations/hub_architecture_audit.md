# Hub architecture audit: how `/j/*` and `/state/*` include and exclude meetings and governments

**Status: closed, one-time audit (WO-232, 2026-09-11).** Ryan asked,
verbatim: "we are constantly messing with hubs and redirects after pin
work. The hubs were designed before any of the gov id work or pinning.
Should we audit the architecture of the hubs and permanently improve how
they include or exclude meetings and govs?" This is that audit: a
read-only measurement of today's architecture, plus a proposed permanent
model. No code changed in this work order — see `BACKLOG.md`'s `[HUMAN]`
entry "Hub identity: freeze slugs to gov_id (decision)" for the decision
this hands to Ryan, and `docs/COVERAGE_HANDOVER.md` §3 / `STATE_HUB_PAGES.md`
for the standing background this builds on.

**Data source.** A fresh pull of `GET /internal/export/pages` against
production, 2026-09-11, no segments: **8,222 pages**. All counts below
are computed by importing `archive/db/crud.py`'s real `_hub_identity()`
function directly against that export — not a reimplementation — so
these numbers are what today's code actually does, not an approximation
of it. The one approximation: the export doesn't carry the exact
`_is_empty_page_condition()` flag a live `/j/` render checks (it needs a
DB session to compute), so "hub-eligible" below is approximated as
"`jurisdiction` is set and `platform != 'unknown'`" — 8,031 of 8,222
pages. That's the same two of three real conditions `_hub_base_conditions()`
checks; the missing one (empty-page exclusion) only removes pages with no
transcript/agenda at all, which is orthogonal to identity.

---

## 1. What a hub is keyed on today, and the two code paths

**Keyed on `gov_id`, with the slug *derived live* from either the
government registry or a raw text fallback — never stored, never
frozen.** Two functions do all of the work:

**Page → hub URL** (`archive/db/crud.py:_hub_identity(gov_id, jurisdiction)`,
called from `hub_slug_for_page()` for `/m/{slug}` pages and from
`_hub_groups()` for the `/j/{slug}` page itself):

1. **Case 1 — `gov_id` has a registry row.** The slug is
   `app.utils.gov_registry.display.hub_slug(gov)` = `slugify(display_name(gov))`,
   computed **fresh on every call** from the registry's current name,
   type and state for that `gov_id`. Two pages spelled differently
   ("County of Fresno, CA" / "Fresno County, CA") land on the same slug
   because both look up the same `gov_id` and get the same live answer.
   The page's own stored `jurisdiction` string is not consulted at all
   in this case.
2. **Case 2 — `gov_id` set, no registry row** (a freshly minted `rtr:`
   id `governments.csv` hasn't been re-scored to include yet). Falls
   through to the same code as case 3.
3. **Case 3 — no usable `gov_id`** (blank, or `rtr:unknown:<host>`, which
   is explicitly excluded from "known" so it never gets a registry
   lookup even though a placeholder registry row exists for it). The
   slug is `archive/utils/jurisdiction_format.jurisdiction_hub_slug(jurisdiction)`
   — slugify of the page's own **raw stored jurisdiction text**, no
   registry involved.

**Hub URL → page list** (`archive/db/crud.py:_hub_groups()` /
`_hub_page_condition()`, behind `GET /j/{slug}`): one SQL `GROUP BY
gov_id, gov_type, jurisdiction` over hub-eligible pages, then each row
run back through `_hub_identity()` to get its slug, grouped by that slug.
A hub's page-membership condition is **two arms**: `gov_id IN
(this group's gov_ids)` **OR** (`gov_id IS NULL AND jurisdiction IN
(this group's raw jurisdiction strings)`). The second arm is a deliberate
design choice, documented in the code, to let an un-keyed page still
join a hub by matching raw text during a partial backfill — and it is
also the mechanism that lets an unrelated un-keyed or `rtr:unknown` page
ride onto a real government's hub by text coincidence (§2 below).

**Where the two paths disagree.** They can't disagree for a case-1 page,
by construction — the slug is computed from the registry both times. They
disagree, structurally, for cases 2/3: a minted or unresolved page's slug
is a **function of its own raw text**, which is exactly what changes
underneath it the moment the government gets a registry row, a rename, a
merge, or a human override — and *nothing* re-slugs the page automatically
when that happens. `hub_slug_aliases.csv` is a **generated snapshot**,
written by hand or by a scoring/backfill script's own report, not a live
index — so a slug that changes between snapshots 404s until someone
notices and adds a row.

---

## 2. Measured, from the fresh export (8,222 pages)

### Identity state

| What | Count of 8,222 |
| --- | --- |
| `gov_id` blank | 198 |
| `gov_id` = `rtr:unknown:<host>` (no hub, per §1 case 3, unless raw jurisdiction text happens to be non-empty) | 220 |
| `gov_id` real, **with** a registry row (case 1 — slug always current, by construction) | 6,127 |
| `gov_id` real, **no** registry row yet (case 2 — minted, slug = raw text fallback) | 1,677 |
| `jurisdiction_confidence = manual_override` (a human already decided) | 385 |

**Pages whose hub slug does not match what the registry would derive for
their `gov_id`: 0, and that's structural, not good news.** A case-1 page
cannot disagree with the registry — the slug *is* a registry lookup, run
fresh every time. The 1,677 case-2 pages have no registry-derived slug to
compare against yet (that's the whole problem — see §4). So this
question, asked literally, returns zero every time it's asked, on any
day, regardless of how much churn is really happening — which is exactly
why churn shows up as *retroactive* pain (a slug moves out from under an
already-published, already-indexed, already-linked page) rather than as
anything a same-day check would ever catch.

### Splits, mixes, and aliases

| What | Count |
| --- | --- |
| Distinct live `/j/` hub slugs today | 4,403 |
| `hub_slug_aliases.csv` rows (old_slug → new_slug) | 829 |
| ...of which the old slug has **zero** live pages today (pure retired redirect) | 804 |
| ...of which the old slug **still has live pages today** (both old and new slug currently resolve to real content) | 25 |
| Distinct governments (by `gov_id` in the alias file) with at least one retired alias | 784 |
| Hubs mixing **2+ distinct real `gov_id`s** on one slug today | 5 (11 pages) |
| ...of which: a minted `rtr:` id and a national `us:`/`ca:` id for what looks like the same real government, coincidentally slugifying the same | 3 hubs, 6 pages |
| ...of which: two genuinely different real governments that legitimately share a display name (Yarmouth County, NS vs. the Municipality of Yarmouth, NS) | 1 hub, 3 pages |
| ...of which: two different minted, not-yet-scored subdivisions (Lunenburg, NS) coincidentally sharing a slug | 1 hub, 2 pages |
| Hubs where a real, keyed government's slug also carries an `rtr:unknown:<host>` page (contamination by text-match coincidence) | 4 hubs, 47 pages (Orem UT 15, Tooele UT 20, Box Elder County UT 10, Caledonia Township MI 2) |
| Hubs mixing a keyed `gov_id` with a blank-`gov_id` page | 1 |

**Governments (by `gov_id`) whose OWN pages split across more than one
slug**, if the `gov_id` in question is real, happens **0 times** — only
the `rtr:unknown:<host>` placeholder ids show up here, and that's a
labeling artifact of grouping by `gov_id`: `rtr:unknown:youtube.com` is
not one government, it's ~59 different real, not-yet-pinned towns and
counties that all share the placeholder id and get scattered across their
own raw-text slugs. That scatter is arguably *better* than one merged
"unknown" bucket for these specific pages (a reader who lands on
`/j/town-of-webster` from a search result sees something plausible), but
it also means the placeholder id is silently doing double duty as both
"no government" and "a filing key that fragments by whatever text
happened to be on the page," which is not documented anywhere as
intentional.

### The unknown bucket, by host (question 6)

220 pages carry `gov_id = rtr:unknown:<host>` today. 126 distinct hosts.
Top 20:

| Host | Pages |
| --- | --- |
| www.youtube.com | 23 |
| youtu.be | 18 |
| vimeo.com | 10 |
| youtube.com | 8 |
| townhallstreams.com | 4 |
| edina-mn.cablecast.tv | 3 |
| hamiltonwenham.cablecast.tv | 3 |
| pcc.cablecast.tv | 3 |
| dakotamediaaccess.cablecast.tv | 3 |
| stcharles-mo.cablecast.tv | 3 |
| trojanvision.cablecast.tv | 3 |
| utvs.cablecast.tv | 3 |
| wilson-co-schools.cablecast.tv | 3 |
| cloud.castus.tv | 3 |
| player.vimeo.com | 3 |
| coppellisd.new.swagit.com | 2 |
| pelhampublicschoolsny.new.swagit.com | 2 |
| wbrw.cablecast.tv | 2 |
| gastoncoschools.cablecast.tv | 2 |
| hometown.cablecast.tv | 2 |

**Shape of the bucket**: 59 of 220 (27%) are on the four confirmed
multi-government hosts (`youtube.com`/`www.youtube.com`/`youtu.be`/
`vimeo.com`/`player.vimeo.com`) — these need a per-video or per-channel
pin, by WO-210's rule, and can never be safely bulk-assigned by host.
The other 161 (73%) are almost all single-government Cablecast/Swagit/
Castus hosts with 1-3 pages each — these are the cheap ones: a host with
exactly one government's worth of unknown pages and no ambiguity is a
same-day pin away from being fully keyed (§5's inclusion rule targets
exactly this set: 20 blank-`gov_id` pages and 11 `rtr:unknown` pages sit
on a host that already has exactly one real, keyed government — see
§5).

---

## 3. What each identity operation does to hubs

| Operation | Hub effect | Alias written automatically? |
| --- | --- | --- |
| Ingest **with** `gov_id` in the payload (`caller_gov_id`) | Ladder is skipped entirely (`_caller_pinned_match`). If the id has a registry row, the page lands on the current live slug immediately — no churn. If it's a fresh mint with no registry row yet, the page's slug is the raw-text fallback until the next scoring run adds it. | No |
| Ingest **without** `gov_id` | Resolver ladder runs (pinned → name repair → national table → mint → blank). Lands on a live registry slug (pinned/registry tiers), a raw-text fallback slug (inferred/unverified/mint), or no hub at all (unresolved/blank, or `rtr:unknown:<host>` with empty jurisdiction). | No |
| Worker re-resolve (transcription finishes, idle-time re-resolve) | Same `_find_or_create_page()` path as ingest. A page that gains a pin between its first ingest and this re-resolve gets a **new** slug — the old slug is now orphaned unless something adds an alias. WO-215's guard prevents this from ever *downgrading* an already-real gov_id to unknown, but it does not protect against a legitimate upgrade silently orphaning the old slug. | No |
| `POST /internal/jurisdiction/override` | Sets `gov_id`/`gov_type`/`jurisdiction` from the registry row directly, tier becomes `manual_override`. The page's own slug changes immediately (live-derived). Also appends a **pending** `tenant_overrides.csv`-shaped rule to a separate review file, for a human to promote later — it does not touch `hub_slug_aliases.csv`. | No |
| `scripts/backfill_gov_id.py --apply` | Rewrites `gov_id`/`gov_type`/`jurisdiction` for every row the ladder disagrees with. Tracks `old_hub`/`new_hub` **in its own printed/CSV report only** (`hub_moves` Counter) — this is the single richest source of "what would need an alias," but nothing consumes that report automatically. | No — a human reads the report and writes rows by hand (WO-209: 64 of 70 hub-changing re-keys got one; 6 deliberately didn't, because the old slug already belonged to a different live government). |
| Pin merge + deploy (`tenant_overrides.csv` change ships) | Affects **new** ingests and re-resolves only. An already-archived page keeps its old identity/slug until something re-resolves it (a backfill run, or the worker touching it again). | N/A (no page changes yet) |
| Curated-government mint (`curated_governments.csv`, "ok mint") | New `rtr:` id, case 2 until the next scoring run: hub keys off raw jurisdiction text. Once scored, `hub_slug(gov)` may compute a different string than the ad hoc fallback did, silently retiring the interim slug. | Only if a human notices and adds one after the next scoring run. |
| Consolidated-government mapping (e.g., a Census correction, an LSAD fix) | Same as a rename: `display_name(gov)` recomputes, `hub_slug(gov)` changes, every page under that `gov_id` moves at once (this is the intended behavior — it's what collapses spelling variants into one hub) — but the *old* slug for that government needs an alias or it 404s. | Only via a scoring-script regeneration (`scripts/score_gov_registry.py`), which is a wholesale rewrite, not additive — see `archive/utils/hub_aliases.py`'s own docstring. |

**The one-line summary**: every operation that changes what a `gov_id`
resolves to, or gives a page a `gov_id` it didn't have, can move that
page's slug — and **none of them writes the alias that keeps the old URL
alive.** That step is manual, ad hoc, and has already been skipped
on purpose at least 6 times (WO-209) for good reasons (the old slug
belongs to someone else) that a human had to work out case by case.

---

## 4. The design question: `gov_id` as identity, slug frozen once

**Proposal**: give every government one `hub_slug`, minted once (from
the registry's naming rules, exactly as `hub_slug(gov)` computes it
today) and stored as a column on the government registry itself (or a
`hub_slugs` table keyed by `gov_id`), never recomputed from a page and
never recomputed from a rename. A page's hub is a pure `gov_id` lookup
against that column. A rename, a Census correction, an override, or a
scoring pass changes the government's *display name*, never its *slug*
— the URL is a permanent handle, the way `us:place:0627000` already is.

### What disappears

- **All of §2's "hubs mixing a minted id with a national id" (3 hubs)**
  and **"two coincidentally-matching minted subdivisions" (1 hub)** —
  these exist only because two different `gov_id`s currently compute the
  same slug by accident of text; a frozen, explicitly-assigned slug per
  `gov_id` has no accident to have.
- **Every alias needed for a rename, a merge, or an override** (the 793
  live "retired slug" cases in `hub_slug_aliases.csv`, and the 64 WO-209
  added in one afternoon) — a page's slug never depends on the
  government's current name, so a name correction has nothing to move.
- **The "does an alias exist for this new slug" review step** in every
  future `backfill_gov_id.py --apply` and `POST /internal/jurisdiction/
  override` — since gov_id-driven pages already carry a permanent slug,
  those operations still change the *government a page belongs to*, but
  never the *URL of the hub it lands on*.

### What remains (this proposal does not fix)

- **Genuine renames of the slug itself** — if Ryan or a scoring pass
  decides an existing frozen slug was wrong (a typo, a bad LSAD
  disambiguator) it still needs one alias row, same mechanism as today,
  just far rarer (once per correction instead of once per registry
  refresh).
- **Merges of two `gov_id`s into one** (a Census correction folding a
  minted id into a newly-matched national one) still need a decision —
  which slug survives — and one alias row for the retired `gov_id`'s
  slug. This is the *same* operation as today's rename case, just scoped
  down to "only when two ids turn out to be one thing," not "every time
  a name recomputes."
- **The unknown-host bucket (§2/§6)** is untouched by this proposal —
  it's not a slug-computation problem, it's a "no `gov_id` at all yet"
  problem, and needs its own answer (§6 below).
- **The 5 real mixed-identity hubs found in §2** still need a human
  decision (merge the duplicate `gov_id`, or confirm two real
  governments legitimately share a hub) — freezing slugs stops *new*
  ones of this shape from appearing by coincidence, but doesn't
  retroactively resolve the 5 that already exist.

### Migration size, estimated from this export

- **4,403 live hub slugs today** would each need exactly one frozen slug
  minted — for the 6,127 case-1 pages, this is `hub_slug(gov)` computed
  once per distinct `gov_id` already in the registry (no behavior change
  for a reader — the URL comes out identical to what it is today,
  because the freeze is defined as "whatever the registry would compute
  right now").
- **1,677 case-2 pages** (minted, unscored) need their eventual
  registry-computed slug minted at mint time instead of left to compute
  ad hoc — this is the step that would have prevented all 4 of §2's
  minted-vs-national collisions from ever forming.
- **829 existing `hub_slug_aliases.csv` rows** carry forward unchanged —
  they're already exactly the right shape (`old_slug → new_slug`) for a
  frozen-slug world; nothing about them needs to change, they just stop
  growing at the rate they have been.
- **One column, one migration**: `hub_slug TEXT` on the government
  registry (or a new one-row-per-`gov_id` table if the registry itself
  is a CSV rather than a DB table — worth checking which before
  building). A backfill populates it once, from exactly today's
  `hub_slug(gov)` output, so day one of the freeze changes zero live
  URLs.
- **Risk is low and mostly procedural**: the frozen slug is defined to
  match current output exactly at freeze time, so there's no reader-
  visible change on cutover day. The real risk is process, not data —
  making sure every future mint/override/backfill path writes to the new
  column instead of leaving it to `_hub_identity()`'s live computation,
  and that a genuine rename still goes through the one-alias-row
  discipline rather than being treated as "just edit the registry file."

---

## 5. Inclusion/exclusion rule set

**Proposed rule**: a hub shows exactly:

1. every page keyed to its own `gov_id`;
2. every page keyed to a `gov_id` the registry maps to it (a consolidated
   or child government — Baltimore's city/county forms, Athens-Clarke);
3. every page a human has explicitly overridden onto it
   (`manual_override`, already true today via case 1 — no change);
4. an un-keyed page **only** when it shares a tenant **host** with an
   already-keyed page for this government, and that host is not a
   `MULTI_GOV_HOSTS` host (YouTube, Vimeo, ClerkHQ, ...) — never by raw
   text match alone.

This replaces today's second inclusion arm (`gov_id IS NULL AND
jurisdiction IN (...)`, a **text** match) with a **host** match, which is
the same kind of evidence WO-210/214/215/221 already established as the
trustworthy signal for shared-host identity, and it explains §2's
contamination cases directly: Orem, Tooele, Box Elder County and
Caledonia Township's `rtr:unknown` pages rode onto a real hub because
their raw jurisdiction text happened to match — a host-based rule asks
"does this un-keyed page's video live on the same tenant as an
already-identified page for this government," a strictly stronger and
less coincidental question, while still excluding a shared multi-gov
host as WO-210 requires.

**How many pages change hubs under it, measured against the export**:

| Pool | Count | What happens under the proposed rule |
| --- | --- | --- |
| Blank-`gov_id` pages total | 198 | — |
| ...on a single-government host (gains a real hub) | 20 | Moves onto that host's one government's hub |
| ...on a `MULTI_GOV_HOSTS` host (stays unkeyed, needs a per-video pin) | 5 | No change — correctly excluded |
| `rtr:unknown` pages total | 220 | — |
| ...on a single-government host (gains a real hub) | 11 | Moves onto that host's one government's hub |
| ...on a `MULTI_GOV_HOSTS` host (stays unkeyed, needs a per-video pin) | 59 | No change — correctly excluded |
| Today's 4 contamination hubs (§2) | 47 pages | The `rtr:unknown` pages in each stop riding along on a raw-text match (they're on the multi-gov `youtube.com`/`youtu.be` host, so they're correctly excluded under the host rule rather than incorrectly included under today's text rule) |

**Net measured effect: 31 pages gain a real hub they don't have today**
(20 + 11), and the 4 existing contamination hubs stop showing unrelated
unkeyed video alongside their real content, with zero new ambiguity
introduced (every included page's host maps to exactly one government).

---

## 6. The unknown bucket: what should happen to `rtr:unknown:<host>` pages

Three options, measured against the 220-page/126-host reality in §2:

**A. A per-host holding hub** (`/j/unidentified-<host>` or similar,
noindexed). Groups the 126 hosts' worth of pages by host, which is
exactly the axis a human fixing this works from (§2's table is already
organized this way). Cheap to build — `_hub_groups()` already computes
almost this shape for `rtr:unknown:<host>` ids, it just currently falls
through to the raw-text fallback instead of a host-keyed one. Downside:
126 thin, near-duplicate noindexed pages, all saying roughly "we don't
know whose meeting this is yet" — exactly the thin-content pattern
`STATE_HUB_PAGES.md` §1 diagnosed Google penalizing hubs for in the first
place, so this only makes sense noindexed.

**B. A single site-wide "unidentified" list.** One page, 220 rows, easy
to scan by a human doing exactly the identity-fixing work this file
documents. Loses the per-host grouping a fixer actually wants (they work
host by host, per §2/§3's evidence), so it's a worse *tool* even though
it's a smaller surface.

**C. Hidden until keyed** (today's actual behavior for the 161 non-multi-
gov-host pages that have no raw jurisdiction text to fall back on, and
for all `rtr:unknown` pages with a blank jurisdiction). Zero thin-content
risk, zero reader-visible confusion — but also zero visibility for the
person doing the identity work, who currently has to run a script against
the export (as this audit did) to even see the list.

**Recommendation: A, restricted to internal/noindexed use** — a per-host
page behind the same `/internal/*` token gate as the rest of the identity
tooling (not a public, crawlable `/j/` page), replacing the ad hoc
"export and grep" step this audit and WO-209/210/214/215/221 each did by
hand. It directly serves the one real, repeated workflow (a human fixing
a host at a time) without adding any new public thin-content surface —
the reader-facing question (does a public page exist for this video at
all) stays "no" until a real `gov_id` exists, exactly as today.

---

## 7. Options for Ryan, and the recommendation

| Option | What it fixes | What it costs |
| --- | --- | --- |
| **Do nothing** | Nothing | Continues costing an alias-file review after every rename/override/backfill, indefinitely (793 governments already needed one) |
| **Freeze `hub_slug` to `gov_id` (§4) only** | Removes the recurring churn source (rename/backfill/override no longer move a page's URL) | One migration, one column, no reader-visible change on cutover |
| **Freeze + host-based inclusion rule (§4 + §5)** | Also fixes today's 4 contamination hubs and picks up 31 pages that could be keyed for free | Slightly more logic in `_hub_page_condition()`; well-precedented by WO-210's existing host-vs-text distinction |
| **+ an internal unknown-bucket view (§6)** | Removes the "export and grep" step every identity WO has repeated | A new `/internal/*` route, no schema change |

**Recommendation: do all three, in that order, as separate, small
changes** — the slug freeze is the one with the real leverage (it's the
thing "we keep messing with hubs and redirects after pin work" is
actually about), the inclusion-rule swap is a small, well-precedented
change riding on infrastructure WO-210 already built, and the
unknown-bucket view is pure tooling with no product risk. None of the
three depends on the others being done first, so they can ship and be
verified independently.

**The one decision Ryan needs to make** is whether to commit to the slug
freeze at all — once a slug is frozen, "fixing" a hub's naming
convention later always costs one alias row instead of being free, which
is a real, permanent trade for a churn source that mostly goes away. See
`BACKLOG.md`'s `[HUMAN]` entry for the decision framed on its own.
