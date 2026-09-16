# YouTube drip: government identity review

For whoever picks up the pages the drip feeds (`docs/YOUTUBE_DRIP_RUNBOOK.md`)
and keys them to the right government, the way the 2026-09-10/11 sweeps
did by hand. Plain language on purpose.

## What the drip does and does not do about identity

The drip **does not** decide which government a video belongs to, and it
**never writes a pin**. When its feed lane turns a queue line into a site
page, the Archive keys the page at ingest through the normal identity
ladder (`app/utils/gov_registry/resolve_government()`: pinned → name
repair → national table → registry → mint → blank; see
`docs/COVERAGE_HANDOVER.md` §3), using the pins that are **deployed** at
that moment. Every page then carries a confidence tier in
`jurisdiction_confidence`:

| Tier | Meaning | Needs a human? |
|---|---|---|
| `registry`, `pinned`, `manual_override` | keyed with real evidence | no |
| anything else, a blank `gov_id`, or a minted `rtr:` id | the ladder guessed, or declined | **yes** |

That rule is `needs_identity_review()` in `scripts/youtube_drip.py`, and
it mirrors `archive/db/crud._GOV_EVIDENCE_TIERS`.

## Where to look

Every page the feed lane creates gets one row in
`~/.rtr/youtube_drip/fed_pages.csv` on the Mac running the drip:

| Column | What it is |
|---|---|
| `fed_at` | when the page was created |
| `slug`, `page_url` | the site page (`/m/<slug>`) |
| `queue_url`, `source_url` | the video, and the government page it was found on (blank or a channel URL when the queue line had none) |
| `gov_id`, `jurisdiction`, `jurisdiction_confidence` | what the Archive keyed it to, and how sure |
| `video_channel`, `video_channel_id` | the YouTube channel that published the video |
| `needs_review` | `yes` when the tier is not evidence-backed |

`title` and `looks_like_meeting` are the off-mission check: the flag is
`no` when the title has no council/commission/board/meeting word (the
same word list WO-191's review used). A `no` is a page to open and,
usually, delete — the drip cannot tell a courthouse-anniversary video
from a council meeting; the queue probe only checks duration, date and
size.

`daily_status.csv` counts `fed_needs_review` and `dead_videos` per day,
so the size of the review pile is visible without opening the files.

## Dead videos: `dead_videos.csv`

When a page's video turns out removed or private (the captions lane), or
a queue line's video is dead (the feed lane's probe), the drip does what
the 2026-09-11 channel probe did by hand, minus the judgment: it reads
the government's own source page for a YouTube channel link (CivicWeb,
eScribe and CivicClerk pages carry one in the footer; a bare YouTube
source has nothing to read), lists that channel's three newest streams
(one YouTube request), and writes one row per candidate to
`~/.rtr/youtube_drip/dead_videos.csv`:

| Column | What it is |
|---|---|
| `slug`, `source_url`, `video_url`, `reason` | the dead page or queue line and why |
| `channel_url` | the channel found on the source page, or blank |
| `candidate_video_id`, `candidate_title` | the channel's newest streams, one per row |

A reviewer picks the candidate that is a governing-body meeting (see
step 1 above — the drip does not choose), adds it to
`scripts/tier3_auto_transcription_queue.txt` as
`https://www.youtube.com/watch?v=<id><TAB><source_url>`, and the feed
lane takes it from there. Tonight's probe found the channel alive in 18
of 24 governments, so this file is mostly good news. Blank
`channel_url` rows are the ones that need a name search by hand.

## How to review a row (the practice the agents used on 2026-09-10/11)

1. **Confirm the government from the channel, not the title.** Open the
   channel (`video_channel_id`) and read its name and its other videos.
   A channel that posts "City Council Meeting - <date>" for one named city
   is that city. WO-191 found about 1 in 10 "meeting" videos on government
   channels were school boards, state agencies, commissions or ceremonies —
   those are not the government's governing body and are `off-mission`.
2. **Check the source page when there is one.** A CivicWeb/eScribe/CivicClerk
   `source_url` names its own government (and usually links the channel
   in its footer). A bare channel `source_url` means the queue line came
   from a channel probe; the channel is the only evidence.
3. **Check what this repo already knows.** The national tables in
   `app/utils/jurisdiction_data/` (`us_places.csv`, `us_counties.csv`,
   `ca_csd.csv`, …) give the `gov_id` for a name-plus-state; existing
   pins for the channel are in `tenant_overrides.csv` (`grep <channel>`);
   the site's own pages for that government are at
   `/j/<gov slug>`. The research file `jurisdiction_coverage.csv` and the
   coverage registry live in `rtr-business` on Ryan's Mac only — not on
   GitHub — so a reviewer on another machine works without them and
   notes anything that needs that file for Ryan. Two real traps from
   2026-09-11: a Canadian municipality keyed to a same-named US place
   (Severn ON → "Severn Township, ND"; Prince Edward County ON → "…, VA"),
   and a county name shared by two states (Walton County FL/GA — left
   unkeyed because the page did not say which).
4. **Decide**: right government → pin; not a governing-body meeting →
   delete; genuinely unsure → leave it for Ryan with a note.

## How to key it

Pins live in `app/utils/jurisdiction_data/tenant_overrides.csv`
(`tenant_host,match,gov_id,strength,source,evidence`). Two shapes work
for YouTube:

- **Per video** — `www.youtube.com,<11-char video id>,<gov_id>,fallback,<source tag>,"<evidence>"`.
  Used for one page. Example from WO-195:
  `www.youtube.com,4pdLtlcWSf0,ca:csd:3543015,fallback,wo195_channel_probe,"Severn, ON (YouTube channel UCzhcoASavyb3nVr4jxzx8vA, linked from severn.civicweb.net) -- ca_csd.csv Severn"`
- **Per channel (the default)** — `www.youtube.com,channel=@TownofWoodside,<gov_id>,...`.
  Fires for every page that channel published, now and later; the
  handle comes from `fed_pages.csv`'s `video_channel` column. **Until the
  deploy that carries WO-244 (2026-09-11) the Archive stored no channel
  on any YouTube page** — the adapter's metadata dict dropped the keys —
  so `fed_pages.csv`'s column is blank for those pages and a `channel=`
  pin fired for none of them; from that deploy on, ingest stores the
  handle and the pin fires on every future upload. A confirmed channel
  pin therefore keys the government's future meetings (its archived
  videos get per-video pins from the sheet), so write this one **only
  when the channel's own name says
  this government AND this government's type** — city vs county vs
  township vs village. The 2026-09-11 backfill review found 13 pins
  where the name matched and the type did not (a "Town of X" channel
  pinned to X city). A community-TV, county or school channel that
  carries a town's meetings gets per-video pins only, never a channel
  pin (WO-237, the conductor's rule).

The evidence line is one sentence a stranger can check: the government,
the channel, and where the link between them was seen. Use a `source`
tag naming the work (`wo203_drip_review`), the same way every sweep did.

Or use the sheet: `python scripts/build_pin_worklist.py` regenerates
`reports/pin_worklist.csv` with every unresolved page grouped by tenant
and channel, with a proposal where a cheap signal is the government's
own name; Ryan writes a name, "ok" or "skip" per row and
`scripts/apply_pin_worklist.py` writes the pins. Drip-fed pages appear
there automatically — this document only adds the drip's own per-page
file, which carries the `source_url` the sheet does not. On a YouTube
row, add "own channel" to `ryan_note` when the channel is the
government's own; the apply then writes the `channel=` pin as well as
the per-video ones (WO-244). As of WO-243, `apply_pin_worklist.py` can
also mint a brand-new government straight through a shared host: an
"ok mint" row with a per-video match (never a bare channel handle) now
writes the curated row and the per-video pin itself, the same shape
WO-220/WO-237 previously had to write by hand.

## What happens after a pin

A pin reaches **new** ingests only after the next deploy (pins are a data
file inside the image; deploys are manual — CLAUDE.md). Pages already
keyed wrong are moved by `scripts/backfill_gov_id.py`, run from the
Archive's Render shell after that deploy (dry run, apply, apply again
for the tier-only residue, third dry run must be zero —
`docs/COVERAGE_HANDOVER.md` §3). Retired hub slugs need rows in
`archive/data/hub_slug_aliases.csv` or they 404.

Deleting an off-mission page: `POST /internal/admin/delete-pages` (dry
run by default; `apply_pin_worklist.py --apply-deletes` does it from a
`DELETE` note on the sheet). Deletion cascades and is not undone by a
revert, so it stays a separate, explicit step.

## When the same channel keeps coming up

Three or more drip rows from one channel with `needs_review=yes` is the
signal to write a **channel** pin rather than three video pins. The
`video_channel_id` column makes that grouping a one-line sort.
