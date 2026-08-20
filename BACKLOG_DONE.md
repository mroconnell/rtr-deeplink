# Backlog — done

Completed items moved out of [BACKLOG.md](BACKLOG.md) to keep the live
document short. Kept verbatim (not summarized) because the investigation
detail — what was checked, on which real cities, what turned out to be a
non-issue vs. a real bug — is itself useful project memory, not just a
changelog of task titles.

## eScribe: second real iSiLIVE page shape (`data-file_name`, ISIStandAlonePlayer.aspx) now recognized; confirmed it does NOT explain any of the 154 "genuine negative" Meeting.aspx URLs [Done 2026-08-19]

`EscribeAssetFinder`'s video-player detection only ever matched
`#isi_player[data-client_id][data-stream_name]`. A real, second iSiLIVE
page shape exists that this selector missed entirely: standalone
`Players/ISIStandAlonePlayer.aspx?Id=<guid>` pages, whose `#isi_player`
div carries `data-file_name` instead of `data-stream_name`. Confirmed
live on 5 real Canadian tenants by fetching the real page HTML directly
(`curl`, no headless browser needed — same as the rest of this adapter):
Caledon, Mississauga, Markham, Victoria, Edmonton — e.g. Caledon's real
page (`pub-caledon.escribemeetings.com/Players/ISIStandAlonePlayer.aspx
?Id=74f36aec-87b7-4596-953d-f21174b1a13a`) renders `<div id="isi_player"
... data-client_id="caledon" data-file_name="Compact Encoder
1105_Planning and Development Committee_2026-06-16-02-28.mp4">`.

Fetched eScribe's own `//video.isilive.ca/cdn/isi_player.js` (the exact
script every `#isi_player` page loads) to confirm how `data-file_name`
should be turned into a URL, rather than guessing: it has a "legacy
support for file_name / stream_name" block (`if (typeof(file_name) !=
'undefined') { stream_name = file_name }`) that aliases `file_name`
straight into the same `stream_name` variable used everywhere else for
URL construction — i.e. `data-file_name` isn't a different pattern at
all, just an alternate attribute name for the identical value. Confirmed
this holds for real by fetching both `cdn1.isilive.ca`'s
`.../playlist.m3u8` and `video.isilive.ca`'s `.vtt` for Caledon's exact
`data-file_name` value using the adapter's existing (unchanged) URL
construction: both returned 200, and the `.vtt` had real, populated,
clean captions (a genuine positive-caption example for this page shape,
not just a schema match — see CLAUDE.md's "don't claim a caption path
works without a positive example" rule).

Fix: `resolve()`'s player selector now also matches
`#isi_player[data-client_id][data-file_name]` as a fallback when
`data-stream_name` isn't present, and `stream_name` is read from whichever
attribute exists (`player.get("data-stream_name") or
player["data-file_name"]`) — everything downstream (m3u8/vtt URL
construction, caption-language selection) is unchanged, since eScribe's
own JS treats them as the same value. Regression test added
(`tests/test_escribe.py::test_resolve_real_caledon_isistandaloneplayer_page`),
fixture-backed with the real Caledon page HTML (trimmed of unrelated
Google-tag/Cloudflare boilerplate, `#isi_player` div and script tags kept
verbatim) and the first 19 real caption cues from the real Caledon `.vtt`
fetched above (`tests/fixtures/escribe/
caledon_isistandaloneplayer_{page.html,captions.vtt}`). Also confirmed
this page shape carries no title/agenda markup at all (its own `<title>`
is empty) — title/date come back `None` and jurisdiction correctly falls
back to the subdomain (`Caledon, ON`), same as the existing "no video
integration" fallback path.

**Checked whether this explains any of the 154 eScribe URLs previously
classified "genuine negative" (real video_url absent, not just gate-blind)
out of the 186 in `~/Documents/rtr-business/research/
escribe_186_nothing_found.txt`** (see `full_escribe_dryrun.log` in the
same directory for the prior classification — 12/186 URLs re-checked here
already had a `data-stream_name` player match, closely matching that
prior "13 gate-blind" count, likely off-by-one from a since-changed
meeting Id). **It does not.** Re-fetched all 186 real pages directly and
checked both selectors: every single one is a `Meeting.aspx` URL (not an
`ISIStandAlonePlayer.aspx` URL), and of those, 0 had a `data-file_name`
player where the old `data-stream_name` selector found nothing — 174 had
no `#isi_player` element at all (still a genuine "no video integration"
outcome), 12 already had a `data-stream_name` match (already-known
gate-blind cases, unrelated to this fix). Separately confirmed on 5 real
tenants (the ones used to build the fix above) that a `Meeting.aspx` page
and its own linked `ISIStandAlonePlayer.aspx` page for the *same meeting
Id* consistently differ in exactly this way — the Meeting.aspx page always
renders `data-stream_name`, only the separate standalone player page ever
renders `data-file_name`. So `data-file_name` is real and worth handling
(someone submitting an `ISIStandAlonePlayer.aspx` URL directly — e.g. a
"share video" link, which these player pages sometimes rank on their own
in search engines — would have silently gotten a "no video" result before
this fix), but it is not the explanation for why those 154 Meeting.aspx
URLs have no video; that remains a genuine "no video integration for this
customer" outcome, not a hidden second bug. Full suite green (1029
passed, 15 skipped, in a clean `origin/main` worktree).

## No delete path existed for Archive MeetingPage rows; built one, used it to remove 3 real UAT tenant pages [Done 2026-08-19]

Real cleanup need: during the gate-blindness recheck below, 3 PrimeGov
vendor UAT/staging tenants (`uatlakeforest`, `uatopenspaceauthority`,
`uatsanmateo` -- test environments, not real government customers, each
serving stale 2021 sandbox content) got real-ingested into production
alongside 339 genuine recoveries, since the recheck script had no way to
distinguish a real tenant from a test one at the URL level.

Investigating how to remove them surfaced two real findings, not just the
cleanup itself:

1. **No delete mechanism existed for `MeetingPage` rows at all.**
   `archive/main.py` had exactly one delete-shaped route
   (`/internal/account/delete-data`, Clerk right-to-deletion only) and
   nothing for content. A first attempt to write a one-off DB script hit
   a real near-miss: the local root `.env`'s `DATABASE_URL` connects to
   `rtr_deeplink_db` (the **resolver's** database), not `rtr_archive`
   (the Archive's real database) -- confirmed by hostname/dbname
   inspection after the script failed with
   `UndefinedColumnError: meeting_pages.meeting_body does not exist`
   (an Archive-only column from a migration merged 2026-08-15, absent
   from `rtr_deeplink_db`'s stray un-migrated Archive-shaped tables --
   the exact same tables flagged in this file's "Stray demo-shaped
   tables found in `rtr_deeplink_db`" entry). No write was attempted
   before this was caught -- the query itself failed first. Confirms
   direct local Postgres access isn't a safe default tool here; the
   HTTP-API path (already this repo's established pattern for every
   other admin operation) is the one that actually reaches the real
   data.

2. Built the real fix instead: `crud.delete_meeting_pages_by_slug()` +
   `POST /internal/admin/delete-pages` (token-gated, `dry_run=true`
   default, slug-only -- never a fuzzy match, so a typo can't take out
   an unrelated real page), cascading through `TranscriptionJob` ->
   `TranscriptVersion` -> `MeetingPageUrlAlias` -> `SavedItem` before the
   `MeetingPage` row itself, since none of those foreign keys cascade at
   the DB level. Built and tested in an isolated `git worktree` (the
   shared checkout had unrelated real in-progress work from another
   session at the time -- see `CLAUDE.md`'s multi-session bullet), PR
   [#202](https://github.com/mroconnell/rtr-deeplink/pull/202), merged
   after CI passed (one ruff-format fixup round).

Used the new endpoint for real: found the 3 exact pages via
`GET /internal/pages/all-urls` (matched on `source_url_normalized`),
dry-run confirmed all 3, then deleted for real. Archive page count went
1887 -> 1884, confirmed 0 UAT matches remaining afterward. The endpoint
stays in place for any future cleanup of this kind -- not removed after
use.

## Archive-push gate silently dropped video-only resolves across 3 call sites [Done 2026-08-19]

Found while doing government-first platform discovery/ingest work (see
`~/Documents/rtr-business/research/ENUMERATION_METHODS.md` for the full
discovery methodology): `scripts/bulk_ingest.py`'s decision of whether a
resolve was "worth pushing" to the Archive checked only `result.segments
or result.agenda_items or result.agenda_link` — never `result.video_url`.
Several adapters can populate a real, playable `video_url` while all three
of those stay empty: Cablecast (`app/platforms/cablecast.py` always sets
`video_url=show["vodUrl"]` in the final `ResolvedMeeting`, but `segments`
stays `[]` whenever no `vod_transcripts` fetch succeeds, and
`agenda_items`/`agenda_link` are never set by this adapter at all), ChampDS
(same shape), and PrimeGov's YouTube-delegated path when the linked video
has zero captions. Confirmed live: re-resolving 78 URLs from a
"confirmed no video" list built by directly checking each Cablecast
tenant's page (not via bulk_ingest.py) found **all 78 had a real
`video_url` bulk_ingest.py's gate had been silently skipping** — every one
pushed successfully once the gate was bypassed
(`scripts/tier3_auto_transcription_queue.txt`'s established gate-bypass
pattern from `scripts/feed_tier3_auto_transcription.py`, generalized into
a one-off script for this recheck). The same recheck against PrimeGov's
38-URL "confirmed no video" list found 0 gate-blind cases — that list's
negatives were genuine, confirming the bug is real but not universal
across platforms.

The identical `segments or agenda_items or agenda_link` gate turned out to
exist in **three places**, not just the one-off script — meaning this bug
was also live in production, not just an internal tooling gap:
`app/main.py`'s live `/api/resolve` endpoint (the BackgroundTasks push
right after a user's request, line ~679), `app/main.py`'s Archive
re-check/backfill helper (`pushed = bool(...)`, line ~348), and
`app/db/crud.py`'s `_worth_pushing()` (the retry-sweep gate feeding
`get_pending_archive_pushes()`, consumed by the opportunistic sweep and
`GET /admin/sweep-pending-pushes`). Fixed all three by adding
`result.video_url` (or, in `crud.py`'s case, `payload.get("video_url")`,
since that function reads the JSON payload directly) to the condition.
Added a regression test
(`test_pending_pushes_includes_video_only_resolutions` in
`tests/test_app_db_crud.py`) alongside the existing agenda-only-resolution
test, and confirmed the full existing suite (1034 passed, 15 skipped)
still passes.

Not yet addressed: whether any *production* users hit this gap before
today (i.e. whether real video-only meetings resolved live via
`/api/resolve` before this fix ever got silently dropped from the
Archive) — no attempt made to retroactively find/backfill those, since
the population most likely to have hit this (Cablecast/ChampDS/PrimeGov
tenants) is exactly the population this session's own bulk re-ingest work
already covers going forward.

## Salvaged tier-1/tier-2 finds ingested; TelVue "ECTV" jurisdiction guess corrected from Scranton, PA to Everett, MA [Done 2026-08-18]

Prompted by checking whether any real, content-confirmed tier-1/tier-2
hosts from earlier investigation work had been left un-ingested. Three
were: Bedford, OH (PrimeGov→YouTube, 1,346 segments) and Peel Region, ON
(eScribe, 1,101 segments) had only ever been live-resolved to investigate
the jurisdiction-bleed bugs they surfaced (see BACKLOG.md's PrimeGov
`_JURISDICTION_RE` and eScribe two-tier-government entries), never
pushed; both ingested via `bulk_ingest.py` and land with the
already-documented wrong jurisdiction from those same bugs (Bedford →
"County of Cuyahoga, OH", Peel Region → "Town of Caledon, ON") — expected,
not a new issue.

The third, TelVue org token `cT30AQ_xtOBQF0oJM2gIVCDX9kjgfWZb`
(2,497-segment real transcript), was the one round-2 TelVue hit
deliberately held back in the original entry below because its
jurisdiction was only a nickname-match guess ("ECTV" → "Electric City
Television" → Scranton, PA) with no confirming .gov link. Re-investigated
via web search before ingesting, per that entry's own "worth a direct
attempt" note — **the guess was wrong**: the same org token's other
playlist entries include "ECTV Channel 3 Public Access Programs" (exact
match to Everett, MA's real public-access channel — cityofeverett.com
describes its own channel lineup as "Public Comcast (Channel 3)...
Government Comcast (Channel 22)", not Scranton's Channel 19) and
"Community Meeting on Stadium Development" (matches the real,
well-documented 2025 Everett, MA Kraft Group/New England Revolution
soccer-stadium community meetings). "ECTV" was an acronym collision
between two unrelated real organizations (Scranton's "Electric City
Television" and Everett, MA's "Everett Community Television"), not the
same one.

The held-back meeting's own title is a bare "City Council Meeting
11-27-23" (no city name at all — same shape as the Fitchburg bug in the
entry below), so `_guess_jurisdiction()`/`enrich_jurisdiction_text()`
correctly return `None` for it and can't be fixed by title parsing alone.
Added `_KNOWN_ORG_TOKEN_JURISDICTIONS`, a per-org-token map in
`app/platforms/telvue.py` (the "may need a real per-customer jurisdiction
map later" gap that file's own module comment already anticipated),
used as a fallback only when the existing guess/enrich chain returns
nothing — one confirmed entry (this token → "Everett, MA"), not a
speculative table. Regression tests added
(`tests/test_telvue.py::test_resolve_falls_back_to_known_org_token_jurisdiction`,
`::test_resolve_unknown_org_token_has_no_jurisdiction`). Re-ingested after
the fix; confirmed live on the public page (jurisdiction now reads
"Everett, MA" — slug unchanged, `city-council-meeting-11-27-23`, same
"slugs don't regenerate on re-ingest" tradeoff as Fitchburg). Full suite
green (1027 passed, 15 skipped).

**The other 5 untested tokens, tested same session**: found a real media
ID for each via web search (same "quote the token" method), live-resolved
each. One genuinely new real captioned jurisdiction: **Natick, MA**
(`994DtmGEsi0VDYK3jJI2BJ72GfgNIpU2`, "Natick Select Board June 10, 2026",
**3,865 real segments** — confirmed via dry-run then ingested for real,
`/m/natick-natick-select-board-june-10-2026`). Surfaced a second real
jurisdiction-guess bug fixing this one: the title has no dash-separated
date (unlike Fitchburg/Ashland's shape), so `_guess_jurisdiction()` runs
against the whole string including the date -- the bare `Board`
alternative in `_BODY_SUFFIX_RE` matched before the two-word `Select
Board`, producing "Natick Select" instead of "Natick". Fixed by adding
`Select Board` as its own alternative ahead of bare `Board` (position, not
alternation order, is what makes it win -- see the regex's own comment).
Regression test added
(`tests/test_telvue.py::test_guess_jurisdiction_handles_select_board`).

Three more tokens got a real jurisdiction identified via search but no
captions yet on the one real page tested for each -- correctly left
un-ingested, same as Multnomah County/Emmett Township above:
**Warren Township, NJ** (`GBRlyEOJkXtkfSrhIDK-uv2PonrUwFBn`, "Warren
Township Committee Meeting December 11, 2025", real page, 0 segments) and
**Rochester** -- city unconfirmed among NH/NY/MN, "Rochester Government
Channel" (`dQtoDvlZYDOtqaf7eRn9z2lb1Nb6EZzu`, "Planning Board - 6/3/24",
real page, 0 segments). One token (`AbfNhigIqnG-4roGCxaFupXEKfme9dfT`)
and the **Kalamazoo, MI** token (`2bm0gzQWeVRzdCgvjXziXKwO3icSKh05`) both
had every search-surfaced media ID come back "no video found" on live
resolve (likely stale/removed content, not a real adapter gap) -- neither
confirmed real or dead conclusively; would need a fresher media ID to
settle either way.

Full suite green throughout (1028 passed, 15 skipped after the Select
Board fix).

## Cablecast/Swagit/CivicClerk stage-2 seeks, full-set real-content check: 180 confirmed real captioned jurisdictions [Done 2026-08-17]

**Landed straight into this file instead of updating its own still-open
`BACKLOG.md` entry, 2026-08-18 — explained below.** This entry's content
comes from [PR #111](https://github.com/mroconnell/rtr-deeplink/pull/111)
("Extend Cablecast/Swagit/CivicClerk real-content check to full sets: 180
real"), opened 2026-08-17 and never merged: `origin/main` moved enough by
2026-08-18 (heavy tier-3 queue churn from the scheduled feed workflows,
plus a full day of other unrelated work) that the PR's
`scripts/tier3_auto_transcription_queue.txt` diff hit a real merge
conflict. Rather than resolve a diff against a queue file that's already
been rewritten several times since, this records the PR's real,
already-true finding directly here — the underlying data work (180 real
ingests) happened for real on 2026-08-17 regardless of whether this PR's
paperwork ever merges, confirmed by checking that `BACKLOG.md`'s own
existing in-place entry on this topic still shows the old, stale "25
confirmed real" number from the original 44/30/30 sample pass, meaning
this update was never actually recorded anywhere until now.

**The real finding**: extended the sample-based real-content check
(44/30/30 URLs) to the full 728-candidate set across all three
platforms. Final tally: **180 confirmed real captioned jurisdictions,
all ingested for real** — Cablecast 2/44, Swagit 139/430, CivicClerk
39/254. Worth remembering: the original 30-URL samples overestimated
real yield, especially for CivicClerk (37% sample rate vs. 15% on the
full set) and Swagit (40% vs. 32%) — a small sample isn't a reliable
stand-in for the full set on this kind of check. The remaining 548
(video-with-no-captions, or nothing found) went to
`scripts/tier3_auto_transcription_queue.txt` for the existing cron
feeder to resolve and push at pickup time, rather than re-checking each
one by hand first.

**Real bug fixed along the way**: `hosts_to_urls.py` (lives in
`rtr-business/research/`, not this repo) used a shared single-thread
executor meant to bound a per-call DNS-hang, but one real hang instead
silently wedged every host queued after it for the rest of the run —
fixed to use a fresh one-shot executor per call.

## TelVue round 2: 12 org tokens found via web search, 4 more real captioned jurisdictions ingested [Done 2026-08-17]

**Same situation as the entry immediately above — landed straight into
this file instead of updating its own still-open `BACKLOG.md` entry,
2026-08-18.** This entry's content comes from
[PR #100](https://github.com/mroconnell/rtr-deeplink/pull/100) ("Backlog:
TelVue round-2 web search finds 4 real captioned jurisdictions"), opened
2026-08-17 and never merged: its `BACKLOG.md` diff hit a real conflict
against other backlog entries that landed nearby since. Same reasoning
applies — checked that `BACKLOG.md`'s own existing in-place TelVue entry
still shows the old "Fitchburg, MA (FATV), 956 real transcript segments"
phrasing from the first round only, confirming this round-2 update was
never actually recorded anywhere until now, even though the real
ingests it describes already happened.

**The real finding**: a second round of the web-search-first method
(the one validated on Legistar the same night as the original TelVue
entry) found 12 real org tokens total across two rounds of searching, 4
of which turned into genuinely new real captioned jurisdictions, all
ingested for real: Fitchburg, MA (FATV, 956 segments, 22 agenda items),
Bellefonte Borough, PA (2 separate meetings, 397/1,635 segments), and
State College Borough, PA (2,365 segments) — the latter three all came
from one org token that turned out to cover multiple distinct PA
jurisdictions (Centre County area) via different playlist IDs, a real
structural finding of its own. One more real hit (2,497 segments) was
deliberately **not** ingested — its jurisdiction is only a
nickname-match guess ("ECTV" → likely Scranton, PA, from "Electric City"
being Scranton's real nickname) with no direct linking .gov page
confirming it, so it was held back rather than guessed. Full
token-by-token table with confidence levels in
`~/Documents/rtr-business/research/telvue_org_tokens.md` (outside this
repo).

**Still not done, same as before**: a systematic `hosts_telvue.txt` the
way Legistar's 19-host list exists now — the 12 tokens above came from
~4 total searches, not the same scale of effort, and the CDX-side
complications the original entry documented (200k-row cap, opaque
token, mixed path shapes) are still real and still unaddressed if
someone wants full coverage rather than a few more spot-checks.

## Queue-advance automation: switched to QUEUE_ADVANCE_PAT, fully unattended end-to-end for both workflows [Done 2026-08-18]

Closes out the saga this file's own next two entries below document in
full (PR #144's permission fix, PR #172's run-selection fix, and the
residual manual-approval gap they left behind). Picks up exactly where
that gap was found: this repo is public, and a `GITHUB_TOKEN`-authored
PR's `author_association` comes back `"CONTRIBUTOR"` rather than
`"OWNER"`/`"MEMBER"`, so its real `pull_request`-triggered `test.yml` run
sits stuck in `action_required` pending manual approval — and the `main`
ruleset's required `test` check only ever credits that genuine
`pull_request`-triggered run, never a `workflow_dispatch` stand-in.
Re-confirmed live immediately before starting this fix: the latest
scheduled run of each workflow (tier3 run 32175611160, granicus run
32173489932, both 2026-08-18) had failed at the exact same point —
`gh pr merge` rejected with `"the base branch policy prohibits the
merge"` — on every single automated run since PR #172 landed.

**Fix: `QUEUE_ADVANCE_PAT`, a fine-grained PAT scoped to `rtr-deeplink`
only (Contents + Pull requests read/write), added as a repo secret.
Expires 2026-10-17 — flagging that explicitly here since it will silently
break both workflows again around then if not rotated; a separate
scheduled reminder already exists for that date.** Both
`feed-tier3-transcription.yml` and `feed-granicus-transcription.yml`
(PR #176) now authenticate `actions/checkout@v4` and every `gh` CLI step
with this PAT instead of the default `GITHUB_TOKEN`. Landed with the
existing `workflow_dispatch` dispatch-and-poll workaround deliberately
left in place (not removed blindly) pending live proof the PAT actually
changes the ruleset outcome.

**Verified immediately, live**: manually triggered
`feed-tier3-transcription.yml`
(https://github.com/mroconnell/rtr-deeplink/actions/runs/32188416992).
The PAT-authenticated `checkout`/`gh pr create` steps worked and opened
PR #177 — but the in-workflow `gh workflow run test.yml --ref "$BRANCH"`
dispatch call itself failed: `HTTP 403: Resource not accessible by
personal access token` — `QUEUE_ADVANCE_PAT` doesn't carry the `actions:
write` scope that dispatch needs (a fine-grained PAT's available
permission list doesn't include one for triggering other workflow runs
the way a classic PAT with the `workflow` scope would). That turned out
not to matter: `gh api repos/mroconnell/rtr-deeplink/pulls/177` showed
`author_association: "OWNER"` (not `"CONTRIBUTOR"`) as predicted, its
natural `pull_request`-triggered `test.yml` run fired immediately with
**no approval gate**
(https://github.com/mroconnell/rtr-deeplink/actions/runs/32188506193),
passed, and a manual `gh pr merge 177 --squash --delete-branch` succeeded
on the first try — the thing that had never once happened automatically
through this entire saga.

**Simplified in PR #178**: removed the now-dead (and now-broken, given
the PAT's scopes) `workflow_dispatch` dispatch-and-poll step from both
workflows, replacing it with `gh pr checks "$BRANCH" --watch --fail-fast`
before `gh pr merge --squash --delete-branch`.

**Hit one more real bug live-testing that simplification**: triggering
`feed-tier3-transcription.yml` again right after PR #178 merged opened PR
#179, but the workflow failed at the new `gh pr checks --watch` call with
`"no checks reported on the branch"` — `gh pr checks --watch` errors
immediately if called before GitHub has registered the
`pull_request`-triggered `test.yml` run at all, rather than waiting for
one to appear; it's watch-existing-checks, not wait-for-a-check-to-exist.
Closed PR #179 without merging (its 12 URLs were already ingested; upsert
makes re-ingestion harmless) and fixed in PR #180: both workflows now
poll (up to 60s) for at least one check to exist before handing off to
`--watch`.

**Final live verification, both workflows, clean runs on the fully-fixed
version**:
- Tier 3: manually triggered
  (https://github.com/mroconnell/rtr-deeplink/actions/runs/32189575670),
  opened PR #181, natural `pull_request` `test.yml` run passed
  (https://github.com/mroconnell/rtr-deeplink/actions/runs/32189668411,
  `author_association: OWNER`), `gh pr merge` inside the workflow itself
  succeeded with zero manual intervention.
  `scripts/tier3_auto_transcription_queue.txt` confirmed down from 1167
  to 1155 lines on `main` (`git log -1 --stat` on the merge commit shows
  exactly `12 deletions(-)`).
- Granicus: manually triggered
  (https://github.com/mroconnell/rtr-deeplink/actions/runs/32189901009),
  opened PR #182, natural `pull_request` `test.yml` run passed
  (https://github.com/mroconnell/rtr-deeplink/actions/runs/32189983911,
  `author_association: OWNER`), same unattended merge.
  `scripts/granicus_auto_transcription_queue.txt` confirmed down from 457
  to 445 lines on `main`, same `12 deletions(-)` pattern.

**Net result: both queue-advance workflows are now genuinely, verifiably
unattended end-to-end** — the residual manual-approval gap flagged in
this saga's prior entry is closed for real, not just theorized. The only
remaining maintenance burden is `QUEUE_ADVANCE_PAT`'s 2026-10-17
expiration (see above).

Also closed (without merging) two other queue-advance PRs stranded from
before this fix — #174 (Granicus) and #175 (tier-3) — left over from runs
that failed at the old `"base branch policy prohibits the merge"` point;
their 12 URLs each were already resolved/ingested, so nothing was lost.

## Queue-advance automation: GITHUB_TOKEN PR-creation permission enabled, a real run-selection bug fixed, verified end-to-end [Done 2026-08-18]

Picks up where the "Two remaining options, needs a real decision" note
below (this file's own prior entry for this saga, now folded in here)
left off. Ryan chose **option 1**: enable this repo's "Allow GitHub
Actions to create and approve pull requests" setting
(`can_approve_pull_request_reviews: true` via `PUT
/repos/{owner}/{repo}/actions/permissions/workflow`, `
default_workflow_permissions` left at `read` since the job already sets
its own `contents: write` at the job level) rather than provisioning a
PAT.

**Verified immediately, live**: manually dispatched
`feed-granicus-transcription.yml`
(https://github.com/mroconnell/rtr-deeplink/actions/runs/32159283179).
`gh pr create` succeeded for the first time ever, opening a real PR
(#171) that correctly popped 12 URLs off
`scripts/granicus_auto_transcription_queue.txt` — the original ask is
confirmed working.

**But the same run then failed at a new, third point**, exposing a real
bug in the workflow's own polling logic that the permission fix had never
been able to reach before: `feed-granicus-transcription.yml` /
`feed-tier3-transcription.yml`'s "Advance queue via PR" step dispatches
`workflow_dispatch` on `test.yml` (per this saga's own earlier comment,
written on the belief that `GITHUB_TOKEN`-authored PRs never trigger
`pull_request`-triggered workflows) and then polls `gh run list
--workflow=test.yml --branch="$BRANCH"` for *any* run on that branch to
watch. That belief turned out to be wrong: this repo is **public**, and a
`GITHUB_TOKEN`-authored PR's `author_association` comes back
`"CONTRIBUTOR"` (confirmed via `gh api .../pulls/171`), not
`"OWNER"`/`"MEMBER"` — so a real `pull_request`-triggered `test.yml` run
*does* fire, it just sits stuck in `action_required`, gated behind this
public repo's fork-PR-approval setting exactly like an outside
contributor's would be. The unfiltered `gh run list` query was grabbing
that stuck run instead of the dispatched `workflow_dispatch` one, so `gh
run watch` immediately failed with `action_required`, aborting the step
before it could merge PR #171.

**Fixed in PR #172**: added `--event=workflow_dispatch` to the `gh run
list` filter in both workflow files, so the polling loop can only select
the run it actually dispatched, and corrected the now-wrong comment
above each one. Verified the flag exists first (`gh run list --help`).
CI passed, merged.

**Re-verified PR #171 with the fix in place — and hit a fourth, deeper
issue**: re-dispatched `test.yml` against PR #171's branch with the
corrected selection logic; it correctly found and watched the
`workflow_dispatch` run this time, which passed. But `gh pr merge 171`
still failed: `"the base branch policy prohibits the merge."` Direct
inspection (`gh api .../commits/{sha}/check-runs`) showed the
`workflow_dispatch` run's `test` check-run as `conclusion: success`,
correctly linked to PR #171 via its own `pull_requests` metadata, from
the exact app/integration (`15368`, `github-actions`) the ruleset's
`required_status_checks` config names — every visible field matched.
`gh pr merge --admin` was still flatly rejected by GitHub's GraphQL API
itself (not just the CLI's local check): `"Required status check 'test'
is expected."` So the `main` ruleset does not credit a `workflow_dispatch`-
sourced check toward its required status check, regardless of matching
name/app/PR-linkage — only the genuine `pull_request`-triggered run
counts. Confirmed live: once Ryan manually clicked "Approve and run" on
the pending, previously-stuck `pull_request`-triggered `test.yml` run in
GitHub's UI, it ran for real, and PR #171 immediately flipped to
`mergeStateStatus: CLEAN`. Merged normally right after —
`scripts/granicus_auto_transcription_queue.txt` confirmed down to 457
lines on `main`, the queue's first real automated advance since PR #147's
one-time manual catch-up.

**Net result**: the original permission gap is genuinely fixed, and the
run-selection bug PR #172 fixed is a real improvement (the workflow no
longer aborts on a false failure) — but full *unattended* automation
isn't there yet, since the required check still needs a human to approve
a pending Actions run each cycle. See `BACKLOG.md`'s new entry for that
real, still-open residual gap and the security tradeoff involved in
closing it further.

Also cleaned up during this pass: deleted all 6 dead
`queue-advance/granicus-*` / `queue-advance/tier3-*` orphan branches
left behind by every failed run before this fix (confirmed via `gh pr
list --head` that none had ever had an associated PR — `gh pr create`
had failed before any of them could open one).

## Queue-advance PRs: repo-level "Allow GitHub Actions to create and approve pull requests" gap found, needs a decision [Superseded by the entry above, 2026-08-18]

Originally found via a real GitHub Actions failure notification email
(`RTR-Claude` Gmail label): the direct `git push` of the
queue-advancement commit was being rejected by the 2026-08-14 branch
ruleset (`GH013`, requires a PR + passing `test` check) on every single
scheduled run since the ruleset existed — confirmed from the actual
failed run's logs
(https://github.com/mroconnell/rtr-deeplink/actions/runs/32035051794).
The resolve/ingest half always worked fine (12 real URLs resolved and
POSTed to `/internal/ingest` per run, several `[OK]`); only the final
commit-back step failed, so the queue never actually shrank — every run
re-fed the same front-of-queue 12 URLs.

**PR #144 (2026-08-17) fixed that specific cause**: instead of pushing
directly, each workflow now commits the queue change on a new branch,
opens a PR, dispatches `test.yml` on it directly via `workflow_dispatch`
(needed because PRs/branches created with the default `GITHUB_TOKEN`
don't trigger `pull_request`-triggered workflows — GitHub's own
loop-prevention for that token — so the required `test` check would
otherwise never appear), waits for that run, then merges once green.
`pytest` (955 passed, 4 skipped) and the PR's own `test` check both
passed, and the PR merged cleanly.

**Live-triggered `feed-tier3-transcription.yml` for real afterward
(`gh workflow run` against `main`,
https://github.com/mroconnell/rtr-deeplink/actions/runs/32074229224) to
verify end-to-end, per this task's own verification requirement — and
it still failed, at a new point**: the resolve/ingest step again
succeeded for real (12 more real URLs), but the new "Advance queue via
PR" step died on `gh pr create` itself:
```
pull request create failed: GraphQL: GitHub Actions is not permitted to create or approve pull requests (createPullRequest)
```
This is a separate repo setting (Settings → Actions → General →
Workflow permissions → "Allow GitHub Actions to create and approve pull
requests"), distinct from the job's own `permissions:` block —
`pull-requests: write` there isn't sufficient on its own, and this
wasn't visible from reading the YAML/API beforehand. Net effect:
automated advancement is *still* broken today, just one step further
into the pipeline than before.

Manually completed the one stranded queue-advance branch that run left
behind (its 12 URLs really were ingested; the diff was just "pop 12
known-already-ingested URLs off the front") via a normal human-authored
PR, #147 — merged, so both queue files are correctly caught up as of
tonight. That's a one-time catch-up, not a fix; the next scheduled run
will hit the exact same `createPullRequest` error.

## Jurisdiction-bleed, third pass — gated eScribe subdomain extraction, leading-date/glued-extension preprocessing, curated junk-tail stoplist [Done 2026-08-18]

Four new bleed patterns found live on `/coverage`, each independently
root-caused as a distinct bug from the 2026-08-17 fixes (`#158`/`#161`),
not guessed — every one of the 13 real raw strings the ask surfaced was
run directly against `finalize_jurisdiction()`/`_jurisdiction_from_
subdomain()` before any fix was written, same convention as every prior
pass in this file. Shipped as [PR #168](https://github.com/mroconnell/rtr-deeplink/pull/168).

**Fix #1 — eScribe's subdomain-derived jurisdiction fallback is now
gated on Census/StatsCan-table validation, closing a real regression
the original ask's diagnosis didn't fully account for.** The ask's own
premise (wordninja missing, so add it to `requirements.txt`) turned out
to be false on direct testing: `wordninja==2.0.0` was already pinned and
already imported unconditionally in both `escribe.py` and `granicus.py`.
The REAL problem, found by actually running the pinned dependency rather
than trusting the diagnosis: `EscribeAssetFinder._jurisdiction_from_
subdomain()` (added WO-14, 2026-08-16) already wordninja-splits its
subdomain label, but does so *ungated* — deliberately, per its own
comment, since Canadian places weren't in the Census table when it
shipped. That reasoning went stale the very next day (`#158` added 5,028
real StatsCan rows to the same table `validated_label_extract()`
checks). Left ungated, re-resolving these customers today would silently
swap one wrong string for a *different, confidently wrong* one:
wordninja splits `"townofbonnyville"` into `town/of/bonny/ville`, which
joins (with spaces, after stripping the leading connector words) to
`"Bonny Ville"` — not `"Bonnyville"`. Confirmed directly against the
real pinned `wordninja==2.0.0` before writing any fix, not assumed.

Now delegates to a new shared, gated function
(`jurisdiction_enrich.validated_label_extract()`, a label-taking sibling
of the existing `_validated_subdomain_extract()` that Granicus's
`_humanize_subdomain()` already reuses via the public
`validated_subdomain_extract()` wrapper), extended with two new tiers
found necessary by testing against the real 8 originally-reported
subdomains rather than the 5 hand-picked ones in the initial ask:

1. **Spaced-then-glued wordninja rejoin.** The initial "corrected Fix 1"
   proposal (raw-unsplit-first, then a spaced wordninja join) was tested
   against the REAL production subdomain `"townofbonnyville"` (not the
   hand-built `"bonnyville"` used in the first round of manual testing)
   and found NOT to resolve it: `words=['bonny','ville']` after stripping
   `town`/`of`, and `"Bonny Ville"` doesn't validate. Adding a GLUED
   (no-space) rejoin as a fallback after the spaced attempt fixes it —
   `"Bonnyville"` validates. Order matters and was verified the hard way:
   trying glued BEFORE spaced was tested first and found to introduce a
   real regression across all 253 real Granicus subdomains in
   production — `"cityofnorthport"` wrongly resolved to `"Northport"` (a
   real but WRONG place, a coincidental table match) instead of the
   correct `"North Port"`; same failure on `"oakridgetn"` →
   `"Oakridge"` instead of `"Oak Ridge"`. Spaced-first, glued-fallback
   fixes Bonnyville with zero Granicus regressions (confirmed by
   sweeping all 253 real Granicus subdomains before and after).
2. **Canadian province-code stripping.** The shared trailing-abbreviation
   strip (`_STATE_ABBREVIATIONS_LOWER`) was US-states-only, so
   `"beaumontab"` (Beaumont, AB) and `"mackenziebc"` (Mackenzie, BC) —
   both real, both grounded in the original ask's own examples — failed
   to validate purely because the trailing province code was never
   stripped. Added `_PROVINCE_ABBREVIATIONS_LOWER` (13 codes, verified no
   collision with the US set).

Also found and closed a real false-positive the province-code list
introduced: `"citynmb"` wordninja-splits to `['city','n','mb']`; after
stripping the leading `city` and trailing province code `mb`, the sole
leftover word `"n"` was found to validate against a single-letter row in
`places.csv` (almost certainly a data artifact — no real municipality is
meaningfully 1-2 letters). Closed with a 3-character floor on any
wordninja-derived candidate.

**Verification: swept all 429 real subdomains currently in production**
(176 distinct eScribe labels + 253 distinct Granicus labels, both pulled
live via `/internal/pages/all-urls`) through old-vs-new logic before
shipping — not just the 13 strings named in the ask. Net: 105/176 eScribe
labels unchanged, 28 newly resolve correctly (Amherstburg, Baraboo,
Watsonville, Clarington, Cramahe, Espanola, Healdsburg, Leduc, Morinville,
Orinda, Penticton, Sahuarita, Scugog, Sechelt, Bonnyville, Beaumont,
Mackenzie, and several state/province-suffix cleanups), 43 honestly
decline instead of asserting wordninja garbage or a non-place acronym as
a jurisdiction (SANDAG the MPO, TDSB the school board, "One Investment
Program"). 249/253 Granicus labels unchanged, 4 newly resolve correctly
(Coppell TX, Hyattsville MD, Manteca CA, Surfside FL), zero regressions.

A real, honestly-flagged tradeoff surfaced by this sweep: ~9 eScribe
customers that currently show a recognizable (if unvalidated) guess would
decline to blank on a FUTURE re-resolve, because the StatsCan/Census
table doesn't cover them yet — Lloydminster and Paso Robles (both simply
missing), Durham/Peel/Waterloo Regions (a whole "regional municipality"
category the table lacks), and Chatham-Kent/Arran-Elderslie/Blue
Mountains (hyphenated names lost on a formatting mismatch). This mirrors
the same "decline beats a wrong guess" tradeoff this repo already
accepted for Granicus (the original tournament: 416 valid/0 garbage vs.
408 valid/229 garbage for an always-guess approach) — extended to eScribe
deliberately, not by accident. Tracked as a live, separate BACKLOG.md
entry (table-completeness gap) rather than blocking this fix on it. Can't
retroactively affect an already-published page — the existing backfill
endpoint only re-runs `finalize_jurisdiction()` on stored text, never
re-invokes subdomain extraction — only a future new meeting from these
customers is affected.

**Fix #2 — leading-date bleed** (`"6/16/25 Bellefonte Borough"`, `"8/6/25
State College Borough"`, both real Pennsylvania Borough examples found
live): a bleed DIRECTION `_trim_repair()` has zero handling for, since it
only ever trims from the right. Closed with a narrow preprocessing regex
(`_LEADING_DATE_RE`) at the top of `finalize_jurisdiction()`, guarded so
stripping a leading date never collapses a date-only string to empty.
Narrow enough (M/D/YY shape) to run unconditionally — no real
jurisdiction name starts with a bare date, so it's a no-op on every
string that doesn't have this exact bleed.

**Fix #3 — glued file-extension bleed** (`"Township of Brock.pdf Pulled
from Council Information Index by Regional Councillor Pettingill..."`,
Brock Township ON — previously tracked as an open gap in BACKLOG.md,
found unrepairable by the 2026-08-17 fixes since `_trim_repair()` cuts on
whitespace tokens and `.pdf` is glued directly onto `"Brock"` with no
space, so no cut ever lands on a clean `"Brock"`). Closed with a second
narrow, no-op-when-absent preprocessing regex (`_GLUED_EXTENSION_RE`)
inserting a space before a recognized office-document extension when
it's glued to a letter — the EXISTING trim-repair/`_looks_like_bleed()`
logic handles the rest unchanged once the space exists.

**Fix #4 — closed, curated junk-tail stoplist** (`_KNOWN_JUNK_TAIL_WORDS
= {"attachments", "meeting"}`), closing two of the three real examples in
BACKLOG.md's existing "single-word-tail gap" entry (Brampton's
`"Brampton Meeting"`, Peterborough's `"Peterborough Attachments"`) — the
third, Castle Rock CO's `"Authorizing"`, stays open since no second real
confirmed example grounds it on the stoplist yet, same "don't guess, only
close what's grounded in real data" discipline as every other fix in this
file. Deliberately a closed list rather than lowering `_MIN_BLEED_WORD_
RUN` generally, which confirmed testing shows would also wrongly trim
real long names (`"Lake Washington School District"` → `"Lake"`) — a
closed list can only ever fire on an exact match to a word already proven
junk, so it can't repeat that mistake.

**Out of scope, investigated not fixed: `"RochestercityMN"`.** Root-
caused via `app/platforms/iqm2.py`: `_TITLE_RE` captures the jurisdiction
verbatim from the page's own `<title>` tag, and Rochester, MN's specific
IQM2 tenant (`rochestercitymn.iqm2.com`) has `"RochestercityMN"` literally
glued together as-is IN THE PAGE'S OWN TITLE TEXT — confirmed by checking
IQM2's only other real customer, Santa Clara County, CA, whose title
correctly reads `"...- Web Outline - The County of Santa Clara,
California"` (proper spacing; extraction working as designed there). NOT
a Python f-string join-character bug as the original ask speculated — the
regex captures exactly what's on the page; the glued text originates at
IQM2's own vendor/tenant configuration for this one city. Only one
example exists (IQM2's only other confirmed customer), not enough real
data to design a general fix.

**Full existing `pytest` suite run before and after every fix, not just
new cases**: 1018 passed / 15 skipped (8 new tests in `tests/
test_jurisdiction_bleed_round2.py`; 2 existing tests updated where they
asserted the specific OLD behavior these fixes intentionally changed —
`test_escribe.py`'s "no video integration" test previously asserted a
synthetic non-place subdomain `"example"` would guess `"Example"`, now
correctly declines; `test_jurisdiction_enrich.py`'s single-word-tail-gap
test split into a narrowed "still open" test for `"Authorizing"` and a
new "now closed" test for `"Meeting"`/`"Attachments"`).

**Backfill note, same two-step pattern as `#158`/`#161` → `#165`/`#166`:**
the leading-date and glued-extension fixes are backfillable via the
EXISTING `POST /internal/jurisdiction/backfill-apply` (`#165`) once
deployed, since the bled tail/prefix in those cases is still separable by
word. The originally-reported eScribe subdomain rows (Bonnyville, Grand
Valley, etc.) are NOT — `"Townofbonnyville"` has no recoverable signal
once already glued together in storage, so fixing those needs an actual
re-resolve against the real source URL, not a text-only patch. Tracked as
its own live, not-yet-built BACKLOG.md entry rather than forced through
the wrong pipeline.

## Jurisdiction-bleed backfill — write path + real production run [Done 2026-08-18]

Data-repair pass closing the residual gap left by the two fixes below
(Canadian-data + Title-Case-bleed, and the same-night trim-repair/
consolidated-gov/entity-suffix second pass, PRs #158/#161): both fixes
were explicitly scoped code-only and never re-processed rows already
archived before they shipped, so 36 already-archived `MeetingPage` rows
were still carrying the old, wrong `jurisdiction` text as of 2026-08-18.
`GET /internal/jurisdiction/bleed-backfill-candidates` (added alongside
#158) could size the gap but nothing could act on it — this closes that.

Built as [PR #165](https://github.com/mroconnell/rtr-deeplink/pull/165):
`POST /internal/jurisdiction/backfill-apply` (token-gated,
`dry_run=true` default) and `crud.apply_jurisdiction_bleed_backfill()` —
always recomputes candidates itself server-side from each row's own
stored inputs (never trusts a client-supplied jurisdiction string), and
writes only the `jurisdiction`/`jurisdiction_confidence` columns, only
for rows where the jurisdiction TEXT actually changes. A
confidence-tier-only diff (e.g. `null` → `"validated"` with the same
string) is deliberately out of scope — most of the 646 raw candidates
from the GET audit are exactly that, and aren't worth a write. Covered
by 7 new integration tests (`tests/test_jurisdiction_backfill_apply.py`)
against the real SQLite test DB — dry-run writes nothing, a real apply
touches only the two columns (title/segments/etc. explicitly asserted
unchanged), confidence-only diffs are skipped, and both auth-gating
paths. Full suite: 1009 passed, 15 skipped. `scripts/
backfill_jurisdiction_bleed.py` drives it end-to-end: dry-run, print the
diff, require a typed `apply` confirmation, then write for real —
built but not needed for this run, since the verification below was
done directly against the endpoint instead.

**Verification, run for real against production 2026-08-18:**
- `GET /internal/jurisdiction/bleed-backfill-candidates` confirmed 36
  text-changing candidates live (of 646 raw candidates / 1231 rows
  checked), matching the task's expected count and examples exactly
  (e.g. "Peterborough is committed to making meetings accessible for
  people of all abilities..." → "Peterborough, ON"; "City of Salt Lake
  City, UT" → "Salt Lake City, UT" ×6).
- `POST .../backfill-apply?dry_run=true` returned the identical 36-row
  diff (same slugs, same before/after strings) as the GET audit —
  confirmed programmatically, not just eyeballed.
- `POST .../backfill-apply?dry_run=false` applied all 36. Re-running the
  GET audit afterward: text-changing candidates dropped to exactly 0;
  confidence-only diffs (out of scope) were unaffected in kind, though
  the just-repaired rows themselves now show up there instead (a
  `"repaired"`-confidence value re-running as `"validated"` once the
  string is already correct — expected, see
  `apply_jurisdiction_bleed_backfill()`'s own docstring, and covered by
  `test_apply_for_real_writes_only_jurisdiction_columns`).
- Diffed `title` across all 36 rows before vs. after (both from the
  audit endpoint's own payload and from the apply response's captured
  pre-write title) — zero mismatches, confirming nothing outside the
  two jurisdiction columns moved.
- Live-loaded 3 of the actually-changed pages on redtaperecordings.com
  (`/m/peterborough-is-committed-to-making-meetings-accessible-for-
  people-of-all-abilit`, `/m/slc-live-meetings-2026-08-11-salt-lake-
  city-council-truth-in-taxation-08-11-2026`, `/m/guelph-now-hold-a-
  meeting-that-is-closed-to-the-public-2026-07-14-council-planni`) —
  all three render the repaired jurisdiction in the page title/header,
  with transcript content and dates unaffected.

## CivicClerk/Granicus `external_id` wasn't host-namespaced — unrelated cities sharing a clip/event number silently merged onto one live page [Done 2026-08-18]

Found by accident while pushing a routine batch of 20 pre-vetted short
tier-3 meetings through the normal resolve+ingest pipeline: one push
(`libertymo.portal.civicclerk.com/event/395/media`, Liberty, MO) came
back pointing at an *existing* page slugged
`montrose-co-2023-08-01-city-council-meeting` -- a different city, a
different date, on the other side of the country. A fresh re-resolve of
the same URL moments later correctly returned Liberty, MO's own title/
jurisdiction, proving the resolver itself was fine and the corruption was
happening at the ingest/matching layer.

**Root cause**: `app/platforms/civicclerk.py` and `app/platforms/
granicus.py` built `external_id` from just the bare per-customer clip/
event number (`civicclerk:{event_id}`, `granicus:{clip_id}`). Both
platforms are multi-tenant SaaS where every customer numbers events/clips
independently starting near 1, so `external_id` was never actually
globally unique -- just unique *within one customer*. `archive/db/
crud.py`'s `_find_existing_page()` matches on `(platform, external_id)`
alone, so whenever two unrelated customers happened to share a number, a
later ingest for one would match the earlier page created for the other
and silently overwrite its title/date/jurisdiction on the same row, plus
add its own `TranscriptVersion` alongside the original's -- multiple
real cities' transcripts stacked on one page with no field anywhere
recording which version came from which city.

**Confirmed blast radius**, queried directly from the live DB: 2 of 75
CivicClerk pages corrupted (`civicclerk:395` had merged Montrose CO /
Ashland WI / Liberty MO onto one row; `civicclerk:14` had merged Cass Co
IA / Riverside County Sheriff's Office onto another) and 7 of 393
Granicus pages (`granicus:607` Fort Myers FL + Fountain Valley CA;
`granicus:3422` Napa CA + Santa Rosa CA; `granicus:555` Broward County FL
Schools + Albuquerque NM; `granicus:453` merged 3 counties -- Baldwin AL,
Bal Harbour FL, Brevard FL; `granicus:1046` North Miami Beach FL +
Pembroke Pines FL; `granicus:267` Manatee County FL Schools + Pioneer
Community Energy; `granicus:1452` Albemarle VA + Azusa CA). Checked and
confirmed zero `SavedItem` rows referenced any of the 9 -- no real user's
saved-meeting link was affected. 4 had a `TranscriptionJob` row (pure
operational history).

**Fix**: namespaced `external_id` by host in both adapters
(`civicclerk:{netloc}:{event_id}`, `granicus:{netloc}:{clip_id}`) so
future ingests can no longer collide across customers. `app/platforms/
models.py`'s `ResolvedMeeting.external_id` docstring updated to state the
host-namespacing requirement explicitly for any multi-tenant platform.
Updated the 7 existing tests that asserted the old bare-ID format
(`test_civicclerk.py` x2, `test_granicus.py` x2, `test_civicplus.py`,
`test_legistar.py` x2) to the new namespaced strings; no test coverage
gap existed for the collision itself since nothing previously exercised
two different hosts sharing one clip/event ID.

**A `crud.py`-level defense-in-depth guard was tried and reverted --
lesson worth keeping.** The first instinct was to also harden
`_find_existing_page()` itself: reject an `external_id` match unless the
matched page's `source_url_normalized` host agrees with the incoming
URL's host, so a *future* adapter making the same bare-ID mistake
couldn't reproduce this corruption either. Traced through the two other
real callers of `external_id`-based cross-host merging before shipping
it, and both would have silently broken: `legistar.py`'s
`_try_fallback_video_link()` path deliberately does `fallback.source_url
= url`, keeping the *original* Legistar URL even though `platform`/
`external_id` correctly point at the real delegated Granicus host; and
`primegov.py` calls `YouTubeAssetFinder.resolve_video_id(video_id,
source_url=url)`, doing the same for the original PrimeGov URL vs.
youtube.com. Both are intentional, existing, working cross-host merges
-- a netloc check would have turned each into a duplicate page instead.
No test caught this because none exercises "same clip ingested once
directly, once via a delegating platform, expect one page" at the crud
layer. Globally-unique `external_id` at the adapter level (verified
per-platform, where the real numbering scheme is actually known) is the
correct fix; there's no cheap generic check at the shared `crud.py` layer
that can't also break a legitimate case it doesn't know about.

**Data repair**: since no `TranscriptVersion` row records its source
host, there was no reliable way to un-mix which transcript belonged to
which city after the fact. Deleted all 9 corrupted `MeetingPage` rows
(cascading their `transcript_versions`/`meeting_page_url_aliases`/
`transcription_jobs` first, no `ON DELETE CASCADE` at the DB level) and
re-resolved + re-ingested all 20 distinct original host URLs fresh
through the now-fixed adapters, producing 20 clean, correctly
host-namespaced, separate pages. Re-queried both platforms for cross-host
alias collisions afterward: 0 remaining on either. Old slugs (e.g.
`montrose-co-2023-08-01-city-council-meeting`) now 404 rather than
redirecting, accepted since nothing legitimately linked to them (they
were serving mismatched content anyway) and no saved item pointed at
them. Full suite green throughout (1005 passed, 9 skipped).

## Cablecast: newer portal template (`/show/{id}`, no `/internetchannel` prefix) was unresolvable, AND once fixed inside the finder, still unreachable through the real production routing path [Done 2026-08-18]

Found via the same tier-1/tier-2 "dead" list pilot campaign as the Swagit
entry below (a background agent piloting `rtr-business/research/
urls_cablecast_miss.txt`, 25 of 211 sampled). Two distinct, stacked bugs,
both real and confirmed live -- fixing only the first would have left
the whole thing silently non-functional in production.

**Bug 1 (found and fixed by the pilot agent), inside
`app/platforms/cablecast.py`.** A newer Cablecast portal template
(confirmed on `satellitebeach.cablecast.tv`, also `carsonca`,
`virginiabeach`, `rialtoca`, and others) drops the `/internetchannel`
prefix and serves shows at bare `/show/{id}` instead of
`/internetchannel/show/{id}`. That bare path is protected by an AWS WAF
JavaScript challenge that returns empty content to any non-browser
fetch (the adapter correctly never attempts to solve/bypass a WAF
challenge -- out of scope, same policy as everywhere else in this
codebase). But the site's *root* page (`/`) isn't WAF-protected, and its
own `window.__remixContext` embeds a large "related shows" catalog (287
real shows confirmed on `satellitebeach` alone, back to 2019) -- enough
to find the requested show without ever touching the blocked path. Also
found and fixed a real `showId` type mismatch discovered along the way:
an `int` on the older `/internetchannel/show/` template (Detroit,
Charlotte) but a `str` on this newer one (e.g. `satellitebeach`'s
`"showId": "540"`) -- silently broke matching even after the URL-shape
fix, until compared as strings on both sides. Fix: a root-page fallback
fetch when the direct `/show/{id}` path 404s or is WAF-blocked, plus
string-normalized `showId` comparison. 4 fixture-backed regression tests
added to `tests/test_cablecast.py` with real fixtures.

**Bug 2 (found in a follow-up check, after the pilot agent's fix landed)
-- the fix above was real but completely unreachable in production.**
`app/platforms/base.py`'s `detect_platform()` is what routes a URL to
`cablecast.py` in the first place, and its check was `"cablecast.tv" in
netloc and "/internetchannel/show/" in path` -- deliberately scoped
narrow back on 2026-08-12 specifically to exclude other, unhandled
`*.cablecast.tv` templates (Charlotte, NC's confirmed-different one).
That narrow scoping meant a bare `/show/{id}` URL was classified as
platform `"unknown"` and never reached `cablecast.py`'s new fallback
logic at all, regardless of how correct that logic was -- confirmed live
by re-running the exact URLs the pilot agent had just verified through
`CablecastAssetFinder().resolve()` directly, but through the real
`detect_platform()` -> `get_finder()` -> `resolve()` path every actual
production caller uses (`scripts/bulk_ingest.py`'s pattern): 2 of 3
"recovered" URLs (`virginiabeach`, `carsonca`) came back with `video_
url=None` and a generic "this city isn't officially supported yet"
message from `generic_fallback.py`, not the real Cablecast handling --
because they were never routed there. Only `coralvision`'s URL (which
happened to already use the old `/internetchannel/show/` shape) worked,
by coincidence of URL shape, not because the real fix was reachable.
**Lesson worth keeping**: verifying a finder fix by calling the finder
class directly, rather than through the actual `detect_platform()` entry
point real callers use, can hide a routing-layer gap that makes the fix
inert in production -- re-test through the real entry point, not just
the class under test, before calling a fix verified.

**Fix**: widened `detect_platform()`'s cablecast condition to also match
a bare `/show/{id}` path (checked precisely -- the segment after `/show/`
must be all-digits, not just presence of the substring), while leaving
every other `*.cablecast.tv` template correctly unclaimed (the pilot
agent separately confirmed two other real template variants -- a
login-gated `FrontDoor.aspx` ASP.NET portal, and a fully client-rendered
SPA with no embedded state -- neither of which uses a `/show/` path at
all, so this widening doesn't accidentally claim them). Re-verified:
`detect_platform()` now correctly returns `"cablecast"` for all three
URLs, full suite green (1005 passed, 9 skipped), and all three real
meetings ingested successfully through the actual production path
(`virginiabeach`: 1 segment, `carsonca`: 32 segments, `coralvision`: 302
segments, all live at their real `/m/{slug}` pages).

## Swagit `/videos/{id}/transcript` URLs resolved to "no video" — turned out to be a real, separate transcript resource, not a missing-video bug [Done 2026-08-18]

Found by the user manually clicking through a "dead" list from an
oversized queue scan (see this same date's `BACKLOG.md`/`CLAUDE_BACKLOG.md`
entries for the two sibling bugs found the same way — a false-dead
YouTube/ffprobe mismatch and a slow-host timeout, both in throwaway scan
tooling, not the adapter). Swagit specifically turned out to be a real
adapter gap, confirmed live, not a script bug: `app/platforms/swagit.py`
correctly resolves `https://{customer}.new.swagit.com/videos/{id}`, but
the same meeting's `/videos/{id}/transcript` URL variant resolved to
`video_url=None`, `"No playable video found on this page."` — even
though clicking it in a real browser clearly showed a working page.

**Root cause, confirmed live against 3 real customers (huberheightsoh
clip 267352, allentx clip 189248, amarillotx clip 317100), not
assumed**: `/videos/{id}/transcript` isn't another view of the video
page at all — it's a genuinely separate resource. Live response headers
confirm `Content-Type: text/plain` / `Content-Disposition: attachment`,
i.e. a real plain-text file download. The old adapter fed that
plain-text download through the HTML-scraping resolve path meant for
the video page; naturally no video markup exists there, so it silently
resolved to nothing.

**It's not just a bug fix — the plain-text file is a real, usable
transcript source**, better than this app's Whisper fallback where
available: a Swagit-hosted transcript (labeled "ASR voice-to-text" by
one customer's own disclaimer, "uncorrected Closed Captioning" by
another), with real second-offset timestamps roughly every 5 minutes and
inline agenda-item markers matching the page's own `a.playerControl`
chapter markers. Every base `/videos/{id}` page that has one links to it
via a real `<a href="/videos/{id}/transcript">` — distinguishable from
the page's unrelated in-page `href="#transcript"` anchor, confirmed
absent on a real collincountytx meeting with no generated transcript, so
this is a genuinely optional per-meeting resource, not something assumed
to always exist.

**Fix, in `app/platforms/swagit.py`**: (1) a `/transcript`-suffixed URL
is normalized back to its base video page for video/metadata/chapter
resolution, so it no longer tries to scrape video markup off the
transcript download; (2) the transcript download (from either URL
shape) is fetched separately and parsed by a new
`_parse_swagit_transcript_download()` into real, timestamped
`TranscriptSegment`s — now the highest-priority transcript source for
this platform, ahead of the existing `#transcript-fragments` DOM path
and the never-yet-observed caption-file path; (3) repeated disclaimer
boilerplate is captured as a `transcript_warnings` note rather than
treated as real transcript prose.

**Verified live post-fix** against all 4 example URLs: video + real
multi-line, correctly-timestamped transcript segments now resolve
correctly for huberheightsoh, allentx, and amarillotx's `/transcript`
URLs; collincountytx (confirmed to have no transcript available) is
unaffected, still resolves video with the correct "no transcript"
warning rather than a false positive. 4 new fixture-backed regression
tests added to `tests/test_swagit.py`, one using real, verbatim-fetched
transcript text (per this repo's synthetic-test convention — real
content even though the fixture itself is hand-built). Full suite: 1002
passed, 9 skipped (unrelated), up from 996 before this session's other
fixes landed.

## Jurisdiction-bleed, second pass — trim-repair fall-through, consolidated-government spelling, entity-suffix allowlist [Done 2026-08-17]

Same-night follow-up audit of the fix immediately below (the Canadian-data
+ Title-Case-bleed fix), run against the real production
`GET /internal/jurisdiction/bleed-backfill-candidates` endpoint (added as
part of that fix) rather than against a handful of hand-picked examples.
Found real false positives the first fix introduced or left unaddressed,
root-caused by tracing `_trim_repair()`'s cut-by-cut behavior directly
(`app/utils/jurisdiction_enrich.py`), not guessed. Three independent
fixes, verified by re-running `finalize_jurisdiction()` against all 652
real rows the audit endpoint returned (with `netloc=None` — confirmed by
diffing against the endpoint's own real-netloc output first that this
changes only 7/652, all a single already-understood SLC authoritative-
domain artifact, so a safe proxy) before and after each fix, plus the
full `pytest` suite (996 passed, 9 skipped throughout).

**Fix #1 — `_trim_repair()` no longer falls through past a literal
match.** The function iterates candidate cuts longest-to-shortest,
checking `_table_lookup()` at each; the bug was that when a cut's prefix
validated but its tail was correctly judged NOT bleed, the old code kept
scanning shorter cuts instead of stopping — letting a wrong, shorter,
spurious match win later in the loop. Two real confirmed examples:
"Richmond Hill Single Source Award" correctly rejected "Richmond Hill"
(a real, different place; tail "Single Source Award" not bleed) but then
wrongly repaired to "Richmond" via the shorter cut (tail "Hill Single
Source Award", 4 words, looked like bleed) — destroying "Richmond Hill".
"East Bay Regional Park District, CA" broke the same way, wrongly
repairing to "East, CA" via a real OH township match at the shortest cut.

Fixing this naively ("stop at the very first cut with ANY hit") broke a
different real, already-correct repair: "East Providence City Council
Live Stream" 's longest hit, "East Providence City", only validates via
the ordinary trailing-"City"-word strip (the literal text "east
providence city" isn't a real table key, only the stripped "east
providence" is) — coincidental, since "City" here is really the start of
"City Council" in the surrounding text. Its tail ("Council Live Stream",
3 words) isn't bleed-shaped, so a blind stop would give up on the whole
string, when the correct behavior is to keep scanning to the next cut
("East Providence", a literal match with a genuinely bleed-shaped tail)
and repair to that. Real fix: `_table_lookup()` was split into a new
`_table_lookup_strength()` that also reports whether a match came from
the name's own literal text (as typed, or with only a deterministic
leading "City of "/etc. removed) versus a secondary/heuristic
normalization (trailing type-word strip, abbreviation expansion, Saint
contraction, ʻokina strip). `_trim_repair()` now stops the search only on
a LITERAL match (accept if bleed, else give up entirely); a
heuristic-only match with a non-bleed tail doesn't stop the search, since
it may be coincidental. Verified: re-running against all 652 real audit
rows, this change affects exactly the two bad cases (Richmond Hill, East
Bay) — nothing else in the corpus moves, including East Providence and
every other already-correct repair named in the original ask (Sarasota,
Hollywood, Hampton, Gainesville, Lethbridge, Kelowna, Oshawa, Mississauga,
Thunder Bay, Peterborough, Sooke, Squamish, Spruce Grove, all 6 Salt Lake
City instances).

**Fix #2 — real consolidated city-county governments now match page
formatting.** "Louisville / Jefferson County Metro" (real archived raw
text) didn't match the stored Census key ("louisville/jefferson county",
derived from "Louisville/Jefferson County metro government (balance)")
because of spaced-slash formatting and a bare "Metro" instead of "metro
government". Added a query-side `_QUERY_GOVERNMENT_TYPE_RE` (strips a
bare trailing metropolitan/metro/unified/consolidated, "government"
optional) and slash-spacing normalization, tried as a new candidate tier
in `_table_lookup_strength()`. Now resolves to
`JurisdictionResult(jurisdiction="Louisville / Jefferson County Metro",
confidence="validated")` — the real entity, correctly identified, rather
than the old destructive "Louisville" (a nationally-ambiguous name,
colliding with real places in CO/GA/KS/MS/NE/OH/TN/AL/IL). Control case
re-verified unaffected: "Nashville-Davidson County, TN" already matched
before this fix (it strips down via the ordinary trailing-"County" strip,
no slash or bare-"Metro" involved) and still does.

**Fix #3 — positive-evidence entity-type-suffix allowlist.**
`_looks_like_bleed()`'s word-count tier (from the first fix, immediately
below) was one-sided: only negative evidence for bleed (lowercase,
digits, roman numerals, a long Title-Case/ALL-CAPS run), nothing to tell
a real long government-entity name apart from real bleed prose that's
also coincidentally all-capitalized. Real confirmed case: "St. Johns
River Water Management District, FL" — "St. Johns" is the only valid
(literal) prefix, and its tail "River Water Management District" (4
words, all Title-Case) is shape-identical to real bleed like "Legacy
Business PLEDGE OF PUBLIC". Added `_ends_with_known_entity_suffix()`: an
END-ANCHORED (not "contains") check against a small set of real,
evidence-grounded government-entity-type words (`district`, `authority`,
`commission`, `government`, `schools`/`school`, `transit`, `utility`,
`isd`/`usd`/`cisd`) and two committee-name phrases
(`committee of adjustment`, `committee of the whole`). Every word is
grounded in an already-archived real jurisdiction name (see
`_ENTITY_TYPE_SUFFIX_WORDS`'s own comment for the specific real names
behind each), not invented — including a confirmed live count of the ISD/
USD/CISD acronym across 14 real archived TX/CA school districts. Bare
"SD"/"FD"/"PD" acronyms were deliberately left out: no real archived
example was found, and a bare "SD" risks colliding with the South Dakota
state abbreviation (a real archived row, "White Rock, SD", would have
been a false-positive trap). End-anchored specifically because real
bleed can legitimately CONTAIN a protected word without ending in it —
Kenora's real, correct repair ("Committee of the Whole Agenda Thursday" →
"Kenora, ON") contains "Committee" but ends in "Agenda Thursday", so a
"contains" check would have wrongly protected it; verified this still
trims correctly after the fix, alongside Guelph's "Committee of
Adjustment" case.

Explicit design bias, per direct instruction: over-protect rather than
under-protect. A plain trailing-word check like this can occasionally
spare a genuine bleed tail that happens to end in a protected word
(leaving a bit of extra, cosmetic noise on the meeting-BODY portion of a
name) — but that's a strictly smaller mistake than the alternative
(trimming through to a shorter, wrong CITY). No case in the 652-row real
audit corpus was found where this allowlist wrongly protects a genuine
bleed tail.

**Bonus find, not in the original report, caught only by re-running the
full 652-row audit after Fix #3:** "Albuquerque Bernalillo County Water
Utility Authority" — already cited in this file's earlier entry (below)
as a "real, correct, legitimately-long agency name" that must not be
trimmed — was in fact STILL being wrongly repaired to "Albuquerque, NM"
by the shipped word-run-only signal (confirmed via the real audit
endpoint's `repaired_jurisdiction` field, not previously covered by any
test). Fix #3 closes this too (tail "Bernalillo County Water Utility
Authority" ends in "Authority").

**Root cause named but deliberately NOT force-fixed:** none — all three
named root causes got a real, verified fix this pass (unlike the first
fix's own entry, which left three residual gaps still open in
BACKLOG.md — those three are untouched by this pass and remain open as
described there).

**Verification:** `tests/test_jurisdiction_enrich.py` gained 8 new tests
using the exact real strings from the audit
(`test_trim_repair_does_not_fall_through_past_a_literal_match_richmond_hill`,
`..._east_bay`,
`test_trim_repair_still_finds_a_shorter_repair_past_a_heuristic_only_match`
(East Providence), `test_finalize_jurisdiction_resolves_a_real_consolidated_government_page_spelling`
(Louisville + Nashville-Davidson control),
`test_finalize_jurisdiction_protects_a_real_special_district_entity_suffix`
(St. Johns), `test_finalize_jurisdiction_protects_a_real_water_utility_authority`
(Albuquerque), `test_finalize_jurisdiction_entity_suffix_allowlist_does_not_protect_real_bleed`
(Kenora + Guelph), `test_ends_with_known_entity_suffix_is_end_anchored_not_contains`
(direct unit test)). Full suite: 996 passed, 9 skipped. This was code-only
— no already-archived production data was touched or re-processed; a
real backfill decision (via the still-live
`GET /internal/jurisdiction/bleed-backfill-candidates` endpoint) stays
with the user.

## Jurisdiction-bleed, confirmed cross-platform — Canadian data table + Title-Case bleed fix [Done 2026-08-17]

BACKLOG.md's "Jurisdiction-bleed, confirmed cross-platform" entry
root-caused two independent causes behind ~27 confirmed real bleed
examples; both fixes below were built and verified against those real
strings, not synthetic ones.

**Fix #1 — real Canadian city/town data.** `scripts/build_jurisdiction_data.py`
gained `build_canada_places()`, sourced from Statistics Canada's own
Standard Geographical Classification (SGC) 2021 "Structure" file
(`https://www.statcan.gc.ca/eng/statistical-programs/document/sgc-cgt-2021-structure-eng.csv`
— public, no login needed, confirmed live by downloading it directly this
session). Every "Level 4 / Census subdivision" row (5,161 total, 5,028
unique after dedup) is a real Canadian municipal-level government —
merged directly into the SAME `app/utils/jurisdiction_data/places.csv`
the US data already lives in (confirmed by reading
`_load_name_state_table()` directly: fully data-agnostic, zero code
changes needed there), not a separate table. Confirmed zero 2-letter
abbreviation collision between the 13 province/territory codes and 50 US
state codes, as the original entry predicted. One real *name* collision
did surface and required updating an existing test:
`test_table_lookup_recognizes_a_spelled_out_saint` — "St. Paul" is now
ambiguous between the Minnesota city and a real Alberta town, exactly the
"extends for free" ambiguity-safety the original entry called out, not a
bug. Deliberately NOT split into a separate Canadian "counties" table —
Canada's census-subdivision level doesn't cleanly separate into "city" vs
"county" government the way US places.csv/counties.csv do, and every
confirmed real bleed case is a plain city/town name; revisit if a real
county-shaped Canadian case turns up. Deliberately NOT accent-folded —
Canadian names are stored exactly as StatsCan spells them (Québec,
Montréal, Trois-Rivières), so an English-language page spelling these
without the French diacritics won't match today; no real confirmed bleed
case needs this yet (every one is a plain-ASCII English city name), left
as an honestly-documented gap rather than untested guessing.

**Fix #2 — Title-Case/ALL-CAPS word-run signal in `_looks_like_bleed()`.**
Added `_MIN_BLEED_WORD_RUN = 4` (`app/utils/jurisdiction_enrich.py`): once
a discarded trim-repair tail contains zero lowercase-initial words (else
the existing check already fires), a tail of 4+ words is now also treated
as bleed. 4 is the exact real gap between the shortest confirmed real
bleed tail (4 words: Sarasota's "Legacy Business PLEDGE OF", Hampton's
"Zoning Ordinance Regarding Standa") and the longest real tail that must
stay untouched (3 words: "Washington School District" off "Lake", "Area
Headquarters Authority" off "Bay", "Metropolitan Transportation
Authority" off "Capital" — all three from BACKLOG.md's own named
must-not-trim list — plus the pre-existing Broward MPO false-positive
regression test's "That'S Identified", 2 words). Verified directly
against all four before picking the threshold, not assumed.

**Real verification, using the actual raw strings from BACKLOG.md's
confirmed table (`tests/test_jurisdiction_enrich.py`, new tests added
this pass), not invented ones:**
- Newly repaired by Fix #1 alone: Mississauga ON, Oshawa ON, New
  Westminster BC, Guelph ON, Thunder Bay ON, Lethbridge AB, Peterborough
  ON (see below).
- Newly repaired by Fix #1 + Fix #2 together: Sarasota FL, Hollywood FL,
  Hampton VA, Gainesville FL, Kelowna BC, Delta BC.
- Confirmed still NOT repaired (real, honestly-flagged residual gaps, not
  silently claimed fixed):
  - **Brampton ON ("Brampton Meeting") and the older Castle Rock CO
    ("Town of Castle Rock Authorizing") cases** — both have a
    single-word discarded tail ("Meeting"/"Authorizing"), below
    `_MIN_BLEED_WORD_RUN`. A single capitalized word is genuinely
    indistinguishable from a legitimate short suffix with this signal
    alone (lowering the threshold to catch these would also wrongly trim
    "Lake Washington School District" → "Lake", confirmed by direct
    testing) — left open rather than risking that regression.
    Locked in as expected/current behavior by
    `test_finalize_jurisdiction_single_word_bleed_tails_remain_a_known_residual_gap`.
  - **Brock Township ON** ("Township of Brock.pdf Pulled from Council
    Information Index...") — a different bug neither fix targets: the
    real place name "Brock" is glued directly to a filename
    (`Brock.pdf`, no space), so no cut of the string ever isolates a
    bare "Brock" token for `_table_lookup()` to validate. An extraction-
    side artifact (something concatenated a PDF filename with no
    separator), not a jurisdiction_enrich.py gap.
  - **A newly surfaced risk, not previously flagged: Fix #1 can turn an
    honestly-garbled "unverified" bleed string into a CONFIDENTLY WRONG
    "repaired" one, when the bled text happens to contain a different,
    unrelated but real Canadian city name.** Two real confirmed
    instances: Shelburne ON's raw value ("Brantford regarding
    Professional Activity") now repairs to "Brantford, ON" — a real
    place, but the WRONG city (the meeting is Shelburne's, not
    Brantford's). Uxbridge ON's raw value ("Peterborough Attachments")
    stays unrepaired only incidentally (single-word tail "Attachments"
    doesn't meet the fix #2 threshold) — if it had been long enough to
    trigger, it would have confidently "repaired" to the wrong city
    (Peterborough) the same way. Neither fix could plausibly have caught
    this: distinguishing "a real city name" from "the CORRECT real city
    name for this specific meeting" from text shape alone isn't solvable
    by a heuristic like this one. This is an instance of a pre-existing,
    accepted category of risk in the whole trim-repair design (the same
    risk the already-shipped Sarasota/Hollywood-style false positives
    carry), not something these two fixes newly introduced from nothing
    — but it's the first time it's been confirmed live with real
    examples, so it's called out explicitly rather than silently
    absorbed into "fixed." Not addressed this pass — see BACKLOG.md for
    the live entry.

**The "unexplained" Peterborough case, re-checked directly against real
code per the ask, not guessed:** calling `finalize_jurisdiction()` with
the real (BACKLOG.md-truncated) raw string
"Peterborough is committed to making meetings accessible for people of
all abilities" already repairs correctly to "Peterborough" (confidence
"repaired") using code that predates BOTH of tonight's fixes — turns out
"Peterborough" already collided with a real US place, Peterborough town
NH, just in the county-*subdivision* table (`_table_lookup()`'s
validation check reads that table; `lookup_city_state()`'s state-filling
check does not, which is why it came back state-less before tonight).
This session could not reproduce BACKLOG.md's "still not trimmed" claim
against current code — most likely explanation is the already-archived
production page's stored value simply predates whatever earlier fix made
this validate, and was never reprocessed (reprocessing already-archived
pages was explicitly out of scope for this pass, see below). What Fix #1
adds on top: an actual province now resolves too ("Peterborough, ON"),
since "Peterborough" is unambiguous in the *place* table once Canada's
entry is the only one there (the NH collision lives in a different table
lookup_city_state() never consults).

**Bonus, not the core ask: sizing a future backfill.** Added
`GET /internal/jurisdiction/bleed-backfill-candidates`
(`archive/main.py` + `crud.list_jurisdiction_bleed_backfill_candidates()`),
same token-gated read-only-audit pattern as
`/internal/transcription/hallucination-candidates` — re-runs
`finalize_jurisdiction()` against every already-archived page's current
stored value and reports which would come out differently. Built and
unit-tested (`tests/test_jurisdiction_backfill_audit.py`) against the
isolated test DB, but this session had no real production `DATABASE_URL`
access (same constraint noted elsewhere in this file for Alembic), so
the *actual* production count was never obtained — hitting this endpoint
with the real `ARCHIVE_INGEST_TOKEN` is how to get it. Per the task's own
scope boundary, no already-archived page's stored jurisdiction was
bulk-modified this pass — this endpoint only sizes the question, a human
decides whether/when to act on it.

**Full test suite**: 986 passed, 9 skipped (pre-existing, unrelated), 0
failed — `pytest` run clean after all changes, including the one
pre-existing test updated for the new real "St. Paul" US/Canada
collision.

## Coverage page — full sortable/filterable per-jurisdiction detail table [Done 2026-08-17]

BACKLOG.md's "[IMPROVEMENT-ROUND] Coverage page" entry's real remaining
gap (the per-platform grouped view already existed and stayed unchanged):
`/coverage` groups by platform and lists "Every place we've covered" by
jurisdiction, but had no single, sortable/filterable table with one row
per successfully-archived jurisdiction and the user's full column spec.
Built as a new, additive section on the existing `/coverage` page — the
existing platform-grouped view and jurisdiction roster keep working
exactly as before, verified by the full pre-existing test suite staying
green (see below).

**What was built**:
- `archive/db/crud.py`: a new `get_full_jurisdiction_coverage()` (~230
  lines including docstrings/helpers), deliberately additive next to
  `get_platform_coverage()`/`get_jurisdiction_coverage()` rather than a
  rewrite of either. One row per jurisdiction (same population as
  `get_jurisdiction_coverage()`, same `MeetingPage.jurisdiction is not
  None` gate), with:
  - `video_embeds`/`agenda_embedded` — straight from `MeetingPage.video_url`
    and `agenda_items`.
  - `instant_transcript` — a real, non-empty `TranscriptVersion` with
    `source == "scraped"` on *any* version of the page, not just the
    default one (a page's default can be promoted to a later
    `"transcribed"` version via `manually_promote_transcript_version()`
    without deleting the original scraped one, so checking only the
    default would wrongly say "no" for a page that still has a real
    scraped transcript sitting non-default).
  - `audio_transcript_possible` — `video_url is not None and video_format
    != "youtube"`. Mirrors `app/main.py`'s own
    `_unreadable_media_message()` reasoning: a YouTube-hosted video is an
    iframe-embed page, never a real media file, so ffprobe can never read
    it — a structural, permanent limitation, not something that needs a
    live probe per row (which would be far too expensive for a full
    coverage table).
  - **Two-column provider split** (`detail_platform`/`video_platform`,
    via new `_platform_split()`/`_wrapper_detail_label()` helpers): only
    genuinely splits into two different labels when there's real
    recoverable evidence they differ. `MeetingPage.platform == "youtube"`
    is recovered back to its real originating wrapper platform
    (Minneapolis LIMS / Salt Lake City / ClerkBase / **PrimeGov** /
    **CivicWeb** — the last two newly added here, since
    `get_platform_coverage()`'s existing `_entry_platform_from_source_url()`
    only ever recognized the first three) via the real, confirmed *.primegov.com
    /*.civicweb.net domain patterns (confirmed live by reading
    `primegov.py`/`civicweb.py` directly, not assumed) on
    `source_url_normalized`. Everywhere else — including every
    Legistar/CivicPlus-delegated row — both columns show the *same*
    label, which is the honest answer: per CLAUDE.md's wrapper-platform
    bullet, Legistar/CivicPlus delegation overwrites both
    `MeetingPage.platform` *and* `source_url_normalized` with the
    delegated platform's own values, so this app genuinely has no stored
    way to tell, post-hoc, that a given Granicus row arrived via a
    Legistar page rather than a directly-pasted Granicus link — showing
    "Detail: Granicus; Video: Granicus" for that row isn't a missed
    split, it's the real limit of what's recoverable from stored data. A
    `platform == "unknown"` (generic_fallback direct-media-file) row
    shows the real `video_url` host as its video label rather than
    guessing a platform name (e.g. never labeled "Vimeo" without a
    confirmed vimeo.com host, per CLAUDE.md's "don't claim a data path
    works without a positive example" convention).
  - **Outcome bucket** (`_classify_page_outcome()`) — mirrors
    `app/db/outcomes.py`'s `classify_outcome()` bucket names/ordering
    (no_video / blank_transcript / agenda_fallback / garbled_transcript /
    non_english_transcript / success), but reads
    `MeetingPage`/`TranscriptVersion` directly rather than importing that
    function, since it classifies a different schema
    (`MeetingResolution`, the resolver's own DB) on a different service's
    DB — archive/ deliberately doesn't import from app/.
  - `last_verified` — `max(updated_at)` across the jurisdiction's pages.
  - A jurisdiction with several archived pages gets each yes/no column as
    "true if ANY of its pages has it" (a "did we ever manage this for
    this city" roster), but its platform-split/outcome/example columns
    from whichever single page has the best (lowest-ranked) outcome
    bucket — same spirit as `get_jurisdiction_coverage()`'s own
    has_transcript-preferred example pick.
  - A correlation bug hit building the `instant_transcript` EXISTS
    subquery: without an alias, SQLAlchemy auto-correlated the outer
    query's own `TranscriptVersion` outerjoin into the subquery too,
    leaving it with no FROM clause at all (`InvalidRequestError`) — fixed
    with the exact same `aliased(TranscriptVersion)` +
    `.correlate(MeetingPage)` pattern `_is_empty_page_condition()` already
    uses a few hundred lines up in the same file, for the identical
    reason.
- `archive/main.py`: `/coverage` now also calls
  `get_full_jurisdiction_coverage()` and computes distinct
  detail-platform/video-platform/outcome option lists for the new
  filter dropdowns (derived from the real rows, not
  `DIRECT_PLATFORMS`/`CUSTOM_PLATFORMS`, since this table can show labels
  those dicts don't have, e.g. "PrimeGov" or a raw host).
- `archive/templates/coverage.html`: new "Full jurisdiction detail table"
  section between the existing jurisdiction roster and the "By platform"
  section, with a filter row (search box, 3 dropdowns, 4 checkboxes) and
  a 10-column table (`#`, Government, Video embeds, Agenda embedded,
  Instant transcript, Audio transcript possible, Detail page, Video
  platform, Outcome, Last verified, Example).
- `archive/static/coverage.js`: generalized from a single hardcoded
  `#coverageTable` to `initSortableTable()` applied to every
  `table.sortable-table` (both the existing table and the new one now
  carry that class), preserving the exact existing sort behavior/pattern
  for the pre-existing table. Added a new client-side filter block scoped
  to `#fullCoverageTable` only (search substring match + 3 dropdown exact
  matches + 4 "only show yes" checkboxes, all AND'd together), reusing
  the sort code's `renumberVisibleRows()` so row numbers skip
  filtered-out rows rather than showing gaps.
- `archive/static/style.css`: `.coverage-filters`/`.coverage-filter-check`/
  `.coverage-filter-count`/`.coverage-yesno-col` styling for the new
  section, deliberately scoped narrowly (comment notes this file is
  Archive-only, no resolver counterpart to keep in sync, same as the
  pre-existing coverage-table rules right above it).
- `README.md` (the `/coverage` route description and the `crud.py`
  function list in "Project structure") and `BACKLOG.md` (this entry
  moved here) updated per this repo's doc-drift convention.

**Scale check before choosing client-side filtering**: production
`/coverage` currently renders 871 jurisdiction rows in the existing
"Every place we've covered" table with zero pagination (confirmed live,
`document.querySelectorAll('#coverageTable tbody tr').length` on
`https://redtaperecordings.com/coverage`) — small enough that adding a
second, similarly-sized table with client-side sort *and* filter is a
direct extension of the same already-working pattern, not a new scaling
risk. `_is_empty_page_condition()`'s own docstring nearby independently
confirms ~1,200 total `MeetingPage` rows in prod as of 2026-08-17, the
same order of magnitude.

**Verification**:
- New tests in `tests/test_footer_and_coverage.py`: a direct-platform
  meeting (Granicus, full video+agenda+transcript → every yes/no column
  True, `outcome == "success"`, detail == video == "Granicus"); a
  synthetic-but-real-shaped LIMS wrapper case (confirmed live via a
  throwaway script before writing the test that
  `app/utils/jurisdiction_enrich.py`'s `_KNOWN_DOMAINS` forces
  `lims.minneapolismn.gov` to jurisdiction "Minneapolis, MN"
  unconditionally on ingest, regardless of the payload's own
  `jurisdiction` field — the test asserts against that real value, not a
  made-up one); a PrimeGov wrapper case on a synthetic
  `*.primegov.com` subdomain (real domain pattern, confirmed by reading
  `primegov.py` directly) proving the new PrimeGov recognition works and
  `audio_transcript_possible` is correctly False for a
  `video_format == "youtube"` row; an agenda-only CivicClerk case
  (`outcome == "agenda_fallback"`); and two HTTP-level tests confirming
  the new table/headers render and a real ingested row appears in the
  HTML. Full suite: 961 passed, 4 skipped (pre-existing skips,
  unrelated), 0 failed, both before and after.
- Direct Python-level verification of `get_full_jurisdiction_coverage()`
  against 6 realistic seeded scenarios spanning direct-platform success,
  LIMS-wrapper success, PrimeGov-wrapper blank-transcript, agenda-only,
  garbled-transcript (non-English + `_GARBLED_MARKER`), and
  video-only/no-transcript (eScribe) — every row's computed
  detail_platform/video_platform/outcome matched expectations exactly.
- HTTP-level verification: a real local `archive.main:app` instance
  (isolated `DATABASE_URL`, the same 6 seeded rows) served `/coverage`
  and the rendered HTML contained the new table with correct per-row
  values for every column, cross-checked against the Python-level output
  above.
- **Genuine limitation hit, worth recording honestly rather than
  glossing over**: real interactive in-browser click verification (sort
  header clicks, dropdown/checkbox filtering) could not be completed this
  session. This session's agent is worktree-isolated
  (`.claude/worktrees/agent-aa1bfbda75e4e291a`), and the Browser pane's
  own dev-server-launching mechanism runs in a *separate* execution
  context that returned a hard `PermissionError: Operation not permitted`
  reading *any* path under `.claude/worktrees/...` — confirmed by direct
  test, not assumed — and, separately, a `getcwd()`-level failure trying
  to reach even the *shared* checkout's own `.venv` from that same
  context (confirmed by finding the pre-existing `archive-verify` launch
  config, unrelated to this session, failed identically). Neither
  worktree-local nor scratch-directory-`--app-dir` workarounds could
  route around this — it's a structural boundary between the agent's
  worktree and the Browser pane's own process-launching context, not a
  fixable mistake in how the dev server was started. The sort/filter JS
  itself carries real risk mitigation despite this: `initSortableTable()`
  is a straight generalization of the exact algorithm
  `archive/static/coverage.js` already used for the pre-existing
  `#coverageTable` (verified live in-browser previously — see this
  file's 2026-08-16 "wave 2 item 9" entry above — "sort-by-click ...
  confirmed against a locally-seeded table"), and the new filter code is
  plain `dataset` attribute checks + `display: none` toggling with no
  novel DOM-manipulation risk. Worth a real in-browser click-through next
  time a session without this isolation constraint touches `/coverage`.

## Transcript/agenda segment timestamps past 59 minutes rendered wrong (2026-08-17)

[Done 2026-08-17] BACKLOG.md previously carried this as "Transcript
segment timestamps unintuitive past 59 minutes — don't match video
player's hh:mm:ss," root cause unestablished, with a specific but
incorrect suspicion recorded: that `formatTime()` in
[player.js](app/static/player.js:59) was somehow producing bare
`364:47`-shaped strings. Verified against current code before touching
anything, per this file's own standing rule about not trusting a stale
backlog entry's stated root cause blindly: `formatTime()` (and its
identical twin in `archive/static/meeting_page.js`) is structurally
correct — `h > 0 ? \`${h}:${pad(m)}:${pad(s)}\` : \`${m}:${pad(s)}\`` —
and can't produce that output for any input, and `meeting_page.js` only
wires click handlers onto already-server-rendered markup; it never
rewrites the timestamp text at all.

**The real bug**: `archive/templates/meeting_page.html` rendered
agenda-item and transcript-segment timestamps directly in Jinja using a
naive `"%d:%02d"|format(seconds // 60, seconds % 60)` at two call sites
(then ~lines 380 and 443) — no hour rollover at all. For a segment at
21887 seconds (6:04:47), that literally computes `21887 // 60 = 364`,
`21887 % 60 = 47` → the string `"364:47"`, exactly matching the real bug
report, while the `<video>` element's own native controls correctly
showed `6:05:03`.

**Fix**: added `format_segment_time(seconds)` in a new
`archive/utils/segment_time.py`, mirroring the correct JS `formatTime()`
logic exactly (`h > 0 ? "{h}:{mm}:{ss}" : "{m}:{ss}"`, zero-padded
appropriately), registered as a Jinja filter (`templates.env.filters
["segment_time"]`) in `archive/main.py` following the same
`templates.env.filters[...]` registration pattern already used for
`warnings_html`/`language_name`/`source_label`/`jurisdiction_display`/
`youtube_thumbnail_url`. Both `meeting_page.html` call sites now use
`{{ x|segment_time }}` instead of the inline format string.

**Test coverage**: `tests/test_segment_time.py` — direct unit tests for
`format_segment_time()`, including the exact real `21887 -> "6:04:47"`
case, the sub-hour case (`125 -> "2:05"`, confirming no regression),
`0`, an exact-hour boundary, minute/second padding within an hour,
`None` defaulting to `0:00`, and fractional-second truncation.

**Live-verified in-browser, not just by reading the logic** (this exact
bug was originally missed that way — see the stale root-cause suspicion
above): ran the Archive service locally against an isolated local SQLite
database (explicitly overriding `DATABASE_URL` to a local sqlite file —
this repo's ambient `.env` at the shared checkout root otherwise gets
picked up by `load_dotenv()`'s upward directory search and points at a
real Postgres instance, which this session deliberately avoided writing
test data into), ingested a real test meeting via `/internal/ingest` with
a genuine 21887-second segment, and loaded the rendered `/m/{slug}` page
in the browser: both the Agenda and Transcript sections now show
`[6:04:47]` (previously would have shown `[364:47]`), with the sub-hour
case (`[0:05]`) and an hour-plus-one-minute case (`[1:01:01]`) also
rendering correctly on the same page.

Full `pytest` (930 passed, 4 skipped) and `ruff format`/`ruff check` both
clean.

## Saved-search email alerts shipped — daily digest cron, not the originally-planned real-time/NoteSubscription design (BACKLOG.md entry corrected 2026-08-17)

[Done, discovered already-shipped 2026-08-17] BACKLOG.md's "Email alerts
for saved searches" entry still described this as pure future work built
on top of a not-yet-built `NoteSubscription` table (part of the much
larger, still-speculative accounts "Note"/profile-pages social-layer plan
in BACKLOG.md's "Accounts + token billing" section) with real-time,
event-driven match detection. Checked the actual code rather than trusting
the backlog text: the feature is fully shipped, via a **materially
simpler mechanism** than either of those two things.

**What actually exists**: `archive/search_alerts.py`'s `run_search_alerts()`
is a daily sweep (`.github/workflows/send-search-alerts.yml`, cron `35 23
* * *`, calling `GET /admin/send-search-alerts` — same GitHub Actions
pattern `daily-report.yml` already uses in place of a paid Render Cron
Job), not real-time/event-driven. It reuses the existing `SavedItem`
table directly (a `last_alerted_at` cursor column added to it) rather
than the proposed new `NoteSubscription` table — no accounts "phase 2" or
`Note`/profile-pages model was needed at all. For every `item_type ==
"saved_search"` row, it re-runs the saved query
(`crud.find_new_matches_for_saved_search()`), resolves a real matching
transcript segment + deep link per match when there's a keyword
(`utils/search.py`'s `find_matching_segment()`), groups every user's new
matches across *all* their saved searches into **one digest email per
user** (`email_utils.compose_search_alert_digest()`) rather than one
email per match, and only advances `last_alerted_at` for searches that
contributed to a digest that actually sent — a failed Resend send or a
missing email never silently drops a match. The recipient's email is
looked up live from Clerk's Backend API at send time and never stored
(`get_user_contact()`), matching `SavedItem`'s existing zero-PII design.
Supports `dry_run` (compose + log, no send, no cursor advance) via both
the admin endpoint and `scripts/send_search_alerts.py`'s CLI wrapper.

**The per-alert unsubscribe token the original entry said would be
needed** (distinct from the existing full-list `/unsubscribe`) is real
and shipped too: `GET /alerts/unsubscribe?token=...`
(`archive/main.py`), signed by `link_tokens.sign_saved_item_id()`.

**Test coverage**: `tests/test_search_alerts_matching.py`,
`tests/test_search_alerts_run.py`, `tests/test_search_alert_email.py`,
and `tests/test_search_alerts_routes.py` — matching logic, the full sweep
(grouping, cursor-advance-only-on-send, dry-run), email composition, and
the HTTP-level admin/unsubscribe routes.

**Correcting the record**: this is genuinely a different feature from what
BACKLOG.md described, not the same one finished — the entry's real-time,
event-driven, one-email-per-match design (`marketing/LIFECYCLE_EMAILS.md`'s
#5, "People are talking about…", subject `Somebody said "[keyword]"`) was
never built; what shipped went straight to what that same entry called
the "digest variant... flagged as later still." The unrelated
`NoteSubscription`/`Note`/profile-pages social-layer plan in BACKLOG.md's
"Accounts + token billing" section is untouched by this — it remains a
real, separate, still-unbuilt piece of future scope (in-profile
notifications specifically still have no equivalent to this email path),
not duplicated here.

## Empty ("zero-value") meeting pages excluded from browse/sitemap/feed at query time; Upcoming/Recent date pills (2026-08-17)

[Done 2026-08-17] Started as Ryan's idea for a morning Routine that would
skim `/meetings?has_transcript=false` and *delete* meetings with no video,
no agenda and no transcript; refined the same minute to "hide them from
search results instead". Measured live before deciding anything
(production `/meetings` subtitle counts): 1,219 archived meetings → 179
with `has_transcript=false` → **39 with `has_transcript=false&has_agenda=
false`**. Curl'd each of the 39 `/m/` pages: **17 rendered "no video
found"** (the true nothing-at-all set — including the two known bare
`/m/meeting` / `/m/meeting-890af1` junk pages), 22 still embedded a
player (video-only, thin but not zero-value). **Several of the 17 were
recent or not-yet-held meetings** — `sarasota-county-fl-2026-08-25-bcc-
regular` (8 days in the future), the two Santa Barbara 2026-08-11 pages
(6 days old) — exactly the "captions land days-to-weeks later" case
`ARCHIVE_RECHECK_AFTER` exists for, so any rule acting on "empty today"
without a date guard would have removed pages about to become real.

**Decisions (Ryan, 2026-08-17):** (1) don't delete — there was no
`MeetingPage` delete path at all (only per-account `SavedItem` deletes),
and adding one would orphan `SavedItem.meeting_page_id`, break already-
shared `/m/` deep links, and re-create the page under a possibly-different
slug on the next paste; (2) make "zero-value" a *default exclusion* in
`list_pages()` and the sitemap; (3) keep it off under an explicit
`has_transcript=false` filter, since that's how gaps get found; (4) the
"how do these get in at all?" question (the push gate in `app/main.py` is
`segments or agenda_items or agenda_link`, yet 22 video-only pages exist)
is deliberately *not* being chased — junk URLs to fake sites will always
be pasteable, so a live exclusion beats policing the entry point.

**Built** (PR from a git worktree, since two other sessions were active
in `archive/` at the same time — both pinged and confirmed
non-overlapping regions):
- `archive/db/crud.py` `_is_empty_page_condition()`: SQL predicate =
  `video_url` NULL/empty AND `agenda_link` NULL/empty AND
  `NOT _has_agenda_condition()` AND `NOT EXISTS (any TranscriptVersion)`
  — *any* version, not just default, so a demoted-but-real transcript
  still counts. The EXISTS uses an `aliased(TranscriptVersion)` +
  `.correlate(MeetingPage)` because `list_pages()` already outer-joins
  `TranscriptVersion`; without the alias SQLAlchemy auto-correlated that
  table away too and raised "returned no FROM clauses" (caught by the
  new tests on the first run). Applied by default in `list_pages()`
  **only when both `has_transcript` and `has_agenda` are `None`**, and
  unconditionally in `list_all_page_slugs()` (sitemap) and
  `list_recent_pages_for_feed()` (feed). Query-time, not a stored flag or
  a Routine: self-healing (a page reappears the moment a recheck fills
  anything in, no un-hide step; a future-dated meeting is never
  permanently judged) and no schema change (a new column would be an
  Alembic-migration case, and prod still hasn't run `alembic stamp head`).
- `archive/main.py` `/m/{slug}`: `page_is_empty` (Python twin of the SQL
  predicate) → `meeting_page.html` emits `<meta name="robots"
  content="noindex">` for empty pages, alongside the existing
  `platform == "unknown"` case. The page still serves 200 so shared links
  keep working. This is the same sitemap-vs-noindex consistency the
  2026-08-17 `generic_fallback` fix established, and directly targets
  Search Console's still-open "Page indexed without content" (a
  title-only shell is the likeliest shape for that verdict).
- **"Upcoming" / "Recent" date pills** (Ryan's follow-on question, same
  session — answered yes and built): new pure helper
  `archive/utils/date_status.py` (`meeting_date_status(date,
  has_transcript, today)` → `"upcoming"` if the meeting date is after
  today, `"recent"` if within `RECENT_MEETING_WINDOW` = 30 days *and* no
  transcript version exists, else `None`; tolerant ISO parse; UTC "today",
  off by at most a calendar day around midnight — fine for a soft label).
  Rendered as an inline `.date-status-pill` next to the date on
  `/meetings` rows (`meeting_list.html`) and as a one-line
  `.date-status-notice` under the title on the meeting page pointing at
  the existing "Refresh this page" control. Neutral-toned, untilted, so
  it doesn't compete with the green TRANSCRIPT stamp. "Recent" is gated
  on no-transcript on purpose (nothing left to wait for once one exists);
  "Upcoming" is not (a pre-posted agenda is still upcoming). The 30-day
  window is a judgment call matching `ARCHIVE_RECHECK_AFTER`'s reasoning,
  named as a constant to tune.

**Verified**: `tests/test_date_status.py` (8 unit tests, pinned `today`)
+ `tests/test_empty_page_exclusion.py` (8 integration tests: empty hidden
from default browse but present under `has_transcript=false` and
`has_transcript=false&has_agenda=false`; each of video-only /
agenda-link-only / agenda-items-only / transcript-only is *not* empty;
an empty page reappears after a later ingest fills it in; sitemap + feed
exclusion at the crud level; empty page serves 200 with noindex while a
real page has none; date_status values per row and the pill/notice
markup on `/meetings` and `/m/`). Full suite 920 passed. Then in-browser
against a seeded scratch SQLite Archive (5 pages: empty shell, upcoming
agenda-link-only, recent video-only, 2021 video-only gap, recent with
transcript), served through the resolver proxy so real CSS applied:
default browse showed 4 of 5 with RECENT and UPCOMING pills on exactly
the right rows and none on the old gap / transcript rows;
`?has_transcript=false` showed the empty shell again; the upcoming and
recent meeting pages showed the notice under the meta line; the empty
page returned 200 with one `noindex` meta and the recent page none;
`/sitemap.xml` and `/feed.xml` each listed the 4 non-empty slugs only;
no server errors. Expected post-deploy effect on prod: the 17 empty
pages drop out of browse/sitemap/feed (sitemap was 1,223 URLs before the
generic_fallback fix — compare after), and any of them that later gain
video/captions come back on their own.

## WO-10 — migrations survive deploys: Archive `preDeployCommand: alembic upgrade head`, `create_all()` gated to SQLite, CI `alembic check` (2026-08-17)

[Done 2026-08-17 for the Archive; resolver half tracked live in
`BACKLOG.md`] The last open wave of `AUDIT_EXECUTION_BRIEF.md`, done the
evening of the day that produced its best motivating example (PR #116's
model column deploying ~13 minutes ahead of its `ALTER TABLE` → every
`meeting_pages` read on the Archive raising `UndefinedColumnError` until
Ryan ran the migration by hand — the fourth schema-ordering incident
after 2026-08-09/10/13). Ryan: "do the WO-10 preDeployCommand".

**The brief's strict order, and how it was honored in one PR**: step 2
(reconcile `alembic_version` with `head`) was already true for the
Archive that day — Ryan had run `cd archive && alembic upgrade head`
twice on the Render shell (`bf4f54a11e5f`, then `c1d2e3f4a5b6`), so
`current == head`. Verified the deeper precondition before automating
anything: on a fresh Postgres, `alembic upgrade head` from empty then
`alembic check` reported **no missing model tables or columns** (the
only diffs were the three deliberately unmapped Postgres-only objects —
the pg_trgm index, the generated `search_tsv` column and its GIN index
— which `alembic check` sees as "in DB, not in models"; expected). So
steps 1 and 3 could land together safely for this service.

**Built** (`render.yaml`, `archive/db/engine.py`,
`.github/workflows/test.yml`, `tests/test_archive_init_models_gate.py`):
- `rtr-deeplink-archive`: `preDeployCommand: cd archive && alembic
  upgrade head`. Render runs it after the build, before the new instance
  is switched live; a failure cancels the deploy and the previous build
  keeps serving — the ordering guarantee this repo never had. Idempotent
  ("already at head" is a no-op), runs with the service's own
  `DATABASE_URL`, alembic from `archive/requirements.txt`. The worker
  shares the DB and deliberately does NOT run migrations (one owner; two
  concurrent `upgrade head`s would race on the same DDL).
- `archive/db/engine.py::init_models()` returns immediately on
  `engine.dialect.name == "postgresql"`; `create_all()` runs only for
  SQLite (local/tests). Gated on the dialect, not an env var, so the safe
  path needs no configuration. This is the change that removes the
  silent-drift mechanism itself: a new table can no longer appear in
  prod without a migration.
- CI: `alembic upgrade head` on a fresh SQLite from the migration chain,
  then `alembic check` — fails a PR that edits a model without a
  migration. Runs on SQLite deliberately: the PG-only objects are
  dialect-guarded in migrations and unmapped on models, so both sides
  omit them and the check is exact (verified clean before adding).
- 2 tests pin the gate (a stub engine reporting `postgresql` is never
  connected to; the real SQLite engine still runs `create_all()`).
- Docs: `CLAUDE.md`'s "brand-new table needs no manual migration"
  bullet — the guidance that made drift invisible — rewritten to the new
  rule (every Archive schema change = one migration, nothing else; two
  corollaries: code must tolerate the pre-migration schema or feature-
  detect, per `crud._fts_available()`; prefer generated columns over
  column + backfill); `archive/alembic/README.md`'s production section
  now leads with "the deploy does this"; `AUDIT_EXECUTION_BRIEF.md`
  updated; the `BACKLOG.md` incident entry closed with the resolver
  follow-up split out.

**Not done, deliberately — the resolver (`app/`)**: its Alembic history
(2 revisions) has never been stamped in prod, so the same
`preDeployCommand` there would fail on first run (the baseline `CREATE
TABLE`s against existing tables — the brief's own warning). The one-time
`alembic stamp head` needs the *resolver* service's Render shell (Ryan);
`render.yaml` carries a comment at the exact spot with the exact steps,
and `BACKLOG.md` tracks it. The resolver has never had a schema
incident, which is why it's the half that could wait.

**Verification of the mechanism itself**: the PR's own deploy is the
first run — Render's Events tab for `rtr-deeplink-archive` shows a
"Pre-deploy" step with `alembic upgrade head` logging that it's already
at head, then the deploy going live; `/api/health` 200 after. The
acceptance criterion "a test migration adding a column deploys cleanly
with no manual step" is met by the *next* real Archive migration —
which, per `CLAUDE.md`'s new rule, will be written to tolerate either
order anyway.

## Jurisdiction hub pages — `/j/{slug}`, one landing page per government, threshold-indexed (2026-08-17)

[Done 2026-08-17] Promoted from `CLAUDE_BACKLOG.md`'s "Jurisdiction hub
pages" idea (Ryan: "the jx pages would be good next", after the state
pages, search rewrite and Archive GA instrumentation had all shipped the
same day). Targets the "[city] council meeting video / transcript"
searches, and doubles as the hook page for city-specific outreach.

**The measurement that shaped the design** (scraped from the live
`/state/*` tables, read-only): the archive is *wide and shallow* — 574
jurisdictions with a state, **439 (76%) with exactly one meeting**, 110
with two, 25 with three+, only two with 10+ (San Diego 42, Napa 24). A
one-meeting "hub" is a near-duplicate of that meeting's own `/m/*` page
— thin/doorway content to a crawler — so building 574 indexable hubs
would have been an SEO liability. Hence: **every hub renders** (real
navigation, and every `/m/*` page links to its hub) but **only hubs with
≥ `crud.JURISDICTION_HUB_MIN_INDEXABLE` = 2 meetings are indexable**
(135 today, covering 47% of meetings) and in `sitemap.xml`; below that
the page carries `noindex` and a "know of another? paste its link" note.
Evaluated live per request, so a singleton hub flips to indexable by
itself when the bulk-ingest scripts land its second meeting — the
threshold tracks depth with no code change. One dial; 3 is the
conservative alternative. The other two open questions from the idea
were answered the same way: **slug scheme** = `jurisdiction_hub_slug()`
(`archive/utils/jurisdiction_format.py`), the slug of the *display* form
(`format_jurisdiction_display()`, which strips "City of" but keeps
"County of"/"City and County of") via the app's one slug rule
(`slugify_text()`, public form of `build_base_slug()`'s per-part rule),
so raw-string variants of one government ("City of Napa, CA" / "Napa,
CA" / casing) consolidate into `napa-ca` while real distinctions stay
separate governments (`county-of-napa-ca`), and " (Canada)" (a display
marker) is stripped; **sitemap timing** = immediately, threshold-gated.

**Built**: `crud._hub_groups()` (one `GROUP BY jurisdiction` over
indexable, non-empty pages — `platform != "unknown"` and
`~_is_empty_page_condition()`, the sitemap's posture — aggregated by hub
slug in Python; a few hundred rows, run per request, no cache/staleness,
**no schema change**), `get_jurisdiction_hub_data(slug)` (every meeting
for the hub's raw strings newest-first with transcript badges, counts,
date range, transcript count, `meeting_body` breakdown, state
abbr/name/slug, `indexable`), `list_indexable_hub_entries()` (sitemap,
real lastmod). `get_state_page_data()` now groups its government table by
hub slug too (so variants are one row) and each row links to its hub.
Route `/j/{hub_slug}` in `archive/main.py` (404 unknown/empty; same
in-route pattern), `jurisdiction_page.html` (title/description/canonical/
OG, `BreadcrumbList` JSON-LD Home › State › Jurisdiction + breadcrumb
nav, lede, body counts, full list, links to `/state/{slug}` and the
`/meetings?jurisdiction=` search, RSS alternate), resolver proxy
`/j/{path}` (same as `/state`), sitemap `<url>` entries, "More
{Jurisdiction} meetings" link on every `/m/*` page next to the state
link, small CSS.

**Verification**: 10 new tests (`tests/test_jurisdiction_hubs.py`, real
seeds with jurisdictions no other file uses — Yountville, CA across two
raw variants + a platform-unknown row; Rio Vista, CA singleton): slug
merging/distinctions, consolidation + counts + bodies + unknown
exclusion, below-threshold not indexable, unknown → None/404, sitemap
threshold, route content/breadcrumb/links, noindex + thin note, meeting-
and state-page links (state table shows the variants as ONE row),
resolver proxy route present. One existing state-page test updated to
identify rows by hub slug (its "Napa, CA" seed now correctly merges with
another test's "City of Napa, CA"). Suite 970 green; JS 34/34. Verified
in-browser through the resolver→archive proxy: styled hub with
breadcrumb, lede, "Town Council (2) · Planning Commission (1)", three
meetings incl. the merged variant, badges; singleton hub renders with
`noindex` + note; state table one Yountville row → `/j/yountville-ca`;
sitemap lists only the indexable hub; meeting page shows "More
Yountville, CA meetings". README: new `/j/{slug}` section + route/crud
listings.

**Not done / worth watching**: no `/coverage` link list to hubs (135+
links is too many there; the state pages are the hub index — the
`/coverage` "Browse by state" → state page → hub path is the intended
route). No `ItemList` JSON-LD (Breadcrumb is the cheap, real win; an
ItemList of 40 meetings adds page weight for unclear return). Stateless
jurisdictions (state legislatures, "NYC Council"-style names) get hubs
without a state breadcrumb level. Whether Google treats 135 two-meeting
hubs as substantive is the real open question — the threshold constant
is the dial if Search Console starts flagging them.
## Search Step 2a: Postgres full-text search (`search_tsv` generated column + GIN), feature-detected, `OR`/stemming/`sort=relevance` (2026-08-17)

[Done 2026-08-17 — code merged; the prod migration run is the one
remaining operational step, see below] Ryan: "and also do 2a", right
after `pg_stat_statements` settled that the DB was the whole ~27s of a
common-word search (LIKE scans averaging 16.5s each under real load vs
4.7s in isolation on a 64MB-`shared_buffers` Postgres — I/O-bound
detoasting of the 77MB corpus per query, which no LIKE tuning could beat;
see the Step 1 entry below and #143's DB plan bump).

**Schema** (`archive/alembic/versions/2026_08_17_2100-c1d2e3f4a5b6_…py`,
Postgres-only, no-op on SQLite): `ALTER TABLE meeting_pages ADD COLUMN
search_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english',
left(coalesce(search_corpus,''), 3000000))) STORED` + `CREATE INDEX
CONCURRENTLY … USING gin (search_tsv)` inside an Alembic
`autocommit_block()`. A *generated* column, deliberately: Postgres
computes it from `search_corpus` on every INSERT/UPDATE, so there is no
ingest-time code to keep in sync and no one-time backfill script — the
two seams that produced #116's outage and #127's OOM the same morning.
`left(…, 3e6)` caps the input so the expression can never exceed
tsvector's hard 1MB limit and fail a row's INSERT (measured on the bench:
a 534K-char corpus → 138KB tsvector; prod's largest meeting is ~400K
chars, so the cap is ~9× that). `'english'` config; the Spanish-language
minority degrades to near-`simple` stemming, not wrong results. **The
column is NOT mapped on `MeetingPage`** — SQLite/`create_all()`/ORM
inserts never see it; crud references it only via
`literal_column("meeting_pages.search_tsv")`.

**Query** (`archive/db/crud.py`): `_fts_available(session)` — Postgres
only, cached 60s, one `information_schema.columns` lookup — decides per
request; when true and not fuzzy, `list_pages()` uses `_fts_condition()`
= `search_tsv @@ websearch_to_tsquery('english', keyword)`, otherwise
the Step 1 LIKE path exactly as before. **This is the third seam
closed**: code and migration can deploy in either order — before the
migration prod simply keeps the LIKE path; within a minute of the
migration FTS is on, no restart. `websearch_to_tsquery()` natively
speaks the `"quoted phrase"` / `-exclusion` syntax `parse_query()`
already accepts, and adds `OR` (closes the "Search bar has no OR
support" backlog item for free), stemming (budget/budgets/budgeting) and
stopword removal; `+`/`&`/`and` (parse_query's no-ops) stay no-ops. Two
deliberate semantic differences from `matches()`, documented in the
docstring: word match not substring ("cat" no longer hits
"concatenate"), and an all-stopword query matches nothing. Membership
and `count(*) OVER ()` come from the GIN index without reading the
corpus, so per-search cost stops scaling with how common the word is
(bench, 1,219 × 300KB docs: `@@ 'budget'` count 0.00s vs LIKE 1.75s /
ILIKE 7.7s; ranked page 0.10s). `sort="relevance"` orders by
`ts_rank_cd(search_tsv, query)` — the one FTS operation that reads the
(much smaller) tsvector per matched row — opt-in via `/meetings?sort=
relevance` (route param, checkbox in the filter panel, carried through
the search form's hidden field and pagination `qs_parts` like `fuzzy`);
default stays newest-first so the UX doesn't change under anyone.
Fuzzy mode is untouched (Python over streamed corpus text; still the
LIKE path for its phrases/exclusions). Snippets are untouched (default-
version segments for the 20 returned rows, `find_snippet()` — an
irregular-stem match like ran→run just yields no snippet, never a wrong
one).

**Verification**: SQLite suite 955 green (the LIKE fallback is what CI
exercises — unchanged behaviour); `tests/test_search_fts.py` = 4
dialect-agnostic shape tests (compiled SQL is `@@ websearch_to_tsquery`,
never LIKE, never touches `search_corpus`; `ts_rank_cd` shape; the LIKE
fallback still finds a real page when `_fts_available` is False; the
sqlite gate never queries) + 5 Postgres-only integration tests, all
green against a real `postgres:16` with the migration applied via
`alembic upgrade head` (the `CREATE INDEX CONCURRENTLY` autocommit path
included): column detected; stemming + word-not-substring; phrase /
exclusion / `OR`; pagination totals; relevance order (dense doc first)
vs default newest; snippet still present. The 13 earlier search tests
(`test_list_pages_sql_authoritative.py`, `test_list_pages_search_
postgres.py`) also pass with FTS active — incl. the "zebrx must NOT
match" exact-mode case and the demoted-version snippet rule.

**Applied to prod 2026-08-17 ~15:10 PT** (Ryan, Archive Render shell:
`cd archive && alembic upgrade head` → `bf4f54a11e5f -> c1d2e3f4a5b6`),
minutes after #143's DB resize landed (`SHOW shared_buffers` → 256MB,
was 64MB). The lock window showed up exactly as predicted — one 503@65s
and two instant 502s in the middle of a measurement — then FTS was on
within the 60s detect window, no restart. **Final production numbers,
clean sequential, via the public domain**, against this morning's:

| query | this morning | after #143 (RAM) alone | after #145 (FTS) |
|---|---|---|---|
| `budget` (~890 matches, "Page 1 of 45") | 26–35s / 502 | 1.47s | **0.39s** |
| `"public comment"` | 503 | — | **0.39s** |
| `flock` | 23–34s | — | **0.49s** |
| `budgets` (stemming, new) | n/a | — | 0.33s |
| `budget&sort=relevance` (new) | n/a | — | 0.41s |
| `flock OR drone` (new; 10 pages vs 5 for `flock`) | n/a | — | fast |
| browse | 0.24s | — | 0.21s |
| `flock&fuzzy=true` (opt-in, Python) | 21s / 503 | — | 10.7s |

So the two levers are separately attributable: RAM took the LIKE scan
from ~27s to ~1.5s (the whole 218MB working set now cache-resident);
FTS took it from there to sub-second and made cost independent of how
common the word is. Result counts unchanged (`budget` still 45 pages —
FTS agrees with the substring path on the common case), 20 highlighted
snippets on page 1. Fuzzy is the one remaining slow mode (opt-in,
UI-labeled); Step 2b (vocabulary table) is designed in `BACKLOG.md` if
it's ever wanted. WO-10's `preDeployCommand: alembic upgrade head` is
still the right follow-up so the next migration needs no shell step —
this one was safe in either order, which is the property future
migrations should keep.

## Search: move to a materialized/indexed column — full saga, closed [Done 2026-08-17]

[Moved from BACKLOG.md 2026-08-17] Built 2026-08-08: `/meetings` search
(title, jurisdiction, agenda text, transcript text — exact and
fuzzy/typo-tolerant modes, see `archive/utils/search.py`) originally
worked by reading each candidate meeting's already-stored JSON and
matching in Python at query time, deliberately, to avoid two things: a
schema change (adding a column to the already-live `MeetingPage`/
`TranscriptVersion` tables — no longer blocked on migration tooling
itself once Alembic was adopted, but still a real production schema
change to run deliberately) and a Postgres-only extension (trigram
search needs `pg_trgm`, which the local SQLite dev fallback has no
equivalent for — would make dev and prod behave differently for the
same query, which this codebase avoids on principle elsewhere too).

**Confirmed hit in production 2026-08-17**: user reported a 502 on
`https://redtaperecordings.com/meetings?q=flock`. Plain `/meetings`
(no `q`) loaded fine, isolating it to the keyword-search path.
Sentry (added the day before, see WO-7 / commit `444cec6`) showed two
`Instance failed: xhv2g — Ran out of memory (used over 512MB)` events
at 7:10-7:11 AM the same day. Root cause in `archive/db/crud.py`'s
`list_pages()`: with a keyword and no other filters, the SQL query
matches every `MeetingPage` row, and the function then loads *every*
`TranscriptVersion.segments` JSON blob for *every version* of *every*
one of those pages into memory in one shot (`transcript_text_by_page`)
before any matching happens — no per-page streaming, no early exit once
`page_size` results are found, no cap on how much transcript JSON gets
materialized at once. Multi-hour meeting transcripts are large
(thousands of timestamped segments each), and this loads all versions
of all meetings regardless of relevance, which was apparently enough
real transcript volume by 2026-08-17 to blow a 512MB instance. So the
"fine at today's scale (dozens of meetings)" original design assumption
was already wrong in production by the time it was actually tested with
a real, popular query term — not just a hypothetical hundreds/thousands
-scale concern.

**The materialized column shipped later the same day** — PRs #116
(schema + GIN-trigram migration), #123 (one-time backfill, run by Ryan
on the Render shell: 1,219 rows), #124 (`list_pages()` rewired to
pre-filter in SQL via `_keyword_conditions_postgres()` against
`MeetingPage.search_corpus`) — plus hotfix #127 (`deferred=True` on the
column, after the freshly-backfilled corpus started riding along on
every plain `select(MeetingPage)` and OOM-crashed the *browse* page —
see this file's "Incident #2 same day" and "Incident: `search_corpus`
column deployed before its migration ran" entries for both that and the
migration-ordering outage from #116's deploy). **Result, measured live
after #127 (2026-08-17 ~10:15 PT)**: browse is fixed for real — plain
`/meetings` 37s→502 before, **0.6s** after; `?page=3` **0.4s**. But
keyword search only went from *crashing* to *slow*: `?q=flock` 23.5s
(~100 matches), `?q=budget` **35s** (~900 of 1,219 meetings match — 45
result pages). No longer 502s, so not an outage, but far outside
anything a visitor will wait for.

**Step 1 shipped 2026-08-17 (same day, ~2h after the numbers above) —
exact-mode search is now SQL-authoritative and O(page_size) in memory:**
full detail in this file's "Search Step 1: SQL-authoritative
`list_pages()`" entry. Short version: `ILIKE '%term%'` on
`search_corpus` is *provably the same predicate* as `matches()`'s
exact mode (same `build_corpus()` over the same four fields, lowercased
on both sides), so the Python re-check over freshly-loaded transcript
JSON was pure overhead — dropped. `has_agenda` moved into SQL, LIMIT/
OFFSET + COUNT(*) pagination, default-version segments loaded only for
the returned page's snippets (preserving the "never show a demoted
version's text" rule), fuzzy words checked in Python over *streamed*
corpus text (~5ms/doc measured, a few seconds archive-wide, off by
default and UI-labeled "slower"). Also fixed: the worker's
transcription-completion path never refreshed `search_corpus`, so
freshly Whisper-transcribed meetings were silently unsearchable on
prod. Verified against a real Postgres 16 + pg_trgm container with the
full migration chain (GIN Bitmap Index Scan confirmed via EXPLAIN for
the exact operator SQLAlchemy emits).

**Step 1 live result was only half the win — and the follow-up (#131,
same day) turned out NOT to move prod at all** (the bench it was built
on didn't model prod's bottleneck): after #129 deployed, search no
longer crashed (fuzzy and `"public comment"` 503→200, counts/snippets
correct) but exact search on common terms was *still* 21–33s — now
provably inside Postgres, on the predicate itself. Rare trigrams
(`quokka`) 0.7s vs common ones ~25s regardless of match count: the
trigram GIN can't be selective for trigrams every 300KB transcript
contains, so every row is rechecked by scanning its whole document,
twice (page query + separate COUNT). Reproduced on a real postgres:16
with 1,219 × 300KB lowercase docs + the GIN index: the two cheap fixes
shipped as #131 — **(a) `LIKE` instead of `ILIKE`** (the corpus is
lowercased at write time and `parse_query()` lowercases terms, so
identical semantics; ILIKE was case-folding every full document per row
via locale — 7.7s→1.75s, same gap with the index disabled), and **(b)
one query with `count(*) OVER ()`** instead of a separate COUNT (halves
the scans). Combined bench: 15.4s→1.76s (8.8×). Two findings recorded,
not fixed at the time: the planner **doesn't even use the GIN index**
for these — the heap is tiny because the corpora are TOASTed, so the
cost model sees "31 pages" and seq-scans, blind to detoast cost
(irrelevant for common terms, where the index can't help anyway; means
rare terms pay a full scan they needn't); and the same bench's stored
`tsvector` column answered `@@ 'budget'` in **0.00s** (count) / **0.10s**
(ranked page) / 0.15s (phrase) — i.e. Step 2a wasn't just ranking, it
was the only path to sub-second on common terms; trigram GIN is
structurally the wrong index for "does this huge doc contain this
common word". **Live after #131: no measurable change** (`budget`
27.5s, `flock` 34.5s, `"public comment"` 31.5s; rare `quokka` 0.2s,
browse 0.24s; clean sequential runs, no warm-up effect) — the bench box
was CPU-bound with the corpus in page cache; prod evidently isn't.

**Resolved 2026-08-17 evening with real DB evidence (Ryan ran EXPLAIN +
`pg_stat_statements` on the Render shell): the DB *is* the whole
27–33s, and it runs 3–4× slower for the app than in isolation.**
`EXPLAIN (ANALYZE, BUFFERS)` of the app's exact query, run
interactively: **4.7s** (Bitmap Index Scan on the trigram GIN — the
index *is* used, contrary to the bench-box guess above; 901 candidates,
9 removed by recheck; `meeting_pages` is 77MB of which the heap is
1.6MB — 98% TOAST; `shared_buffers = 64MB`). But `pg_stat_statements`
for the same statements as the *app* ran them: **49 calls, mean 16.5s
(page) + 16.7s (count) ≈ 33s per search, max 41s/46s** — and a bare
`SELECT id … WHERE search_corpus ILIKE $1` from an app/script path:
mean **32.9s**. Same query, same data: the difference is *load*. This
Postgres had 64MB of buffers, cold TOAST reads at ~3MB/s (a 20-row
snippet `segments` fetch: mean 2.8s, max 7.9s — `EXPLAIN` hid it
because it never sends rows), and that day also absorbed the worker's
5-minute sweeps (fixed the same day, see "Worker auto-transcription
candidate sweep"), crawler searches (2 full 77MB scans each pre-#131),
and **14 ad-hoc interactive queries over 10s each totalling 1,043s
(17 min) of saturation** — so nothing stayed cached and every scan ran
at a fraction of its isolated speed; #131's CPU savings were invisible
against that. **Conclusion, a finding not a hypothesis: any design that
reads the corpus per search is bounded by this DB's I/O; only answering
from an index (a `tsvector` GIN — count and membership without
touching TOAST) or a DB with enough RAM to keep the 77MB corpus
resident escapes it.** `shared_buffers=64MB` implied Render's smallest
Postgres tier; the next tier up (#143) made the whole working set
cache-resident, see below.

**Step 2a: relevance ranking + stemming via Postgres full-text search
— built and shipped 2026-08-17.** Full detail in this file's "Search
Step 2a" entry. Alembic revision `c1d2e3f4a5b6` adds
`meeting_pages.search_tsv` as a `GENERATED ALWAYS AS
(to_tsvector('english', left(search_corpus, 3e6))) STORED` column + GIN
index (Postgres-only; no backfill script and no ingest change — Postgres
computes it, closing the two seams that bit #116); `list_pages()`
feature-detects the column at runtime (`_fts_available()`, cached 60s)
and uses `search_tsv @@ websearch_to_tsquery('english', q)` when
present, else the LIKE path — so code and migration deploy in either
order, closing the third seam. Membership + count come from the GIN
index without reading the corpus, so cost stops scaling with how common
the word is; stemming, stopwords and `OR` came free (closing the
separate "search bar has no OR support" backlog item — see below);
`?sort=relevance` (`ts_rank_cd`) is opt-in with newest-first still the
default. **Applied to prod 2026-08-17 ~15:10 PT**, minutes after #143's
DB resize landed (`shared_buffers` 64→256MB). Final production numbers:
`budget` 26–35s → 1.47s (RAM alone) → **0.39s** (FTS); `"public
comment"` 503 → **0.39s**; `flock` 23–34s → **0.49s**; `flock OR drone`
works; `budgets` stems; browse 0.21s. Fuzzy remained the one slow mode
(opt-in, UI-labeled "slower") — `flock&fuzzy=true` was **10.7s** at this
point, tracked as Step 2b below.

**Step 2b: trigram-indexed `search_vocabulary` table for fast fuzzy
search — built and shipped 2026-08-17/18.** Fuzzy was correct and no
longer crashed after Step 1, but stayed inherently O(archive) CPU in
Python (tokenize every corpus, ~4ms each) because `matches()`'s bounded
Levenshtein against real corpus words has no recall-safe SQL equivalent
over whole documents — `word_similarity()` on a 130KB doc is either
useless (too loose a threshold lets everything through) or lossy (a
selective threshold drops genuine 2-edit typos on 6-letter words). The
fix: PRs #159 (schema — `SearchVocabulary`, a distinct, page-agnostic
GIN-trigram-indexed word table, cross-dialect on the model like
`search_corpus` itself since populating it needs a real
application-level write path, unlike `search_tsv`'s generated column;
`_refresh_search_corpus()` — already the single choke point keeping
`search_corpus` in sync from both `ingest_resolution()` and the
worker's transcription-completion path — extended to also upsert each
corpus's words via the new `_upsert_vocabulary_words()`), #160
(`scripts/backfill_search_vocabulary.py`, one-time sweep for
pre-existing pages), #162 (`list_pages()` wired to use the vocabulary
when available via the new `_vocab_available()`, mirroring
`_fts_available()`'s exact feature-detect pattern: each fuzzy word
longer than 4 chars is trigram-matched against the vocabulary
(`_vocab_candidate_stmt()`, the `%` operator so the GIN index is
actually usable), every candidate re-verified against the *exact*
Levenshtein function `matches()` already uses — byte-for-byte parity,
the trigram step is purely a fast candidate generator, never the final
decision — and the confirmed real words checked against `search_corpus`
via the already-fast Step 1 LIKE path; words ≤4 chars skip vocabulary
lookup per `matches()`'s own "short words require exact" rule; a fuzzy
term with zero real matches anywhere in the archive correctly fails the
whole query via `sql_false()`, not a silently-skipped condition).

**#159 deployed clean via WO-10's new `preDeployCommand`** — the first
Archive migration to land after WO-10 shipped, and it worked exactly as
designed: Render's pre-deploy hook ran `alembic upgrade head`
automatically before the new code went live, so the "model column
deployed ahead of its migration" outage class that hit #116 didn't
repeat here. Confirmed via the Render Events log (`Starting pre-deploy:
cd archive && alembic upgrade head` → migration applies → `Pre-deploy
complete!` → app goes live) and `/internal/schema-info` afterward.

**Real incident, 2026-08-18: the backfill script's first real run hit
PostgreSQL's hard 65535-bound-parameters-per-statement protocol limit,
fixed same-day as hotfix #163.** `_upsert_vocabulary_words()` built one
`INSERT` with one bound parameter per word; real-time ingest only ever
passes one page's distinct words at a time (a few hundred to a couple
thousand), so this was never exercised near any limit before. The
backfill script passes an entire *batch's* union of words (200 pages at
once), and a real batch produced 62,000+ distinct words in one call —
over the limit. Not a production outage (real-time ingest was never at
risk, only the one-time backfill was blocked from completing). Fixed in
the shared helper itself, not the script, so every caller is protected:
`_upsert_vocabulary_words()` now chunks into batches of 2000 words per
`INSERT`. New regression test reproduces the exact failure shape
(70,000 words in one call), confirmed fixed against a real `postgres:16`
container before merge. Backfill re-run afterward completed cleanly:
1,243 pages → ~337,000 distinct vocabulary words across 7 batches, no
errors.

**Verified against real Postgres throughout** (a recurring practice for
every step of this saga, given CI is SQLite-only and cannot exercise any
of the Postgres-only paths): #162's own test suite (`tests/
test_search_fuzzy_vocab.py`, 9 tests) caught two real things before
merge — a genuine pytest-asyncio/asyncpg incompatibility unrelated to
the search logic itself (fixed with `loop_scope="session"`, same fix
`test_search_fts.py`/`test_list_pages_search_postgres.py` already
needed), and a lesson repeated from earlier in this same saga: a bare
`EXPLAIN` run through a bound parameter got a different, more
conservative *generic* plan than an ad-hoc literal query — so the test
suite asserts real timing (fuzzy search stays under a second against a
5,000+ word synthetic vocabulary) rather than a fragile EXPLAIN
plan-shape. Structurally, `search_vocabulary` holds distinct *words*,
not per-meeting *transcripts*, so even its worst-case fallback plan
scans a small, bounded table — never gigabytes of TOASTed transcript
text the way `search_corpus`'s own worst case did.

**Final measured production numbers (2026-08-18, after #163's backfill
completed)**: real typo `trafic`→`traffic` **~2.2s** (was ~10s+ class of
streamed Python before Step 2b existed at all); `budget&fuzzy=true`
**~2.1s**; `flock&fuzzy=true` **~5s** (down from 10.7s at the end of
Step 2a, but the smallest win of the three — `flock` has several short,
common, genuinely-1-edit-distance real-word neighbors in the vocabulary,
so its confirmed-candidate OR-set is larger than `trafic`'s or
`budget`'s, and checking several individually-common words against
`search_corpus` is real work even on the fast Step 1 path; recorded
honestly as a real, unexplained-further variance rather than claimed as
uniformly fixed). Fuzzy is no longer O(archive), but — unlike exact
mode and FTS, which both went to sub-second — it did not reach
sub-second uniformly; a real, live finding for whoever revisits fuzzy
performance next, not a claimed final state.

**Also closes** the separate "Search bar has no `OR` support" backlog
item (Step 2a: `websearch_to_tsquery()` understands `a OR b` natively on
the FTS path; `parse_query()` itself still has no OR, which only matters
for the LIKE-fallback/fuzzy paths — dev/CI and pre-migration Postgres —
where OR was never a live gap worth blocking on).

## Worker auto-transcription candidate sweep: from 102MB of transcript JSON every 5 idle minutes to one anti-join (2026-08-17)

[Done 2026-08-17] Found while chasing prod search latency (below); Ryan
asked for exactly this ("have that worker use the filter for no
transcripts to limit how many meetings it pulls each time"). `worker/
main.py` calls `crud.find_auto_transcription_candidate()` every
`AUTO_GENERATION_CHECK_INTERVAL_SECONDS = 300` while its queue is empty.
The old shape: `select(MeetingPage)` for all ~1,219 pages, then per page
`_has_good_transcript()` — which selected the **full `TranscriptVersion`
entity, `segments` JSON included** (not deferred) just to evaluate
`not version.segments` — and `_in_auto_transcription_cooldown()`, which
selected full `TranscriptionJob` rows including `partial_segments` (an
in-progress transcript as JSON). ~2,400 round-trips per sweep, all 102MB
of default-version transcript JSON (`sum(pg_column_size(segments))`,
Render shell) pulled to the worker to make one decision, on a Postgres
with `shared_buffers = 64MB`. **`pg_stat_statements` (enabled by Ryan the
same evening) showed the `_has_good_transcript()` select as the #1
consumer of production DB time: 218,480 calls, 2,822s (47 min) total,
mean 13ms, max 1.1s — more than everything else in the top 8 combined**;
218k ÷ 1,219 ≈ 180 sweeps since stats began. Its docstring said "fine at
today's scale (dozens of meetings)" — the same stale assumption the
search OOM disproved that morning.

**Fix (`archive/db/crud.py`)**: `_EMPTY_CONTENT_HASH = _content_hash([])`
(sha256 of "" — both version-creating paths set `content_hash` via
`_content_hash()`, so "has real content" is decidable from that indexed
64-char column, never `segments`); new `_good_default_transcript_exists()`
— a correlated `EXISTS` over `is_default` / `content_hash != EMPTY` /
`transcript_warnings` text-cast `NOT LIKE` the two quality markers (plain
ASCII, so exact on Postgres `json::text` and SQLite; `NULL` warnings
guarded explicitly since `NOT (NULL LIKE …)` is NULL); `_has_good_
transcript()` now selects only `content_hash, transcript_warnings` (same
decision, for its other callers — the recheck cadence and two `/internal`
listings that loop the same way); `_cooldown_active(jobs_newest_first,
now)` pure helper shared by `_in_auto_transcription_cooldown()` (now
selects `status, updated_at` only) and the finder; `find_auto_
transcription_candidate()` = one candidates query (`WHERE NOT
EXISTS(good default)`, `ORDER BY created_at ASC`, light columns) + one
`status/updated_at` history query for those ids, then the unchanged
escalating-cooldown rule in Python until a candidate passes. Same
"oldest page without a good transcript and not in cooldown" result.

**Verification**: suite 925 green with zero changes to the three
existing candidate-finder tests; two new tests (`tests/test_
transcription_jobs.py`): the compiled predicate/cooldown SQL names no
`segments`/`partial_segments` column, and garbled/hallucinated/clean
default versions classify identically through the SQL predicate and the
per-page helper. On a real `postgres:16` with the full migration chain
(session-scoped loop, see the search entry): the six worker-path tests
pass, and `EXPLAIN (ANALYZE, BUFFERS)` of the candidate query is a **Hash
Anti Join, 8 shared buffers, <0.1ms** — vs 102MB moved before. Explicitly
*not* claimed: that this sweep was the search-latency contention (it was
~5% duty); the search finding is separate, below.

## Search Step 1: SQL-authoritative `list_pages()` — exact search O(page_size), fuzzy streamed, worker corpus gap closed (2026-08-17)

[Done 2026-08-17] Follows the two same-day incidents below. After hotfix
#127, browse was 0.6s but keyword search was still 23–35s and 503'd on
common terms (`"public comment"`, fuzzy anything) — measured live:
`quokka` (rare, ~1 match) 0.7s; `flock` (~100) 23.5s; `budget` (~900 of
1,219) 35s; `"public comment"` 503@65s; `flock&fuzzy` 503@67s. Latency
was a straight function of match count: after the SQL trigram pre-filter,
`list_pages()` still loaded **every candidate's full
`TranscriptVersion.segments` JSON** for a Python `matches()` re-check
plus snippets, then paginated in Python.

**The key finding that made the fix small**: in exact mode the Python
re-check was provably redundant. `matches()` decides `term in corpus`
where `corpus = build_corpus(title, jurisdiction, agenda, transcript)`;
`search_corpus` is `compute_search_corpus()` — the *same* `build_corpus()`
over the same four fields, lowercased, with `parse_query()` lowercasing
terms. So `search_corpus ILIKE '%term%'` **is** the exact-mode predicate,
byte-for-byte; the "SQL is only a pre-filter, never trusted alone"
caution in #124's docstring was reasonable defensiveness nobody had
checked. Phrases/exclusions are exact in both modes too.

**What changed** (`archive/db/crud.py`, `list_pages()` rewritten;
`_keyword_conditions_postgres()` → `_keyword_conditions()`; `_IS_POSTGRES`
removed): every filter in SQL incl. `has_agenda` (new
`_has_agenda_condition()` — text-cast compare against `[]`/`null`/SQL
NULL, deliberately not `json_array_length()`, which raises on Postgres
for the JSON-`null` rows that really exist — 2 of 30 in the verification
DB); `LIMIT/OFFSET` + one `COUNT(*)`; explicit column select (no entity,
no chance of a deferred column sneaking back); `created_at DESC, id
DESC` for stable pagination across bulk-ingest timestamp ties;
default-version `segments` loaded **only for the returned page's rows**
for snippets — preserving the "never show a demoted version's excerpt"
rule (real bug fixed 2026-08-08) exactly, which the earlier "snippet
from `search_corpus`" idea would have broken. Fuzzy words: SQL can't
decide them recall-safely (worked out from trigram sets:
`word_similarity` at the recall-safe 0.15 threshold #124 used passes
everything on a 130KB doc; anything selective drops genuine 2-edit typos
— `budget`→`bodgat` scores 0.14) — so they're checked in Python by the
unchanged `matches()`, over **streamed `search_corpus` text**
(`session.stream`, `yield_per=200`, one corpus in memory at a time),
never JSON. Measured 4.3ms tokenize + 0.3ms Levenshtein per 250KB doc →
~5.6s archive-wide CPU: slow, opt-in, UI-labeled "slower", no longer a
crash. Same code path on SQLite and Postgres now — *smaller* dev/prod
divergence than #124's `_IS_POSTGRES` branch, and the SQLite suite
exercises the real query.

**Real bug fixed alongside**: `report_chunk_result()`'s
transcription-completion path created + promoted a new
`TranscriptVersion` but never recomputed `search_corpus` — so on
Postgres, where the corpus is the match, every Whisper-transcribed
meeting's transcript was silently unsearchable until something
re-ingested the page. New shared `_refresh_search_corpus(session, page)`
called from both `ingest_resolution()` and the completion path;
regression test drives a real job through `claim_next_chunk()` →
`report_chunk_result()` and asserts the word is searchable.

**Verification**: 8 new tests (`tests/test_list_pages_sql_authoritative.py`:
SQL-authoritative exact match, demoted-version match with `None`
snippet, exclusions/phrases in SQL, all three no-agenda storage shapes,
LIMIT/OFFSET totals across pages, fuzzy typo tolerance + snippet quotes
the real word, fuzzy exclusions in SQL, worker corpus refresh); full
suite 903 green on SQLite with **zero changes to existing tests**. Then
against a real `postgres:16` container with this repo's full Alembic
chain applied (`alembic upgrade head`, incl. pg_trgm + GIN): the 8 new
tests + the other session's 4 Postgres-only search tests all pass;
`EXPLAIN` with `enable_seqscan=off` confirms the exact operator
SQLAlchemy emits (`~~*`) hits `ix_meeting_pages_search_corpus_trgm` as a
Bitmap Index Scan; the has_agenda text-cast predicate confirmed against
real JSON-`null` rows. (Postgres runs need `loop_scope="session"` on the
test file — asyncpg's import-time pool is loop-bound; documented in the
file, harmless on SQLite.) Step 2 (FTS ranking; fuzzy vocabulary table)
backlogged in `BACKLOG.md`'s search entry with full designs.

**Live after #129 deployed (2026-08-17 ~10:57 PT)**: correct and no
longer crashing — `budget` "Page 1 of 45", `flock` "Page 1 of 5", 20
`<mark>` snippets, fuzzy 200 (was 503), `"public comment"` 200 (was 503),
browse 0.56s — **but exact search still 21–33s** (`budget` 26s, `flock`
34s, `"public comment"` 32s, `budget&page=40` 28s, fuzzy 21s). So the
diagnosis above was only half right: the JSON load was *a* cost, but the
dominant one for common terms is the SQL predicate itself. Tell: rare
trigrams (`quokka`) 0.7s vs anything with common trigrams ~25s regardless
of match count — the trigram GIN yields ~every row as a candidate for
trigrams that every 300KB transcript contains, and each is rechecked by
scanning its full document, twice (page + separate COUNT).

**Follow-up #131 (same day, Ryan: "ship (a) and (b) if the numbers hold
up") — benchmarked first on a real postgres:16 with 1,219 × 300KB
lowercase docs (444MB, real-word vocab, "budget" in 75%) + the pg_trgm
GIN index:**

| query | time |
|---|---|
| as deployed by #129: `ILIKE` page + separate `ILIKE` COUNT | 7.7s + 7.7s |
| (a) `LIKE` page / COUNT | 1.75s / 1.76s |
| (a)+(b) `LIKE` + `count(*) OVER ()` in one query | **1.76s total (8.8×)** |
| `ILIKE` vs `LIKE` with `enable_bitmapscan=off` (pure recheck cost) | 7.69s vs 1.79s |
| phrase `"public comment"` ILIKE → LIKE | 8.7s → 2.8s |
| stored `tsvector` GENERATED column, `@@ 'budget'` count / ranked page / phrase | 0.00s / 0.10s / 0.15s |

(a) is semantics-preserving by construction — `search_corpus` is
lowercased at write time (`compute_search_corpus()` → `build_corpus()` →
`.lower()`) and `parse_query()` lowercases terms — while Postgres's ILIKE
case-folds every full document per row via locale before matching; the
identical gap with the index disabled proves it's the recheck, not index
selection. (b) rides the total along as a window aggregate on the same
LIMIT/OFFSET query (a page past the end, no rows, falls back to the
standalone COUNT). New test pins the compiled operator is `LIKE` not
`ILIKE` on the Postgres dialect. Verified on the real-Postgres container
(both test files green; window total == standalone count with LIMIT
applied after). Two findings recorded in `BACKLOG.md`, not fixed: the
planner doesn't use the GIN index at all here (TOASTed corpora → tiny
heap → "31 pages" cost estimate → seq scan; harmless for common terms,
a missed win for rare ones), and the tsvector row above means Step 2a is
the only sub-second path for common terms — trigram GIN is structurally
the wrong index for "does this huge doc contain this common word".

**Live after #131 deployed (clean, sequential, ~30 min post-merge): no
measurable change.** `budget` 27.5s (29s on a warm second run), `flock`
34.5s, `"public comment"` 31.5s, `budget&page=40` 33.8s, fuzzy 21s;
`quokka` 0.2s and browse 0.24s. So the bench, which was **CPU-bound**
(case-folding on an NVMe box with the whole corpus in page cache), did
not model prod's bottleneck: something costs ~25–30s for any common
term, ~0 for rare terms and browse, and doesn't warm up between runs.
Leading hypothesis (unverified — twice today a from-outside diagnosis
was half wrong, so this one is explicitly *not* asserted): **I/O** —
every common-term query detoasts and reads the entire TOASTed corpus
(hundreds of MB) from disk on a small Render Postgres whose cache can't
hold it; halving the scans (b) wouldn't show if the second scan was
already cache-warm, and case-folding CPU (a) is invisible against disk
reads. Settling it needs one `EXPLAIN (ANALYZE, BUFFERS)` from the
Render shell (asked of Ryan; `read=` ≫ `hit=` confirms I/O) plus table/
TOAST size and `shared_buffers`. If I/O, Step 2a — a `tsvector` GIN that
answers word membership from the *index* without touching the corpus at
all — is the fix, and the only one; #131 stays as a correct,
semantics-neutral improvement on any CPU-bound box. Two lessons kept:
(1) benchmark the *deployed* environment's shape (RAM, disk, cache),
not just its query — a bench that fits in page cache can't reproduce an
I/O-bound prod; (2) **never poll a slow endpoint with a short client
timeout** — a `curl -m 15` loop against `/meetings?q=budget` aborted
client-side while the Archive kept running each ~25s scan, stacking
overlapping full-corpus reads for eight minutes and producing a
spurious 75s reading before the loop was killed and a clean sequential
measurement taken.

## [Done — moved from BACKLOG.md 2026-08-17] `/meetings` search & saved items — UI gaps found 2026-08-11

Moved wholesale during the 2026-08-17 backlog triage pass: Ryan's own
triage table marked this whole section `done?` (jurisdiction/state
normalization gaps found and mostly fixed), and every sub-item below
either turned out to be a non-issue on investigation or shipped a real
fix. **One caveat worth flagging rather than silently dropping**: the
first bullet's "Update 2026-08-14" leaves one genuinely open thread —
whether `active_account` evaluates correctly for a real signed-in visitor
arriving via the `/meeting?url=` → `/m/{slug}` redirect specifically has
never been reproduced (needs a real logged-in session this repo's
sessions don't have). If that repro check still matters, it's worth its
own live `BACKLOG.md` entry rather than assuming it's covered here.

- ~~**"Save this meeting"/"Save this search" buttons render for every
  visitor regardless of sign-in status, and an anonymous click silently
  no-ops."**~~ **Investigated 2026-08-13, turned out to already be
  false.** Live-checked as a genuinely signed-out visitor on both
  `/meetings` and a real `/m/*` page — neither Save button renders at
  all. Confirmed via `git log -S "if active_account"` that both
  templates' `{% if active_account %}` gating has been in place since the
  very first accounts-phase commits (`47f4ab5`/`a1ac0ec`), not added
  later — this bug's premise was incorrect from the moment it was
  written 2026-08-12, most likely a misread of the code rather than a
  real regression. No fix needed.

  **Update 2026-08-14: a different, real report — no save button while
  actually signed in**, on
  [redtaperecordings.com/meeting?url=...sccgov.iqm2.com/Citizens/SplitView.aspx?Mode=Video&MeetingID=17601](https://redtaperecordings.com/meeting?url=https%3A%2F%2Fsccgov.iqm2.com%2FCitizens%2FSplitView.aspx%3FMode%3DVideo%26MeetingID%3D17601)
  (the real Santa Clara County meeting from this file's own IQM2 build
  notes). Confirmed structurally: `app/templates/meeting.html` (the
  `/meeting?url=` live-resolve page) has **zero** save-button markup at
  all — grep for "save" across that template and its JS returns nothing
  — so a save button structurally cannot appear there regardless of
  login state, only after the client-side `/api/resolve` call redirects
  to the real `/m/{slug}` page once archived. Live-replayed this exact
  URL (signed out, since this session has no way to authenticate as the
  user): it does redirect correctly to
  `/m/the-county-of-santa-clara-ca-2026-08-11-board-of-supervisors-regular-meeting`
  with real title/jurisdiction/video, and that page's own save buttons
  are correctly gated behind `{% if active_account %}`
  ([meeting_page.html:163](archive/templates/meeting_page.html:163)/
  [:216](archive/templates/meeting_page.html:216)). **Genuinely
  unconfirmed by this investigation**: whether `active_account` evaluates
  correctly for a real signed-in visitor after arriving via this specific
  `/meeting?url=` → redirect chain — that's exactly what the user
  reported failing, but reproducing it needs their actual logged-in
  session, not something checkable without real account credentials.
  Worth a repro check: does the save button appear if a logged-in user
  navigates directly to the `/m/{slug}` URL rather than via `/meeting?url=`?
  If yes, the bug is specifically in whether the Clerk session cookie
  survives this redirect path; if no, `active_account` itself has a
  broader problem.

- ~~**"Save this search" can silently save the wrong/stale search, and
  gives no feedback that it's already been saved.**~~ **Investigated
  2026-08-13: the stale-value bug was already fixed 2026-08-11 (see
  `archive/static/meeting_list.js`'s own header comment/`isStale()`,
  predating this backlog entry) — Save is disabled the moment the search
  box/filters diverge from what's actually applied. The remaining piece,
  the Save/Unsave toggle + visual cue, built 2026-08-13 — full detail in
  `BACKLOG_DONE.md`.**

- **Meeting title/jurisdiction display: casing still inconsistent row to
  row — the state-abbreviation and truncation parts of this gap shipped
  2026-08-11, see BACKLOG_DONE.md.** State names are now normalized to
  their 2-letter abbreviation at Archive ingest time
  (`archive/utils/jurisdiction_format.py`'s `normalize_state_suffix()`,
  wired into `archive/db/crud.py`'s `_find_or_create_page()`), and long
  titles/jurisdiction lines now truncate with an ellipsis on `/meetings`
  (`.calendar-candidate-main a` / `.calendar-candidate-date` in
  `style.css`) instead of wrapping. **Still open, deliberately not
  touched**: city/county/meeting-body name casing itself. That's
  effectively unbounded (tens of thousands of real values) with real
  edge cases a blind `.title()`/casing rule gets wrong (acronyms like
  "MTA"/"ZBA", multi-word or apostrophe'd city names) — every adapter
  still stores whatever casing the source page used, unchanged, and
  fixing that safely would need either a real per-value dictionary/
  exception list or a narrower heuristic (e.g. something like
  `vtt_parser.py`'s existing `normalize_shouting_caption()` ALL-CAPS
  detector, which only re-cases when its own heuristic is confident,
  rather than a blanket `.title()`) — not attempted this pass, since a
  wrong guess here silently corrupts a real name with no easy undo.

  **Also flagged by the user 2026-08-12, real and separate from the above:
  some jurisdictions never had a state at all to begin with** —
  `normalize_state_suffix()` only fires on a trailing `", <State>"`
  suffix, so a jurisdiction with no state component just passes through
  untouched. **Audited, designed, and partly built 2026-08-12 — full
  detail in `BACKLOG_DONE.md`.** A new shared module,
  `app/utils/jurisdiction_enrich.py`, fills in a missing state using real
  US Census Bureau data (counties, places, and ZIP-to-county/ZIP-to-place
  crosswalks, ~3.2MB, checked into the repo) plus a small confirmed-domain
  registry for names that are ambiguous nationally (e.g. "Detroit" is a
  real city in 4 different states) — tried in priority order: confirmed
  domain → unambiguous name lookup → a ZIP-anchored address found in page
  text, scoped to never let a county government's own city-shaped mailing
  address stand in for the county itself (see `BACKLOG_DONE.md` for why
  that's a real, specific trap, not a hypothetical one). Wired into
  **Granicus** (the largest single source of this gap) and **Cablecast**
  so far.

  **Update 2026-08-12: fully wired now, every adapter identified in the
  audit — full detail in `BACKLOG_DONE.md`.** Legistar, PrimeGov, eScribe,
  CivicWeb, and LIMS all now call the same shared
  `jurisdiction_enrich.enrich_jurisdiction_text()`; CivicClerk gets a
  narrower fallback (`lookup_city_state()` when its own API's
  `location.city` is present but `location.state` is empty) since its
  data already arrives as separate structured fields rather than free
  text. Two real bugs in the shared module were found and fixed along the
  way (an "Oklahoma City"-shaped double-normalization collision with
  "Oklahoma borough, PA", and a since-reverted PrimeGov window-cap
  regression — see the bug entry above, still genuinely open). Full suite
  green (551 tests); live-verified against real Cablecast, Granicus,
  PrimeGov, and CivicWeb pages.

  **Still open, real gaps not touched by either pass**: YouTube's
  `uploader`-as-jurisdiction and the cases where no jurisdiction is set at
  all (`generic_fallback.py`, `civicplus.py`) are different problems this
  module doesn't address (not a missing state — a wrong or absent field
  entirely). CivicClerk's new fallback is schema-verified but not
  content-verified — no real customer with a blank `location.state` has
  turned up yet to confirm it fires correctly in practice (covered by a
  synthetic test only, per `tests/test_civicclerk.py`).

  **Update 2026-08-15: a real customer confirms an even blanker case than
  the one flagged above, and it has a clean, already-built fix path.**
  [losaltoshillsca.portal.civicclerk.com/event/4567/media](https://losaltoshillsca.portal.civicclerk.com/event/4567/media)
  (Los Altos Hills, CA — City Council Regular Meeting, June 18, 2026)
  shows a completely blank jurisdiction live on
  [redtaperecordings.com](https://redtaperecordings.com/meeting?url=https://losaltoshillsca.portal.civicclerk.com/event/4567/media).
  Confirmed via `curl` against the real API
  (`losaltoshillsca.api.civicclerk.com/v1/Events/4567`):
  `eventLocation` is `{"city": null, "state": null, ...}` — not just a
  missing state, the *whole* location object is empty. `civicclerk.py`'s
  only fallback ([civicclerk.py:81-86](app/platforms/civicclerk.py:81))
  is `if city and not state: state = lookup_city_state(city)` — it never
  fires when `city` itself is falsy, so `jurisdiction` ends up `None`
  with zero fallback attempted at all, unlike every other adapter this
  audit wired up.

  **Confirmed fix needs no new code, only a new call.**
  `jurisdiction_enrich.extract_jurisdiction_chain()` (built 2026-08-15 for
  `JURISDICTION_METADATA_PLAN.md`, see `BACKLOG_DONE.md`) already resolves
  this exact URL correctly with zero extra network calls — tested live in
  the repo's own venv (`wordninja` isn't in a bare `python3`'s path,
  needed `source .venv/bin/activate` first):
  `extract_jurisdiction_chain(page_text="", html="", url=url)` →
  `"Los Altos Hills, CA"`, via the chain's validated-subdomain tier
  (`losaltoshillsca` → wordninja splits to `["los", "altos", "hills",
  "ca"]` → strips the trailing state abbreviation → `"Los Altos Hills"`
  validates against the Census places table). CivicClerk was never wired
  into this chain — the module's own comment names Swagit and
  generic_fallback as "the first two callers," not CivicClerk, even
  though CivicClerk's blank-location case is exactly the "adapter's own
  primary extraction came up empty" scenario the chain was built for.

  **A second, independent, even richer real signal was found while
  checking "the agenda or anywhere else" per the user's ask — CivicClerk's
  own agenda file is fetchable as plain text and the adapter never reads
  it at all today.** The `Events/{id}` response's `publishedFiles` array
  includes a real "Agenda" entry
  (`GetMeetingFile(fileId=8983,plainText=false)`); calling the same
  endpoint with `plainText=true` instead returns a JSON `{"blobUri": ...}`
  pointing to a SAS-signed Azure blob `.txt` — confirmed live, and its
  real content starts: `"Town of Los Altos Hills / City Council Regular
  Meeting Agenda / Thursday, June 18, 2026, at 5:30 PM / Council Chambers,
  26379 Fremont Road, / Los Altos Hills, CA 94022"`. That's a clean match
  for the chain's stoprule tier (`_STOPRULE_TRIGGER_RE`, "Town of X") —
  actually a *stronger* signal than the subdomain tier, since it doesn't
  depend on wordninja splitting a customer's subdomain cleanly. Today
  `civicclerk.py` never fetches `publishedFiles`/`GetMeetingFile` at all,
  for jurisdiction or anything else — this is a real, unused, confirmed
  data source, not a hypothetical one.

  **Path (1) fixed 2026-08-16, wave 2 item 6 — full detail in
  `BACKLOG_DONE.md`.** `civicclerk.py` now calls
  `extract_jurisdiction_chain(page_text="", html="", url=url)` as a
  fallback whenever `eventLocation` yields no usable city, confirmed
  live on this exact Los Altos Hills example (new regression test in
  `tests/test_civicclerk.py`). ~~**Path (2) still open, not built**~~
  **Fixed 2026-08-16 — full detail in `BACKLOG_DONE.md`.** New
  `_fetch_agenda_text()` fetches the `publishedFiles` "Agenda" entry's
  plaintext blob (`GetMeetingFile(...,plainText=true)` → `{"blobUri":
  ...}` → the SAS blob itself) and feeds it through the same
  `extract_jurisdiction_chain()`, tried only after path (1) has already
  failed (costs two extra requests). New regression test uses a
  synthetic subdomain/place name so it doesn't depend on path (1) also
  failing to fire.

  ~~**New gap found 2026-08-14, live-testing `/meetings`' jurisdiction
  filter: searching "California" finds nothing, but "CA" works.**~~
  **Fixed 2026-08-14 — full detail in `BACKLOG_DONE.md`'s "Wave 1" entry.**

## [Done — moved from BACKLOG.md 2026-08-17] Deep links

Moved wholesale during the 2026-08-17 backlog triage pass: Ryan's own
triage table marked this section `done?` (both real gaps found auditing
the deep-link scheme were fixed the same day they were found).

The `t`/`line` scheme itself is sound and hasn't changed since the initial
scaffold (`t`, raw seconds, always wins the actual seek; `line=seg-N` is
display-only highlighting — see the comment above `applyDeepLink()` in
`shared_static/deep_link.js` and the precedence-bug fix below). That's
already the "robust, won't shift under us" design a deep-link contract
needs. Three real gaps found auditing it (2026-08-08) — two fixed since,
one was already this file's own known-open item now closed too:

- **~~Two independent copies of `t`/`line`/`seg-N` logic, and
  `line=seg-N` could point at the wrong line after a version change~~ —
  both fixed 2026-08-08.** Was: `app/static/player.js` and
  `archive/static/meeting_page.js` duplicated the exact same deep-link
  parsing/apply logic, kept in sync only by a comment; separately, a
  bookmarked `/m/some-meeting?t=630&line=seg-42` could highlight the
  wrong line if that page's default `TranscriptVersion` was ever
  replaced (`t=630` would still seek correctly — a wrong-highlight bug,
  not a broken link). Fixed together, since both touched the same
  parse/apply code: the shared logic (`getQueryParams`,
  `getDeepLinkTime/Line/Version`, `updateUrlParams`, `findActiveSegment`,
  `highlightSegment`, `applyDeepLink`, the `segments`/`autoScrollEnabled`
  module state) now lives in one new file, `shared_static/deep_link.js`
  — a new top-level directory mounted identically by both `app/main.py`
  and `archive/main.py` at `/shared-static` (one file on disk, two
  independent `StaticFiles` mounts, so either service serves it whether
  reached directly or through the resolver's reverse proxy). Loaded
  before `player.js`/`meeting_page.js` in each page's `{% block scripts
  %}`, both of which had their duplicate copies deleted. `updateUrlParams`
  now automatically tags every generated link with the Archive's current
  `TranscriptVersion.id` (read from a new `data-version-id` attribute on
  `archive/templates/meeting_page.html`'s `<body>`, via a `body_attrs`
  block added to `archive/templates/base.html` matching the resolver's
  existing pattern) — automatic per call site, not something a future
  new "copy link" button could forget to pass. `applyDeepLink` trusts
  `line` only when the URL's `version` matches the page's current one
  (or either side has no version info at all — an old pre-fix link, or
  the resolver's page, which has no version concept); on a real
  mismatch it falls back to `findActiveSegment(t)` (time-proximity
  matching) instead of highlighting a possibly-wrong index.

  Verified three ways, no JS test framework existing in this repo: (1) a
  real behavioral difference caught and preserved during the merge —
  `player.js`'s `highlightSegment` respected an `autoScrollEnabled`
  toggle the Archive page doesn't have; folded into the shared file so
  the Archive page (which never toggles it) behaves identically to
  before. (2) A one-off Node `vm.runInContext` script (not a permanent
  test) simulating real multi-`<script>`-tag scoping — critically *not* a
  plain `eval()`, which was tried first and gave misleading results
  because direct eval creates its own nested lexical scope, unlike
  separate classic `<script>` tags which genuinely share top-level
  `let`/`const` bindings — covering version-match, version-mismatch-
  fallback, no-version-old-link, resolver-page (no version), and the
  URL-tagging behavior of `updateUrlParams` itself: 9 cases, all passing.
  (3) Real local servers (resolver proxying to a real local Archive
  instance, matching production's reverse-proxy shape exactly) with a
  seeded real page, checked live in-browser — `/shared-static/deep_link.js`
  loads with no console errors, all shared functions (`applyDeepLink`,
  `findActiveSegment`, `updateUrlParams`, `highlightSegment`) are defined
  and callable from both `player.js` and `meeting_page.js`, `segments`
  populated by one script is correctly visible to functions defined in
  the other (confirming real cross-script-tag `let` sharing, not just the
  Node simulation), and `data-version-id` renders correctly. Full Python
  suite green throughout (121 tests, unaffected -- this was a pure
  frontend change).

## [Done — moved from BACKLOG.md 2026-08-17] SSRF guard on `/api/resolve`

[Done 2026-08-14] (WO-5 of `AUDIT_EXECUTION_BRIEF.md`, audit finding #2):
`ResolveRequest.url` was a bare, unvalidated `str` that flowed straight
into `generic_fallback.py`'s `session.get(url, allow_redirects=True,
...)` for any unrecognized host, with no scheme allowlist, no private/
internal-IP rejection, no per-hop redirect re-validation, and (in
production, `GENERIC_FALLBACK_HEADLESS=1`) a real headless browser that
would load whatever it was pointed at. New `app/utils/url_guard.py`
closes all of that at once — see this file's own "Security hardening"
section (below) for the full fix and verification detail. Moved out of
`BACKLOG.md`'s "App-wide audit" section during the 2026-08-17 triage
pass, where it had been sitting tagged `done?` even though it was
genuinely finished, not uncertain.

## [Considered and declined — moved from BACKLOG.md 2026-08-17] Grand unification of adapter metadata extraction

Not a bug, not a build — a deliberate scope decision made during the
jurisdiction/title extraction planning conversation
(`JURISDICTION_METADATA_PLAN.md`) and confirmed during the 2026-08-17
backlog triage pass. The tournament-style extraction work that plan
green-lit stops at "promote measured winners into a shared fallback
chain" — it does not attempt a full rewrite of each adapter's *primary*
extraction into one unified mechanism. That's platform-specific for real
reasons (API fields, RSS feeds, URL conventions differ enough per vendor
that a single shared extractor would fight each one), so a grand
unification beyond the fallback-chain layer was considered and explicitly
declined, not left as an open idea to revisit. Kept here for the
reasoning rather than in live `BACKLOG.md`, since there's no future
action attached to it.

## Incident #2 same day: backfilled `search_corpus` OOM-crashed the plain `/meetings` browse — hotfix #127 (2026-08-17)

[Resolved 2026-08-17] Directly downstream of the migration incident
below, once it was fixed. Ryan ran PR #123's one-time
`scripts/backfill_search_corpus.py` on the Render shell (~09:55 PT,
1,219 rows). Within minutes `/meetings` — the *plain, no-keyword browse*
— went from fine to 37–57s responses and then 502s, `?page=2` 502'd
instantly (Render's LB refusing while the instance restarted), and Ryan
saw `proxy_get` timeouts in Sentry from the resolver side. Everything
else on the Archive stayed healthy the whole time (`/api/health` 0.4s,
`/coverage` 2s, `/m/*` ~1s), which is what localized it to that route.

**Root cause** (read from `list_pages()` + `models.py`): `search_corpus`
holds every meeting's *entire concatenated transcript text*, and every
`select(MeetingPage)` in `crud.py` — eleven call sites, including
`list_pages()`'s browse — selects every mapped column by default. That
was harmless for the ~30 minutes the column was empty; the moment the
backfill filled all 1,219 rows, rendering 20 title rows on `/meetings`
meant loading 1,219 full transcripts into a 512MB instance. Same OOM
class as the morning's `?q=flock` 502, now on the highest-traffic route
on the site — and it fired *because* the fix for that first OOM had just
been completed.

**Fix (#127, one keyword + tests)**: `deferred=True` on the column
(`archive/db/models.py`) — keeps it out of every default SELECT list;
it's only ever referenced in WHERE predicates (`ilike` /
`word_similarity`) which never load the value, and a grep confirmed
nothing in the app reads it as an attribute (all uses are writes). New
regression test pins the compiled SQL (`search_corpus` absent from a
default `select(MeetingPage)`, present in an explicit WHERE); the two
existing tests that read the attribute directly opt in via `undefer()`
(async SQLAlchemy raises `MissingGreenlet` on an implicit lazy load,
which is exactly what caught them). Suite 895 green.

**Verified live ~2 min after deploy**: plain `/meetings` **0.6s** (was
37s→502), `?page=3` **0.4s** (was instant-502). Keyword search survives
now but is still 23–35s for common terms — that residual is the live
"Search: move to a materialized/indexed column" entry in `BACKLOG.md`,
with the second-query root cause written up there.

**Lesson worth keeping**: a "schema-only, nothing reads it yet" column
is only inert if the ORM doesn't load it — a large `Text` column on a
hot model must be `deferred` from the first commit, not after the
backfill proves it. Two incidents in one morning from one three-PR
series, both in the seams *between* the PRs (deploy-before-migrate, then
populate-before-defer) rather than in any PR's own diff — the sequencing
was documented carefully and still bit twice; that's the WO-10 argument.

## Incident: `search_corpus` column deployed before its migration ran — ~13 min sitewide Archive outage (2026-08-17)

[Resolved 2026-08-17] **Timeline (all PT, from git + Sentry):** 09:25 PR
#116 merged and deployed (release `f44f5d84`) — "Search: add
materialized search_corpus column (PR1/3)", adding
`MeetingPage.search_corpus` (nullable Text) + an Alembic migration
(`f54a11e5f`) + a GIN-trigram index on Postgres. The PR description
correctly said "nothing reads this column yet … safe to deploy alone" —
but the ORM *selects every mapped column* on any `select(MeetingPage)`,
so the instant the model gained the attribute, every read of
`meeting_pages` in production issued `SELECT … meeting_pages.search_corpus
…` against a table that didn't have it. Sentry (its first real day of
service — this closes WO-7's "confirm a real exception appears in the
dashboard" criterion) recorded `sqlalchemy.dialects.postgresql.asyncpg.
ProgrammingError: <UndefinedColumnError>: column meeting_pages.
search_corpus does not exist` across five issues at once: `/m/{slug}`
(23 events, `crud.get_page_by_slug()`), `/meetings`, `/feed.xml`, and
the worker's `claim_next_chunk` / `find_auto_transcript…` polling — i.e.
everything that touches Postgres, both services. 09:37 PRs #123 (backfill
script) and #124 (rewire `list_pages()`) merged; the migration was
applied to prod in that window (Sentry's last event ~09:38, every
page 200 on re-test after), and Ryan then ran `alembic upgrade head` +
`python scripts/backfill_search_corpus.py` (1,219 rows) by hand on the
Render shell to complete PR2/3's one-time step.

**Diagnostic misstep worth recording, since it briefly went into
`BACKLOG.md` as fact:** the outage was first observed from *outside* by
a session investigating Search Console's flagged-URL list, which caught
three specific 500ing pages (`/m/welcome-to-clerkbase`, an SLC page, a
Minneapolis LIMS page) and — because eight other pages tested 200 in the
same pass and `transcript.txt` exports "worked on the same rows" — wrote
it up as a slc/lims/clerkbase-specific template-render bug. Every one of
those observations was a **timing artifact**: the 500s were sampled
inside the 13-minute window and the 200s just after it closed. Root cause
was correctly identified only once the Sentry traceback was read. Lesson,
already stated in `CLAUDE.md` in another form: don't infer a code-path
diagnosis from black-box HTTP status sampling when a traceback is
available — go get the traceback first.

**Root cause, structurally:** `init_models()` runs `create_all()`, which
creates *new tables* but never ALTERs existing ones (documented in
`CLAUDE.md`), so a model change to an existing table is only safe once
its Alembic migration has run against prod — and today nothing enforced
that ordering at deploy time. Same class as the two earlier incidents
that motivated adopting Alembic (job-priority column, materialized search
column). What's still open — a mechanism, not a rule — is tracked as the
live `BACKLOG.md` "Schema-migration deploy ordering" entry, feeding WO-10.

## Per-state SEO landing pages — `/state/{slug}` (2026-08-17)

[Done 2026-08-17] Built from a direct user ask ("all the meetings in a
state, eg California, Florida") in a discoverability-focused session —
never a `BACKLOG.md` item, so recorded done directly here. Related but
deliberately deferred: `CLAUDE_BACKLOG.md`'s per-jurisdiction hub pages
(`/j/{slug}`), whose open questions (slug scheme over messy stored
jurisdiction strings, thin-content threshold) don't apply here — state
pages group by the stored jurisdiction's *write-time-canonicalized*
`", ST"` suffix (`normalize_state_suffix()` runs on every ingest), which
sidesteps the messy-string problem entirely. Production motivation
checked before building: ~871 covered jurisdictions on live `/coverage`,
575 with a clean `", ST"` suffix (CA 153, TX 105, FL 74).

**What shipped**: `GET /state/{slug}` (e.g. `/state/california`) on the
Archive + a matching resolver proxy entry (`app/main.py`, mirrors
`/coverage`'s — without it the route 404s in production). New
`archive/templates/state_page.html`: state-specific title/meta
description, self-referential canonical (deliberately unlike
`/meetings`' filter-blind one), a governments table (same shape as
`/coverage`'s "Every place we've covered"), the 25 most recent meetings,
and a link to pre-filtered `/meetings?jurisdiction={StateName}` (full
name, so `jurisdiction_search_terms()` expands it). Data:
`crud.get_state_page_data()` — **anchored `LIKE '%, CA'` suffix match,
not `list_pages()`'s substring ilike** ("Decatur, GA" contains "ca" and
would leak into California; a regression test covers exactly this), with
a Python-side exact-suffix re-check since SQLite's LIKE is
case-insensitive while Postgres's isn't — and
`crud.get_state_coverage_index()` (one row per covered state, max
`updated_at` as sitemap lastmod). Both exclude `platform == "unknown"`
pages, same trust posture as the same-day sitemap noindex fix (entry
below). Internal linking for crawlability: `/coverage` gained a "Browse
by state" section, and every `/m/{slug}` page whose jurisdiction has a
state links "More {State} meetings". `sitemap.xml` gained a per-state
loop with real lastmod. New state helpers in
`archive/utils/jurisdiction_format.py` (`US_STATE_ABBR_TO_NAME` inverted
from the existing name→abbr map with a DC casing override,
`STATE_SLUG_TO_ABBR`, `state_abbr_from_jurisdiction()`,
`state_slug_from_abbr()`). Unknown state slugs and real states with zero
indexable meetings both 404.

**Known limitations, deliberate**: jurisdictions without a recognized
`", ST"` suffix (school districts named without one, state agencies,
non-US like Elliot Lake ON) appear on no state page (~296 of 871 in
production at build time); no pagination (capped at 25 recent + the
`/meetings` link); no JSON-LD (CollectionPage/ItemList judged negligible
SERP value for a listing page — possible follow-up).

**Verification**: 19 new tests green (`tests/test_state_pages.py`,
`tests/test_sitemap.py` additions, `tests/test_jurisdiction_format.py`
additions), full suite 889 passed. Browser-verified per repo convention
against seeded local data on both services: styled rendering via the
resolver proxy (8011) incl. the Browse-by-state section and the meeting
page's state link, direct-archive rendering, `/state/nowhere` +
`/state/wyoming` 404s, `xmllint`-valid sitemap with state URLs present
and an unknown-platform page's slug absent, on both ports. One
shared-test-DB collision found and fixed along the way: an exclusion
assertion originally seeded "Fresno, CA" as the unknown-platform row,
which collided with `tests/test_civicclerk.py`'s own indexable Fresno
row when the full suite ran — switched to Coalinga, CA (real Census
place, used by no other test), per the suite's unique-identifiers
convention.

## Sitemap no longer lists noindexed `generic_fallback` pages (2026-08-17)

[Done 2026-08-17] **`sitemap.xml` includes `generic_fallback` pages that
the page template itself `noindex`es — a real, code-confirmed
contradiction, not just a guess from the alert.** Source: a separate
Search Console alert (received 2026-08-17, forwarded via Gmail to
`CLAUDE_BACKLOG.md` first, then promoted to `BACKLOG.md` after tracing it
to real code) specifically titled "New reasons prevent pages **in a
sitemap** from being indexed... Excluded by 'noindex' tag" — meaning
Google is finding these via `sitemap.xml` itself, not just organic
crawling. Root cause confirmed by reading both sides:
`archive/templates/meeting_page.html:12-19` emits
`<meta name="robots" content="noindex">` whenever `page.platform ==
"unknown"` (i.e. every `generic_fallback`-resolved page — the
least-verified adapter, by design per `BACKLOG.md`'s trust & safety
section), but `archive/db/crud.py`'s `list_all_page_slugs()` (used by
`archive/main.py`'s `/sitemap.xml` route) selected every `MeetingPage`
slug unfiltered — no `platform != "unknown"` clause — so every
`generic_fallback` page's URL landed in the sitemap while its own page
simultaneously told Google not to index it.

**Fix**: added `.where(MeetingPage.platform != "unknown")` to
`list_all_page_slugs()`'s query (`platform` is `nullable=False` and
already indexed, `archive/db/models.py:29`), plus the suite's first-ever
`/sitemap.xml` tests (`tests/test_sitemap.py`): static paths + XML
content type, an indexable seeded page appearing with `<lastmod>`, a
seeded `platform="unknown"` page absent from the rendered sitemap (the
regression case), and a direct crud-level exclusion assertion. Live
sitemap held 1,223 URLs just before the fix (counted via `curl` — how
many are `generic_fallback` isn't distinguishable from slugs alone;
compare the count after the next deploy for the real delta). The
separate "Page indexed without content" reason from the same 2026-08-17
alert batch is NOT explained by this — still open in
`CLAUDE_BACKLOG.md`'s 2026-08-17 entry, along with "Page with redirect"
(2026-08-16). Re-check Search Console after Google re-fetches the
sitemap to confirm the "Excluded by 'noindex' tag" reason actually
clears.

## Reliability/ops audit execution — Phase 1 + Waves 1, 2, 3, 4, 6 (WO-1, WO-6 through WO-9, WO-11 through WO-13, WO-16) (2026-08-14 through 2026-08-17)

`AUDIT_EXECUTION_BRIEF.md` (root of this repo) tracked a 16-work-order
reliability/ops plan across a Phase 1 and six waves. As of 2026-08-17
everything is shipped and verified except Wave 5 (WO-10, "migrations
survive deploys") — still genuinely open, blocked on Ryan's prod DB
access, and kept live in `AUDIT_EXECUTION_BRIEF.md` itself since it's the
one remaining active work order. `AUDIT_EXECUTION_BRIEF.md` was trimmed
2026-08-17 to just that open work; this entry preserves the Problem/Do/
Fixed detail for the work orders that didn't already have their own
dedicated section here — **WO-2** (see "Testing infrastructure" below),
**WO-3** (see the `.gitignore` correction entry below), and **WO-5** (see
"Security hardening" below) already had their own entries and aren't
repeated; **WO-14/WO-15/WO-16's jurisdiction/refresh-path work** already
has its own entries above and isn't repeated either, though WO-16 is
listed below for completeness since the brief bundled it into Wave 6.
A handful of small Ryan-owned dashboard/manual checks were left open
across these waves (Sentry exception verification, confirming a Render
health-check gate actually blocks a bad deploy, confirming both admin
crons run green against the new header-auth before removing the old
query-param fallback, confirming a real Render deploy off the new pinned
lockfiles, GA event visibility, a real sent alert email) — these were
**not** silently dropped; they're consolidated into one live checklist
item in `BACKLOG.md` ("Reliability/ops audit — remaining manual/dashboard
checks") rather than left scattered as footnotes across six waves.

### WO-1 · Fix `robots.txt` prefix match — DONE 2026-08-14

**Problem.** `app/main.py`'s robots.txt emitted a bare `Disallow:
/meeting`, and robots.txt matches by prefix — so it also blocked
`/meetings`, the Archive's own browse/search hub, despite that page being
simultaneously advertised as indexable in the sitemap.

**Fixed.** Replaced the single directive with two anchored forms,
`Disallow: /meeting$` and `Disallow: /meeting?`, so `/meetings` is no
longer caught. Unit tests assert both anchored forms are present, no bare
`Disallow: /meeting` line exists, and `/meetings` isn't matched. Deployed
and the live `robots.txt` confirmed correct; Search Console re-submission
was Ryan's follow-up, outside code scope.

### WO-6 · Health checks that can fail — DONE 2026-08-16

**Problem.** Both `/api/health` handlers (resolver and Archive) returned
a static `{"status": "ok"}` regardless of DB state. During the
2026-08-09 incident the app was failing every query on a missing column
and would still have reported healthy.

**Fixed.** Both handlers now open a real DB connection before reporting
`ok` — the resolver runs `SELECT 1`, the Archive runs a cheap
`SELECT count(*)` against `MeetingPage` (catching a missing/misnamed
table, not just a dead connection). Either raising → `logger.exception` +
`{"status": "error", "reason": "database unreachable"}` at 503. Covered
by `tests/test_health_endpoint.py` (all four cases: both services ×
reachable/unreachable — DB unreachability simulated by swapping the
module-level `engine` object for a stub whose `.connect()` raises, since
`AsyncEngine.connect` turned out to be a read-only attribute that can't
be monkeypatched directly). Full suite green (789 passed at the time).

### WO-7 · Know when production breaks (Sentry + uptime + failure-visible cron) — DONE 2026-08-16

**Problem.** No error monitoring existed anywhere; production exceptions
only surfaced if someone happened to check Render logs. The daily digest
also degraded silently by design — one failed metric didn't blank the
others, so a cron's `curl --fail-with-body` saw HTTP 200 on a half-broken
report.

**Fixed.**
- Sentry free tier wired into all three services (`_init_sentry()`,
  duplicated per service matching the existing Clerk-degrades-gracefully
  pattern) — no-op when `SENTRY_DSN` is unset. Its default logging
  integration means every existing `logger.exception()`/`logger.error()`
  call across all three services starts reporting with zero
  per-call-site changes.
- New `GET /api/health/resolve-check` runs a real resolve (the same
  cache-then-live-adapter path `/api/resolve` itself uses) against one
  operator-chosen URL (`UPTIME_CHECK_URL`), so a plain GET from a
  free-tier uptime service proves the whole pipeline, not just the DB.
  Returns `not_configured` (still 200) when unset, so the endpoint
  existing can never itself break a dashboard.
- Both `daily-report.yml` and `send-search-alerts.yml` got an `if:
  failure()` step posting to `ALERT_WEBHOOK_URL` when set, and a
  `::warning::` annotation otherwise (GitHub's own failed-scheduled-
  workflow email is the fallback either way).
- `run_daily_report()` now returns each metric's `{value, error}`;
  `/admin/daily-report` checks for any failed metric first and returns
  502 `metrics_unavailable` with the failure list, so `--fail-with-body`
  actually trips.

**Ryan's account setup, done 2026-08-16**: `SENTRY_DSN` live on all three
services; UptimeRobot configured against
`https://simivalley.granicus.com/player/clip/2840` (a real Granicus
meeting, deliberately not YouTube/headless-browser, to avoid unrelated
false alarms) with `UPTIME_CHECK_URL` set on the resolver — confirmed
live via `curl` returning `{"status":"ok"}`. Took a manual "Deploy latest
commit" to actually pick up the env var; a plain restart didn't.

**Verified.** A forced metric failure turns the daily-report workflow
red — covered by
`tests/test_daily_report.py::test_admin_daily_report_returns_502_when_a_metric_failed`
plus the full suite (808 passed). `tests/test_health_resolve_check.py`
and `tests/test_sentry_init.py` cover the new endpoint and the no-op/init
gate. **Not verified**: a deliberately raised exception actually landing
in the Sentry dashboard — DSN is live but this specific check was never
run; now tracked in `BACKLOG.md`'s consolidated checklist.

### WO-8 · Admin token out of the URL — DONE 2026-08-16

**Problem.** `daily-report.yml` and `send-search-alerts.yml` both sent
`?token=${{ secrets.ADMIN_STATS_TOKEN }}` — GitHub masks it in Actions
logs, but Render's own request logs don't. The Archive already did this
correctly.

**Fixed.** `_admin_token_ok()` now checks `Authorization: Bearer` first
and falls back to the `token` query param only if no (or a malformed)
header is present — still `secrets.compare_digest`, not `==`. All 9
`/admin/*` routes take an `authorization` header param now. Both cron
workflows switched to `curl -H "Authorization: Bearer ..."`; the
query-param path is deliberately still live, per a "not a flag day"
transition. `tests/test_admin_token_auth.py` covers no-credentials → 404,
correct/incorrect header → 200/404, correct/incorrect legacy query param
→ 200/404, header priority when both present, and a malformed header
falling back to the query param rather than hard-rejecting. Full suite
green (796 passed).

**Still open, not code**: confirming both workflows actually run green
against the deployed header-auth change, then removing the query-param
fallback in a follow-up PR — needs a real cron run against prod first.
Now tracked in `BACKLOG.md`'s consolidated checklist rather than as a
loose end here.

### WO-9 · The three events that make outreach measurable — DONE 2026-08-16

**Problem.** Five GA events existed (`submit_meeting_url`, three
`copy_link_to_time`, one `newsletter_signup`). Missing: whether a
resolve succeeded, whether anyone played the video, and any way to
attribute a visit to an outreach recipient.

**Fixed.**
- `resolve_result` fires at all four `/api/resolve` response branches
  with `{status, platform}` — status values always one of a small fixed
  set, never free text.
- `transcript_seek` fires from the real transcript-line click handler,
  deliberately not agenda-item clicks (same CSS class, separate feature).
- `video_play` fires from the shared `play` listener covering
  native/YouTube/Viebit. **Real bug found and fixed while wiring this
  up**: the native adapter's own muted warm-up play-then-pause trick
  fired the same event — without a fix, `video_play` would have fired on
  every page load. Fixed with a module-level
  `suppressWarmupPlayTracking` flag.
- **Second real gap, outside original scope**: the Archive had no Google
  Analytics at all, meaning any outreach visit landing directly on a
  permanent `/m/{slug}` page (a large fraction of real traffic) would
  have been invisible to GA regardless of UTM survival. Fixed by
  mirroring the resolver's `GA_MEASUREMENT_ID`/`gtag`/`trackEvent`
  snippet onto the Archive's `base.html`.

**Verified live** against a local dev server and a real Granicus meeting
(Simi Valley): `window.dataLayer` inspected directly — `resolve_result`
fires correctly on success, `video_play` does not fire on page load but
does on a real click, `transcript_seek` fires on a real transcript-line
click. UTM params confirmed to survive the `/meeting` → `/m/{slug}`
archive redirect intact. Full suite green (836 passed), JS suite green
(29 passed).

**Ryan's half, not code**: settle the UTM convention
(`?utm_source=outreach&utm_campaign=first10&utm_content=<recipient-slug>`)
before any real outreach send — unrecoverable if the first emails go out
without it.

### WO-11 · Pin dependencies, then scan them — DONE 2026-08-16

**Problem.** Every requirements file used unbounded `>=` with no
lockfile, while `render.yaml` reinstalls on every deploy — so two deploys
of identical source could install different dependency versions. No
Dependabot, no `pip-audit`.

**Fixed.** Each service now has a `requirements.in` (loose source)
compiled via `pip-compile` into a fully-pinned `requirements.txt`.
`yt-dlp`, `faster-whisper`, and `youtube-transcript-api` are deliberately
excluded from compilation and appended unpinned by hand afterward, each
with a comment explaining why (see `CLAUDE.md`'s yt-dlp note) and a
reminder to re-append after the next `pip-compile` run. `.github/
dependabot.yml` covers all three service directories, weekly.
`pip-audit` added as a non-blocking `test.yml` step, scanning all four
requirements files — clean at the time, left non-blocking so a future
CVE disclosure doesn't silently block every merge.

**Verified** locally (no prod access that session): full suite green
(818 passed) after installing the pinned resolver requirements,
including a real major-version bump surfaced by pinning
(`clerk-backend-api` 6.0.1 → 7.0.0, confirmed compatible). Archive and
worker requirements each verified installing cleanly in their own
isolated scratch venv, matching how they actually deploy.

**Still open, not code**: a real Render deploy off the new pinned
lockfiles hasn't been watched — now tracked in `BACKLOG.md`'s
consolidated checklist.

### WO-12 · Linter and formatter — DONE 2026-08-16

**Problem.** No ruff/black/mypy/pre-commit config anywhere. With
multiple sessions editing this tree the same day, a formatter mostly
protects `git pull --rebase` from gratuitous whitespace conflicts.

**Fixed, in two PRs** (squash-merge-only branch protection means two PRs
was the only way to get two separate commits on `main`):
- Config PR: `ruff.toml` (`select = ["E", "F", "W"]`, `ignore = ["E402",
  "E501"]` — E402 excluded because this repo intentionally imports some
  modules only after `load_dotenv()`/`_init_sentry()` runs; E501
  excluded because comments/docstrings here are deliberately
  prose-length). Also fixed the 13 real findings that selection
  surfaced (7 unused imports, 2 unused locals, 2 ambiguous
  single-letter names, 2 trailing-whitespace lines in Alembic-generated
  migration docstrings) and added `ruff check` as a blocking CI step.
- Reformat PR: ran `ruff format` across `app/`, `archive/`, `worker/`,
  `scripts/`, `tests/` — 144 files reformatted. Added `ruff format
  --check` as a blocking CI step. Coordinated with 4 active peer sessions
  before running the repo-wide reformat given its blast radius.

**Skip mypy** — deliberate, not attempted; retrofitting types is a
multi-day project with unclear payoff at this stage.

**Verified.** `ruff check`/`ruff format --check` both pass cleanly. Full
suite green post-reformat (835 passed).

### WO-13 · Adapter health canary — DONE 2026-08-16

**Problem.** The test suite and WO-7's Sentry both catch code-level
failures, but neither catches this repo's most common real failure mode:
a government site quietly changes structure and a working adapter starts
returning empty/wrong data while still returning HTTP 200 — no
exception, nothing for Sentry to see. Self-flagged in
`CLAUDE_BACKLOG.md` as "still the highest-value remaining item."

**Fixed.** `scripts/adapter_canary.py` calls each platform's real
`AssetFinder.resolve()` directly (in-process, not via the deployed HTTP
service — no production cache/stats/Archive noise) against one real,
confirmed-good URL per platform, pulled from each platform's own test
fixtures. `.github/workflows/adapter-canary.yml` runs it daily (its own
cron time, no resource contention with the other two cron workflows)
with `playwright install chromium` for the two headless-browser-gated
platforms (LIMS, SLC), reusing WO-7's exact `if: failure()` →
`ALERT_WEBHOOK_URL`-or-`::warning::` notification step. A
`CalendarPageError` with real candidates found (e.g. CivicPlus's
AgendaCenter, which has no single-meeting URL shape) counts as a pass —
a real regression there would show as the candidate list going empty,
not the routing behavior itself.

**Two platforms deliberately excluded from `CANARY_URLS`**: swagit (no
real Swagit meeting URL exists anywhere in this repo's text) and
civicplus (the one site this adapter was ever verified against stopped
resolving 2026-08-07, re-confirmed dead by live DNS failure building
this canary — a `BACKLOG.md` entry names an untested replacement
candidate, Maricopa County AZ).

**Verified.** Running live against real government sites (not mocked):
20/20 platforms pass. Deliberately breaking one adapter's parsing
locally (a fixture-based fake finder returning an empty
`ResolvedMeeting`, plus a `CalendarPageError`-with-zero-candidates case)
produces a real reported failure — `tests/test_adapter_canary.py` (10
tests, no real network calls). Full suite green (818 passed).

### WO-16 · Census-table jurisdiction gaps — bundled in Wave 6, DONE 2026-08-16

Full detail already in this file's own "WO-16: Census-table jurisdiction
gaps" entry above (townships/county subdivisions added to the lookup
table, the two literal-date-as-jurisdiction pages no longer reproduce,
Elliot Lake ON confirmed already handled correctly) — not repeated here.

## PITR test restore — confirmed working, real data verified (2026-08-17)

WO-4 (`AUDIT_EXECUTION_BRIEF.md`, Wave 4) left one item genuinely open:
the documented restore procedure (`README.md`'s "Backups and recovery")
was written from Render's documented behavior plus this workspace's
confirmed real settings, but nobody had clicked through an actual
recovery. Ryan ran a real throwaway PITR restore via Render's dashboard
(new scratch instance `rtr-deeplink-db-copy`, restored from the latest
available point, "copy existing settings" selected) and it was verified
together in this session.

**First check produced a false alarm, since corrected.** `SELECT count(*)
FROM meeting_pages` against the restored instance's default-suggested
database (`rtr_deeplink_db`, the name Render's Connect panel defaults
to) returned 4 — alarmingly low against production's real ~860+ rows.
Cross-checked live production directly (`curl` against `/coverage` and
`/api/health`) and confirmed production itself was completely healthy
(860 rows, health check OK) — ruling out a live incident and pointing at
either the restore mechanism or the check itself being wrong.

**Root cause: checked the wrong database name, not a broken restore.**
`\l` on the restored instance showed the Postgres *server* actually hosts
two logical databases: `rtr_deeplink_db` (the resolver's — real tables
`meeting_resolutions`/`problem_reports`, confirmed 355 real rows in the
restore) and `rtr_archive` (the Archive's real database — confirmed
**1,117 real rows** in `meeting_pages` in the restore, matching
production). The 4-row result came from a *different*, apparently dead
set of Archive-shaped tables that happen to also exist inside
`rtr_deeplink_db` (see the new stale-tables entry in `BACKLOG.md` for
that separate finding) — not from the real `rtr_archive` database at all.

**Conclusion: the restore procedure works.** All real data (both
services' worth) came through correctly in the scratch instance. The
`README.md` procedure's steps are confirmed accurate, not just
theoretically correct. Scratch instance deleted immediately after
verification, per plan — never repointed at any real service.

## Made `scripts/transcribe_backlog_locally.py` safe for a real unattended overnight run (2026-08-17)

Direct fallout from a real session running the script overnight
(`--limit 40`, several hours in): the user, who isn't a developer and
doesn't know Python I/O internals, asked why a multi-hour run showed
*zero* output in its log file despite the process clearly being alive
(high CPU), and separately reported that the very first HTTP call the
script makes had crashed the entire run hours earlier and gone unnoticed
until manually checked. Framed as "a large unattended local job a
non-developer needs to be able to check on and trust," not just a
one-line bug fix.

**Root cause of the invisible output**: every progress line in the
script used plain `print(...)`, which fully block-buffers when stdout is
redirected to a file/pipe (as it always is for a real backgrounded
overnight run) — the OS only gets the bytes on process exit or an
explicit flush. The only reason *anything* showed up live in that run's
log was that `app/platforms/media_probe.py`'s `logger.warning()`/
`logger.info()` calls happen to flush immediately:
`logging.StreamHandler.emit()` calls `self.flush()` after every record
regardless of the stream's buffering mode. That inconsistency (some
things live, most not, no obvious reason why) was itself part of what
the user found confusing.

**Fix — output**: routed all of the script's own progress output through
Python's `logging` module, configured the same way `worker/main.py`'s
own standalone process already does it (`logging.basicConfig(level=
logging.INFO)` at import time, module-level `getLogger(...)`) rather than
inventing a third output convention — plus `stream=sys.stdout` (matching
where the old `print()` calls went) and `force=True` (so this config
wins regardless of import order). Configuring the *root* logger here also
means `media_probe.py`'s existing calls — previously the only visibly-live
thing, for no reason a reader of this script would guess — now share the
exact same timestamped format as everything else. Plain-English additions
beyond the raw bug fix, per the brief's "make it trustworthy for a
non-developer" framing: a real-config summary line at run start (model
size, limit, dry-run, chunk-seconds, promote), a plain-English
starting/finishing line per meeting, and running ingested/skipped/failed
totals logged after *every* meeting (not just at the very end) — the
whole point being a run that might not make it to the end unattended.

**Root cause of the crash**: the script's very first network call
(`GET /internal/transcription-backlog`, fetching the whole candidate list
before the main loop even starts) had no retry at all — a transient 502
from unrelated deploy activity elsewhere took down the entire 40-meeting
run, before the per-meeting loop's own existing try/except (which *does*
already isolate one meeting's failure from the rest) ever got a chance to
help.

**Fix — retries**: added `_request_json()`, a shared retrying request
helper used by every call this script makes to the Archive's own
`/internal/*` API (candidate list fetch, ingest push, promote) — same
exponential-backoff-with-jitter shape already established in
`app/platforms/granicus.py`'s `_fetch_page()`
(`(2**attempt) * random.uniform(0.5, 1.5)`), scaled up with a bigger base
delay (these calls can afford to be patient against an hours-long run).
Deliberately narrower retry predicate than granicus.py's, though:
granicus.py retries any status >=400 because it scrapes arbitrary
third-party sites where even a 403 can be a transient bot-block; these
calls are to *our own* Archive API with *our own* token, so a 4xx is a
real, static problem (bad token, malformed payload) that retrying can't
fix — only 5xx and connection-level failures (timeout, DNS, reset)
retry. Applied to the initial candidate fetch (the real incident) and,
per the brief's explicit prompt to think beyond just the cheap call, to
the per-meeting ingest push too — a transient blip there after local
Whisper compute has already finished (potentially a long time for a real
meeting) is a much bigger loss than the initial fetch failing. If an
ingest push still fails even after retries are exhausted, the finished
payload is now written to `local_transcription_backups/` (gitignored)
instead of just being discarded with a "failed" log line — recoverable
later with a plain `curl -X POST .../internal/ingest` once the Archive is
reachable again, not a re-transcription. If the *initial* candidate fetch
still fails after retries, the run now exits with one clear plain-English
line (real outage vs. bad token, what to check) instead of an unhandled
Python traceback.

**"Machine slept mid-run" made legible, not solved** (the brief's fourth
ask, explicitly scoped as "use your judgment, explain either way"): can't
stop macOS from sleeping from inside a script, so this doesn't try.
Added `_note_if_suspended()`, called after each transcription chunk and
after each meeting: compares `time.time()` (wall clock, which jumps
forward by the real elapsed time on wake) against `time.monotonic()`
(which stops advancing while the machine is suspended). A big *skew*
between the two — not the absolute elapsed time, since a single real
Whisper chunk can legitimately run 10-20+ minutes of continuous CPU work
— is what actually indicates a suspend; ordinary work doesn't produce
that skew, only an actual suspend or a long stalled connection does.
Purely informational (a `logger.warning()` line), by design — there's
nothing more automatable to build here without either fighting macOS's
own power management or adding a `caffeinate`-style wrapper, which is a
real, separate, user-facing choice (trading battery/fan noise for
guaranteed run continuity) rather than something to silently decide for
them in this script.

**Test coverage** (`tests/test_transcribe_backlog_locally.py`, 8 new
tests): per this repo's own "synthetic tests need a real-verified shape,
and testing a retry loop needs something real to retry against"
convention, `_request_json()`'s retry/backoff logic is tested against a
*real* aiohttp server on a loopback port (`_CountingServer`), not a
mocked `aiohttp.ClientSession` — real sockets, a real HTTP
request/response cycle, backoff delays shrunk via monkeypatched module
constants (not mocked-away `asyncio.sleep`) so the suite stays fast while
the retry loop itself runs unmodified. Covers: recovers after 2 real 502s
then a real 200 (asserting the exact real request count, 3, not just "it
didn't crash"); a 4xx fails on the first attempt without retrying;
persistent 5xx gives up after exactly `max_retries` real attempts; a
genuine connection-refused port (nothing listening) is retried and
eventually raises, distinct from the HTTP-status path; `_get_candidates()`
itself (not just the shared helper) survives a transient 502 end-to-end.
Plus direct tests of `_note_if_suspended()` (warns on a real backdated
wall-vs-monotonic skew, silent when the clocks agree) and
`_save_local_backup()` (writes back exactly the JSON that would have been
POSTed). All 866 tests pass (up from 854 before this change — 12 new:
these 8 plus 4 that landed on `main` from unrelated work merged in while
this was in progress).

**Live-verified, not just unit-tested** — the literal bug being fixed
(invisible output in a redirected file while the process is still
running) can't be proven by a unit test, since it's about real process
I/O timing. Ran the actual script for real (`--dry-run --limit 1`,
against the real production Archive and a real backlog candidate —
Calgary AB, a real eScribe meeting) with stdout redirected to a file the
same way the overnight `--limit 40` run already in progress on this same
machine was started, then read that file repeatedly *while the process
was still alive* (confirmed via `ps`, real climbing CPU time, not just
assumed): `Run started: model_size=...` appeared within 1 second of
launch, followed over the next several minutes by the model-load
confirmation, the real candidate-list response, the meeting-start line,
and faster-whisper's own internal progress lines (duration probe,
language detection) — every one of them visible in the redirected file
before the process exited, which is exactly the failure this fix
targets. (Also incidentally confirmed this repo's own worktree-safety
convention for real: `ps` showed the actual, currently-running `--limit
40` overnight process from earlier tonight, untouched by any of this.)

**Also updated**: `README.md`'s "Working the existing backlog locally"
section documents the new visibility/retry/local-backup behavior;
`.gitignore` gained `local_transcription_backups/`.

## Cleaned up two live pages hit by the seam-duplication/phase-cancellation bugs; built the retroactive hallucination audit; real reusable `--promote` tooling (2026-08-16)

Follow-up work after both bugs (seam-duplication, PRs #91/#92; stereo
phase-cancellation hallucination, PRs #94/#95) were fixed and deployed —
two specific already-live pages the user named still had the old bad
symptom in their default transcript, plus the phase-cancellation entry's
own write-up had flagged the retroactive already-shipped-exposure audit
as explicitly open/not yet built (see BACKLOG.md's note that closed).

**Real gap found first, fixed properly rather than worked around**:
`archive/db/crud.py`'s `ingest_resolution()` returned only
`{"slug", "url"}` — no way for a caller to learn the id of the
`TranscriptVersion` a push just wrote, so `scripts/transcribe_backlog_
locally.py` had no way to promote a fresh re-transcription of an
already-live page (its existing default already has segments+language,
so `_is_real_improvement()`'s auto-promotion never fires for a manual
re-transcription — confirmed by reading that function before writing any
code, not assumed). Fixed by having `ingest_resolution()` return a real
`"version_id"`, threaded straight through `POST /internal/ingest`'s JSON
response, plus a new `--promote` flag on the script that calls the
existing `POST /internal/transcript-version/promote` endpoint
automatically after a successful ingest. **A second real gap surfaced
live, not synthetically**: re-running Boulder County for real the first
time, the freshly-transcribed (fixed) content's hash already matched a
non-default `TranscriptVersion` left over from earlier real (non-dry-run)
investigation work, so nothing *new* was created and `version_id` came
back `None` — `--promote` correctly no-op'd, but that defeated the whole
point for exactly the case it exists for. Fixed by tracking a separate
`matched_version_id` (the id of whichever version a push's content
corresponds to, freshly created or an existing content-hash duplicate)
distinct from the `new_version_id` the auto-promotion-on-improvement
check must keep using internally (that check must never re-promote an old
duplicate just because it was pushed again). Landed as PR #97, 3 new
`tests/test_ingest_promotion.py` cases lock in all three cases (fresh
push, no-segments push, content-hash duplicate); `tests/
test_transcription_jobs.py` gained a fourth test covering the new audit
endpoint below. 840 total tests passing after merge, `ruff check`/`ruff
format --check` clean.

**Retroactive hallucination audit, same template as the seam-duplication
bug's `GET /internal/transcription/completed-multichunk`**: new `GET
/internal/transcription/hallucination-candidates` (also in PR #97)
re-runs `detect_hallucination_warnings()` (reused, not reimplemented)
against the *stored* segments of every `source=="transcribed"`
`TranscriptVersion`, left-joining `TranscriptionJob.transcript_version_id`
to label `cloud_worker` vs. `local_script`-produced (the local script
never touches `transcription_jobs` at all — see its own module
docstring). Read-only/audit-only, never re-transcribes anything itself.

**Run for real immediately after PR #97 deployed** (confirmed via `render
deploys list srv-d9ras3ijnfac73f9ps5g -o json` showing deploy
`dep-da19r88db16c73c9r3lg`, commit `ec95957`, `status: "live"`, finished
2026-08-17T05:36:42Z — not just that the GitHub merge succeeded). Real
result: **5 candidates**, all `already_flagged: false` (i.e. a genuinely
new finding — none of these rows already carried the hallucination
warning marker):

| slug | version_id | produced_by | job_id | language | segments |
|---|---|---|---|---|---|
| revised-long-beach-ca-2026-08-04-aug-04-2026-city-council-special-meeting | 176 | cloud_worker | 74 | en | 1239 |
| san-diego-county-ca-2026-06-24-board-of-supervisors | 240 | cloud_worker | 103 | en | 4662 |
| meeting-38ca49 | 246 | cloud_worker | 111 | en | 5052 |
| portcoquitlam-2025-02-18-committee-of-council-meeting | 971 | local_script | — | te | 230 |
| kitchener-2026-05-05-heritage-kitchener-committee | 981 | cloud_worker | 201 | cy | 410 |

Spot-checked all 4 remaining candidates live to rule out a heuristic
false-positive on legitimate repetitive procedural speech (roll calls,
votes) — every one confirmed real, not a misfire: Long Beach and San
Diego County (`en`) both open with a genuine repetition-loop artifact
(14+ consecutive segments of bare `"."`); `meeting-38ca49` (Sacramento
County, CA Board of Supervisors, 2026-08-11) opens with a classic Whisper
stock hallucination on quiet/no-speech audio (`"Thank you for your
attention." ... "Thank you very much for watching this video and I'll
see you in the next video."`) before recovering into real coherent
content once the meeting actually starts; Kitchener is genuinely garbled
Welsh-script gibberish throughout, including both a ~500-character run of
repeated `w` and a later `"Ff. Ff. Ff. Ff."` repetition loop. See
BACKLOG.md's matching open entry for the remaining-4 re-transcription
decision, deliberately left to the user, same precedent as the
seam-duplication audit's own
118-job list.

**The two user-named live pages, cleaned up for real** (not just a dry
run):

- **Boulder County, CO**
  (`bouldercounty-2026-02-05-historic-preservation-advisory-board`) — the
  seam-duplication bug's duplicated "truck caro..." sentence at the
  chunk-1/chunk-2 boundary (~15:00). Re-ran `scripts/
  transcribe_backlog_locally.py --url "<source_url>" --promote` for real
  against the deployed fix: `chunk 1/2 transcribed (136 segments)`,
  `chunk 2/2 transcribed (94 segments, dropped 3 seam-duplicate
  segment(s))`, `227 segments (language=en) ... (promoted version 986 to
  default)`, 230.4s total. Verified against the real live page with a
  fresh cache-busted `curl` fetch (independent of any browser/CDN cache):
  the distinctive duplicated fragment unique to the bug (`"Is just this
  whole question about truck caro..."`) appears **0 times**; the phrase
  "truck caro" itself appears exactly 2 times, matching the two real,
  legitimate separate mentions in the actual meeting (at 15:00 and
  15:53), not the original bug's 3 (the legitimate 2 plus the duplicated
  intro). The transcript now flows cleanly from `[14:31] "...acutos to
  her and her effort."` straight into `[15:00] "This whole question about
  truck caro, which may actually predate the Bracero program, there's an
  exhibit at the Colorado Railroad Museum..."` with no restatement.

- **Port Coquitlam, BC**
  (`portcoquitlam-2025-02-18-committee-of-council-meeting`) — the
  phase-cancellation hallucination bug's Telugu/Sinhala/gibberish default
  transcript (`transcript_language="te"`). Re-ran the same command against
  the deployed fix: extraction log confirmed the automatic left-channel
  fallback fired on both chunks (`"Chunk audio at 0s looks suspiciously
  quiet after mono downmix (-44.2dB) -- retrying with the left channel
  alone..."`, same at `900s`, `-45.5dB`), `chunk 1/2 transcribed (190
  segments)`, `chunk 2/2 transcribed (116 segments)`, `306 segments
  (language=en) ... (promoted version 991 to default)`, 348.9s total.
  Verified against the real live page: the old garbage marker (`"Did you
  ever see your mom"`) appears **0 times**; the transcript now opens with
  coherent real English content — `"All right, good afternoon, everyone.
  I call to order. Committee of council meeting, February 18, 2025..."`
  — flowing into an actual real development-variance-permit discussion
  (`"...The applicant Burkill Development Limited has applied for a
  development variance permit for a lot at 2472 Chilcott Avenue..."`),
  matching the real content this exact meeting was already independently
  confirmed to contain during the original bug investigation (see this
  file's phase-cancellation entry below). The old `te` version (971) is
  still visible in the page's version picker and still appears in the
  hallucination-candidates audit above — confirmed **not deleted**, only
  demoted (`is_default` flipped from `true` to `false` between the two
  audit runs) — matching this repo's "never delete transcript versions"
  convention (`promote_transcript_version()`'s own docstring).

**Not done here, deliberately, per the task's own explicit scope**: no
other live page was re-transcribed or otherwise touched — the remaining 4
hallucination-audit candidates and the separate 118-job seam-duplication
list are both real, open, user-facing decisions, not something to act on
automatically.

## WO-14: shared jurisdiction-regex bleed fix for Granicus + eScribe (2026-08-16)

**Problem.** `GranicusAssetFinder._extract_metadata()`'s page-body
jurisdiction regex has no sentence/tag boundary, so it can swallow
unrelated agenda text into the stored jurisdiction — confirmed live
2026-08-15 across multiple real customers, found while auditing all ~650
`/meetings` rows after the 204-URL Granicus batch landed. Root cause,
`granicus.py`: `re.search(r"\b(City|County|Town) of ([A-Z][A-Za-z
.]{1,40})", page_text)` — the character class `[A-Za-z .]` allows spaces
*and* literal periods with no stop condition at a real sentence end, so
once "City of X" matches, the regex just keeps consuming
letters/spaces/periods for up to 40 more characters regardless of whether
that text is still the city name. Live-verified by fetching a real page
directly — `hercules.granicus.com/player/clip/1306`'s actual page text
produced exactly `'City of Hercules. XIV. PUBLIC COMMUNICATIONS XV. '`
when the old regex ran, matching the real stored jurisdiction on
[redtaperecordings.com/m/city-of-hercules-xiv-public-communications-xv-2024-05-14-city-council-on-2024-05](https://redtaperecordings.com/m/city-of-hercules-xiv-public-communications-xv-2024-05-14-city-council-on-2024-05)
character for character. Only fires when `_fetch_channel_info()`'s
RSS-channel jurisdiction (the normally-preferred source) comes back empty
for that customer, so it's a fallback-path bug, not universal.

Real examples pulled from the live `/meetings` listing, all Granicus, all
the same shape:
- `Sarasota Legacy Business PLEDGE OF PUBLIC` (should be `Sarasota, FL`)
- `Punta Gorda Council is seeking the servic[es...]` (should be `Punta Gorda, FL`)
- `Huntsville.Ordinance No.` (should be `Huntsville, AL`) — also shows the
  regex swallowing a literal `.` with no following space
- `Fort Worth in Communications with the Tex[as...]` (should be `Fort Worth, TX`)
- `Edgewater and the Florida Department of T[ransportation...]` (should be `Edgewater, FL`)
- `Town of Castle Rock Authorizing the Plum Creek Wa[ter...]` (should be `Castle Rock, CO`)
- `Castle Pines History of Parks and Recreat[ion...]` (should be `Castle Pines, CO`)
- `Boston to accept and expend the amount of, MA` (should be `Boston, MA`)
- `Milwaukee.` (should be `Milwaukee, WI`) — the mildest real case

Not a universal cap on the whole "City/County of X" idea —
`Lexington-Fayette Urban County Government`, `Capital Metropolitan
Transportation Authority, TX`, `Albuquerque Bernalillo County Water
Utility Authority`, and `Housing Authority of the County of Santa Clara`
all also flagged as "implausibly long" in the same audit but are real,
correct, legitimately-long agency names.

**The identical bug existed independently in `escribe.py`**, not shared
code with Granicus — confirmed root cause, 6 real examples, found scanning
`/coverage`'s 501-row table for outliers.
`re.search(r"City of ([A-Za-z .]+)", page_text)` — the exact same
open-ended `[A-Za-z .]` character class, written separately from
Granicus's version. Real confirmed hits, all live-verified via the
meeting's own "View original source" link:
- `pub-cityofgainesville.escribemeetings.com` → "Gainesville General
  Policy Committee Meeting AGENDA Thursday, FL" (should be "Gainesville, FL")
- `pub-delta.escribemeetings.com` → "Delta Housing Accelerator Fund
  Initiatives Summary.pdf Recommendation" (should be "Delta, BC")
- Four real Canadian examples where the regex ran on past the city name
  into land-acknowledgment boilerplate: "Mississauga as being part of the
  Treaty and Traditional Territory of the Mississaugas of the Credit First
  Nation," "Oshawa is situated on lands within the traditional and treaty
  territory of the Michi Saagiig and Chippewa Anishinaabeg and the
  signatories of the Williams Treaties," "Port Moody Strategic Priorities
  Committee Agenda Tuesday," "Thunder Bay be approved in accordance with
  Table" (should be Mississauga/Oshawa/Port Moody/Thunder Bay, ON/BC
  respectively).

**Fix.** Rather than patching each adapter's regex independently, both
now call the shared `jurisdiction_enrich.extract_jurisdiction_chain()` —
a bounded stop-rule/capitalization-walk chain that was already built and
shipped for `swagit.py`/`civicclerk.py`/`generic_fallback.py` (PR #56,
2026-08-15/16) but never wired into Granicus or eScribe despite being the
exact fix this bug needed; every candidate it returns is validated
against the Census tables (directly, via trim-repair, or via the domain
registry) before being accepted, so it declines instead of guessing when
nothing cleanly bounds the match. `_extract_metadata()` in both adapters
now takes the raw `html` string (previously only `soup`/`url`) since the
capitalization-walk tier needs tag boundaries the parsed `soup` text
doesn't preserve. Granicus keeps its separate reversed "X County" regex
as a secondary fallback (not covered by the chain, which only handles
"X of Y" phrasing, and not itself flagged as buggy).

A second, real bug found and fixed in the same pass: eScribe's
`_jurisdiction_from_subdomain()` fallback (used when the chain declines)
was a bare `.replace("-", " ").title()`, which only helps a subdomain
with literal hyphens — every real customer confirmed live is one
concatenated word (`cityofgainesville`, `thunderbay`, `portmoody`), so a
multi-word city collapsed into one mashed-together word ("Thunderbay",
"Portmoody" instead of "Thunder Bay"/"Port Moody"). Now wordninja-splits
the label the same way Granicus's `_humanize_subdomain()` does, with
leading `city`/`county`/`town`/`of` tokens stripped — but deliberately
*not* gated on Census-table validation like Granicus's version
(`jurisdiction_enrich.validated_subdomain_extract()`), since eScribe
serves real Canadian customers the US-only Census tables can't validate
by construction (see WO-16 in `BACKLOG.md`); gating on validation here
would make the fallback decline on exactly the customers it most needs to
cover.

**Verification.** All 9 Granicus + 6 eScribe confirmed cases re-verified
(5 Granicus cases resolve correctly from page text alone; the other 4 via
Granicus's real per-customer subdomain convention — see the residual gap
split out in `BACKLOG.md`; all 6 eScribe cases resolve correctly via the
fixed subdomain fallback). Hercules re-verified against a fresh live fetch
of `hercules.granicus.com/player/clip/1306` (2026-08-16): the old regex
logic still reproduces the exact documented bug on today's page; the new
code produces `"City of Hercules, CA"`. That live HTML is now checked in
as `tests/fixtures/granicus/hercules_clip1306.html` and covered by
`test_extract_metadata_jurisdiction_no_longer_bleeds_into_agenda_text_hercules`.
New regression tests: `tests/test_granicus.py`'s
`test_extract_metadata_jurisdiction_bleed_regressions_text_only` (5 cases)
and `..._via_subdomain_fallback` (4 cases); `tests/test_escribe.py`'s
`test_extract_metadata_jurisdiction_no_longer_bleeds_into_agenda_text` (6
cases) and `test_jurisdiction_from_subdomain_splits_concatenated_multiword_names`.
Full suite (845 tests), `ruff check`, and `ruff format --check` all clean.

**Not fully closed** — see `BACKLOG.md`'s residual "Title-Case/ALL-CAPS
bleed" entry for the 4 Granicus cases that only resolve correctly today
via subdomain-fallback luck, not the text-based chain itself.

## WO-16: Census-table jurisdiction gaps (2026-08-16)

**Problem.** The 2026-08-14/15 649-jurisdiction Census-table validation
audit left four categories of confirmed gaps (`BACKLOG.md`): two archived
pages storing a literal date as their jurisdiction (source untraced);
townships/county subdivisions (Upper Providence PA, Greenburgh NY, Upper
Dublin PA — all confirmed real) missing from the lookup table entirely;
and Elliot Lake, ON needing some kind of non-US exemption since it was
never going to be in a US Census table.

**Fix, part 1 — townships/county subdivisions (the one real code
change).** Census tracks these as a wholly separate gazetteer (COUSUB),
not a subset of the counties/places tables already used —
`scripts/build_jurisdiction_data.py` gained `build_county_subdivisions()`,
downloading and filtering the real 2024 Census county-subdivision
gazetteer (`2024_Gaz_cousubs_national.zip`, 36,421 raw rows) to
`FUNCSTAT == "A"` only (16,157 rows) — deliberately narrower than
`places.csv`'s `"A"/"B"/"F"` (that expansion was earned by real confirmed
consolidated-government examples; COUSUB's own `"F"` rows are literally
placeholder `"County subdivisions not defined"` junk, and the other
codes — `G`, `C`, `B`, also real townships/towns on a quick sample — have
no `BACKLOG.md`-confirmed real example needing them yet, so left out
rather than guessed at). New `app/utils/jurisdiction_data/
county_subdivisions.csv`, loaded as `_SUBDIVISION_STATES` in
`jurisdiction_enrich.py` and checked as a third, lowest-priority tier in
`_table_lookup()` (after place, after county — a real city/county name
should always win over a same-named township, and no confirmed real case
needs the opposite). All three confirmed examples verified: `_table_lookup
("Upper Providence Township") == ("subdivision", ["PA"])` (this name is
genuinely real *twice* in PA — Montgomery and Delaware counties — still
resolves unambiguously since both agree on state), same for Greenburgh
NY and Upper Dublin PA.

**Real new finding from adding this table**: "Oshawa" (the Ontario city
several WO-14 eScribe test cases already used, land-acknowledgment
boilerplate) turns out to also be a real, if obscure, county subdivision
— "Oshawa Township, MN" — confirmed via a direct `_table_lookup("Oshawa")`
call returning `("subdivision", ["MN"])`. This flipped one of WO-14's own
regression tests from resolving via eScribe's subdomain fallback (bare
"Oshawa") to resolving via `extract_jurisdiction_chain()`'s primary
stop-rule tier instead (`"City of Oshawa"`, "City of" prefix intact,
stripped only at display time — see WO-14's own entry above). Traced all
the way through: the actual stored/displayed jurisdiction text is
unaffected either way (still correctly "Oshawa," never wrongly relabeled
to Minnesota — `enrich_jurisdiction_text()` doesn't attach a state suffix
just because a name happens to validate against a single-state table
entry, it needs an independent ZIP/domain signal to do that), only the
internal `jurisdiction_confidence` tag changes (`"validated"` instead of
whatever the fallback path would have produced) — and that field is
explicitly diagnostic-only with zero UI surface
(`JURISDICTION_METADATA_PLAN.md`). Fixed the now-overly-strict test
assertion (`tests/test_escribe.py`, exact `==` loosened to a substring
check, matching the more robust pattern `tests/test_granicus.py`'s own
WO-14 tests already used) rather than the underlying behavior, since
there was nothing incorrect to fix. Documented as a real, narrow,
accepted structural limitation of the whole validate-against-Census-
tables approach — any real US place/subdivision name that happens to
coincide with a well-known foreign place name carries this same risk,
not something specific to Oshawa or to this pass's change.

**Investigated, no code change — parts 2 and 3.** The two
literal-date-as-jurisdiction pages are no longer reproducible: a fresh
full scan of live production `/coverage` (843 rows today, up from 649 at
the original audit, fetched via a real `curl` against
`redtaperecordings.com`, not guessed) found zero jurisdictions matching a
plain "Month Day, Year" shape, and neither of the two originally-quoted
date strings appears anywhere on the page. Most likely already closed as
a side effect of WO-14's bleed fix (or a peer session's parallel work)
rather than independently root-caused here — the original two URLs were
never recorded at the time, and the audit's own `baseline_validation.csv`
no longer exists in any session's scratchpad, so there's no way to
confirm the exact mechanism, only that the symptom is gone today.
Elliot Lake, ON: directly tested `finalize_jurisdiction()` against
"Elliot Lake"/"Elliot Lake, ON" — both correctly grade `"unverified"`
(kept as given, not rejected, no wrong-US-state force-fit attempted), the
same documented-correct category real untabled entity types (school
districts, MPOs, and — per this finding — non-US jurisdictions
generally) already get. No live bug found to fix; the "exemption flag"
this item asked for would matter for a future re-run of the audit
*script* itself (so Elliot Lake doesn't inflate a "not in table" miss
count), and that script no longer exists to extend.

**Verification.** New test:
`tests/test_jurisdiction_enrich.py`'s
`test_table_lookup_recognizes_a_township_county_subdivision` (all 3
confirmed real townships, plus the two-Upper-Providence-Townships
same-state-still-unambiguous case). Full suite (854 tests), `ruff check`,
`ruff format --check` all clean. `county_subdivisions.csv` generated by
running the new build function directly against a freshly `curl`-fetched
real Census gazetteer file (not hand-written), same provenance standard
as the other three tables.

## WO-15: stale-archived-page refresh path (2026-08-16)

**Problem.** Two confirmed gaps combined into one recurring root cause:
re-submitting an already-archived URL through the public API never
triggered a refresh (it short-circuited to the cached lookup; only the
token-gated `GET /admin/recheck-archive-page` or the passive 30-day
`ARCHIVE_RECHECK_AFTER` cycle re-resolved it), and the YouTube
transcript-wanted queue (`crud.list_youtube_pages_missing_transcripts()`)
only ever surfaced pages with **no** default transcript at all, never an
existing-but-flagged-bad one. `BACKLOG.md` traces this pattern as the
likely root cause behind several separately-filed "why does this page
look wrong" bugs.

**Fix, part 1 — public refresh endpoint.** New `POST
/api/refresh-archived-page` in `app/main.py`: looks up the URL via
`archive_client.lookup()`, rejects with `not_archived` (404) if there's
no permanent page yet, enforces a `MANUAL_REFRESH_COOLDOWN` (1 hour —
shorter than the 30-day passive cadence since this is an explicit user
ask, but still a real floor so a "refresh" button can't be used to hammer
the real government source repeatedly) via `429 cooldown`, then calls the
existing `_recheck_archived_page()` synchronously and returns its result
— the same function the admin endpoint and passive sweep already use, so
no new resolve logic was written. Rate-limited (`10/hour` via the
existing slowapi limiter) and SSRF-guarded (`check_destination()`) the
same as `/api/resolve`. A "Refresh this page" button was added to
`archive/templates/meeting_page.html` (`archive/static/meeting_page.js`'s
`wireRefreshPageButton()`, styled in `archive/static/style.css`) — calls
the resolver's endpoint via a plain relative `fetch()`, which works
same-origin with no CORS setup needed because `app/main.py`'s existing
`/m/{slug}` route already proxies the Archive's pages through the
resolver's own origin (confirmed by checking `archive/static/
meeting_page.js`'s existing `wireReportProblemForm()`/`wireTranscribeForm()`,
which already call other resolver-hosted `/api/*` routes the same way).

**Fix, part 2 — quality-aware transcript-wanted queue.**
`list_youtube_pages_missing_transcripts()` (`archive/db/crud.py`) used to
only check `~default_exists` (no `is_default=True` row at all). Now
reuses `_has_good_transcript()` — the same quality gate
`list_transcription_backlog_candidates()` already uses (real segments +
`_has_real_warning_free_transcript()`) — so a page whose default is
*present but garbled* (e.g. a Whisper audio-fallback transcript that
never got real captions) resurfaces too. Strict broadening: the original
"no row at all" case still returns `False` from `_has_good_transcript()`
(no segments), so nothing regresses.

This surfaced a second real gap: `archive/db/crud.py`'s
`_is_real_improvement()` (which decides whether a fresh ingest push
auto-becomes the page's new default) is deliberately narrow — it only
auto-promotes when the current default has no segments at all, or has
segments but no language. A page now in the broadened queue because its
default is garbled already has segments+language, so a fresh real-caption
push would silently create a new *non-default* version and leave the
garbled one live and visible — the queue would think the problem was
fixed while the page itself looked unchanged. Fixed by having
`scripts/fetch_youtube_transcripts.py` explicitly call the already-built
`POST /internal/transcript-version/promote` (added same-day, 2026-08-16,
for `scripts/transcribe_backlog_locally.py`'s opt-in `--promote` flag)
after every successful push — always, not opt-in, since a genuinely-
fetched real YouTube caption track is unconditionally more trustworthy
than whatever's already flagged bad (unlike `transcribe_backlog_locally.py`'s
own Whisper-based re-transcriptions, where quality varies enough to want
a human's say-so first).

**Verification.** New tests: `tests/test_refresh_archived_page.py` (5
cases: not-archived 404, cooldown 429, real recheck fires past cooldown,
missing-`updated_at` never blocks, SSRF guard fires before any lookup),
`tests/test_transcript_wanted.py`'s new
`test_wanted_includes_youtube_page_with_garbled_transcript`,
`tests/test_fetch_youtube_transcripts.py`'s two new `process_one()`
promote tests (promotes when `version_id` is set; skips cleanly when it
isn't). Full suite (853 tests), `ruff check`, `ruff format --check` all
clean. Live-verified locally end-to-end against a real (SQLite,
non-production) resolver+Archive pair: created a real archived page,
clicked the actual "Refresh this page" button in-browser — confirmed the
429 cooldown response and its styled error message, backdated
`updated_at` past the cooldown, clicked again — confirmed a real (not
mocked) `_recheck_archived_page()` call fired, attempted a genuine fetch
against the (nonexistent) test URL, failed gracefully, and rendered "No
changes found at the source." with no crash and no unhandled exception.

**Not verified against a real already-broken production page** (e.g.
Fountain Valley clip 607 or the `riversidecountyca.iqm2.com` title bug,
both cited in `BACKLOG.md` as the pattern this mechanism should help
with) — deliberately not done this pass: triggering a real re-scrape
against production data isn't something to do unprompted, and more
importantly, both of those pages' *underlying* root causes are still
separate, unfixed bugs of their own (IQM2's title/jurisdiction
extraction, and Fountain Valley clip 607's still-undetermined data
mismatch) — this mechanism only removes the "how would a fix ever reach
the already-archived page" blocker, it doesn't retroactively produce
correct data from an adapter that's still extracting the wrong thing. Once
either of those adapter bugs is actually fixed, re-verifying via a real
click on the live page (rather than the token-gated admin endpoint) is
the natural way to confirm this mechanism works end-to-end in production
— split out as its own follow-up rather than closed here.

## Local-Mac transcription backlog script — bigger model than the worker's forced "tiny" (2026-08-16)

Built to work down the real ~209-meeting `/meetings?has_transcript=false`
backlog: `worker/`'s cloud transcription worker is forced to
`faster-whisper` `"tiny"` by Render's 2GB plan (see
`worker/transcription_engine.py`'s own docstring — real OOM crashes on
`"small"`, not a quality choice), and `"tiny"`'s real accuracy has two
confirmed failure modes already on record in `BACKLOG.md`'s "On-demand
transcription" section (a meaning-changing mistranscription, a
near-total transcription failure on a real Napa stretch of English
speech). A local Mac has no such RAM ceiling, so
`scripts/transcribe_backlog_locally.py` runs there instead, with a
bigger model.

**What shipped:**
- `scripts/transcribe_backlog_locally.py` — discovers candidates, re-
  resolves each fresh via the same `app/platforms/base.py` adapter
  registry the worker/resolver use, probes duration and skips anything
  implausible (`app/platforms/media_probe.py`'s existing 5-min-to-14-hour
  bounds), extracts audio directly (`extract_chunk_audio()`, no full
  download) in 900-second chunks, transcribes each chunk locally, and
  pushes the finished transcript back through `POST /internal/ingest`
  with `"source": "transcribed"` explicitly set. `--model-size` defaults
  to a real-RAM-based pick (`"small"` at ≥16GB, `"medium"` at ≥32GB,
  `"base"` otherwise — see `_pick_default_model_size()`'s own docstring),
  not a guess. `--url` lets one specific meeting be targeted directly,
  bypassing the oldest-first queue (added mid-build, once it became clear
  the queue's first several real candidates were multi-hour meetings —
  needed a way to target a short one for a fast verification pass, and
  it's generally useful afterward too, the same "target one page
  directly" pattern `/admin/recheck-archive-page?url=` already offers on
  the resolver side).
- `GET /internal/transcription-backlog` (`archive/main.py` +
  `archive/db/crud.py`'s new `list_transcription_backlog_candidates()`)
  — the any-platform, batch counterpart to `/internal/transcript-wanted`'s
  YouTube-only queue. Reuses `find_auto_transcription_candidate()`'s own
  `_has_good_transcript()`/`_in_auto_transcription_cooldown()` checks
  directly, so this script and the worker's own idle-time auto-generation
  path never duplicate feasibility-probe effort on (or fight over) the
  same recently-failed page. Returned candidates include YouTube-backed
  pages too (not filtered server-side) since a plausible future
  YouTube-audio-fallback mechanism (BACKLOG.md's still-open "Whisper
  fallback for YouTube videos with no captions at all" entry — a
  different mechanism, yt-dlp audio download rather than direct URL
  extraction, since a resolved YouTube `video_url` is a
  `youtube.com/embed/{id}` page, not something `ffprobe`/`ffmpeg` can
  extract audio from directly) might want them; this script's own
  `process_one()` filters them out cheaply client-side instead, on
  `video_format == "youtube"`.
- `IngestRequest.source` (`archive/main.py`, optional, defaults to
  `"scraped"` — every existing caller, resolver pushes included, is
  unaffected). Real correctness fix this closes: `archive/db/crud.py`'s
  `ingest_resolution()` previously hardcoded every fresh `TranscriptVersion`
  to `source="scraped"` regardless of what actually produced it — fine
  when every caller's content genuinely was scraped from a government
  source, but this script's content is Whisper-transcribed and needed to
  read that way. Silently mislabeling it "scraped" would have meant it
  read as an authoritative government caption instead of getting the real
  `meeting_page.html` "AI TRANSCRIPT" disclaimer the worker's own
  `source="transcribed"` output already gets — a real reputational risk
  this repo has already flagged directly (the Cupertino/Napa hallucination
  findings above), not a cosmetic labeling detail. The content-hash dedup
  check in the same function was scoped to `source` too (previously
  hardcoded to compare only against existing `"scraped"` rows) — without
  that, a `"transcribed"` push could never dedup against an earlier
  identical `"transcribed"` push, creating a fresh duplicate version every
  time the same meeting got re-run with the same result.

**Deliberately does not touch `transcription_jobs`/`claim_next_chunk()`
at all** — `claim_next_chunk()`'s own docstring is explicit that it's
safe for exactly one worker process, not concurrent ones (no row-level
locking). This script is a second, independent process that could run
at the same time as the real worker, so it follows `scripts/fetch_
youtube_transcripts.py`'s established pattern instead: discover and push
purely over the same token-gated `/internal/*` HTTP surface, idempotent
and content-hash-deduped either way, so a rare race with the cloud worker
picking up the same page just gets deduped, not double-versioned.

**Verification, real not synthetic:**
- Local functional test first, before ever touching production: an
  isolated SQLite instance (`DATABASE_URL=""`, explicitly forced — see
  the "real problems hit" note below), 3 synthetic `MeetingPage` rows
  (no transcript at all / a recent failed job in cooldown / YouTube-
  backed with no transcript), confirmed `GET /internal/transcription-
  backlog` returns exactly the right 2 candidates (excludes the
  cooldown one) and respects `limit`; confirmed `POST /internal/ingest`
  with `source="transcribed"` renders the real "AI TRANSCRIPT" disclaimer
  on the resulting page, and that same-source dedup / cross-source
  non-dedup both work as designed (pushed identical content twice under
  `"transcribed"` → 1 version; pushed the same content again under
  `"scraped"` → a distinct 2nd version, not deduped against the first).
  `pytest` — 789 passed, no regressions (initially saw 5 failures caused
  by test-DB pollution from this same manual testing, not a real
  regression — see below).
- Landed via PR #81 (`gh pr create` + `gh pr merge --squash
  --delete-branch`, from an isolated worktree per this file's own
  multi-session convention), which deployed the new `/internal/*`
  endpoint to the real Render Archive service. Confirmed live via a
  direct `GET /internal/transcription-backlog` call against the real
  `ARCHIVE_BASE_URL` (200, a real candidate returned) before proceeding.
- **Real end-to-end run against the live backlog**: queried the real
  endpoint for candidates, `ffprobe`'d several to find a short one (the
  queue's first several real entries — Chula Vista, Watsonville — turned
  out to be 3.5+ hour meetings, impractical for a fast verification pass)
  — landed on Welland/Elgin County, ON
  (`welland-2026-01-27-county-council-meeting`, eScribe, a real
  783-second/13-minute recording, no prior transcript). Ran for real
  (`--model-size small`, not even the cloud worker's `"tiny"`): 102 real,
  coherent segments (`language=en`) in 113 seconds wall time, pushed
  successfully. Confirmed live on the actual public page
  (`https://redtaperecordings.com/m/welland-2026-01-27-county-council-meeting`):
  the real "AI TRANSCRIPT" disclaimer renders, and real timestamped
  segments are present starting "We're live." at 0:00 through real
  adjournment/motion dialogue at the end ("Motion is carried... Councilor
  Woodner moves. Deputy warden Jones seconds... I think we have a new
  record.") — coherent, on-topic content, not a hallucination loop. A
  follow-up `GET /internal/transcription-backlog` call confirmed the page
  no longer appears in the queue.

**Real problems hit while building this, not hypothetical:**
- Running a local `uvicorn archive.main:app` for dev testing, `python-
  dotenv`'s default `load_dotenv()` (no explicit path) walks *upward*
  from the calling module's own directory looking for a `.env` — since
  this worktree is nested inside the main repo checkout (which has its
  own real `.env`), that search silently found and loaded the outer
  repo's real `DATABASE_URL`, `ARCHIVE_BASE_URL`, and
  `ARCHIVE_INGEST_TOKEN` into a supposedly-isolated local test process.
  Caught immediately (the query failed with a schema mismatch against
  whatever that `DATABASE_URL` pointed at — not confirmed to be real
  live production specifically, but treated as if it might be) — no
  writes occurred (only a failing `SELECT`), but real enough to be worth
  recording explicitly: always force `DATABASE_URL=""` (an explicit,
  already-present env var, which `load_dotenv()`'s default
  non-override behavior respects) when running any local dev/test server
  from inside a nested worktree, not just leaving it unset.
- That same `DATABASE_URL=""` habit, used again for a full `pytest` run,
  collided with `tests/conftest.py`'s own `os.environ.setdefault
  ("DATABASE_URL", ...)` — `setdefault` only fills in a *missing* key,
  and an explicit empty string already counts as "present," so the test
  suite silently fell through to `archive/db/engine.py`'s own local-dev
  fallback file (`./archive_dev.db`) instead of the isolated tmpfile
  `conftest.py` sets up per session. That file already had leftover rows
  from earlier manual testing, producing 5 real (but non-representative)
  test failures on count-based assertions. Not a real regression —
  confirmed by re-running with `DATABASE_URL` genuinely unset (not
  `""`) against a clean checkout: 789 passed. Worth remembering
  specifically because it looks exactly like a real regression at a
  glance.

## Napa VOD "Testing 123" hallucination: proposed ffmpeg fix disproven, original symptom no longer reproduces (2026-08-16)

Picked up the still-open "second, distinct manifestation of the
hallucination failure mode" entry (the County of Napa 2026-06-02 Board
of Supervisors meeting, 0:00–8:57 transcribing as repeated "Testing one,
two, three" plus fabricated Spanish-looking text) rather than blindly
implementing its proposed `-fflags +genpts` fix — that flag was
explicitly flagged "untested" in the entry itself, so verified first,
per this file's own "verify before generalizing" convention.

Fetched the real production HLS URL directly (via the live meeting
page's own embedded video URL, `archive-stream.granicus.com/OnDemand/
_definst_/mp4:archive/napa/napa_10ae7709-....mp4/playlist.m3u8`) and ran
three real local checks with ffmpeg 8.1.2 + the repo's own
`faster-whisper==1.2.1`:

1. **`-fflags +genpts` does nothing** — reproduced the exact same "Queue
   input is backward in time" / "non monotonically increasing dts"
   warnings with the flag present, identical to without it.
2. **A different flag, `-af aresample=async=1`, does eliminate every
   warning — but the extracted audio itself is unchanged.** Transcribed
   both the warning-free and warning-riddled extractions through the
   exact same model config; the transcripts were line-for-line
   identical (one trivial 2-second segment-boundary shift). The dts
   warnings are a cosmetic libmp3lame-muxer complaint about
   container-level timestamp metadata that never affected which audio
   samples actually reached Whisper — there was no real bug in
   `extract_chunk_audio()` to fix.
3. **The originally-reported hallucination itself doesn't reproduce.**
   Re-ran the exact 2026-08-12 repro (same URL, same single continuous
   0–900s chunk, same model/prompt/beam_size) and got a single brief
   "Testing 1, 2, 3" at 0–15.7s, then a clean, accurate transcript the
   rest of the way through 900s (a real Pledge of Allegiance, "Pet of
   the Week" segment, and the full Pride Month proclamation, all
   transcribed correctly) — not the ~17x repeated phrase plus fabricated
   Spanish text originally reported. Most plausible explanation, not
   conclusively confirmed: `worker/requirements.txt` pins no version for
   `faster-whisper` (bare `faster-whisper` line, no `==`), so every
   fresh build picks up whatever's newest — a real possibility an
   upstream release between 2026-08-12 and now already fixed this class
   of repetition-loop hallucination (a known Whisper-family bug
   category), unrelated to anything in this app's own code. Not chased
   further (would need pinning + bisecting historical `faster-whisper`
   releases, out of scope for closing this entry).

Closed the entry as "no code fix needed" rather than leaving a disproven
fix hypothesis open or implementing a flag that (confirmed) changes
nothing. No code changed; this is a research-only close-out.

## Jurisdiction validation gaps: "Saint"/"St.", ʻokina, CivicClerk agenda-text fallback (2026-08-16)

Three follow-on fixes picked up after closing out the easy-win triage
waves, same "root cause and fix direction already established" bar:

- **`_table_lookup()` (`app/utils/jurisdiction_enrich.py`) rejected two
  real, legitimately-spelled name families.** "Saint Paul" never matched
  the Census table's own "St. Paul city" key — confirmed via a direct
  grep of `places.csv`: this ONE prefix family (of the six
  `_ABBREV_EXPANSIONS` covers) is stored abbreviated in the real table
  (148 "St. " rows, zero "Saint " rows), the opposite of Fort/Mount/
  North/South/East/West, all stored spelled out — so the existing
  abbreviation-expansion tier (built for exactly the opposite direction)
  never helped here. New `_contract_saints()` tries the reverse
  ("Saint"/"Sainte" → "St."/"Ste.") as an additional candidate tier.
  Separately, "Kauaʻi" (real Hawaiian ʻokina) never matched the table's
  plain "Kauai" (no diacritic) — new `_strip_okina()` tier strips
  ʻokina/apostrophe-like characters before lookup. Two new tests in
  `tests/test_jurisdiction_enrich.py`. Full suite green (784 tests).
- **CivicClerk's blank-`eventLocation` fallback (fixed same day, see
  "Easy-win triage" above) only tried the free, URL-only tier of
  `extract_jurisdiction_chain()` — the source entry's "path (2)"
  remainder is now built too.** New `_fetch_agenda_text()`
  (`app/platforms/civicclerk.py`) fetches the event's own
  `publishedFiles` "Agenda" entry as plaintext (swap `plainText=false`
  → `plainText=true` on the existing `GetMeetingFile` URL, which returns
  `{"blobUri": ...}` pointing to a SAS-signed Azure blob, then fetches
  that blob directly) and feeds the real text through the same chain —
  a richer signal that doesn't depend on wordninja splitting a
  customer's subdomain cleanly. Only tried once the free tier has
  already failed, since it costs two extra requests. New regression
  test (`test_resolve_falls_back_to_agenda_plaintext_when_subdomain_also_fails`)
  uses a synthetic subdomain/place name specifically so it doesn't
  depend on the free tier also failing to fire, keeping the two tests
  independent. Full suite green (785 tests).

## Easy-win triage waves 1 + 2 — 9 backlog items shipped (2026-08-16)

Both waves scoped in BACKLOG.md's "Easy-win triage" section (a direct
pass through the file to pull out genuinely low-risk, root-cause-known
items) landed in two commits, full suite green throughout (782 pytest +
29 JS tests by the end). Source entries for each item, struck through
with a pointer to this entry, live wherever they originally were in
BACKLOG.md/BACKLOG_DONE.md — not duplicated in full here.

**Wave 1 — copy & data only:**
1. Contact `mailto:` links (`app/templates/base.html`,
   `archive/templates/base.html`) now point at
   `ally@redtaperecordings.com` instead of `ryan@`. The same email-audit
   entry's other leftover, `app/templates/about.html`'s feedback link
   (previously `ryan@how-to-adu.com`, a personal inbox, not a
   `redtaperecordings.com` address at all), fixed the same way 2026-08-16
   in a follow-on pass.
2. Transcription rate-limit 429 copy (`app/static/player.js`,
   `archive/static/meeting_page.js`) rewritten to "You've hit the
   transcript request limit for now — please try again in about an
   hour." The harder half of the source ask — signed-in users bypassing
   the limit entirely — is still open (slowapi's `@limiter.limit(...)`
   applies unconditionally at decoration time, no existing per-request
   bypass pattern in this codebase).
3. `README.md` no longer says saved-search alert emails are "Not yet
   built" — `archive/search_alerts.py` is real, merged, and cron-driven
   via `.github/workflows/send-search-alerts.yml`.
4. `netapps.ocfl.net` (Orange County, FL) registered in
   `app/utils/jurisdiction_enrich.py`'s `_KNOWN_DOMAINS` — pure data, no
   code change needed since `finalize_jurisdiction()` (called from
   `archive/db/crud.py`'s `_find_or_create_page()`) already consults the
   registry for every adapter's ingest.
5. Swagit's `_extract_metadata()` (`app/platforms/swagit.py`) now
   collapses internal whitespace (`re.sub(r"\s+", " ", raw_title)`)
   after extracting `raw_title`, fixing a literal tab character from
   Swagit's own `<title>` tag passing straight through into stored
   titles (confirmed live on a real DFPS, TX page via `curl`).

**Wave 2 — small, self-contained logic fixes:**
6. `civicclerk.py`'s `resolve()` now falls back to
   `jurisdiction_enrich.extract_jurisdiction_chain(page_text="",
   html="", url=url)` whenever `eventLocation` yields no usable
   jurisdiction string at all (not just a missing state) — confirmed
   live on Los Altos Hills, CA (event 4567), new regression test added
   to `tests/test_civicclerk.py`.
7. `granicus.py`'s `resolve()` now appends a `transcript_warnings` entry
   whenever a chosen caption track's segment count is exactly 36,000 —
   Granicus's own undocumented per-file cue cap on very long meetings,
   confirmed on 3 independent real customers (College Park GA, Coral
   Gables FL, Marion County FL). New regression test in
   `tests/test_granicus.py` uses a synthetic 36,000-cue VTT (a real one
   would be an unwieldy fixture).
8. New public `jurisdiction_enrich.validated_subdomain_extract()`
   (thin wrapper around the existing tournament-tested
   `_validated_subdomain_extract()`) replaces `granicus.py`'s
   `_humanize_subdomain()`'s bare always-guess wordninja split. The
   function now declines (returns `None`) instead of guessing when
   neither the raw subdomain nor its wordninja split validates against
   the Census place/county tables — fixes garbage like "sfwmd" →
   "S Fw, MD" while keeping real cities ("fresno" → "Fresno, CA")
   working. A trailing US state abbreviation is still stripped and
   reattached as a ", ST" suffix independently of validation, same as
   before (some subdomains encode it specifically to disambiguate a
   nationally-ambiguous city name). Two new regression tests in
   `tests/test_granicus.py` (one legit-city, one declined-acronym).
   Not yet re-resolved against the ~15 already-archived rows with this
   bug — the fix only changes future resolves.
9. `/coverage`'s "Every place we've covered" table
   (`archive/templates/coverage.html`) gained a frozen leftmost
   row-number column (`position: sticky; left: 0`, lighter font-weight)
   and clickable Government/Example meeting/Transcript headers that sort
   the table client-side — new `archive/static/coverage.js` (repeat
   click toggles ascending/descending; "Transcript" sorts by badge
   presence) plus new CSS in `archive/static/style.css` (an explicit
   `background` on the sticky column plus a manual striped-row overlay,
   since Bootstrap's own `.table-striped` background wouldn't otherwise
   reach an element pinned out of the normal row). Row numbers renumber
   to the sorted display order rather than staying tied to the original
   alphabetical rows, per the source entry's explicit scoping. Verified
   live in a real browser (not just the test suite): seeded a local
   Archive instance, confirmed sort-by-click reorders rows and
   renumbers correctly, and confirmed the sticky column's computed
   style (`position: sticky; left: 0px`) via direct JS inspection.

## `page.platform` never refreshed on re-ingest of an existing page — found while verifying TelVue, fixed, then closed 8 more "unknown" pages (2026-08-16)

Found while checking whether TelVue's 3 known real meetings had actually
come off the "unknown platform" list after `telvue.py` shipped earlier
the same session. They hadn't, even though re-ingesting them demonstrably
worked (real segments/agenda_items/video_url all updated correctly,
confirmed live on `/m/august-11-2026-ashland-planning-commission` and the
other two). Root cause, confirmed reading `archive/db/crud.py`'s
`_find_or_create_page()`: the `else:` branch (updating an *existing*
matched page) refreshed `title`/`date`/`jurisdiction`/`video_url`/
`video_format`/`agenda_items`/`video_warnings`/`agenda_link`/`updated_at`
— every content field a later, better resolve could improve — but never
reassigned `page.platform`, so it stayed frozen at whatever value the
page had on first creation. Content was genuinely fixed; the platform
*label* just silently lied about it forever after. Affected every page
whose adapter was added/fixed *after* the page was first archived under
`platform="unknown"` (or any wrong prior platform value), not just the
3 TelVue ones.

**Fixed in [PR #69](https://github.com/mroconnell/rtr-deeplink/pull/69)**:
`page.platform = payload.get("platform") or page.platform` as the first
line of the same `else:` branch, mirroring the existing truthy-gated
pattern already used for every other field just above it. New regression
test (`tests/test_ingest_promotion.py::test_reingest_updates_platform_on_an_existing_page`)
reproduces the exact real scenario: ingest under `platform="unknown"`,
re-ingest the same URL under a different platform with a different
`external_id` (matching how the real TelVue pages fell through to the
`source_url_normalized` match path, not the `external_id`+`platform`
path) — asserts platform actually updates. Full suite passing at merge
time (771/771).

**Real, unrelated production incident hit right after merging**: Render's
deploy for this exact commit failed —
`ERROR: Could not install packages due to an OSError:
HTTPSConnectionPool(host='files.pythonhosted.org', port=443)... too many
502 error responses` — a transient PyPI CDN failure, not a code problem
(confirmed zero new imports in the diff). Diagnosed via the `render` CLI
(services list → deploys list → build logs filtered by timestamp) and
fixed by triggering a redeploy of the same commit
(`render deploys create srv-d9ras3ijnfac73f9ps5g --confirm`); the
redeploy succeeded and the fix was verified live immediately after.

**Follow-up the same day**: re-checked all remaining "unknown"-platform
pages via `/internal/pages/all-urls` now that the fix was deployed (13 →
8 after this pass). Found real, new value in 3: a clerkshq/Yellow
Springs OH page (4,712 segments), a seattlechannel.org page (7,210
segments + 8 agenda_items), and confirmed `netapps.ocfl.net` correctly
*stays* `unknown` (no adapter exists for it, working as intended). Also
found a genuinely new tier-3 candidate this way —
`riversidecountyca.iqm2.com` (real video, no transcript) — added to
`scripts/tier3_auto_transcription_queue.txt` and shipped as
[PR #70](https://github.com/mroconnell/rtr-deeplink/pull/70).

**Re-checked again 2026-08-16, after the Hyland adapter work below
shipped**: `platform="unknown"` count is down to 4 (`/internal/pages/
all-urls` re-fetched fresh, not from a cached copy). Of those,
`mccobagenda.databankcloud.com`'s `id=4665` page — one of the 8 in the
previous count — is now correctly `platform="hyland"` after being
re-ingested as part of that work. The remaining 4 are `netapps.ocfl.net`
(no adapter, expected — see its own "Orange County FL" entry elsewhere
in this file), `discover.pbc.gov` (SharePoint, no adapter, expected),
`cityofsebastopol.gov` (no adapter, expected), and, surprisingly,
`riversidecountyca.iqm2.com` itself — the same URL just re-ingested via
this section's own PR #70, on a domain `iqm2.py` clearly does have an
adapter for. That one looks like a real, fresh gap rather than an
expected "no adapter" case and is logged as its own open item in
`BACKLOG.md`.

## Hyland "OnBase Agenda Online" — expanded from 3 to 23 real customer domains, second UI version + YouTube delegation added (2026-08-16)

Follow-on to the adapter build below, same day, prompted by the user
finding real example URLs via plain web search after the initial 3-customer
version shipped. Grew into a much bigger platform-coverage pass:

**Second UI version ("Version B") found and supported.** Two real URLs
(Santa Barbara CA, Concord CA) run a genuinely different UI version of
this product: the original `Meetings/ViewMeetingAgenda` endpoint
redirects to a generic error page for these customers, and the real
agenda outline instead comes from `Documents/ViewAgenda` (a converted-
Word-document render via Aspose.Words) whose real item ids still join
against the same `itemEventPoints` video-seek mechanism as the original
version. `resolve()` tries the original endpoint first (safe
unconditionally -- Version B's redirect target never matches the title/
date regex) and falls back only when that yields nothing. Real bug
caught building this: Version B's item text can span multiple sibling
`<span>` tags inside one link, and extracting only the first span
truncated real content (confirmed on Concord: "Considering" instead of
the full real sentence) -- fixed with a full-anchor-then-strip-tags
extraction, scoped to Version B only.

**YouTube delegation added.** A real Municipality of Anchorage, AK
meeting confirmed this vendor's page template also supports a plain
YouTube iframe embed instead of JW Player (the page's own JS references
both "JWPlayer.cshtml" and "YoutubePlayer.cshtml"). `_find_video()` now
falls back to `YouTubeAssetFinder` delegation whenever no direct media
file is found, matching escribe.py/civicclerk.py's existing pattern --
also picks up a real transcript as a side effect, something no JW-Player
customer on this platform has had before.

**20 more real customer domains found and registered**, growing the
platform from 3 to 23 total, via three methods layered on top of each
other:
1. User-supplied real URLs (Santa Barbara, Concord, plus a
   researcher-supplied list of subdomain-naming conventions the user
   relayed -- Steamboat Springs CO, Whittier CA, Compton CA, Sarasota
   County FL, Municipality of Anchorage AK, Santa Cruz CA, Hamilton
   County OH's Job & Family Services instance, plus a `padre.org` and a
   `hamilton-co.org` "Search Meeting Content" landing page that
   confirmed the same product without an easily obtainable real meeting
   id via a plain GET).
2. Wayback CDX subdomain enumeration of the two known shared-hosting
   apex domains (hylandcloud.com: 87,473 crawled URLs, 129 unique
   subdomains; databankcloud.com: 767 URLs, 8 subdomains), filtered to
   subdomains with an `agendaonline` path in their own crawl history --
   found Dunwoody GA, Durango CO, Gilbert AZ, Henderson NV, Tempe AZ
   (reachable here even though the separately-found `www.tempe.gov` page
   is Akamai-blocked), and Westerville OH. Two more candidates
   (`3cenergy.hylandcloud.com`, a second `maricopa.hylandcloud.com`
   tenant) are confirmed dead (DNS failures live) and were not
   registered.
3. A `site:.gov inurl:OnBaseAgendaOnline/Meetings/ViewMeeting` web
   search -- found Pittsburg CA, Modesto CA, Centennial CO, and a
   second, distinct Santa Barbara CA subdomain
   (`records.santabarbaraca.gov`, alongside the already-found `docs.`
   one -- both resolve independently). Two more candidates
   (`documents.provo.gov`, `onbase.sandiego.gov` -- San Diego's real
   `.gov` domain) are confirmed dead (404/DNS failure on their own site
   root, not just one stale id) and were not registered.
   `sandiego.hylandcloud.com` (found via method 2) does resolve, but its
   only content (5 total crawled URLs ever, oldest dated 2016) reads as
   an abandoned pilot rather than the city's actual current system
   (almost certainly Granicus, like every other major CA city already
   covered) -- registered anyway since it's real and resolving, with
   that caveat noted in the registry comment.

Every one of the 20 new domains was confirmed with a real, correctly-
resolving `ViewMeeting` URL through the actual adapter before being
registered -- none enumerated blind. Real, non-obvious confirmation from
this pass: none of the 20 needed any adapter code change beyond a
jurisdiction registry entry, despite real path-prefix variance across
them (`198agendaonline` through `251agendaonline`, plus fully custom
prefixes like `gilbertagendaonline` and `211agendaonlinecouncil`) --
direct evidence the routing/version-probing logic already generalizes
rather than being tuned to the first few customers.

Verified: 3 new fixture-backed tests (`tests/test_hyland.py`, now 7
total for this platform) covering Version B's fallback, its real
multi-span text-truncation fix, and YouTube delegation with a real
transcript. Full suite 778/778 passing. End-to-end `bulk_ingest.py
--dry-run` against all 29 known real URLs across all 23 domains,
confirming correct `platform=hyland` routing and real title/date/
agenda_items/video for every one.

## Hyland "OnBase Agenda Online" — new dedicated adapter built, overturning the earlier "genuinely renders client-side" conclusion (2026-08-16)

Built `app/platforms/hyland.py`, replacing `generic_fallback.py`'s
patchwork handling of this platform (below) for all 3 confirmed real
customers: `tucsonaz.hylandcloud.com` (Tucson, AZ, no video), `mccobagenda.
databankcloud.com` (Maricopa County, AZ), `agendanet.saccounty.gov`
(Sacramento County, CA) — routed in `base.py` on the shared
`/Meetings/ViewMeeting` URL path shape (confirmed identical across all 3
despite each using a different preceding product-name path segment and a
different hosting domain — an earlier routing attempt also required
`"agendaonline"` in the path, which real-world-tested false on Sacramento's
`/BoardofSupervisors/Meetings/ViewMeeting` shape; caught via
`bulk_ingest.py --dry-run` against the real URL, not by inspection).

**The real finding that made this worth a dedicated adapter, not just a
`_KNOWN_DOMAINS` registry entry**: this product's own
`/Meetings/ViewMeetingAgenda?meetingId={id}&type={doctype}` AJAX endpoint
returns real, plain server-rendered HTML via a bare `curl` — no JS
execution needed — on all 3 customers, including Tucson. **This directly
overturns this file's own earlier conclusion** ("the AJAX endpoint...
returns the same empty vendor-branded shell, not real meeting data —
everything genuinely renders client-side," which drove building and
enabling the headless-browser escalation for this exact page shape). That
earlier probe used the page's own literal, unsubstituted
`type=AGENDATYPEVALUE` JS-template placeholder rather than the real
`doctype` value from the URL — once substituted, the endpoint returns a
real `<h1>{meeting name}<br>{date time}<br></h1>` header plus a full
nested outline of `accessible-item`/`accessible-section` divs, each real
item carrying its own text and a `loadAgendaItem({id})` onclick. Confirmed
against fresh `curl` fixtures for all 3 customers, saved to
`tests/fixtures/hyland/`.

**Second real finding, only relevant to the 2 customers with video
(Maricopa/Sacramento, not Tucson)**: the main `ViewMeeting` page's inline
`itemEventPoints`/`sectionEventPoints` JS objects (flagged as "not
investigated further" in the Sacramento entry below) map that same numeric
item id to a real video-seek offset in seconds. Joining the two endpoints
on that shared id produces a real, timestamped `agenda_items` list (48
items for Maricopa, 35 for Sacramento) — genuine per-agenda-item deep
linking, with no headless browser and no per-customer heuristics beyond
the id join. Tucson has no video, so no event points exist there either;
it falls back to `agenda_link` pointing at its own real per-meeting AJAX
URL (not the OnBase site root `_find_agenda_link()`'s best-effort scan
used to return).

Video extraction (Maricopa/Sacramento) reuses `media_scan.scan_media_urls`/
`is_hls_url`/`media_type` rather than re-implementing JW-player `file:`
parsing — the same shared code already fixed for this exact page shape's
`&amp;token=` entity-decoding and query-stringed-`.m3u8` bugs during the
2026-08-14 generic-fallback rebuild, so this adapter can't regress either
one. No caption/transcript track of any kind was found on any of the 3
samples' JW Player config (no `tracks:` key at all, unlike TelVue) — this
platform is video(+agenda)-only until a real example says otherwise.

Jurisdiction: none of the 3 known domains has reliable in-page text
(Maricopa/Tucson have zero; Sacramento's sits in a generic sitewide
`<title>`, one unconfirmed-to-generalize sample) — all 3 registered in
`jurisdiction_enrich._KNOWN_DOMAINS` instead, same reasoning as this
file's existing LIMS/CivicWeb precedent for this exact situation. A future
4th OnBase customer needs its own registry entry the same way (not
automatic) — a real, expected residual, not a bug.

Verified: 4 new tests in `tests/test_hyland.py` (real fixtures, no
synthetic HTML), full suite 775/775 passing, and end-to-end via
`bulk_ingest.py --dry-run` against all 3 live URLs post-fix, confirming
correct `platform=hyland` routing and the exact real title/date/
agenda_items/video counts shown above.

## Checked empirically: no other adapter has eScribe/CivicClerk's YouTube-delegation gap (2026-08-16)

Prompted by a fair challenge after the eScribe/CivicClerk fixes above:
a lot of government sites embed YouTube, so is it really plausible that
only two adapters out of the whole set have this gap? The earlier check
had only been a code-pattern audit (grep for an arbitrary/configurable
external-URL field) — real, but not the same as looking at real data.

Ran the empirical version: pulled every live `MeetingPage` via
`/internal/pages/all-urls` (1,073 pages), excluded platforms already
confirmed to delegate properly (youtube, primegov, civicweb, clerkbase,
telvue, lims, slc, escribe, civicclerk — the last two fixed earlier this
session), leaving 730 pages across granicus (383), swagit (241), iqm2
(86), cablecast (2), viebit (2), aurora_tv (1), ca_legislature (2), and
the residual `unknown` bucket (13). Fetched each page's own rendered
`/m/{slug}` HTML (fast — hits our own Render service, not 700+ external
government sites) and regex-matched `data-video-url`/`data-video-format`
for a youtube.com/youtu.be URL.

**Result: zero genuine hits.** One match came back (`unknown` /
`welcome-to-clerkbase`, a clerkshq/YellowSprings-OH page), but it isn't a
new gap — it's the same `page.platform` staleness bug documented in
`BACKLOG.md` (that page was ingested before `clerkbase.py`'s own
delegation existed, so it's frozen at `platform="unknown"` even though
the adapter resolves it correctly today; `clerkbase.py` already
delegates to `YouTubeAssetFinder` properly, confirmed reading its
source). 5 of 730 fetches hit a transient `URLError` and weren't
retried (under 1% of the sample) — not enough to change the conclusion,
but a real gap in this check's own script if it's ever rerun.

Conclusion: granicus/swagit/iqm2/cablecast/viebit/aurora_tv/
ca_legislature are all real video-hosting products in their own right
(that's their business model), so their customers don't typically *also*
embed a separate YouTube video the way an agenda-only platform like
eScribe or CivicClerk sometimes does when a customer has no native video
integration. No further adapter work needed here — closed, not just
deprioritized.

## TelVue: a whole new platform found hiding as "unknown"; CivicClerk had the same YouTube-delegation gap as eScribe (2026-08-16)

Follow-on from the eScribe fix above, prompted by the user asking what a
self-audit of our *own already-live pages* (not new enumeration) might
surface. Pulled every live `MeetingPage` via `/internal/pages/all-urls`
(1,071 pages total that session) and looked specifically at the 13 rows
with `platform="unknown"` — real, already-ingested meetings that
`generic_fallback.py` had to handle because no dedicated adapter existed.

**TelVue — a real platform with zero coverage, found from 3 real
customer meetings already live under `platform="unknown"`** (2 direct
`videoplayer.telvue.com` URLs, 1 reached via a `u.peg.tv` shortlink).
Investigated live against a real Ashland, OR Planning Commission meeting:
everything needed — video (`master.m3u8`), real per-speaker closed
captions, and a separate real chapters/agenda track — is embedded as
plain JSON in the static page HTML
(`Player.setupData['playlist']`), no JS execution needed. Confirmed
`u.peg.tv/s/{code}` is a plain HTTP redirect straight to the
`videoplayer.telvue.com` page (`u.peg.tv/s/6abzuu` → 200 on the TelVue
URL) — same wrapper pattern as Legistar/CivicPlus's Granicus delegation,
so no separate PEG.tv adapter was needed, just routing both domains to
one `TelvueAssetFinder` in `detect_platform()`.

Built `app/platforms/telvue.py`, registered it, added real fixture-backed
tests (`tests/test_telvue.py`, fixtures from the real Ashland meeting).
Verified live against both the direct URL and the peg.tv redirect: real
segment counts (2683 and 4108) and real agenda chapters (9 and 15) on
first try. Real gap caught building this: WebVTT `<v Speaker N>...</v>`
voice tags aren't stripped by `parse_vtt()` on its own — without
stripping them the transcript would have literally shown
`<v Speaker 1>Recording in progress.</v>` — handled locally in the
adapter rather than touching the shared parser, since this is the first
platform this codebase has seen with voice-tagged VTT. Jurisdiction is
best-effort only (extracted from the title's body-name portion, e.g.
"Ashland Planning Commission" → "Ashland") since TelVue's URL path uses
an opaque per-customer org token, not a readable city name the way
eScribe's `pub-{city}` subdomain is — unconfirmed against multiple real
customers.

Re-ingested the 3 already-live URLs afterward (real `bulk_ingest.py`, not
dry-run) — all 3 matched their existing `MeetingPage` row by
`source_url_normalized` and updated in place (`platform` upgraded from
`unknown` to `telvue`, real transcripts/agenda attached), confirmed by
comparing slugs before/after: no duplicates created.

**CivicClerk had the identical YouTube-delegation gap eScribe did, just
via a different code path.** Found by re-running the same "zero
transcript, is_youtube=True" check from the eScribe investigation against
`resolved_platform="civicclerk"` rows — 3 hits
(`ashlandcowi`/`eriecopa`/`highlandparkil`.portal.civicclerk.com). Root
cause, confirmed reading `civicclerk.py`: some customers set
`externalVideoUrl`/`externalMediaUrl` to a plain YouTube link, but the
adapter's `video_format` was computed purely from the URL's file
extension (`video_url.rsplit(".", 1)[-1]`) — a `youtube.com/watch?v=...`
URL has no matching extension, so `video_format` came back `None`. That's
worse than just missing captions: the frontend needs
`video_format="youtube"` specifically to trigger the iframe+Player-API
playback path, so the video may not have played at all, confirmed live
on `ashlandcowi` event 362 (`video_format=None`, `segments=0`) before the
fix.

**Fixed**: when `video_url` matches a YouTube URL shape
(`YouTubeAssetFinder.extract_video_id()` returns a real id), delegates to
`YouTubeAssetFinder.resolve_video_id()` for the correct `video_url`/
`video_format`, and only falls back to YouTube's captions when
CivicClerk's own `closedCaptionTracks`/`closedCaptionUrl` come back empty
— CivicClerk's own captions are kept when present, since those are
usually curated per-meeting rather than auto-generated. Updated the
existing real-fixture test (`clovisca_event17`, a real Clovis, CA sample
already in the suite) to assert the fix rather than the old broken
behavior, with `YouTubeAssetFinder._extract_info` properly mocked.
Verified live: 2 of the 3 real cases now resolve with real segments
(3042, 1602) and correct `video_format="youtube"`; the third
(`eriecopa`) genuinely has no captions available on YouTube's side —
expected variance, not a bug, matching the escribe fix's 49/51 (not
51/51) real-world hit rate. Real-ingested the 2 successful cases.

`pytest` full suite: 770/770 passing after both changes.

## eScribe never delegated to YouTube for captions on its own found-video pages (2026-08-16)

Found while cataloguing where video actually lives for ~1,200 "zero
transcript" URLs accumulated across this and a prior session (real
resolve re-checks, not archived-URL guesses — see
`rtr-business/research/video_hosting_catalog_combined.csv`, built by a
new `scripts/catalog_video_hosting.py`). 51 of the 269 eScribe pages in
that "no transcript, agenda items, or agenda link found" bucket turned
out to have a real, live YouTube embed — `escribe.py`'s own
`scan_page_for_video_evidence()` backstop tier had already found the
video, but `platform` stayed `"escribe"` (not `"youtube"`), which is why
grepping the dry-run log's `platform=X` text for `youtube` (the first,
cheaper check tried) undercounted this to zero — only re-resolving each
URL directly and reading `result.video_url`/`video_format` surfaced it.

Root cause, confirmed reading the source: `scan_page_for_video_evidence()`
(`generic_fallback.py`) is deliberately detection-only — its own
docstring says so ("the YouTube tier returns the embed URL directly
rather than running YouTubeAssetFinder's metadata resolve, since an
opting-in adapter already has its own better metadata"). Every *other*
caller that reaches this tier already does the follow-up call itself:
`generic_fallback.py`'s own `resolve()`, `primegov.py`, `civicweb.py`,
`clerkbase.py` all call `YouTubeAssetFinder.resolve_video_id()` once they
have a video id. `escribe.py` was the one adapter that took the detected
embed URL as final without ever fetching captions for it — not a
timing/network issue, a genuine missing code path.

**Fixed**: `escribe.py`'s backstop branch now extracts the video id from
the returned embed URL and calls `YouTubeAssetFinder.resolve_video_id()`
the same way `primegov.py` does, keeping eScribe's own (usually better)
title/date extraction and only falling back to YouTube's when eScribe's
own came back empty — same override reasoning `primegov.py`'s docstring
already gives.

**Verified live** against 5 real, previously-zero-segment pages
(`pub-beaumontab`, `pub-brant`, `pub-cambridge`, `pub-courtenay`,
`pub-mackenziebc`.escribemeetings.com): all 5 now resolve with real
segment counts (3207, 3016, 6500, 2680, 1009) where they previously
showed `segments=0`. `pytest tests/test_escribe.py` still 10/10 after the
change — no regression to eScribe's own native (iSiLIVE) caption path.
Real-ingested all 51 confirmed eScribe+YouTube URLs afterward via
`scripts/bulk_ingest.py` (no dry-run) — see the git commit for the
outcome tally.

**Not checked further**: 3 URLs in the same catalog resolved as
`platform=civicclerk` with a YouTube video found but zero
segments/agenda — plausibly the same missing-delegation gap in
`civicclerk.py`, not confirmed. Left open if it recurs.

## "Request Transcript from Audio" rendering on genuinely no-video pages (2026-08-15)

Real gap raised by the user 2026-08-14 while investigating Palm Beach
County's SharePoint page (`BACKLOG.md`'s Wayne County/Palm Beach entry),
independently re-confirmed against the real archived page
`/m/meeting-890af1`. Two connected bugs, not one — found by tracing the
full click path before touching anything, not just the obviously-visible
symptom:

1. **The main CTA button had no video-presence check at all.**
   `meeting_page.html`'s `show_transcribe_cta` was computed purely from
   whether an AI transcript already existed
   (`not (active_version and active_version.segments and
   active_version.source == "transcribed")`), so it rendered on every
   page site-wide regardless of `page.video_url` — including genuinely
   empty pages (Wayne County/Tucson/Palm Beach-style) where clicking it
   can't possibly produce anything, since there's no audio source to
   point a transcription job at. Fixed by gating on `page.video_url` too.
2. **A sharper, previously-unnoticed version of the same bug, found by
   checking what a fix to (1) alone would actually leave behind.**
   `generic_fallback.py`'s `_NO_VIDEO_FOUND_WARNING` text literally said
   "you can try to request a transcript from the audio" on a page with no
   video *or* audio source. `archive/utils/render_warnings.py` auto-wraps
   that exact phrase into a clickable `.transcribe-inline-trigger`
   button, and `archive/static/meeting_page.js:536` fires it with **no
   null guard**
   (`document.getElementById('transcribeToggle').click()`). So fixing
   (1) alone would have silently turned the *inline warning-text* version
   of this same broken promise into a real JS exception on click, instead
   of the harmless-but-misleading no-op it is today — a worse bug than
   the one being fixed. Closed by rewriting the warning text to stop
   promising something impossible (confirmed no other adapter's warning
   text contains this exact phrase, via a repo-wide grep, so this was the
   only source).

Verified live (not just via the API): seeded a local Archive DB with one
no-video page and one has-video page, confirmed in-browser via the actual
rendered `/m/{slug}` HTML that the button is absent on the former and
still present on the latter. `tests/test_generic_fallback.py` gained a
regression assertion that the misleading phrase is gone from
`_NO_VIDEO_FOUND_WARNING`. Full suite green (764 tests) throughout.

## Wave 1: meeting-page CSS drift/overflow, auto-scroll toggle port, jurisdiction search, LIMS endOffset, SEO tier 2 (2026-08-14)

Shipped in one commit (`2421f9f`, #52) — seven small, independently
root-caused fixes from `BACKLOG.md`/`CLAUDE_BACKLOG.md`. Recorded here
2026-08-15, a day after the fact — the commit landed but the source
backlog entries were never moved out, exactly the doc-drift class of
problem this repo's own "App-wide audit" entry already flags. 721 pytest
+ 29 npm tests green; live-verified end to end against a real resolved
Jacksonville, FL Granicus meeting.

- **Agenda/transcript timestamp column drift.** `.transcript-segment`'s
  grid (`archive/static/style.css`, `app/static/style.css`) used an
  `auto`-sized first column, so each row's timestamp width was fit to
  that row alone — a list spanning `[0:05]` to `[7:59:59]` visibly
  drifted row to row. Fixed to a fixed `8.5ch` column (comfortably fits
  the longest real timestamp at the 14-hour transcription cap, in the
  monospace font already used). Verified live: timestamp columns align
  at 83.47px/27.2px/326.5px across all 2177 real segments on the
  Jacksonville test page.
- **Meeting pages rendering unusually wide.** `#transcriptColumn` (the
  `1fr` grid track holding agenda/transcript content) had no
  `min-width: 0`, so an unbreakable long agenda-PDF URL (confirmed real,
  a ~185-character unbroken token on a Sacramento County page) forced
  the track past its fair share, pushing `.meeting-page` past its own
  `max-width: 860px`. Fixed with the same `min-width: 0` override
  already used for `.calendar-candidate-main`/`.saved-item-main`.
- **Auto-scroll toggle missing on every permanent `/m/{slug}` page.**
  The resolver's ephemeral `/meeting?url=` page had a real
  `#toggleAutoScrollBtn`/`autoScrollEnabled` toggle
  (`app/templates/meeting.html`, `app/static/player.js`); the Archive's
  permanent pages never had one at all —
  `archive/static/meeting_page.js` hardcoded auto-scroll on with no way
  to turn it off. Ported the toggle markup/JS/CSS across. Verified live:
  renders and actually toggles.
- **LIMS agenda items never got a real `end` timestamp.**
  `lims.py`'s `_flatten_timestamps()` set `end == start` for every item
  (no per-item duration data), so `meeting_page.html`'s `Clip` JSON-LD
  guard (`end > start`) was never true for any LIMS page — every LIMS
  `Clip` silently missed `endOffset` (one of the 8 non-critical issues
  Google's Rich Results Test flagged on a real Minneapolis LIMS page).
  Fixed by adopting Granicus/IQM2's existing convention: each item's
  `end` becomes the *next* item's `start` (the last item keeps
  `end == start`, unavoidable without real duration data). Verified
  directly against the real `MarkedAgenda/COW/6144` fixture.
- **`/meetings`' jurisdiction filter couldn't match a full state name.**
  Real regression from the 2026-08-11 `normalize_state_suffix()` fix
  (see that entry below): once stored jurisdictions consistently end in
  a 2-letter abbreviation ("Sacramento County, CA"), a plain substring
  filter against the stored column means searching "California" matches
  nothing while "CA" always works — confirmed live 2026-08-14. Fixed via
  `jurisdiction_search_terms()` (`archive/utils/jurisdiction_format.py`),
  reusing the existing `US_STATE_NAME_TO_ABBR` table to expand a
  full-name search term to its abbreviation (or vice versa) so either
  form matches. Verified: `jurisdiction=California` and `jurisdiction=CA`
  now return the same results.
- **`uploadDate` missing an ISO-8601 timezone + no `Event` JSON-LD.**
  Second half of the 2026-08-12 Google Search Console alert (the
  `thumbnailUrl` half shipped separately 2026-08-14, see the
  "VideoObject.thumbnailUrl + Clip key moments" entry below).
  `uploadDate` now emits `date + "T00:00:00Z"` instead of a bare date
  string (real per-adapter time-of-day capture would be a much bigger,
  multi-adapter lift — WCAG-markup research elsewhere in this repo found
  only Portland.gov of 7 real government sites checked actually exposes
  real time-of-day, so this interim fix is deliberately not literally
  accurate, just validator-clean). A new `Event` JSON-LD block sits
  alongside the existing `VideoObject` one (`name`/`startDate`/
  `jurisdiction` were already on the page). Verified: both render as
  valid JSON-LD on the test page. **Still open, not touched this pass**:
  direct mp4/m3u8 pages (the majority of the Archive) still have no
  `thumbnailUrl` at all, pending real `ffmpeg` frame extraction and
  somewhere to host the frames; and the separate "invalid datetime
  value" flag (at least one real row has a non-`YYYY-MM-DD` `date`) was
  never cross-checked against production data — both remain real,
  tracked gaps, not silently dropped.
- **No `<link rel="canonical">` on `/meetings` or `/coverage`, no
  `<meta name="description">` on the resolver's `index.html`/
  `about.html`.** `/meetings`' seven independent query params created
  real duplicate-content surface area with no canonical pointing back to
  the bare unfiltered URL. Added canonical links to both pages
  (`archive/templates/meeting_list.html`, `coverage.html`) and meta
  descriptions to both resolver pages, including adding the
  `{% block meta %}` `base.html` itself was missing. Verified: canonical
  links render on `/meetings` and `/coverage`.
- **`CLAUDE.md` corrected a stale claim** that eScribe/PrimeGov/YouTube
  had zero test coverage — all three were already fixture-covered by
  this point, per README's own "Running tests" section.

## Jurisdiction/title extraction pipeline (2026-08-15)

Part of the multi-round improvement described in
`JURISDICTION_METADATA_PLAN.md` — see that file for the full baseline
audit, extraction tournament, and design rationale this work grew out of.

- **[Done 2026-08-15] `places.csv` was missing every real consolidated
  city-county government (Nashville-Davidson, Louisville/Jefferson,
  Indianapolis, Baton Rouge, and 6 others), because
  `build_jurisdiction_data.py`'s `build_places()` only kept Census
  FUNCSTAT "A" rows.** Root-caused against the *actual* 2024 Gazetteer
  file, not guessed — downloaded it fresh and inspected the real
  FUNCSTAT distribution (19,465 "A", 12,820 "S" CDPs, 34 "I" inactive, 8
  "F", 4 "N" nonfunctioning, 2 "B"). Every one of the 8 "F" rows and
  both "B" rows is a real, actively-governed city, just filed under
  Census's own "... (balance)" statistical-area naming for the 8 (its
  own docs: "F" marks a statistical *area* construct, not a claim the
  government is fictitious) or coded "B" because the government legally
  overlaps its parish (Baton Rouge, Lafayette, LA). Fix: broadened the
  filter to `FUNCSTAT in ("A", "B", "F")`, confirmed against a full
  regeneration that this adds exactly those 10 real rows and nothing
  else (fresh run against freshly re-downloaded Census source files,
  `git diff --stat` showed only `places.csv` changed, +10 lines, no
  changes to `counties.csv`/`zcta_*.csv`).

  **A second, real bug found while testing the fix, not before
  shipping it**: `jurisdiction_enrich.py`'s `_normalize_name()` needed
  new logic to strip the "(balance)" suffix and the government-type
  phrase ("metropolitan government"/"metro government"/"unified
  government"/"consolidated government") before these new rows could
  ever be looked up by their real common names. The first version of
  that fix applied the *existing* trailing-type-word strip
  unconditionally afterward too — which turned "Greeley County unified
  government (balance)" into just "greeley", colliding with three
  unrelated real cities named Greeley (CO/IA/KS) and making an
  otherwise-clean, unambiguous county lookup falsely return `None`. Caught
  by testing all 8 "F" rows individually before considering the fix
  done, not just the ones that happened to work. Fixed by skipping the
  generic trailing strip whenever the government-type phrase already
  matched — "County" in "Greeley County" is part of the real
  distinguishing name here (a *county* consolidated government, not the
  unrelated city), same class of trap as the already-documented
  "Oklahoma City"/"Carson City" case in this same function. Verified:
  `lookup_city_state("Greeley County") == "KS"` and
  `lookup_city_state("Greeley")` still correctly returns `None`
  (genuinely ambiguous, must not resolve).

  Regression tests added:
  `test_lookup_city_state_resolves_real_consolidated_city_county_governments`
  (all 7 city-shaped entries, individually) and
  `test_lookup_city_state_does_not_over_strip_a_consolidated_government_name`
  (the Greeley collision, both directions) in `tests/test_jurisdiction_enrich.py`.
  Full suite green (734 tests) both before and after.

- **[Done 2026-08-15] `extract_jurisdiction_chain()`'s capitalization walk
  could pick up a real city name mentioned inside spoken caption
  dialogue, not the meeting's own jurisdiction, and would have stored it
  as-is.** Found running workstream 4's dry-run backfill diff against
  real cached HTML (not hypothetical): a Broward MPO Swagit page
  (`browardmpo.new.swagit.com/videos/359517`) has an ALL-CAPS caption
  line — "...ALSO, THE S. MIDDLE RIVER MOBILITY PROJECT IN THE CITY OF
  FORT LAUDERDALE THAT'S IDENTIFIED..." — that the walk matched into,
  producing `"City of Fort Lauderdale That'S Identified"`. The
  `_looks_like_bleed()` trim-repair gate correctly declined to trim it
  (neither `"That'S"` nor `"Identified"` starts lowercase, so nothing
  signals bleed), but the chain still returned the ungated raw candidate
  — the same class of false positive `_JURISDICTION_RE`'s own
  module-level comment in `app/platforms/primegov.py` already documents
  for PrimeGov's agenda-body text (the SLC/Holladay case), now confirmed
  on a second, independent adapter/page.

  Fix: `extract_jurisdiction_chain()` now requires every candidate to
  actually clear `finalize_jurisdiction()`'s own bar (validated/repaired/
  authoritative) before accepting it — a candidate that doesn't is
  discarded and the next tier is tried, rather than ever being returned
  raw. This is deliberately stricter than `finalize_jurisdiction()`'s
  general policy of keeping an *adapter-native* unvalidatable
  jurisdiction unchanged (real special-purpose entities like school
  districts have no table to validate against, but a real trust basis in
  the adapter's own purpose-built extraction) — none of this chain's
  three tiers have that trust basis, since they're all generic regex
  guesses over arbitrary page text.

  Adding this gate exposed a second, smaller gap: it would have also
  rejected genuinely correct page-abbreviated names ("Ft. Worth", "Mt.
  Vernon" — real names real websites write that way, see this file's own
  entry on `_STOPRULE_ABBREV_OK` in `JURISDICTION_METADATA_PLAN.md`)
  since the Census table's own key is the spelled-out form ("Fort
  Worth"). Fixed by adding `_expand_abbreviations()` (St./Ste./Ft./Mt./
  Pt./N./S./E./W. → their full forms) as an extra candidate
  `_table_lookup()` tries when the raw name doesn't match as-is —
  narrowly scoped to `_table_lookup()` only (not the public
  `lookup_city_state()`/`lookup_county_state()` API other adapters call
  directly via `resolve_state()`), to keep this fix's blast radius
  contained to the new validation gate and `finalize_jurisdiction()`'s
  own validate/trim/split path.

  Re-ran the workstream-4 dry-run diff (against the same cached 649-page
  HTML the tournament already fetched, no new network requests) after
  the fix: the Fort Lauderdale row disappeared from the change set
  entirely (jurisdiction correctly stays blank) and no other row's
  confidence dropped to "unverified" as a *new* value — every remaining
  proposed change is validated/repaired/authoritative. Regression tests:
  `test_extract_jurisdiction_chain_rejects_a_capitalization_walk_false_positive`
  (the real Fort Lauderdale case) and `test_table_lookup_recognizes_a_page_authored_abbreviation`
  in `tests/test_jurisdiction_enrich.py`. Full suite green (763 tests).

- **[Done 2026-08-15] The whole jurisdiction pipeline merged to `main`,
  deployed, and the real backfill executed against production**
  ([PR #56](https://github.com/mroconnell/rtr-deeplink/pull/56)) — with
  one real deploy-pipeline mistake caught and corrected mid-session, not
  before. All 6 commits on `jurisdiction-pipeline-r1` had sat unmerged
  the whole time this feature was being built, tested, and dry-run —
  `main`/`origin/main` never moved. A first live "execute the 21" backfill
  run (real network re-resolves, real pushes to production) went through
  cleanly with 0 failures, but a spot-check on `redtaperecordings.com`
  afterward showed the Hercules page's jurisdiction completely unchanged.
  Root cause, confirmed directly: querying production Postgres for
  `meeting_pages.meeting_body` raised `UndefinedColumnError` — the new
  Alembic migrations had only ever been run against local SQLite this
  session (by design, to avoid touching production `DATABASE_URL` for a
  schema diff), never against production. The backfill script pushes via
  an HTTP call to the Archive's own deployed service (`archive_client.push()`),
  not a direct DB write from local code — so it had been re-resolving
  each page correctly with the new adapter code, then handing the result
  to a still-*old*-code production service with no `finalize_jurisdiction()`
  call and no new columns, which just silently re-stored the same
  already-bled raw value. No data was corrupted (a same-value overwrite,
  not a bad write), but the backfill's actual purpose never fired.

  Fix, in order: (1) pushed the branch, opened PR #56, merged to `main`
  after CI passed (`gh pr merge --squash --delete-branch`, blocked once by
  branch protection until the required "test" check finished); (2) ran
  `alembic upgrade head` for both services directly on Render's own shell
  (not from a local machine — `archive/alembic/env.py` and
  `app/alembic/env.py` each read their DB URL from their own service's
  `DATABASE_URL`, and this repo's local `.env` has an entirely different
  `DATABASE_URL` — the resolver's own dev DB, not either production
  database — so running migrations locally without an explicit override
  risked targeting the wrong database entirely); (3) confirmed both
  production databases' `alembic_version` tables were already correctly
  tracked at each migration's expected `down_revision` before running
  (clean forward migration, no stamping needed); (4) re-ran the 21-page
  backfill for real once the schema was in place.

  **A second, smaller mistake, caught immediately via the same
  discipline**: the post-backfill verification query itself first went
  through `archive.db.crud` (importing `archive/db/engine.py`, which
  resolves its own `DATABASE_URL` from env) instead of the dedicated
  `ARCHIVE_DATABASE_URL` this session's read-only cross-service scripts
  already used correctly earlier (see the tournament's
  `fetch_tournament_sources.py`) — same wrong-database class of mistake
  as the deploy issue above, just local and read-only. Caught by the
  query failing with the identical `UndefinedColumnError`, re-diagnosed
  by comparing the resolved database *names* (not just hosts, which
  matched) across all three: `archive.db.engine.DATABASE_URL` and env
  `DATABASE_URL` both resolve to `rtr_deeplink_db` (the resolver's own
  database); only `ARCHIVE_DATABASE_URL` resolves to `rtr_archive`, the
  real target. Re-verified correctly via a direct `asyncpg` query against
  `ARCHIVE_DATABASE_URL`: all 21 pages landed exactly as the dry-run
  predicted (e.g. Hercules: `jurisdiction_confidence="repaired"`,
  `"City of Hercules, CA"`; the Santa Clara Housing Authority page:
  `meeting_body="Housing Authority"`, `jurisdiction="County of Santa
  Clara, CA"`). Confirmed rendering correctly live on
  `redtaperecordings.com`'s `/meetings` search for both.

  **Lesson for next time a schema-changing branch sits unmerged while
  being developed and dry-run**: a clean local test suite and a clean
  dry-run against cached data prove the *code* is correct, never that
  it's *deployed* — always check `git log main..<branch>` (or just try a
  live read against production) before trusting a "successful" live push
  actually exercised the new logic, not just the old code silently
  absorbing it.

## Site polish

- **[Done 2026-08-14] `VideoObject.thumbnailUrl` (YouTube-backed pages) +
  `Clip` "key moments" structured data on `/m/{slug}` — the two
  doubly-endorsed SEO tier-1 items from `CLAUDE_BACKLOG.md`'s 2026-08-13
  audit, built per the user's direct ask during the discoverability
  strategy session.** Addresses the critical half of `BACKLOG.md`'s
  Google Search Console entry (missing `thumbnailUrl` blocks video
  rich-result eligibility outright) and turns `agenda_items`' real
  per-item timestamps into Google-renderable chaptered "key moments."

  What shipped: new `archive/utils/video_thumbnail.py` —
  `youtube_thumbnail_url()` derives the free, predictable
  `i.ytimg.com/vi/{id}/hqdefault.jpg` thumbnail from any YouTube-shaped
  `video_url` (the 11-char-id regex mirrors `app/platforms/youtube.py`'s,
  duplicated rather than imported across the service boundary per the
  existing `clerk_auth.py` convention; `hqdefault` specifically because
  `maxresdefault` 404s on many older uploads) — registered as a Jinja
  filter in `archive/main.py`. `meeting_page.html`'s meta block now
  emits, for YouTube-backed pages: `thumbnailUrl` in the `VideoObject`
  JSON-LD plus `og:image`/`twitter:card` (the same underlying gap as
  `CLAUDE_BACKLOG.md`'s "Social share previews" item — one fix, both
  uses; a shared deep link now unfurls with the video thumbnail instead
  of a bare text card). And for any page with real agenda timestamps:
  a `hasPart` array of `Clip` objects (`name` truncated to 100 chars —
  IQM2 items can carry full ordinance text — `startOffset`,
  `endOffset` only when `end > start`, and a `?t={start}` deep-link
  `url`, the same contract the visible agenda timestamps produce).
  Gated three ways: requires `public_base_url` (Clip URLs must be
  absolute, same guard as canonical/og:url), skips when the agenda
  section's own `unreliable_timestamps` condition holds (the
  all-items-at-0:00 CivicClerk shape — key moments claiming 26 items
  all start at 0:00 would be false navigation; expression duplicated
  into the meta block since Jinja blocks don't share scope, with
  keep-in-sync comments on both copies), and omits the key entirely
  rather than emitting an empty array.

  Verified: 8 new tests (`tests/test_meeting_page_structured_data.py`)
  — filter unit tests (embed/watch/youtu.be shapes, None for m3u8/
  missing) and rendered-page tests via the ingest→GET `/m/{slug}` path,
  where `json.loads` on the extracted JSON-LD doubles as a validity
  check on the hand-built template JSON (synthetic payloads, but the
  embed-URL shape is exactly what `youtube.py` builds and agenda items
  use the real `{start, end, text}` segment shape). Full suite 680
  passed. Live-verified in-browser against a locally-served seeded page:
  `JSON.parse` of the rendered JSON-LD succeeds in the browser,
  thumbnail/clips/og:image/twitter:card all present and correct, agenda
  section renders unchanged, no new console errors (the two 404s seen —
  `/archive-static/*` — are a pre-existing artifact of hitting the
  Archive service directly instead of through the resolver's proxy,
  confirmed unrelated).

  **Residuals, split back out as live items**: mp4/m3u8 pages still have
  no thumbnail (needs real ffmpeg frame extraction — the majority of
  archived pages, so the Search Console complaint isn't fully closed,
  see `BACKLOG.md`'s updated entry) and the `uploadDate`
  timezone/invalid-value half of that same entry is untouched. Google's
  actual rendering of key moments should be re-checked in Search
  Console once a real YouTube-backed page with agenda items is
  re-crawled — structured-data validity is confirmed, rich-result
  *uptake* is Google's call, not verifiable locally.

- **[Done 2026-08-14] Minneapolis LIMS stores raw HTML inside agenda item
  text — real adapter bug found live-verifying the Clip markup above,
  now fixed at the extraction source, not just papered over in the
  template.** Confirmed on production
  (`/m/city-of-minneapolis-mn-2026-08-10-committee-of-the-whole`,
  real source `MarkedAgenda/COW/6144`): the Agenda section was
  rendering items like
  `&lt;a href='/Download/CommitteeReport/4915/...pdf'
  class='previousmettingdate' aria-label='...'>Business, Housing &
  Zoning Committee ` as literal escaped text — `app/platforms/lims.py`'s
  `_flatten_timestamps()` was storing a category's
  `SerializedVideoTimestamps` title verbatim, and this particular
  category type (a Committee Report cross-link, not every category)
  carries a raw, unclosed `<a>` tag right in the title string. Sibling
  file-level titles on the same meeting are plain text, so this is a
  category-level quirk specific to how LIMS labels a Committee Report
  reference, not a wholesale format shift.

  Fixed with a new `LimsAssetFinder._clean_title()` (strips tags via
  `_HTML_TAG_RE`, collapses leftover whitespace) called on both the
  category-level and file-level title before building each
  `TranscriptSegment` — plain titles pass through byte-for-byte
  unchanged. Deliberately fixed at the adapter/extraction layer, not
  with a defensive `striptags` in the display template (the open
  question the same-day Clip-markup entry above left undecided) — the
  template already got its own narrower `striptags` for the `Clip` JSON-LD
  specifically, but the real fix belongs where the data enters the
  system, per this repo's general convention of not silently absorbing
  a source-data bug downstream.

  Verified three ways: 2 new tests in `tests/test_lims.py`
  (`test_clean_title_strips_real_html_anchor_shape` using the exact
  stored text recovered from the production page, plus a full-resolve
  regression test) — both COW and non-COW existing tests untouched, 683
  passed full-suite. Live-verified on production after deploy+re-push:
  scanned all 11 archived Minneapolis pages
  (`https://redtaperecordings.com/meetings?jurisdiction=Minneapolis`)
  for `&lt;a href` in their rendered HTML — found contamination on
  exactly 2 (`COW/6120` and `COW/6144`, both Committee of the Whole
  meetings; the other 9, including several City Council and other
  committee types, were already clean), used
  `GET /admin/recheck-archive-page?url=...` (documented in README's
  "Caching and reporting" section) to force a fresh re-resolve + Archive
  push of both against the fixed adapter, then re-fetched both rendered
  pages and confirmed zero `&lt;a href` occurrences and correct Clip/
  agenda text (e.g. "Business, Housing & Zoning Committee", no leaked
  markup) on both.

  **Still open, explicitly not decided or checked this pass**: whether
  any other adapter has the same latent issue — only LIMS is confirmed;
  and the same-day entry's open question about a defensive
  template-level `striptags` for the visible agenda section (not just
  the Clip JSON-LD) remains genuinely undecided, now lower-priority
  since the actual source-data bug is fixed.

- **[Done 2026-08-10] Built a branded 404 page on both services, plus
  logging when one is hit — the "custom 404 / not-found page, plus an
  error log when it gets hit" ask.** Confirmed neither service had one
  before: every unmatched route fell through to FastAPI's default
  plain-JSON 404, and the one existing branded case (Archive's
  `/m/{slug}` for an unknown meeting page, already using its own
  `not_found.html`) logged nothing.

  Registered a `StarletteHTTPException` handler on both `app/main.py`
  and `archive/main.py` (`not_found_handler`) that intercepts only
  genuinely unmatched routes — confirmed via `grep` that neither service
  ever explicitly `raise`s `HTTPException`, so every existing deliberate
  404 (API/internal endpoints) is a plain `JSONResponse` return, not a
  raised exception, and never reaches this handler; verified this
  directly with a test hitting `/admin/stats` with no token (a real,
  network-free JSON-404 example) and confirming it stays JSON, not the
  new HTML page. For a real 404, both services now log
  `logger.warning("404: %s (referer=%s)", ...)` (the referer is exactly
  the "old bookmark / stale external link" signal that was invisible
  before) and render a matching `not_found.html` — reused the Archive's
  existing template as-is, added a new equivalent for the resolver
  (`app/templates/not_found.html`, linking back to `/`, the resolver's
  actual primary action). Also added the same logging to the Archive's
  existing `/m/{slug}` not-found path, previously silent.

  5 new tests (`tests/test_404_handling.py`): branded-page rendering on
  both services, the warning log firing with the right path/referer,
  the existing API-404 JSON path staying unaffected, and the Archive's
  `/m/{slug}` case now logging too. Full suite: 326 passed (321 + 5 new).
  Live-verified in-browser against local dev servers (resolver proxying
  to a real local Archive instance, matching production's reverse-proxy
  shape): a genuinely unmatched resolver path, a bad `/m/{slug}` proxied
  through to the Archive's own page, and a real valid `/m/{slug}` (to
  confirm the happy path wasn't accidentally caught by the new handler)
  — all three rendered exactly as expected, and both dev server logs
  showed the new warning line firing (including, as a bonus real-world
  confirmation, a genuine browser-requested `/favicon.ico` correctly
  triggering the resolver's handler too).

  Sitemap and the site footer (the other two "site polish" asks from the
  same message) were still open at the time this was written.

- **[Found already done 2026-08-10] Sitemap turned out to already exist
  — the BACKLOG.md entry describing it as unbuilt was stale, not a real
  gap.** Went looking to scope it as its own task and found `GET
  /sitemap.xml` already fully built on the Archive
  (`archive/main.py`/`archive/templates/sitemap.xml.jinja`, backed by
  `crud.list_all_page_slugs()`), proxied through the resolver at the
  same path (matching the `/m/*`/`/archive-static/*`/`/feed.xml`
  pattern, keeping SEO authority on `redtaperecordings.com`), and
  already referenced in the resolver's dynamically-generated
  `robots.txt` (`Sitemap: https://redtaperecordings.com/sitemap.xml`).
  Confirmed live in production, not just in code: `curl`ed
  `https://redtaperecordings.com/sitemap.xml` directly and got a real
  200 with real `<loc>`/`<lastmod>` entries for actual archived
  meetings, and confirmed `robots.txt` really does point at it. No work
  needed — removed the stale bullet from BACKLOG.md rather than leaving
  a "not yet built" note describing something that already works.

- **[Done 2026-08-10] Built a universal site footer with Sitemap/RSS/
  Coverage/Contact links, closing out the last open "site polish" ask.**
  Clarified scope with the user first (real ambiguity, not guessed):
  both services get it (not just the resolver, which already had a
  minimal one), the existing subscribe prompt gets folded into the same
  footer rather than staying a lone paragraph, and the extra links are
  specifically RSS feed, Coverage, and Contact/report-a-problem (the
  user didn't pick "About," so it wasn't added).

  The resolver (`app/templates/base.html`) already had a `<footer>`
  with just the subscribe prompt, conditionally hidden on `/subscribe`
  itself; restructured it into a `.footer-links` nav row (always shown)
  plus the subscribe prompt (still conditionally hidden there). The
  Archive (`archive/templates/base.html`) had no footer at all —
  added the identical structure, matching this codebase's existing
  precedent of deliberately duplicating shared markup/CSS across the
  two services' independent templates (see `archive/static/style.css`'s
  own header comment) rather than building new cross-service template
  sharing infra just for this. CSS (`.site-footer`/`.footer-links`/
  `.footer-subscribe-prompt`) added to both stylesheets identically.

  Contact links to `mailto:ryan@redtaperecordings.com` rather than a
  new contact form or the existing per-meeting "Report a problem" flow
  (which needs a specific meeting URL to POST against, so isn't a good
  fit for a global footer link) — reuses the real forwarding mailbox
  set up earlier the same day (see "Email deliverability" above) rather
  than building new infrastructure.

  Coverage links to a new placeholder page (`GET /coverage`,
  `app/templates/coverage.html`) rather than a dead link — the user
  asked for it in the footer despite the real Coverage page (a public
  sortable jurisdiction/platform table, see "Archive roadmap") not
  being built yet. Built on the **resolver**, not the Archive: the real
  future version will read from `/admin/stats`'s underlying data, which
  lives in `app/db` on the resolver, not `archive/db` — confirmed by
  checking where `/admin/stats` itself is actually defined before
  picking a home for the stub, rather than assuming Archive because
  that's where the sitemap/feed live. `noindex`'d via `head_extra`
  (`<meta name="robots" content="noindex">`) since thin placeholder
  content isn't worth indexing until the real page replaces it.

  5 new tests (`tests/test_footer_and_coverage.py`): the coverage page
  renders and is noindexed, both services' footers carry all four
  links, and `/subscribe` still hides the redundant prompt while
  keeping the footer links. Full suite: 341 passed (336 + 5 new).

  Live-verified in the browser on both services through the resolver's
  proxy (matching production's reverse-proxy shape): screenshotted the
  homepage footer, clicked through to the real Coverage stub and
  confirmed its own noindex tag via `javascript_tool`, confirmed a real
  Archive `/m/{slug}` page (proxied) renders the same footer, and
  confirmed `/subscribe` correctly drops the redundant prompt while
  keeping all four links. One real tooling mixup caught immediately, no
  lasting effect: a first screenshot attempt landed on a stray
  `file://` tab the edit-preview hook had auto-opened for one of the
  edited templates, not the actual local dev server — caught from the
  tab context (`file://.../base.html`, raw unrendered Jinja syntax
  visible) and corrected by explicitly re-selecting the real
  `localhost:8010` tab before continuing.

## Email deliverability

- **[Done 2026-08-10, verified live against the real Resend API] Built a
  real one-click unsubscribe mechanism across every email
  `archive/utils/email.py` sends, and started the `noreply@` →
  `ryan@` sender-address migration.** Prompted directly by the user: "can
  we add an unsub link to the footer of all our resend emails?" plus,
  separately, a link to Resend's own deliverability docs flagging
  `noreply@` addresses as a real sender-reputation risk.

  `archive/utils/email.py` gained `_unsubscribe_footer_html(to)`, which
  builds a real link to a new `GET /unsubscribe` route — injected
  centrally inside `_send()` (`html = html + _unsubscribe_footer_html(to)`)
  so all four existing `send_*()` functions get it automatically, rather
  than each one needing to remember to add it. Returns `""` (no footer)
  when `PUBLIC_BASE_URL` isn't set, since local dev has no real public
  URL to build a working link from.

  The actual unsubscribe route lives on the **resolver**
  (`app/main.py`), not the Archive — matching `/confirm-transcription`'s
  existing precedent, since the resolver owns the public domain a plain
  email-link click needs to work from, and already has its own Resend
  credentials (`/api/newsletter/signup`). Refactored that route's inline
  POST logic into a shared `_resend_audience_upsert(email, *,
  unsubscribed)` helper, reused by the new `GET /unsubscribe` route (new
  template `app/templates/unsubscribed.html`). No login or confirmation
  step, matching CAN-SPAM's one-click requirement.

  Initially added a mirror-image `unsubscribe_contact()` function
  directly to `archive/utils/email.py`, then recognized it would never
  actually be called (the real unsubscribe write happens via the
  resolver's own `_resend_audience_upsert()`, a separate service with
  its own credentials) — removed before it became dead code, and
  `_unsubscribe_footer_html()`'s docstring was corrected to describe
  where the real route actually lives.

  Testing needed new ground: `tests/aiohttp_mock.py`'s existing
  `mock_session()` only ever patched `.get()`, and a grep of the whole
  suite found no existing `.post()`-mocking pattern at all — every
  Resend call in this codebase (`_send()`, `_resend_audience_upsert()`,
  `upsert_audience_contact()`) is a POST. Rather than extend the shared
  mock helper, each new test file (`tests/test_email_unsubscribe.py`,
  `tests/test_unsubscribe_route.py`) monkeypatches a small local fake
  `aiohttp.ClientSession` directly, scoped to just that test — simpler
  than generalizing a shared helper for a pattern used in exactly two
  files so far. 12 new tests total: footer generation (empty when
  unconfigured, real link when configured, trailing-slash and
  special-character URL handling), `_send()`'s footer-injection
  guarantee (verified by capturing the real POST payload), the
  `/unsubscribe` route's full matrix (missing/malformed email, Resend
  success/failure/unconfigured), and `_resend_audience_upsert()`'s own
  HTTP-calling logic directly. Full suite: 319 passed (307 pre-existing
  + 12 new), no regressions.

  Live-verified end-to-end, not just via mocks: started the resolver's
  dev server locally against the real (gitignored) `.env`, which holds
  real production `RESEND_API_KEY`/`RESEND_AUDIENCE_ID` credentials (the
  user's own established local-dev-against-prod workflow, confirmed
  pre-existing, not something started this session) and hit
  `GET /unsubscribe?email=ryan@example.com` in the browser — confirmed
  the real page renders ("You're unsubscribed", the email echoed back)
  and that it made a real Resend API call (see BACKLOG.md's note on the
  resulting test contact left in the real audience — harmless, flagged
  for visibility). The footer-injection guarantee inside `_send()` was
  verified via a mocked-POST unit test rather than sending a real email
  to a real inbox, to avoid live-spamming anyone during verification.

  Changed local `.env`'s `RESEND_FROM_ADDRESS` from
  `Ryan <noreply@ally.redtaperecordings.com>` to
  `Ryan <ryan@ally.redtaperecordings.com>`. Confirmed via a real DNS
  lookup (`dig MX`/`dig NS`) that neither `redtaperecordings.com` nor
  `ally.redtaperecordings.com` has any MX record today, and that the
  domain's nameservers are Namecheap's default
  (`dns1/dns2.registrar-servers.com`) — matching the user's own
  "not sure, I think it's just resend" read when asked.

  Follow-up the same day: the user asked directly who a reply to a
  Resend email would reach, and asked for it to forward to
  `ryan@how-to-adu.com`. `ally.redtaperecordings.com` itself turned out
  to have no MX of its own — the only MX in that zone was on
  `send.ally.redtaperecordings.com` (`feedback-smtp.us-east-1.amazonses.com`),
  Resend's own SES bounce-handling record, unrelated to receiving real
  mail. That record is what made Namecheap's simplified "Redirect Email"
  widget report "Your domain is using other email service" when the
  user first tried it directly on `ally` — a false positive from a
  record one host down, not a real conflict, but confirmed live that
  Namecheap's wizard doesn't distinguish. Switching Namecheap's
  domain-wide "Mail Settings" dropdown to "Email Forwarding" was also
  ruled out live: the preview after switching showed only a bare SPF TXT
  record and no MX at all, meaning `send.ally`'s existing MX had already
  dropped out of view pre-save — too risky to save blind given it could
  have deleted Resend's real bounce-handling record for the whole zone,
  not just added forwarding.

  Landed on two changes instead, both confirmed working live, not just
  in theory:
  1. **Code**: `_send()` (`archive/utils/email.py`) now sends a
     `reply_to` field (confirmed via Resend's own API docs that this is
     a real supported field, string or array) read from a new
     `RESEND_REPLY_TO_ADDRESS` env var, independent of
     `RESEND_FROM_ADDRESS`. Lets the visible From stay on `ally` (the
     subdomain Resend has actually verified for sending — its DNS was
     never touched) while replies route to the root domain instead. 2
     new tests (`tests/test_email_unsubscribe.py`) confirm `reply_to` is
     included when configured and omitted when not. Added to both
     `.env.example` files and `render.yaml` (`sync: false`, matching
     `RESEND_FROM_ADDRESS`'s existing pattern) for both
     `rtr-deeplink-archive` and `rtr-transcription-worker`.
  2. **DNS**: rather than Namecheap's own forwarding wizard, set up free
     forwarding via **ImprovMX** instead — a decoupled service that only
     needs 2 MX records + 1 SPF TXT record added manually (while staying
     in Namecheap's "Custom MX" mode the whole time), so the existing
     `send.ally` MX record was never at risk. Records added at host `@`
     on `redtaperecordings.com`: `MX mx1.improvmx.com` (priority 10),
     `MX mx2.improvmx.com` (priority 20), `TXT "v=spf1
     include:spf.improvmx.com -all"`. Discovered mid-setup that
     Namecheap splits Advanced DNS into two separate sections — MX
     records go under "Mail Settings" (grayed out for other types while
     Custom MX is selected), while the TXT record needed the separate
     general-purpose "Host Records" section instead. `ryan@redtaperecordings.com`
     → `ryan@how-to-adu.com` set up as an alias in ImprovMX (plus a
     wildcard catch-all ImprovMX created by default). Verified twice,
     independently: once in ImprovMX's own dashboard (all three DNS
     checks green/"Active"), and again directly via `dig MX`/`dig TXT
     redtaperecordings.com` from this session, confirming the exact
     records live in real DNS, not just ImprovMX's cached view of them.

  **Closed out 2026-08-10, same day**: user set both env vars
  (`RESEND_FROM_ADDRESS=Ryan <ryan@ally.redtaperecordings.com>`,
  `RESEND_REPLY_TO_ADDRESS=ryan@redtaperecordings.com`) on all three
  Render services — `rtr-deeplink-archive` and `rtr-transcription-worker`
  as expected, plus `rtr-deeplink` (the resolver) too. The last one was a
  real surprise: `rtr-deeplink`'s code never reads
  `RESEND_FROM_ADDRESS` (confirmed via grep — it only calls Resend's
  audience-contacts endpoint, which needs no From address) and the var
  isn't declared in that service's `render.yaml` block either, so
  assumed it wasn't configured there — but the user had it set directly
  in Render's dashboard anyway (real drift between the manifest and
  actual dashboard state, from whenever they first set the resolver's
  Resend vars up). Updated there too for consistency, harmless either
  way since it's unused in that service's code. Saved without a redeploy
  (not urgent) — Render only applies env var changes on the next
  deploy/restart, so the old `noreply@` value is still what's actually
  in use by the Archive/worker processes until that happens next.

- **[Done 2026-08-12] `ryan@redtaperecordings.com` and
  `ally@redtaperecordings.com` now actually receive email, forwarded to
  `ryan@how-to-adu.com`.** Closes the gap flagged 2026-08-12: neither
  address had a real mailbox behind it, so `RESEND_REPLY_TO_ADDRESS`
  replies and the site footer's `mailto:` Contact link were going
  nowhere silently.

  Domain/DNS/mailbox-provider setup, done directly by the user (no DNS
  or mailbox-provider access from this session) — Namecheap's own free
  Email Forwarding UI wasn't usable ("Your domain is using other email
  service") because MX already pointed at ImprovMX
  (`mx1`/`mx2.improvmx.com`, plus the `spf.improvmx.com` SPF include —
  same ImprovMX setup as the `noreply@` → `ryan@` sender migration
  above), so forwarding aliases were added directly in the ImprovMX
  dashboard instead: `ryan` and `ally` (plus a catch-all `*`), all →
  `ryan@how-to-adu.com`.

  First test looked like a failure — ImprovMX's Usage Dashboard showed
  2 "Received," but nothing arrived at `ryan@how-to-adu.com`. Root
  cause: the test was sent *from* `ryan@how-to-adu.com` to an alias
  that forwards back to the same address — Gmail's loop detection saw
  a duplicate Message-ID from itself, and ImprovMX's re-signing
  workaround for that case breaks DMARC alignment, landing the message
  in spam (ImprovMX proactively emailed an explanation of exactly this,
  confirmed legitimate despite Gmail's "might be dangerous" banner —
  self-forward-loop notification, not phishing). Not a forwarding bug —
  specific to testing from the same account you're forwarding to. A
  real test from a separate, unrelated address delivered cleanly to
  `ryan@how-to-adu.com`, confirming forwarding actually works for real
  incoming mail.

## Search

- **[Done 2026-08-10] Fixed quoted phrase search on `/meetings` —
  reported directly by the user, confirmed against the real code before
  fixing, not guessed.** `archive/utils/search.py`'s `matches()` used to
  split a query on whitespace with no quote-awareness at all, so
  `"data center"` became two literal terms, `"data` and `center"`,
  quote characters glued on — since real transcript/agenda text never
  has a literal `"` stuck against a word, this guaranteed zero results,
  not a graceful "quotes ignored" fallback. Confirmed directly before
  building anything: `matches('"data center"', ...)` on a corpus
  containing "a new data center project" returned `False`, while
  `matches('data center', ...)` (no quotes) on the same corpus returned
  `True`.

  Also clarified something the user's own description was close on but
  not quite exact about: unquoted multi-word search
  (`all(term in corpus for term in terms)`) was, and still is, **AND**,
  not OR — a corpus missing either word entirely returns `False`. It
  just never required the words to be *adjacent*, which is what likely
  read as looser/OR-like (a match where "data" is in the title and
  "center" is three paragraphs into the transcript was, and remains, a
  hit for the unquoted case).

  New `_parse_query()` splits a query into `(phrases, words)` —
  `"quoted phrases"` (`_PHRASE_RE = re.compile(r'"([^"]*)"')`) are
  extracted first and required as one continuous adjacent substring
  match (reusing the same plain-substring mechanism single-word exact
  matching already used, just applied to the whole phrase); the
  remainder is split into words as before, each still required
  independently (AND). Phrases are **always** matched as an exact
  literal substring, even when `fuzzy=True` — phrase-level fuzzy
  matching (an adjacent run of near-matching words) is a meaningfully
  harder problem than what was asked for, and quoting is itself a
  reasonable signal the caller wants a literal match. `find_snippet()`
  checks phrases before unquoted words within each candidate text, so a
  phrase match wins the highlighted snippet when both would otherwise
  match. An unclosed quote (e.g. `"data center` with no closing mark)
  isn't a syntax error — `_PHRASE_RE` simply doesn't match it, so the
  stray `"` character rides along as part of whatever word it's glued
  to, same "that one term won't match" behavior as before this fix,
  just scoped to the single malformed term instead of guaranteeing the
  whole query returns nothing.

  Deliberately did **not** build a full advanced-search query language
  (explicit AND/OR/NEAR operators) — also asked about directly by the
  user, and explicitly declined for now: `search.py`'s own docstring
  already flags this whole approach as deliberately naive, "fine at
  today's scale... not meant to scale past a few hundred [meetings],"
  and a real boolean-operator grammar is more machinery than that scale
  justifies. The phrase-quote fix alone covers the concrete case that
  was actually hit.

  Added a small `.subtitle` hint line under the search box on
  `/meetings` (`archive/templates/meeting_list.html`) — `Tip: put a
  phrase in "quotes" to match it exactly, e.g. "data center".` — since
  the feature would otherwise be entirely undiscoverable; no existing
  UI anywhere mentioned quote support.

  14 new tests (`tests/test_archive_search.py`, 21 total in that file):
  adjacent-vs-non-adjacent phrase matching, unquoted behavior unchanged,
  a phrase combined with an unquoted word, a missing phrase failing even
  when its individual words are both present, case-insensitivity, the
  unclosed-quote fallback (doesn't crash), an empty `""` phrase being
  ignored rather than becoming a stray literal token, snippet
  highlighting the full phrase, phrase-over-word snippet precedence, and
  phrase matching staying exact even with `fuzzy=True`. Full suite: 336
  passed (326 + 14 new, plus 4 pre-existing search tests already
  covered exact/fuzzy word behavior unaffected by this change). One
  real near-miss caught while writing tests, not left in: the regex
  originally required `[^"]+` (one or more chars), so a literal `""`
  (empty quotes) didn't match the phrase pattern at all and fell through
  as a stray 2-character literal token instead of being cleanly ignored
  — switched to `[^"]*` (zero or more) so it's captured and filtered by
  the existing `if p.strip()` check like any other whitespace-only
  phrase would be.

  Live-verified end-to-end in the browser, not just via unit tests:
  ingested a real test meeting locally with two segments — one with
  "data center" adjacent, one with "data" and "center" both present but
  *not* adjacent ("...the data collected showed the community center
  needs repairs") — through the actual `/internal/ingest` endpoint (not
  a direct DB write), then drove the real `/meetings` search UI through
  the resolver's proxy (matching production's reverse-proxy shape).
  Confirmed `q="data center"` finds the meeting and highlights exactly
  `<mark class="search-match">data center</mark>` (the phrase, not just
  one word), and that `q="community data"` (present but non-adjacent in
  the seeded text) correctly returns zero results — the phrase
  requirement is real, not just passing in isolated unit tests.

  Caught and corrected a real mistake mid-verification, no lasting
  harm: initially started the local Archive dev server without
  overriding `DATABASE_URL`, which fell back to the real production
  Postgres URL from `.env` — but that's the *resolver's* production
  database (confirmed earlier the same day during the `/meetings`
  outage investigation above), not Archive's. `init_models()` runs
  `create_all()` unconditionally on startup, so this could in principle
  have tried creating Archive's tables in the wrong production
  database — confirmed via a direct `information_schema` query,
  immediately after noticing the mistake, that the table list was
  unchanged (still just `alembic_version`/`meeting_resolutions`/
  `problem_reports`, no `meeting_pages` or anything else new). No
  writes occurred; the only request made before catching this was a
  read-only `/api/health` check. Restarted with an explicit absolute
  `DATABASE_URL=sqlite+aiosqlite:///<repo-root>/archive_dev.db` before
  doing anything further.

- **[Done 2026-08-11] Added Google-style `-exclude`/`-"phrase"` search
  operators plus no-op `+`/`&`/`AND`, closing most of the "no boolean
  operators" gap `BACKLOG.md` had flagged** (commit `0cf48bf`; `OR`
  remains genuinely open — see BACKLOG.md, it needs real expression-tree
  parsing this flat list-based `_parse_query()` can't represent).
  `_parse_query()` now also collects `excluded_phrases`/`excluded_words`
  from any `-`-prefixed phrase/word; `matches()` checks those first and
  fails immediately on a hit, before the positive AND checks run, so an
  exclusion always wins over a coincidental positive match elsewhere in
  the same corpus. Exclusions are always checked as an exact substring,
  even in fuzzy mode — a fuzzy exclusion risks dropping a meeting that
  only *resembles* the excluded term, a worse failure mode than an
  exclusion occasionally missing a typo'd instance. `+term`, a bare `&`,
  and the bare word `AND` are stripped as no-ops (previously would have
  been searched for as literal, always-failing tokens). The `?` search-
  tips popover on `/meetings` (`meeting_list.html`) replaced the old
  static one-line hint, since the growing operator list no longer fit
  inline. 5 new tests in `tests/test_archive_search.py` cover word/phrase
  exclusion, exclusion staying exact under fuzzy mode, and both no-op
  forms. *(Note: this entry was written up after the fact, 2026-08-11,
  during a backlog-cleanup pass — the actual build predates it; see
  `CLAUDE.md`'s note on more than one session sharing this repo.)*

## Incidents

- **[Resolved 2026-08-11] Clerk production cutover surfaced three real
  bugs, none caught by the extensive test suite or staging verification
  — all found live, in production, while switching from Clerk's
  development instance to a real production instance.** Staging had
  used a Clerk dev instance the whole time; moving to production meant a
  new `pk_live_.../sk_live_...` key pair, real DNS verification
  (5 CNAME records added in Namecheap), a fresh Google OAuth SSO
  connection, and a new production webhook — each of these surfaced a
  bug the dev-instance path had never exercised.

  **Bug 1 — `clerk_frontend_api_url()` broke site-wide immediately after
  the key swap (PR #6).** The function decoded the publishable key's
  base64 segment without padding it first. Real Clerk keys omit
  base64's trailing `=` padding, so `base64.b64decode()` only worked
  before by *coincidence*: the dev-instance key's encoded segment
  happened to already be a multiple of 4 characters (48 chars, no
  padding needed), while the new production key's segment (38 chars)
  wasn't. The exception got swallowed by the function's own broad
  `except Exception: return None`, producing an empty Frontend API URL
  that made `shared_static/clerk_nav.js`'s own configured-vs-not guard
  disable Clerk entirely, client-side, for every visitor — caught within
  minutes by comparing what the live site was actually serving
  (`curl`ing for `data-clerk-publishable-key`/`data-clerk-fapi-url`)
  against the expected new key, not by any error surfacing on its own.
  Fixed by re-padding the base64 segment before decoding, in both
  `app/utils/clerk_auth.py` and `archive/utils/clerk_auth.py`
  (deliberately duplicated, see that module's own docstring) — with a
  regression test using the *exact* real production key value, unpadded,
  rather than a helper-encoded (and therefore always-correctly-padded)
  fake, which is exactly what let the original bug ship untested.

  **Bug 2 — nav divider stayed visible when signed in (PR #7), caught by
  a real user click-through, not automated tests.** The "Get Updates"
  divider `<li>` carries Bootstrap's `d-none d-lg-block` utility classes
  (`display: block !important` at the `lg` breakpoint), which beat the
  plain `hidden` attribute `clerk_nav.js` was setting to hide it (not
  `!important`) — so the divider never actually disappeared at desktop
  widths even though the "Get Updates" link itself correctly did,
  leaving two adjacent dividers with nothing between them. Fixed by
  setting the inline `display` style directly (also `!important`)
  instead of relying on the `hidden` attribute for that one element.

  **Bug 3 — the real blocker: `/account/saved` and the Save
  buttons silently treated a genuinely signed-in visitor as signed out
  (no PR of its own — an env var fix, but got a diagnostics PR, #8).**
  Confusing to debug because the symptom was asymmetric: the nav avatar
  rendered correctly (proof of a valid session) since that's driven
  entirely client-side by `window.Clerk.user`, while `active_account` —
  computed server-side on Archive via `get_clerk_user_id()`, gating the
  Save buttons and `/account/saved`'s real content — kept coming back
  `None`. Confirmed via Clerk's own dashboard Logs (not guessed) that a
  real `session.created` event existed for the production instance
  (`is_development_instance: false`), ruling out anything client-side or
  Clerk-side. `get_clerk_user_id()` was deliberately silent on every
  failure path (so a plain anonymous visitor — the overwhelming common
  case — generates zero log noise), which meant there was *no visible
  signal at all* for a real, failed verification attempt either. Added
  diagnostic logging (PR #8) gated specifically on "a `__session` cookie
  was present but verification still failed" — anonymous traffic stays
  exactly as silent as before, but a real failure now surfaces Clerk
  SDK's own `state.reason`/`state.message`. That immediately named the
  cause: `JWK_FAILED_TO_RESOLVE`, "Public Key is not in the proper
  format." `CLERK_JWT_KEY` (an optional local-verification optimization
  holding a PEM public key) had gotten mangled pasting a multi-line
  value into Render's env var UI — a very easy way for a PEM key
  specifically to break (dropped newlines, a missing header/footer
  line). Fix needed no code change at all: `CLERK_JWT_KEY` was simply
  deleted from both services' env vars, falling back to the SDK's
  normal networked JWKS fetch (which self-caches after the first
  request, so this costs approximately nothing) — confirmed working
  immediately after that redeploy.

  **Takeaway for next time a Clerk instance switch happens** (e.g. if
  this app ever needs a second production-like instance): re-verify the
  publishable-key decode against the *specific* new key value (not just
  "some dev-shaped key"), and treat `CLERK_JWT_KEY` as an optional,
  easy-to-mangle optimization worth leaving unset unless there's a
  measured reason to need networkless verification from the very first
  request.

- **[Resolved 2026-08-10] Live production outage: `/meetings` 500ing on
  both services, caused by the pending `video_warnings`/`agenda_link`
  migration (see "Bugs" below) never having been applied — no longer
  hypothetical once a fresh Archive deploy actually ran the code
  expecting those columns.** Reported directly by the user ("our
  /meetings page is currently not loading"). Confirmed root cause before
  touching anything: `curl`ing the Archive service directly (not through
  the resolver's proxy) also 500'd while `/api/health` stayed fine,
  isolating it to `MeetingPage` queries specifically;
  `archive/db/models.py` confirmed to declare `video_warnings`/
  `agenda_link` as real ORM-mapped columns (added in `fb9ae9e`, before
  this session's current thread) — any query against that model,
  including `list_pages()` (which backs `/meetings`), was always going
  to try selecting columns that didn't exist yet in the real production
  table.

  Real mistake caught mid-fix, no actual harm done: initially believed
  local `.env`'s `DATABASE_URL` could be used to run the migration
  directly against Archive's real production database (having real
  production credentials sitting in a local, gitignored `.env` for
  exactly this kind of local-dev-against-prod work is this repo's
  established pattern) — but a direct query confirmed that database only
  has `alembic_version`/`meeting_resolutions`/`problem_reports` (the
  *resolver's* own `app/db` tables), no `meeting_pages` at all. The
  resolver and Archive use two separate real production Postgres
  instances, each with its own `DATABASE_URL` set independently in
  Render's dashboard (`sync: false` in `render.yaml` for both) — local
  `.env` only ever had the resolver's. Caught before any write was
  attempted (only read-only `alembic current` and an
  `information_schema` query were run against the wrong database) — an
  initial hypothesis about the two services sharing one physical
  database and clobbering each other's `alembic_version` tracking was
  raised, then retracted once this was confirmed: they're genuinely
  separate databases, so that specific risk doesn't actually exist.

  Real fix: user ran the exact commands already drafted in BACKLOG.md
  from the `rtr-deeplink-archive` service's own Render Shell (real
  prod credentials, no separate URL needed) — `alembic current`
  confirmed `8e7cf3b20f86` first, `alembic upgrade head` ran the real
  `ALTER TABLE meeting_pages ADD COLUMN` DDL
  (`8e7cf3b20f86 -> 76a4a2820a2b`), `alembic current` confirmed
  `76a4a2820a2b (head)`. Verified independently, not just trusting the
  Shell output: `curl`ed both `https://rtr-deeplink-archive.onrender.com/
  meetings` and `https://redtaperecordings.com/meetings` directly,
  confirmed 200 on both.

- **[Resolved 2026-08-10] Root-caused a real, recurring problem the user
  had separately noticed: Render service plans kept silently reverting
  to `free` after being manually upgraded in Render's dashboard.**
  `render.yaml` is a Render Blueprint, and Render reconciles every
  Blueprint-managed service (including its `plan:`) to match this file
  on every Blueprint sync — which fires automatically on every push to
  `main` by default. `render.yaml` had `plan: free` hardcoded for both
  `rtr-deeplink` and `rtr-deeplink-archive`
  (`rtr-transcription-worker`'s `plan: standard` was already correct and
  unaffected), so any manual dashboard upgrade survived only until the
  next push — and this session alone had already pushed 5 commits by the
  time this came up, meaning it had almost certainly been reverting
  repeatedly and recently, not as a one-off. Not a Render bug — the file
  genuinely was out of date with a decision that had only ever been made
  in Render's dashboard, never reflected back into the repo.

  Fixed by declaring the real intended plan (`starter`) for both
  services directly in `render.yaml`, and added a top-of-file comment
  explaining the Blueprint-sync mechanism and instructing that every
  `plan:` (and, implicitly, anything else Blueprint-managed) needs to
  stay in sync with decisions made in chat or the dashboard — a
  dashboard-only change will keep getting silently undone otherwise.
  User independently re-upgraded `rtr-deeplink-archive` in the dashboard
  first in order to get Shell access to run the migration above (real
  evidence that Render's Shell feature itself may require a paid plan,
  not available on `free`) — the `render.yaml` fix here is what stops
  that specific service from reverting again on the next push.

## Bugs

- **[Done 2026-08-17] Confirmed all 4 of the user's originally-reported
  2026-08-11 lifecycle-email bugs are fixed in current code, closing the
  stale live entry BACKLOG.md still carried for this batch.** Read the
  actual current code rather than trusting the backlog text, per this
  repo's own "don't just trust the backlog text" convention: (a)
  transcript excerpt always empty in completion emails — `archive/db/
  crud.py`'s `_job_dict()` includes `"transcript_version_id":
  job.transcript_version_id`; (b) email header background/label colors
  reversed — `archive/utils/email.py`'s `_branded_wrapper()` has the outer
  `<td>` in `#212529` (dark, matching the site's `bg-dark` navbar) with
  the inner `<span>` carrying its own `#b71c1c` red background, the
  correct on-site `.dymo-label` contrast (red label *inside* a dark bar,
  not the reverse); (c) hardcoded ALL CAPS instead of Title Case — the
  same function's `wordmark = "Red Tape Recordings"` is real Title Case,
  not `RED TAPE RECORDINGS`; (d) "Red Tape Recordings" text not linking
  back to the site — both `_branded_wrapper()`'s header wordmark and
  `_signoff_html()`'s sign-off line wrap the text in a real `<a
  href="{base_url}">` when `base_url` is set. See this file's two
  matching 2026-08-11 entries below for the original root-cause/fix
  detail on each. BACKLOG.md's live stub for this batch (which already
  knew 3 of these were fixed and only flagged the unrelated "People are
  talking about…" saved-search-alert item as a separate, still-open
  feature — see the "Email alerts for saved searches" entry, corrected
  the same day this entry was written) is removed now that nothing about
  this batch is still open.
- **[Done 2026-08-16] Hallucinated Whisper transcript (Telugu/Sinhala/
  symbol spam, nonsense English, `transcript_language` pushed as `"te"`)
  root-caused to stereo phase cancellation in `extract_chunk_audio()`'s
  mono downmix, and fixed with both a real extraction-side fix and a new
  Whisper-specific garbled-output check — found live via
  `scripts/transcribe_backlog_locally.py --url` against a real backlog
  meeting, same session as the seam-duplication bug below.** Port
  Coquitlam, BC's `portcoquitlam-2025-02-18-committee-of-council-meeting`
  (a 1572-second, 2-chunk eScribe meeting) came back as complete
  gibberish: a chaotic mix of Telugu, Sinhala, random Unicode symbol
  spam, nonsense English (`"Did you ever see your mom will never wake up
  at the bus stop?"`, `"Lord of Evil, saint of heaven, / Lord God of
  peace!"`), and long runs of a single repeated character. A real timing
  anomaly correlated: 2624.2s to transcribe 1572s of audio — slower than
  real-time, versus ~7:1 faster-than-real-time for two other real
  meetings transcribed the same session with the same model/settings.

  **Root cause, confirmed empirically, not assumed.** Re-resolved the
  meeting fresh and fetched its real HLS playlist/audio directly
  (`https://cdn1.isilive.ca/.../Committee%20Encoder%20839_Committee%20of%20Council%20Meeting_2025-02-18-03-59.mp4/playlist.m3u8`).
  Sampling fresh, isolated 60-second slices across the *entire* meeting
  (not just the reported boundary) with `faster-whisper "tiny"` showed
  garbage/hallucination at essentially every point, not just one chunk
  seam — ruling out a localized bad-segment theory. `ffmpeg volumedetect`
  on the actual extracted mono audio showed `mean_volume: -44.2dB` (chunk
  1) / `-45.5dB` (chunk 2) — a real ~24dB gap versus a known-good real
  meeting (Boulder County, ~-20.5dB, from the seam-duplication
  investigation below). `ffprobe` confirmed the source is genuine stereo
  AAC (`channels=2`). Extracting the left channel alone and the right
  channel alone (via ffmpeg's `pan=mono|c0=c0` / `c0=c1`) each measured
  `-15.7dB` — a real, present, much louder signal than the mono mix —
  and extracting their *difference* (`pan=mono|c0=c0-c1`) measured
  `-10.4dB`, louder still: the exact numeric signature of two near-
  perfectly phase-inverted channels (summing them cancels; subtracting
  reinforces). Transcribing all three confirmed it decisively: the
  standard mono downmix produced nonsense (`"Public comment, public
  comment, public comment..."`, `"the door will be open to the door
  without any further delay in the day"`), while the left channel, right
  channel, and their difference all independently produced the *same*
  clean, coherent real transcript of a real council discussion
  ("Councillor Garling. Sorry, I'm confused now. So there is an access
  point off of Ogovi..."). `faster-whisper "tiny"` on the real (pre-fix)
  chunk 2 audio also directly reproduced a hallucination-loop symptom:
  one real sentence repeated verbatim across 44 of 45 total segments.

  **Fix, two parts, not just detection.** (1)
  `app/platforms/media_probe.py`'s `extract_chunk_audio()` now checks its
  own already-extracted audio's mean volume (cheap — no network, just
  decoding the small file already on disk) and, when it's below
  `-38dB` (set with real margin between the ~-20dB good and ~-45dB
  confirmed-broken cases), automatically retries with the left channel
  alone (`pan=mono|c0=c0`) instead of the averaged downmix, using it only
  if it's meaningfully louder (confirming real cancellation, not a
  genuinely quiet source) — this actually *fixes* the extraction rather
  than only flagging bad output downstream, so a meeting like this one
  now produces a real, usable transcript instead of a correctly-rejected
  blank one. (2) Defense-in-depth for whatever (1) doesn't catch (a
  genuinely corrupted stream, wrong media entirely, or a hallucination
  cause unrelated to phase cancellation): `worker/segment_utils.py`
  gained `detect_hallucination_warnings()` — the same role
  `app/utils/vtt_parser.py`'s `is_likely_garbled()` already plays for
  scraped captions, which this Whisper-specific ingest path had no
  equivalent of at all until now. Three independent signals, each tuned
  against the real confirmed symptoms above: a segment-level repetition-
  run ratio (≥0.5, well below the real 0.89 confirmed case), a run of
  ≥10 identical characters in a row (essentially never real speech), and
  a non-Latin-alphabetic-character ratio (≥15%, deliberately excluding
  accented Latin letters so a legitimate French/Spanish transcript —
  real content already live on this Archive, e.g. an LA USD board
  meeting — isn't penalized). Wired into `archive/db/crud.py`'s
  `report_chunk_result()` finalize step (covers both a real
  user-submitted transcription and the worker's own idle-time
  auto-generated jobs, the one place both actually finish) via a
  deliberate duplicate in `archive/utils/transcription_quality.py` — same
  cross-service-duplication convention as `archive/utils/language.py`,
  since the Archive shouldn't gain a dependency on `worker/`'s heavier
  codebase for a few small pure functions — and directly in
  `scripts/transcribe_backlog_locally.py`'s `transcribe_meeting()`, which
  never touches `transcription_jobs` at all. The existing
  `_GARBLED_MARKER`-based "does this page have a good transcript" checks
  (re-transcription eligibility, the `/coverage` and `/meetings` "✓
  Transcript" badges — four separate call sites in `archive/db/crud.py`)
  now also honor the new hallucination marker via a shared
  `_has_real_warning_free_transcript()` helper, replacing four separate
  inline `_GARBLED_MARKER`-only checks — per this file's own note on
  `app/db/outcomes.py`, a new quality-warning message needs exactly this
  kind of update or it silently falls through to a more generic bucket.

  **Verified against real data, not just that the code runs.** Re-ran
  `scripts/transcribe_backlog_locally.py --dry-run --url <the same Port
  Coquitlam URL>` (no live page modified) with both fixes in place. The
  extraction log shows the automatic left-channel fallback firing on
  both chunks (`"Chunk audio at 0s looks suspiciously quiet after mono
  downmix (-44.2dB)..."` / same at `900s`, `-45.5dB`). The resulting
  transcript is 306 segments of completely coherent real English content
  from start to finish (a real development-variance-permit discussion,
  ending with the meeting's real closing procedure), `language=en`
  correctly detected (not `"te"`), zero hallucination warnings, and a
  clean flow through the exact 900s chunk boundary that previously
  produced garbage. Total transcription time dropped from the original
  run's reported 2624s (slower than real-time) to 354s (4.4x
  faster-than-real-time) — independent confirmation that the
  hallucination-induced slow decoding is gone too, not just that the
  output looks better. `tests/test_worker_segment_utils.py` and
  `tests/test_transcription_jobs.py` carry this as permanent regression
  coverage: the real reproduced repetition-loop segments, the real
  post-fix clean transcript (a false-positive check), the real quoted-
  verbatim nonsense-English lines from the original report (documented
  as a real, honest limitation this heuristic doesn't try to catch —
  semantic nonsense needs a language-model judge, not a cheap structural
  check), and a DB-integration test confirming the archive-side
  duplicate is actually wired into `report_chunk_result()`'s finalize
  path, not just present in the file — 835 total tests passing.

  **Not done here, deliberately**: the already-live Port Coquitlam page
  itself was not re-transcribed or otherwise modified as part of this
  work — same reasoning as the seam-duplication entry below, that's the
  user's own call to make.

- **[Done 2026-08-16] Multi-chunk transcription duplicated real
  sentences at every ~900s chunk boundary on an HLS source — found live
  by the user on a real production page (Boulder County, CO,
  `bouldercounty-2026-02-05-historic-preservation-advisory-board`), root-
  caused by directly diffing real audio, and fixed in the shared code
  path both `worker/main.py` (the live cloud worker) and
  `scripts/transcribe_backlog_locally.py` use.** The user spotted a real
  duplicate right at the chunk 1/chunk 2 seam (900s = 15:00) on the live
  page: chunk 1 cut off mid-sentence ("...there's an exhibit at the.")
  and chunk 2 restated the same sentence from the top before continuing
  ("This whole question about truck caro...there's an exhibit at the
  Colorado Railroad Museum..."). Confirmed as a systemic pattern, not a
  one-off, by the user independently ("the repetition often happens at
  15:00 minute marker") and by a same-day single-chunk meeting (Welland,
  ON, 783s, never split) showing no such artifact.

  **Root cause, confirmed empirically, not assumed** (per this file's own
  "don't claim a data path works/fails without a positive example"
  convention): `worker/segment_utils.py`'s `chunk_start()`/
  `chunk_duration()` have zero designed overlap on paper (chunk N covers
  exactly `[N*900, (N+1)*900)`), so the real mechanism had to be in
  `app/platforms/media_probe.py`'s `extract_chunk_audio()`, which uses
  fast/input-side ffmpeg `-ss` seeking (before `-i`). Fetched Boulder
  County's real HLS playlist directly: segments are ~36s each, and the
  segment covering the true 900s mark actually starts at 887.8s — not a
  clean multiple of 36, so this doesn't self-correct across sources.
  Then extracted the *real* audio three ways from the real source
  (`https://cdn1.isilive.ca/.../GMT20260206-010224_Recording_gallery_1280x720.mp4/playlist.m3u8`)
  and transcribed each with `faster-whisper`: (1) production's actual
  fast `-ss 900` extraction, (2) an accurate/output-side `-ss 900`
  extraction for comparison, (3) an accurate continuous slice spanning
  850-950s as ground truth. Result: the accurate extraction at exactly
  900s correctly starts mid-sentence ("Colorado Railroad Museum, so down
  in Golden..."), while production's fast extraction at the same
  requested timestamp actually contains audio from ~883-887s onward —
  the *exact* sentence chunk 1 had just finished, re-transcribed in
  full. Confirmed via ffmpeg's own read statistics too: the accurate
  extraction had to read ~31.7MB (nearly the whole preceding stream) to
  reach 900s; the fast one read only ~1.6MB — proving the fast path
  really does jump straight to a nearby segment rather than decoding
  forward, and that jump can land before the requested second for an
  HLS source specifically (a direct-file source has no such segment
  granularity to snap to, so this doesn't affect a non-HLS platform).

  **Fix**: not a seek-accuracy fix — making `-ss` accurate for HLS means
  ffmpeg has to download and decode the *entire* preceding stream (the
  ~31MB vs. ~1.6MB measured above for just this one chunk), a cost that
  only grows with how far into a meeting a chunk starts, silently
  turning every later chunk of a long meeting into a near-full
  re-download. Instead, `worker/segment_utils.py` gained
  `count_seam_overlap_segments()`/`merge_chunk_segments()`: a word-level
  fuzzy match (via `difflib.SequenceMatcher` ratio over sliding
  suffix/prefix word windows, not whole-segment text equality — two
  independent Whisper decodes of the same audio don't reliably agree on
  segment boundaries or punctuation, confirmed by the real transcripts
  above) anchored at the actual seam, tuned against the real confirmed
  overlap (an 18-word run) and checked against a real false-positive
  case (a short, ordinary shared phrase like "thank you very much"
  scores well below the real duplicate's match ratio). Wired into both
  real call sites so neither was left half-fixed: `worker/main.py`'s
  `process_next_chunk()` (`claim_next_chunk()` now also returns the
  job's `partial_segments` so the worker can compare against what's
  already persisted; `report_chunk_result()` gained an opt-in
  `drop_previous_tail` param, default 0 so every pre-existing
  caller/test is unaffected) and `scripts/transcribe_backlog_locally.py`'s
  `transcribe_meeting()` (`merge_chunk_segments()` in place of a plain
  `.extend()`).

  **Verified against real data, not just that the code runs**: re-ran
  `scripts/transcribe_backlog_locally.py --dry-run --url
  <the same Boulder County URL>` (no live page modified) after the fix —
  log line reads `chunk 2/2 transcribed (86 segments, dropped 3
  seam-duplicate segment(s))`, and printing the actual resulting
  segments around the boundary confirms a clean, single flow directly
  from chunk 1's last real sentence ("...tie to what Larry brought up
  previously.") into chunk 2's fuller restatement ("This whole question
  about tricharro...Colorado Railroad Museum...") with no duplicate
  text. `tests/test_worker_segment_utils.py` carries this as a
  permanent regression test using the verbatim real production duplicate
  text plus real `faster-whisper` output captured during this
  investigation (commented as real, not synthetic, per this file's own
  test-honesty convention) — 827 total tests passing.

  **Audit of already-shipped exposure**: added `GET
  /internal/transcription/completed-multichunk` (token-gated, read-only,
  same reasoning as `/internal/schema-info`) specifically to answer this
  without needing direct production `DATABASE_URL` access. Real result,
  queried right after this fix deployed: **118 completed
  `TranscriptionJob` rows have `total_chunks > 1`** (i.e. went through
  the buggy chunk-boundary path at least once), spanning `job_id` 1
  through 192, `completed_at` 2026-08-08 through 2026-08-16 — every one
  of them a real candidate for this exact duplication having shipped to
  a live public page before this fix existed. This count covers only
  jobs the *cloud worker's* queue processed (real user-requested
  transcriptions plus its own idle-time auto-generation, both of which
  go through `TranscriptionJob`/`claim_next_chunk()`); it does **not**
  cover `scripts/transcribe_backlog_locally.py`'s own local-Mac backlog
  runs (Boulder County itself included), since that script deliberately
  never touches the `transcription_jobs` table at all (see its own
  module docstring) — those are a real, separate, currently-uncounted
  population also affected by the same bug, sized differently if ever
  needed (e.g. via `TranscriptVersion` rows with `source="transcribed"`
  not linked to a `total_chunks > 1` job). Deliberately did not
  re-transcribe or modify any of the 118 live pages as part of this work
  — that decision belongs to the user, and the full list (job id, page
  slug, chunk count, duration, completion date) was handed over
  separately for exactly that call.

- **[Done 2026-08-14] Correction to WO-3 of `AUDIT_EXECUTION_BRIEF.md`
  ("Stop shipping machine-local `.claude/` config") — `.claude/` was
  never actually tracked in this repo.** The brief's premise, echoed from
  `AUDIT_2026-08-14.md` finding #12, was that `.claude/settings.local.json`
  (pre-approving `Bash(git push *)`) and `.claude/launch.json`
  (hardcoding `/Users/mroconnell/...`) were committed and shipping to
  every clone. Verified thoroughly before acting on it: `git log --all
  --oneline -- .claude/` (every branch, local and remote) returns
  nothing; `git ls-tree -r origin/main` and every `origin/*` branch's
  tree has no `.claude/` entries; `.gitignore`'s own history
  (`git log -p -- .gitignore`) never mentions it either. `settings.local.json`
  specifically is additionally covered by this machine's own personal
  global gitignore (`~/.config/git/ignore`, `**/.claude/settings.local.json`)
  — but that's local-machine config, irrelevant to whether the repo
  itself ever tracked it, and doesn't explain `launch.json` (not covered
  by that global rule, also never tracked). Genuinely unconfirmed: why
  the audit reported this as a live finding — plausibly a `find`/`ls`
  check that saw the files existing on disk without confirming via `git
  ls-files` whether they were actually committed. Added `.claude/` to
  `.gitignore` anyway (defensive, costs nothing, matches WO-3's
  acceptance criterion `git ls-files | grep '^\.claude/'` returns
  nothing — already true beforehand, stays true after). No `git rm
  --cached` needed since nothing was ever cached.

- **[Done 2026-08-14] `robots.txt`'s `Disallow: /meeting` was also
  blocking `/meetings` (the Archive's own browse/search hub) — found in
  the 2026-08-14 app-wide audit (`AUDIT_2026-08-14.md`, finding #1), not
  live-caught by a person.** `app/main.py`'s `/robots.txt` handler emitted
  a single bare `Disallow: /meeting`, meant only to keep the ephemeral
  `/meeting?url=…` resolver page out of the index once a `/m/{slug}`
  permanent version exists. robots.txt `Disallow` matching is
  prefix-based, not exact, so that one line also matched `/meetings` —
  which `archive/main.py`'s `_SITEMAP_STATIC_PATHS` simultaneously lists
  as indexable in `sitemap.xml`. Confirmed live before the fix: fetching
  `redtaperecordings.com/meetings` returned a robots-disallowed result
  while `/`, `/about`, and `/robots.txt` fetched fine — the site was
  telling crawlers to index a page it also told them not to crawl, working
  directly against the discoverability effort already underway.

  **Fix**: replaced the single directive with two anchored forms —
  `Disallow: /meeting$` (exact path only) and `Disallow: /meeting?` (its
  query-string variants) — both supported by Google and Bing. `/meetings`
  no longer matches either. New `tests/test_robots_txt.py` (3 tests, 686
  total passing): asserts the emitted body carries both anchored forms and
  not the old bare line, asserts `/meetings` isn't matched by any emitted
  `Disallow` line, and asserts the ephemeral resolver page (`/meeting` and
  `/meeting?url=…`) is still blocked. Deliberately not using
  `urllib.robotparser` for the assertions — confirmed by hand it doesn't
  implement `$` end-anchoring or treat `?` literally, so it gives wrong
  answers for exactly the cases this fix changes; the test implements the
  real (Google/Bing) semantics itself instead.

  **Still needed, not code**: re-submit the sitemap in Search Console
  after this deploys and confirm `/meetings` stops being reported as
  blocked — that's a Search Console action + a multi-day recrawl wait,
  not something this PR can verify.

- **[Done 2026-08-13] PrimeGov now backfills `title` from the page's
  own real inner `<title>` tag when YouTube's own extraction is
  empty — found live by the user on a real LA City Council meeting.**
  The user pointed out that
  [a real LA `Portal/Meeting` URL](https://lacity.primegov.com/Portal/Meeting?meetingTemplateId=157675)
  would come through with no title even though YouTube's own title
  ("Regular City Council") and the page's own `<title>` tag ("City
  Council Meeting - 8/12/2026 5:00:00 PM") were both real and available.
  Investigated rather than assumed: a local resolve (residential
  network, yt-dlp unblocked) actually already returned the right title
  today — the *real* gap only shows up when yt-dlp is blocked (Render's
  documented IP-block gap, `youtube.py`), confirmed by simulating that
  exact condition (`DownloadError`, same pattern `test_youtube.py`
  already uses) — `resolved.title` came back `None`, while jurisdiction/
  date still worked fine since those already had their own page-based
  fallbacks (built 2026-08-09/12) — title never did.

  **Real, confirmed shape, not assumed from one example**: every
  PrimeGov `Portal/Meeting` page carries *two* `<title>` tags — an
  outer, useless `<title>Meeting</title>`, followed by a real one
  further into the response. Confirmed live across all 3 independently-
  confirmed real PrimeGov customers this repo has ever checked (OKC:
  "City Council - 8/4/2026 1:30:00 PM"; Thousand Oaks: "Thousand Oaks
  City Council Regular Meeting (Closed Session) - 7/8/2026 12:00:00
  AM"; LA: "City Council Meeting - 8/12/2026 5:00:00 PM") — not an
  LA-specific quirk, a platform-wide pattern. New
  `_extract_title()` returns the first `<title>` tag whose text isn't
  the exact generic placeholder. Applied in `resolve()` only when
  `resolved.title` is still empty — a real YouTube title, when
  available, is never overridden.

  **Verified**: 4 new unit tests (629 total passing) — the extraction
  function against the real confirmed shape, the no-real-title case,
  and two `resolve()`-level tests (backfills when YouTube is blocked,
  never overrides a real YouTube title) using the same `DownloadError`
  simulation pattern already established in `test_youtube.py`. A real
  local resolve of all 3 customer URLs with yt-dlp genuinely blocked
  (simulated) confirmed every one now gets its real title instead of
  `None`.

- **[Done 2026-08-13] Legistar's `MeetingDetail.aspx` page now backfills
  `agenda_link` — a real, easy win identified 2026-08-12 but not built
  until now.** Re-confirmed live against the same real Mesa, AZ example
  (`mesa.legistar.com/MeetingDetail.aspx?ID=1428059`) that the exact page
  shape from the original report is still accurate: `<a
  id="ctl00_ContentPlaceHolder1_hypAgenda" href="View.ashx?M=A&...">`.
  New `_extract_agenda_link()` matches by ID *suffix* (`hypAgenda`), not
  the full `ctl00_ContentPlaceHolder1_` prefix — that prefix is an
  ASP.NET WebForms naming-container artifact that could in principle
  differ under a different master-page nesting on another customer's
  instance; a suffix match costs nothing and is strictly safer, even
  though only one customer's exact prefix has been confirmed so far.

  Wired into both of `LegistarAssetFinder`'s delegation paths
  (`resolve()`'s primary `a.videolink` path and `_try_fallback_video_link()`),
  applied as `resolved.agenda_link or page_info.get("agenda_link")` in
  both — a fallback for whenever the delegated platform (e.g. Granicus's
  own `AgendaViewer.php` link) didn't already find one, not an override.
  Deliberately *not* gated behind the existing `_looks_like_raw_filename()`
  title-quality check the way title/jurisdiction/date already are in the
  primary path — agenda_link is real, useful data independent of whether
  the delegated platform's own title happened to look bad.

  Left the "Meeting location" field (a real meeting-type sub-label on
  this same page, e.g. "Study Session") deliberately unbuilt — see the
  still-open `BACKLOG.md` entry for why: unconfirmed whether every
  Legistar customer uses that field the same way Mesa does, or puts a
  real physical address there instead.

  Verified: 2 new unit tests (agenda-link extraction against the real
  confirmed page shape, and a no-agenda-yet case) plus 3 existing tests
  updated for the extra dict key; full suite green (616 tests); a real
  local resolve against the live Mesa URL confirms `agenda_link` comes
  through correctly while title/date/jurisdiction — already fine from the
  delegated YouTube result in this case — pass through unmodified, same
  intended split-application behavior.

- **[Done 2026-08-13] "Save this search" is now a real Save/Unsave
  toggle with a visual confirmation cue, plus two stale backlog entries
  corrected after live investigation showed their underlying bugs no
  longer exist (one never did).**

  **Investigation first, before building anything**: the two
  `/meetings` Save-button bugs the user asked about turned out to already
  be resolved. (1) Live-checked as a genuinely signed-out visitor on both
  `/meetings` and a real `/m/*` page — neither Save button renders at
  all; `git log -S "if active_account"` confirmed the `{% if
  active_account %}` gating on both templates has been in place since the
  very first accounts-phase commits, not added later, so the original
  "renders for every visitor" premise was wrong from when it was written.
  (2) The stale-search-value bug (saving whatever was last *applied*
  instead of the just-typed, unsubmitted text) was already fixed
  2026-08-11 — `archive/static/meeting_list.js`'s `isStale()` disables
  Save the moment the box/filters diverge from what's actually applied,
  predating this backlog entry's own write-up. `BACKLOG.md` corrected to
  reflect both.

  **What was actually still open and got built**: the Save/Unsave toggle
  itself, per the user's own brainstormed design (turn "Save this search"
  into "Unsave search" immediately after a successful save, revert the
  moment the box/filters change again) plus a visual confirmation cue —
  user's explicit direction: reuse the exact "pop up and glow" tape-deck
  cue already built for `#transcribeToggle` (`.pointed-to`/
  `cassette-btn-pop` in `style.css`) rather than invent a new visual
  language, "to stick to across the site until we go for a full redesign
  one day."

  `archive/static/meeting_list.js`'s `wireSaveSearchButton()`: tracks the
  returned `saved_item_id` from a successful save, reuses the same
  `/api/account/unsave-search` endpoint `saved_items.js` already calls
  from `/account/saved` for the unsave click, and — a real correctness
  fix, not just cosmetic — resets back to "Save this search" the instant
  `isStale()` goes true again, since a stale "Unsave search" label would
  otherwise unsave the *old* search using an id that no longer
  corresponds to what's on screen. In-session only (doesn't check the
  server for a pre-existing matching saved search on page load) — matches
  the user's own stated scope of "immediately after a successful save,"
  not a fuller "is this exact search already saved" feature.

  **Verified via a standalone browser harness** (real DOM structure +
  real CSS + the real JS file, `fetch` mocked to avoid needing a live
  Clerk session) rather than skipped for lack of live auth: save → button
  flips to "Unsave search," correct `saved_item_id` threaded through;
  unsave → reverts cleanly; editing the search box after a save reverts
  the button to disabled "Save this search" *and* clears the stale
  "Saved ✓" status text (a small additional fix caught during this same
  verification pass — the status message used to linger next to the
  reverted button, reading as if it still applied). Full suite green (614
  tests, no Python touched by this change).

- **[Done 2026-08-13] `civicweb.py` no longer lets YouTube's `uploader`
  field leak through as jurisdiction when the page's own `<title>`
  extraction doesn't match.** Found while auditing every direct
  `YouTubeAssetFinder` delegator for the same bug class just fixed in
  `lims.py` and `generic_fallback.py` (see the entry directly below) —
  `civicweb.py`'s `if jurisdiction: resolved.jurisdiction = jurisdiction`
  had no `else` branch, so a non-matching `<title>` (unconfirmed live so
  far, but the exact same code shape LIMS and generic_fallback both had
  before their real confirmed failures) would silently leave whatever
  YouTube's uploader field set in place. Fixed by falling back to
  `jurisdiction_enrich.known_jurisdiction_display()` (not LIMS's own
  `f"{known.name}, {known.state}"` shortcut — that only works because
  LIMS's one confirmed domain is a *city*; CivicWeb's confirmed domain is
  Dallas *County*, and dropping the "County" distinction the same way
  would misleadingly read as a city named Dallas).
  `known_jurisdiction_display()` also correctly returns `None` when the
  domain isn't confirmed, clearing the bad uploader value entirely rather
  than leaving it in place. New test confirms the fallback produces
  "County of Dallas, TX," not "Dallas County TV" (the fixture's uploader
  value). Full suite green (614 tests). Audited every other direct
  YouTube delegator in the same pass — see `BACKLOG.md`'s updated entry
  for the one still-unconfirmed gap (Legistar's primary delegation path).

- **[Done 2026-08-13] `generic_fallback.py`'s YouTube-embed branch now
  backfills title/jurisdiction/date from the source page itself when
  YouTube's own metadata comes back empty — closes the CRRMA
  "Untitled meeting" gap, confirmed against 5 real board-meeting URLs.**

  **Root cause, two stacked issues**: (1) YouTube's yt-dlp call is
  blocked by anti-bot checks from Render's server IP (the existing,
  documented infrastructure gap, `youtube.py`), so
  `YouTubeAssetFinder.resolve_video_id()` degrades to a title-less,
  jurisdiction-less `ResolvedMeeting` in production; (2)
  `generic_fallback.py`'s YouTube-embed branch never attempted any
  fallback of its own when that happened — confirmed live 2026-08-13 that
  `redtaperecordings.com/m/meeting-732f78` still showed "Untitled
  meeting" with no jurisdiction.

  **What got built**: `GenericFallbackAssetFinder._backfill_metadata_from_page()`,
  called after both the YouTube-delegation branch and the final
  catch-all "nothing found" branch (both build a `ResolvedMeeting` that
  can end up with no title). Confirmed live via `curl` against all 5
  known real CRRMA board-meeting URLs (`crrma.org/information/meetings/
  board/{date}`, 2025-11-12 plus four more): every one carries the exact
  same `<title>Camino Real Regional Mobility Authority | El Paso,
  Texas</title>` shape (splittable on `|` into org name + jurisdiction)
  and an identical `<h1 id="notice-of-meeting">`/body-paragraph block
  naming the governing body more specifically ("CRRMA Board of
  Directors" — matches the user's own stated naming preference, "I'd
  expect it to have CRRMA in there somewhere"). Title prefers the
  notice-block phrase over the bare `<title>`-derived org name; date
  falls back to a `YYYY-MM-DD` segment already present in the source
  URL's own path. Jurisdiction is stored as raw text ("El Paso, Texas"),
  not pre-abbreviated — `normalize_state_suffix()` already runs on every
  ingest server-side, so abbreviating here too would be redundant, not
  incorrect. Deliberately scoped to this one confirmed page shape, not
  generalized to other generic-fallback sites without their own
  confirmed example, same convention as every other adapter in this
  repo.

  **A second, separate real bug found while live-verifying the fix**:
  `redtaperecordings.com/m/meeting-732f78` already had a *title* (from an
  earlier successful local yt-dlp resolve during this session's own
  production backfill run, which used a residential IP yt-dlp isn't
  blocked from) — but its jurisdiction was "Camino Real Regional
  Mobility Authority," a YouTube channel *uploader* name, not a real
  jurisdiction. Root cause: `YouTubeAssetFinder.resolve_video_id()`
  unconditionally sets `jurisdiction=info.get("uploader")` whenever
  yt-dlp succeeds (`youtube.py`) — the exact same class of bug already
  fixed for PrimeGov (which unconditionally overrides YouTube's uploader
  for this reason), just never addressed for `generic_fallback.py`'s
  YouTube branch. Fixed by making jurisdiction backfill unconditional
  (always prefers the page's own value when found, regardless of whether
  `resolved.jurisdiction` is already set) while keeping title backfill
  gated on emptiness only (a real YouTube-derived title is legitimate and
  shouldn't be overridden) — since this branch's only possible delegate
  is `YouTubeAssetFinder`, there's no other legitimate source
  `resolved.jurisdiction` could hold here.

  **Verified three ways**: 4 new unit tests (613 total passing) covering
  the DownloadError-blocked case, the uploader-override case, and two
  pure-function edge cases (bare title-tag fallback without a notice
  block, and a full no-op when the title isn't pipe-shaped at all); a
  real local resolve against the live `crrma.org` URL (residential
  network, yt-dlp succeeds) confirming `jurisdiction == "El Paso, Texas"`
  and the real YouTube title/date pass through unmodified.

  **Still open**: the "what to show when nothing at all can be found"
  UI/copy question — see the still-open `BACKLOG.md` entry.

- **[Done 2026-08-13] Four more real jurisdiction bugs reported by the
  user after reviewing the production backfill's results — the
  SLC/Holladay PrimeGov bug, a state-casing bug (Colorado Springs), and 8
  nationally-ambiguous city names with no state (Alexandria VA,
  Sacramento CA, Long Beach CA, Oakland CA, San Diego CA, Berkeley CA,
  Boston MA, Baltimore MD). All shipped in one PR (#34), then re-run
  through the backfill scoped per-domain, then live-verified.**

  **SLC/Holladay**: the earlier same-day investigation (see the still-open
  `BACKLOG.md` entry for the general structural problem) had reverted a
  positional-window fix because it traded two correct real cities for
  one. Checking the actual URLs of every `slc.primegov.com` page in the
  Archive settled it: every one of them, including the two mis-labeled
  "City of Holladay," has its own meeting title confirming it's really a
  Salt Lake City meeting ("Salt Lake City Formal Meeting," "Salt Lake
  City Council Work Session"). Added `slc.primegov.com` to
  `jurisdiction_enrich._KNOWN_DOMAINS` and a new
  `known_jurisdiction_display()` helper — unlike the existing
  fill-in-missing-state-only lookup, this returns a full "City of X,
  ST" string and is checked in `primegov.py`'s `resolve()` *before*
  `_extract_jurisdiction()`'s unreliable body-text search ever runs, so
  the false-positive Holladay match can no longer win. Scoped to this one
  confirmed domain only — see the still-open `BACKLOG.md` entry for why a
  future unconfirmed PrimeGov city could still hit the original bug.

  **Colorado Springs "Co" vs. "CO"**: Colorado Springs' own Granicus RSS
  channel title carries the state as "Co," not "CO" — a real source-data
  quirk, not a bug in this repo's own extraction. Neither existing
  mechanism caught it: `enrich_jurisdiction_text()` skips any value that
  already has a comma (by design, so it doesn't second-guess a state that
  came with the name), and `normalize_state_suffix()` only matched a
  *spelled-out* full state name. Extended `normalize_state_suffix()`
  (`archive/utils/jurisdiction_format.py`) to also re-case an
  already-2-letter suffix that's a real abbreviation but not uppercase —
  still a no-op on an already-correct "Dublin, CA."

  **8 no-state cities**: all were extracting a correct "City of X" with
  no state because the name is genuinely ambiguous nationally (confirmed
  via `app/utils/jurisdiction_data` — e.g. "Alexandria" collides with
  real places in LA/MN/KY/IN, "Boston" with several small towns outside
  MA), so `enrich_jurisdiction_text()`'s name lookup correctly declined
  to guess. Added each as a confirmed domain to `_KNOWN_DOMAINS`, same
  pattern as the existing Detroit/Charlotte/Minneapolis/Dallas County
  entries — 7 on Granicus (Alexandria, Sacramento, Long Beach, Oakland,
  San Diego, Berkeley, Boston), 1 on Legistar (Baltimore, resolved via
  the page's own domain, not the delegated YouTube video's).

  **Verified**: 15 new/updated unit tests (608 total passing, including 3
  existing tests whose fixtures now correctly resolve a state they'd
  previously hardcoded as unresolved — Baltimore, Alexandria). Once both
  Render services deployed the merged PR, re-ran
  `scripts/backfill_archived_pages.py --url-contains <domain>` once per
  affected domain (58 pages total across all 10 domains, 0 failures) and
  live-verified on redtaperecordings.com: the two former "Holladay" pages
  and every other `slc.primegov.com` meeting now show "Salt Lake City,
  UT"; Colorado Springs shows "CO"; Alexandria shows "Alexandria, VA";
  Baltimore shows "Baltimore, MD".

- **[Done 2026-08-13] Bulk backfill of archived pages — built
  `scripts/backfill_archived_pages.py`, then found and fixed a real bug
  in it via dry-run, then ran it against all 179 production archived
  pages. Fully closes the "archived pages don't self-heal" gap for every
  example on record at the time.**

  **Real bug found before the production run**: the first full dry-run
  (179 pages) had 24 failures, all "Could not find a YouTube video ID in
  {url}" — every LIMS, PrimeGov, and one Legistar (Baltimore) page, plus
  generic_fallback's CRRMA page. Cause: the script picked the finder
  using `MeetingPage.platform`, which stores the name of whichever finder
  actually resolved a page — `"youtube"` for anything that delegates
  (PrimeGov, LIMS, Legistar-via-YouTube, generic_fallback's YouTube-embed
  branch) — rather than the platform to re-resolve *through*. Those pages
  deliberately keep their *original* (non-YouTube) `source_url_normalized`
  stored specifically so a re-resolve goes back through that platform's
  own scraping logic; handing that URL straight to `YouTubeAssetFinder`
  can't find a video ID in it. Fixed by re-detecting the platform fresh
  from the URL (`detect_platform(url)`) instead of trusting the stored
  field — matching what `GET /admin/recheck-archive-page` already did.
  Verified against one LIMS page and one PrimeGov SLC page individually
  before re-running the full sweep; the corrected dry-run then showed
  only 2 failures (both transient YouTube read-timeouts, not a code
  issue) and 172 pages that would update (up from 150) — plus the CRRMA
  page started resolving too.

  **Production run** (`--delay 1.5`, all 179 pages, unscoped): 173 pages
  updated, 2 failed (both the same transient YouTube read-timeouts seen
  in the corrected dry-run — re-running just those later would likely
  clear them, not investigated further since they're not a code bug), 4
  had nothing new to push. Live-verified afterward on
  redtaperecordings.com: Napa's Parks/Rec/Trees Commission page now shows
  "Napa, CA" (previously no state); the Memphis City Council page still
  shows "The City of Memphis, TN" — correctly abbreviated now, but with
  the display-prefix bug intact, tracked as its own item (see "Strip
  'The City of' from jurisdiction display" below); the residual
  Long-Beach-2023 page (real Charlotte, NC meeting archived under a
  stale `detroit-mi-...` slug from before the original Cablecast
  hardcoded-jurisdiction bug was fixed — see the false-alarm
  investigation note this same session) re-pushed cleanly as a no-op,
  confirming the slug itself is just a historical artifact, not a sign of
  further corruption.

  **Decided explicitly not to schedule this to run automatically.**
  Unlike the (scheduled, safe-by-construction) saved-search alert digest,
  which only ever *adds* new content, this script *rewrites* existing
  `MeetingPage` rows against live output from adapters that can
  themselves have bugs — exactly what the platform-detection bug above
  was. Running unattended on a cron would have pushed that bug's 24 bad
  results straight to production instead of catching it in a dry-run
  first. Stays a manual, `--dry-run`-first operation for now; revisit only
  if it accumulates a track record of clean runs.

  Below is the original build entry, kept as-is:

  **The gap this fixes**: `MeetingPage.jurisdiction` (and every other
  resolved field) is set once at ingest and never re-checked on its own.
  Confirmed live against seven separate, already-fixed bugs still showing
  their old wrong value purely because nobody had resubmitted those exact
  URLs since the fix shipped — Long Beach's Swagit "Revised -" bug,
  San Francisco/Denver's display bug, Fresno, Napa and other CA cities,
  Memphis/Jacksonville, a PrimeGov page, and a Viebit/NYCC page.

  **What got built**:
  - `crud.list_all_page_urls()` (`archive/db/crud.py`) — every archived
    page's `slug`/`title`/`platform`/`source_url_normalized`, same shape
    convention as the existing `list_youtube_pages_missing_transcripts()`
    (the "transcript wanted" queue) but unscoped to any one platform,
    since this backfill exists to fix any adapter's stale data.
  - `GET /internal/pages/all-urls` (`archive/main.py`) — token-gated
    route exposing the above, same pattern as `/internal/transcript-wanted`.
  - `archive_client.list_all_page_urls()` (`app/archive_client.py`) —
    the resolver-side proxy fetching that list.
  - `app.main._recheck_archived_page()` gained an optional `dry_run=False`
    parameter — still does the real resolve (so a caller can see what
    *would* change) but skips the push. Previously untested at the unit
    level despite being live since 2026-08-09; gained real coverage in
    this pass (`tests/test_recheck_archived_page.py`) — dry-run vs. real
    push, unsupported-platform and resolve-exception error paths, and
    confirming a resolve with no real content never pushes regardless of
    `dry_run`.
  - `scripts/backfill_archived_pages.py` — the sweep itself. Imports
    `app.main._recheck_archived_page()` directly to reuse its exact
    resolve+push logic rather than reimplementing it. Runs strictly
    sequentially (never concurrently), with a configurable delay between
    *every* page regardless of source domain (default 2s) — real
    politeness matters here, this hits potentially hundreds of different
    live government sites, several of which host more than one archived
    page (e.g. multiple Long Beach meetings all on the same
    `longbeachca.new.swagit.com`). `--dry-run`, `--limit N`, and
    `--platform NAME` flags let a run be scoped/previewed before an
    unscoped real one.

  **Verified three ways**: 15 new unit/integration tests (the crud
  function + route, `_recheck_archived_page()`'s new `dry_run` behavior);
  full suite green (599 tests); and a real local end-to-end run — spun up
  an isolated local Archive server (its own throwaway SQLite file, never
  touching production), seeded one real page (the actual Long Beach
  Swagit meeting, `longbeachca.new.swagit.com/videos/395182`) with a
  deliberately-wrong stored jurisdiction ("Revised - Long Beach, CA",
  reproducing the real bug), then ran the script against it: `--dry-run`
  correctly reported "would push -- jurisdiction='Long Beach, CA'" while
  leaving the stored value untouched (confirmed by re-reading it after),
  then a real run correctly rewrote the stored value to `Long Beach, CA`
  (confirmed by re-reading it again). This used a genuine live network
  call to the real Swagit page, not a mock, and never touched production
  data at any point.

  **Explicitly not done in this pass**: running it against production.
  Given it hits potentially hundreds of different real government
  websites and rewrites live `MeetingPage` rows, that's a deliberate,
  separate action for whoever has `ARCHIVE_BASE_URL`/
  `ARCHIVE_INGEST_TOKEN` access to run themselves, ideally starting
  scoped (`--dry-run --limit 5` or `--platform swagit`) before an
  unscoped run — see the still-open `BACKLOG.md` entry.

- **[Done 2026-08-13] Four real bugs found live-testing the previous
  day's jurisdiction_enrich rollout, all shipped in one pass
  (PR #29) — this entry was missed at the time and only written up
  after the fact, 2026-08-13, when the user asked whether the Swagit fix
  had a backlog record at all. It didn't; corrected here.**
  - **`format_jurisdiction_display()` (`archive/utils/
    jurisdiction_format.py`) and its JS twin (`app/static/player.js`)
    mangled real consolidated city-counties.** A naive "starts with
    'City '" prefix check also matched "City and County of San
    Francisco"/"...Denver" on just the first 5 characters, leaving "and
    County of San Francisco". Checked and left fully untouched now — the
    "and County of" phrasing is real, non-redundant information, unlike
    a plain "City of", same reasoning as why "County of X" alone was
    already preserved.
  - **Swagit's title-parsing regex (`app/platforms/swagit.py`'s
    `_extract_metadata()`) swallowed a "- Revised -"/"- Closed Session -"
    marker into the jurisdiction on Long Beach meetings** (e.g. "Revised
    - Long Beach, CA" instead of "Long Beach, CA"). A lazy `(.*?)`
    title-part match locks onto the *first* hyphen it can make the rest
    of the pattern satisfy — since the marker text itself has no comma,
    that first split still worked, swallowing "Revised - Long Beach"
    whole into the city group. Made the match greedy (`(.*)`) so it
    always backtracks to the *last* hyphen before ", {State}$" instead —
    the real city boundary in every real title shape seen so far,
    including the plain no-marker case. Live-reverified 2026-08-13 (see
    the "archived pages don't self-heal" entry in `BACKLOG.md`): a fresh
    resolve of `longbeachca.new.swagit.com/videos/395182` with the
    current code correctly returns `Long Beach, CA`.
  - **Dallas County's CivicWeb pages had no state.** Investigated why the
    ZIP-anchored address fallback wasn't catching it: the real page has
    zero 5-digit numbers anywhere in its raw HTML, so the lookup had
    nothing to key off. Added `dallascounty.civicweb.net` to
    `jurisdiction_enrich.py`'s confirmed-domain registry instead, same
    pattern as Cablecast's Detroit/Charlotte entries — live-verified
    resolves to `Dallas County, TX`.
  - **LIMS (`app/platforms/lims.py`) occasionally returned a bare city
    name with no state.** When the agenda page's title didn't match the
    expected `_TITLE_RE` shape, `resolve()` silently kept whatever
    jurisdiction `YouTubeAssetFinder` had already set — the channel/
    uploader name, an unrelated field. Fixed to always prefer the known
    Minneapolis domain (LIMS is single-tenant, every real URL is this one
    system) rather than ever trusting an uploader name for this
    specifically.

  **Verified**: full suite green (556 tests, 5 new regression tests:
  `test_display_keeps_consolidated_city_and_county_label`,
  `test_extract_metadata_strips_a_revised_marker_from_jurisdiction`,
  `test_extract_metadata_strips_a_closed_session_marker_from_jurisdiction`,
  plus CivicWeb/LIMS domain-fallback tests). Also confirmed several other
  user-reported cases from the same live-testing pass (Fresno, NYCC,
  Memphis, Jacksonville, "SLC Live Meetings") were stale already-archived
  data from before earlier fixes shipped, not currently-reproducible
  code bugs — current code resolves all of them correctly when re-run
  directly. That distinction turned into its own tracked, still-open
  entry (`BACKLOG.md`'s "archived pages don't self-heal") once it kept
  recurring.

- **[Done 2026-08-12] Built `app/utils/jurisdiction_enrich.py` — a shared,
  Census-backed "fill in a missing state" module, and wired it into
  Granicus (the largest single source of the gap) and Cablecast.**
  Follows a full per-adapter audit (below) of *why* jurisdictions come
  through with no state, done at the user's request after
  `normalize_state_suffix()` (which only ever reformats an *already-
  present* trailing `", <State>"` suffix) turned out to leave plenty of
  real jurisdictions completely untouched.

  **The audit's real findings, by adapter:**
  - **Never state-less**: `aurora.py`, `slc.py`, `viebit.py` (fixed
    single-jurisdiction constants); `swagit.py` (its one regex is
    `"{City}, {ST}"`-shaped, so state is always present when it matches
    at all, absent entirely — not state-less — otherwise).
  - **State-less by construction, the real bulk of the gap**:
    `granicus.py`'s two primary jurisdiction paths (body-text "City of
    X"/"X County" regex, and the RSS channel-title split) never include a
    state; `legistar.py` shares the same shape and often inherits
    Granicus's own gap via delegation; `primegov.py`, `escribe.py`,
    `civicweb.py`, `lims.py` are all the same — real free text pulled
    straight off the source page, never structured into city+state.
  - **Not really a jurisdiction at all**: `youtube.py` sets
    `jurisdiction=info.get("uploader")`, a channel name.
  - **Depends on upstream data completeness**: `civicclerk.py` trusts its
    own API's `location.state`, correct when populated, silently absent
    otherwise (unconfirmed how often that happens across customers).
  - **A different shape `normalize_state_suffix()` can't touch even in
    principle**: `ca_legislature.py` builds `"California State Assembly"`
    — the state is already in the name, just not as a trailing suffix.
  - **No jurisdiction set at all** (arguably a cleaner failure than
    state-less): `generic_fallback.py`'s direct fallback path and
    `civicplus.py` when not delegating.

  **What got built, following a real back-and-forth on architecture with
  the user** (should city/state logic live inside each adapter, or above/
  after them, or as a URL/domain table?) — landed on a layered design,
  not a single mechanism:
  1. **Real US Census Bureau Gazetteer/relationship data**
     (`app/utils/jurisdiction_data/*.csv`, generated by
     `scripts/build_jurisdiction_data.py` from four official, public-
     domain source files: national counties, national places/cities, and
     ZCTA-to-county + ZCTA-to-place relationship files). Real, verified
     numbers, not estimates: 3,222 counties, 19,465 active incorporated
     places (after filtering out Census-Designated Places, which have no
     real government), 46,940 ZCTA↔county relationship rows, 34,383
     ZCTA↔place rows — ~3.2MB total, checked into the repo. Deliberately
     keeps every row, including real name collisions (422 county names
     and 2,243 place names repeat across multiple states — "Washington
     County" alone exists in 30+ states; "Detroit" is a real city in MI,
     OR, AL, *and* TX) and every ZCTA that spans more than one county/
     place (~30% of them, confirmed directly against the real data) —
     ambiguity is resolved at lookup time, not by deleting rows.
  2. **The real trap this whole design is built around, found while
     scoping it with the user**: a government office's own mailing
     address, found via a ZIP-anchored regex in page text, almost always
     resolves (via ZIP) to whichever *city* physically contains it — even
     when the real jurisdiction is the surrounding *county*, since ZIP
     codes are a postal construct with no concept of county government at
     all. Confirmed concretely: ZIP 95403 (a real Santa Rosa, CA address)
     maps correctly to "Sonoma County" via the ZCTA→county crosswalk and
     to "Santa Rosa city" via the ZCTA→place crosswalk — both correct
     answers to different questions. Fixed by never letting the module
     infer *type* (county vs. city) from a ZIP lookup at all — type must
     always come from the caller's own real page-text classification
     (the same "County"/"Parish" vs. "City of"/"Town of" distinction
     adapters already make), and the ZIP lookup is scoped to query only
     the matching type's crosswalk.
  3. **`resolve_state(name, jurisdiction_type, *, netloc=None,
     page_text=None)`** — the one public entry point, tried in priority
     order: (a) a confirmed domain match (`lookup_by_domain()`, a small
     hand-curated registry — the *most* reliable signal, since it
     resolves even a nationally-ambiguous name like "Detroit" or
     "Charlotte" by tying it to one specific, human-verified real
     instance); (b) an unambiguous name lookup against the matching
     type's Census table (returns `None` on a real collision, never
     guesses); (c) a ZIP-anchored address found in `page_text`
     (`find_zip_addresses()`), cross-referenced against the same type's
     crosswalk. Returns `None`, never a guess, if nothing resolves.
  4. **Cablecast migrated**: `_KNOWN_STATE_BY_CITY` (the old two-entry
     hardcoded dict) replaced by a call into the shared module — same
     Detroit/Charlotte results (both still only resolve via the confirmed-
     domain registry, since both names are genuinely ambiguous nationally,
     confirmed against the real gazetteer), plus a real, free improvement:
     a future unconfirmed Cablecast customer with a nationally-unique city
     name (verified with a real test: "Chicago") now resolves automatically
     with no allowlist entry needed at all.
  5. **Granicus wired**: a new `_enrich_jurisdiction_state()` step runs
     once, after the RSS-channel-title override (the last thing that can
     change `jurisdiction`), reusing the same `page_text` blob
     `_extract_metadata()` already builds. Skips anything that already
     has a comma (from `_humanize_subdomain()`'s own existing state-suffix
     detection) or the "Unknown Jurisdiction" placeholder. Type is read
     directly from whether "County"/"Parish" appears in the already-
     extracted jurisdiction text.

  **Verified three ways**: 23 new unit tests for `jurisdiction_enrich.py`
  itself (every real example cited above, plus the ZCTA tie-break logic
  against a real multi-county ZIP — 94952 spans both Marin and Sonoma
  counties, Marin's real overlap area is larger, confirmed picked
  correctly); updated Cablecast/Granicus test suites (new enrichment-
  specific tests plus all existing tests still passing unchanged,
  including the one real pre-existing case, Alexandria, VA, that
  correctly stays state-less since "Alexandria" is a real, genuinely
  ambiguous city name in 8 states); and live, real-network checks against
  three real Granicus cities — Napa (`County of Napa, CA`, via RSS-title
  + county lookup), Fresno (`City of Fresno, CA`, a clean new
  resolution), and Colorado Springs, which surfaced a real, pre-existing,
  harmless quirk: its own RSS feed literally says "City of Colorado
  Springs, **Co**" (lowercase, a source-side typo) — confirmed via direct
  `curl` of the real feed, not a bug introduced here; the enrichment step
  correctly left it untouched since it already had a comma, exactly the
  intended conservative behavior. Full suite green (544 tests).

  **Explicitly not attempted this pass, real follow-ups**: Legistar,
  PrimeGov, eScribe, CivicWeb, and LIMS all share the same "free-text
  extraction, no state" shape as Granicus and would benefit from the same
  `resolve_state()` wiring, just not done yet — Granicus was picked first
  as the single largest source of the gap, not the only one. **Update
  2026-08-12: all five wired, plus a CivicClerk fallback — see the entry
  below.** YouTube's uploader-as-jurisdiction and the "no jurisdiction set
  at all" cases (`generic_fallback.py`, `civicplus.py`) are different
  problems this module doesn't address at all (not a missing state, a
  wrong or absent field) and still need their own fixes, not covered by
  either pass.

- **[Done 2026-08-12] Wired `jurisdiction_enrich.resolve_state()` into the
  remaining five free-text adapters flagged as follow-ups above —
  Legistar, PrimeGov, eScribe, CivicWeb, LIMS — plus a CivicClerk
  fallback, closing out the "no-state jurisdiction" audit for every
  adapter identified in it.** Direct continuation of the entry above, at
  the user's own "well, let's do it for all the adapters, right?"
  request; same shared `enrich_jurisdiction_text()` call, same
  comma-guard/placeholder-skip logic, wired at each adapter's own
  jurisdiction-extraction point (after any adapter-specific override, same
  as Granicus's own RSS-title-override ordering) rather than centralizing
  it above/after all adapters, since the raw page text a ZIP-anchored
  address lookup needs doesn't survive past each adapter's own `resolve()`
  call.

  **Per-adapter notes**:
  - **Legistar** (`_extract_page_meeting_info()`) — both call sites
    (the primary parse and `_try_fallback_video_link()`'s own metadata
    read) updated to pass the page URL through for domain lookup.
  - **PrimeGov** (`_extract_jurisdiction()`) — wired in the same pass that
    hit and reverted a real regression (see the correction entry below);
    the enrichment wiring itself wasn't the regression's cause.
  - **eScribe, CivicWeb, LIMS** — same shape, each adapter's own
    `page_text`/`url` already in hand at the extraction point, no new
    network call needed.
  - **CivicClerk** — different shape from the other five: its own API
    returns `eventLocation.city`/`.state` as separate structured fields
    already, not free text to parse a type out of, so rather than reusing
    `enrich_jurisdiction_text()` (built for a single combined string) this
    calls `jurisdiction_enrich.lookup_city_state()` directly, and only
    when `city` is present but `state` is empty — the "both present"
    case (every real sample checked so far: Clovis CA, Emporia KS,
    Highland CA, Lino Lakes MN) is left untouched. **Unconfirmed with a
    real example** — no CivicClerk customer with a genuinely blank
    `location.state` has been found yet, so this fallback is
    schema-verified but not content-verified, same "flagged, not assumed"
    convention as this repo's other best-effort paths; covered by a
    synthetic test (`test_resolve_fills_in_missing_state_via_shared_lookup`,
    `tests/test_civicclerk.py`) using an unambiguous city (Fresno, CA)
    rather than a real fixture.

  **Two real bugs found and fixed while wiring this, both in the shared
  module, not adapter-specific**:
  1. **`_normalize_name()` double-stripping "City of Oklahoma City"**:
     leading-strip correctly removed "City of " → "Oklahoma City", but the
     same call then *also* trailing-stripped the remaining "City" (the two
     strips weren't mutually exclusive yet) → wrong key "Oklahoma" →
     collided with a real "Oklahoma borough, PA" in the gazetteer → wrong
     state (PA instead of OK) returned. The bare form "Oklahoma City" (no
     "City of" prefix) hit the same collision via the unconditional
     trailing-strip. **Fixed** two ways together: made `_normalize_name()`
     (used for stored/keyed data) do one strip only, leading OR trailing,
     never both; and added `_normalize_candidates()` (used for query-side
     lookups) which tries the as-is lowercased form first — matching how
     the Census data itself stores "Oklahoma City city" → "oklahoma city"
     — only falling back to a trailing-stripped candidate if the as-is
     form isn't a real table key. Regression tests added for both the
     "City of X City"-shaped and bare "X City"-shaped forms of this trap,
     plus the user-suggested "Kansas City" case (real in both KS and MO,
     confirmed correctly stays ambiguous rather than picking one).
  2. **PrimeGov's window-cap regression** — found live-testing this exact
     wiring, full detail in the correction entry directly below.

  **Verified**: full suite green (551 tests, up from 544) after all six
  adapters wired; live-verified against real pages for Cablecast,
  Granicus, PrimeGov (OKC + Thousand Oaks, post-revert), CivicWeb (Dallas
  County, correctly stays state-less — genuinely ambiguous across 5
  states); Legistar's own two previously-live-verified sample URLs
  (Mesa AZ, Baltimore MD) both now 410 Gone (meetings rolled off
  Legistar's own site since they were last checked, unrelated to this
  change) — Legistar's fixture-based tests, which encode the real page
  shape from when they were fetched, still pass unchanged. See
  `jurisdiction_test_examples.csv` (repo root, also copied to
  `~/Documents/rtr-business/research/`) for the full table of every
  jurisdiction/adapter/URL combination used to validate this work,
  ambiguous and unambiguous alike.

- **[Done 2026-08-12] Cablecast real transcript extraction — built the
  same day the first positive `vodTranscripts` example was found (see the
  Cablecast jurisdiction-fix entry below), at the user's own request to
  bundle it into the same pass.** `vodTranscripts` had long been a real
  field in Cablecast's schema, but was empty `[]` on every one of 36
  Detroit shows checked — until a real Charlotte, NC show
  (`show/2451`) turned up a genuinely populated, fetchable entry:
  `[{"languageCode": "en", "url": ".../2451-City-Council-Meeting-v17/
  transcript.en.txt"}]`.

  **The file's real shape, confirmed live via `curl` (not guessed)**: one
  cue per line, `HH:MM:SS,mmm<TAB>ALL CAPS TEXT`, blank-line-separated,
  real `\r\n` line endings — 512 real cues across a genuine ~3h16m
  meeting. Despite the `.txt` extension, this is **not** real SRT (no
  sequence-number lines, no `-->` end-time range, just a single start
  timestamp per block) — feeding it through `vtt_parser.py`'s existing
  `.txt` fallback (`strip_unknown_caption_markup()`) would have left each
  cue's raw timestamp glued onto the front of its text as if it were
  content, since that fallback's timing-line stripper only recognizes a
  *pair* of timestamps (`-->`-shaped), not a single one. Also would have
  wrongly routed every *other* platform's own generic `.txt` caption
  fallback through Cablecast-specific parsing, since `vtt_parser.py`'s
  dispatch is keyed by file extension, not by platform.

  **Built, in `app/platforms/cablecast.py` directly** (not
  `vtt_parser.py`, for the reason above): `_parse_transcript()` parses
  the real shape; each cue's end is the next cue's own start (no
  explicit end time exists in the format at all — same convention
  Granicus's `AgendaViewer.php` chapter markers already use for the
  identical "only a start time given" shape). `_fetch_transcript()`
  fetches + decodes (reusing `vtt_parser.py`'s `decode_vtt_bytes()` for
  the same non-UTF-8-safe fallback every other adapter's caption fetch
  already has). `resolve()` fetches every entry in `vodTranscripts`
  concurrently (`asyncio.gather`), re-derives each track's real language
  from its own cue text via `detect_language_from_texts()` rather than
  trusting the entry's own `languageCode` label (same "never trust the
  source-provided label" stance Granicus/CivicClerk already take, after
  a real Simi Valley Granicus track once turned out to be mislabeled),
  prefers an `"en"` match as the primary transcript, and carries any
  other real fetched track as an `AlternateTranscript` rather than
  discarding it — same shape Granicus's own multi-track handling already
  uses. `normalize_shouting_caption()` re-cases the real ALL-CAPS content,
  same treatment every other platform's shouting captions get. A fetch
  failure (404, timeout) on a populated `vodTranscripts` entry degrades
  to the same honest "No transcript found for this event." outcome as no
  entry at all, not a crash.

  Verified against a new real fixture
  (`tests/fixtures/cablecast/charlotte_transcript_2451.en.txt`, the exact
  live file) — 512 cues, correct end-time-borrowed-from-next-cue
  behavior, correct `en` language detection, correct ALL-CAPS re-casing
  (including a genuine artifact worth noting, not a bug: the very first
  cue has a stray leading comma before its first word, so the shared
  sentence-case regex finds no letter right at position 0 to capitalize
  and that one cue starts lowercase — real source data, not something
  this fix should silently "fix" further). Plus 4 new isolated
  `_parse_transcript()` unit tests (basic shape, last-cue end-equals-
  start, malformed lines skipped, no-match returns empty) and a
  fetch-failure test. Also **live-verified end-to-end against the real
  Charlotte URL over the real network** (not just the fixture) — same
  512 segments, `en`, zero warnings. Full suite green (513 tests).

- **[Done 2026-08-12] Jurisdiction display was verbose and inconsistent
  site-wide — "City of Napa, CA" everywhere read as redundant since
  almost everything archived is a city.** User request: drop "City of"/
  "City" entirely from display (e.g. just "Napa, CA"), reserving an
  explicit label for the actual exceptions — counties (and states, e.g.
  California State Legislature).

  **Approach**: a real display-time formatter, not a change to what's
  stored — `jurisdiction` is stored pre-formatted at ingest time
  (`normalize_state_suffix()` in `archive/utils/jurisdiction_format.py`,
  called from `archive/db/crud.py`'s `_find_or_create_page()`), and is
  used as free text in several places (page titles, `<title>` tags, JSON-
  LD descriptions, the `/coverage` jurisdiction table) — changing the
  stored value would need a migration/backfill and lose the raw source
  text; a render-time formatter can be revisited freely.

  **Built**: `format_jurisdiction_display()`, next to
  `normalize_state_suffix()` in the same module — drops a leading "City
  of "/"City " (case-insensitive), leaves everything else (including
  "County of X"/"X County" and state-legislature-style body names like
  "Illinois General Assembly") untouched. Registered as a Jinja filter
  (`jurisdiction_display`, `archive/main.py`) and applied everywhere a
  stored `MeetingPage.jurisdiction` renders: `meeting_page.html`'s
  `<title>`, meta/JSON-LD description, and visible byline;
  `meeting_list.html`'s row byline; `saved_items.html`'s saved-meeting
  row (deliberately **not** applied to the saved-*search* filter display
  on the same page, since `sp.jurisdiction` there is raw user-typed
  filter text, not a stored jurisdiction value); `coverage.html`'s main
  table and both platform-grouped sections. The resolver's own
  client-rendered `/meeting?url=` page has no server-side Jinja pass, so
  `app/static/player.js` got its own small JS mirror
  (`formatJurisdictionDisplay()`) applied at its one jurisdiction display
  line.

  Verified with 9 new unit tests (`tests/test_jurisdiction_format.py`) —
  City/City-of dropped (case-insensitive), County/Town/state-legislature
  names preserved, no-prefix values pass through, None/empty handled —
  plus a live-browser check against a real seeded local page (careful to
  point the dev server at a local SQLite file, not the real `DATABASE_URL`
  in `.env`, which turned out to be a real Render Postgres instance, not
  a safe local default): `/m/{slug}`, `/meetings`, and `/coverage` all
  correctly show "Napa, CA" instead of "City of Napa, CA" for a seeded
  "City of Napa, CA" meeting. One existing test
  (`tests/test_footer_and_coverage.py`) asserted the old unformatted text
  verbatim and was updated to assert the formatted text instead — the
  bug this test needed fixing, not a regression. Full suite green (508
  tests).

- **[Done 2026-08-12] PrimeGov's `_extract_jurisdiction()` regex wasn't
  scoped to the page header, so it could pick up an unrelated city name
  mentioned in agenda body text.** Reported by the user with two real
  examples on `slc.primegov.com` (Salt Lake City's own PrimeGov portal): a
  real Salt Lake City Council meeting
  (`https://slc.primegov.com/Portal/Meeting?meetingTemplateId=3853`) got
  jurisdiction "Holladay" instead — Holladay was only mentioned as one
  agenda item (its addition to the Central Wasatch Commission), and
  `app/platforms/primegov.py`'s `_JURISDICTION_RE` (`\b(city|county|town)
  of\s+...`) did a plain `.search()` over the *entire* page HTML, so the
  first "City of Holladay"/"Town of Holladay"-shaped phrase anywhere in
  the agenda body won over the page's real header. A second, different
  meeting got "SLC Live Meetings" as its jurisdiction instead — that one
  never matched the regex at all (no "City/County/Town of X" phrase found
  on that page), so `PrimeGovAssetFinder.resolve()` left
  `YouTubeAssetFinder.resolve_video_id()`'s own `jurisdiction=info.get
  ("uploader")` (the YouTube channel name) in place uncorrected — a real,
  different failure mode from the Holladay case, not the same bug twice.

  **What's actually reliable on a real page** (`meetingTemplateId=3853`),
  checked before assuming a fix: `<title>` is a dead end — literally just
  "Meeting" on every PrimeGov meeting page, confirmed on both the
  Holladay-agenda-item page and the no-match page; no `og:title` meta tag
  exists either. What *is* reliable: the agenda's own header banner,
  `<strong>SALT LAKE CITY COUNCIL</strong><br><strong>AGENDA</strong>`
  (22pt, bold), appears early in the page — well before the "City of
  Holladay" agenda-item text the unscoped regex latched onto instead —
  but not at the raw start either, which is mostly `sessionStorage`/
  CSRF-token JS boilerplate on this platform. Note the real header banner
  itself ("SALT LAKE CITY COUNCIL") isn't shaped like "City/County/Town of
  X" at all, so no regex built around that phrase pattern was ever going
  to extract "Salt Lake City" from it directly — the achievable fix is
  preventing the *wrong* downstream match, not synthesizing a correct one
  from a header shape the regex was never designed to parse.

  **Fix**: `_extract_jurisdiction()` now strips `<script>`/`<style>`
  blocks (`_BOILERPLATE_RE`, removing exactly the sessionStorage/CSRF
  boilerplate that was pushing the real header content further down than
  expected) and caps the search to the first 2000 characters of what's
  left (`_JURISDICTION_SEARCH_WINDOW`, matching `_extract_date()`'s own
  `[:2000]` convention) — scoping the search to the real header/
  agenda-opening area means body text further down the page (like the
  Holladay mention) is never reachable at all, not just deprioritized.
  Separately, `resolve()` now unconditionally sets
  `resolved.jurisdiction = self._extract_jurisdiction(html)` instead of
  only overriding when a page match was found — YouTube's `uploader`
  field is never a jurisdiction, so a PrimeGov page whose header doesn't
  match the pattern now correctly comes through with no jurisdiction at
  all (an honest "we don't know") rather than a wrong-looking channel
  name. Verified with new tests (`tests/test_primegov.py`): a
  reconstructed SLC-shaped page (header that doesn't match, unrelated
  "City of X" text pushed past the search window) correctly returns
  `None` instead of the wrong city; a `<script>`-boilerplate-heavy page
  still correctly reaches a real header past the window; the existing
  "no header at all" test was updated to assert `jurisdiction is None`
  instead of the old fallback-to-uploader-name behavior, since that
  behavior was the bug. Full suite green (500 tests).

  **The URL subdomain (`slc` in `slc.primegov.com`) was considered as a
  secondary signal and deliberately not built** — subdomains don't spell
  out full jurisdiction names, so it'd need its own maintained subdomain
  → jurisdiction mapping rather than being usable directly, more brittle
  than the fix actually shipped.

  **Correction, same day: the window-capping half of this fix was
  reverted after live-checking real character offsets, not just the
  synthetic test above.** While live-verifying the *separate*
  jurisdiction-enrichment (state-filling) work against real PrimeGov
  pages, fetched all three known real examples fresh and found this
  fix's own "the real header appears early, body text appears later"
  assumption was simply wrong for two of them: OKC's real header sits at
  character offset ~4,753 (already past the 2,000-char window — resolved
  to no jurisdiction at all instead of "City of Oklahoma City"), and
  Thousand Oaks's only real match is a "City of Thousand Oaks" mention
  buried in mission-statement prose at offset ~264,423, nowhere near the
  top of the page. Confirmed directly that re-running the *original*
  unscoped search against all three real pages gets OKC and Thousand
  Oaks right (both are genuinely the first "X of Y"-shaped match on their
  own page) and only SLC wrong — meaning the windowed fix had actually
  traded two correct, originally-confirmed real cities for one, a net
  regression, not an improvement. **Reverted the window cap specifically**
  (kept the separate, independently-good `<script>`/`<style>` stripping,
  and kept the "never fall back to YouTube's uploader" fix, which was
  unrelated to windowing) — SLC's original false-positive bug is
  therefore genuinely reopened, tracked as its own live item in
  `BACKLOG.md` with the real offset data above, since no window size can
  cleanly separate "real header" from "false-positive agenda text" by
  position alone across all three known real shapes. Full suite green
  throughout (549 tests after this correction).

- **[Done 2026-08-12] `find_platform_link()`'s fallback delegation could
  self-loop into real infinite recursion — root-caused and reproduced,
  this is what the user's "weird hanging and then an error message"
  actually was**, not a slow page. User's report:
  [/meeting?url=...columbus.legistar.com/MeetingDetail.aspx?ID=1425378...](https://redtaperecordings.com/meeting?url=https%3A%2F%2Fcolumbus.legistar.com%2FMeetingDetail.aspx%3FID%3D1425378%26GUID%3D82C83DE5-FC6D-48A3-A38F-C366EE419566%26Options%3Dinfo%7C%26Search%3D)
  hung, then the frontend showed `Failed to reach the resolver:
  SyntaxError: Unexpected token '<', "<!DOCTYPE "... is not valid JSON`
  — that's the tell: not an application error at all, but a proxy/
  gateway timeout page (HTML) being `JSON.parse()`'d as if it were the
  API response, because the real request never finished in time.

  **Reproduced directly**: `LegistarAssetFinder.resolve()` on this exact
  URL still hadn't returned after 60s locally (killed by an explicit
  timeout in testing) — a real hang, not a one-off network blip.
  Instrumented every step individually to find it: fetch (1.3s) and
  BeautifulSoup parse (0.08s) are both fine; `_find_video_links()`
  correctly finds nothing (this Columbus meeting genuinely has no
  `a.videolink`); the hang is in what happens next.
  `_try_fallback_video_link()` (`app/platforms/legistar.py:130-165`)
  falls to `find_platform_link(html, page_url, exclude={"youtube"})`
  (`app/platforms/base.py`), which finds a real, completely unrelated
  anchor tag every Legistar page has —
  `<a href="#mainContent" class="skip-to-content">Skip to main
  content</a>` — a totally standard accessibility skip-link. `urljoin()`
  resolves `"#mainContent"` against the *current page's own URL*,
  producing that same Columbus URL back again (just with a
  `#mainContent` fragment), and `detect_platform()` on that resolved URL
  matches `"legistar.com" in netloc` → returns `"legistar"` again.
  `exclude` only ever excluded `"youtube"`, never the *current* platform
  — so the code delegates to `LegistarAssetFinder.resolve()` **on
  effectively the same page it's already resolving**, which re-fetches
  it, finds no video again, hits the same skip-link again, and recurses
  again — genuine unbounded recursion, not a slow operation, bounded
  only by Python's recursion limit or a request timeout somewhere
  upstream, whichever comes first. Each cycle re-fetches this
  particular 800KB page (a large real ASP.NET ViewState blob, ~1.3s per
  fetch), so this was also a real resource-waste multiplier, not just a
  hang.

  **Real severity: likely broader than this one Columbus meeting.** Any
  Legistar city where a meeting has (a) no `a.videolink`, (b) no
  YouTube link anywhere on the page, and (c) the same near-universal
  "skip to content" anchor — an extremely common accessibility pattern,
  not a Columbus quirk — would hit this identical loop. Given Phoenix/
  Philadelphia/Albuquerque were already established to have "no video
  link at all" as a common real outcome across several Legistar cities,
  this recursion was plausibly already firing (and timing out) on more
  than just this one reported URL. `generic_fallback.py`'s own
  `_try_delegate_to_known_platform()` calls the same `find_platform_link()`
  and had the identical latent risk, not reproduced with a concrete
  example but closed by the same root-level fix.

  **Fix**: `find_platform_link()` (`app/platforms/base.py`) now skips
  any candidate that resolves to the same URL as `page_url` once its
  fragment is stripped — closes this at the root, for every caller,
  independent of what `exclude` set they pass (a same-page anchor can
  never be a genuinely different platform's real video link). Belt-and-
  suspenders: `legistar.py`'s own `_try_fallback_video_link()` also now
  excludes `"legistar"` explicitly, not just `"youtube"`. Verified with
  a new regression test reproducing the exact Columbus shape (a page
  with no `a.videolink` and only a same-page skip-link) resolving
  cleanly to the honest "No video link found" message instead of
  hanging, plus two lower-level `base.find_platform_link()` unit tests
  (a bare `#fragment` href, and an absolute self-referencing href with a
  fragment). Full suite green (498 tests total across this session's
  changes).

- **[Done 2026-08-12] Resolve-level cache had no expiry at all, unlike
  its Archive-level counterpart — a one-time bad resolve got served to
  every future visitor forever.** Real example: Portland, OR's council
  agenda pages (`www.portland.gov/council/agenda/...`) really do resolve
  correctly today, but the live site was serving a stale, permanently-
  cached negative result from before that was true. User report:
  [www.portland.gov/council/agenda/2026/7/29](https://www.portland.gov/council/agenda/2026/7/29)
  "doesn't get handled the way I'd expect" despite an obvious embedded
  YouTube video — live resolve showed "We think the video is here: [No
  video found]" / "[No agenda found]."

  **But the exact same resolve, run directly against this repo's own
  code (register_all_finders → detect_platform → finder.resolve(), no
  mocking), found everything correctly**: `video_url:
  https://www.youtube.com/embed/5DaGjSejyF4`, `video_format: youtube`,
  `agenda_link: https://www.portland.gov/council/agenda`. The raw page
  really does server-render a plain `<iframe src="https://www.youtube.com/embed/5DaGjSejyF4...">`
  (confirmed via direct `curl`, no JS needed), `www.portland.gov` isn't
  matched by any `detect_platform()` rule so it correctly falls to
  `GenericFallbackAssetFinder`, and its
  `YouTubeAssetFinder.extract_video_id(html)` step found the embed on
  the very first try. **The extraction code was not the bug** —
  confirmed by literally re-running it, not just reading it.

  **The real bug was the resolve-level cache having no expiry.**
  `/api/resolve` checks the Archive first (which correctly *does* have a
  recheck window — `ARCHIVE_RECHECK_AFTER`/
  `ARCHIVE_RECHECK_AFTER_NO_TRANSCRIPT`), then falls to
  `crud.get_cached_resolution(normalized)` (`app/db/crud.py`) for
  anything not yet archived — and that query had **no age check or TTL
  at all**, just "most recent row with `status == 'success'`, however
  old." Critically, `status="success"` gets logged unconditionally for
  *any* resolve that doesn't raise — `video_found=bool(result.video_url)`
  was just a descriptive column, not something that excluded a
  found-nothing `GenericFallbackAssetFinder` result from being cached and
  replayed forever. Whatever this specific URL's *first-ever* resolve
  attempt returned (plausibly before generic-fallback's YouTube-embed
  detection existed, or a one-off transient fetch hiccup) was what every
  subsequent visitor got served indefinitely, with no automatic path
  back to a fresh resolve.

  **Fix**: `get_cached_resolution()` now expires a `video_found=False`
  row after `_STALE_NO_VIDEO_RECHECK_AFTER` (1 hour, mirroring
  `ARCHIVE_RECHECK_AFTER_NO_TRANSCRIPT`'s own "nothing to lose by looking
  again" reasoning) — a row that DID find a video keeps no TTL at all, a
  confirmed-working platform resolve being much less likely to have been
  wrong than a "found nothing" miss is to have since improved. Verified
  with three new real-DB tests (`tests/test_app_db_crud.py`): a stale
  no-video row is correctly ignored (falls through to `None`, triggering
  a fresh live resolve), a fresh no-video row within the TTL is still
  served, and a video-found row backdated 30 days is still served
  unconditionally (confirming the TTL is scoped correctly, not a blanket
  exclusion). Full suite green.

- **[Done 2026-08-12] "Request Transcript from Audio" showed a misleading
  "no usable audio or video source" error that was actually just the
  transcription-request rate limit — root-caused and fully reproduced**
  on a real example the user flagged:
  [/m/the-city-of-milwaukee-wi-2026-07-31-common-council-on-2026-07-31-9-00-am](https://redtaperecordings.com/m/the-city-of-milwaukee-wi-2026-07-31-common-council-on-2026-07-31-9-00-am)
  (Granicus, `milwaukee.granicus.com/player/clip/5265` — video played
  fine on the page itself, confirmed by watching it; the garbled-at-
  source caption detection the user was pleased with was correct and
  unrelated). Clicking the button fires `POST /api/transcription/
  check-feasibility` (`app/main.py`), capped at `@limiter.limit
  ("5/hour")`. **The real response, confirmed via a live network capture
  that reproduced this exact symptom, was an HTTP 429 with body
  `{"error":"Rate limit exceeded: 5 per 1 hour"}`** — not the route's own
  `{"ok": false, "message": ...}` shape at all (slowapi's rate-limit
  handler returns its own generic body instead). The frontend didn't
  distinguish these two shapes: `runFeasibilityCheck()` (present,
  identically, in both `archive/static/meeting_page.js` and
  `app/static/player.js`) did
  `checkStatusEl.innerHTML = linkifyWarning(data.message || "We couldn't
  find a usable audio or video source for this meeting.")` — on a 429,
  `data.ok` and `data.message` were both `undefined`, so it silently fell
  through to that hardcoded default, reading exactly like a real
  Granicus-resolution failure with no hint the actual cause was "you've
  already requested 5 transcriptions this hour, try later."

  **Second real-world hit, same day**: user separately reported the same
  "couldn't find a media file" failure on a Detroit, MI Cablecast meeting
  after trying "a couple URLs." Checked both underlying steps directly,
  standalone, against that exact real show: `CablecastAssetFinder.resolve()`
  found the real `.m3u8` in 0.3s, and `probe_duration()` against that
  same URL correctly read a real ~29-minute duration in ~5s — neither
  step was broken for Cablecast specifically. Hit the identical 429 twice
  testing this in the same session (already used up the 5/hour budget
  from the Milwaukee check above), the more likely explanation than a
  second, Cablecast-specific bug: trying several URLs in a row is exactly
  the usage pattern that exhausts 5/hour fastest, and every one of those
  attempts would show this same misleading message regardless of
  platform.

  **Fix**: both duplicated copies of `runFeasibilityCheck()`
  (`app/static/player.js`, `archive/static/meeting_page.js`) now check
  `res.status === 429` explicitly, before falling through to `data.ok`,
  and show real rate-limit copy ("You've requested a few transcripts
  already this hour — please try again a bit later.") instead of the
  generic failure message. No existing JS test framework covers
  `player.js`/`meeting_page.js` directly (only `shared_static/
  deep_link.js` has JS test coverage in this repo) — verified live
  in-browser instead, matching this repo's own "verify in-browser, not
  just via the API" convention.

  **Separate, less-clear observation from the same Detroit report**:
  initial page load/video playback was described as "very slow"
  (eventually loads fine). Not reproduced consistently enough to
  root-cause — most likely an unrelated cold-start delay (Render's
  worker/web services spinning up from idle) rather than anything
  Cablecast-specific, since the direct `resolve()` timing above was
  fast; a real gap still worth a second look if it recurs independent of
  a fresh deploy/idle period, not closed by this fix.

- **[Done 2026-08-12] `CablecastAssetFinder` hardcoded jurisdiction as
  "Detroit, MI" for *every* Cablecast customer, not just Detroit — real
  wrong-data bug, confirmed live** on a real example the user hit
  directly: submitting [charlotte.cablecast.tv/internetchannel/show/2451](https://charlotte.cablecast.tv/internetchannel/show/2451?site=1)
  (a real Charlotte, NC City Council meeting, "Council Meeting - June
  22, 2026") resolved with jurisdiction "Detroit, MI." Reproduced
  directly against this repo's own code: title, date, and video
  (`charlotte.cablecast.tv/store-40/2451-City-Council-Meeting-v17/vod.m3u8`)
  all resolve correctly — only jurisdiction is wrong, and it's wrong
  because it's not actually derived from the page at all.
  `_JURISDICTION = "Detroit, MI"` (`app/platforms/cablecast.py:63`) was a
  hardcoded class constant, unconditionally applied to `resolve()`'s
  output regardless of which real Cablecast customer the URL belongs to.

  **Root cause of why Charlotte even reaches this adapter at all**:
  `detect_platform()`'s own comment (`app/platforms/base.py`, the
  `cablecast.tv` block) claimed "Charlotte, NC's confirmed Cablecast site
  uses a visibly different template this adapter doesn't handle" —
  **confirmed false for this URL shape**, live: Charlotte's
  `/internetchannel/show/{id}` page has the identical
  `window.__remixContext` Remix.js structure Detroit's does (makes sense
  in hindsight — Cablecast is a shared hosted product, so of course
  customer show-pages share a template; whatever *was* different about
  Charlotte at the time that comment was written, either wasn't this
  specific page shape, or has since changed). So this isn't really
  "Charlotte slipping through a narrow domain check" — it's the adapter
  legitimately working end-to-end for a second real customer, with only
  the identity label wrong.

  **Fix**: `_extract_jurisdiction()` now reads the real per-customer
  identity out of the already-parsed Remix `site` object (found via a new
  `_find_site()`, the same recursive-search shape `_find_show()` already
  used — matched on `siteId` *and* `pageDescription` together, since real
  pages also carry many small `{siteId, title: None}` decoys nested under
  each show's own `upcomingRuns` list that would otherwise match first).
  Tries `site.pageDescription`'s prose first (a "City/County/Town of X"
  phrase), falling back to `site.title`. `site.title` alone was confirmed
  too unreliable to use directly: Detroit's real title is "Channel 10" (no
  city name anywhere in it), while Charlotte's is "City of Charlotte GOV
  Channel" — genuinely different shapes between two real customers, not
  two ways of writing the same thing; `pageDescription` is what actually
  names the city reliably on both ("The City of Detroit's Channel 10
  features..." / "The City of Charlotte is committed to..."). A state
  suffix (", MI" / ", NC") is only appended for a customer this has
  actually been confirmed against (`_KNOWN_STATE_BY_CITY`, a two-entry
  allowlist) — Cablecast's own page data has no state field or reliable
  domain signal, so a not-yet-confirmed city renders with no state suffix
  rather than a guessed one, tracked as a real, honest gap by the
  "no-state jurisdiction audit" item in `BACKLOG.md`.
  `_JURISDICTION_RE` deliberately matches a single word only (not a real
  multi-word city name like "Fountain Valley") — both real customers
  confirmed so far are one-word cities, and a multi-word capture would
  have greedily pulled `title`'s own trailing branding words ("... GOV
  Channel") in as if they were part of the city name; revisit once a real
  multi-word-city customer turns up.

  Verified against a real Charlotte fixture
  (`tests/fixtures/cablecast/charlotte_show_2451.html`, fetched live) added
  alongside the existing Detroit one — both now resolve their own real
  jurisdiction correctly (`tests/test_cablecast.py`, 8 new tests covering
  `_find_site`/`_extract_jurisdiction` directly plus the full Charlotte
  resolve). Full suite green (498 tests). Not yet checked against a third
  real Cablecast customer, so the single-word-city assumption is still
  worth revisiting once one turns up.

  **Bonus, unrelated discovery from fetching the Charlotte fixture**: real
  show 2451's `vodTranscripts` field is genuinely populated — `[{
  "languageCode": "en", "url": ".../2451-City-Council-Meeting-v17/
  transcript.en.txt"}]` — and that URL is real and fetchable (confirmed
  live via `curl`, HTTP 200, ~160KB of real content). This is the first
  positive example of this field ever found (every one of 36 Detroit shows
  checked earlier had an empty `[]`). **Not yet extracted/wired in** — out
  of scope for this jurisdiction-fix pass; tracked as a real, distinct
  follow-up in `BACKLOG.md` (`Platform coverage`), since the file's own
  shape (`HH:MM:SS,ms<TAB>ALL CAPS TEXT`, blank-line-separated — not real
  SRT, no index numbers or `-->` range) needs its own parser.

- **[Done 2026-08-12] Fixed YouTube's `upload_date` off-by-one at the root
  (`app/platforms/youtube.py`), found while researching Columbus, OH for
  Wave 2 platform coverage.** Columbus's own `columbus.legistar.com`
  meeting pages have no video link at all (confirmed live: 0
  `a.videolink` elements, same "Legistar with no video column" pattern
  already documented for Phoenix/Philadelphia) — real recordings live
  only on the city's YouTube channel/playlist, with no link back from
  Legistar at all. Rather than build a risky Legistar→YouTube matching
  feature (fuzzy title/date search across a channel, real chance of
  picking the wrong meeting's video), confirmed live that pasting the
  YouTube URL directly already resolves correctly today via the existing
  `YouTubeAssetFinder` — real title, jurisdiction, and an 8,037-segment
  transcript, zero new code needed. **Not worth building the matching
  feature at all**: the core deep-link value (video + transcript) is
  already complete for Columbus as long as someone pastes the YouTube
  link instead of the Legistar one; matching to the Legistar record
  would only add polish (an official agenda link, jurisdiction
  cross-check), a real but low-value, not-yet-built enhancement.

  **Real bug found in the process**: the resolved date came back one day
  off (`2026-06-23` instead of the real `2026-06-22`) — the same
  previously-known `upload_date`-is-when-posted-not-when-it-happened gap
  `primegov.py` already works around at its own layer (see its
  `_extract_date()`/BACKLOG_DONE.md's PrimeGov entry), but never fixed at
  the root in `youtube.py` itself, so every other path that delegates to
  `YouTubeAssetFinder` (direct YouTube URLs, SLC, LIMS, Mesa/Albuquerque's
  Legistar delegation) still had it. Root cause confirmed via yt-dlp
  directly on two independent real, livestreamed-then-archived samples
  (Columbus and the already-documented OKC PrimeGov case): `upload_date`
  reflects when the VOD finished processing (one day late on both), while
  `release_date` — the live broadcast's own start date, present whenever
  `was_live=True` — matched the real meeting date exactly on both. Fixed:
  `resolve_video_id()` now prefers `release_date`, falling back to
  `upload_date` only when a video was never live (`release_date` absent).
  1 new test with real OKC values pins the fix; the existing "imperfect
  date" test still pins the honest fallback-only case. Full suite green
  (461 tests, up from 460).

- **[Done 2026-08-12] Fixed a real Legistar bug found independently while
  verifying a Wave 2 platform-coverage research pass — Charlotte, NC (and
  likely any other Legistar instance with the same audio-download feature)
  was misclassified as a calendar page on every single-meeting URL.**
  `LegistarAssetFinder._find_video_links()` selects every `a.videolink`
  element and requires only that its onclick target contain the substring
  `"Video.aspx"` — true of all three anchors some Legistar instances render
  per real video (`Mode2=Video`, `Mode2=Audio`, `Mode2=AudioDownload`), not
  just the real video link. A single real Charlotte meeting page
  (`MeetingDetail.aspx?ID=1365278`) was therefore counted as 3 "video
  links," tripping the `len(video_links) > 1` calendar-page heuristic and
  raising `CalendarPageError` on a genuine single-meeting URL — confirmed
  live via a direct resolve before fixing. Maricopa, AZ (the original
  reference case this heuristic was built and tested against) only ever
  emits the `Mode2=Video` anchor per row, which is why this shape was never
  caught before.

  Fix: skip any candidate whose onclick target contains `Mode2=Audio`
  (matches both `Mode2=Audio` and `Mode2=AudioDownload` as a substring) —
  confirmed via a direct call against the real fetched Charlotte page that
  this correctly drops from 3 candidates to the 1 real `Mode2=Video` link.
  Maricopa's calendar page re-checked after the fix still correctly returns
  21 distinct candidates, confirming the calendar-vs-single-meeting
  distinction itself is unaffected. New fixture
  `tests/fixtures/legistar/charlotte_meeting_audio_download.html` (a real
  fetched page) plus 2 new tests: a minimal synthetic case isolating the
  three-anchor shape, and an end-to-end resolve against the real fixture
  confirming it now delegates to Granicus instead of raising
  `CalendarPageError`. Full suite green (455 tests, up from 453).

  **Real, previously-uncertain consequence this closes**: a Wave 2 research
  pass had flagged Charlotte as needing a new Cablecast adapter, based on
  a `charlotte.cablecast.tv` URL found independently of the city's own
  Legistar calendar. Live-checking Charlotte's actual calendar rows found
  they delegate to classic Granicus instead
  (`charlottenc.granicus.com/player/clip/{id}`, this app's existing,
  already-supported path) — the Cablecast site is very likely a separate
  secondary channel, not what a real pasted Legistar URL hits. With this
  bug fixed, Charlotte should already resolve correctly today without a
  new adapter; worth confirming with a real end-to-end `/api/resolve` call
  once deployed, and worth checking whether any of the *other* three
  Cablecast cities found in that pass (Detroit, Columbus, Aurora) hit this
  exact same audio-download-link shape before assuming they genuinely need
  a new adapter too.

- **[Done 2026-08-12] Fixed a real ALL-CAPS transcript on a live production
  page (Minneapolis City Council, 2026-07-16) — root-caused to stale
  pre-fix data, not a shouting-heuristic gap, and closed by building a
  missing admin capability along the way.** Checked the user's own
  reported page directly: the transcript was genuinely, fully ALL CAPS,
  and also still showed the raw pre-2026-08-10 `&amp;gt;&amp;gt;`
  double-escape artifact — proof its stored `TranscriptVersion` predated
  every relevant parsing fix (shouting-detection, marker, unescape) and
  had simply never been reprocessed, the same "old pages don't
  retroactively benefit from a parsing fix" pattern already hit for
  Dublin/Yountville.

  **Real dead ends hit trying to force a fix, each a genuine gap** (both
  still open as their own BACKLOG.md entry — this only closes the one
  specific page, not the systemic cause): an `/admin/recheck-archive-page`
  run confirmed live production re-resolves can't fetch YouTube captions
  at all (the known Render-IP block) — it refreshed the agenda/metadata
  but not the transcript; re-submitting the source URL through the normal
  public flow did nothing, since `archive_client.lookup()` short-circuits
  to a redirect before any live resolve starts; and the daily local
  `scripts/fetch_youtube_transcripts.py` script's queue only ever lists
  pages with *no* transcript, so a page with an existing-but-bad one is
  invisible to it.

  **What actually fixed this one page**: a one-off local run (residential
  IP, same requirement as the daily script) fetched the real transcript
  via `youtube-transcript-api`, correctly de-shouted and unescaped via
  the existing `snippets_to_segments()`/`unescape_caption_entities()`
  pipeline (6,577 real segments), and pushed it through the normal
  `/internal/ingest` path using the source URL's own alias to match the
  existing page. This created a second, correct `TranscriptVersion` — but
  revealed one more real gap: `promote_transcript_version()` only ever
  fires automatically from `ingest_resolution()`'s `_is_real_improvement()`
  check (no-segments/no-language cases), so a fresh, better-quality
  replacement pushed against an already-has-segments-and-language default
  had no path to become the default at all.

  **Closed that gap for real, not just for this one page**: a new
  token-gated admin action — `crud.manually_promote_transcript_version()`
  → `POST /internal/transcript-version/promote` (`archive/main.py`) →
  `archive_client.promote_transcript_version()` →
  `GET /admin/promote-transcript-version` (`app/main.py`) — mirroring the
  existing `correct-transcript-language` feature's exact chain. Built on
  its own fresh branch off `main` (not `accounts-clerk-phase1`, which had
  gone stale after an earlier squash-merge under a different commit hash
  the same day), PR #16, merged and deployed via Render's normal
  Blueprint auto-deploy (confirmed both `rtr-deeplink` and
  `rtr-deeplink-archive` live on the merge commit via the `render` CLI
  before calling the new endpoint). 9 new tests (crud-level + HTTP-level,
  mirroring the correct-language feature's existing coverage).

  **Verified end to end on the real live page**: called
  `/admin/promote-transcript-version` for the Minneapolis meeting's
  version 122, then confirmed via a direct fetch of the live page that
  its first transcript segment reads "Good morning everyone. My name" —
  the real fix, not just a passing test. Full suite green throughout
  (453 tests after the promote-endpoint addition).

- **[Done 2026-08-11] Fixed two of the three real gaps in `/meetings`'
  title/jurisdiction formatting — state abbreviations and truncation;
  casing consistency deliberately left open (see BACKLOG.md).** Reported
  by the user from a real `/meetings` screenshot: long names weren't
  truncated, casing varied row to row, and US states appeared as both
  full names and 2-letter abbreviations, with no centralized
  normalization anywhere in the codebase.

  **State abbreviation**: new `archive/utils/jurisdiction_format.py`'s
  `normalize_state_suffix()` canonicalizes a trailing full state name to
  its 2-letter code (`"San Diego, California"` → `"San Diego, CA"`),
  wired into `archive/db/crud.py`'s `_find_or_create_page()` — the single
  choke point every ingest (from every adapter) already passes through
  before a `MeetingPage` row is created or updated, so this needed no
  per-adapter changes. Deliberately narrow: only the text after the
  *last* comma is ever treated as a state candidate, so it can't misfire
  on a jurisdiction string that itself contains a comma (e.g. "Winston-
  Salem, Forsyth County, North Carolina" → "Winston-Salem, Forsyth
  County, NC", not touching "Forsyth County"). Already-abbreviated or
  state-less jurisdictions pass through byte-for-byte unchanged. 9 new
  tests (`tests/test_jurisdiction_format.py`).

  **Truncation**: `/meetings` row title and jurisdiction/date line both
  now truncate with a CSS ellipsis (`.calendar-candidate-main a` /
  `.calendar-candidate-date` in `archive/static/style.css`) instead of
  wrapping — scoped to that specific row layout, not `.calendar-
  candidate` itself, since that class is also reused unmodified by the
  resolver's calendar-picker list. Live-verified in-browser: injected a
  real long title/jurisdiction row and confirmed both ellipsis-truncate
  on one line instead of wrapping.

  **Deliberately not touched**: city/county/meeting-body name casing.
  Unlike state (~50 closed values), city/body names are effectively
  unbounded with real edge cases a blind `.title()` call gets wrong
  (acronyms, apostrophes, multi-word names) — capture-time normalization
  there risks silently and permanently corrupting a real name with no
  easy undo, so it's left as its own open item in BACKLOG.md rather than
  guessed at this pass. Full suite green (438 tests, 429 + 9 new).

- **[Done 2026-08-11] Fixed the nav flashing "Sign in" on every full page
  load for an already-signed-in visitor — reported by the user against
  `/account/saved`.** `archive/templates/base.html`'s nav always
  server-rendered "Sign in" visible-by-default regardless of a real
  server-side session; the swap to the account button only happened once
  `shared_static/clerk_nav.js` finished loading ClerkJS and checked
  `window.Clerk.user` client-side, flashing on every full navigation.
  `active_account` (`get_clerk_user_id(request)`) was already computed
  and passed into context by every route that extends this template
  (`meeting_page`/`meetings_index`/`account_saved` in `archive/main.py`)
  — the nav's initial rendered state now reads it directly (`hidden` on
  whichever element doesn't match) instead of always defaulting to
  signed-out. `clerk_nav.js` itself is unchanged, now only correcting a
  real client-side sign-in/out transition after load. Verified two ways:
  new regression tests (`tests/test_accounts_anonymous_regression.py`)
  confirming the initial HTML for both states via a monkeypatched
  `get_clerk_user_id`, and live in-browser against the anonymous case.
  Full suite green (422 tests).
- **[Done 2026-08-11] Fixed the Clerk sign-out flow landing on Clerk's own
  bare hosted page instead of this site — now live-confirmed.** Root
  cause confirmed live: at Claude's request, the user signed out on
  staging and landed on `guided-bedbug-18.accounts.dev/sign-in` (a real
  screenshot showed Clerk's own generic branding, no RTR nav/footer at
  all) — exactly the theory `BACKLOG.md` had flagged (`mountUserButton()`
  called with no `afterSignOutUrl` option, so Clerk's built-in "Sign out"
  menu item used its own default destination). Fix: `shared_static/
  clerk_nav.js`'s `window.Clerk.load()` call now passes `afterSignOutUrl`
  pointing back at the homepage. **Confirmed working 2026-08-11**: the
  user signed out for real (via their own Chrome, already-authenticated
  session) and landed on the homepage as intended — no further action
  needed.
- **[Done 2026-08-11] Made the source-transcript disclaimer's pointer to
  the real "Request Transcript from Audio" button more obvious — user
  feedback the same day the disclaimer itself shipped.** The original
  plain `<a href="#transcribeToggle">here</a>` just anchor-scrolled,
  which wasn't obvious enough that the real button lives in the other
  column. Copy now reads "...with the button to the left", and clicking
  it pops/glows `#transcribeToggle` via a new `.pointed-to` CSS animation
  (`archive/static/style.css`) wired from `meeting_page.js`'s new
  `wireSourceDisclaimerPointer()` — the "depressed vs. popped-up"
  tape-deck cue floated for the search/save-search buttons in
  `BACKLOG.md`, first real use of it. Deliberately does *not* auto-click
  the real button the way the existing `.transcribe-inline-trigger`
  warnings-text pattern does, since that would silently fire the
  feasibility check's real network request just from reading the
  disclaimer — undermining `wireTranscribeForm()`'s own deliberate
  friction. Also fixed a real pre-existing gap found while touching this:
  `archive/static/style.css` was missing `.transcribe-inline-trigger`
  entirely (present in `app/static/style.css`, the file it's supposed to
  stay in sync with), so every transcribe-inline-trigger this service
  already rendered in warnings text was unstyled. Verified live
  in-browser: clicking the link visibly lifts the button with a glowing
  border, and confirmed programmatically that the `pointed-to` class is
  added on click.
- **[Done 2026-08-11] Applied ALL-CAPS re-casing to the
  SBV/SUB/SMI/plain-.txt caption fallback, closing half of the
  "ALL-CAPS transcript display" report (see BACKLOG.md for the still-open
  half).** `normalize_shouting_caption()` (`app/utils/vtt_parser.py`)
  only ever ran on structured (VTT/SRT/TTML) cue lists via
  `parse_vtt()`/`parse_srt()`/`parse_ttml()` — `strip_unknown_caption_
  markup()` (the SBV/SUB/SMI/SAMI/plain-.txt fallback) never called it at
  all, so an ALL-CAPS track from one of those formats stayed ALL CAPS
  unconditionally. Fix: extracted the shared shouting-detection/re-casing
  check into a new `_normalize_shouting_text(text: str) -> str` helper
  (same 40-letter-sample/≤2%-lowercase-ratio heuristic, same
  `_sentence_case()`), called from both `normalize_shouting_caption()`
  (cue-list callers, refactored to use it internally) and
  `strip_unknown_caption_markup()`'s own plain-text return. Verified with
  two new fixture-backed tests in `tests/test_vtt_parser.py`: a real
  ALL-CAPS SBV-style sample correctly re-cases; a short (under the
  40-letter minimum) ALL-CAPS sample stays untouched, matching
  `normalize_shouting_caption()`'s own threshold behavior. Full suite
  green (420 tests).
- **[Done 2026-08-11] Fixed completion emails always rendering an empty
  transcript excerpt — a real bug hitting every single send.**
  `_job_dict()` (`archive/db/crud.py`) never included
  `transcript_version_id` in its returned dict, even though
  `TranscriptionJob.transcript_version_id` is set on completion
  (`report_chunk_result()`). `worker/main.py`'s `_send_completion_email()`
  looked it up via `status.get("transcript_version_id")`, always got
  `None`, and the excerpt silently stayed `""`, rendering as bare
  `&hellip;` in the email. Fix: add
  `"transcript_version_id": job.transcript_version_id,` to `_job_dict()`'s
  return dict — the data already existed on the model, it just never
  surfaced through this function. Verified by extending
  `tests/test_transcription_jobs.py`'s existing
  `test_full_chunk_lifecycle_promotes_transcribed_version` (a real,
  non-mocked completion lifecycle) with an assertion that
  `get_transcription_job_status()`'s returned `transcript_version_id`
  matches the real one — the existing mocked worker tests wouldn't have
  caught this, since they bypass `_job_dict()` entirely.
- **[Done 2026-08-11] Fixed the lifecycle email header's contrast and
  linked both "Red Tape Recordings" occurrences.** `_branded_wrapper()`
  (`archive/utils/email.py`) had the outer `<td>` in the label's own red
  (`#b71c1c`) with the inner `<span>` unstyled (just a border) — the
  reverse of the real on-site `.dymo-label` look, where a red label sits
  *inside* a separately-dark navbar and reads as a label specifically
  because of that contrast. Fix: outer cell now a dark shade matching
  `bg-dark` (`#212529`), inner span carries its own explicit `#b71c1c`
  background, and the text is real Title Case ("Red Tape Recordings")
  instead of hardcoded `RED TAPE RECORDINGS`. Both `_branded_wrapper()`
  and `_signoff_html()` now accept a `base_url` param
  (`PUBLIC_BASE_URL`), wrapping the wordmark and sign-off line in a real
  `<a href>` — both were previously plain unlinked text. Verified by
  rendering a real `send_completion_email()` call to a local HTML file
  and viewing it in-browser (no live Resend send available this
  session) — dark bar with a contrasting red label inside, both "Red
  Tape Recordings" occurrences confirmed as real `<a href>` links via
  `document.querySelectorAll('a')`. The missing `text-shadow` emboss
  effect from the real `.dymo-label` is still absent — left alone per
  the original finding, since text-shadow support across email clients
  is notoriously unreliable and not worth chasing without a client-safe
  alternative.
- **[Done 2026-08-11] Added the missing nav divider between "My Saved
  Items" and "Sign in"** — the one gap in `archive/templates/base.html`'s
  otherwise consistent divider-between-every-nav-item pattern. One-line
  fix, verified live in-browser.
- **[Done 2026-08-11] Saved-searches list now shows `has_agenda`/
  `has_transcript`/`fuzzy` alongside jurisdiction/date.**
  `archive/templates/saved_items.html`'s summary line previously only
  showed `sp.jurisdiction` and the date range, even though the saved
  link itself already correctly encoded all the filters — a viewer
  scanning their saved searches had no way to tell, at a glance, that an
  entry was (for example) filtered to "has transcript only." Display-only
  fix, verified via a `TestClient` request against a seeded `SavedItem`
  row with all three filters set (`"Testville · has transcript · has
  agenda · fuzzy"` rendered correctly), since no live Clerk session was
  available this session to click through the real page.
- **[Done 2026-08-11] Fixed `/meetings` row title wrapping wider on
  agenda-only rows than rows with a transcript badge.** The
  `.transcript-badge` span was only rendered `{% if m.has_transcript %}`,
  so an agenda-only row had no second flex child reserving that column's
  width and `.calendar-candidate-main` (and its title) expanded to fill
  the row. Fix: `meeting_list.html` now always renders the badge markup;
  a new `.transcript-badge-placeholder` class (`visibility: hidden`,
  same box dimensions) hides it visually when there's no transcript
  instead of omitting the element. Verified live in-browser, both rows'
  titles now wrap at the same right margin.
- **[Done 2026-08-11] Added a parallel disclaimer for source-provided
  (non-AI) transcripts, per direct user request.** Only
  `source="transcribed"` versions got the existing amber "AI TRANSCRIPT"
  disclaimer; `source="scraped"` (the actual value for every
  platform-provided caption) got none, despite also being unreviewed
  third-party content. Added an `{% elif active_version.source ==
  "scraped" %}` branch in `meeting_page.html` with the user's own copy, a
  distinct "SOURCE TRANSCRIPT" label, and a blue-tinted `.source-disclaimer`
  style (vs. the AI box's amber) so the two stay visually distinguishable
  at a glance — links to the existing `#transcribeToggle` button rather
  than duplicating its behavior. Verified live in-browser against a
  meeting page with a real `source="scraped"` version.
- **[Done 2026-08-11] Built the first mitigation from the Trust & safety
  threat-model section: per-page `noindex` on `generic_fallback` pages.**
  `archive/templates/meeting_page.html`'s meta block now renders
  `<meta name="robots" content="noindex">` whenever `page.platform ==
  "unknown"` (the exact `platform_name` `generic_fallback.py` registers
  under, confirmed the only adapter using that value) — stops
  search-engine amplification of the least-verified, most-open resolve
  path without blocking or gating anything. Verified live in-browser
  against both an `unknown`-platform page (noindex present) and a
  `granicus`-platform page (no robots meta at all), confirming the gate
  is real, not a blanket noindex.
- **[Done 2026-08-11] Fixed `GranicusAssetFinder._fetch_agenda_items()`
  silently discarding its own PDF-fallback link when `AgendaViewer.php`
  redirects to a *raw binary* PDF, instead of the HTML/Google-Docs-preview
  PDF the existing Berkeley/Paradise Valley AZ fallback path was built
  for.** Found live while bulk-ingesting Napa's City Council/Housing
  Authority/Measure G Granicus channel (`view_id=12`, clip 3470 and 34
  others) via `scripts/bulk_ingest.py` — every single one came back with
  `agenda_items=0` and no fallback warning either, unlike Napa's Planning
  Commission channel (`view_id=2`) resolved earlier the same session,
  which got real agenda items. Root cause: `response.text()` on a raw PDF
  raises `UnicodeDecodeError`, which was being caught by the same blanket
  `except Exception: return [], None` guarding real request failures
  (bad status/connection error) — so a 200 response with a real,
  fetchable agenda on it was treated identically to "the request itself
  failed," discarding `final_url` along with it. Fix (`app/platforms/
  granicus.py`): capture `final_url` before attempting the text read, and
  catch `UnicodeDecodeError`/`LookupError` from `response.text()`
  separately, returning `([], final_url)` — the same fallback shape the
  Berkeley/Paradise Valley case already produces. Verified live against
  the real Napa clip (agenda_items still `[]`, since there's genuinely no
  timestamped structure to parse, but `transcript_warnings` now correctly
  links the real PDF instead of saying nothing) and added a
  fixture-backed regression test (`tests/test_granicus.py`,
  `test_agenda_viewer_redirect_to_raw_pdf_surfaces_as_fallback_link`,
  using a new `FakeResponse(text_raises=...)` param in `tests/
  aiohttp_mock.py`) so this doesn't silently regress. Does **not** change
  whether these 35 meetings get ingested — they still have no transcript
  (blank captions) and no parseable chapter data, so `/api/resolve` and
  `bulk_ingest.py`'s existing "only push real content" gate correctly
  skips them either way; this only fixes what gets surfaced to a user who
  resolves one of these URLs directly instead of losing the agenda link
  entirely.

- **[Done 2026-08-10, verified end-to-end locally] Built real
  `video_warnings`/`agenda_link` support on the Archive, replacing the
  generic stand-in message shipped earlier the same day.** Corrected a
  real mistake in this item's own earlier BACKLOG.md phrasing along the
  way: it referenced `agenda_warnings`, a field that existed only
  briefly in an earlier session and was deliberately replaced by
  `agenda_link` (a raw URL, not a pre-formatted sentence) before
  anything else in the codebase started depending on it — confirmed via
  a real grep (zero occurrences of `agenda_warnings` anywhere in the
  current code) before building anything, not assumed from the stale
  note.

  Two new nullable columns on `MeetingPage`
  (`archive/db/models.py`): `video_warnings` (JSON list) and
  `agenda_link` (text). `IngestRequest` (`archive/main.py`) gained both
  fields (previously silently dropped by Pydantic on every ingest,
  since `MeetingPage` had nowhere to put them).
  `crud._find_or_create_page()` stores them with the same truthy-gated
  "keep fresh, don't blindly overwrite" semantic `agenda_items` already
  uses — deliberately not an unconditional overwrite, since a partial
  ingest payload that omits these fields entirely (e.g.
  `scripts/fetch_youtube_transcripts.py`'s transcript-only push)
  defaults to `[]`/`None` via Pydantic, and an unconditional overwrite
  would silently wipe a real warning/link a fuller earlier resolve had
  found.

  New `archive/utils/render_warnings.py` (`render_warnings_html()`) is
  the server-side Jinja2 equivalent of `shared_static/deep_link.js`'s
  `linkifyWarning()` + `player.js`'s `renderWarnings()` phrase-button
  behavior — the Archive renders warnings server-side, not via client
  JS, so it needed its own version, registered as a `warnings_html`
  Jinja2 filter (`archive/main.py`, wrapped in `Markup` so a template
  call site doesn't also need `|safe`). Applied to the existing
  `transcript_warnings` spots (previously plain `|join(" ")`, no
  linkify/button behavior at all) and the new `video_warnings` spot
  (replacing the "No video available for this meeting." stand-in when
  real warnings exist, falling back to it only when they genuinely
  don't). `agenda_link` renders as its own "We think we found an agenda
  here: `<link>`" line under the Agenda heading — the section's own
  gating condition changed from `page.agenda_items` alone to `(page.
  agenda_items or page.agenda_link)`, so the heading now appears even
  for a meeting with only a link and no real per-item timestamps,
  matching the original design intent ("own heading, not nested under
  Transcript"). `.source-guess` CSS (the deliberately-not-`.warnings`-
  styled treatment for "we think we found this" lines) mirrored from
  `app/static/style.css` into `archive/static/style.css` — didn't exist
  there before, since the Archive never had this kind of line at all.
  `archive/static/meeting_page.js` gained `wireTranscribeInlineTriggers()`,
  called before the early `if (!wrapper) return` in its
  `DOMContentLoaded` handler on purpose — the no-video case (no
  `#videoWrapper` at all) is exactly the case most likely to have the
  transcribe-request phrase in its warning text, and that early return
  would otherwise skip wiring it entirely.

  7 new tests (`tests/test_render_warnings.py`): escaping, linkifying,
  the transcribe-button wrap (case-insensitive), multi-warning joining,
  empty-list handling, and a real defense-in-depth check (escape-then-
  linkify order means injected markup in a warning string can never
  smuggle a fake link past the escaping). Migration
  (`76a4a2820a2b_add_video_warnings_and_agenda_link_to_.py`) generated
  correctly by diffing against a database first brought to the *current*
  head (`8e7cf3b20f86`), not a fresh empty one — confirms it's a real
  incremental `ALTER TABLE`, not an accidental second baseline. Verified
  upgrade/downgrade both work cleanly, and diffed the resulting schema
  against a fresh `create_all()` build: identical except column
  order (SQLite's `ALTER TABLE ADD COLUMN` always appends at the end
  regardless of where the model declares a field — a real, harmless,
  already-established pattern from every previous migration in this
  session, not a new concern). Local `archive_dev.db` (the repo-root
  file, not `create_all()`-built) stamped at `8e7cf3b20f86` then
  upgraded for real to pick up both new columns, confirmed real existing
  data (1 row) survived intact.

  **Caught two of my own mistakes while doing this, both self-corrected
  before they became real problems**: (1) generating the migration
  against a fresh empty database first, which would have produced a
  second incorrect baseline instead of an incremental diff — caught by
  reviewing the generated file by hand before trusting it, redone
  correctly against a database first brought to head. (2) Running
  `alembic` commands from inside `archive/` without an explicit
  `DATABASE_URL` twice in a row, which resolves the default relative
  `./archive_dev.db` path relative to *that* directory instead of the
  repo root — created a stray empty `archive/archive_dev.db` file (and,
  separately, an `app/dev.db` one from earlier `app/alembic` testing);
  both caught by checking file sizes/schemas before trusting them,
  neither ever touched the real data.

  Full live end-to-end verification, not just unit tests: ingested a
  real test meeting with both fields populated against a local Archive,
  viewed the rendered page through the resolver's proxy (port 8010, not
  the Archive directly on 8020 — hitting it directly 404s on
  `/archive-static/*`, the same pre-existing quirk noted earlier this
  session) — confirmed the real `video_warnings` text renders (not the
  generic stand-in), the real `agenda_link` renders as an actual
  `<a target="_blank">` under its own Agenda heading, and — the part a
  pure server-render check can't prove — clicking the inline transcribe
  phrase actually reveals the transcribe form (`form.hidden` flips from
  `true` to `false`), confirming `wireTranscribeInlineTriggers()`'s
  click wiring genuinely works, not just that the button element exists
  in the DOM. Full suite green throughout (307 tests, up from 300).
  Production still needs the real migration applied — left as a live
  `BACKLOG.md` item with the exact command, not run blind.

- **[Done 2026-08-10, confirmed in production] Built `app/alembic/`,
  mirroring `archive/alembic/`'s existing structure and conventions
  exactly, closing the gap that caused the same day's earlier
  `/admin/stats` production incident.** `env.py`/`script.py.mako` are
  near-identical adaptations (s/archive/app/ throughout — same
  `DATABASE_URL`-from-the-app's-own-engine pattern, no separate config to
  keep in sync). Generated the baseline migration
  (`ee8f7ff76fb3_baseline_schema.py`) by autogenerating against a
  genuinely empty SQLite database, same method `archive/alembic`'s own
  baseline used — correctly includes both existing tables
  (`meeting_resolutions`, `problem_reports`) with every current column,
  including the two (`archive_pushed_at`, `archive_push_attempts`) that
  caused the incident this closes.

  `alembic>=1.13` was missing from the root `requirements.txt` entirely
  — only `archive/requirements.txt` had it, since only the Archive
  service's own deploy had ever needed to run `alembic` commands from
  its Render Shell before. Added to the resolver's own `requirements.txt`
  too, or `app/alembic/` would exist in the repo but not actually be
  runnable in the resolver's production shell.

  Verified locally, same method `archive/alembic/README.md` already
  established: `alembic upgrade head` against a fresh empty SQLite
  database, diffed against a separate `create_all()`-built database —
  identical except the `alembic_version` bookkeeping table itself and
  the same cosmetic `(CURRENT_TIMESTAMP)` vs `CURRENT_TIMESTAMP`
  default-clause rendering difference already documented as harmless on
  the Archive side; `alembic downgrade base` cleanly drops both tables
  back to just `alembic_version`. Also stamped the local `dev.db` file
  at this new baseline (it already had the correct schema from the same
  day's earlier manual `ALTER TABLE` fix, confirmed before stamping, not
  assumed) — `dev.db` is gitignored, so this only fixes this one
  machine's copy; a fresh clone starts from a genuinely empty `dev.db`
  via `create_all()`, which needs no migration at all.

  **Production adoption completed the same day**, via the user's own
  Render Shell run of `app/alembic/README.md`'s documented sequence:
  `alembic current` printed nothing first (confirming the expected
  "schema correct, bookkeeping never started" state, not assumed),
  then `alembic stamp ee8f7ff76fb3` — bookkeeping-only, no DDL, since
  production's schema already matched this baseline exactly (fixed by
  hand earlier the same day) — brought it to `ee8f7ff76fb3 (head)`.
  Independently re-confirmed via `GET /admin/stats` against real
  production immediately after: `pending_archive_pushes: 0`, no error,
  same clean state as before the stamp. Unlike `archive/alembic`'s
  original adoption (which needed a real `stamp` + `upgrade` because
  production was genuinely missing a whole table), this one only ever
  needed the bookkeeping-only `stamp` — matches this repo's
  now-twice-learned lesson (Archive's own Alembic incident, then this
  same day's `app/db` one) to verify real current state before trusting
  any account of it, including this one.

- **[Done 2026-08-10, found and fixed against real production data]
  `get_pending_archive_pushes()`'s sweep query could silently miss real
  candidates.** Found while manually clearing the pending-push backlog
  the schema-fix incident (entry above) left behind — not a hypothetical,
  a real production symptom: `/admin/sweep-pending-pushes` returned `0`
  retried while `/admin/stats`' unfiltered `pending_archive_pushes` count
  still showed `10`. Root cause: the query over-fetched with
  `.limit(limit * 3)` at the SQL level, then filtered by
  `_worth_pushing()` (checks `resolved_payload["agenda_items"]`, JSON,
  not filterable portably at the SQL level) in Python afterward.
  Production genuinely has plenty of `status="success"` rows with no
  real content (`blank_transcript`/`no_video` outcomes are still
  `"success"` at the DB-status level) — when enough of those sit ahead
  of a real candidate in `created_at` order, the fixed-size over-fetch
  window can exhaust itself on non-candidates before ever reaching a
  row actually worth pushing, silently. Fixed by dropping the SQL-level
  limit entirely and filtering the full matching set in Python before
  slicing to the caller's `limit` — same "personal reporting log, a full
  scan per call is fine for now" reasoning `get_stats()` already uses
  for this table (per that function's own docstring). New regression
  test (`test_pending_pushes_finds_a_real_candidate_behind_many_
  content_free_rows`) reproduces the exact shape (15 content-free rows
  ahead of one real candidate) and was confirmed to actually fail
  against the pre-fix code (temporarily reintroduced the old `.limit(limit
  * 3)`, watched the test fail with the real candidate missing, restored
  the fix) before trusting it as a real regression guard. Verified
  against production itself, not just the test: re-ran the sweep after
  deploying the fix, found and successfully retried all 10 previously-
  hidden rows, confirmed `pending_archive_pushes` reached a genuine `0`.

- **[Done 2026-08-10, fixed live in production] Deploying the durable-push
  fix (entry below) itself broke production `/admin/stats` for a real,
  avoidable reason: `app/db` has no migration tooling, and this was its
  first-ever schema change that wasn't a brand-new table.** Real
  incident, not a hypothetical: added two new columns to the existing
  `meeting_resolutions` table, verified thoroughly against fresh local
  SQLite databases (where `create_all()` correctly creates a table with
  every current column, since there's no pre-existing schema to
  reconcile against) — but never against a database that already had the
  *old* schema, which is exactly production's situation. `create_all()`
  can only ever add new tables, never alter an existing one — the exact
  same wall `archive/db` hit three times before adopting Alembic
  (2026-08-09, see this file's earlier entries), just never hit by
  `app/db` before because it had never needed an `ALTER` until now.
  `/admin/stats` returned 503 in production (`get_stats()`'s full-table
  scan touches the new columns on every row via the ORM, failing on
  "column does not exist"); `/api/resolve` itself kept working (confirmed
  live, twice) because `log_resolution()`'s `INSERT` failure was already
  caught by the existing `safe()` wrapper, silently degrading to the old
  bare-`archive_client.push` fallback exactly as that fallback was
  designed to do — the *feature* was inert, not the *site*.

  Fixed live: gave the user a one-off `ALTER TABLE meeting_resolutions
  ADD COLUMN IF NOT EXISTS ...` (both new columns), run via the
  `rtr-deeplink` (resolver) service's Render Shell — same "Python
  one-liner via SQLAlchemy" pattern as the day's earlier Baltimore/
  Memphis one-off DB corrections, adapted to `app/db.engine` instead of
  `archive/db`. Confirmed fixed: `/admin/stats` returns 200 with the new
  `pending_archive_pushes` field.

  That field then read `30` — alarming at first glance, but explainable
  and not a new bug: every pre-existing row got `archive_pushed_at =
  NULL` by definition when the column was added (Postgres can't
  retroactively know an old push already succeeded), so every
  successful resolve from *before* this session's fix showed up as
  "pending" even though most were already real Archive pages. Manually
  triggered `/admin/sweep-pending-pushes` repeatedly to clear the
  backlog rather than waiting on organic traffic — which surfaced a
  second real bug (`get_pending_archive_pushes()`'s `limit * 3`
  over-fetch heuristic silently missing real candidates behind a run of
  content-free rows, fixed in its own entry above/nearby) before the
  count finally reached a genuine `0`.

  **Real lesson, not just this one incident**: "verified end-to-end"
  against a fresh local database is not the same claim as "verified
  against production's actual current schema" — this repo already knew
  that in the abstract (it's the whole reason `archive/db` has Alembic),
  but the lesson hadn't yet been generalized to `app/db`, which uses the
  identical `create_all()`-only mechanism and was always going to hit
  the same wall on its first real `ALTER`. Worth deciding whether
  `app/db` should get its own Alembic setup now, matching
  `archive/db/alembic/`, so a future column addition here doesn't need
  another live production incident to catch it — logged as its own live
  item in `BACKLOG.md`.

- **[Done 2026-08-10, verified end-to-end] Built the real fix for the
  silent-Archive-push-loss bug: durable push tracking plus an
  opportunistic retry sweep, instead of trusting a bare fire-and-forget
  `BackgroundTasks` call alone.** Closes out the item logged earlier the
  same day (a real LA PrimeGov/YouTube meeting that resolved with 3,101
  real segments but never reached the Archive, leading theory being a
  resolver process restart losing the in-flight background task with
  zero log trace).

  **Design**: reused `app/db/models.py`'s existing `MeetingResolution`
  table (already stores the full resolved payload for every successful
  resolve) rather than a new outbox table — added `archive_pushed_at`
  (null until a push actually succeeds) and `archive_push_attempts`.
  `crud.log_resolution()` now returns the new row's id (`flush()` before
  `commit()`); a new `_push_and_track(resolution_id, payload,
  normalized)` in `app/main.py` wraps `archive_client.push()` (which now
  returns `bool` instead of bare `None`) and marks the row pushed on
  success or records a failed attempt otherwise. Both places that fire a
  background push — the fresh-resolve success path and the cache-hit
  opportunistic-push path — now go through this wrapper instead of
  calling `archive_client.push` directly (the fresh-resolve path falls
  back to the old bare-push behavior only if `log_resolution` itself
  failed, i.e. `resolution_id is None`, since there's nothing to track
  against in that case). `crud.get_cached_resolution()`'s return shape
  changed from a bare payload dict to `{"resolution_id", "payload"}` so
  the cache-hit path has an id to track against too; both call sites in
  `app/main.py` updated.

  **The actual retry mechanism**: `crud.get_pending_archive_pushes(min_age_minutes,
  limit)` finds rows with real content (`transcript_found` or
  `resolved_payload["agenda_items"]`), `status == "success"`,
  `archive_pushed_at IS NULL`, under `MAX_ARCHIVE_PUSH_ATTEMPTS` (5,
  after which a permanently-broken payload stops being retried but stays
  visible), older than a grace period (default 5 minutes — deliberately
  excludes a just-created row, so the sweep never races the normal fast
  path seconds after a response returns). This app has no background job
  queue by design (per CLAUDE.md), so the sweep isn't a real scheduler:
  `_maybe_schedule_push_sweep()` is an in-memory time-gated check fired
  opportunistically at the top of every `/api/resolve` call, the same
  pattern `ARCHIVE_RECHECK_AFTER`'s stale-page recheck already uses —
  fine for a single-instance deploy, not a distributed-lock guarantee.
  New `GET /admin/sweep-pending-pushes` (token-gated, matching
  `/admin/recheck-archive-page`'s shape) triggers and awaits the same
  sweep synchronously, for checking on or forcing it directly.
  `crud.get_stats()` gained a `pending_archive_pushes` count (no
  age/attempts filtering, unlike the retry-candidate query — a
  visibility count should still surface a row past the retry cap) so
  `/admin/stats` finally has something to show for this failure mode,
  directly closing the "even monitoring wouldn't catch this" gap the
  original report identified.

  **Verification**: `tests/conftest.py` now also initializes `app/db`'s
  schema (it shares `DATABASE_URL` with `archive/db`, just never had its
  own tables created in the test fixture before). 18 new tests across
  `tests/test_app_db_crud.py` (grace period, content-free/agenda-only/
  non-success exclusions, max-attempts cutoff, the cache shape change,
  the stats count) and `tests/test_archive_push_tracking.py`
  (`_push_and_track`/`_sweep_pending_archive_pushes` success and failure
  paths via a monkeypatched `archive_client.push`, the admin endpoint's
  token gating and real behavior, the sweep gate not double-scheduling).
  Then a full live end-to-end run, not just unit tests: started the
  resolver pointed at a deliberately unreachable Archive URL, resolved
  the real Baltimore meeting from the original report — confirmed the
  push failure was correctly recorded (`pending_archive_pushes: 1`,
  `attempts: 1`) — pointed the resolver at a real local Archive,
  backdated the row past the grace period, called `/admin/sweep-pending-
  pushes` for real, and confirmed the retry succeeded: the pending count
  dropped to 0 and the meeting genuinely appeared in the local Archive's
  `/meetings` search. Full suite green throughout (299 tests, up from
  281); also fixed the same `load_dotenv()`-as-import-side-effect test
  flake found earlier the same day (see the entry below), this time
  triggered by the new push-tracking test file importing `app.main` —
  moved both `ARCHIVE_INGEST_TOKEN` and `ADMIN_STATS_TOKEN` test
  defaults into `conftest.py` itself (guaranteed to run before any test
  module's own import), a permanent fix rather than patching each
  affected file's import order individually.

- **[Done 2026-08-10] `scripts/fetch_youtube_transcripts.py` now emails a
  report after every real run — every transcript actually added, plus
  a distinctly different alert if the run fails to complete.** Reuses
  the Archive's existing Resend integration (`archive/utils/email.py`)
  rather than building a second one-off implementation — same
  `RESEND_API_KEY`/`RESEND_FROM_ADDRESS` the Archive service already
  has. Two new functions there: `send_youtube_transcript_report()`
  (lists every ingested meeting with a real clickable link built from
  `PUBLIC_BASE_URL`, not the Archive's own internal `ARCHIVE_BASE_URL`
  — plus skipped/failed counts — sent on *every* normal completion,
  even an empty one, so silence itself becomes a signal the daily
  `launchd` job stopped firing rather than reading as "nothing new
  today") and `send_youtube_transcript_failure()` (a different subject/
  shape, sent when the run doesn't complete normally at all — an
  IP-level block aborting mid-run, missing `ARCHIVE_BASE_URL`/
  `ARCHIVE_INGEST_TOKEN`, or any unhandled exception). Recipient
  defaults to `ryan@how-to-adu.com`, overridable via
  `YOUTUBE_FETCH_REPORT_EMAIL`. Titles/slugs/error text are
  `html.escape()`d before insertion, since they ultimately trace back
  to scraped government page content. `--dry-run` sends no email
  either way, matching its existing "preview only" contract.

  The whole body of `main()` now runs under one try/except specifically
  so every real failure mode reaches the alert path, not just the
  already-handled IP-block case — confirmed no regression to the
  existing per-video "failed" vs. fatal-abort distinction (an
  individual video failing to fetch still just shows up in the normal
  report's failed list; only a run that can't complete at all triggers
  the separate alert). Verified for real, not just via the return
  value: called both new email functions directly with real
  `RESEND_API_KEY`, confirmed `True` from both, and a real end-to-end
  script run (fresh local Archive, one queued page, non-dry-run) that
  successfully sent the report as its very last step with no exception.

- **[Done 2026-08-10] `scripts/fetch_youtube_transcripts.py` runs
  automatically once a day now, via a `launchd` job on the user's Mac
  (`scripts/com.redtaperecordings.fetch-youtube-transcripts.plist`,
  checked into the repo for documentation/reinstall, actually installed
  at `~/Library/LaunchAgents/`).** Must run on the user's own machine,
  not Render — the whole reason this script exists is that YouTube
  blocks caption fetches from Render's cloud IP (see the entry below).
  Daily at 9:00am, `RunAtLoad` deliberately `false` so it only fires on
  the schedule (LaunchAgents auto-load at every login, which would
  otherwise add extra runs beyond the intended cadence); if the Mac is
  asleep at the scheduled time, macOS runs it after the next wake rather
  than skipping it. Output goes to `~/Library/Logs/fetch-youtube-
  transcripts.log`. Verified for real: `launchctl load`, then `launchctl
  start` to fire it immediately without waiting for the schedule,
  confirmed the log file was written with the script's real output
  ("Transcript-wanted queue is empty -- nothing to do," correct since
  the one real queued page had just been drained manually). The plist's
  own header comment documents install/test/uninstall commands so this
  doesn't depend on tribal knowledge.

  Also ran the script for real against production for the first time
  (prompted by verifying the new timing output below): the queue had
  exactly one real page waiting — Minneapolis's BHZ committee meeting —
  fetched and pushed successfully, 3,377 real segments with clean
  speaker markers, now live at `/m/city-of-minneapolis-2026-07-07-
  business-housing-zoning-committee`.

- **[Done 2026-08-10] Per-video timing added to `scripts/fetch_youtube_transcripts.py`,
  which surfaced and fixed a real, order-dependent test flake.** User
  asked how long a run would take for several long meetings -- answer
  ("seconds each, independent of meeting length, since this fetches an
  already-generated caption track in one API call rather than processing
  audio") is now printed directly (wall-clock timestamp + per-item
  elapsed + a final total/average) instead of just asserted. While
  verifying the new output, `tests/test_transcript_wanted.py::
  test_transcript_wanted_route_returns_queue` started failing, but only
  when run alongside `tests/test_fetch_youtube_transcripts.py` --
  isolated, it passed. Root cause: that new test file imports
  `snippets_to_segments` from the script for pure-function testing, and
  the script had a module-level `load_dotenv()` call as an import side
  effect -- when pytest happened to collect that file first (alphabetical
  order put `test_fetch_...` before `test_transcript_...`), it loaded the
  repo's real local `.env` (including the real `ARCHIVE_INGEST_TOKEN`)
  into the environment before `test_transcript_wanted.py`'s own
  `os.environ.setdefault("ARCHIVE_INGEST_TOKEN", "test-token")` line ever
  ran -- `setdefault()` is a no-op once a real value already won the
  race, so the test's requests using `Bearer test-token` got a real 404
  against the real token instead of the isolated test one. Fixed by
  moving `load_dotenv()` out of module scope and into the `if __name__ ==
  "__main__":` guard -- the only code path that actually needs real env
  vars (`main()`'s `_base_url()`/`_headers()` calls) already lives behind
  that same guard, so this is a pure side-effect removal, not a behavior
  change for real script runs (re-verified: `--dry-run` against
  production still resolves `ARCHIVE_BASE_URL`/`ARCHIVE_INGEST_TOKEN`
  correctly). `scripts/bulk_ingest.py` has the identical top-level
  `load_dotenv()` pattern but has never been imported by a test file, so
  it was never exposed to this same race -- worth keeping in mind if it
  ever becomes importable too.

- **[Done 2026-08-10, verified end-to-end] Built the YouTube transcript
  recovery pipeline: a "transcript wanted" queue on the Archive plus a
  local residential-IP fetcher script — after a deliberate experiment
  killed the last hope of fetching server-side.** Closes out the
  2026-08-09 "Minneapolis LIMS resolves failing at the YouTube step"
  production incident (degrade-gracefully fix confirmed working in
  production 2026-08-10: the user's own BHZ/6105→6073 tests rendered
  video + LIMS's real metadata/agenda with the transcript honestly
  absent) and replaces that item's open "options for the IP block not
  yet evaluated" tail with a decided, built answer.

  **The experiment (analysis option b5)**: before building anything,
  tested whether YouTube's InnerTube `get_transcript` endpoint — a
  genuinely different endpoint from the already-blocked timedtext URLs
  and yt-dlp's player API — escapes the cloud-IP block. Hand-rolled
  calls failed `FAILED_PRECONDITION` even from a residential IP with
  the watch page's own full `INNERTUBE_CONTEXT`, cookies, and the
  page-embedded `params` (extracted from a real watch page's
  `ytInitialData`); rather than reverse-engineer further, switched to
  `youtube-transcript-api` (the maintained library that already solves
  the current attestation recipe): **locally it works perfectly** —
  1,556 real segments for the real Minneapolis video `YgAu_4xWvGU`,
  including the *human-typed* CC1 track (real `>>` speaker markers),
  not just auto-captions — **and from Render's shell the identical
  call raises `IpBlocked`** (the library's own cloud-provider-IP error,
  run by the user directly). Also re-confirmed in passing:
  `get_video_info` (the classic StackOverflow-era trick) returns HTTP
  410 Gone, and the official Data API's `captions.download` requires
  the video owner's OAuth — neither is a path. Conclusion: fetching
  must happen off-server, full stop.

  **The build**: `crud.list_youtube_pages_missing_transcripts()` +
  token-gated `GET /internal/transcript-wanted` on the Archive — every
  YouTube-backed `MeetingPage` with no `is_default=True`
  `TranscriptVersion` ("no default" rather than "no rows," so a page
  whose only version was demoted as a copied agenda is re-fetchable
  too), returning exactly the identity fields `_find_or_create_page()`
  needs to match the existing page on push (platform, external_id,
  source_url_normalized). `scripts/fetch_youtube_transcripts.py`
  (same shape as `bulk_ingest.py`: local `.env`, `--dry-run`,
  `--limit`, per-item results + totals) drains the queue via
  `youtube-transcript-api` and pushes through the normal
  `/internal/ingest` — idempotent by the existing content-hash dedupe.
  Conversion details that came from the real data: blank timing-padding
  snippets dropped; leading real `>>` becomes the site's `»` marker
  (the existing `normalize_speaker_change_marker()` handles the
  *literal-entity* `&gt;&gt;` case, a different artifact); the whole
  track reuses `normalize_shouting_caption()` for ALL-CAPS CC tracks,
  plus an explicit capitalize-after-`»` pass since sentence-casing
  can't see through the marker prefix. 5s inter-video delay (gentler
  than bulk_ingest's 1.5s — these hit YouTube from the operator's own
  home IP, which the library warns can also get temporarily blocked);
  an `IpBlocked`/`RequestBlocked` aborts the whole run instead of
  burning the queue on identical failures. `youtube-transcript-api`
  added to `requirements-dev.txt` only, deliberately not
  `requirements.txt` — useless on the deployed services' blocked IPs.

  **Verification**: 12 new tests (`tests/test_transcript_wanted.py`:
  queue includes a transcriptless YouTube page / excludes one with a
  transcript / excludes non-YouTube pages / route token-gating;
  `tests/test_fetch_youtube_transcripts.py`: snippet conversion incl.
  blank-drop, marker replacement, de-shout, mid-text `>>` untouched),
  plus a real end-to-end run against a local Archive: ingested a
  transcriptless YouTube page, confirmed it appeared in the queue, ran
  the script for real (real YouTube fetch, 1,555 segments), confirmed
  the transcript landed on the same page (no duplicate), the queue
  drained to empty, and the rendered page shows clean de-shouted text
  with `»` markers — visibly better output than the pre-block scraped
  version of the same video (which has rolling-duplicate lines and raw
  `&gt;&gt;` artifacts). Follow-ups (actually running it against
  production, automating it, the no-captions Whisper fallback) tracked
  as a live BACKLOG.md item.

- **[Done 2026-08-10, verified live] YouTube-embedded meetings' `t=`
  deep link silently landed at 0:00 instead of the requested moment.**
  Reported live by the user on a real Minneapolis LIMS/YouTube meeting
  (`.../meeting?url=https://lims.minneapolismn.gov/MarkedAgenda/BHZ/6073&t=1168`),
  alongside a UX question about whether the "no transcript, but we're
  tracking the playhead" copy was overpromising given the seek didn't
  actually work. Root cause: both `initYouTubeVideo()` (`app/static/
  player.js` and `archive/static/meeting_page.js`) constructed the
  `YT.Player` bare (just `videoId`, cued at 0), then called
  `applyDeepLink()` in `onReady`, which sets `video.currentTime = t` ->
  `ytPlayer.seekTo(t, true)`. That's a well-known YouTube IFrame API
  race: a `seekTo()` issued immediately after `onReady`, before any
  buffering or user interaction, doesn't reliably stick.

  Fix: a new shared `buildYouTubePlayerVars(baseVars)` in
  `shared_static/deep_link.js` folds the current deep-link time in as
  `playerVars.start` (rounded down) at player *construction* time, which
  YouTube treats as part of the initial load/cue itself rather than a
  race-y follow-up call -- both `player.js` and `meeting_page.js` now
  call it instead of duplicating the same inline logic (matches this
  file's whole reason for existing: shared deep-link mechanics kept in
  one place, not copy-pasted twice). `applyDeepLink()` still runs
  unchanged in `onReady` for the line-only case (no `t`) and for
  highlighting the matching transcript/agenda row -- its own `seekTo()`
  call in the `t`-present case is now redundant but harmless, since the
  position is already correctly cued by then.

  Verified two ways: (1) three new `tests_js/deep_link.test.js` cases
  for `buildYouTubePlayerVars` (folds `t` in as `start`, rounds down;
  omits `start` entirely with no `t`; doesn't mutate the caller's base
  object) -- sanity-checked real by temporarily disabling the fix and
  confirming exactly 1 test fails, 25/26 still passing. (2) Live in a
  real browser against local dev servers for *both* pages: the
  resolver's ephemeral `/meeting` page (a fresh, never-archived
  `youtube.com/watch?v=YgAu_4xWvGU` resolve) and the Archive's permanent
  `/m/{slug}` page (a locally-ingested test meeting, reached through the
  resolver's proxy so `/archive-static/*` resolves correctly -- hitting
  the Archive service directly 404s on that path, a known pre-existing
  quirk, not new). Both real rendered `<iframe>` `src` attributes
  contained the requested `start=` value exactly
  (`.../embed/YgAu_4xWvGU?...&start=1168...` and `...&start=2500...`
  respectively) -- direct proof YouTube received the correct starting
  position at construction time, not just a passing unit test. Full
  Python suite unaffected (268 tests, no Python code touched); full JS
  suite green (26 tests, up from 23).

- **[Done 2026-08-10, confirmed in production] Alembic one-time production
  adoption incident: my own instructions, based on a stale doc, pushed
  production's migration bookkeeping backward instead of forward.**
  `archive/alembic/README.md` claimed production had never been stamped
  and gave a fixed recovery recipe (`stamp a8dc5aad7eff` then `upgrade
  head`) to run unconditionally. That claim had gone stale without the
  doc being updated — a real `alembic current` run in the user's Render
  shell showed production was *already* correctly at `8e7cf3b20f86`
  (head) before any of that recipe ran, almost certainly because someone
  had already recovered from the original 2026-08-09 stamp-head incident
  (see that entry) without updating this doc to match. Following the
  stale recipe anyway force-stamped production backward to the baseline
  revision, then the redundant `alembic upgrade head` correctly failed
  with `DuplicateColumnError` on `transcription_jobs.priority` (it
  already existed) — caught immediately, not silently, and no DDL
  actually ran (transactional, rolled back cleanly) — but it left the
  bookkeeping row one step behind reality until corrected.

  Real fix, in two parts: (1) `archive/alembic/README.md`'s one-time
  adoption section rewritten to require running `alembic current` first
  and branching on its actual output, instead of presenting a fixed
  narrative as fact — the doc itself now says explicitly not to trust
  its own account of "what production's state is" without checking.
  (2) The user ran the actual correction from the Render shell:
  `alembic stamp 8e7cf3b20f86` (bookkeeping-only, no DDL) followed by
  `alembic current`, confirming `8e7cf3b20f86 (head)`. Independently
  re-confirmed via the new `GET /internal/schema-info` endpoint (see
  below) hit directly against real production: `alembic_version:
  "8e7cf3b20f86"`, `mismatched_tables: []`, `schema_matches_models:
  true` — the real schema and the bookkeeping now agree, checked two
  different ways.

  **The broader lesson, not just this one file**: a doc's account of
  live infrastructure state is a snapshot from whenever it was last
  written, not a live fact — verify against the real thing before acting
  on it, the same "verify against the real thing" convention this repo
  already applies to adapters and sample data. Directly prompted building
  `/internal/schema-info` (below) so that verification is a real API call
  going forward, not a manual command someone has to run and paste back.

- **[Done 2026-08-10] Added `GET /internal/schema-info` (`archive/main.py`)
  so confirming the Archive's real production DB schema no longer
  requires someone with `DATABASE_URL` access to run `psql`/`alembic`
  commands by hand and paste the output back.** Directly prompted by the
  Alembic incident just above/nearby: a stale doc's account of
  "production has never been stamped" turned out to be wrong, and acting
  on it without checking first caused a real (contained) mistake. This
  endpoint gives a way to check the real, live state directly instead.
  Token-gated the same way as every other `/internal/*` route (bearer
  token matching `ARCHIVE_INGEST_TOKEN`, 404 not 401/403 on a missing/
  wrong token). Reflects actual live columns per table via SQLAlchemy's
  `Inspector` against a real connection, next to what `archive/db/
  models.py`'s `Base.metadata` currently expects, and reports any
  mismatch directly (`mismatched_tables`, `schema_matches_models`) --
  deliberately treats the *actual reflected schema* as ground truth, not
  `alembic_version`'s own bookkeeping row (still reported, as context
  only), since it was exactly that bookkeeping row going stale that
  caused the incident this exists to prevent a repeat of. Three new
  tests (`tests/test_schema_info_endpoint.py`, matching the existing
  `test_correct_language_endpoint.py`'s pattern): missing-token and
  wrong-token both 404, and a real call against the test suite's own
  isolated SQLite DB confirms `mismatched_tables == []` /
  `schema_matches_models is True` when the DB genuinely matches the
  models (which it always does in a `create_all()`-built test DB).
  Documented in `README.md`'s "Permanent pages" section, including that
  this route is deliberately not one of the paths `redtaperecordings.com`
  proxies through (only `/m/*`/`/archive-static/*` are) -- it's only
  reachable at the Archive service's own base URL directly.

- **[Done 2026-08-10] Minneapolis LIMS URLs for any committee other than
  City Council failed with "Could not find a meeting id in this LIMS
  URL," never reaching video/agenda resolution at all.** Reported live
  by the user with a real URL: `https://lims.minneapolismn.gov/
  MarkedAgenda/BHZ/6105` (Business, Housing & Zoning committee). Root
  cause: `app/platforms/lims.py`'s `_ID_RE = re.compile(r"/MarkedAgenda/
  CI/(\d+)")` hardcoded the literal committee code `CI` (City Council --
  the only committee the adapter had been built/tested against, matching
  `tests/test_lims.py`'s own fixture URL) instead of treating that path
  segment as a variable. Confirmed the numeric id is the only part any
  downstream step actually uses -- `json_url = f".../MeetingYoutubeVideo/
  {meeting_id}"` takes just the number, no committee code at all -- so
  the fix is a general `[A-Za-z]+` match on that segment (`_ID_RE =
  re.compile(r"/MarkedAgenda/[A-Za-z]+/(\d+)")`) rather than trying to
  enumerate every real Minneapolis committee code. New regression test
  (`test_resolve_works_for_a_non_ci_committee_code`) resolves the real
  reported BHZ URL end-to-end through the existing mocked fixtures,
  confirming it now succeeds the same way the CI case always did. Could
  not get a fresh live fetch of the real BHZ page directly during this
  session (LIMS's Cloudflare protection blocked a plain `curl`, and the
  in-session browser tool was intermittently unavailable) -- confidence
  here instead comes from the user's own real report (the exact URL and
  exact failure message), plus the fact that no downstream code path
  touches the committee-code letters at all, so broadening the match is
  safe by construction, not a guess.

- **[Done 2026-08-10, confirmed in production] Production incident: the
  `worker` service crashed outright at startup** (`Exited with status 1
  while running your code`, `ModuleNotFoundError: No module named
  'playwright'` — a real Render worker crash log, not a hypothetical).
  Cause: `worker/main.py` imports `app.platforms` for fresh `video_url`
  re-resolution before each transcription chunk, which registers every
  adapter including `LimsAssetFinder`/`SlcAssetFinder` — both import
  `app/platforms/headless_browser.py`, which had a top-level `from
  playwright.async_api import ...`. `playwright` is deliberately absent
  from `worker/requirements.txt` (kept lean on purpose, per that file's
  own comment) — this app/worker requirements split predates the
  playwright-dependent LIMS/SLC adapters, and wasn't reconciled when
  they were added, so just importing `app.platforms` took down the
  *entire* worker process, not just LIMS/SLC-related jobs.

  Fix (`app/platforms/headless_browser.py`): made the playwright import
  lazy (`try`/`except ImportError`, sentinel `None`), so
  `register_all_finders()` always succeeds regardless of whether
  playwright is installed — only a resolve that actually needs a real
  browser now fails, with the same clean `HeadlessBrowserUnavailable`
  message as the missing-binary case, not a whole-service outage.
  Verified locally at the time by simulating a playwright-less import
  environment; **confirmed against the real production deploy 2026-08-10
  per the user** ("worker looks like it was running great all night") —
  no crash-loop, stayed up overnight.

  **Real, deliberate decision, not an accident: the worker will NOT get
  playwright/Chromium added, for now.** The obvious next question —
  "just add it to `worker/Dockerfile` too" — was checked for real
  tradeoffs rather than assumed safe. Measured directly (real Playwright
  launch + a real fetch of the actual Minneapolis LIMS Cloudflare-
  challenge page): Chromium's *own subprocess tree* (separate from the
  Python process, purely additive to total container memory) uses
  ~266MB just launched with no page loaded, ~535MB after actually
  loading that real page. `headless_browser.py` keeps one shared browser
  alive for the whole process lifetime (launched once, reused) — fine
  for the resolver web service, but on this worker the whisper model is
  *also* loaded for the whole process lifetime, so that ~266MB becomes a
  permanent tax on top of it, and a LIMS/SLC job's per-chunk re-resolve
  overlapping with active whisper inference on `standard`'s 2GB plan
  works out to roughly `1421MB (whisper, 900s chunk) + 535MB (Chromium
  mid-fetch) ≈ 1956MB` — only ~92MB under the ceiling, a thinner margin
  than the ~600MB that was already proven too tight once (two real OOM
  crashes) before this same plan was sized. **Decision (2026-08-09):
  leave the gap as-is** — a transcription job for a LIMS/SLC meeting
  fails cleanly (no browser available) rather than risking a third OOM
  crash for a platform combo no real request has hit yet. Per the user:
  revisit as a natural follow-on next time the worker's Render plan is
  upgraded anyway (for this or any other reason) — not worth a dedicated
  plan bump on its own just for this.

- **[Done 2026-08-10] Added the first automated test coverage for
  `shared_static/deep_link.js`'s `t`/`line`/`version` contract — deep
  linking is the entire reason this repo exists, and it had zero
  regression protection before this.** Every prior verification of this
  file's behavior, including the version-mismatch precedence fix itself,
  was manual/in-browser or a throwaway one-off Node script (see the
  deep-link versioning entry above/nearby) — a real regression (`line`
  regaining precedence over `t`, the version-mismatch fallback silently
  breaking) would only ever have been caught by live-testing, same gap
  the Python `pytest` suite already closed on that side.

  New `package.json` (repo root, `type: "commonjs"`) + `tests_js/` — the
  first JS tooling this repo has needed. Uses Node's built-in test runner
  (`node --test`, no test-framework dependency) plus `jsdom` (the one
  real devDependency, needed for `document`/`window`/`URLSearchParams`/
  `history.replaceState`, all of which `deep_link.js` uses directly).
  `tests_js/helpers.js`'s `makeWindow()` loads the real file into a fresh
  `jsdom` window as an actual appended `<script>` element, not
  `vm.runInContext` or `eval()` — deliberately reproducing the same
  "separate classic `<script>` tags share top-level `let`/`const`
  bindings" behavior that mattered when this file was first split out of
  `player.js`/`meeting_page.js` (a plain `eval()` creates its own nested
  lexical scope and would silently misrepresent this). Function
  declarations (`getDeepLinkTime`, `applyDeepLink`, etc.) land on
  `window` this way and are called directly in tests; the module-level
  `let segments` does not (per spec, unlike function declarations,
  `let`/`const` never become properties of the global object) —
  `setSegments()` reaches it the same way real callers do, via a second
  appended `<script>` doing a bare (no `let`/`const`) assignment into the
  shared scope.

  23 tests across `getDeepLinkTime`/`getDeepLinkLine`/`getDeepLinkVersion`/
  `updateUrlParams`/`findActiveSegment`/`highlightSegment`, plus the full
  `applyDeepLink` contract: the same 9 cases originally checked manually
  (t-always-wins-the-seek with a trustworthy line present, version-match,
  version-mismatch-with-t falling back to time-proximity not the stale
  line, version-mismatch-with-no-t leaving playback untouched, no-version-
  on-either-side trusting `line` — including the resolver's page
  specifically, which has no version concept at all even if a shared URL
  happens to carry a stray `version` param). Sanity-checked the suite is
  real, not tautological: temporarily short-circuited the `t`-always-wins
  branch in `deep_link.js`, confirmed exactly the 2 tests exercising it
  failed (21/23 still passing), reverted, confirmed clean 23/23 again.
  `README.md`'s "Running tests" section documents `npm install && npm
  test` alongside the existing `pytest` instructions. `node_modules/`
  added to `.gitignore`; `package-lock.json` committed for reproducible
  installs. Full Python suite unaffected (264 tests, pure test-only
  addition, no application code touched).

- **[Done 2026-08-10, partial] Archive's `meeting_page.html` no longer
  shows a silent empty gap when a meeting has no video at all.** One of
  three real bugs the resolver-side "Live-tested the generic fallback"
  entry (below) found and fixed was an invisible `video_warnings`
  message when no video was found — this mirrors that fix's *spirit*
  server-side, not the full fix. When `page.video_url` is falsy, the
  video column now shows a plain `<div class="warnings">No video
  available for this meeting.</div>` instead of rendering nothing at
  all between the title and the "Report a problem"/"Request Transcript"
  buttons, which previously left a reader guessing whether that gap was
  a bug. **Deliberately not the real fix** — the resolver shows the
  actual, specific per-meeting reason (e.g. "No video link found on this
  Legistar page." or one of `generic_fallback.py`'s tentative "we think
  we found..." messages); the Archive can't yet, because `MeetingPage`
  has no column to store that text in and reaching that requires a real
  Alembic migration + a production DB-access step this session doesn't
  have (split back out as its own live item in BACKLOG.md, along with
  the still-unaddressed agenda-link and transcribe-button-phrasing parts
  of the same original gap). Verified live against the local archive dev
  server (port 8020): POSTed a real `/internal/ingest` payload with no
  `video_url` but real `agenda_items`, confirmed the fallback message
  renders correctly in-browser with no crash, both `#videoColumn`'s
  layout and the existing "Report a problem"/"Request Transcript"
  buttons unaffected. Full suite green (264 tests, no Python logic
  touched — template-only change).

- **[Done 2026-08-10] Viebit/NYCC meetings now resolve `jurisdiction` to
  "New York City, NY" (the city+state format most other platforms use),
  not "New York City Council" (a legislative body name).** Not a
  correctness bug exactly — `LegistarAssetFinder._extract_page_meeting_
  info()` was deliberately extracting the real legislative body name from
  the Legistar page's own `<title>` tag — but the wrong shape for this
  app's convention (Swagit's `f"{city}, {state}"`, PrimeGov's "City of X"
  fix). Took the hardcode option the live item laid out rather than
  trying to generalize "extract the city, not the body name" from a
  single confirmed sample: `ViebitAssetFinder` (`app/platforms/viebit.py`)
  is confirmed used only by NYC Council, so a `_JURISDICTION = "New York
  City, NY"` class constant, set directly on every `ResolvedMeeting` it
  returns, is the narrow, accurate fix — matches this repo's "narrow fix
  until real examples exist" convention (see the `collect_edge_case_urls`
  memory). Setting it in `viebit.py` itself (not `legistar.py`) also fixes the
  Legistar-delegated path for free: `legistar.py`'s primary override
  path does `resolved.jurisdiction = resolved.jurisdiction or
  page_info["jurisdiction"]`, so once Viebit's own resolve() always
  returns a truthy jurisdiction, the Legistar page title's "New York City
  Council" never gets a chance to overwrite it via that `or`. Two
  existing `tests/test_legistar.py` assertions (`result.jurisdiction ==
  "New York City Council"` and `is None`) updated to the new, correct
  expected value; `tests/test_viebit.py`'s real end-to-end NYC Council
  fixture test gained a `result.jurisdiction == "New York City, NY"`
  assertion. Full suite green (264 tests).

- **[Done 2026-08-10] Transcripts no longer show a raw `&gt;&gt;` encoding
  artifact in place of a clean speaker-change marker.** Confirmed root
  cause 2026-08-09: YouTube's own raw auto-caption VTT source contains
  the *literal* 8-character string `&gt;&gt;` as real cue text at the
  start of a new speaker's first cue (not an actual `>` character this
  app was mis-escaping) — this app's rendering was doing the technically
  correct, safe thing with that literal text (escaping the `&` for safe
  HTML output), the ugliness was a display/polish gap, not a correctness
  or security bug. New `normalize_speaker_change_marker()` in
  `app/utils/vtt_parser.py`, called from `parse_vtt()` right after the
  existing `normalize_shouting_caption()` call — matches only the exact
  literal `^&gt;&gt;\s*` prefix (anchored to the very start of a cue's
  text, deliberately not a general entity-decoding pass) and replaces it
  with a real, inert Unicode marker (`»`, U+00BB) instead of stripping
  the "new speaker" signal outright. Placed in the shared `parse_vtt()`
  (used by every platform that funnels through it, not just YouTube's
  own adapter) rather than `youtube.py` specifically, which also settles
  the live item's open "not yet checked whether this shows up on a
  non-YouTube source" question — since the fix lives in the shared
  parser, any source that happens to hit the same artifact is already
  covered without needing a second confirmed sample first. `parse_ttml()`
  deliberately left untouched — TTML/XML text goes through
  `ElementTree.itertext()`, which already resolves real XML entities
  during parsing, so a literal `&gt;&gt;` artifact can't arise there the
  same way. Two new regression tests in `tests/test_vtt_parser.py`: one
  end-to-end through `parse_vtt()` confirming the real YouTube-shaped
  input renders as `» Welcome everyone...`, one directly against
  `normalize_speaker_change_marker()` confirming a mid-text `&gt;&gt;`
  (not at the very start of a cue) is deliberately left untouched, so a
  caption that legitimately mentions an ampersand or angle bracket
  elsewhere never gets a second, unintended round of interpretation.
  Full suite green (264 tests, up from 262).

- **[Done 2026-08-12] Generalized the double-escaping fix above to every
  remaining case it deliberately left open — mid-cue `&gt;&gt;`, any
  other pre-escaped HTML entity, and the entire text-fallback caption
  path.** The narrow fix's own docstring flagged exactly what it wasn't
  covering: `&gt;&gt;` appearing mid-cue rather than at cue start; other
  entities (`&amp;`, `&#39;`, `&lt;`, `&quot;`, `&nbsp;`) arriving
  pre-escaped in source caption text; and `strip_unknown_caption_markup()`
  (the SBV/SUB/SMI/SAMI/plain-.txt fallback), which had no cue-level text
  normalization of any kind. New `unescape_caption_entities()` in
  `app/utils/vtt_parser.py` runs a real `html.unescape()` pass, called
  last in `parse_vtt()` — after `normalize_speaker_change_marker()`, so
  the start-of-cue case still becomes the real `»` glyph exactly as
  before, and only whatever's left (mid-cue occurrences, other entities)
  gets the general unescape — and last in `strip_unknown_caption_markup()`
  too, deliberately *after* its tag-stripping regex runs, so a caption
  that legitimately meant an already-escaped fake tag as literal text
  (e.g. `&lt;i&gt;`) can't unescape into something that regex would then
  wrongly strip.

  Confirmed safe against the original narrow fix's own stated risk
  (broadly unescaping could misfire on a caption that legitimately
  contains a bare `&`/`<`/`>`): `html.unescape()` only ever converts text
  already shaped like a real entity reference (`&name;`, `&#NNN;`, or the
  handful of legacy semicolon-less named entities HTML5 still
  recognizes) — a literal, non-entity `&` (e.g. "Bed & Breakfast") isn't
  that shape and passes through untouched; a new test asserts exactly
  this. Whatever comes out still goes through Jinja's normal autoescape
  before reaching the page, so a real `<`/`>`/`&` this surfaces displays
  as safe literal text, never interpreted as markup.

  6 new tests in `tests/test_vtt_parser.py`: mid-cue `&gt;&gt;` plus
  `&amp;`/`&quot;`/`&#39;` all unescaping correctly; a literal ampersand
  staying untouched; the start-of-cue-marker-then-mid-cue-entity case
  end-to-end through `parse_vtt()`; the fallback path unescaping
  `&amp;`/`&quot;`; and the tag-stripping-order safety case above. Full
  suite green (443 tests, up from 438).

- **[Done 2026-08-10] `/meetings` results now break the jurisdiction/date
  onto its own line under the title, instead of running inline right
  after it.** `archive/templates/meeting_list.html`'s
  `.calendar-candidate-main` renders the title `<a>` and a
  `.calendar-candidate-date` `<span>` back to back with no separator
  markup — the fix is CSS-only. `.calendar-candidate-date`
  (`archive/static/style.css`) changed from `margin-left: 0.5rem` (an
  inline sibling) to `display: block; margin-top: 0.15rem`, so a reader
  scanning down the page gets one consistent left-aligned jurisdiction/
  date column instead of hunting for it after a variable-length title.
  Deliberately scoped to `archive/static/style.css` only, not mirrored
  into `app/static/style.css` — the resolver's own use of the same
  `.calendar-candidate`/`.calendar-candidate-date` classes
  (`renderCalendarPage()` in `app/static/player.js`) is a different,
  more compact UI (an ambiguous-URL disambiguation dropdown, not a
  spacious search-results page) that the original complaint wasn't
  about; forcing it onto two lines there would just make that dropdown
  taller for no benefit. Verified visually in-browser with a static test
  harness reusing the real stylesheet against the local archive dev
  server (port 8020) — confirmed the date line now sits directly under
  the title on its own line for both a short and a long/wrapping title.

- **[Done 2026-08-10] Transcript/agenda rows now keep a wrapped line's
  left edge aligned under the first line's text, instead of falling back
  to the far-left margin under the timestamp.** User-reported: "do we
  have a backlog item about transcript styling? The fact that the text of
  the captions doesn't all left align to the same margin make it very
  hard to read." `.transcript-segment` (both `app/static/style.css` and
  `archive/static/style.css` — kept in sync manually per the note at the
  top of the latter) switched from plain inline flow to
  `display: grid; grid-template-columns: auto auto 1fr; column-gap:
  0.4rem; align-items: start;` — fixed-width timestamp/button columns
  (`white-space: nowrap` on `.segment-timestamp`, since the grid no
  longer needs a manual `margin-right`), text taking the remaining `1fr`
  column with `min-width: 0` so it wraps within its own column instead of
  overflowing.
  Found and fixed a real edge case while implementing: `renderAgenda()`
  (`app/static/player.js`) and `archive/templates/meeting_page.html`
  both have a second, *single-child* `.transcript-segment` shape — just
  a bare `<span class="segment-text">`, no timestamp/button — used when
  a source (confirmed: several CivicClerk cities' eventBookmarks) reports
  every agenda item at the identical timestamp, since rendering those as
  real clickable per-item links would be misleading. Under the naive
  3-column grid, that lone child would've landed in the first
  auto-sized column (squeezed to a narrow box) instead of the full row.
  Fixed with `.transcript-segment > .segment-text:only-child { grid-column:
  1 / -1; }` in both stylesheets, scoped narrowly enough it doesn't touch
  the normal 3-child case (real `:only-child` check, not a class toggle).
  Verified visually in-browser (`mcp__Claude_Browser__*`, local resolver
  dev server) with a static test harness reusing the real
  `app/static/style.css` covering both shapes side by side: a long
  wrapped transcript line (confirmed second line aligns under "This",
  not under "[12:34]") and a single-child agenda item (confirmed it
  spans the full row width, not squeezed left). Full `pytest` suite
  (262 tests) still green — pure CSS change, no Python logic touched.

- **[Done 2026-08-10] Fixed two real, user-caught data-quality bugs from
  the bulk-ingest batches: a wrong Legistar jurisdiction and a wrong
  Granicus date, plus a genuinely new date source (Granicus's own
  Minutes documents).**

  **Legistar jurisdiction**: Baltimore showed "CharmTV Citizens' Hub"
  (a YouTube channel/uploader name) instead of "City of Baltimore".
  Root cause was two separate bugs stacked: (1) `_extract_page_meeting_
  info()` only ever checked `<title>`, empty on Baltimore's page (unlike
  NYC's, which has the real info there) — but the identical "{jurisdiction}
  - Meeting of {body} on {date} at {time}" text is present in the page's
  own RSS `<link rel="alternate" type="application/rss+xml">` tag, a
  standard Legistar template element, confirmed present regardless of
  whether `<title>` itself is populated. (2) Even once found, the
  fallback path's jurisdiction override (`resolved.jurisdiction or
  page_info["jurisdiction"]`) only ever filled in an *empty* value —
  YouTube's uploader field wasn't empty, just wrong, so it never lost to
  page_info. Flipped the priority in the fallback path specifically
  (`page_info["jurisdiction"] or resolved.jurisdiction` — page_info wins
  outright when available) since Legistar's own official page is more
  authoritative than an arbitrary delegated platform's guess; left the
  primary, long-established `a.videolink` delegation path's own priority
  order untouched, out of caution.

  **Granicus date, wrong not missing**: a real Memphis, TN meeting
  (clip 9789) showed 2023-12-05 when the real date was 2023-12-19 (confirmed
  directly by the user). Root cause: the page's own body text has "V.
  APPROVAL OF PREVIOUS MEETING MINUTES (December 5, 2023)" — a standard
  agenda item referencing the *prior* meeting's date — which body-text
  date parsing grabbed as if it were this meeting's own. Fixed by
  stripping any `(previous|prior|last) meeting ... (parenthetical date)`
  match before date-parsing gets a chance to match inside it (scoped
  tightly to a parenthetical right after the phrase, not a loose
  character window, after an early version's test caught it eating a
  second, legitimate date too broadly). Confirmed via the real page that
  no other date-shaped text exists there at all, so the fix correctly
  turns a wrong date into an honest missing one, not a different wrong
  guess.

  **New date source found live**: investigating a second real Memphis
  clip (10031, "Parks & Environment", date silently missing rather than
  wrong) led to discovering Granicus's own Minutes-viewer feature
  (`MinutesViewer.php?clip_id=...&view_id=...`) — a real, plain HTTP-
  fetchable page (no headless browser needed, unlike the player page's
  own JS-driven "Minutes" tab click) with the real meeting date right at
  the top when a customer has published minutes for that meeting. Added
  `_fetch_minutes_date()`, tried after RSS but before the document-link-
  filename last resort. `allow_redirects=False` deliberately — confirmed
  live that clip 9789 (no published minutes) 302-redirects this same
  endpoint to a raw scanned PDF rather than 404ing; treating any redirect
  as "no minutes available" avoids ever handing binary PDF bytes to
  BeautifulSoup.

  **Real gap in the fix-and-forget flow, caught mid-correction**: neither
  bug's already-published Archive page got fixed by simply re-resolving
  the URL — `archive/db/crud.py`'s "keep page fields fresh" update logic
  (`page.date = payload.get("date") or page.date`) only ever *fills in* a
  previously-empty field, deliberately never clears/overwrites an
  existing (even if wrong) one, to protect against a later bad resolve
  erasing good data. Correcting Memphis's already-wrong date needed a
  direct one-off database correction (run by the user via Render's
  Postgres shell for the `rtr-deeplink-archive` service specifically);
  Baltimore turned out not to need one at all, since the original blank-
  page visit (before the Legistar fix existed) never found a video, so
  nothing had met the "worth archiving" bar to get pushed in the first
  place. The Parks & Environment page's previously-empty date *did* get
  filled in correctly by a normal re-ingest, once `_fetch_minutes_date()`
  gave it something to find.

- **[Done 2026-08-10] Legistar now falls back to a broader link scan when
  its own `a.videolink` pattern finds nothing, extracted into a shared,
  reusable function alongside the generic fallback's identical need.**
  Real user finding: Baltimore's Legistar instance
  (`baltimore.legistar.com`) has no `a.videolink` at all for a real
  meeting — its actual recording is a plain `<a href="https://youtu.be/
  ...">Recording</a>` link sitting in an attachments table, a completely
  different shape than the `a.videolink[onclick="window.open(...)"]`/
  `OpenTelerikWindow(...)` pattern confirmed across Maricopa AZ and NYC.
  Legistar's own adapter claims the domain and gave up with "No video
  link found," never reaching `generic_fallback.py`'s own delegation
  logic (built earlier the same day for the identical class of problem
  on Austin, TX's non-Legistar page).

  Extracted the shared scanning core into `app/platforms/base.py`'s new
  `find_platform_link(html, page_url, *, exclude=frozenset())` — scans
  every `<a href>`/`<iframe src>`/`<video src>`/`<source src>` through
  `detect_platform()`, returning `(url, platform)` for the first real
  match. `generic_fallback.py`'s own `_try_delegate_to_known_platform()`
  now calls this instead of duplicating the scan; `legistar.py` gained a
  new `_try_fallback_video_link()` called only when `_find_video_links()`
  finds nothing, trying a real YouTube link first (`YouTubeAssetFinder.
  extract_video_id(html)` — turns out this already works directly
  against raw HTML text, not just a URL, since it's a `.search()` not
  `.match()`; no new YouTube-specific function needed), then
  `find_platform_link()` for anything else, applying the same page-title
  metadata override (`_extract_page_meeting_info()`) real video-link
  delegation already uses.

  Both callers exclude `"youtube"` from the general scan and rely on
  their own tighter, video-ID-validated check instead —
  `detect_platform()`'s broad `"youtube.com" in netloc` match would
  otherwise false-positive on a bare channel/user link (the real case
  that motivated this exact split when `generic_fallback.py` was first
  built: Aurora, CO's "Watch Us on YouTube" footer icon).

  Verified live end-to-end against the real Baltimore meeting: real
  video plays (YouTube embed), real title/date/jurisdiction
  ("City Council Hearing; October 20, 2025", 2025-10-20, CharmTV
  Citizens' Hub — Baltimore's own Legistar page title didn't match the
  `_PAGE_TITLE_RE` pattern NYC's does, so this correctly fell back to
  YouTube's own real metadata rather than leaving anything blank), and
  2587 real transcript segments, replacing what was previously a page
  with no video and no transcript at all.

- **[Done 2026-08-10] Generic fallback now delegates to any other
  platform this app already supports, found as a plain link on the
  page.** Real user finding: Austin, TX's own council meeting pages
  (`austintexas.gov/council/{date}-reg`) don't embed video at all —
  they link out to their Swagit-hosted recording
  (`austintx.swagit.com/play/{id}/0/`) as a plain `<a href>`, which
  `SwagitAssetFinder` already resolves correctly on its own (confirmed
  directly: real video URL, real title, real date, all correct). Added
  `_try_delegate_to_known_platform()`: scans every `<a href>`/`<iframe
  src>`/`<video src>`/`<source src>` on the page through the same
  `detect_platform()` every URL gets classified by, and delegates to
  that adapter's real `resolve()` on the first match. Checked before
  `media_scan.py`'s generic media-URL scan (a full, real adapter's
  result is strictly richer than a raw `.m3u8`/`.mp4` guess) but after
  the existing YouTube-embed regex (kept as-is, first priority).

  Deliberately excludes `"youtube"` from the delegation scan — already
  handled by the narrower, embed/watch-URL-specific regex checked first;
  `detect_platform()`'s broader `"youtube.com" in netloc` check would
  otherwise also match a bare channel/user link (a real false positive
  confirmed live on Aurora, CO: a footer "Watch Us on YouTube" icon
  pointing at a channel page, not a specific video — would have raised
  inside the delegated `YouTubeAssetFinder.resolve()` since no 11-char
  video ID exists in a channel URL). Any delegation failure (a bad
  match, a `CalendarPageError` from e.g. a Legistar calendar link,
  network errors) is swallowed and treated as "no delegation possible,"
  never allowed to turn an honest "found nothing" into a crash.
  `source_url` is overridden back to the ORIGINAL page after a
  successful delegation (not the delegated platform's own URL), matching
  how LIMS/PrimeGov already preserve their own source_url through a
  YouTube delegation — a visitor who came from `austintexas.gov` should
  never see `swagit.com` as "the source."

  **Real CSS bug caught during live verification, not from a unit
  test**: `.source-guess` (the "we think the video/agenda is here:
  `<link>`" lines, added the previous session) had no `overflow-wrap`.
  A real long unbroken media URL (Swagit's own `archive-stream.
  granicus.com/.../playlist.m3u8` link, no natural break points) rendered
  595px wide inside a 300px-wide left column, visually overflowing 267px
  into the right column and colliding with the Agenda heading's own text
  — confirmed via `getBoundingClientRect()` on the actual rendered anchor
  (`right: 829`, while the right column starts at `left: 562`), not just
  eyeballed from a screenshot. Fixed with `overflow-wrap: break-word` on
  both `.source-guess` and `.source-guess a`.

  Verified live end-to-end against the real Austin URL: real video plays
  (real Austin City Council branding, real 4:51:27 duration), real
  agenda_items with real timestamps render (Swagit's own agenda-viewer
  data, not a guessed link), `source_url` stays the original
  austintexas.gov page, and the long-URL overflow no longer collides
  with the Agenda column after the CSS fix.

- **[Done 2026-08-10] Redesigned the generic-fallback meeting page per a
  detailed user spec, given directly against a real screenshot.** The
  previous pass (see the "Live-tested the generic fallback" entry just
  below) fixed real bugs but kept the declarative/warning-box tone; the
  user wanted the whole unsupported-platform experience to read as
  openly tentative instead. Concrete changes, all in `app/templates/
  meeting.html` / `app/static/player.js` / `app/static/style.css`:

  - A full-width banner ("This government website isn't supported yet,
    so we're going to try our best.") above both columns, plain weight/
    color (reuses `#meta`'s existing `<p>` styling, already full-width
    via `grid-column: 1 / -1`).
  - Left column: the old bold-on-yellow video warning box replaced with
    a plain "We think the video is here: `<link>`" line (or
    "[No video found]"), the "Request Transcript from Audio" button
    unchanged below it.
  - Right column: an "Agenda" heading now always shows for a best-effort
    result (previously only when something was found), with a plain
    "We think we found an agenda here: `<link>`" line (or
    "[No agenda found]") — above "Transcript", not nested under it.
  - Transcript section: the "No transcript to click through... we're
    tracking the playhead" copy (which implied a certainty the app
    doesn't have) replaced with just "Sometimes deep-linking to a
    specific moment works on a site we don't officially support yet, and
    sometimes it doesn't — still worth trying." The live-tracking "0:00"
    readout (which was frozen forever anyway when no video existed to
    track — a real latent bug this replacement also fixes) is replaced
    with a manual timestamp text input + a "Copy link to this moment"
    button that reads the typed value instead of a video adapter's
    current time, wired independently so it works even with zero video.

  **Real design fix caught mid-implementation**: gating all of this on
  `platform === 'unknown'` (the approach used in the previous pass) is
  wrong — `generic_fallback.py` delegates to `YouTubeAssetFinder` when it
  finds an embedded YouTube video (the single most common real outcome),
  and that finder's own `platform` field stays `"youtube"` regardless of
  caller. Added `ResolvedMeeting.best_effort: bool`, set `True` on every
  result this adapter produces (delegated or not), and switched all of
  the new UI's gating to that instead — the previous pass's deep-link
  caveat (built one session earlier) had this exact same latent flaw and
  got fixed retroactively in the same change.

  Also replaced `agenda_warnings: List[str]` (a sentence, added the
  previous session) with `agenda_link: Optional[str]` (a raw URL) — the
  new plain-line UI needed just the link, not a pre-formatted sentence,
  and nothing else in the codebase had started depending on the old
  field yet.

  Verified live against both real test cities from the previous pass:
  Aurora, CO (real video + real agenda link, both lines populated
  correctly, video still plays) and Accomack County, VA's BoardDocs (no
  video/agenda found, both correctly show the bracketed fallback text,
  manual timestamp entry copies a real working deep link). A real CSS
  gap caught in the same pass: `#agendaSection` showing unconditionally
  now exposed `#agendaList`'s empty container as a stray bordered box
  when there were no real `agenda_items` — fixed with `.transcript-list:
  empty { display: none; }`, matching `.warnings:empty`'s existing
  pattern.

- **[Done 2026-08-10] Live-tested the generic fallback against a real,
  never-before-seen city (Aurora, CO's auroratv.org) and fixed three real
  bugs it surfaced.** First real end-to-end test of `generic_fallback.py`
  (built 2026-08-09) against a genuinely unsupported site, per the user's
  own request ("let's test the fallback page you made") — found via a
  live check of the shared sample sheet's "50 cities" tab (BoardDocs
  entries there are explicitly documented as never getting a dedicated
  adapter, guaranteeing the fallback path), then Aurora came from the
  user's own follow-up test.

  **Real bug #1**: Aurora genuinely has a playable video (a real .mp4)
  and real captions (a real .vtt) on the page, but the resolver reported
  neither. Root cause: `media_scan.py`'s `MEDIA_URL_PATTERNS` all require
  a literal `https?://`, but both URLs live inside an inline `<script>`
  JSON blob (a JW Player config) with every `/` written as a JSON-escaped
  backslash-slash — confirmed by fetching the real raw HTML directly.
  Fixed by de-escaping before scanning (see `media_scan.py`'s own
  docstring for the full reasoning on why a blanket replace is safe).
  Verified against the real page: `video_url` now resolves to the real
  `vod.mp4`, and 5310 real transcript segments load from the real .vtt.

  **Real bug #2**: `video_warnings` was silently invisible whenever no
  video was found at all — confirmed live via a real BoardDocs page
  (Accomack County, VA) that genuinely has no video. Root cause:
  `#videoError` (where the warning rendered) is a child of `#videoSection`,
  which itself gets `hidden = true` whenever there's no `video_url` —
  taking the warning down with it even though the warning exists
  specifically to explain *why* there's no video. Fixed by splitting into
  a new, independently-visible `#videoWarnings` for the no-video case;
  `#videoError` stays reserved for genuine native-video/HLS playback
  failures where a video legitimately exists (a real, narrower, different
  case). A prior fix earlier in the same session (the YouTube IP-block
  degrade-gracefully change) had already exercised this exact code path
  with a video present — masking this bug, since it only reproduces when
  there's no video at all.

  **Design gap, not exactly a bug**: the agenda-link message (built
  2026-08-09) was nested under the Transcript heading via
  `transcript_warnings`, which the user correctly flagged as misleading
  (an agenda link isn't transcript-related). Added
  `ResolvedMeeting.agenda_warnings`, a new field mirroring the existing
  `video_warnings`/`transcript_warnings` pattern, rendered under its own
  Agenda heading regardless of whether real `agenda_items` exist.

  **UX improvements, from direct user feedback on a live screenshot**:
  messages mentioning requesting a transcript from the audio were plain
  dead text next to the real button elsewhere on the page — standardized
  the phrasing to a single matchable substring across `generic_fallback.py`
  and the three other adapters with a similar message
  (`civicclerk.py`/`escribe.py`/`granicus.py`'s garbled-transcript case),
  and made that exact phrase a real inline `<button>` triggering the same
  action (`document.getElementById('transcribeToggle').click()`). The
  no-transcript live-playhead panel's hint text now adds a caveat when
  `platform === 'unknown'`, since deep-link reliability there genuinely
  isn't confirmed the way it is on a supported platform.

  Also answered a real design question the user raised: does the
  "Request Transcript from Audio" flow re-check for video/captions
  independently, in case the initial page scan misses something?
  Confirmed yes already, structurally — `/api/transcription/
  check-feasibility` calls the exact same `get_finder(platform).resolve()`
  path as the main resolve, so fixing the shared `media_scan.py` bug
  above fixed both at once; no separate mechanism was needed.

  **Follow-up correction, same session**: the copy shipped in all of the
  above read as confident/declarative ("You can still...", matter-of-fact
  instructions) rather than the open-ended, tentative "hey, we're trying
  our best, this might not work" tone the user had originally specified
  for this exact feature (from the original request that led to building
  `generic_fallback.py` in the first place). Rewrote all four
  `generic_fallback.py` messages and the platform-specific deep-link
  caveat to match: "we think we found...", "might work, or it might
  not...", "we're trying our best" rather than definitive statements —
  caught only because the user asked directly whether their original
  copy suggestion had been dropped, a real reminder that copy tone from
  earlier in a long session can get lost across many intervening fixes.

  **Known residual gap, not yet addressed**: `archive/templates/
  meeting_page.html` and `archive/static/meeting_page.js` render the same
  video/agenda/transcript sections server-side (Jinja2, not this same JS
  render path) and likely have the identical underlying issues (warnings
  nested under the wrong heading, no equivalent of the new
  `agenda_warnings` field) — not yet mirrored, since no `platform="unknown"`
  meeting has ever actually been pushed to the Archive (confirmed via a
  real audit of all 22 archived meetings, see the YouTube-captions
  investigation entry above/nearby). Worth doing before the first such
  meeting actually gets archived, not urgent before then.

- **[Done 2026-08-09] Fixed production incident: Minneapolis LIMS (and
  likely SLC, same underlying cause) resolves failing with Playwright's
  own raw error text shown on the page.** Reported live by the user:
  pasting a real Minneapolis meeting URL showed `BrowserType.launch:
  Executable doesn't exist at /opt/render/.cache/ms-playwright/...`
  verbatim, including Playwright's multi-line ASCII-art box — confirmed
  the exact deployment risk flagged (but not yet verified) when these
  adapters shipped: `render.yaml`'s `playwright install --with-deps
  chromium` build step did not leave a working browser binary where the
  running service looks for it.

  Two real fixes shipped immediately: `app/platforms/
  headless_browser.py`'s `_get_browser()` now self-heals (runs
  `playwright install chromium` in-process on first launch failure, then
  retries once) so a broken/incomplete build step doesn't leave this
  permanently down until a redeploy; and `fetch_via_browser()` now raises
  a short, clean `HeadlessBrowserUnavailable` message instead of letting
  Playwright's own raw error text reach a real visitor's page.

  **That fix's own deploy then failed outright** ("Exited with status 1
  while building your code") — real evidence pointing at `--with-deps`
  specifically: it shells out to `apt-get install` for Chromium's system
  libraries, which needs root/sudo Render's build sandbox almost
  certainly doesn't grant, failing the whole chained build command
  before `pip install`'s own success even mattered. Switched to plain
  `playwright install chromium` (browser binary only, no system-package
  install attempt) — see `render.yaml`'s own comment for the full
  reasoning and the `runtime: docker` fallback if a plain binary download
  turns out not to be enough.

  **Confirmed working 2026-08-09**: the user retested a real Minneapolis
  meeting in production and Playwright launched/scraped successfully —
  the resolve got all the way through the LIMS agenda page and handed
  off a real YouTube video ID before hitting a *different*, later-stage
  failure (YouTube's own anti-bot check, logged as a new active incident
  in BACKLOG.md). That later failure signature is itself the proof this
  fix worked — it couldn't have been reached if Playwright were still
  failing to launch.

- **[Done 2026-08-09] Built auto-idle-time transcription job generation**,
  closing the last open piece of the on-demand-transcription feature —
  the worker no longer sits fully idle when the job queue is empty; it
  looks for a `MeetingPage` missing a good transcript and creates a
  self-generated job for it, so the Archive's transcript coverage grows
  passively instead of only when someone manually clicks "Transcribe."
  Design decided via a real interview (three questions: cooldown
  strategy after a failure, what `requester_email` an auto-job should
  use given the column is required and the worker emails it on
  completion, whether a separate volume cap is needed beyond the
  existing priority system) — landed on: escalating backoff (each
  consecutive failure for the same page doubles the cooldown, capped at
  30 days, matching `ARCHIVE_RECHECK_AFTER`'s existing precedent — a flat
  cooldown or a permanent give-up-after-N-failures cap were the two
  alternatives considered and rejected), a real configured email address
  (`AUTO_TRANSCRIPTION_REQUESTER_EMAIL`) doubling as a lightweight
  completion-email activity digest rather than a new no-email code path
  or a dedicated mailbox, and no separate cap — `PRIORITY_LOW` already
  means a real visitor's request always jumps ahead of self-generated
  work, so a growing backlog of auto-jobs can never block one.

  New pieces: `archive/db/crud.py`'s `find_auto_transcription_candidate()`
  (oldest-archived-first, skips pages with a good transcript or in
  cooldown — a full Python-side scan, deliberately, fine at today's scale
  same reasoning as `/meetings`' own search scan),
  `_in_auto_transcription_cooldown()` (the escalating-backoff math, walking
  back from the most recent job counting *consecutive* failures — an older
  failure before a later "completed" job is stale history, not part of
  the current streak), `create_failed_auto_transcription_job()` (records
  a re-resolve/feasibility failure as a real, already-`failed`
  `TranscriptionJob` row so it enters the same cooldown mechanism a real
  chunk-processing failure uses, rather than a separate "skip list" that
  would need its own schema), and `create_transcription_job()` gained a
  `priority` parameter (previously hardcoded to `PRIORITY_MEDIUM` — the
  only call site until now). `worker/main.py`'s `maybe_generate_auto_job()`
  reuses the exact feasibility-check logic `app/main.py`'s
  `/api/transcription/check-feasibility` has (`probe_duration`,
  `is_plausible_meeting_duration`, both already imported by the worker
  for its own chunk-processing path) rather than duplicating it, and is
  gated in `run_forever()`'s idle branch by both "the queue is completely
  empty" (implied for free once `claim_next_chunk()` returns nothing,
  since this repo runs exactly one worker process — see that function's
  own docstring) and a separate `AUTO_GENERATION_CHECK_INTERVAL_SECONDS`
  (5 minutes) so it doesn't re-scan the whole Archive on every single
  15-second empty poll.

  Verified end-to-end live (not just unit tests): created two real
  archived pages missing a transcript (one with a deliberately fake,
  unresolvable URL; one a real, live PrimeGov meeting confirmed
  resolvable earlier this session) and called `maybe_generate_auto_job()`
  directly against the real Archive DB. Confirmed correct oldest-first
  ordering, confirmed the fake-URL candidate correctly recorded a
  re-resolve failure, confirmed the real candidate's feasibility check ran
  for real (found a real video URL; `probe_duration` itself came back
  unreadable from this dev sandbox specifically — the same known
  environment-specific network limitation already diagnosed for other
  media URLs this session, not a bug in this feature), confirmed both
  landed in the DB with `priority=0` and the configured digest email as
  `requester_email`, and confirmed both were correctly excluded from
  candidacy immediately afterward (cooldown). 19 new tests: 15 crud-level
  in `tests/test_transcription_jobs.py` (including one that directly
  exercises the escalation math with backdated timestamps — 2 consecutive
  failures 36 hours ago must still be in cooldown under doubling, which
  would already have cleared a flat 1-day rule) and 4 in the new
  `tests/test_worker_auto_generation.py` covering the parts of
  `maybe_generate_auto_job()`'s control flow that don't need mocking a
  live resolve. Full suite (207 tests) passing. New env var
  `AUTO_TRANSCRIPTION_REQUESTER_EMAIL` documented in `.env.example` —
  auto-generation is simply disabled (not guessing a placeholder address)
  when it's unset.

- **[Done 2026-08-09] Built a language-track correction flow: "public
  report, admin fixes."** Real gap closed: a `TranscriptVersion`'s
  `language` was set once (langdetect's guess for a self-transcribed
  version, or the source's own label for a scraped one) and never
  correctable afterward short of a raw database edit. Design decided via
  a real interview (three questions: who can invoke the correction, does
  it need to handle genuine bilingual content, does it apply to any
  version or only self-transcribed ones) — landed on: public report via
  the existing "Report a problem" form (new `wrong_language` issue type,
  added to `VALID_ISSUE_TYPES` in `app/db/crud.py` and the dropdown in
  both `app/templates/meeting.html` and
  `archive/templates/meeting_page.html`), a human (Ryan) reviews via the
  existing `/admin/problem-reports` list and applies the fix, no
  bilingual/mixed-content support attempted, and any version can be
  corrected — not just self-transcribed ones.

  New pieces: `archive/db/crud.py`'s `correct_transcript_version_language()`
  (targets the page's current default version when no `version_id` is
  given, since that's what a reporter was actually looking at);
  `archive/main.py`'s token-gated `POST /internal/transcript-version/
  correct-language`; `app/archive_client.py`'s `correct_transcript_language()`
  proxy function; and `app/main.py`'s `GET /admin/correct-transcript-
  language?token=&url=&language=&version_id=`, which takes the reported
  meeting's raw source URL (same shape as the existing
  `/admin/recheck-archive-page`) and looks up the matching Archive page
  the same way a repeat paste would, rather than requiring the admin to
  already know the internal slug. Verified end-to-end against a real
  live-archived NYC meeting: submitted a real `wrong_language` report via
  `/api/report-problem`, confirmed it appeared in `/admin/problem-
  reports`, applied the correction via `/admin/correct-transcript-
  language`, confirmed the change actually rendered on the permanent
  page's `schema.org inLanguage` field, then reverted it back to the
  real correct value. 8 new tests (4 crud-level in
  `tests/test_ingest_promotion.py`, 4 HTTP-level in the new
  `tests/test_correct_language_endpoint.py` covering token gating and
  the not-found path, which live entirely in the route layer and aren't
  reachable from a crud-level test). Full suite (198 tests) passing.

- **[Done 2026-08-09] `/meetings` pagination threw a real 422 in production
  whenever a filter checkbox was left unset.** Reported live by the user
  with the exact broken URL: clicking "Next" on
  `https://redtaperecordings.com/meetings?page=2&q=&jurisdiction=&
  date_from=&date_to=&fuzzy=&has_agenda=&has_transcript=` returned a raw
  FastAPI validation error instead of the next page. Root cause:
  `archive/templates/meeting_list.html`'s pagination link always emitted
  all seven filter params via a `%`-format string, substituting `""` for
  any unset one — e.g. `...&fuzzy=&has_agenda=&has_transcript=`. FastAPI's
  bool-typed query params (`fuzzy: bool`, `has_agenda: Optional[bool]`,
  `has_transcript: Optional[bool]`) reject an empty string outright (422
  `bool_parsing`) rather than treating it as "not provided" — only an
  *omitted* param does that.

  Fixed both ends, not just the one that caused this specific report:
  the template now builds the querystring from a list of only the params
  that actually have a value (also fixes an adjacent, previously-unnoticed
  bug — a search query containing `&` or `#` would have corrupted the
  pagination link's other params, since the old format string never
  URL-encoded anything); and `archive/main.py`'s route itself now accepts
  `fuzzy`/`has_agenda`/`has_transcript` as plain strings and parses them
  tolerantly (`_parse_optional_bool()`), so URLs already bookmarked/shared
  with the old broken shape — including the exact one just reported —
  keep working instead of 404ing/500ing forever. First HTTP-level route
  test added to this suite (`tests/test_meetings_route.py`, via
  `fastapi.testclient.TestClient`) — every other test here exercises
  `crud`/pure functions directly, which never touches FastAPI's own
  query-param parsing layer where this bug actually lived. Verified live
  against a local server with the exact reported URL (confirmed 200, was
  422) and by rendering the fixed template logic directly against mock
  filter state (confirmed a clean `page=2` with no filters set, and
  correct `%26`-encoding of a query containing `&`). Full suite (190
  tests) passing.

- **[Done 2026-08-09] Added a static citymeetings.nyc cross-link to NYC
  Council meeting pages, and caught a real, unrelated bug while verifying
  it live: `archive/db/crud.py`'s `get_page_by_slug()` silently dropped
  `platform` from its returned dict entirely.** User pointed to Vikram
  Oberoi's citymeetings.nyc (an independent, AI-chapter-summary tool
  specifically for NYC Council meetings, covering ~80 meetings as of his
  own talk) as worth a mention on NYC pages — confirmed live first
  (`mcp__Claude_Browser__*` against a real citymeetings.nyc chapter
  permalink) that clicking a chapter there does *not* auto-seek the video
  either (`currentTime` stayed 0 through page load, only advanced normally
  once `.play()` was called directly — same deep-link gap this app exists
  to close), so this is a genuinely complementary link, not a
  better-alternative one. Decided against automated per-meeting
  cross-linking (his coverage isn't guaranteed to include any given
  meeting we resolve, and mapping meetings across two independent slug
  schemes would couple our reliability to his site's uptime) — a static
  note instead, shown whenever `platform == "viebit"` (confirmed Viebit is
  NYC-Council-only so far, see ViebitAssetFinder's docstring). Added to
  both `app/templates/meeting.html`/`app/static/player.js` (client-JS
  toggle, matching the resolver's render-after-`/api/resolve` pattern) and
  `archive/templates/meeting_page.html` (server-side Jinja2 conditional).

  **The Archive side silently failed on first live-verification pass** —
  the DB row genuinely had `platform="viebit"` (confirmed via direct
  sqlite3 query), but the rendered page never showed the note. Root cause:
  `get_page_by_slug()` builds and returns a hand-constructed dict (not the
  ORM object) for template consumption, and that dict's field list simply
  never included `platform` — Jinja2's `page.platform == "viebit"` on a
  dict without that key silently evaluates to `Undefined == "viebit"`
  (`False`), no exception, no missing-key error, just quietly wrong. Fixed
  by adding `"platform": page.platform,` to the returned dict. Real
  example of this repo's "verify in-browser, not just via the API"
  convention catching something a DB-level check alone would have missed
  — see `CLAUDE.md`. Added `test_get_page_by_slug_includes_platform` to
  `tests/test_ingest_promotion.py` as a regression guard (this dict has no
  other test asserting its exact key set, so this bug could otherwise
  recur silently for any future field). Verified end-to-end against a real
  live-resolved NYC meeting pushed through both local services together
  (resolver + Archive), confirmed absent on a non-Viebit Archive page
  (Dublin, CA) as a regression check. Full suite (187 tests) passing.

- **[Done 2026-08-09] NYC Legistar meetings delegated to Viebit showed
  Viebit's own raw uploaded filename as the meeting title
  ("NYCC-250-8-2_251218-120823.mp4") instead of anything human-readable.**
  Reported by the user against a real production URL
  (`legistar.council.nyc.gov/MeetingDetail.aspx?ID=1362373...`). Root
  cause: `LegistarAssetFinder._find_video_links()` already extracts a
  `title`/`date` per candidate via `_extract_row_info()` — but that
  extraction is shaped for *calendar* rows (each `<tr>` has a title cell
  and a date cell), and on a single-meeting `MeetingDetail.aspx` page the
  video link's parent `<tr>` is just a one-cell "Video" row, so the
  extracted title was always "Untitled meeting"/discarded, and the
  single-video-link resolve path threw the whole `video_links[0]` dict
  away anyway once it had the URL, delegating to `resolve_via_platform()`
  with nothing to fall back on. `ViebitAssetFinder` (the platform
  underneath NYC's Legistar instance) has no better title of its own —
  confirmed live, Viebit's own `video.title` field is just the raw
  uploaded filename, not a human title.

  Fix: confirmed live on two real NYC `MeetingDetail.aspx` pages that the
  outer page's own `<title>` tag reliably gives
  `"{jurisdiction} - Meeting of {body} on {M}/{D}/{YYYY} at {time}"` —
  e.g. `"The New York City Council - Meeting of Committee on Finance on
  12/18/2025 at 11:30 AM"` and `"...Meeting of City Council on
  12/18/2025 at 1:30 PM"`. Added `LegistarAssetFinder._extract_page_meeting_info()`
  (regex-parses that shape into `title`/`jurisdiction`/`date`) and
  `_looks_like_raw_filename()` (matches a trailing video file extension —
  `.mp4`/`.mov`/`.wmv`/`.avi`/`.mkv`/`.m4v`). After delegating, `resolve()`
  now overrides the delegated result's `title` only when it looks like a
  raw filename, and fills `jurisdiction`/`date` only when those are
  missing entirely — never silently replacing an already-good value from
  a platform that has its own real metadata (e.g. Granicus). Verified
  against both real live URLs end-to-end (direct `resolve_via_platform()`
  call and the real `/api/resolve` endpoint) — `ID=1362373` now resolves
  `title="Committee on Finance"`, `jurisdiction="New York City Council"`,
  `date="2025-12-18"` (previously the raw filename, `None`, and a
  coincidentally-correct date respectively). 6 new tests added to
  `tests/test_legistar.py` (11 total, up from 5) covering the override,
  the no-`<title>`-tag passthrough case (existing behavior unchanged), and
  both helper functions directly; full suite (186 tests) passing.

  **Separately reported in the same message: Viebit video playback itself
  is also broken in production ("Video failed to load; source link
  only.").** This is a real, larger, confirmed-but-deferred bug — see the
  live entry in `BACKLOG.md` for the full root-cause investigation
  (Referer/Origin-gated CDN, confirmed via direct browser testing) and why
  the fix (switching to an iframe embed of Viebit's own player, matching
  the YouTube precedent) isn't being built yet.

  **[Done 2026-08-12] Fixed for real: Viebit now plays via an iframe
  embed, with reload-based deep-link seeking.** Two real questions were
  blocking this since 2026-08-09: whether Viebit's embed page has any
  cross-frame seek API, and whether iframing it is even viable given
  that uncertainty. Answered by pulling Viebit's own real player bundles
  directly (`lgx-videojs-plugins-*.js`, `vod-embedded-*.js`, from a live
  NYC Council video): no `postMessage` API exists anywhere in either
  file, but the embed page itself reads a `?t={seconds}` query param on
  load and seeks there once playback starts — the same mechanism
  YouTube's own `?start=` uses, just load-time-only.

  **Real, unavoidable consequence of "load-time-only, no live API"**:
  there's no way to read the iframe's actual current playback position
  from outside it. Rather than fake it (a "copy link to current time"
  or "currently playing" highlight based on the last-clicked position
  would silently go stale the moment playback continues past it), both
  are deliberately disabled for this platform specifically — the user's
  own explicit call between three options (honest degradation vs. fake
  tracking vs. load-time-only with no click-to-seek at all). Explicit
  seeks (a transcript-line click, "Go to time") still work fully, since
  those only ever need a known target time, never a read.

  **Build**: `viebit.py`'s `video_url` is now always rebuilt as the
  confirmed-safe-to-iframe `/embed/vod?v={id}` path on the fetched
  page's own origin (not whatever URL a Legistar delegation's redirect
  chain happened to land on, nor the raw `master.m3u8`), with a new
  `video_format="viebit"`. New `createViebitAdapter()` /
  `initViebitVideo()` in both `app/static/player.js` and
  `archive/static/meeting_page.js` (duplicated, matching this repo's
  existing convention for these two files) — the adapter's
  `currentTime` setter rebuilds the iframe `src` with the new `t=` and
  reassigns it (a real reload, not an instant seek); `play()`/`pause()`
  are no-ops and `addEventListener()` never fires, since neither is
  possible from outside the iframe either. `wireSharedControls()` in
  both files gained a `{ liveTracking: false }` option that hides (not
  just leaves silently non-functional) the "copy link to current
  time"/"copy link to this moment" controls, while leaving auto-scroll
  toggle and the "Go to time" box wired normally. New `<iframe
  id="viebitFrame">` element alongside the existing native-`<video>`/
  YouTube containers in both `meeting.html` and `meeting_page.html`,
  with matching CSS in both services' `style.css`.

  Verified live end-to-end on both pages (not just unit tests): the
  resolver's `/meeting` page with a real NYC Council embed URL
  (`councilnyc.viebit.com/embed/vod?v=...`) — the real Video.js player
  renders correctly (title, NYC seal, play button) after a brief native-
  `<video>`-fallback flash during its own load; "Go to time" correctly
  reloads the iframe with `t=` and updates the shareable URL;
  "copy link to current time" confirmed hidden. Then the Archive's
  `/m/{slug}` page with a real seeded `video_format="viebit"` page: same
  correct rendering, a real transcript-line click correctly reloads the
  iframe (`&t=10`) and updates the URL with `t=10&line=seg-1&version=1`.
  9 Python tests updated/added in `tests/test_viebit.py` (URL-shape
  changes plus a new `_build_embed_url()` unit test); `tests/
  test_legistar.py`'s NYC delegation test needed no changes (its
  assertions were already loose enough). Full suite green (467 tests).

- **[Done 2026-08-09] Production incident: the worker was crash-looping on
  every `claim_next_chunk()` call with `column transcription_jobs.priority
  does not exist`.** Root cause: this session's own
  `archive/alembic/README.md` said `alembic stamp head` for the one-time
  production-adoption step — correct when written (only the baseline
  migration existed), but a second migration (`8e7cf3b20f86`, the priority
  column) landed in the same session before anyone ran it against
  production, so "`head`" silently became the wrong target the moment that
  second migration was committed. README fixed to reference the specific
  revision id (`a8dc5aad7eff`) instead of the word `head`, with an explicit
  "why `head` is unsafe here" paragraph — see `archive/alembic/README.md`.

  **Confirmed fixed by the user, run from a Render shell into the
  `archive` service** (note: `alembic` must be run from inside `archive/`
  — running it from the repo root fails with `FAILED: No 'script_location'
  key found in configuration`, since `alembic.ini` lives under
  `archive/`). `alembic current` before the fix printed nothing (production
  had genuinely never been stamped, matching the README's prediction);
  `alembic stamp a8dc5aad7eff` then `alembic upgrade head` ran clean, and
  a final `alembic current` confirmed `8e7cf3b20f86 (head)`. This confirms
  the database schema now has the `priority` column, which removes the
  root cause of the crash-loop — the running worker process's own recovery
  (whether it needed a restart, or picked this up on its next poll cycle)
  wasn't independently checked this session, since neither Render logs nor
  process state were available to it.

- **[Done 2026-08-09] PrimeGov's date/jurisdiction fixed for real, using the
  page's own visible "FORMAL AGENDA"/"REGULAR MEETING" header text — a
  different, more reliable signal than the embedded sub-document `<title>`
  approach tried and reverted earlier in this same investigation (see the
  entry directly below this one).** Real bug: `PrimeGovAssetFinder.resolve()`
  (`app/platforms/primegov.py`) delegated entirely to
  `YouTubeAssetFinder.resolve_video_id()`, which sets `date` from yt-dlp's
  `upload_date` and `jurisdiction` from the raw YouTube `uploader` handle.
  Confirmed live against both real samples that both were wrong: OKC's
  `upload_date` (`20260805`) and Thousand Oaks's (`20260708`) were each one
  day *after* the real meeting (both uploaded the morning after an evening
  session), and Thousand Oaks's `uploader` ("CTO Meetings") carries no
  identifiable city name at all (OKC's "cityofokc" is barely usable).

  Per the user's own suggestion — "look for the date and jurisdiction on
  the page/row that is linking off to that youtube URL... probably the
  most accurate and dependable solution" — checked the PrimeGov page's own
  rendered text (`mcp__Claude_Browser__get_page_text` first, then a plain
  `curl`/`aiohttp` fetch to confirm it's in the *raw static HTML*, no
  headless browser needed): both real samples have a plain, prominent
  agenda header giving the correct date —
  `https://okc.primegov.com/Portal/Meeting?meetingTemplateId=68482`: "THE
  CITY OF OKLAHOMA CITY / FORMAL AGENDA / CITY COUNCIL / August 4, 2026";
  `https://toaks.primegov.com/Portal/Meeting?meetingTemplateId=9446`:
  "City Council / REGULAR MEETING / Tuesday, July 07, 2026". Both dates
  match the video's own title exactly (`"...Meeting - August 4, 2026"`,
  `"...Meeting - July 7, 2026"`) — unlike the reverted embedded-`<title>`
  approach, which for Thousand Oaks picked up an unrelated "Closed
  Session" sub-document's date (July 8, coincidentally matching the wrong
  `upload_date` instead).

  Built `PrimeGovAssetFinder._extract_date()` (first full-month-name date —
  `(Monday|...|Sunday)?, Month D(D), YYYY` — found within the first 2000
  chars of `BeautifulSoup(...).get_text()`, converted to ISO) and
  `_extract_jurisdiction()` (`(city|county|town) of X` bounded by an HTML
  tag or punctuation, with a second-line-of-defense cap that stops
  collecting words at the first one that doesn't start with a capital
  letter). The tag/punctuation bound was necessary, not cosmetic: a naive
  `city of` regex run against Thousand Oaks's flattened page text matched
  clear across an unrelated mission-statement sentence ("...City of
  Thousand Oaks that all employees are to be treated with respect and
  dignity...") because nothing but a lowercase word follows the real city
  name there; OKC's all-caps table-cell header ("OKLAHOMA CITY" then
  "FORMAL AGENDA" then "CITY COUNCIL" with no punctuation between them
  once tags are stripped) needed the opposite fix, a tag-boundary stop
  instead of a punctuation one. `resolve()` now overrides
  `YouTubeAssetFinder`'s `date`/`jurisdiction` only when a real page match
  is found, otherwise keeps YouTube's better-than-nothing values (covered
  by a dedicated fallback test).

  Verified against both real live URLs end-to-end (not just the extraction
  methods) via a direct `resolve()` call and the real `/api/resolve`
  endpoint, then in-browser on the rendered meeting page — confirmed the
  page actually shows "City of Thousand Oaks · 2026-07-07" for the
  Thousand Oaks sample. 8 new unit tests + 3 new `resolve()`-level tests
  added to `tests/test_primegov.py` (15 total, up from 5), full suite
  (181 tests) passing.

- **[Done 2026-08-09, reverted before shipping — see the entry above for
  the fix that actually landed] PrimeGov's date/jurisdiction come entirely
  from YouTube's own metadata, which is measurably worse than what's
  already sitting on the PrimeGov page itself.** Confirmed live
  (2026-08-08) via
  `https://okc.primegov.com/Portal/Meeting?meetingTemplateId=68482`
  (Oklahoma City) — video and transcript resolve cleanly (3503 real
  English auto-caption segments, no warnings beyond the standard
  auto-caption disclaimer), but:
  - `date` resolved to `2026-08-05`, one day off from the real meeting.
    The PrimeGov page has an embedded agenda document titled `"City
    Council - 8/4/2026 1:30:00 PM"` and body text saying `"August 4,
    2026"` — the *video's own title* even says "Oklahoma City Council
    Meeting - August 4, 2026". Root cause: `PrimeGovAssetFinder.resolve()`
    (`app/platforms/primegov.py`) extracts only the YouTube video id from
    the page HTML and discards everything else, delegating entirely to
    `YouTubeAssetFinder.resolve_video_id()` — which sets `date` from
    yt-dlp's `upload_date` (`app/platforms/youtube.py` line ~80), i.e.
    when the video was *posted to YouTube*, not the real meeting date.
    Plausible mismatch for any meeting uploaded the next morning after an
    evening session.
  - `jurisdiction` resolved to `"cityofokc"` — YouTube's raw `uploader`
    field (the channel handle), not a real jurisdiction string like
    "Oklahoma City, OK".
  Only affects PrimeGov pages that actually have video (the common case
  per the item above) — agenda-only PrimeGov pages never hit
  `YouTubeAssetFinder` at all.

  **Tried building the "parse the page's own embedded date" fix
  2026-08-09, per the note above to check a second sample first — glad
  it was checked, since the second sample actively disproved it, not
  just failed to confirm it.** Found a real, consistent embedded-date
  signal on *both* OKC and a second sample, Thousand Oaks
  (`https://toaks.primegov.com/Portal/Meeting?meetingTemplateId=9446`):
  a nested agenda-document `<title>...- M/D/YYYY H:MM:SS AM/PM</title>`,
  distinct from the outer page's own generic `<title>Meeting</title>`
  (OKC: `"City Council - 8/4/2026 1:30:00 PM"`; Thousand Oaks:
  `"Thousand Oaks City Council Regular Meeting (Closed Session) -
  7/8/2026 12:00:00 AM"`). Built and initially verified against OKC
  (correctly produced `2026-08-04`, matching the video's own title,
  the page body text, and the docket title all agreeing) — but checking
  the *second* sample as planned caught a real problem before shipping:
  Thousand Oaks's embedded title gives **July 8**, while the video's own
  title says **"...Meeting - July 7, 2026"**. Cross-checked against
  yt-dlp's real `upload_date` for that video (`20260708`) — the embedded
  "July 8" exactly matches the *upload* date, not the real meeting date,
  meaning this specific page's embedded agenda document (labeled
  "Closed Session") is dated by when *it* was processed/logged, not
  necessarily the same date as the open session actually captured on
  video. Building this fix would have silently replaced one
  upload-lag-shaped bug with another, harder-to-notice one (both
  produce a plausible, only-one-day-off wrong date) rather than
  actually fixing it. **Reverted, not shipped** — the "page's own
  embedded date is more reliable than YouTube's" premise doesn't hold
  up as a general rule; a third real sample, or a way to independently
  corroborate the embedded date against the video's own title text
  before trusting it, would be needed before trying again.
  `jurisdiction` remains unfixed too — the embedded title only
  reliably includes a city name on some cities (Thousand Oaks yes, OKC
  no), so there's nothing consistent to extract there either.

- **[Done 2026-08-08] `media_scan.scan_media_urls`'s "sources" JSON-blob
  branch was dead code — removed rather than fixed.** The regex
  `r'({[^}]*"sources"\s*:\s*\[[^}]*\][^}]*})'` used `[^}]*` to span from
  the array's `[` to its closing `]`, but that character class excludes
  `}` entirely — so it could never match past the closing `}` of an
  object *inside* the array, meaning it never matched any real
  JWPlayer-style config blob. Confirmed dead via a unit test
  (`tests/test_media_scan.py`) before touching it. Deleted the branch and
  its now-unused `json` import rather than writing a fixed JSON-aware
  version, since a "fixed" version would still be unverified against any
  real page — exactly the kind of unverified parsing path this project's
  own convention avoids shipping (see the "never build from assumption"
  rule above). Both adapters that call `scan_media_urls` (Granicus,
  Swagit) already get every real media URL they've ever needed from the
  plain regex patterns tried first in the same function. Verified: full
  `pytest` suite green after the change (including an updated version of
  the pinning test, renamed to `..._was_removed_as_dead_code` and
  re-documented rather than left describing code that no longer exists),
  and live against a real Simi Valley Granicus meeting — video URL and
  394 real transcript segments still resolve correctly with the branch
  gone.
- **[Done 2026-08-07] Caption language track picker.** Follow-up from the
  caption language detection fix (below) — `GranicusAssetFinder` already
  detected the real language of every fetched caption track internally
  (the `candidates` list in `app/platforms/granicus.py`) but only ever
  exposed the one it chose, silently discarding any others. Added a new
  `AlternateTranscript {language, segments}` model and
  `ResolvedMeeting.alternate_transcripts` field (`app/platforms/models.py`);
  Granicus's `resolve()` now populates it from every fetched, non-blank
  candidate track other than the chosen one, full segments included (not
  just a language label), so the frontend can switch client-side with no
  second `/api/resolve` round-trip. Frontend: a "Language: [ ]" `<select>`
  next to the Transcript heading (`#transcriptLanguagePicker` in
  `meeting.html`), hidden whenever there's nothing to switch between (the
  common single-track case). `player.js`'s `setupTranscriptLanguagePicker()`
  builds its options from the chosen track + alternates, using
  `Intl.DisplayNames` for a real language name (e.g. "Spanish") rather than
  showing a raw ISO code, and falling back to the code itself if the
  browser can't resolve it; switching reassigns the module-level `segments`
  array and calls the existing `renderTranscript()`, so search/highlighting/
  auto-scroll all keep working against whichever track is active without
  separate wiring.

  No real multi-caption-track meeting has been found live yet (every
  sample checked so far, like Simi Valley clip 2840, turned out to have
  exactly one track, just sometimes mislabeled) — confirmed live against
  Simi Valley that the field correctly stays `[]` and the picker stays
  hidden in that case, no regression. The actual multi-track code path
  was verified with a mocked `resolve()` (two synthetic VTT tracks, one
  English one Spanish): correctly chose English (matches
  `TARGET_LANGUAGE`) and carried the Spanish track through
  `alternate_transcripts` with its full 20 segments intact. The frontend
  switcher was verified in a real browser (`mcp__Claude_Browser__*`) by
  injecting synthetic two-track data into a live-rendered meeting page and
  driving the actual shipped `setupTranscriptLanguagePicker()`/
  `renderTranscript()` functions: the picker showed "English"/"Spanish"
  options, selecting "Spanish" correctly swapped the rendered transcript
  text and the global `segments` state, and the heading-row layout
  (`.transcript-heading-row` flex, `justify-content: space-between`) placed
  the picker at the row's right edge with no overlap against the "Transcript"
  heading. Confirmed the new field round-trips harmlessly through
  `archive_client.push()` — the Archive's `IngestRequest` schema
  (`archive/main.py`) has no `alternate_transcripts` field and Pydantic
  ignores unrecognized fields by default, so it's silently dropped there;
  deliberately resolver-only, since the Archive already has its own
  separate mechanism for multiple languages (`TranscriptVersion` rows,
  its own version picker).
- **[Done 2026-08-07] Real bug: a URL already cached locally never got
  backfilled into the Archive.** `/api/resolve`'s local-cache-hit branch
  (`app/main.py`) returned the cached payload directly without ever
  reaching the "push to the Archive" step, which only ran on a fresh live
  resolve — so any URL cached before the Archive integration existed, or
  while `ARCHIVE_BASE_URL` was unset/misconfigured, could never become a
  permanent page on its own, since every future resolve of that exact URL
  just kept serving the local cache. Confirmed live via `psql` on Simi
  Valley's `meeting_resolutions` row (`hit_count: 3`, predating the Archive
  integration). Fixed by making the local-cache-hit branch opportunistic:
  if the cached payload has real content (`segments` or `agenda_items`)
  and the Archive lookup at the top of `resolve()` already came back empty
  for this URL, fire the same `archive_client.push()` background task the
  fresh-resolve path uses. Verified live end-to-end with two local uvicorn
  processes (resolver + Archive, SQLite fallback): resolved a real Simi
  Valley meeting (clip 2840, 394 segments + 17 agenda items) with
  `ARCHIVE_BASE_URL` unset to reproduce a pre-Archive cached row, then
  restarted the resolver with the Archive wired up and re-resolved the
  same URL — `/internal/lookup` 404'd (Archive genuinely didn't have it
  yet), the local cache served the response, and the new opportunistic
  push fired and succeeded (`/internal/ingest` 200), after which
  `/internal/lookup` for that URL correctly returned a real `/m/{slug}`.
  Didn't build the one-time backfill pass (the other option raised in the
  original item) — the code fix closes the gap going forward for every
  URL as it's next resolved, which covers the real-world case without a
  separate one-off script.
- **[Done 2026-08-06 for Legistar/CivicPlus; investigated for PrimeGov —
  not applicable] Unsupported-platform failure is too blunt.** Fixed for
  Legistar and CivicPlus specifically: both delegate to the embedded
  Granicus link when present, and a calendar/listing page returns a
  pick-list of real meetings rather than a bare error (see Platform
  coverage section below). The remaining "no adapter at all" case is only
  PrimeGov today (detected but unregistered) — investigated whether the
  same "find an embedded supported-platform link, then delegate" pattern
  would help there: checked 3 real PrimeGov cities (Los Angeles, San Jose,
  Petaluma) and all three embed video via a **YouTube** iframe player,
  not a link to any currently-supported vendor platform. Unlike
  Legistar/CivicPlus (which really are just wrappers around Granicus),
  PrimeGov is a genuine distinct video host — the "find a supported
  link" fallback had nothing to find here, so a real PrimeGov/YouTube
  adapter was needed. **[Done 2026-08-07] Built — see the PrimeGov/
  YouTube entry in Platform coverage below.** (The "video ID not
  statically present" claim above turned out to be based on checking a
  PrimeGov URL shape without a video at all -- the shape a real shared
  link uses does have it, directly in the page HTML.)
- **[Done 2026-08-06] Zero-caption Granicus meetings — investigated with
  fresh real meetings** (since the original test clip IDs weren't recorded
  anywhere, re-tested against a current real meeting per flagged city:
  Cupertino, Mountain View, Berkeley, Paradise Valley AZ, San Diego city).
  Findings: Cupertino and San Diego now resolve real captions fine
  (2191 and 7349 segments) — the original zero-caption cases were likely
  specific to those particular old meetings, not a systemic bug. Berkeley
  and Paradise Valley AZ have a genuinely blank source `captions.vtt`
  (confirmed by fetching it directly — the standard 8-byte
  `"WEBVTT\n\n"` placeholder Granicus creates whether or not captioning
  was ever generated) — already correctly detected and warned about, not
  a bug. Mountain View uncovered a real bug, now fixed (see below).
- **[Done 2026-08-06] Real bug: caption/video-ID guessing used the
  pre-redirect URL, so `MediaPlayer.php?clip_id=...` links (how Granicus's
  own UI shares a link) never got their captions.vtt path guessed at
  all.** Found via the Mountain View investigation above: its page has no
  `<track>` tag (Flowplayer-based UI, not native HTML5 captions), so the
  guessed-path heuristic in `_extract_media_urls` was the *only* way to
  find its captions.vtt — but that heuristic pattern-matched against
  `granicus.com/player/clip/` or `granicus.com/videos/`, which a
  `MediaPlayer.php?view_id=&clip_id=` URL never matches even though it
  redirects to `/player/clip/{id}` immediately. Fixed: `_fetch_page` now
  returns the post-redirect URL alongside the HTML, and all URL-shape
  matching (`_extract_clip_id`, media guessing, RSS view_id/clip_id
  lookup) runs against that instead of the originally-submitted URL.
  Confirmed via real Mountain View, San Francisco, and DC
  `MediaPlayer.php` links — jurisdiction/date/captions all resolve
  correctly now where they silently wouldn't have before.
- **[Done 2026-08-06] Date extraction fixed via RSS `pubDateParts`.**
  `_fetch_channel_info` (renamed in spirit, same function) now also
  matches the resolved meeting's `clip_id` against the
  `ViewPublisherRSS.php` feed's `<item>` entries and reads the structured
  `<gran:pubDateParts yr= mo= day=>` attributes — confirmed live against 3
  of the originally-failing cities: San Francisco (clip 52945, page has
  no date signal anywhere — title is just "Board of Supervisors - Regular
  Meeting" — RSS gives 2026-07-28 correctly), DC (clip 10801 → 2026-07-14),
  Mountain View (clip 5389 → 2026-07-09). San Diego and Cupertino's fresh
  test meetings already had dates in their titles, so weren't a live
  reproduction of the original bug, but the RSS path is exercised for
  them too. Alexandria VA remains unfixed and is tracked as a live item
  in [BACKLOG.md](BACKLOG.md).

- **[Done 2026-08-06] Jurisdiction/title metadata cleanup.** Fixed via three
  tiers: the Granicus RSS channel title (constant per `view_id`, confirmed
  format `"{Jurisdiction}: {Body} (Videos Feed)"` across 6 cities) is tried
  first and also used to prepend the governing body to titles that don't
  already name one; then a "City/County/Town of X" (or reversed "X
  County") text search across page body *and* meta description (the
  sdcounty.granicus.com case only had it in `<meta name="description">`,
  invisible to `soup.get_text()`); then `wordninja`-based subdomain
  segmentation as a last resort (`sandiego` &rarr; "San Diego" instead of
  "Sandiego"). Applies to Legistar/CivicPlus too since both delegate to
  GranicusAssetFinder. One known residual gap: `dc.granicus.com` still
  resolves to jurisdiction "Dc" — no page-text signal or view_id available
  to do better, and decided not worth a DC-specific hardcode for one city
  (wontfix, not tracked as a live item).

- **[Done 2026-08-06] Caption quality heuristic.** `is_likely_garbled()`
  (`app/utils/vtt_parser.py`, shared by Granicus/eScribe/CA Legislature)
  flags a transcript as likely-garbled-at-the-source when >6% of its
  words are short junk fragments (≤2 letters, not a real short English
  word like "a"/"to"/"is"). Threshold calibrated against real samples:
  Alexandria VA's confirmed-garbled captions (clip 6490 — fragments like
  "test meele first item on t", "last meeting.Oa") sit at ~17%, while four
  independently-confirmed clean real sources (Boston, San Diego, DC, San
  Francisco) all sit under 2% — comfortable margin on both sides. Live
  re-verified after implementation: Alexandria correctly gets the new
  warning message (with the same manual-transcription contact CTA as the
  blank-VTT case), Boston/SF/DC/San Diego/Cupertino all resolve with zero
  false positives.

- **[Done 2026-08-06] Caption language detection.** Fixed: found via live
  review that Simi Valley clip 2840's only caption track is labeled
  `srclang="en"` on the page but is actually Spanish content (confirmed by
  fetching the raw VTT). `GranicusAssetFinder` now detects the real
  language of caption text via `langdetect` rather than trusting the page
  label, prefers a track matching `TARGET_LANGUAGE` ("en") when multiple
  tracks exist, and surfaces a warning when the best available track
  doesn't match. Follow-up (UI dropdown to let the user pick between
  multiple language tracks when more than one exists) built 2026-08-07 —
  see the "Caption language track picker" entry above.

- **[Done 2026-08-06] San Francisco's ALL CAPS captions normalized.**
  `_normalize_shouting_caption()` (`app/utils/vtt_parser.py`, runs inside
  `parse_vtt` so every platform benefits) detects a track as
  all-caps-at-the-source (essentially zero lowercase letters across a
  40+-letter sample) and re-cases it to sentence case, capitalizing after
  real sentence punctuation across cue boundaries (cues are joined with a
  placeholder before casing, so a sentence split mid-cue isn't treated as
  two separate sentence starts) rather than per-cue. Confirmed live: a
  real San Francisco Board of Supervisors meeting (clip 52945) that was
  genuinely ALL CAPS at the source now renders as normal sentence-case
  text (e.g. "the july 28th 2026 regular meeting of the san francisco
  board of supervisors. Madam clerk, please call the roll."). Spot-checked
  the other 6 meetings with real transcripts (2026-08-06): 5 of 6 English
  ones (San Diego, Oakland, Boston, San Francisco, DC) are genuinely
  readable with only minor rough patches (a few garbled words
  mid-Boston); Alexandria VA remains the one clear outlier at genuinely
  unreadable quality — now caught by the caption quality-detection item
  above.

## UX polish (from live review, 2026-08-06)

- **[Done 2026-08-06] Video player sizing, play button, poster, and
  awkward-pause-on-play.** All four addressed together: the video wrapper
  now locks a 16:9 aspect-ratio via CSS so it never collapses to a tiny
  default box; a large, obvious overlay play button replaces the small
  native control-bar triangle; and a one-time muted-play-then-pause on
  `loadedmetadata` both renders a real first frame (serving as a poster,
  no separate thumbnail-fetch needed) and pre-buffers the initial
  segments, so the user's actual first play click starts instantly instead
  of visibly waiting to buffer — confirmed this measurably works in
  testing. Verified in-browser on desktop and mobile widths, and confirmed
  no regression to deep-link seeking (a real risk: the warm-up's play/pause
  could have clobbered a pending deep-link seek, since `currentTime` set
  before metadata loads just queues as the "default playback position" —
  fixed by capturing and restoring that value instead of resetting to 0).
- **[Done 2026-08-06] Transcript search, per-line link icon, manual
  timestamp entry, sticky toolbar.** All four verified end-to-end against
  a real 1073-segment Boston meeting. Search mirrors browser Ctrl+F
  (highlight all matches, "N/M" count, prev/next + Enter/Shift+Enter
  navigation — confirmed 21 real matches for "sidewalk"). Each transcript
  line has a chain-link icon that copies a link to that line without
  moving playback (distinct from clicking the timestamp, which seeks);
  after a follow-up look it was enlarged (14px&rarr;17px) and now also
  shows at rest (opacity 0.6) on whichever segment is current when the
  video is paused, suppressed during playback so it doesn't flicker line
  to line with auto-scroll. A "Go to time" input (accepts H:MM:SS, M:SS,
  or seconds) sits in the video toolbar and works even with no transcript,
  since deep-linking to a moment — not the transcript — is the primary
  goal. The toolbar itself is now `position: sticky` so it stays reachable
  when scrolling past it, addressing the original auto-scroll-fights-you
  complaint.
- **[Done 2026-08-07] "View original source" link on the meeting page.**
  Links back to the original government meeting page (`data.source_url`)
  in a new tab, styled small/muted so it reads as an outbound link rather
  than the page's own title. `source_url` is a required field on
  `ResolvedMeeting`, so this renders for every successfully-resolved
  meeting regardless of platform.
- **[Done 2026-08-07] Live playhead timestamp where the transcript
  would be.** Deep-linking to any moment already worked with zero
  transcript (`t=` has always been the sole seek-position authority),
  but nothing signaled that — a meeting with no transcript/agenda
  previously just showed a warning and a dead end. `#transcriptMissing`
  now shows a large live-updating timestamp (`updateNoTranscriptTime()`
  in `player.js`) plus a "Copy link to this moment" button, sharing one
  click handler with the existing toolbar button. Surfaced and fixed a
  real gap: the timestamp is now also updated immediately after
  `applyDeepLink()`, not just on `timeupdate` — for YouTube specifically,
  `timeupdate` is only polled while actually playing, so a paused/
  autoplay-blocked load would otherwise show a stale "0:00" instead of
  the real deep-linked position. Verified live against Paradise Valley
  AZ's confirmed blank-caption meeting.

- **[Done 2026-08-07] Newsletter signup box redesign.** Resolved the
  open question in favor of a new-but-consistent treatment: `.newsletter-btn`
  is a sibling to `cassette-btn` (same bold-mono/chunky-border family)
  but deliberately not `cassette-btn` itself — "sign up" isn't a "rewind
  to a moment" action, so it's solid navy instead of the reel-icon
  gimmick, keeping `cassette-btn` reserved for the two buttons its own
  scoping comment already calls out. Input now matches the homepage's
  fused-pill sizing (48px height, matching border-radius split) instead
  of plain unstyled Bootstrap. Added a small dymo-label-style kicker tag
  ("STAY IN THE LOOP") on the dedicated `/subscribe` page — reuses the
  wordmark's signature visual element as a secondary section tag.
  Verified visually and confirmed the submit flow still works unchanged.
- **[Done 2026-08-07] "Get Updates" link in the site nav pointing at
  the email signup.** Originally shipped as a same-page
  `#newsletterForm` anchor to a footer form; replaced same-day (see the
  dedicated `/subscribe` page item below) after the user pointed out
  three real problems with the anchor approach — no visible cue if
  you're already scrolled to the bottom, breaks Ctrl+click/open-in-new-
  tab, and a shared link lands people wherever the anchor happens to be
  rather than a clean destination. The nav link now points at
  `/subscribe` directly.
- **[Done 2026-08-07] Dedicated `/subscribe` page, replacing the
  footer-anchor approach above.** New `GET /subscribe` route +
  `subscribe.html` holds the actual signup form now (autofocused input,
  no anchor-jump needed). Nav's "Get Updates" and the About page's
  "Subscribe to get updates" both link straight to `/subscribe`. The
  sitewide footer keeps a plain text link to it (`request.url.path`
  check in `base.html` suppresses that link specifically on
  `/subscribe` itself, so the page doesn't show the same prompt twice).
  `newsletter.js`'s anchor-focus workaround was removed since it's no
  longer needed. Verified: page renders with the email input
  autofocused, footer link correctly present/absent on the right pages,
  and the full submit flow still works end-to-end (confirmed the
  graceful "not available" message renders when Resend isn't
  configured, via a direct programmatic submit after a manual click
  raced the screenshot).

- **[Done 2026-08-07] Spinning cassette-reel animation on the "please
  wait" fetch message.** `player.js`'s loading-state line now renders
  two `.cassette-reel` SVGs (reusing the existing icon markup) with a
  new `.spinning` modifier class — a slower 1.6s spin than the 0.8s
  hover flourish elsewhere, since this can run for up to ~20s and a
  quick spin reads frantic sustained that long. Verified the animation
  is actually wired (not just present in markup) via computed style —
  `animationName: "reel-spin", animationDuration: "1.6s"` — after
  confirming a byte-fresh fetch of `style.css` contains the rule.

## Platform coverage

- **[Done 2026-08-14] New adapter: Seattle Channel (`seattlechannel.org`)
  — confirmed live against two independent real meetings on the
  `/videos?videoid={id}` page shape before writing any code, per this
  repo's own convention** (the original investigation, 2026-08-12, only
  had one confirmed example, x189286; x184865 was fetched fresh the same
  session as this build to confirm the shape generalizes). Real data this
  platform has that most unsupported ones don't: a direct, unauthenticated
  `.mp4` URL, real populated SRT captions, and real per-agenda-item
  `data-seek` timestamps — richer coverage than several already-shipped
  adapters manage.

  **The reliable disambiguator, confirmed against both real samples**: the
  primary video's JW Player instance is always literally
  `jwplayer('vidPlayer')` — a fixed, hardcoded element id — while any
  *other* video embedded further down the same page (a real "related
  story" clip, confirmed present on the x184865 sample) uses a different,
  per-video numeric id (`jw4052508` on that sample). `seattlechannel.py`
  slices the HTML to the `vidPlayer` block specifically, bounded by the
  `playerInstance.on('complete', ...)` call that immediately follows every
  real `setup()` call in this template — confirmed this is what keeps the
  adapter from ever picking up the unrelated video's file/caption/title,
  not just a theoretical concern (a real fixture test exercises exactly
  this).

  **Deliberately scoped narrower than the whole domain**: `detect_platform()`
  only claims `seattlechannel.org` URLs whose path is exactly `/videos`
  *and* carry a `videoid` query param — the older
  `/mayor-and-council/city-council/city-council-all-videos-index?videoid=...`
  feed page (many *other* meetings' videos below the requested one, the
  original 2026-08-12 find) and a bare `/videos` with no `videoid` (an
  ambiguous case never actually seen live) both fall through to
  `generic_fallback.py` instead, which already handles the `/videos?
  videoid=` shape reasonably via its own JW-config scan pattern (see this
  file's 2026-08-14 generic-fallback rebuild entry) and the feed page via
  its existing scan. Rather than guess at `CalendarPageError`-style
  candidate-list handling for the no-`videoid` case with zero real
  examples to verify against, this stays on the already-adequate fallback
  path — narrower scope, but every claimed shape is real-verified, not
  speculative.

  **Real gap found building this, not fixed here (out of scope — a shared
  `vtt_parser.py` heuristic, not this adapter)**: the first fixture
  attempt trimmed the real caption file to ~60 lines, which turned out to
  be a genuine trap. This transcript's heavy real use of
  `&gt;&gt;&gt;`/`&gt;&gt;` speaker-change markers (nearly every line) means
  each `&gt;`'s own embedded lowercase letters (`g`, `t`) skew
  `normalize_shouting_caption()`'s letter-ratio heuristic — it runs
  *before* entity-unescaping, by design (see `unescape_caption_entities()`'s
  own docstring: "run once, last") — so over a short sample the lowercase
  ratio crosses `_SHOUT_LOWERCASE_RATIO_MAX` and the heuristic concludes
  the ALL-CAPS transcript "isn't really shouting," leaving it uppercase.
  Confirmed against the real, full 7,320-line file that this is purely a
  too-small-sample artifact, not a real production gap — normalization
  correctly fires once there's enough real prose to dilute the marker
  density (confirmed to flip around the 700-line mark on this real file).
  Fixture grown to a real 900-line/225-cue excerpt instead of casually
  reordering a deliberately-ordered shared pipeline.

  Live-verified end to end against both real URLs through a local resolver
  instance: x184865 ("City Council 3/3/2026") returns 1,830 real
  transcript segments, `en`, no warnings, and 5 real agenda items with
  `endOffset` chained to the next item's start (same convention as
  Granicus/IQM2/LIMS); x189286 ("City Council 8/11/2026," the original
  find) resolves equally cleanly. 8 new fixture-backed tests
  (`tests/test_seattlechannel.py`), full suite green (729 tests).

- **[Done 2026-08-13] New adapter: CHAMP/ChampDS (`play.champds.com`) —
  confirmed live against 6 independent real customers before writing
  any code, per this repo's own convention (the original investigation
  had only checked Atlanta, GA).** Fetched real API responses directly
  (`playapi.champds.com/{customer}/event/{id}`, a plain unauthenticated
  JSON GET) for Auburn NY, Gillette WY, Marlborough MA, Saco ME, and
  Worcester MA (found via a live web search for other real
  `play.champds.com` URLs) — every one matched the original Atlanta
  shape for title/date/jurisdiction, but split roughly evenly on video
  availability: `MediaInfo.DownloadURL` (a direct MP4) present for
  Atlanta and Auburn only; the other 4 (the actual majority) have only
  `MediaInfo.VOD2` (a relative HLS path).

  **Real, confirmed blocker found while verifying VOD2 playback, not
  just theorized**: before wiring VOD2 in as `video_url`, checked
  whether the reconstructed `.m3u8` URL is actually fetchable from this
  site's own context. It isn't — `curl` confirmed
  `securestream10.champds.com` enforces a strict
  `Referer: https://play.champds.com/` check (a bare request, this
  site's own real domain as referer, and an unrelated third-party
  referer were all rejected with 406; only champds.com's own referer
  worked). The master playlist's own sub-resources (`index-v1-a1.m3u8`,
  then real `.ts` segments) are relative URLs on the same host, so the
  same check would presumably block those too, not just the master file
  — confirmed the block isn't scoped to one request. Embedding this URL
  directly in `<video>`/hls.js on this site would send this site's own
  referer, not champds.com's, and 406 in the browser at playback time,
  not resolve time — the kind of "looks like it works, silently breaks
  live" gap this repo's conventions exist to avoid. Decided *not* to
  ship a link that would fail this way: `_extract_video()` only returns
  `DownloadURL`-shaped MP4s; the VOD2 case still returns full
  metadata/agenda info with an honest "no video found" instead. Making
  VOD2 playable for real would need a genuine streaming reverse-proxy
  (fetch server-side with the right header, rewrite every segment URL
  inside the playlist to route through it) — real, scoped follow-up
  work, not attempted this pass (see the still-open note in
  `BACKLOG.md`, folded back into the closed entry there since the
  adapter itself is done).

  **Also found while building**: real per-item agenda text exists
  (`Agenda.AgendaItems`, e.g. Gillette's real "A. Call to Order") but
  with no per-item time offset, only ordering — same shape mismatch as
  Legistar's own "Meeting Items" table (see the Legistar `agenda_link`
  entry above), so not forced into `agenda_items`. `Agenda.Attachments`
  (e.g. Marlborough's real "Packet" PDF) is a better fit for the
  single-link `agenda_link` field instead — the real download path
  (`/ATT/{customer}/{MediaFileLocation}/{MediaFileName}`) was found by
  reading `play.champds.com`'s own `cds.event.js` (`getAttachmentPath()`)
  rather than guessing, confirmed live with a real `curl` (200,
  `Content-Type: application/pdf`, real `Content-Length`).
  `MediaInfo.Captions` was empty on all 6 customers checked — no
  positive example, so left unattempted, same "don't claim a caption
  path works without a positive example" convention as CivicClerk/
  eScribe.

  **Verified three ways**: 9 new unit tests (real trimmed JSON fixtures,
  not invented shapes) covering the direct-MP4 case, the
  VOD2-deliberately-withheld case, agenda-link extraction, the
  no-captions warning, and error paths; a real local resolve against
  all 6 live customer URLs (confirmed title/jurisdiction/date/
  video_url/agenda_link match expectations); direct `curl` verification
  that Atlanta's MP4 download URL is genuinely playable (200, real
  `Content-Length`) while Marlborough's VOD2 URL would 406 in this
  site's context. Full suite green (625 tests). Also extended the
  shared `tests/aiohttp_mock.py`'s `FakeResponse.json()` to accept
  (and ignore) a `content_type` kwarg, matching real aiohttp's
  `content_type=None` skip-check behavior — needed since ChampDS's real
  API serves JSON as `Content-Type: text/html` (confirmed live), not
  `application/json`, the first adapter here to hit that.

- **[Done 2026-08-12] New adapter: Detroit, MI's Cablecast video portal —
  reversed an earlier "unsolvable, dead endpoint" call after being
  pushed back on, and it turned out to be genuinely solvable.** The
  original Wave 2 research's sample URL
  (`detroit-vod.cablecast.tv/CablecastPublicSite/`) timed out on a
  direct HTTPS request and was logged as unreachable. Turned out to be
  half right: the portal's HTTPS (port 443) genuinely does hang
  indefinitely for the *entire* domain (confirmed via direct `curl`:
  15s+ timeout on HTTPS, under a second on plain HTTP) — but the site
  itself is very much alive, and Detroit's own city website
  (`detroitmi.gov`) links this exact portal today, correctly using a
  plain `http://` URL rather than `https://`.

  Given a real show URL (`detroit-vod.cablecast.tv/internetchannel/
  show/{id}?site=1`), the page is a Remix.js SSR app embedding the
  requested show's full data — plus a ~35-item "related shows"
  carousel — in one `window.__remixContext = {...};` JSON blob.
  `_find_show()` recursively searches that whole tree for the object
  whose own `showId` matches the URL's, rather than assuming a fixed
  key path (Remix's loader-data nesting is keyed by route id, not
  worth hardcoding). The real video is a direct, unauthenticated
  `.m3u8` on a *different* subdomain (`reflect-detroit-vod.cablecast
  .tv`, confirmed reachable over HTTPS just fine — only the portal
  domain itself hangs) — already fully supported by this app's existing
  hls.js pathway, zero new frontend work needed, unlike Aurora/Viebit.

  `resolve()` always fetches over plain HTTP regardless of what scheme
  was pasted (`_force_http()`), so the more natural `https://` paste
  doesn't hang the whole resolve — verified this doesn't regress
  `source_url` (still records exactly what the user pasted, even though
  the fetch itself goes over HTTP).

  Deliberately scoped to this specific portal template
  (`cablecast.tv` domain *and* an `/internetchannel/show/{id}` path),
  not a general "any `*.cablecast.tv` domain" rule — Charlotte, NC's
  confirmed Cablecast site uses a visibly different template (a
  "DOWNLOADS" tab exposing plain `store-N/...-vN/vod.mp4` +
  `transcript.en.txt` files directly, no Remix JSON, HTTPS works fine
  there), so this isn't assumed to generalize to every Cablecast
  customer without its own confirmed sample.

  `vodTranscripts` is a real field in the schema but was an empty `[]`
  on every one of 36 real shows checked on the one page fetched — per
  this repo's "don't claim a data path works without a positive
  example" convention, no extraction is attempted; only whether it's
  non-empty is checked, so a future real populated example can be wired
  in without first needing to prove the field exists.

  Confirmed live end-to-end against the real show the user found
  (`show/15323`, "Detroit City Council Formal Session 07-28-2026"):
  correct title/date/jurisdiction, a real playable `.m3u8` URL, honest
  "no transcript" warning. Also confirmed a pasted `https://` URL
  resolves in ~0.3s instead of hanging. New `app/platforms/cablecast.py`
  + fixture (`tests/fixtures/cablecast/detroit_show_15323.html`, a real
  530KB fetched page), registered in `detect_platform()`. 9 new tests
  (`tests/test_cablecast.py`). Full suite green (476 tests, up from
  467).

- **[Done 2026-08-12] New adapter: CivicWeb (iCompass, a Diligent brand),
  resolving the Wave 2 research's open question — confirmed live it's a
  YouTube-delegating platform, not a new video host.** The research had
  found CivicWeb hosting Dallas County, TX's meeting calendar but
  flagged the actual video-embed shape as JS-rendered/unconfirmed. Live
  browser inspection (Claude in Chrome, since the in-app Browser tool was
  down) of a real meeting's "Video" tab found the real network call: a
  plain, unauthenticated JSON API,
  `{origin}/api/videolink/{meetingId}`, returning `YouTubeEventId`
  directly — same delegation shape as PrimeGov (calls
  `YouTubeAssetFinder.resolve_video_id()` directly with the original
  CivicWeb URL preserved as `source_url`, not the Legistar/CivicPlus
  pattern where `source_url` ends up being the delegated platform's own
  URL).

  **Real bug found and fixed mid-build**: `/api/videolink/{id}`
  specifically double-encodes its JSON — the raw response body is a JSON
  *string literal* (`"[{...}]"`, quotes included) containing the real
  array as text, not the array directly — a WCF/`.svc`-family quirk,
  confirmed live via a direct `aiohttp` call showing `response.json()`
  returns a Python `str`, not a list. The separate `meetingData` endpoint
  (used for the title) doesn't have this quirk. `_fetch_json()` now
  parses a second time whenever the first pass still yields a string, so
  the same helper handles both endpoints' shapes correctly.

  Title comes from `MeetingsService.svc/meetings/{id}/meetingData`'s
  `Name` field, date from the videolink API's own `MeetingDate`,
  jurisdiction parsed from the page's own `<title>{Jurisdiction} -
  Meeting Information</title>` pattern. Confirmed live end-to-end: real
  title ("Commissioners Court - Aug 04 2026"), correct date, jurisdiction
  ("Dallas County"), and an 8,144-segment real transcript via YouTube
  delegation. Real per-item deep-linking data exists in the same schema
  (`IndexPoints`/`LocalIndexPoints`, matching a camera-icon UI seen on
  the page) but was empty on this one real meeting — not built, per this
  repo's "don't claim a data path works without a positive example"
  convention; flagged in BACKLOG.md if a populated example ever turns
  up.

  New `app/platforms/civicweb.py`, registered in `detect_platform()`
  under the `civicweb.net` domain. 5 new tests
  (`tests/test_civicweb.py`). Full suite green (466 tests, up from 461).

- **[Done 2026-08-12] New adapter: Aurora, CO's own council video site
  (auroratv.org), found in a Wave 2 platform-coverage pass and confirmed
  buildable via direct live research.** A Drupal 10 site whose every
  video page embeds its JW Player config as a plain top-level object
  inside Drupal's own `drupalSettings` JSON blob
  (`<script type="application/json" data-drupal-selector="drupal-
  settings-json">`), server-rendered — no JS execution needed, unlike
  most other JW-Player sites. That blob's `mp4_url` is a real, direct,
  unauthenticated file served via CloudFront in front of Cablecast's
  storage (Aurora happens to use Cablecast as its underlying video host
  — the same vendor found independently on Charlotte/Detroit/Columbus,
  OH — see BACKLOG.md), and confirmed live to already work with zero
  frontend changes: `ResolvedMeeting.video_format="mp4"` already gets
  native `<video>` playback via `player.js`'s existing `initNativeVideo()`
  path.

  **Real gap found and fixed mid-build, not assumed correct from the
  schema**: the blob's top-level `video_caption` key looks like it should
  be the caption URL, but is actually a server filesystem path
  (`/home/atowntv/public_html/sites/default/files/...`), not fetchable —
  only `jw_data.caption_file_path` is the real `https://` URL. Caught by
  actually resolving a real meeting and seeing the caption count come
  back 0 despite a direct `curl` of that same file succeeding — not
  discovered by reading the schema alone. Confirmed live end-to-end
  against `auroratv.org/video/regular-meeting-aurora-city-council-
  june-22-2026`: real 5,310-segment English transcript, real title/date
  parsed from `<title>`, jurisdiction hardcoded to "Aurora, CO" (a
  single-city custom site, same pattern as `slc.py`).

  **Genuinely unconfirmed, flagged rather than assumed**: whether
  `auroratv.org` or the CloudFront-fronted Cablecast storage blocks
  requests from Render's cloud IP the way YouTube/Riverside County/
  Minneapolis LIMS/SLC do — no Cloudflare/WAF signature was found in
  either host's response headers during development (plain Apache +
  CloudFront, same shape already confirmed working for a different
  Cablecast city's files), but that's not proof against an IP-based
  block specifically, which wouldn't show up in headers at all. Needs a
  real live-production resolve to confirm — not yet done as of this
  entry.

  New `app/platforms/aurora.py`, registered in `detect_platform()`
  (`base.py`) under the `auroratv.org` domain and in
  `register_all_finders()`. 5 new tests (`tests/test_aurora.py`) against
  two real fixtures (the video page + its real VTT captions). Full suite
  green (460 tests, up from 455).

- **[Done 2026-08-09] Built a generic "try our best" fallback for any
  URL `detect_platform()` doesn't recognize**, directly from the user's
  own request and mockup layout: today, pasting an unsupported city's
  URL got a flat `unsupported_platform` error with zero attempt made,
  every time. `app/platforms/generic_fallback.py`'s
  `GenericFallbackAssetFinder` is registered under `platform_name =
  "unknown"` — the exact string `detect_platform()` already returns for
  anything unmatched — so `get_finder("unknown")` now finds this instead
  of raising, with no changes needed anywhere else in the dispatch path.

  Reuses existing infrastructure almost entirely rather than building new
  parsing from scratch: a plain (non-headless-browser — that's reserved
  for known Cloudflare-gated platforms specifically) fetch, checked first
  for an embedded/linked YouTube video (a huge share of small-city sites
  just embed a YouTube video with no dedicated platform at all) —
  delegates to `YouTubeAssetFinder` for real video + real captions when
  found, the best possible outcome here. Falls back to `media_scan.py`'s
  existing generic `.m3u8`/`.mp4` scanner (the same one Granicus/Swagit
  already use, not reimplemented) plus any caption-shaped URL found in
  the same scan, parsed via the same `parse_captions_by_extension()`
  dispatch every real adapter goes through. Deliberately does **not**
  attempt agenda-item detection — every other adapter's agenda parsing is
  tied to that platform's own known page structure, and there's no
  reliable generic pattern to reuse the way there is for media URLs;
  guessing badly would be worse than agenda items just being absent
  (which the existing UI already handles fine everywhere it's optional).

  **Zero frontend changes needed** — `initVideo()` already handles any
  `video_url`/`video_format` combo generically, and the no-transcript
  live-playhead deep-link tracker (built earlier, see this same file)
  already covers "no transcript, but you can still link to a moment" for
  any video, not just ones from a known platform. Every outcome (nothing
  found / video found / video + transcript found) gets an honest,
  specific warning message instead of a flat error, matching the user's
  own requested copy fairly closely.

  Verified end-to-end through the real, unmodified running app (not just
  fixture tests) using a local test page standing in for a genuinely
  unrecognized small-city site with an embedded YouTube iframe — resolved
  correctly via real YouTube delegation with real auto-generated
  captions, rendered with the honest "we don't officially support this
  website yet, but found a video and did our best" message directly under
  the video, and the deep-link/live-playhead tools worked identically to
  every other platform. 5 new fixture-backed tests
  (`tests/test_generic_fallback.py`) covering the YouTube-embed path,
  direct-media-plus-captions path, no-video-found path, and a page fetch
  failure. Full suite (235 tests) passing.

  **Real architecture note, deliberate**: this makes the
  `unsupported_platform` error branch in `app/main.py`'s `/api/resolve`
  (and its matching outcome bucket in `app/db/outcomes.py`) effectively
  unreachable going forward — every URL now resolves to *something*.
  Left in place rather than removed, a conservative choice: `get_finder()`
  could still raise for a genuinely different reason later.

- **[Done 2026-08-09] Two new platforms shipped — Minneapolis LIMS and
  Salt Lake City's council meeting-recap pages — both previously
  completely unsupported, both needing this repo's first genuinely new
  kind of dependency: a real headless browser.** Real production
  impact: pasting either city's real URL into the app today returns a
  plain `unsupported_platform` error with zero results — confirmed by
  testing both against the live, unmodified app immediately before this
  work started, specifically so "does this actually work now" could be
  answered against a real before/after, not just a mockup.

  **The path here started from a live mockup** (see the "SLC multi-video"
  entry earlier the same day) that proved the UI needed zero frontend
  changes for this data shape, but used a hand-picked video id to
  sidestep the real blocker (Cloudflare) rather than solve it. This
  entry is that blocker actually getting solved for real.

  **`app/platforms/headless_browser.py`** — a shared, lazily-launched,
  reused Playwright Chromium instance (`fetch_via_browser(url) -> html`).
  The real fix that worked is much smaller than a full "stealth" setup,
  confirmed by isolating each variable independently rather than
  combining guesses: a plain headless launch still gets served the
  Cloudflare challenge page (Playwright's default context sends a
  User-Agent that identifies itself as headless — an easy signal for
  Cloudflare's bot detection); `--disable-blink-features=
  AutomationControlled` alone didn't fix it; extra wait time alone
  didn't fix it; **a normal desktop Chrome User-Agent + a real viewport,
  alone, did** — confirmed against both real sites independently before
  combining. Also confirmed and ruled out as easier alternatives:
  client-side `fetch()` from a real visitor's own browser (blocked by
  CORS on both sites, no `Access-Control-Allow-Origin`), and iframing
  the government's own page from a different origin (works for SLC, real
  content renders; blank for Minneapolis LIMS despite the site loading
  fine at the top level — a genuine difference between the two, not
  pursued further as a real feature once headless-browser fetching
  itself was confirmed to work for both).

  **`app/platforms/lims.py`** — Minneapolis's own "Legislative
  Information Management System"
  (`lims.minneapolismn.gov/MarkedAgenda/CI/{id}`). Two headless fetches
  per resolve (confirmed the JSON data isn't embedded in the agenda
  page's own HTML, so there's no way to get both from one fetch): the
  agenda page for title/date/jurisdiction (parsed from its own `<title>`
  tag, e.g. `"Climate & Infrastructure Committee Agenda 8/6/2026 1:30 PM
  - City of Minneapolis"`), and `GET /MeetingYoutubeVideo/{id}` (same
  numeric id) for the real video + `SerializedVideoTimestamps` — a
  genuinely richer signal than most already-supported platforms give:
  real per-agenda-item start times, not just a title. That JSON is a
  category → item tree, not a flat list (a "Discussion" category can
  itself have a real timestamp *and* contain several individually-
  timestamped items) — `_flatten_timestamps()` surfaces every entry with
  a real timestamp at any nesting level, confirmed live this matters (a
  real sample's "Consent" category has its own timestamp and no files,
  which a leaves-only flatten would have dropped entirely). Delegates to
  `YouTubeAssetFinder` for the video itself and real captions.

  **`app/platforms/slc.py`** — Salt Lake City's `slc.gov/council/
  *-meeting-recap/` pages. Built directly on the corrected finding from
  the same day's earlier mockup work: these pages do **not** embed
  multiple distinct videos (the original assumption) — every real page
  checked has exactly one video with several `t=`-timestamp links into
  it. Extracts every "(Watch)"-style link's timestamp (handles both real
  `t=1441` and `t=2455s` formats, confirmed mixed on the very same page)
  plus its nearest containing paragraph's own text as the topic, turning
  each into an `agenda_items` entry the same shape LIMS's structured
  data produces. One real, known gap found while building, not chased
  further: a page's single "highlight" story uses a different HTML
  pattern (a "Learn More"/"Watch the Briefing" promo box, not the plain
  "{topic}. (Watch)" shape every other item uses) and gets silently
  skipped rather than parsed — a safe failure mode (no garbage text),
  logged as an open follow-up in BACKLOG.md rather than risking a
  fragile heading-guessing heuristic.

  **`detect_platform()`** gained two new narrow rules —
  `lims.minneapolismn.gov` (exact domain) and `*.slc.gov` scoped
  specifically to the `-meeting-recap` path pattern confirmed across
  real pages, not the whole domain (most of `slc.gov` is ordinary city
  content this app has no reason to try to resolve).

  Verified end-to-end live, not just via unit tests: both real URLs
  against the real, unmodified local app (before: `unsupported_platform`
  for both) and after (real video, real jurisdiction/date, real agenda
  chapters, real transcript) — then in-browser for both, including
  clicking a real agenda-item chapter and confirming the video actually
  seeks (Minneapolis: 53:00 chapter → video jumped to 53:05, transcript
  auto-scrolled to the matching real moment). 15 new tests
  (`tests/test_lims.py`, `tests/test_slc.py`, plus two new
  `detect_platform()` cases in `tests/test_base.py`), all mocking
  `fetch_via_browser` rather than launching a real browser during the
  suite. Full suite (226 tests) passing.

  **Real, deliberately not fully resolved before shipping**: whether the
  new `playwright install --with-deps chromium` build step actually
  works on Render's plain `python` buildpack is unverified — Chromium
  needs real system shared libraries ffprobe never did, and this session
  has no real Render deploy access to test it. Documented prominently in
  `render.yaml`'s own comment and flagged as a live BACKLOG.md item,
  expecting a real possible failure the way the transcription worker's
  own first two deploys hit real OOM crashes, not assumed to work on the
  first try.

- **[Done 2026-08-06] Legistar adapter** — confirmed and built: Legistar is
  purely a calendar/agenda wrapper, video always redirects via
  `Video.aspx?Mode=Granicus&ID1={id}&Mode2=Video` straight to Granicus.
  See `app/platforms/legistar.py`.
- **[Done 2026-08-06] CivicPlus adapter** — confirmed and built, same
  pattern as Legistar: an AgendaCenter listing page (`tr.catAgendaRow`
  rows) has a direct per-meeting video link in `td.media` when video
  exists (confirmed real: `ca-westlakevillage.civicplus.com`, 16 real
  Granicus links across one listing page). No "single meeting" URL shape
  observed — every AgendaCenter URL is a listing, so >1 video row always
  raises the calendar pick-list. See `app/platforms/civicplus.py`.
- **[Done 2026-08-07] Granicus agenda-item chapter-marker fallback,
  same role as CivicClerk's `eventBookmarks`/Swagit's `.playerControl`.**
  When there's no usable transcript, `GranicusAssetFinder` now tries
  `AgendaViewer.php?clip_id={id}&embedded=1` — Granicus's own agenda-index
  feature, when a customer has it turned on, renders each item as
  `<a name="agenda{id}" onclick="top.SetPlayerPosition('0:{seconds}',null)">
  {title}</a>`. Confirmed live: works on Simi Valley (17 items) and San
  Francisco (82 items). Does not help either of the two jurisdictions
  confirmed genuinely blank-caption in the 2026-08-06 zero-caption
  investigation above: Berkeley redirects `AgendaViewer.php` to its own
  external site (`berkeleyca.gov`) instead, with an empty `cuepoints`
  array on the player page too; Paradise Valley AZ redirects it to a
  Google Docs PDF preview, and its `cuepoints` array has real
  timestamps/ids but no titles anywhere to pair them with. Both simply
  return zero items and fall through to the existing "no transcript"
  warning, so this is additive, not a regression, for jurisdictions that
  don't have it. Real ratio of "has native agenda index" vs. "redirects
  elsewhere" across Granicus's full customer base is unknown — worth
  revisiting once more jurisdictions are checked.
- **[Done 2026-08-07] Surface an agenda link even when there's no
  timestamped chapter data (Berkeley/Paradise Valley AZ style).**
  `_fetch_agenda_items()` now returns `(items, fallback_url)` — when
  the native `<a name="agenda...">` structure isn't found but the
  request still resolved to a real page, `fallback_url` is that page's
  URL (`response.url` after `AgendaViewer.php`'s redirect, same pattern
  `_fetch_page` uses for the main page), and `resolve()` appends a
  plain "agenda is available here: {url}" warning instead of
  discarding it. Also fixed to make it *actually* clickable: `player.js`
  was rendering all transcript warnings through `escapeHtml` (plain
  text only), so a URL in a warning would've shown as inert text — new
  `linkifyWarning()` escapes first, then wraps bare URLs in a real
  `<a target="_blank">`. Verified against live Berkeley and Paradise
  Valley AZ (both get `fallback_url`, Simi Valley's 17 real items
  correctly get `None`), and end-to-end in-browser that the rendered
  warning contains a real anchor tag. Not yet investigated: whether
  this redirect-target pattern holds generally across other Granicus
  customers who lack the native agenda index, or is specific to these
  two.
- **[Done 2026-08-07] Dedicated "Agenda" section, structurally separate
  from "Transcript," always loaded regardless of transcript
  availability.** Agenda/chapter-marker data (Granicus's
  `AgendaViewer.php` items, CivicClerk's `eventBookmarks`, Swagit's
  `.playerControl` markers) previously got folded directly into
  `ResolvedMeeting.segments` as if it were transcript content, and only
  when there was no real transcript at all — a reasonable v1 shortcut
  that didn't hold once agenda was meant to be its own thing. Added a
  new `agenda_items: List[TranscriptSegment]` field on `ResolvedMeeting`
  (`app/platforms/models.py`), kept structurally separate from
  `segments` so agenda/chapter data is never mistaken for real
  transcript content. Granicus, CivicClerk, and Swagit adapters now
  populate it unconditionally (agenda fetch decoupled from `if not
  segments:`), so a meeting with both a real transcript and a real
  agenda shows both simultaneously — verified live on Simi Valley
  Granicus (394 real transcript segments + 17 agenda items
  simultaneously). New `#agendaSection` in `meeting.html`, positioned
  between the video and transcript sections; `player.js`'s
  `renderAgenda()` reuses the transcript's `.segment-timestamp`/
  `.segment-link-btn`/`.segment-text` markup for click-to-seek and
  copy-link, but deliberately doesn't participate in
  `findActiveSegment()`'s "currently playing" highlighting or the
  `line=` deep-link param — agenda items are seek-only via `t=`,
  simpler than transcript's fine-grained tracking. `classify_outcome()`
  in `app/db/outcomes.py` now checks `resolved_payload.agenda_items`
  directly instead of inferring the `agenda_fallback` bucket from a
  warning-text marker (`_AGENDA_FALLBACK_MARKER` removed). Verified
  live across three real scenarios: Simi Valley Granicus (transcript +
  agenda both shown), Yountville Swagit (agenda only, 7 items,
  transcript-missing block shows a plain "No transcript found"
  message), Paradise Valley AZ Granicus (no agenda section — no
  timestamped agenda data available — but the existing blank-caption
  warning and clickable agenda-PDF fallback link still render
  correctly in the transcript-missing block). YouTube/PrimeGov adapter
  untouched this round — confirmed it still resolves cleanly with an
  empty `agenda_items: []` (no crash, no regression).
- **[Done 2026-08-06] CivicClerk, Swagit, eScribe adapters built.**
  BoardDocs deliberately excluded — confirmed across 2 real cities (South
  Portland ME, Taos NM) it's a document/agenda platform with no reliable
  video, despite a site-level `bd.videoservice` flag; not worth a
  video-resolver adapter. Also confirmed (Taos NM sample) that agendas
  embedding a live Zoom meeting ID/passcode give no path to a recording —
  Zoom join links and cloud-recording URLs are unrelated and unguessable
  from each other, and Zoom's Recordings API requires OAuth credentials
  tied to the hosting account, not a public lookup. Not building a Zoom
  integration; if a city happens to separately publish a real
  `zoom.us/rec/...` link on a page, normal page-scraping would already
  pick it up like any other link.
- **[Done 2026-08-07] PrimeGov + standalone YouTube adapters.** Two new
  platforms, `app/platforms/primegov.py` and `app/platforms/youtube.py`.
  Confirmed live end-to-end (LA City Council, a real ~100-minute meeting)
  through the full pipeline: resolve, iframe playback, transcript render,
  deep-link seek on page load, click-to-seek from a transcript line, and
  "Copy link to current time" — all working.

  **PrimeGov → YouTube delegation**: confirmed live (`lacity.primegov.com`)
  that a real shared-link meeting page (`Portal/Meeting?
  compiledMeetingDocumentFileId=...`) has `var videoUrl = "{11-char-
  YouTube-id}";` directly in the server-rendered HTML, right next to a
  `youtube.com/iframe_api` script tag — simple regex extraction, no JS
  execution needed. (An agenda-only URL shape, `?meetingTemplateId=...`,
  is what got checked in the original "not statically present"
  investigation above — that page genuinely has no matching recording.)
  Unlike Legistar/CivicPlus's delegation, this preserves the *original*
  PrimeGov URL as `source_url` (calls `YouTubeAssetFinder.
  resolve_video_id()` directly rather than going through
  `resolve_via_platform()`), so "View original source" points back to
  the actual meeting page, not a raw youtube.com URL.

  **YouTube playback**: no direct video file URL exists for YouTube,
  unlike every other platform here — needs an embedded iframe + the
  YouTube IFrame Player API, a structurally different control surface
  (`seekTo()` instead of `currentTime=`, no native `timeupdate` event,
  async player creation) than the native `<video>`/hls.js pathway.
  `player.js` now wraps whichever one is active behind a shared
  `{currentTime get/set, play, pause, addEventListener}` adapter shape
  (`createNativeAdapter` / `createYouTubeAdapter`) set once as
  `activeVideoAdapter`, so transcript click-to-seek, "Copy link to
  current time", "Go to time", and `applyDeepLink()` all work unchanged
  against either one — verified all of the above live against the real
  LA meeting, including deep-link seeking on a fresh page load (the
  trickier async case, gated on the player's `onReady`).

  **YouTube caption download is blocked for plain HTTP requests** —
  real finding, not assumption: every caption URL YouTube hands out
  (via the watch page's embedded `ytInitialPlayerResponse` JSON, itself
  fetched fine with plain HTTP) returned `200 OK` with **0 bytes**
  across 5 different request shapes tried live: aiohttp/curl, with a
  real browser User-Agent, cross-origin `fetch()`, same-origin `fetch()`
  from youtube.com itself, and a freshly-signed same-session URL grabbed
  via JS on the actual watch page. **yt-dlp works reliably** where all of
  those failed (confirmed against the real LA meeting: 570KB, ~2000
  real caption segments) — it evidently has its own way of working
  around whatever's blocking bare HTTP clients, so caption fetching goes
  through yt-dlp's `urlopen()` (called via `asyncio.to_thread` since
  yt-dlp is synchronous), not our own aiohttp session. **Ongoing
  maintenance risk**: yt-dlp is under active, frequent maintenance
  specifically because YouTube keeps changing things to block scraping
  — left unpinned (latest) in `requirements.txt` on purpose; pinning an
  old version would risk this breaking sooner. If YouTube/PrimeGov
  resolves start failing, check for a yt-dlp update first.

  **YouTube's caption VTT uses a "roll-up" cue style**, not one cue per
  line (confirmed on both an auto-generated and, per a different real
  track on the same video, a manual/CC-sourced track) — each cue repeats
  the previous settled line and grows the *next* line word-by-word, so
  treating each cue as its own segment produces massive duplicate text.
  New `dedupe_rollup_cues()` in `vtt_parser.py` collapses this into real
  segments — verified against the real 4035-cue/570KB sample: 2004 clean
  segments, no visible duplication, fully coherent reconstructed text.

  **Manual vs. auto-generated caption track selection**: prefers a
  manual (non-ASR) track when available, but only when its coverage is
  comparable to the auto-generated one — real finding on the LA sample:
  the "manual" CC track only starts at 18:49 into the video (likely a
  government CART feed that skips pre-meeting dead air), while the
  auto-generated track covers the full video from :01. A transcript
  with a 19-minute unlinkable gap at the start is worse for a deep-link
  tool than a slightly lower-quality but complete one, so manual is only
  used when it starts within 60s of the auto-generated track's start
  (`YouTubeAssetFinder._pick_caption_track()`). Confirmed live: correctly
  fell back to the (complete, auto-generated) track for this video and
  warned the user it's auto-generated, not human-transcribed.

  Follow-ups not yet investigated (non-English caption handling, and
  whether the manual-track coverage gap is typical or one-off) are
  tracked as live items in [BACKLOG.md](BACKLOG.md).

## Reporting & caching

- **[Done 2026-08-07] Per-adapter reporting log + read-through cache.**
  New `app/db/` layer (SQLAlchemy async, Postgres via `DATABASE_URL` in
  prod — Render Postgres, user's choice over Neon/Supabase — local SQLite
  fallback otherwise). `/api/resolve` now checks for a prior successful
  resolve of the same normalized URL before fetching live, and logs every
  attempt (success or failure) unconditionally to `meeting_resolutions`.
  All DB calls are wrapped so a down/misconfigured database degrades
  silently rather than breaking resolving — verified live by pointing
  `DATABASE_URL` at an unreachable host and confirming `/api/resolve`
  still returned correct results with no 500. Two token-gated endpoints:
  `GET /admin/stats` (aggregates) and `GET /admin/log` (unaggregated
  per-URL list, JSON or CSV). Also added `external_id` to `ResolvedMeeting`
  (populated so far by Granicus and CivicClerk from ids they already
  extract internally) as a foundation for future dedup.
- **[Done 2026-08-07] Outcome classification fixed to reflect content
  quality, not just resolve status.** Real gap found via live testing: a
  resolve that returns a video with zero transcript segments — or with
  only chapter-marker fallback data (Granicus/CivicClerk/Swagit) — was
  counting as `"success"` in the reporting log, since both `status="success"`
  and `segments` being non-empty (chapter markers still populate
  `segments`) looked identical to a real transcript from the logging
  code's point of view. `app/db/outcomes.py`'s `classify_outcome()` now
  buckets every row into `success` / `agenda_fallback` / `blank_transcript`
  / `garbled_transcript` / `non_english_transcript` / `no_video`, on top of
  the existing `resolve_failed` / `calendar_page` / `unsupported_platform`
  cases — verified against live Simi Valley (garbled Spanish captions),
  Paradise Valley AZ (genuinely blank, no fallback available), and a
  synthetic test covering all five content-quality buckets directly.
- **[Done 2026-08-07] Real bug: non-UTF-8 captions.vtt crashed the whole
  transcript fetch.** `_fetch_vtt` in Granicus/eScribe/CA Legislature all
  called aiohttp's `response.text()`, which decodes strictly as UTF-8 and
  raises `UnicodeDecodeError` on anything else — confirmed live on Simi
  Valley clip 2840, whose real Spanish-language `captions.vtt` isn't valid
  UTF-8 (`0xf3` at byte 241), producing zero segments and a transcript
  warning instead of the actual captions. New `decode_vtt_bytes()`
  (`app/utils/vtt_parser.py`) reads the response as raw bytes and tries
  UTF-8, then Windows-1252, then finally UTF-8 with `errors="replace"`,
  shared by all three platforms' `_fetch_vtt`. Verified live: Simi Valley
  clip 2840 now returns 394 real Spanish-language segments instead of the
  decode-error warning.

## Roadmap items completed

- **[Done 2026-08-07, live] Newsletter signup.** A footer signup form
  (sitewide, in `base.html`) POSTs to `/api/newsletter/signup`, which
  adds the email to a Resend audience. Chose Resend over Mailchimp
  specifically because it can also handle the future "email alerts for
  saved searches" item (triggered per-user sends) on the same
  account/API, not just newsletter broadcasts — Mailchimp would need a
  separate paid add-on (Mandrill) for that later. Degrades gracefully
  like the DB layer: with no `RESEND_API_KEY`/`RESEND_AUDIENCE_ID` set,
  signups return a clean "not available right now" message instead of
  erroring. Live on `redtaperecordings.com` (DNS via Namecheap).
  **Real gotcha hit and fixed**: the first `RESEND_API_KEY` created was
  scoped to "Sending access" only, which Resend rejects for the
  audiences/contacts endpoint with `401 restricted_api_key` — Resend API
  keys need **Full access** to manage audience contacts, not just send
  mail, and permission level can't be changed on an existing key
  (create a new one, revoke the old). Confirmed via Render's live logs
  (the `logger.error("Resend signup failed (%s): %s", ...)` line in
  `main.py` was what surfaced the exact cause) and a real end-to-end
  signup afterward.
- **[Done 2026-08-07, live] Basic analytics.** Google Analytics 4, per
  the user's choice. `base.html` conditionally loads `gtag.js` from
  `GA_MEASUREMENT_ID` and always defines a global
  `window.trackEvent(name, params)` — a real call to `gtag('event', ...)`
  when GA is configured, a no-op otherwise — so call sites never need to
  branch on whether GA is set up. Three events wired so far:
  `submit_meeting_url` (homepage form), `copy_link_to_time` (the core
  viral action — someone creating a shareable deep link),
  `newsletter_signup`. Deliberately did **not** send which meeting URLs
  get pasted in as a GA event parameter — that's redundant with the
  per-adapter reporting log above (which already tracks this
  server-side, with outcome detail GA has no equivalent for) and there's
  no reason to also hand government meeting URLs to Google.
- **[Done 2026-08-07] Permanent meeting pages** (the Archive's core
  feature). Built as a genuinely separate app, `archive/` — own FastAPI
  service, own database (same Render Postgres server as the resolver,
  but a separate logical database), own deploy — reachable at
  `redtaperecordings.com/m/{slug}` via a reverse-proxy in the resolver's
  `app/main.py` (`/m/*` and `/archive-static/*`), so the custom domain
  stays consolidated for SEO/sharing even though it's two services.
  Content model: `MeetingPage` (one per real-world meeting, identity via
  `(platform, external_id)` or normalized URL) + `TranscriptVersion`
  (many per page — language/source variants, deduped by a content hash
  of the segment text) + `MeetingPageUrlAlias` (every input URL that's
  ever pushed, so a lookup keyed on a wrapper-platform URL like Legistar
  still short-circuits even though its real identity lives on the
  platform it delegates to). Pages are fully server-rendered (real
  transcript/agenda content on first byte, not client-fetched JSON) for
  actual crawlability. Handoff: the resolver checks the Archive *before*
  resolving (`archive_client.lookup()`) and redirects to the permanent
  page if one exists, preserving `t=`/`line=`; after a live resolve
  with real content (transcript or agenda — never for blank/failed
  resolves), it pushes via `archive_client.push()` on a `BackgroundTasks`
  callback (not a bare `asyncio.create_task`, which risked the task
  being garbage-collected mid-flight). Both directions degrade silently
  through the same `safe()` pattern as the existing DB calls — a down
  Archive never breaks `/api/resolve`, and the resolver's `/m/*` proxy
  returns a clean 503 rather than hanging.

  Verified live end-to-end locally (two uvicorn processes): a real
  content-bearing resolve (Simi Valley Granicus, 394 segments + 17
  agenda items) correctly created a `MeetingPage`; re-pasting the same
  URL returned `{"redirect_url": "/m/{slug}"}` in ~20ms instead of
  re-scraping; the alias table correctly short-circuited a
  wrapper-platform-shaped URL pointed at the same `external_id`; deep
  links (`t=630&line=seg-4`) survived the redirect and correctly seeked
  + highlighted on the permanent page; a second transcript version
  (different language) correctly appeared in the version picker
  (`?version={id}`, full page reload) without disturbing the first; an
  identical re-push correctly did not create a duplicate version
  (content-hash dedup); a blank/no-content resolve (Paradise Valley AZ)
  correctly never reached the Archive at all; and killing the Archive
  process confirmed `/api/resolve` kept resolving live with no 500 while
  `/m/{slug}` degraded to a clean 503.

  Operational notes for when this goes live: Render's free web services
  spin down after 15 min idle (~30-60s cold start) — fine during
  testing, but the Archive service should move to a paid plan before
  `/m/*` links are actually shared or submitted for indexing, since a
  Googlebot fetch regularly eating that latency is a real crawl-health
  risk, not just a stray-visitor annoyance. Free Render web services can
  send private-network requests but not receive them, so the proxy
  targets the Archive's public `.onrender.com` URL for now — switching
  to Render's internal hostname once the Archive is paid is a one-line
  env var change. The second Postgres database
  (`CREATE DATABASE rtr_archive;` on the existing instance) and the
  second Render web service both still need to be provisioned by the
  user themselves before this is live in production.

  Explicitly not built in this pass (still gated on the Archive
  existing): the transcription crawler, search, accounts/billing, email
  alerts, on-demand crawl requests, video highlights — all tracked as
  live roadmap items in [BACKLOG.md](BACKLOG.md). Also not resolved:
  whether a genuine re-scrape of the same `(language, source)` with
  different content should replace that version in place or add a new
  one and flip which is default — flagged for a follow-up decision, not
  blocking.
- **[Done 2026-08-08] Meetings index page, sitemap.xml/robots.txt, and
  keyword search + filters — built together since search/filters narrow
  the same query the index page uses, not a separate feature.**
  `crud.list_pages()` (paginated, 20/page, `LIMIT`/`OFFSET`) backs a new
  `GET /meetings` route + `meeting_list.html`, reachable at
  `redtaperecordings.com/meetings` via a matching proxy route in
  `app/main.py`. Search box + jurisdiction/date-range/language filters
  are plain GET params on the same route (shareable/bookmarkable URLs,
  no JS required). v1 keyword search covers title + jurisdiction only,
  via a portable `.ilike()` (works on Postgres and the local SQLite
  fallback) — deliberately not full transcript-body search, since
  `segments` are JSON per `TranscriptVersion`, not a plain searchable
  column; that's flagged as a real follow-up in `BACKLOG.md`, not
  silently half-built. `GET /sitemap.xml` (`crud.list_all_page_slugs()`,
  unpaginated — fine at the current hundreds/thousands scale) plus a new
  `GET /robots.txt` on the resolver (`Disallow: /meeting` — the
  ephemeral resolver page — plus a `Sitemap:` line) give the Archive an
  actual crawl path for the first time; previously a `/m/{slug}` page
  was only reachable if you already had its exact URL. Verified live
  end-to-end (both locally and against `redtaperecordings.com`):
  pagination math, keyword search, jurisdiction/language filters
  (including a genuinely-correct edge case — `language=en` correctly
  excludes an agenda-only page with zero transcript versions, not a
  bug), combined filters, the empty-results state, and a real
  `sitemap.xml`/`robots.txt` render with absolute URLs in production.
- **[Done 2026-08-08] Bug: permanent Archive pages hardcoded `<html
  lang="en">` regardless of the actual transcript's language.**
  Confirmed live on the Simi Valley page, whose default transcript
  version is Spanish — the page declared `lang="en"` anyway. Fixed:
  `archive/main.py`'s `meeting_page()` route now passes the active
  `TranscriptVersion.language` into the template as `page_lang`
  (falling back to `"en"` for agenda-only pages with no transcript at
  all); `archive/templates/base.html` reads it via
  `{{ page_lang|default('en') }}`. Verified locally: the same Simi
  Valley page now renders `<html lang="es">`, and an agenda-only page
  (Yountville) correctly falls back to `<html lang="en">`. **Could not
  fully re-verify the non-English branch in production** against this
  specific URL — a real, separate gap surfaced while trying: Simi
  Valley had already been served 3 times from the resolver's own local
  `meeting_resolutions` cache (`hit_count: 3`, cached well before the
  Archive integration's env vars were fixed), so `/api/resolve` keeps
  short-circuiting on that local cache hit and never reaches the live
  resolve → Archive push path for this URL — confirmed directly via
  `psql` against `rtr_deeplink_db`. Production is running the identical
  code as the locally-verified build, so the fix itself isn't in doubt,
  but this exposed a real backfill gap — see the new "Bugs" entry in
  [BACKLOG.md](BACKLOG.md).
- **[Done 2026-08-08] Opportunistic re-check on a permanent-page hit.**
  Cadence decision made and built: a hit on an existing Archive page
  triggers a background re-resolve + re-push only if the page hasn't been
  touched in `ARCHIVE_RECHECK_AFTER` (30 days, `app/main.py` — not derived
  from measured data, a reasonable middle ground between "government
  caption pipelines can take weeks to catch up" and "don't hammer the
  source site on every visit to a popular meeting"). `GET /internal/lookup`
  (`archive/main.py`) now returns the page's `updated_at`; the resolver's
  `archived`-hit branch in `resolve()` parses it (`_parse_updated_at()`,
  treating a naive timestamp as UTC — SQLite doesn't enforce tz-awareness
  the way Postgres does, so which shape comes back depends on which DB the
  Archive happens to be running against) and fires
  `_recheck_archived_page()` via `BackgroundTasks` when stale, never
  blocking the redirect response. Reuses the same finder + `archive_client.
  push()` path as a fresh resolve.

  **Real bug found and fixed while verifying this**: `MeetingPage.
  updated_at`'s `onupdate=func.now()` (`archive/db/models.py`) only fires
  when SQLAlchemy actually detects a changed attribute — but
  `ingest_resolution`'s existing-page branch (`archive/db/crud.py`)
  reassigns `page.title`/`.date`/etc. to values that are usually identical
  to what's already stored, which doesn't dirty the row. Confirmed live
  with an isolated script: backdating `updated_at` and re-ingesting the
  exact same payload left it unchanged, meaning a re-check that found no
  new content would never stop being "stale" and would re-fire on *every*
  subsequent hit — precisely the hammering problem this feature exists to
  prevent. Fixed by having `ingest_resolution` explicitly set
  `page.updated_at = datetime.now(timezone.utc)` on every existing-page
  ingest, regardless of whether any field actually changed, so it reliably
  means "last time this page was checked."

  Verified live end-to-end with two local uvicorn processes (resolver +
  Archive, isolated ports/SQLite files to avoid colliding with other local
  activity against the conventional 8010/8020 dev ports): pushed a real
  Simi Valley meeting, backdated its `updated_at` to simulate a stale page,
  then resolved the same URL twice in a row. First hit: fast redirect
  response plus exactly one background `POST /internal/ingest` (the
  re-check). Second hit, immediately after: redirect only, no re-check —
  confirming the now-fresh `updated_at` correctly suppressed a repeat
  trigger. Ran the project's existing `pytest` suite (`tests/`, added
  concurrently by another session working this same backlog) before and
  after — all passing, no regressions from either change.

- **[Done 2026-08-13] `/coverage` page redesign + sitemap completeness**
  (commits `9e1cef0`, `517011f`), from a live-testing pass that turned up
  several real usability/accuracy issues, not a hypothetical cleanup:
  the Cablecast row still said "(Detroit, MI)" even though Charlotte, NC
  had already become a real, live-transcribed second customer on the same
  adapter; each row linked the *platform name* instead of the example
  meeting, backwards from the sitewide `/meetings` convention; the
  Transcript badge read as attached to the platform label rather than the
  specific example; and only one example city was ever shown per
  platform, even Granicus, underselling its real breadth.

  **`archive/db/crud.py`**: `DIRECT_PLATFORMS["cablecast"]` label changed
  to plain `"Cablecast"` (city names now come from real per-example
  jurisdiction data instead of a hand-maintained label that will go stale
  again the next time Cablecast gains a city). Added
  `_PLATFORM_EXAMPLE_COUNTS` (default 3, Granicus 5) and
  `_select_examples()`, which prefers a distinct jurisdiction per pick
  (real multi-city breadth) then `has_transcript=True` within that, and
  never fabricates rows. `_coverage_row()` now returns a plural
  `examples` list while keeping the old singular `example` (=
  `examples[0]`) and `page_count` fields for back-compat.

  **`archive/templates/coverage.html`**: replaced the duplicated
  `coverage.direct`/`coverage.custom` loops with one shared
  `{% macro platform_group(row) %}` (same in-file-macro pattern as
  `meeting_page.html`'s `version_picker()`), rendering each example's
  title as the link with its own Transcript badge — platform name became
  a plain `<h3>` group heading. Rewrote the "By platform" intro sentence
  with SEO/LLM-discoverability intent (real search phrasing like "link to
  city meetings on Granicus", plus framing useful to an LLM agent
  recommending the tool) and rewrote "What about Platform XYZ?" to name
  all four confirmed real delegation pairings (Legistar→Granicus,
  CivicPlus→Granicus, PrimeGov→YouTube, CivicWeb→YouTube).

  **Decision (left to Claude's judgment by the user): kept prose, did not
  merge into a "Granicus/Legistar" row label.** A `MeetingPage` ingested
  via a Legistar/CivicPlus URL is stored with `platform="granicus"` and a
  real `granicus.com` `source_url_normalized` — no Legistar-specific data
  exists on it at all (see `crud.py`'s existing comment on why these are
  excluded from `DIRECT_PLATFORMS`). A merged label would visually claim
  the shown example demonstrates Legistar support, which it doesn't —
  the same "don't claim a data path works without a positive example"
  principle this repo already applies elsewhere.

  **Sitemap**: `archive/templates/sitemap.xml.jinja` and
  `archive/main.py`'s `/sitemap.xml` route previously only emitted
  `/m/{slug}` entries via `crud.list_all_page_slugs()`. Added a static
  `_SITEMAP_STATIC_PATHS` list (`/`, `/about`, `/coverage`, `/meetings`)
  rendered with no `<lastmod>` (no real timestamp exists for them —
  didn't fabricate one). Deliberately excluded `/account/saved`,
  `/alerts/unsubscribe`, `/meeting` (ephemeral, already
  `robots.txt`-disallowed), and any `/admin/*` route.

  **SEO/LLM-discoverability audit**: a broader sitewide audit was run in
  parallel (structured data, meta tags, canonical URLs, `llms.txt`,
  AI-crawler access) but, per user decision, only the two items above
  shipped this pass — the full tiered audit was logged to
  `CLAUDE_BACKLOG.md`'s "SEO / LLM-discoverability" section for later
  triage rather than built blind.

  **Follow-up fix same day**: auditing README/backlog accuracy afterward
  surfaced a stale, self-contradicting comment in
  `app/platforms/cablecast.py` (left over from before Charlotte was
  confirmed working) claiming Charlotte used "a visibly different
  template this adapter doesn't handle" — directly contradicted by the
  adapter's own docstring three lines below. Fixed the comment and the
  matching stale README table row (commit `517011f`); comment/doc-only,
  verified via `pytest tests/ -k cablecast` (21 passed).

  Verified via `pytest tests/test_footer_and_coverage.py`, a local
  Archive run (`DATABASE_URL=` empty-prefix trick to force SQLite) with
  `/coverage` checked in-browser (page text dump + `read_page` + a direct
  `curl` of rendered HTML, since the browser pane's screenshot tool was
  flaky that session) confirming the Cablecast row no longer says
  "(Detroit, MI)", each example title links with its own badge, and
  Granicus shows 5 distinct-jurisdiction examples; and `curl
  localhost:<port>/sitemap.xml` confirming `/`, `/about`, `/coverage`,
  `/meetings` all appear and `/account/saved`, `/meeting`, `/admin/*` do
  not.

  **What's still open**: the larger "sortable/filterable table, one row
  per jurisdiction with agenda-embedded/instant-transcript/provider-split/
  outcome-bucket/last-verified-date columns" spec from the original
  Coverage page roadmap ask is still unbuilt — today's work is a UX/
  accuracy pass on the existing grouped-by-platform page, not that table.
  Tracked as the still-open part of the "Coverage page" entry in
  `BACKLOG.md`'s Archive roadmap section.

## Testing infrastructure

- **[Done 2026-08-07] Fixture-based pytest suite, from Claude's own
  suggested backlog (`CLAUDE_BACKLOG.md`).** 47 tests across
  `tests/test_vtt_parser.py`, `test_media_scan.py`, `test_base.py`, and
  end-to-end adapter tests for Granicus/Legistar/CivicPlus/CivicClerk.
  Built on branch `claude-backlog/round-1`.

  Real fixtures, not synthetic, wherever a live fetch was possible during
  this session (2026-08-07): Granicus — Napa City clip 3450 (genuinely
  blank captions.vtt, the real 8-byte placeholder) and Simi Valley clip
  2840 (the exact real Spanish-caption meeting `BACKLOG_DONE.md` already
  documents above); Legistar — a real `maricopa.legistar.com/Calendar.aspx`
  page (confirms the calendar pick-list against real markup); CivicClerk —
  real `clovisca.api.civicclerk.com` API responses for two real events (20:
  direct mp4 + 31 real agenda bookmarks; 17: `externalVideoUrl`/YouTube
  fallback, zero bookmarks). CivicPlus is the one exception: the real site
  this adapter was originally verified against
  (`ca-westlakevillage.civicplus.com`) has since been restructured (302s to
  a JS-redirect stub, no `AgendaCenter` markup) and the plain
  `civicplus.com` subdomain no longer resolves at all — that fixture is
  hand-built to match the exact real markup shape `civicplus.py`'s own
  docstring documents as confirmed live on 2026-08-06, not a guess (see
  `tests/fixtures/civicplus/README.md`).

  **Real tooling finding**: `aioresponses` (latest release, 0.7.9) doesn't
  support the aiohttp version this project's unpinned `aiohttp>=3.9`
  requirement resolves to today (3.14.3) — its `_build_response` omits the
  now-required `stream_writer` kwarg to `ClientResponse.__init__`, a hard
  `TypeError` on every mocked request. Rather than pin the app's real
  dependency down just to satisfy a test-only library, wrote a small
  self-contained `tests/aiohttp_mock.py` that monkeypatches
  `aiohttp.ClientSession.get` directly — a `FakeResponse`
  (status/text/read/json/raise_for_status) plus a `mock_session({url:
  FakeResponse})` context manager, exact-URL-keyed. Same "actively
  maintained dependency chasing a moving target" risk category as yt-dlp
  (see the working-conventions note in `CLAUDE.md`) — worth rechecking
  whether `aioresponses` has caught up next time this suite needs
  extending.

  **Two real bugs found while building this, unrelated to the feature
  being tested**:
  1. `media_scan.scan_media_urls`'s `"sources"` JSON-blob regex branch was
     dead code — confirmed via a unit test that its `[^}]*\]` could never
     span the closing `}` of an object inside the array, so no input shape
     that would produce a `source["src"]`-consumable dict could ever
     match. Not a live bug (both callers, Granicus and Swagit, already get
     real URLs from the plain regex patterns tried first) — flagged as a
     live `BACKLOG.md` item first, then removed outright (rather than
     fixed) the same day, since a "working" JSON-aware replacement would
     still be unverified against any real page. The regression test was
     renamed to `test_scan_media_urls_sources_json_branch_was_removed_as_
     dead_code` and still asserts the same input yields no URLs, now
     because the branch is gone rather than because it never matched.
  2. A test-writing mistake that would have hidden a **real fixture bug**
     if not caught: an early draft of the CivicClerk "externalVideoUrl
     fallback" test reused event 20's real `Events/20` JSON with only the
     `id` field patched to 17 — but event 20's `mediaStreamPath`/
     `mediaSourcePathMp4` fields are themselves populated with event 20's
     real direct mp4 URL, so the test would have silently asserted against
     the wrong video source (the shadowing field, not the fallback path it
     claimed to test) had the assertion not been checked against the real
     API response first. Fixed by fetching and saving event 17's own real
     `Events`/`EventsMedia` JSON instead of hand-editing a different
     event's — a reminder that even a "real fixture" test can lie if it's
     assembled from mismatched real pieces.

  Not yet covered: Swagit, eScribe, CA Legislature, PrimeGov/YouTube
  adapters (no test files yet — README's "Running tests" section flags
  this as the natural next extension), and the `app/db/` and `archive/`
  layers (no fixtures or tests for either). `requirements-dev.txt` and
  `pytest.ini` (`asyncio_mode = auto`) added; see README's new "Running
  tests" section for how to run it.

- **[Done 2026-08-08] Six more items from `CLAUDE_BACKLOG.md`, all on
  branch `claude-backlog/round-1`.** Verified live against real running
  instances of both services (not just unit tests) for every item below.

  **PWA manifest.** `app/static/manifest.json` + a new `app/static/icon.svg`
  (a square 192x192 SVG in the site's existing dymo-label red/navy, "RTR"
  monogram — SVG-only, no PNG fallback generated, so pre-maskable-icon
  Android/iOS install flows may not pick it up; a real gap, not silently
  claimed to be complete). Linked from both `app/templates/base.html` and
  `archive/templates/base.html` (`/static/manifest.json` is reachable from
  Archive-served pages too since `/static/` is mounted on the resolver,
  same-origin regardless of which service rendered the HTML).

  **schema.org `VideoObject` JSON-LD** on `archive/templates/meeting_page.html`,
  gated on `page.video_url` existing. `contentUrl` for a direct file
  (mp4/m3u8), `embedUrl` for YouTube (schema.org distinguishes the two).
  `duration` computed for real from the active transcript's last segment
  end time when one exists. No `thumbnailUrl` (this app doesn't generate
  one — same underlying gap as the missing `og:image`), so this likely
  isn't rich-result-eligible yet, just valid structured data. Verified via
  a standalone Jinja render (both a real-data case and a no-video case
  that correctly emits no `<script>` block at all).

  **Rate limiting on `/api/resolve`** via `slowapi`, keyed by client IP
  (`get_remote_address`), 20/minute. Verified live: 21 rapid requests
  against a real local server returned `200` x20 then `429` with
  `{"error":"Rate limit exceeded: 20 per 1 minute"}`. Real production
  correctness issue caught and fixed in the same pass: Render's edge
  proxy means `request.client.host` would otherwise show Render's own
  proxy IP for every request (making the limiter either a no-op shared
  across all real users, or a way one heavy caller starves everyone else)
  — `render.yaml`'s `startCommand` for the resolver now passes uvicorn
  `--proxy-headers --forwarded-allow-ips='*'` so `X-Forwarded-For` is
  trusted from Render's proxy specifically, a standard pattern for
  PaaS-hosted uvicorn. In-memory limiter storage (slowapi's default) is
  fine for the current single-instance free-tier deploy; would need a
  shared backend (Redis) to stay correct across multiple instances.

  **Transcript export (TXT/SRT).** Two different implementations for two
  different architectures, deliberately not shared code: the Archive's
  permanent pages get real server-side download endpoints
  (`GET /m/{slug}/transcript.{txt,srt}` in `archive/main.py`, formatting
  via new `archive/utils/transcript_export.py`, covered by
  `tests/test_transcript_export.py`) since the data is actually persisted
  there; the ephemeral resolver page (`app/templates/meeting.html`) has no
  server-side persistence at all (that's the whole point of this app per
  README), so its "Text"/"SRT" buttons build the file **client-side** in
  `app/static/player.js` from the `segments` array already in memory, via
  a `Blob` + synthetic download link. Verified live end-to-end: real HTTP
  downloads from the Archive endpoint (content-disposition header and
  body both correct, against a real 394-segment Simi Valley transcript),
  and the resolver's client-side path exercised directly in-browser
  (`downloadTranscript('txt')` triggered with no errors, output format
  confirmed to match the server-side formatter byte-for-byte in
  structure).

  **RSS feed of newly-archived meetings**, `GET /feed.xml` on the Archive
  (optionally `?jurisdiction=`), proxied through the resolver the same
  way `/sitemap.xml` already is. New `crud.list_recent_pages_for_feed()`
  (deliberately separate from the `/meetings` index's `list_pages()` —
  a feed just wants "last N, optionally scoped to one jurisdiction," no
  pagination). Autodiscovery `<link rel="alternate">` plus a visible "RSS
  feed" link added to `/meetings`. **Real bug found and fixed before
  shipping**: `feed.xml.jinja`'s name ends in `.jinja`, not `.xml` —
  `jinja2.select_autoescape()` keys off the literal extension, so
  autoescape was silently OFF for this template (same latent gap already
  present in `sitemap.xml.jinja`, harmless there only because it
  interpolates slug/date, not free-text titles). A real meeting title
  containing a bare `&` or `<` produced invalid, unparseable XML —
  confirmed via `xml.etree.ElementTree.fromstring()` failing on the
  unescaped output. Fixed by explicitly `|e`-escaping every interpolated
  value rather than relying on filename-based autoescape detection;
  `tests/test_feed.py` pins this down as a regression test. Also fixed:
  the feed's own `atom:link[rel=self]` initially built itself from
  `str(request.url)`, which — since this service is only ever reached
  through the resolver's proxy — reflected the Archive's own internal
  host:port, not the public one; switched to the same `PUBLIC_BASE_URL`-based
  `base_url` already used for canonical/OpenGraph URLs elsewhere in this
  app. Verified live through the real proxy chain (resolver → Archive →
  real SQLite-backed `MeetingPage` row), both unfiltered and with a real
  `?jurisdiction=` filter.

  **"Report a problem" feedback control**, on both the resolver's
  ephemeral page and the Archive's permanent pages. New `ProblemReport`
  table (`app/db/models.py`) + `POST /api/report-problem` (rate-limited,
  10/minute) + a token-gated `GET /admin/problem-reports`, mirroring the
  existing `/admin/log` pattern. Deliberately lives only on the resolver's
  DB (not a second table on the Archive) — reports from an Archive page
  reach it via a same-origin `fetch()`, since `/api/*` isn't part of the
  Archive proxy and Archive pages are served from the same public domain
  either way. **Real bug caught before shipping, not just after**: the
  first version wrapped `crud.log_problem_report()` in the existing
  `safe()` helper and checked `if result is None` to detect a storage
  failure — but `log_problem_report` itself returned `None` on *success*
  too (a bare `-> None` function), making success and failure
  indistinguishable and the error path effectively unreachable. Fixed by
  having it return `True` on success before ever running it live. Also
  corrected mid-build: an initial draft only treated `result is None` as
  a failure when `DATABASE_URL` was set, based on a false assumption that
  no-`DATABASE_URL` meant "no database" — this app always has *some*
  database (local SQLite fallback, per `engine.py`), so that condition
  would have silently swallowed real write failures in local/no-Postgres
  setups. Verified live end-to-end in-browser on both surfaces: a real
  submission from the resolver's `/meeting` page (filled form, submitted,
  "Thanks — we'll take a look." shown) confirmed to actually land in the
  DB via `GET /admin/problem-reports`; the Archive page's toggle/form
  confirmed to reveal correctly too. `.cassette-btn` reused for the
  submit button — technically outside the "just two buttons" scope
  `app/static/style.css`'s own comment claims, but consistent with
  `archive/templates/meeting_list.html`'s pre-existing "Search"/"Apply
  filters" buttons already extending past that scope; not re-litigated
  here, just noted.

- **[Done 2026-08-08] CivicClerk closed captions, previously unverified,
  now implemented from a real user-supplied example.** The user found a
  real CivicClerk event with populated captions —
  `emporiaks.portal.civicclerk.com/event/585/media` (Emporia, KS) —
  after 8 sampled cities across two sessions had all come back with null
  caption fields (`BACKLOG.md` had accumulated a theory that captioning
  is an opt-in add-on most customers don't turn on; this doesn't disprove
  that, just confirms it's real and working when a city does).

  **Real format finding, not assumed**: the caption file is **SRT, not
  VTT** — `closedCaptionTracks[].file` is a `.srt` URL
  (`cpmedia.azureedge.net/emporiaks/ClosedCaption/....srt`). This
  codebase had no SRT parser at all before this (`app/utils/vtt_parser.py`
  was VTT-only). New `parse_srt()` added there.

  **Real bug caught before shipping**: SRT differs from VTT in that each
  cue is preceded by a standalone sequence-number line ("1", "2", ...).
  Feeding raw SRT text into the existing `parse_vtt()` directly is unsafe
  — once the first cue is open, a later sequence-number line doesn't
  match the timestamp regex, so `parse_vtt`'s loop treats it as more cue
  *text*, silently appending the next cue's index number to the end of
  the current cue. Confirmed on the real 3677-cue Emporia file before the
  fix (every cue but the last corrupted); `parse_srt()` strips
  sequence-number lines first (only when immediately followed by a
  timestamp line, so a caption that's legitimately just a number is never
  touched) before reusing `parse_vtt`'s cue-accumulation logic.
  `tests/test_vtt_parser.py` pins this down with both a minimal synthetic
  case and the real fixture, asserting no cue's text is left over as a
  bare number.

  `app/platforms/civicclerk.py`'s `resolve()` rewritten to actually fetch
  and parse captions instead of showing a "not verified yet" warning:
  tries `closedCaptionTracks` first (richer — supports multiple language
  tracks, mirroring Granicus/eScribe's real-content-language-detection
  pattern rather than trusting any `label` field), falls back to a bare
  `closedCaptionUrl`/`transcriptionUrl` when there's no tracks array
  (matching the fallback order in the reference implementation the user
  supplied). Dispatches VTT vs. SRT parsing by the caption URL's file
  extension, since there's no other signal available. Verified live
  end-to-end against the real Emporia event: 3677 real segments, English
  correctly detected from content (not a label), zero transcript
  warnings, real title/date/jurisdiction/video/26 real agenda items — and
  in-browser, confirming the transcript actually renders on the page with
  no console errors. `tests/test_civicclerk.py` gained a third real-fixture
  test (`Events/585` + `EventsMedia/585` + the real 272KB `.srt` file) for
  this exact case, and `BACKLOG.md`'s "unverified" bug item was removed
  since it's now a positively-confirmed, tested, working path.

- **[Done 2026-08-08] Generalized the CivicClerk SRT lesson across every
  caption-fetching adapter: wider format *detection* everywhere, real
  *parsing* for TTML/DFXP/ITT, best-effort text fallback for the rest.**
  Directly prompted by discussing what the SRT fix implied more broadly —
  the same "assumed VTT because that's what everything else uses" mistake
  was a live risk on Granicus and CA Legislature specifically, which both
  filtered caption candidates to `.endswith(".vtt")` even though the
  shared page scanner already recognized `.srt` as a subtitle URL and
  would have silently skipped one if a customer ever linked to it.

  **New in `app/utils/vtt_parser.py`**: `parse_ttml()` (real structured
  parser for TTML/DFXP/ITT — XML `<p begin= end=>` cues, namespace-agnostic
  tag matching since vendors vary on `tt:p` vs. a default namespace,
  clock-time and offset-time timeExpression support, frame/tick-based
  timing explicitly skipped rather than guessed at since there's no frame
  rate available to convert with); `strip_unknown_caption_markup()` (a
  deliberately generic, format-agnostic best-effort text extractor for
  SBV/SUB/SMI/SAMI/plain-.txt — strips markup tags, MicroDVD-style
  `{123}{456}` frame markers, and SRT/SBV-style timing lines, keeps
  whatever real text remains, no per-line timestamps); and
  `parse_captions_by_extension(url, content)`, a single dispatch point
  every adapter now goes through instead of each reimplementing its own
  extension-sniffing — returns `(cues, fallback_text)`, exactly one
  populated on success, both empty for a genuinely unreadable format
  (`.scc`/`.stl`, real binary/encoded formats with nothing extractable
  without real codec decoding). A bare `.xml` extension is ambiguous
  (some vendors export real TTML with a plain `.xml` extension rather
  than `.ttml`), so that case probes `parse_ttml()` first — a safe probe
  since it returns `[]` cleanly on non-TTML-shaped input, not a guess
  that could corrupt anything — before falling through to the generic
  text fallback.

  **`app/platforms/media_scan.py`** (the shared scanner Granicus/Swagit/CA
  Legislature all use) now recognizes `.ttml`/`.dfxp`/`.itt`/`.scc`/
  `.stl`/`.sbv`/`.sub`/`.smi`/`.sami` unconditionally, plus `.xml`/`.txt`
  only when the URL path also looks caption-related (`caption`,
  `subtitle`, `transcript`, or `/cc[_./-]`) — those two extensions are too
  generic to match unconditionally (would also catch sitemap references,
  analytics config, any random text file on the page); confirmed via a
  real test that a real `sitemap.xml` correctly stays unmatched while a
  `ClosedCaption/....srt`-shaped URL correctly matches. `media_type()`
  applies the same keyword gate independently (not just relying on
  callers to have already gone through the gated scanner), since it's a
  general classifier some caller might run on an un-scanned URL (e.g. a
  caption URL straight from an API field, as CivicClerk does).

  **Adapter changes** (Granicus, CA Legislature, Swagit, CivicClerk — the
  four that ever fetch a caption file): each now tries every detected
  caption URL through `parse_captions_by_extension`. Structured results
  (`cues`) go through the exact same language-detection/best-track/
  garbled-check logic as before (Granicus/CivicClerk's multi-track
  selection was untouched, just fed from a wider candidate pool).
  Unstructured `fallback_text` becomes `segments` with every non-blank
  line as its own pseudo-cue at `start=0.0, end=0.0` (deliberately not a
  new model field — reuses the existing transcript-list rendering path
  for free, and a click still seeks to a valid position, just not a
  precise one), with a warning explaining the format limitation. Neither
  produced anything (binary formats, or a text-based one that came back
  genuinely empty) surfaces a direct "you can view it directly: {url}"
  warning instead of silence, mirroring the existing `AgendaViewer.php`
  fallback-link pattern. Swagit gained an entirely new code path here —
  it previously only ever tried `#transcript-fragments` (a DOM mechanism,
  still unverified per BACKLOG.md) and never looked at `media_urls` for a
  real caption *file* at all.

  **Everything re-verified live against the real meetings already used to
  build these adapters, confirming zero regressions**: Simi Valley
  (Granicus, 394 Spanish segments, same warnings, same language
  detection), Napa City (Granicus, blank-caption case, same "blank"
  message + agenda fallback link), Yountville CA (Swagit, 7 agenda items,
  same video resolution), Emporia KS (CivicClerk, 3677 SRT segments, zero
  warnings) — all byte-for-byte identical output to before this change.
  CA Legislature's real hearing samples from earlier sessions couldn't be
  re-located (no ID was ever recorded, and a live search for a current
  hearing with a populated caption track didn't turn one up in a
  reasonable amount of searching) — covered instead by new synthetic
  tests, including one confirming the real `/thumbnails/` scrubber-sprite
  VTT exclusion still holds under the wider extension list.

  **New test coverage**: 31 tests in `tests/test_vtt_parser.py` (up from
  14) covering `parse_ttml` (clock-time, offset-time, namespace prefixes,
  nested markup, frame-based-time skipping, malformed XML),
  `strip_unknown_caption_markup` (SBV/MicroDVD/SAMI shapes), and
  `parse_captions_by_extension`'s full dispatch tree; `test_media_scan.py`
  gained detection tests for every new extension plus the xml/txt
  keyword-gate (both positive and negative cases); Granicus/CivicClerk
  gained synthetic (not real — no non-VTT/SRT caption file has ever been
  observed on either platform) tests for both the text-fallback and
  link-only paths; and **CA Legislature and Swagit each got their first
  test file ever** (`test_ca_legislature.py`, `test_swagit.py`), scoped
  to the new caption-fallback logic specifically rather than full adapter
  coverage — the broader gap (no coverage of these two adapters' core
  resolve() flow at all) is still open, noted in the "Testing
  infrastructure" entry above.

- **[Done 2026-08-08] Permanent Archive page stuck showing no transcript
  after an adapter fix, with no way to refresh it besides waiting up to
  30 days — fixed with an on-demand admin recheck endpoint.** Found while
  investigating why `redtaperecordings.com/m/emporia-ks-2026-07-22-commission-meeting`
  (CivicClerk event 585) showed no transcript despite the SRT caption fix
  above being able to find one: that page had been pushed to the Archive
  *before* the fix landed, and `/api/resolve` checks the Archive before
  ever calling the adapter again ([app/main.py](app/main.py)) — so once a
  permanent page exists, every repeat visit just redirects to it,
  confirmed live by re-pasting the source URL and watching it bounce
  straight back with no new resolve. The only existing refresh path,
  `ARCHIVE_RECHECK_AFTER` (a 30-day passive background recheck on a stale
  lookup hit), hadn't elapsed for this page.

  **Fix**: `_recheck_archived_page()` (the function the passive recheck
  already used) changed from a fire-and-forget `-> None` to returning a
  summary dict (`pushed`, `platform`, `title`, `segment_count`,
  `agenda_item_count`, `transcript_warnings`, `video_warnings`) — the
  passive `BackgroundTasks` caller still discards it, unaffected. New
  `GET /admin/recheck-archive-page?token=&url=` calls it directly and
  awaits it synchronously (unlike the passive path, the caller here is
  explicitly waiting to see the outcome), gated by the same
  `ADMIN_STATS_TOKEN` pattern as the other `/admin/*` routes (404 on a
  bad/missing token, not 401/403, so it's not distinguishable from a
  typo).

  An earlier version of this fix was a one-off shell script
  (`scripts/refresh_archive_page.py`) meant to be run from a Render
  Shell, written before discovering the production plan doesn't have
  Shell access. Removed once the HTTP endpoint made it unnecessary — no
  reason to maintain two ways to do the same thing, and the endpoint
  works from anywhere (browser, curl, no Render access needed at all)
  rather than only from a shell on that one service.

  **Verified live end-to-end**: 84/84 tests still pass locally after the
  refactor. Once deployed, `curl
  ".../admin/recheck-archive-page?token=$ADMIN_STATS_TOKEN&url=https://emporiaks.portal.civicclerk.com/event/585/media"`
  (run from the user's own Render Shell, token substituted from that
  container's own env — never typed/pasted anywhere) returned
  `{"pushed":true,"platform":"civicclerk","title":"Commission
  Meeting","segment_count":3677,"agenda_item_count":26,
  "transcript_warnings":[],"video_warnings":[]}`. Reloading the permanent
  page immediately after confirmed the Transcript section now renders (a
  `<h2>Transcript</h2>` heading present, 3703 `.transcript-segment`
  elements — 3677 transcript lines + 26 agenda items, both reusing the
  same CSS class per the Agenda section's markup-reuse design — with the
  first three real lines: "CALL MEETING TO ORDER", "MEMBERS PRESENT",
  "PROCLAMATIONS").

  Residual gaps intentionally left open, split back out into
  [BACKLOG.md](BACKLOG.md): the *passive* 30-day recheck cadence still
  doesn't vary by transcript quality (this fix only added the on-demand
  manual path, not a smarter automatic one), and Emporia's own
  `eventBookmarks` all reporting `markerTimeStart: 0` (a separate, real
  source-data quirk noticed during this same investigation, unrelated to
  the missing-transcript bug) is still unaddressed.

- **[Done 2026-08-08] Granicus: video missing on cities whose
  `MediaPlayer.php` only embeds a legacy Flash player, fixed with a
  fallback to Granicus's newer `/videos/{id}/player` page.** Found via a
  user-reported real meeting,
  `redtaperecordings.com/m/city-of-fountain-valley-city-council-meeting-jun-16th-2026`
  (source: `fountainvalley.granicus.com/MediaPlayer.php?clip_id=607`),
  which showed no video at all. Root cause, confirmed directly against
  the live page: `MediaPlayer.php`'s HTML embeds only a `modernplayer.swf`
  Flash object whose `VideoUrl` param points at `ASX.php?...&stream_type=
  rtmp` — RTMP, unplayable in any modern browser, not a bug in our
  scanner correctly ignoring it. `GranicusAssetFinder` only ever fetched
  the originally-submitted page, so for a city on this legacy template
  there was never any `.m3u8`/`.mp4` to find. Separately confirmed
  Granicus does have a real, working HLS stream for the same clip, just
  on a page this adapter never fetched:
  `fountainvalley.granicus.com/videos/607/player`, which loads `hls.js`
  against a genuine `archive-stream.granicus.com/.../playlist.m3u8`.

  **Fix** (`app/platforms/granicus.py`): extracted the existing
  m3u8-preferred/mp4-fallback selection logic into a new
  `_pick_video_url()` staticmethod (previously inlined in `resolve()`),
  and added `_fetch_video_from_player_page()` — only called when the main
  page's candidates yield no video, so cities where it's already found
  there (the common case) pay no extra request. Single-attempt, not
  `_fetch_page`'s retry-with-backoff (matching `_fetch_caption_file`'s
  style) — this is an opportunistic fallback probe, not the one request
  the whole resolve depends on, so a slow/dead player page fails cheap
  rather than costing multiple retries with exponential backoff on every
  affected city.

  **Verified live end-to-end, twice**: first against Granicus's own
  `/videos/607/player` page directly in-browser (`readyState: 4`,
  i.e. fully loaded and playable, confirmed by actually calling
  `.play()` and watching `currentTime` advance) — ruling out that the
  discovered stream URL itself was somehow dead despite existing (a real
  risk: a bare `curl` to the same m3u8 URL got a 403 from Granicus's CDN,
  almost certainly hotlink/bot protection rather than a broken stream,
  since the real browser fetch succeeded fine). Then against this
  resolver's *own* frontend, run locally (`uvicorn app.main:app --port
  8010`) against `/meeting?url=<the real clip 607 URL>` — confirmed the
  video element reaches `readyState: 4` and visibly renders the real
  Fountain Valley council chamber footage (screenshot: title card "City
  Council Study Session Meeting, June 16, 2026", duration 7:31:13
  matching the stream's real `duration: 27073.36`s), ruling out a
  same-origin-only quirk (Granicus's own domain vs. a cross-origin
  `hls.js` fetch from `redtaperecordings.com` could plausibly have hit a
  different CORS/referrer outcome — it didn't).

  Incidentally, this is the same meeting CLAUDE.md already flagged as a
  useful caption-parsing sample ("language misdetected as Portuguese")
  — separately confirmed during this same investigation to be genuinely
  garbled at the source: fetched the real `.vtt` directly from Granicus,
  it's structurally valid WebVTT (correct header/timestamps) but the cue
  *text* is garbage (`###...@@@@@@@kkIkkkkk~kkkkkkkook?Ek?E?E?E`) —
  Granicus's own captioning pipeline failing for this meeting, not a
  decoding bug on our end. `langdetect` calling that noise `'pt'` is
  expected garbage-in/garbage-out behavior; the system already handles
  it correctly (`is_likely_garbled` fires, the "looks garbled at the
  source... treat it as approximate" warning shows). Nothing to fix
  there — CLAUDE.md's sample-list entry updated to describe it
  accurately (garbled-hence-misdetected, not just misdetected) and to
  note the video gap is now fixed.

  **New test coverage**: `tests/test_granicus.py::
  test_resolve_falls_back_to_player_page_for_video_when_mediaplayer_has_none`,
  backed by three new real fixtures (`fountainvalley_clip607_mediaplayer.html`,
  `fountainvalley_clip607_player.html`, `fountainvalley_clip607_captions.vtt`,
  all fetched live 2026-08-08) — pins the exact real m3u8 URL, `m3u8`
  format, zero video warnings, 146 real (garbled) segments, and the
  `'pt'`/garbled transcript warnings together, so this exact case can't
  silently regress. The three existing synthetic caption-fallback tests
  (blank-guessed-captions, unstructured-text-fallback, unreadable-format)
  needed a `/videos/{id}/player` 404 route added to their existing mocks,
  since none of their fixtures have a video either and would otherwise
  now trigger the new fallback request unmocked.

- **[Done 2026-08-08] Swagit and CA Legislature never ran language
  detection, so real English transcripts showed no "en" on the
  `/meetings` listing.** User-reported from the Browse Meetings page:
  "Jan 13, 2026 City Council" (Dublin, CA, Swagit) showed a bare
  jurisdiction/date with no language and no "agenda only" tag despite
  clearly having a real transcript. Root cause, confirmed by reading
  every adapter: Granicus and CivicClerk both call content-based language
  detection (never trusting a source `srclang` label — see the Simi
  Valley Spanish-mislabeled-`en` finding elsewhere in this file) and pass
  `transcript_language` through; `SwagitAssetFinder` and
  `CaliforniaLegislatureAssetFinder` never called it at all, leaving the
  field permanently `None` for every meeting on either platform,
  regardless of transcript quality. Masked on each individual meeting
  page because `archive/main.py`'s `page_lang` defaults to `"en"` when
  the stored value is falsy (`(active_version["language"] if
  active_version else None) or "en"`) — correct for the `<html lang>`
  attribute's own purpose, but it meant the gap was invisible anywhere
  except the `/meetings` list, which shows the raw stored value with no
  such fallback.

  Incidentally confirms a previously-"unverified" path for real: Dublin's
  Jan 13, 2026 meeting (Swagit clip 372020) has a genuine 36,072-cue
  English transcript via `#transcript-fragments a[data-ts]` (one word per
  cue) — `SwagitAssetFinder`'s class docstring and
  [BACKLOG.md](BACKLOG.md) both said this DOM path had "never been
  populated in any sample checked." It's real; that unverified note is
  removed. Separately confirmed a real Senate floor session
  (`senate.ca.gov/media/senate-floor-session-20260806`, 3,084 cues) has
  the same missing-language gap on the CA Legislature side.

  **Fix**: extracted the two byte-identical `_detect_cue_language`
  copies already duplicated across `granicus.py` and `civicclerk.py` into
  one shared `detect_language_from_texts()` in `app/utils/vtt_parser.py`
  (took a plain `Iterable[str]` rather than a cue-dict shape, since
  Swagit/CA Legislature's segments are already `TranscriptSegment`
  objects, not raw dicts, at the point language needs detecting) — three-
  strikes-you-extract, not premature, since this was about to become a
  fourth copy. `swagit.py` now detects language once from whichever real
  segments it found (`#transcript-fragments` or the caption-file
  fallback); `ca_legislature.py` detects it for both its structured-cue
  and unstructured-text-fallback paths.

  **Verified live end-to-end** against both real meetings that surfaced
  the gap: Dublin clip 372020 (`transcript_language: "en"`, 36,072
  segments) and the Senate floor session (`transcript_language: "en"`,
  3,084 segments, real `.m3u8` video URL too). 87/87 tests pass (85
  existing + 2 new: `test_swagit.py::
  test_resolve_detects_language_from_transcript_fragments` and
  `test_ca_legislature.py::test_resolve_detects_language_from_real_captions`,
  both synthetic — coherent English sentences fed through the same
  `#transcript-fragments`/caption-file code paths, pinning that language
  detection actually fires and gets wired through to
  `ResolvedMeeting.transcript_language`). Only fixes future resolves —
  the two real meetings' existing permanent Archive pages still need the
  same `/admin/recheck-archive-page` treatment as Emporia/Fountain Valley
  before this shows up live on `/meetings`.

  While auditing the `/meetings` listing for this, found a third,
  structurally different bug on the same page (a permanent page frozen
  with output from a since-removed code path, not fixable by a recheck at
  all) — kept as its own open item in [BACKLOG.md](BACKLOG.md) rather than
  folded in here, since the fix shape is completely different.

- **[Done 2026-08-08] `/meetings` search now covers transcript/agenda
  text, with an exact/fuzzy toggle, replacing the old title/jurisdiction-
  only keyword box.** User-requested: transcription errors mean a
  literal word like "traffic" can show up in a real transcript as
  "trafic" or "traffiq", so a plain substring search would silently miss
  real matches. Also dropped the `language` text-filter field per the
  request and added `has_transcript`/`has_agenda` checkboxes instead —
  more directly useful than a free-text language guess, and fixes real
  cases already found in this session (Yountville's stale/misleading
  transcript-shaped agenda, the Emporia/Fountain Valley pages before
  their admin-recheck refresh) being invisible to filter on before.

  **Design decision, made deliberately, not a placeholder:** no schema
  change, no Postgres-only extension. `archive/utils/search.py` does
  exact (plain substring) and fuzzy (bounded Levenshtein per word,
  threshold scaled by word length: 0 for <=4 chars, 1 for 5-7, 2 for 8+)
  matching in pure Python, over text read from the same JSON columns
  that already exist — no new column, so nothing to migrate. Exact is
  the default (per the user's explicit ask, "that way when searches run,
  they'll default to the faster one") since it skips per-word distance
  computation entirely. This is a real, acknowledged scale limit, not an
  oversight — see the new "Search: move to a materialized/indexed
  column" entry in [BACKLOG.md](BACKLOG.md) for what outgrowing it looks
  like and why it isn't built that way yet.

  **`archive/db/crud.py`'s `list_pages()` rewritten**: `has_transcript`
  still filters in SQL (cheap, no JSON involved — it's just "does a
  default `TranscriptVersion` row exist"). Transcript `segments` are only
  ever pulled from the DB when a keyword search is actually running,
  so a plain filter-only browse of `/meetings` never drags every
  meeting's full transcript JSON over the wire for nothing (Dublin's
  real 36k-segment transcript alone is over a megabyte of JSON — see the
  Swagit language-detection entry above). `has_agenda` and keyword
  matching can only be evaluated once content is in hand, so pagination
  for those runs in Python over the SQL-filtered candidate set instead
  of `LIMIT`/`OFFSET` — a real behavior change from before, fine at
  today's scale, called out explicitly in the function's own docstring
  for whoever touches this next.

  **Verified**: `tests/test_archive_search.py` (5 new tests, pure
  functions, no DB/mocking needed) pins the exact-vs-fuzzy behavior
  directly, including the motivating "traffic"/"trafic"/"traffiq"
  example and that short words (<=4 chars) require an exact token match
  rather than fuzzing into unrelated words ("cat" must not match "car").
  End-to-end verified live against a local archive service + seeded
  SQLite data (not synthetic-only): exact search for "traffic" found a
  real transcript containing it, the same search for the typo "trafic"
  correctly found nothing in exact mode and correctly found it in fuzzy
  mode, `has_agenda`/`has_transcript` checkboxes correctly filtered a
  two-meeting seed set, and the rendered `/meetings` page (screenshotted)
  showed both checkboxes, the language/​"agenda only" badges, and
  filter-state persistence through a real "Apply filters" submit — not
  just checked via the Python API. 92/92 tests pass.

- **[Done 2026-08-08] On-demand transcription from audio — a viewer can
  request our own transcript when the source's own captions are missing,
  garbled, or wrong-language.** User-designed feature, planned in detail
  before building (job execution infra, transcription engine, and
  email-verification strictness were all explicit decisions the user made
  rather than defaults picked silently). Real product goals stated
  alongside the request, intentionally not built now but designed around:
  speaker diarization + a name-mapping UI, and comparing the finished
  transcript against the agenda for topic coverage — both moved to
  `CLAUDE_BACKLOG.md`.

  **Architecture: a third service.** Neither the resolver nor the Archive
  web service can run something that might take hours, so a new
  `worker/` — a persistent, paid Render Background Worker (the first
  paid, always-on infrastructure this project has needed; no free tier
  exists for this) — processes jobs in the background. Deliberately
  breaks the resolver/Archive HTTP-only separation in one direction only:
  the worker imports `archive.db`/`archive.utils.email` directly (it *is*
  Archive backend logic, just in a process shape the Archive's own web
  dyno can't offer) and `app.platforms` directly (read-only, to re-resolve
  a fresh media URL before each chunk — HLS/signed URLs can go stale over
  a long job). `app/platforms/media_probe.py`'s ffmpeg/ffprobe wrapper and
  the adapter-registration helper (`app/platforms/__init__.py`'s new
  `register_all_finders()`, extracted from what used to be nine inline
  `register()` calls in `app/main.py`) both live under `app/platforms/`
  specifically so `app/main.py`'s synchronous feasibility-check endpoint
  and `worker/main.py`'s chunk processing can share them without `app/`
  ever depending on `worker/`.

  **The flow**: feasibility check (`POST /api/transcription/check-
  feasibility` — live-resolves, then `ffprobe`s the real duration, reject
  under 5min/over 14h) → submit (`POST /api/transcription/submit`,
  re-checks feasibility server-side, never trusts a client flag) → the
  Archive creates a `TranscriptionJob`
  (`POST /internal/transcription/create-job`) → **email-verification
  rule, exactly as specified**: if the address is already in the Resend
  newsletter audience, the job queues immediately; a first-time address
  requires one confirmation-email click
  (`GET /confirm-transcription` on the resolver →
  `POST /internal/transcription/confirm`), which also opts them into the
  audience so every request after their first is frictionless → the
  worker loops claiming one chunk at a time
  (`archive/db/crud.py`'s `claim_next_chunk()`), extracting that chunk's
  audio with `ffmpeg` (re-resolved media URL, realistic User-Agent/
  Referer headers — see the Fountain Valley 403 workaround below),
  transcribing it with self-hosted `faster-whisper` (model loaded once at
  worker startup, reused for every job/chunk after that — **exactly the
  "free service that won't suck" the user asked for**, since the worker's
  cost is already fixed regardless of how much gets transcribed, no
  per-minute API meter on top), shifting timestamps from chunk-relative to
  full-meeting-relative seconds (`worker/segment_utils.py`'s
  `shift_segments()`), and persisting the result
  (`report_chunk_result()`) before moving on — checkpointed after every
  chunk specifically so a worker restart/redeploy loses at most one
  in-flight chunk, never the whole job. On the last chunk: a new
  `TranscriptVersion(source="transcribed")` is created, its language
  detected from its own real text
  (`archive/utils/language.py`, a deliberate duplicate of `app/utils/
  vtt_parser.py`'s `detect_language_from_texts()` — same reasoning as the
  existing `url_normalize.py` duplicate, keeps the Archive's web service
  from gaining a dependency on `app/`), and — closing a real,
  independently-confirmed gap — promoted to the page's default via new
  `promote_transcript_version()`.

  **Real, previously-existing bug fixed as part of this**: before this
  build, only the very first `TranscriptVersion` a `MeetingPage` ever got
  was set `is_default=True` — nothing later ever promoted a subsequent
  one, an unresolved question already flagged in this file's own Archive-
  build entry above. `promote_transcript_version()` closes it: demotes
  the previous default, promotes the new one, never deletes anything (the
  demoted version stays reachable through the existing `?version=`
  picker).

  **Schema, deliberately minimal**: new `TranscriptionJob` table
  (`archive/db/models.py`) — status machine `pending_confirmation` →
  `queued` → `in_progress` → `completed`/`failed`, `partial_segments`
  accumulated as the durable per-chunk checkpoint, `confirmation_token`.
  No migration needed (`create_all()` handles a new table, per this
  repo's existing convention). One shared-code addition to a model that's
  used everywhere: `TranscriptSegment` (`app/platforms/models.py`) gained
  an optional `speaker` field, unused by every path today including this
  one — added now, cheaply, since it's free and saves a schema touch when
  diarization is actually built (the same base `faster-whisper` model
  WhisperX already builds real diarization on top of via
  `pyannote.audio`, so this wasn't a speculative guess at the eventual
  design).

  **`ingest_resolution()` refactored**: its inline find-or-create-
  `MeetingPage` logic was extracted into `_find_or_create_page()`, since
  `create_transcription_job()` needed the exact same "find this meeting's
  permanent page, or create one" behavior (a transcription request can be
  the very first thing that ever creates a page for a meeting, same as a
  normal resolve).

  **Verified live, not just unit-tested, at every layer**:
  - `app/platforms/media_probe.py`'s `ffprobe`/`ffmpeg` wrappers against a
    real public HLS stream (Apple's bipbop test stream, 1800.00059s probed
    duration matching the stream's actual real length) — and, the
    motivating case — the **exact** Granicus CDN URL that returned a bare
    403 earlier this session (Fountain Valley clip 607, `BACKLOG_DONE.md`
    entry above): with the realistic-headers workaround, `ffprobe`
    correctly returned `27073.362074`s, matching the `7:31:13` observed
    in-browser in that earlier entry exactly.
  - `worker/transcription_engine.py`'s `FasterWhisperEngine` against real
    speech (macOS `say` → `ffmpeg`-converted audio): produced an accurate
    transcript with correct per-segment timestamps; chained with
    `shift_segments()` at a simulated chunk-3 offset (2700s) and confirmed
    the shifted timestamps were exactly right.
  - The full `TranscriptionJob` lifecycle against a real (file-based,
    isolated) SQLite session — creation, the per-page duplicate-job lock,
    the global concurrent-job cap, chunk-by-chunk claim/report,
    finalization, promotion, and the confirm-token flow (including that a
    used/wrong token correctly fails) — both by hand and as 8 real pytest
    integration tests (`tests/test_transcription_jobs.py`, using a new
    session-scoped isolated-SQLite-file fixture in `tests/conftest.py`
    added specifically for this, since no archive/db test infra existed
    before this feature).
  - Every new HTTP endpoint over real HTTP (not just direct Python calls):
    `archive/main.py`'s new `/internal/transcription/*` routes (including
    confirming the 404-not-401 auth pattern holds, and that a
    validly-shaped-but-unauthenticated request is correctly rejected) and
    `app/main.py`'s new `/api/transcription/*` routes, run together as two
    live local services — feasibility check and submit both verified
    against the real Fountain Valley meeting, including the real
    `pending_confirmation` → confirm-link → `queued` transition and the
    correctly-stripped `requester_email` in every public-facing response.
  - `worker/main.py`'s actual `process_next_chunk()` end-to-end against a
    real seeded job (real bipbop audio, real `faster-whisper` "tiny"
    model, graceful fallback when the platform re-resolve legitimately
    fails, graceful degradation when Resend isn't configured for the
    completion email) — and separately, the real `run_forever()` polling
    loop (not just the underlying function) driven end-to-end with the
    actual default `"small"` model, confirming the full production
    startup → model-load → poll → claim → process → complete path works,
    not just its pieces in isolation.
  - The full frontend flow (toggle → feasibility check → email step →
    submit → correct success/error messaging) on **both** the resolver's
    ephemeral `/meeting` page and the Archive's permanent `/m/{slug}`
    page, screenshotted, against the real Fountain Valley meeting on both.
  - `render.yaml` validated as parseable YAML with the expected structure;
    `worker/Dockerfile` reviewed by hand but **not** build-tested (no
    Docker daemon available in the build environment) — flagged as a real
    gap in `BACKLOG.md`, not silently assumed to work.
  - 111/111 tests pass (was 92 before this feature; +19 new: 5
    `test_worker_segment_utils.py`, 1 `test_media_probe.py`, 8
    `test_transcription_jobs.py` covering the DB lifecycle including the
    new language-detection-on-completion behavior, plus the
    `TranscriptSegment.speaker` field addition needed no new test since
    it's a passive schema addition with no behavior to verify yet).

  Real gaps intentionally left open (see `BACKLOG.md`'s "On-demand
  transcription" section for the full list): ffmpeg availability on the
  resolver service is unverified (may need a Docker runtime switch, same
  as the worker), the worker's Render plan sizing for `faster-whisper` is
  a guess pending real memory profiling, Resend's contact-lookup-by-email
  endpoint shape is unverified against a real account, an unconfirmed
  `pending_confirmation` job blocks new requests for that meeting with no
  expiry, and — most importantly — **nothing here has been exercised
  against actual deployed Render infrastructure yet**, only locally and
  against real external services (Granicus's CDN, Apple's test stream,
  Hugging Face's model hub) from a local/sandboxed environment.

- **[Done 2026-08-08] First real deploy of the transcription worker
  crash-looped: `worker/requirements.txt` was missing `pydantic`.** Real
  production failure, confirmed from Render's own logs immediately after
  the entry above shipped:
  `ModuleNotFoundError: No module named 'pydantic'` at `worker/main.py`'s
  very first import (`app.platforms.base` → `app.platforms.models`,
  which imports `pydantic` directly) — `worker/Dockerfile`'s image built
  fine (a real, useful data point: the un-build-tested-locally risk
  flagged above turned out fine), but the container crashed on every
  start, Render restarting it in a loop.

  **Root cause of why local testing missed this**: every local
  verification of `worker/main.py` (BACKLOG_DONE.md's entry above lists
  several) ran inside this repo's one shared dev `.venv`, which already
  had `app/`'s full `requirements.txt` (including `pydantic`, via
  `fastapi`) installed alongside `worker/requirements.txt`'s packages —
  so a genuinely missing entry in `worker/requirements.txt` specifically
  was invisible no matter how thoroughly the *code* was exercised.
  **Fix, and the methodology lesson that matters more than the one-line
  diff**: added `pydantic>=2.0` to `worker/requirements.txt`, then
  re-verified all three services — not just the worker — each in a
  freshly created, genuinely isolated venv containing *only* that
  service's own `requirements.txt` (`python3 -m venv ...` +
  `pip install -r .../requirements.txt` + a plain import, nothing
  borrowed from the shared dev environment). `app/`, `archive/`, and
  `worker/` all now confirmed to import cleanly on their own declared
  dependencies alone. Worth remembering for any future change that
  touches more than one of these three services: a shared local dev venv
  is fine for iterating quickly, but the *last* check before pushing
  anything that adds a new cross-file import needs to happen against
  each service's real, isolated dependency set, or a missing-package bug
  like this one won't surface until it's already live and crash-looping.

- **[Done 2026-08-08] Set up `HF_TOKEN` for the worker.** No code change
  needed — `huggingface_hub` (a `faster-whisper` dependency) already
  reads `HF_TOKEN` from the environment on its own; this was purely an
  infra step. `render.yaml` updated to document the (optional) env var
  slot on `rtr-transcription-worker`. User created a free Hugging Face
  account, generated a read-only access token, and added it to the
  worker's environment in Render — future model-load logs should stop
  showing the "sending unauthenticated requests" warning.

- **[Done 2026-08-08] Unconfirmed `pending_confirmation` transcription
  jobs now expire instead of blocking a page forever.** Was: an
  unconfirmed first-time request had no expiry, so it would block any
  new request for that meeting indefinitely. Fixed exactly as previously
  scoped: `archive/db/crud.py` gained `PENDING_CONFIRMATION_EXPIRY =
  timedelta(hours=48)`; `create_transcription_job()`'s duplicate-request
  check now treats a `pending_confirmation` job older than that as not
  blocking (a fresh request creates a new job instead of returning the
  stale one); `confirm_transcription_job()` was updated to match — a
  stale confirmation-email link for an expired job now returns `None`
  (same "invalid or already used" response as an unknown token) rather
  than being able to resurrect an abandoned job after a newer one may
  have already superseded it. The now-unused `ACTIVE_JOB_STATUSES`
  constant was removed rather than left dead. Verified with new tests
  (`tests/test_transcription_jobs.py::test_expired_pending_confirmation_
  is_superseded_and_unconfirmable`, backdating a real row's `created_at`
  directly): a fresh request after expiry gets a new job id, and the old
  token no longer confirms. Full suite green (115 tests) after the
  change.

- **[Done 2026-08-08] All-zero agenda timestamps (Emporia, KS's CivicClerk
  `eventBookmarks`) no longer render as false clickable `[0:00]` links.**
  User picked the "suppress + plain outline" option over "keep the links
  with a warning" — a link that looks actionable but silently does
  nothing is worse than no link at all. Implemented generically (not
  CivicClerk-specific) since the root pattern — "more than one agenda
  item, all sharing the exact same start time" — could show up on any
  platform, not just this one: `app/static/player.js`'s `renderAgenda()`
  and `archive/templates/meeting_page.html`'s agenda block (mirroring
  each other, same pattern as the rest of this codebase's duplicated
  frontend logic) both detect `items.length > 1 and every item.start ===
  items[0].start`, and when true render a plain unlinked outline with a
  one-line note ("This source doesn't provide real per-item timestamps,
  so these agenda items aren't clickable.") instead of the normal
  clickable-timestamp treatment. A single item at `0:00` is deliberately
  *not* suppressed — that's the normal case of the first agenda topic
  starting at the top of the video. Verified: full pytest suite green
  (116 tests) plus a direct Jinja-render check of all three cases
  (all-zero, normal distinct times, single item at 0:00) confirming the
  right branch renders in each.

- **[Done 2026-08-08] Worker's chunk-failure log now uses the same
  1-indexed chunk numbering as the claim-success log.** Found while
  investigating a real production timeout (`worker/main.py`'s ffmpeg
  extraction hit `_SUBPROCESS_TIMEOUT_SECONDS` on one chunk of a real
  job): the claim log used `chunk_index + 1` (1-indexed, e.g. "chunk
  11/12") while the two failure logs used the raw 0-indexed `chunk_index`
  directly, so a failure and its immediate retry looked like two
  *different* chunks in the logs (off by one) even though
  `report_chunk_result()`'s failure path never advances
  `chunks_completed`, meaning the same chunk really was retried
  correctly with no data loss. Confirmed via the actual production log:
  "ffmpeg extraction failed for chunk 11" (0-indexed = the 12th/last
  chunk) immediately followed by "Claimed job 2: chunk 12/12" (1-indexed
  = the same chunk) — genuinely confusing to read together, not a real
  bug in the retry logic itself. Fixed both failure log lines to use
  `chunk_index + 1, total_chunks` and spell out "(will retry on next
  poll)" explicitly, so a future read of these logs doesn't need this
  same investigation to know the outcome.

- **[Done 2026-08-08] Swagit's `#transcript-fragments` word-level
  segments now get grouped into readable multi-word lines.** Was: real
  data confirmed on a Dublin, CA meeting — six separate clickable
  `[0:04]`/`[0:05]` lines for the single six-word phrase "GOOD EVENING
  AND HAPPY NEW YEAR," spoken in under two seconds, since Swagit's
  `#transcript-fragments` DOM emits one `<a data-ts>` per word
  (`start == end`, a true instant) rather than real multi-word VTT/SRT
  cues like every other adapter. Fixed with a new pure function,
  `_group_word_fragments()` (`app/platforms/swagit.py`), applied only to
  the `#transcript-fragments` DOM path (not the real-caption-file path,
  which already has proper cues and shouldn't be re-merged) — a rolling
  4-second time window per line, chosen over a fixed word count or
  sentence-aware grouping (these fragments carry no punctuation at all
  to key off of). Each group's `start` is its first word's real
  timestamp, `end` its last word's. Verified against the exact real
  Dublin timestamps from the bug report
  (`tests/test_swagit.py::test_group_word_fragments_merges_real_dublin_example`)
  plus three more unit tests (empty input, single word, window-boundary
  behavior) and an updated integration test confirming the existing
  language-detection test still passes with grouped (not one-per-word)
  segments. Full suite green (121 tests).

- **[Done 2026-08-08] `ingest_resolution()` now promotes/demotes a
  page's default `TranscriptVersion` when warranted — the general fix
  for both the Yountville stale-transcript bug and the Dublin
  missing-language bug.** Was: a recheck could never improve a page's
  displayed default — `ingest_resolution()` (`archive/db/crud.py`) only
  ever *added* a new version `if segments:`, and only the very first
  version a page ever got was `is_default=True`; nothing later ever
  promoted or demoted anything. Two confirmed real bugs from this: a
  Yountville page permanently stuck showing 10 fake "transcript" rows
  that were actually a copy of the agenda (from a since-removed code
  path), and a Dublin page permanently stuck showing no language on
  `/meetings` even after `swagit.py`'s language-detection fix landed,
  because a fresh recheck would only ever add a *second*,
  correctly-labeled version without promoting it over the stale one.

  Fixed with two new helper functions plus a new `current_default`
  lookup at the top of `ingest_resolution()`, before any version is
  created:
  - `_is_real_improvement(current_default, new_language)` — narrowly
    scoped to the two confirmed real cases, not a blanket "always
    promote the newest": true if the current default has no real
    segments at all, or has segments but no detected language while the
    fresh version has one. If the current default already has both real
    segments and a language, a fresh duplicate-ish version isn't
    confidently better and is left alone — avoids flip-flopping the
    default unpredictably. When true and a new version was actually
    created this ingest, `promote_transcript_version()` (already built
    for the transcription-job completion path) is called on it — the
    Dublin-style half.
  - `_default_looks_like_copied_agenda(current_default, agenda_items)`
    — true if the current default's segment texts are structurally
    identical, in order, to the *freshly resolved* agenda_items in this
    same ingest. Detects the Yountville failure mode generally (any
    page with that same data shape), not by matching old warning-message
    text, which would only ever catch that one historical bug. When true
    and no new version was created this ingest (nothing better found
    either), the stale default is demoted (`is_default = False`) even
    without a replacement, rather than staying stuck forever.
  Both checks only ever run when a `current_default` already exists — a
  brand-new page's first version keeps its existing simple
  `is_default=True`-on-creation behavior unchanged.

  Verified with 5 new real-DB integration tests
  (`tests/test_ingest_promotion.py`): the Dublin case (promotes a newly
  language-detected version over a language-less default), the
  Yountville case (demotes a copied-agenda default when a recheck finds
  real agenda but no segments), a stability check (no promotion when the
  default already has both segments and a language), a brand-new-page
  sanity check (no crash with no existing default), and a negative case
  for the agenda-copy detector (a default with real, non-agenda-matching
  segments is correctly left alone). Full suite green (126 tests).

  Not yet done, left as a residual live item: actually running
  `/admin/recheck-archive-page` against the two real motivating pages
  (Yountville, Dublin) to confirm this fires correctly outside of tests
  too — needs `ADMIN_STATS_TOKEN`, which this session doesn't have — and
  the originally-planned audit of all 12 permanent pages for the same
  stale-shape issue, now that there's a real fix to apply if any others
  turn up. See BACKLOG.md.

- **[Done 2026-08-08] Swagit's ALL-CAPS `#transcript-fragments` text now
  gets re-cased for readability, reusing the existing shouting-caption
  standard instead of inventing a second one.** Confirmed live on the
  real Dublin, CA meeting: the grouped word-fragments (see the grouping
  entry above) were still genuinely ALL CAPS at the source ("GOOD EVENING
  AND HAPPY NEW YEAR..."), reading as shouting even once grouped into
  real lines. `app/utils/vtt_parser.py` already had exactly this problem
  solved for Granicus's VTT captions (confirmed real on San Francisco's
  all-caps live captions) via `normalize_shouting_caption()` (renamed
  from `_normalize_shouting_caption` to make it importable — no other
  behavior change) + `_sentence_case()`: detects roughly-all-uppercase
  content (not per-cue, so a normal transcript with a few capitalized
  acronyms is never touched) and re-cases it. `swagit.py`'s
  `#transcript-fragments` branch now calls the same function on its
  grouped segments (converted to the dict shape the function expects,
  written back onto the `TranscriptSegment` objects afterward) right
  after grouping — reuses the exact tested detection/casing logic rather
  than a second Swagit-specific implementation, and correctly no-ops on
  a hypothetical future Swagit deployment that turns out to emit
  normal-case text. Verified with a new integration test
  (`tests/test_swagit.py::test_resolve_normalizes_all_caps_transcript_fragments`)
  using the real all-caps Dublin wording end-to-end through `resolve()`.
  Full suite green (127 tests).

- **[Done 2026-08-08] `/meetings`' fuzzy/exact search toggle moved into
  the filters dropdown; filters laid out in deliberate rows; a real
  "Clear all filters" button added.** The fuzzy checkbox had been hidden
  entirely in an earlier pass (per an explicit request, based on a
  mistaken belief it was already inside the filters dropdown when it was
  actually in the main search bar) — real regression, since that left it
  reachable only via a raw `?fuzzy=true` URL param with no UI control at
  all. Restored into `archive/templates/meeting_list.html`'s actual
  filters `<form>` this time, alongside "Has transcript"/"Has agenda."
  Also fixed the messy layout the user flagged: the filters form used to
  be one flat `flex-wrap` container, so narrow checkboxes landed on
  whatever row had leftover horizontal space next to unrelated text/date
  fields — accidental grouping, not deliberate. Now three explicit
  `.filters-row` groups (fields / checkboxes / actions) stacked in a
  column, each wrapping independently. "Clear all" already existed as a
  plain muted text link shown only when a filter was active (an existing,
  easy-to-miss `.clear-filters` class matching this session's recurring
  "small text link, easy to miss" pattern) — now a real always-visible
  `.cassette-btn-outline` button (a new, visually lighter sibling to the
  existing bold `.cassette-btn`, so it doesn't compete with "Apply
  filters" for attention) next to "Apply filters." Verified with a Jinja
  render check; no backend changes needed (`fuzzy: bool = False` in
  `archive/main.py` already parsed the checkbox correctly, same
  convention as the existing `has_agenda`/`has_transcript` checkboxes).

- **[Done 2026-08-08] The AI-transcript disclaimer now appears everywhere
  an AI-generated transcript is actually shown, not just the meeting
  page, and has real visual identity.** Audited every surface: the
  on-page disclaimer (`archive/templates/meeting_page.html`) was the
  *only* place it existed — the `.txt` transcript export
  (`/m/{slug}/transcript.txt`) and the transcription-completion email
  (`archive/utils/email.py`) both quoted/exported AI-generated text with
  zero indication it might be wrong. Fixed:
  - `.txt` export: the same disclaimer text prepended when
    `active_version.source == "transcribed"`. Deliberately *not* added to
    the `.srt` export — SRT is a strict cue format meant for subtitle
    players, and a fake cue at 00:00 would visually overlay the video as
    if it were spoken dialogue, competing with the real first line;
    plain text has no such constraint.
  - Completion email: added unconditionally (every completion email is,
    by definition, about an AI-transcribed version — `send_completion_
    email()` only ever gets called from the transcription-job completion
    path), matching the on-page wording.
  - Styling: the on-page disclaimer moved off the plain amber `.warnings`
    pill every other transcript-quality message uses, onto a new
    `.ai-disclaimer` treatment that reuses the site's `.dymo-label-small`
    motif (the same "label-maker tag" look as the site wordmark and the
    `/subscribe` page's section tag) as a real visual flag — a small
    "AI TRANSCRIPT" badge next to the text, per an explicit request to
    give this one more identity than a generic warning, since it's
    telling a reader the text might contain fabricated sentences, not
    just "approximate."
  Verified with Jinja render checks (both templates) and the full pytest
  suite (127 tests, unaffected — template/CSS/email-copy changes only).

- **[Done 2026-08-08] `/meetings` search results now show a "✓
  Transcript" badge instead of a raw language code, and it's
  quality-aware, not just presence-aware.** Was: the listing showed
  `· en` (or `· es`, etc.) — not intuitive at a glance, per direct
  feedback, and beside the point anyway since the real question a viewer
  has is just "does this meeting have a transcript," not which language
  it's in. Replaced with a `✓ Transcript` badge, shown regardless of
  language (per explicit follow-up: language-independent, but *only* for
  quality transcripts) — `archive/db/crud.py`'s `list_pages()` used to
  set `has_transcript` from bare row presence (`version_id is not
  None`), which would badge a genuinely garbled transcript the same as a
  clean one. Now reuses the same `_GARBLED_MARKER` signal
  `_has_good_transcript()` already uses (built earlier this session for
  the Archive recheck cadence), inlined directly in `list_pages()`'s row
  loop rather than calling that function per row -- it does its own DB
  query per page, which would be a real N+1 across a results page;
  `transcript_warnings` is now pulled in the same single batched query
  `list_pages()` already runs, cheap since it's a short list unlike full
  segment JSON. Styled with `.has-transcript-badge` (`--accent` blue,
  no new hardcoded color). Verified with a new real-DB test
  (`tests/test_list_pages_search.py::test_has_transcript_badge_is_quality_aware_not_just_presence`,
  a garbled page and a clean page in the same query, asserting the badge
  differs) plus a Jinja render check. Full suite green (128 tests).

- **[Done 2026-08-08] "✓ Transcript" restyled as a real pill badge, pinned
  to a fixed right-hand column, with a light rubber-stamp treatment.**
  Direct design feedback on the badge added earlier the same session:
  the word "Transcript" only needs reading once before a viewer
  recognizes it by shape/color afterward, so it can run small; making it
  a real graphic element keeps it on one line; and it should land in the
  same vertical line of sight on every row regardless of how long that
  row's title/jurisdiction/date text happens to be, which inline
  middot-separated text can't guarantee.
  - Layout: `archive/templates/meeting_list.html`'s row markup split
    into `.calendar-candidate-main` (title + meta, grows/wraps
    naturally) and the badge as a sibling, with a new `.meeting-result-
    row` modifier class (`display:flex; justify-content:space-between`)
    added *alongside* the existing `.calendar-candidate` class rather
    than changing that class's own rules — `.calendar-candidate` is
    also used unmodified by the resolver's calendar-picker list
    (`renderCalendarPage()` in `player.js`), which doesn't have this
    two-level structure and would have misrendered if the base class
    itself became a flex container.
  - Visual: new `--success-bg`/`--success-fg` CSS variables (soft
    green), following the same paired-token pattern the existing
    `--pill-bg`/`--pill-fg` amber warning color already established,
    rather than a one-off hardcoded hex. Styled as a small stamped-
    looking pill — 2px border (not the soft pill-radius look), monospace
    uppercase text, a slight `rotate(-4deg)` tilt — matching the site's
    existing "Red Tape Recordings" government-document motifs (the
    dymo-label wordmark, cassette buttons) per an explicit "make it a
    tiny bit rubber-stamped, government aesthetic, don't overdo it"
    request. No texture/grunge image, just typography + a small rotation.
  Verified live in-browser (not just rendered HTML) against a real local
  resolver+Archive pair (matching production's reverse-proxy shape) with
  seeded real pages — checked both desktop and mobile widths: the badge
  stays pinned to the right/top-right as titles wrap, the filters
  dropdown (fuzzy toggle + rows) renders as intended, and the resolver's
  separate calendar-picker list is unaffected. Full suite green (128
  tests, no test changes needed — this was a pure CSS/template layout
  pass on already-tested data).

- **[Done 2026-08-08] The "Red Tape Recordings" dymo-label wordmark no
  longer forces the navbar hamburger onto a second line on mobile.**
  Confirmed live at 375px width (a real iPhone-class viewport): the
  full-size label alone measured 312px wide, leaving the 56px toggler no
  room in the 351px available (375px viewport minus the navbar
  container's own padding) — it wrapped to its own row below the
  wordmark. Added the codebase's first `@media` query (none existed in
  either stylesheet before this) to both `app/static/style.css` and
  `archive/static/style.css` (kept in sync manually, per that file's own
  header comment): below 576px, `.navbar-brand .dymo-label` gets a
  smaller font-size/padding/letter-spacing, scoped to the navbar
  wordmark specifically so the desktop-size `.dymo-label` used for the
  `/subscribe` page's larger heading elsewhere is unaffected. Verified
  live in-browser at both 375px (label now 203px, ~91px of real margin
  before the toggler, confirmed via `getBoundingClientRect()` that both
  elements' vertical ranges genuinely overlap on one row, not just
  visually close) and desktop width (font-size unchanged at 19.52px,
  confirming the media query doesn't affect wider viewports). Full suite
  green (128 tests, unaffected — pure CSS change).

- **[Done 2026-08-08] Transcript auto-scroll softened; video pinned in a
  sticky column on desktop — the two fixes decided together for the
  jarring-jump complaint.** Was: watching via the playhead jerked the
  page down to the transcript continuously (a `timeupdate`-driven
  `highlightSegment()` call ran `scrollIntoView({block: 'center'})` on
  every tick, even when the active line was already visible), and
  because the video wasn't pinned, there was nothing to jump back up
  *to* once it scrolled away. Built exactly as decided (Picture-in-
  Picture ruled out: this app renders video two different ways — native
  `<video>` vs. a YouTube iframe — and PiP only works cleanly against
  the former, so it'd behave inconsistently by platform):
  - **Softened auto-scroll**: `highlightSegment()`
    (`shared_static/deep_link.js`) gained an optional third parameter,
    `scrollBlock`, defaulting to `'center'`. The continuous
    `timeupdate`-driven call sites (`app/static/player.js` and
    `archive/static/meeting_page.js`, both `wireSharedControls()`) now
    pass `'nearest'` — a real no-op per the `scrollIntoView` spec when
    the target is already visible, so it only moves the page when the
    active line has genuinely scrolled out of view, and moves it the
    minimum distance rather than forcefully recentering every tick.
    Every *deliberate* one-time jump (`applyDeepLink()` on page load, a
    "Go to time" submit, a transcript-line click) was left on the
    default `'center'` — those are cases where firmly centering the
    target is exactly what was asked for, so only the passive
    follow-along behavior needed softening, not `highlightSegment()`
    itself.
  - **Sticky video on desktop**: a genuine two-column CSS Grid layout,
    not just a `position: sticky` bolted onto the existing single-column
    page — a full-width sticky video would have been impractically tall
    on wide screens (16:9 scales with width), leaving little room to
    read the transcript beneath it. Deliberately narrow (`minmax(220px,
    300px)`), per direct product framing: most viewers here are
    deep-linking to a specific moment and just need audio plus a visual
    confirmation of who's speaking, not a large frame for reading
    slides — someone who genuinely needs to read a presentation would
    open the source video fullscreen directly rather than use this
    tool's transcript view. `app/templates/meeting.html` and
    `archive/templates/meeting_page.html` both gained a new
    `#transcriptColumn` wrapper around the agenda/transcript sections
    (no ID changes to existing elements, so no JS changes needed beyond
    the scroll-block fix above) — sharing one grid cell/row with
    `#videoSection` in the other column gives the sticky video real
    vertical room to move within, bounded by that row's full height
    rather than just the video's own short natural height. `#meta` and
    the report-problem/transcribe forms stay full-width via `grid-column:
    1 / -1`, above/below the two-column area. The pre-existing `.toolbar`
    sticky-to-viewport-top rule (a prior, narrower fix for the same
    underlying complaint) is now redundant once the whole `#videoSection`
    sticks as one unit, and would otherwise nest two independent sticky
    contexts against each other — set to `position: static` specifically
    within the new desktop breakpoint, left untouched (still doing its
    original job) below it. Below `900px` (comfortably above
    `.meeting-page`'s own 860px max content width + padding) everything
    stays single-column, matching mobile's prior behavior unchanged.
  Verified live in-browser on both pages (not just rendered HTML) against
  real local resolver+Archive pairs with seeded multi-line transcripts,
  at a genuine 1280px desktop width: confirmed the video's on-screen
  position is pixel-identical across two screenshots taken before and
  after scrolling the transcript column, and confirmed it naturally
  scrolls away once its shared row's content is exhausted (correct
  sticky behavior, not a bug) rather than floating forever. Full suite
  green (128 tests, unaffected — template/CSS/JS layout change only).

- **[Done 2026-08-08] Real transcribe button styling + a full round of
  live-review feedback on the sticky video column above, on both
  `app/templates/meeting.html` and `archive/templates/meeting_page.html`
  (kept in sync, per convention).** Started as a small styling pass
  (`.link-button` → `.cassette-btn` on the "Transcribe this meeting from
  audio" toggle; `.report-problem-status`/`.transcribe-status` rewritten
  from hardcoded `#2f855a` green into a shared pill treatment using new
  `--success-bg`/`--success-fg`/`--error-bg` CSS variable pairs, matching
  `.warnings`' existing amber-pill language), then substantially expanded
  after live testing surfaced a real layout bug plus several rounds of
  direct feedback:
  - **`#reportProblemForm`/`#reportProblemToggleWrap` and
    `#toggleAutoScrollBtn`/`#seekForm` overlapping the sticky video on
    scroll (real bug).** These started as separate grid items sharing
    `#videoSection`'s grid row via explicit `grid-row` line numbers — but
    a sticky element's "stick range" is bounded by its own row, and two
    independently-sized sticky-adjacent siblings in the same row fought/
    rode over each other as the page scrolled. Fixed by wrapping
    `#videoSection` together with the report-problem toggle/form *and*
    the transcribe-request toggle/form into one new `#videoColumn`
    container, made sticky as a single unit — removes the whole class of
    problem (one sticky box, sized to its own real content) and lets
    `#videoColumn`/`#transcriptColumn` use plain column-only grid
    auto-placement again, no more explicit row numbering needed. On
    Archive specifically, this also required hoisting the
    "should the transcribe CTA show at all" condition (`not
    (active_version and active_version.segments and active_version.source
    == "transcribed")`) out of two duplicated inline conditionals (one in
    the "has a transcript" transcript-section branch, one in the "no
    transcript" branch) into a single `show_transcribe_cta` template
    variable computed once, since the CTA now lives in one place instead
    of inline with whichever branch happened to render.
  - **Auto-scroll toggle + "Go to time" moved below the video** (resolver
    only — Archive never had these), into a new `.video-subtoolbar` div,
    per direct feedback ("let's move those to below the video," after an
    initial too-narrow assumption that only the seek form needed to
    move). Found and fixed a real CSS bug in the same pass: a blanket
    `.video-subtoolbar .btn { width: 100% }` rule also matched the seek
    form's own submit button (it carries `.btn` too), fighting the seek
    form's flex layout and squashing the timestamp input to ~21px while
    pushing the button past the column's right edge. Narrowed to
    `#toggleAutoScrollBtn` specifically; both controls now stack full-
    width (`flex-direction: column; align-items: stretch`) so their
    left/right edges always align regardless of column width — confirmed
    via `getBoundingClientRect()` (both rows: left 234px, right 534px,
    exact match) after a follow-up request to align them.
  - **"Copy Link to Current Time" → live "Share video at X:XX" label +
    fading toast.** The toolbar button's label now updates every
    `timeupdate` tick (`Share video at ${formatTime(...)}`, mirroring the
    existing `updateNoTranscriptTime()` pattern), so a click can no longer
    swap the label to "Copied!" the way it used to — a separate
    `#linkToCurrentToast` element handles that instead. Iterated twice
    more per feedback: text changed to "Copied to clipboard", duration
    5s (was 2s), and repositioned from beside/below the button to
    floating *above* it — implemented as a `position: absolute` overlay
    (`bottom: 100%`, centered, its own pill background/shadow) inside a
    new `.copy-control` positioning wrapper around just the button (not
    the whole `.toolbar`, whose own `position` flips between sticky/
    static across the desktop breakpoint and would've made an
    inconsistent containing block).
  - **Transcribe button relocated + relabeled.** Moved into the new
    `#videoColumn` (previously lived at the bottom of the transcript
    column) so it sits directly under the video alongside "Report a
    problem," and renamed from "Transcribe this meeting from audio" to
    "Request Transcript from Audio" per direct feedback.
  - **Tighter meta-block spacing.** `.meta p` had no `margin-bottom`
    override on either stylesheet, so the browser's ~1em default
    paragraph spacing (not `.source-link`'s own already-tight margin) was
    the real cause of "too much space" between the jurisdiction/date line
    and "View original source" below it. Fixed with `margin: 0 0
    0.25rem`.
  - **Always-visible transcript scrollbar.** `.transcript-list` gained
    `scrollbar-width: thin` + `scrollbar-color` (Firefox) and styled
    `::-webkit-scrollbar*` rules (Chrome/Safari/Edge — merely styling
    `::-webkit-scrollbar` switches these browsers from invisible overlay
    scrollbars to always-reserved-space classic ones), so the box reads
    as a scrollable window at a glance instead of looking like a hard
    content cutoff.
  - **Shorter agenda box.** A long agenda was pushing the "Transcript"
    heading below the fold. `.agenda-section .transcript-list` now caps
    at `max-height: 220px` (vs. the main transcript list's `60vh`) — the
    agenda is secondary/reference material here, not the primary content.
  Verified live in-browser against a real local resolver+Archive pair
  (seeded Dublin, CA sample data, genuine 1280px desktop width) —
  discovered mid-verification that hitting the Archive dev server
  directly on its own port skips the resolver's `/archive-static/*`
  proxy route entirely (Archive's `base.html` references
  `/archive-static/...`, but Archive itself only mounts `/static`; the
  resolver's `app/main.py` has the actual `/archive-static/{path}` proxy
  route), silently serving an unstyled page — not a real bug, just a
  reminder to always test Archive pages through the resolver
  (`ARCHIVE_BASE_URL` pointed at the local Archive instance) rather than
  Archive's own port directly. Confirmed on both pages: no overlap
  scrolling all the way to the page bottom, seek-form/auto-scroll edges
  pixel-aligned, toast reads "Copied to clipboard" and floats above the
  button, agenda visibly shorter with "Transcript" on-screen without
  scrolling. Full suite green (128 tests, unaffected — template/CSS/JS
  layout change only).

- **[Done 2026-08-08] Transcription-complete email: brand-lite styling +
  a "forward this" ask, per the four open questions decided the same
  day (see prior BACKLOG.md entry, now removed).** `archive/utils/
  email.py`'s `send_completion_email()` was three unstyled `<p>` tags;
  rewritten as a table-based HTML email (a single outer `<table>`, not
  just divs, since Outlook desktop's Word rendering engine handles
  table layouts far more predictably) with the site's real colors/font
  hand-inlined as literal hex/font-family values on each tag — `--primary`
  navy `#2c3e50`, the amber warning-pill pair `#ffe6a1`/`#a84b00`, Georgia
  serif — since most email clients strip `<style>` blocks and CSS
  variables outright. No logo asset exists in this repo yet (confirmed,
  same gap as `CLAUDE_BACKLOG.md`'s og:image note) so the "brand" header
  is a plain red bar with the wordmark as styled monospace text, not an
  image. The AI-transcript disclaimer keeps its exact existing wording
  (matches the on-page/on-export versions) but now renders in the same
  amber-pill visual language as `.warnings`/`.ai-disclaimer` instead of
  plain colored text. The excerpt gets a left-border blockquote treatment;
  "Read the full transcript" is now a real button-styled link (white bg,
  2px black border, monospace bold — same visual family as `.cassette-btn`,
  hand-inlined since email clients can't load the real stylesheet). Per
  the decided scope: no "support us" ask (site has nothing concrete to
  point it at yet — split back out as its own live BACKLOG.md entry for
  later), reframed as a plain one-line "forward this email, or share the
  link" ask instead — no new share-button code, just copy; the naive
  first-500-characters excerpt was left unchanged (already built, no
  known complaints yet to justify a smarter picker). Verified by
  rendering the real function's output (monkeypatched `_send()` to
  capture the HTML instead of calling Resend) with real sample content
  and viewing it live in-browser — confirmed the header bar, navy
  heading, amber disclaimer pill, italic bordered excerpt, button-styled
  link, and forward-this line all render as intended. Full suite green
  (128 tests, unaffected — no tests assert on this function's HTML
  content).

- **[Done 2026-08-08] Matched-context snippet under each `/meetings`
  search result**, e.g. "...5.4 City <mark>Council</mark> Participation
  in the 2026 St. Patrick's Day Parad..." — real quoted excerpt from the
  meeting's own agenda/transcript text, not just the bare title/date/
  jurisdiction row. New `find_snippet()` in `archive/utils/search.py`
  (alongside the existing `matches()`/`tokenize()`/`build_corpus()`):
  given a query and an ordered list of body texts, returns the first
  match with ~50 chars of surrounding context on each side (ellipsis
  only where the text was actually truncated), the matched span wrapped
  in `<mark class="search-match">` — reusing the exact highlight class
  the in-page transcript search already uses, rather than inventing a
  second visual language for "this is a matched term." Fuzzy mode
  matters here specifically: a fuzzy match's span is the *real* word
  found in the source text (e.g. a transcript's actual typo "trafic"),
  never the query term itself, so a snippet always quotes what the
  source genuinely says — the alternative (splicing the query term into
  someone else's sentence) would read as silently doctored. Non-matched
  portions of the snippet are HTML-escaped; only the deliberately
  inserted `<mark>` tag is left raw, so the caller can render with a
  `safe` filter without reopening any injection risk from scraped or
  AI-transcribed source text.

  `archive/db/crud.py`'s `list_pages()` calls `find_snippet()` per
  *displayed* row only (not every filtered match — a snippet nobody's
  about to see costs nothing to skip), passing `[transcript_text,
  agenda_text]` — deliberately excluding title/jurisdiction, which
  already render directly above any snippet in `meeting_list.html`, so
  a title-only match (e.g. searching "Council" against "Jan 13, 2026
  City Council") correctly shows no redundant snippet, falling through
  to whichever other field actually matched instead (confirmed live:
  that exact query surfaced the agenda's "5.4 City Council
  Participation..." line, not a repeat of the title). New `.search-
  snippet` CSS in `archive/static/style.css` (Archive-only, like the
  rest of `/meetings`' layout — the resolver has no keyword search over
  transcripts).

  Verified with 6 new unit tests (`tests/test_archive_search.py`):
  exact-match context extraction, fuzzy match quoting the real
  misspelled word rather than the query term, multi-text ordering/empty-
  text skipping, no-match returns `None`, HTML-escaping of surrounding
  text while leaving the inserted `<mark>` tag raw, and ellipsis only
  appearing where truncation actually happened. Also verified live
  in-browser against the real seeded Dublin, CA sample through the
  resolver's proxy: an agenda-body match ("fireworks"), a transcript-
  body match ("pledge"), and the title-suppression case ("Council")
  above. Full suite green (134 tests — 6 new).

- **[Done 2026-08-08] Real pytest coverage for the PrimeGov and YouTube
  adapters — both previously at zero, per BACKLOG.md's "zero test
  coverage" note.** Prompted directly by a user-found real sample
  (`https://okc.primegov.com/Portal/Meeting?meetingTemplateId=68482`,
  Oklahoma City) resolved live against the actual adapters first — real
  video (delegates to a YouTube embed), 3503 real English auto-caption
  segments — which also surfaced the separate date/jurisdiction gap
  logged as its own live BACKLOG.md entry.

  New `tests/test_youtube.py` (11 tests) and `tests/test_primegov.py` (5
  tests), both using the exact real video id/title/uploader/upload_date
  from that OKC sample as fixture data rather than synthetic values.
  YouTube's real dependency, yt-dlp, stays genuinely untouched/unmocked
  — these monkeypatch `YouTubeAssetFinder._extract_info()` instead (a
  plain staticmethod, the exact seam `resolve_video_id()` calls through),
  so only *yt-dlp's result* is stubbed, not the library itself. Covers:
  `extract_video_id()`'s regex across every real URL shape (watch,
  youtu.be, embed, shorts, live); the full `resolve_video_id()` happy
  path (title/date/jurisdiction/video_url/segments all pinned against
  the real OKC values, including the *current, imperfect* upload_date-
  derived date — see the companion BACKLOG.md entry, this test
  deliberately pins today's real behavior rather than the eventually-
  fixed one); manual-vs-auto-generated caption warning; non-English
  caption warning; no-captions-available warning; a missing `upload_date`
  correctly leaving `date` as `None`; and the 2026-08-08
  `ignoreerrors: False` fix specifically — a `yt_dlp.utils.DownloadError`
  now surfaces its real message through the raised `ValueError` instead
  of a generic guess (see that same day's YouTube removed/blocked bug
  fix in this file).

  `test_primegov.py` covers `PrimeGovAssetFinder`'s own scraping/
  delegation logic (using `aiohttp_mock`'s existing `FakeResponse`/
  `mock_session` pattern for the page fetch, same as every other
  fixture-backed adapter test): extracting the real `var videoUrl =
  "..."` shape and delegating to `YouTubeAssetFinder`; the documented
  `source_url` quirk (stays the original PrimeGov URL, not the delegated
  YouTube one — pinned directly, since this is the one behavior this
  class exists to provide over a plain Legistar/CivicPlus-style
  delegation); and the no-video-found case (agenda-only
  `meetingTemplateId` page) returning a warning instead of raising.

  eScribe is now the only adapter of the original three still at zero
  coverage — narrowed BACKLOG.md's entry accordingly. `dedupe_rollup_cues`
  itself already had direct unit tests in `tests/test_vtt_parser.py`
  before this pass; not re-tested here through the YouTube adapter, since
  that would just be redundant coverage of the same pure function. Full
  suite green (149 tests — 15 new).

- **[Done 2026-08-08] Real bug found and fixed via the first-ever eScribe
  sample with actually-populated captions: `parse_vtt()` was silently
  corrupting every single cue's text with the *next* cue's number.**
  User-found live sample:
  `https://pub-bakersfield.escribemeetings.com/Meeting.aspx?Id=981f78d7-8211-4b4b-b066-5f93b4fd5e74`
  (Bakersfield, CA) — resolved cleanly end-to-end (video, 174 real
  English caption segments, no warnings) except every segment's text
  ended with a stray trailing number: `"...City Council\n2"`,
  `"...pleasure to\n3"`, etc. This closes BACKLOG.md's long-standing
  "eScribe caption content-quality unverified... none were populated"
  gap — the per-language VTT filename convention (confirmed structurally
  on Richmond, CA) turns out to work as designed once a city's captions
  are actually populated.

  Root cause, confirmed by fetching the real raw `.vtt` file directly:
  Bakersfield's captions number every cue on its own line immediately
  before the timestamp line — e.g. `1\n00:26:21.932 --> 00:26:24.711\n
  The 330 p.m. meeting...`. This is spec-legal WebVTT (section 4.1
  explicitly allows an optional cue-identifier line, the same convention
  SRT uses for its sequence numbers), but `app/utils/vtt_parser.py`'s
  `parse_vtt()` only ever recognized `WEBVTT` and blank lines as
  non-text lines — any other non-blank, non-timestamp line got appended
  as trailing text onto whichever cue was still open, which for an
  identifier line is always the *previous* cue (the one that just closed,
  not the one about to start).

  Fixed with a one-line lookahead: rewrote the line-by-line loop to check
  whether the *next* line matches the timestamp regex before deciding a
  non-timestamp line is real cue text — if the next line is a timestamp,
  the current line is a cue identifier and gets skipped instead of
  appended. Deliberately lookahead-based rather than "skip any line that
  looks like a bare number," so a genuinely short real cue (e.g. "Yes.")
  is never mistaken for an identifier just because it's short (pinned by
  its own test). No other real fixture (Granicus/YouTube/CivicClerk/CA
  Legislature/Swagit-via-caption-file) showed this contamination symptom
  before or after the fix, so this was a pure correctness fix, not a
  behavior change for any already-passing case.

  Three new tests in `tests/test_vtt_parser.py`: the exact minimal repro
  (numbered identifier lines swallowing the wrong cue's text), a
  guard against the short-real-cue false positive, and a real trimmed
  25-cue fixture (`tests/fixtures/escribe/bakersfield_ccm330_captions.vtt`,
  the actual Bakersfield file's first 25 cues) pinning the live bug and
  its fix together. Verified live in-browser too, not just via
  `resolve()`/unit tests: the actual `/meeting?url=...` page renders the
  full clean transcript with correct clickable `[26:21]`-style timestamps
  and no stray trailing digits anywhere. Full suite green (152 tests — 3
  new here, on top of the prior PrimeGov/YouTube entry's 15).

- **[Done 2026-08-08] `/meetings` added to the site nav.** User ran this
  directly (not this session) — confirmed live: `redtaperecordings.com`'s
  navbar now links to `/meetings` as "Search Meetings," and the prior
  "Look Up a Meeting" link reads "Add Meeting."

- **[Done 2026-08-08] All three real live pages confirmed stuck on stale
  pre-fix data are now fixed — user ran `/admin/recheck-archive-page`
  directly (this session never had `ADMIN_STATS_TOKEN`).** Verified live
  against all three, not just taken on faith:
  - `.../m/dublin-ca-2026-01-13-jan-13-2026-city-council` — transcript
    now renders as clean, de-shouted, word-grouped sentences ("3, 2, 1.
    Good evening and happy new year to everyone...") instead of the old
    36,085 ALL-CAPS word fragments; `/meetings` now shows the "✓
    Transcript" badge; page shows two versions ("en (scraped)" active,
    "unknown (scraped)" demoted) confirming the promotion logic kept the
    old version reachable rather than deleting it.
  - `.../m/yountville-ca-2026-04-21-apr-21-2026-town-council-budget-workshop`
    — even better than expected: the fake agenda-copied-into-segments
    version is now demoted ("unknown (scraped)"), and the *active*
    default is a real, good-quality self-transcribed AI version ("en
    (transcribed)") with the AI-transcript disclaimer rendering
    correctly — a transcription job evidently completed for this page
    since the original bug was found.
  - `.../m/california-state-senate-2026-08-06-senate-floor-session` —
    transcript renders normally with real content (Senate roll call),
    confirming the language-detection fix applied.

  One minor side-effect noticed while verifying, logged as its own new
  BACKLOG.md entry: Dublin's `/meetings` search-result *snippet*
  (distinct from the page itself) still shows old ALL-CAPS text, since
  `find_snippet()` searches across every `TranscriptVersion`'s
  concatenated text (including demoted ones) without distinguishing
  which version actually matched.

- **[Done 2026-08-08] Archive permanent pages now have the resolver's
  "no transcript yet" live-playhead + copy-link feature.** Ported
  `app/templates/meeting.html`'s `#transcriptMissing` block and
  `app/static/player.js`'s `updateNoTranscriptTime()`/`noTranscriptLinkBtn`
  wiring into `archive/templates/meeting_page.html` and
  `archive/static/meeting_page.js` — same pattern as the transcribe-
  request and report-a-problem features, each deliberately duplicated
  into both services rather than shared, since Archive's page is
  server-rendered while the resolver's is built from JSON client-side.

  One deliberate adaptation, not a straight copy: the live-timestamp
  block only renders when `page.video_url` is present (`{% if
  page.video_url %}` inside the new `#transcriptMissing` branch) — a
  real Archive-only case the resolver doesn't need to handle the same
  way, since a server-rendered page can genuinely have no video *and*
  no transcript at once (e.g. an eScribe page with only a live Vimeo
  stream, no archive — see `EscribeAssetFinder`'s own docstring), where
  "tracking the playhead" wouldn't make sense with nothing to play. That
  case still falls back to the original plain "No transcript available
  for this meeting" text. `updateNoTranscriptTime()`/`noTranscriptLinkBtn`
  wiring lives inside `wireSharedControls()` (the same function that
  already drives `linkToCurrentBtn`'s live label), since both need the
  same `adapter` — `noTranscriptLinkBtn` keeps the resolver's simpler
  swap-the-label-text-to-"Copied!" behavior (not the dynamic-label
  version `linkToCurrentBtn` needed, since this button's label isn't
  itself dynamic), and — being Archive-only — doesn't call the
  resolver's `trackEvent()`, which doesn't exist on this service at all
  (confirmed: no analytics setup anywhere in `archive/templates/base.html`).

  Verified live against two freshly-seeded real Archive pages through
  the resolver's proxy (the established correct way to test Archive
  pages — hitting Archive's own port directly skips `/archive-static/*`
  and breaks styling, a lesson from earlier this session): a video-
  present/no-transcript page, where seeking the video and dispatching a
  real `timeupdate` event moved `#noTranscriptTime` from "0:00" to
  "0:45" in sync with the video's own displayed time, and a direct
  `.click()` on `#noTranscriptLinkBtn` correctly appended `?t=45` (no
  `line=`, since there are no segments to match) to the URL; and a
  no-video/no-transcript page, confirmed still falling back to the
  original plain "No transcript available for this meeting" text
  unchanged. Full suite green (152 tests, unaffected — template/JS
  change only, no existing Jinja-render tests cover this template).

- **[Done 2026-08-08] `MAX_CONCURRENT_TRANSCRIPTION_JOBS` raised from 3
  to 15, per direct request.** `archive/db/crud.py`'s
  `create_transcription_job()` — a plain constant, no other logic
  touched. Note for later: raising this widens the *queue* (more
  requests get accepted into `queued`/`in_progress` instead of a 429
  "at capacity" rejection), it doesn't speed up processing — the single
  worker process still claims and processes one chunk at a time,
  serially (`worker/main.py`'s `run_forever()`), so a deeper queue means
  longer real wait times per job, not more throughput. No test asserted
  the specific value (only a docstring comment referenced the constant
  by name), so nothing else needed updating. Full suite green (152
  tests, unaffected).

- **[Done 2026-08-08] Fixed `/meetings` search-result snippets surfacing
  stale text from a demoted `TranscriptVersion`.** Found while verifying
  the Dublin recheck fix earlier the same day: the meeting page itself
  rendered a clean, de-shouted transcript, but its search-result snippet
  still showed the old ALL-CAPS text. `list_pages()` (`archive/db/
  crud.py`) already builds `transcript_text_by_page` by concatenating
  *every* version's segments (needed so a query matching only a demoted
  version's text still finds the page), but `_snippet_for()` was reusing
  that same all-versions blob for the *displayed* excerpt too, with no
  way to tell "matched in the current version" from "matched in an old
  one."

  Fixed by tracking a second dict, `default_transcript_text_by_page`,
  populated only from the version with `is_default=True` (one extra
  column, `TranscriptVersion.is_default`, added to the existing
  per-version query rather than a new query) — `_snippet_for()` now
  builds its excerpt only from that. `_matches_page()`'s boolean check is
  untouched, still searching every version, so the page still correctly
  shows up in results even when the only match is in demoted text — it
  just shows no snippet in that case, rather than a misleading one, since
  a viewer clicking through would never actually see that text on the
  page itself.

  Two new tests in `tests/test_list_pages_search.py`: extended the
  existing demoted-version test to assert `snippet is None` once the
  matching keyword only exists in the demoted version, and added a new
  positive-case test confirming a keyword matching the *current* default
  version still produces a real snippet as before. Full suite green (153
  tests — 1 new, on top of the demoted-version test's new assertion).

- **[Done 2026-08-08] Archive passive recheck cadence now depends on
  transcript quality, not just page age — built earlier this session,
  documented retroactively here after its BACKLOG.md entry was found
  still marked open despite the code already existing.** Exactly the
  two-piece design BACKLOG.md described: (1) `lookup_page_for_url()`
  (`archive/db/crud.py`) now returns a `has_transcript` field alongside
  `{slug, url, updated_at}`, via a new `_has_good_transcript()` helper —
  true only when the page's default `TranscriptVersion` has real,
  non-empty, non-garbled segments (same signal `/meetings`' quality-aware
  badge already uses); (2) `app/main.py` gained
  `ARCHIVE_RECHECK_AFTER_NO_TRANSCRIPT = timedelta(hours=1)` alongside the
  existing 30-day `ARCHIVE_RECHECK_AFTER`, and `/api/resolve`'s
  archive-redirect path picks between them based on the looked-up page's
  `has_transcript` flag — missing/falsy defaults to the shorter window
  (including the case where the Archive being talked to predates this
  field entirely, so an old deployed Archive doesn't accidentally get a
  30-day-only viewer stuck rechecking too rarely). Covered by
  `tests/test_lookup_has_transcript.py` (3 tests: real transcript → true,
  no version at all → false, garbled version → false).

- **[Done 2026-08-08] New platform: Viebit, the real video platform
  underneath NYC Council's Legistar instance — a real second gap fixed
  along the way (NYC's own domain was never actually reachable through
  `LegistarAssetFinder.resolve()` at all, a bug in the fix that was
  believed done), plus real, populated, correctly-parsed transcript
  captions for NYC Council meetings (a first).** Fully traced live from
  the NYC Legistar calendar page down to real caption content, entirely
  via plain HTTP — no headless browser needed anywhere in the chain,
  despite Minneapolis's LIMS platform (found the same day) needing one
  for a structurally similar-looking problem.

  **The trace**: NYC's video links (`a.videolink[onclick]`, confirmed on
  a real 40-video-link calendar page) call `OpenTelerikWindow('Video.aspx
  ?Mode=Auto&URL={base64}&Mode2=Video', 'video')` instead of every other
  Legistar city's plain `window.open('Video.aspx?Mode=Granicus&ID1=...')`
  — but `Video.aspx?Mode=Auto&...` itself does a real server-side 302
  redirect chain straight through to a Viebit `/embed/vod?v={id}` URL
  (confirmed via `curl -I -L`), so no base64-decoding is needed in this
  repo's own code at all — `LegistarAssetFinder`'s existing
  `allow_redirects=True` fetch already lands there directly once it
  recognizes the onclick shape. The landed page's plain HTML (confirmed
  identical whether fetched via the outer `/vod/?v=...` URL the base64
  decodes to, or the `/embed/vod?v=...` URL it redirects to) contains a
  `var pageConfig = {...};` JS object with everything needed: a real HLS
  `master.m3u8` URL, a real populated VTT caption URL (1748 raw cues on
  the real sample checked), and a title.

  **Real second bug found and fixed**: `LegistarAssetFinder.resolve()`'s
  own domain check (`"legistar.com" not in netloc`) was a bare substring
  check that evaluates `True` (i.e. "not Legistar") for NYC's actual
  `legistar.council.nyc.gov` pages too, since that string doesn't contain
  "legistar.com" as a substring — meaning even after `detect_platform()`
  was taught to route nyc.gov to `LegistarAssetFinder` (the earlier
  2026-08-08 fix, believed complete), `resolve()` itself would have sent
  NYC's own domain straight back into `resolve_via_platform()`, which
  re-detects "legistar" and would have recursed on the exact same URL
  rather than ever reaching `_find_video_links()`. Fixed by extracting a
  shared `_is_legistar_domain()` static method (used at both of the two
  call sites that previously duplicated the buggy check), matching
  `detect_platform()`'s own domain list instead of drifting from it.

  **Build**: new `app/platforms/viebit.py` (`ViebitAssetFinder`) — parses
  `pageConfig` via a small regex + `json.loads`, builds the m3u8 URL from
  `video.src[0].storage + .url`, and reuses existing shared utilities
  rather than writing new caption-format logic: `dedupe_rollup_cues()`
  (built for YouTube's differently-shaped growing-word rollup) turns out
  to already correctly collapse Viebit's two-line rolling-caption shape
  too — confirmed empirically (1748 raw cues → 876 clean segments) — since
  an exact-duplicate-text cue is just the trivial case of that function's
  existing prefix-matching merge logic, no new dedup code needed; and
  `normalize_shouting_caption` (already called inside `parse_vtt`)
  handles the source's ALL-CAPS text. Registered in
  `app/platforms/__init__.py`; `"viebit.com"` added to `detect_platform()`.
  `LegistarAssetFinder._find_video_links()`'s onclick regex extended to
  match `OpenTelerikWindow(...)` alongside the existing `window.open(...)`
  pattern (same `a.videolink` selector for both).

  **Real, disprove-not-just-unverified finding, documented honestly, not
  swept under a "should work" assumption**: fetching the real
  `master.m3u8` from this session's own sandboxed dev environment gets a
  403 from a Varnish-fronted CDN (`vbfast-vod.viebit.com`) even with
  realistic Referer/Origin/User-Agent headers, while a real browser (this
  session's own Browser tool) loads the identical URL successfully with
  no errors. Checked several hypotheses (Referer, Origin, a `vv=` token
  from the page's own `vod-check-in` POST) without finding the real
  gating mechanism — left as an open BACKLOG.md item to recheck from
  production rather than guessed at further. Transcript/caption fetching
  is a completely different, ungated path on the same CDN domain and is
  unaffected either way — confirmed via the real 876-segment result
  rendering correctly on the actual `/meeting?url=...` page, live, not
  just via `resolve()`.

  **Tests**: `tests/test_viebit.py` (4 tests, using real fixtures —
  `tests/fixtures/viebit/nycc_vod_page.html` and `nycc_captions.vtt`,
  both fetched live from the real sample) covering the full happy path
  (title/date/video_url/segment-count/language/de-shouting all pinned
  together against real data), a missing-`pageConfig` page returning a
  warning not a crash, a page with no caption track, and `_format_date`'s
  edge cases. Three new tests added to `tests/test_legistar.py`: the real
  40-candidate NYC calendar page (`tests/fixtures/legistar/
  nyc_council_calendar.html`) raising a proper pick-list via the
  `OpenTelerikWindow` onclick shape, a single NYC meeting delegating all
  the way through to a real Viebit result, and a direct pin of the
  `_is_legistar_domain()` fix (NYC's domain now correctly recognized,
  Viebit's correctly rejected). Verified live end-to-end via a real local
  resolver: `/api/resolve` and the rendered `/meeting?url=...` page both
  confirmed against the actual NYC URL, not just the mocked tests — the
  transcript renders with correct clickable timestamps and clean,
  de-shouted text; the video element shows a load failure, consistent
  with the CDN-403 finding above. Full suite green (160 tests — 7 new).

- **[Done 2026-08-09] eScribe: real per-item agenda timestamps and a
  jurisdiction fallback, both built from the same real Bakersfield, CA
  sample the `parse_vtt()` cue-identifier fix used, plus the last of the
  original three zero-coverage adapters now has real tests.** Investigated
  further than the original "no start-time attribute spotted" note in
  BACKLOG.md (written from a first look at just the `.AgendaItem` DOM) —
  a deeper look at the full page source found a `var video = {
  Bookmarks: [...] }` JS array with real per-item timestamps
  (`{"AgendaItemId": N, "TimeStart": ms, "TimeEnd": ms}`), keyed by the
  same numeric id each `.AgendaItem`'s title link passes to
  `SelectItem(N)`.

  Not every agenda item gets a bookmark — confirmed live: only 4 of the
  real page's 10 items did (apparently only substantive/voted-on items,
  not procedural ones like "ROLL CALL"). Rather than fabricate a start
  time for the other 6 (a real, unverified claim, and risky besides:
  `TranscriptSegment.start` is a required field, and several items
  sharing a made-up identical timestamp would likely trip the frontend's
  existing "unreliable timestamps" all-identical heuristic and cost the
  4 real ones their clickability too), `_extract_agenda_items()`
  (`app/platforms/escribe.py`) simply omits items with no matching
  bookmark rather than guessing. An item with more than one bookmark
  (confirmed: one real item had two, presumably discussed then revisited
  later) uses its earliest occurrence.

  Separately, `jurisdiction` fixed the same way BACKLOG.md's open
  question framed it: Bakersfield's page body has no "City of X" phrase
  (just a plain address), so a new `_jurisdiction_from_subdomain()`
  fallback derives it from the reliable `pub-{city}.escribemeetings.com`
  subdomain instead, used only when the body-text regex doesn't match.

  New `tests/test_escribe.py` (7 tests, closing the last gap of the
  original three zero-coverage adapters — PrimeGov/YouTube closed
  2026-08-08): the real Bakersfield sample end-to-end (title/date/
  jurisdiction/video_url/segment-count all pinned, plus all 4 real
  agenda items' text and timestamps), the subdomain-fallback helper
  directly, malformed/missing-Bookmarks-array handling, an item
  correctly skipped when it has no matching bookmark, and the two
  existing no-video/no-caption warning paths (previously entirely
  unverified by any test). New fixtures: `tests/fixtures/escribe/
  bakersfield_ccm330_page.html` (the full real page) alongside the
  already-existing trimmed captions fixture from the `parse_vtt()` fix.

  Verified live end-to-end through a real local resolver, not just the
  mocked tests: `/api/resolve` and the rendered `/meeting?url=...` page
  both confirmed against the actual Bakersfield URL — "Bakersfield ·
  2026-07-15" renders in the meta line, and a real clickable 4-item
  Agenda section renders with correct `[29:13]`/`[1:08:36]`/`[1:48:40]`/
  `[2:09:36]` timestamps. (Hit a stale local dev-cache red herring
  first — `/api/resolve` returned 0 agenda items even after the fix was
  confirmed correct via direct Python calls; turned out to be `dev.db`
  caching a resolution from earlier the same session, before this fix
  existed — cleared by deleting the local cache file, not a bug in the
  new code.) Full suite green (167 tests — 7 new).

- **[Done 2026-08-09] Alexandria VA's "meeting dates can't be extracted"
  gap closed — the real cause was one specific attribute-value blind
  spot, not a genuinely dateless page.** The original BACKLOG.md entry
  said "no date signal anywhere in the page body" — true for *visible
  text* specifically (confirmed live: Alexandria's real Granicus pages
  are thin client-rendered shells, no `og:title`, no `<h1>`, under 700
  characters of body text total, and no `view_id` to cross-reference an
  RSS feed either), but a closer look found the page's Agenda/Minutes
  document links are still server-rendered as plain `data-url="...pdf"`
  attributes — invisible to every existing date source here since none
  of them ever look at attribute values, only `soup.get_text()`. Those
  filenames follow a real, consistent Legistar-hosted-Granicus
  convention: `..._YY-MM-DD_Docket.pdf` (confirmed live on clip 6490's
  real Agenda *and* Minutes links both landing on the same
  `_25-04-02_` date fragment).

  New `GranicusAssetFinder._extract_date_from_document_links()`
  (`app/platforms/granicus.py`) scans every `[data-url]` element for that
  pattern, converting the 2-digit year to `20XX`. Wired in as a true
  last resort in `resolve()` — after page-text extraction *and* the RSS
  fallback have both already failed — preserving the file's existing
  documented priority order (page's own signals > RSS > this new
  fallback) rather than risking it preempting a more authoritative
  source on some other city's page.

  New tests in `tests/test_granicus.py` (3 tests, using a new real
  fixture `tests/fixtures/granicus/alexandria_clip6490.html`): the full
  resolve path landing on `date == "2025-04-02"` with the real fixture,
  plus two direct unit tests of the extraction helper (a real match, and
  a document link with no date pattern returning `None`). Verified live
  end-to-end: both a direct `resolve()` call and the actual rendered
  `/meeting?url=...` page (`"City of Alexandria · 2025-04-02"` in the
  meta line) against the real clip 6490 URL. Full suite green (170
  tests — 3 new).

- **[Done 2026-08-09] Adopted Alembic for the Archive's Postgres
  schema** — the real fix, decided 2026-08-08, for a wall this repo hit
  three separate times: `Base.metadata.create_all()` (still run
  unconditionally on every startup, unchanged) can only ever *add new
  tables*, never alter an existing one, and the job-priority column and
  the materialized search column both need exactly that.

  New `archive/alembic/` (async template, `alembic init -t async`) +
  `archive/alembic.ini`. `env.py` doesn't hardcode a database URL or a
  placeholder metadata object — it imports the real
  `archive.db.engine.DATABASE_URL` (same resolution the app itself uses,
  so dev/test/prod all naturally point at the right database with
  nothing to keep in sync) and `archive.db.models.Base.metadata` (so
  `alembic revision --autogenerate` diffs against the real
  `MeetingPage`/`TranscriptVersion`/`TranscriptionJob`/
  `MeetingPageUrlAlias` models directly, not a stub).

  Generated the baseline migration
  (`archive/alembic/versions/..._baseline_schema.py`) by autogenerating
  against a genuinely empty SQLite database (not the local dev DB, which
  already has these tables and would've diffed as "no changes") —
  `CREATE TABLE` for all four tables plus every index/foreign key.
  Verified locally: `alembic upgrade head` against a fresh empty SQLite
  file produces a schema that diffs identical to `create_all()`'s own
  output (only real difference: the `alembic_version` bookkeeping table
  itself, plus a cosmetic `(CURRENT_TIMESTAMP)` vs `CURRENT_TIMESTAMP`
  default-clause rendering quirk — same value, just how SQLite's own
  introspection reports a `server_default` either way); `alembic
  downgrade base` cleanly drops everything back out. **Not verified
  against real Postgres** — this sandboxed dev environment has Postgres
  *client* tools (`psql`/`initdb`/`pg_ctl` via Homebrew) but no server
  binary, and installing one felt like more system-level footprint than
  this check warranted; flagged honestly in `archive/alembic/README.md`
  as worth a real check before the first production `stamp head`, since
  Postgres's own type/default rendering can differ from SQLite's.

  `archive/db/engine.py`'s `init_models()` gained a doc comment
  explaining the new split responsibility rather than being changed
  itself — it stays exactly as it was (unconditional `create_all()` on
  every startup) since that's still the right zero-friction behavior for
  fresh local/test databases; Alembic is additive, the real source of
  truth for *production* schema changes specifically, not a replacement
  for `create_all()` everywhere.

  **Deliberately not run against production** — this session has no
  production `DATABASE_URL` access, and the one-time adoption step
  (`alembic stamp head`, telling production "you're already at the
  baseline, don't try to `CREATE TABLE` over existing rows") is exactly
  the kind of real, hard-to-reverse production-database action that
  needs the person who actually has that access to run it deliberately,
  not something to do on their behalf. Full instructions, including the
  exact one-time command, written into `archive/alembic/README.md`
  rather than left to be reconstructed later. Full suite green (170
  tests, unaffected — new tooling/config only, no application code
  changed).

- **[Done 2026-08-09] Job priority, built the moment Alembic unblocked
  it — `TranscriptionJob` gets a real `priority` column, and the one
  real call site (a live visitor's own request) now uses it.** Exactly
  the plan already written down: `priority: Mapped[int]` added to
  `TranscriptionJob` (`archive/db/models.py`, `default=10,
  server_default="10"` so the Alembic migration safely backfills every
  already-existing row rather than needing them nullable first). New
  named constants in `archive/db/crud.py` — `PRIORITY_LOW = 0` (reserved
  for the still-unbuilt self-generated idle-time batch work),
  `PRIORITY_MEDIUM = 10` (every real request today) — kept as literals
  in the model rather than imported, avoiding a `models` → `crud` import
  cycle, with a comment on each side pointing at the other so they don't
  quietly drift apart. `claim_next_chunk()`'s `.order_by()` gained
  `priority.desc()` ahead of the existing `created_at.asc()`, and
  `create_transcription_job()` — confirmed still the only real call site
  creating a job from an actual request — now sets
  `priority=PRIORITY_MEDIUM` explicitly.

  New migration `archive/alembic/versions/..._add_priority_to_
  transcription_jobs.py`, generated by autogenerating against a fresh
  copy of the baseline schema (not the shared local dev DB). Verified
  the backfill specifically, not just "applies without erroring": a real
  row inserted *before* running the migration correctly ended up with
  `priority=10` after `alembic upgrade head`, and `alembic downgrade -1`
  cleanly dropped the column back out.

  New test in `tests/test_transcription_jobs.py`:
  `test_claim_next_chunk_prefers_higher_priority_over_older_job` —
  creates an older job, drops its priority to `PRIORITY_LOW` directly via
  the DB (mirroring how `test_list_pages_search.py` already reaches past
  the public API for a scenario it doesn't expose), then creates a
  newer `PRIORITY_MEDIUM` job through the real `create_transcription_job()`
  path and confirms `claim_next_chunk()` picks the *newer, higher-priority*
  one first — proving priority actually overrides FIFO order, not just
  coincidentally agreeing with it. Full suite green (171 tests — 1 new).

- **[Done 2026-08-13] `generic_fallback.py`'s title/jurisdiction backfill
  now handles a second real separator style, an agenda-link
  `title`-attribute backfill, and a stale User-Agent that was silently
  blocking at least one real site.** Two small, independently-confirmed
  gaps from BACKLOG.md's "Platform coverage — open questions" section,
  both fixed in one pass since they touch the same function.

  **Sebastopol, CA's `" - "`-separated `<title>` shape** (`_TITLE_TAG_DASH_RE`,
  `app/platforms/generic_fallback.py`): the existing `_TITLE_TAG_PIPE_RE`
  only matched `"Org | Jurisdiction"` (CRRMA's shape); Sebastopol's real
  title reads `"City Council Meeting January 6, 2026 - City of
  Sebastopol, California"`. Added a second regex, tried only when the
  pipe pattern doesn't match, scoped to the *last* `" - "` in the title
  (a greedy first group backtracks past any earlier hyphen inside the
  meeting name itself) with the tail required to contain a comma (a real
  jurisdiction reads "City[, State]"; a bare meeting-name segment
  wouldn't) — covered by
  `test_backfill_does_not_split_on_a_hyphen_inside_the_meeting_name` in
  `tests/test_generic_fallback.py`.

  **Real, separate blocker found live while verifying this fix, fixed in
  the same pass**: a direct (non-mocked) resolve against the real
  Sebastopol URL came back completely empty even with the new regex in
  place — the page fetch itself was silently failing.
  `generic_fallback.py`'s hardcoded `User-Agent` (`Chrome/91.0.4472.124`,
  copy-pasted from 2021, shared verbatim across 11 files in
  `app/platforms/`) gets a 403 from this site's WAF; a plain `curl` with
  a current Chrome UA string against the identical URL gets a clean 200
  with the real page. Bumped **only `generic_fallback.py`'s own UA** to a
  current Chrome string — deliberately not touched in the other 10
  files, which target known vendor platforms already confirmed working
  with the old string; changing an already-working request header
  sitewide needs its own per-platform verification, not a drive-by
  bundled into this fix. Confirmed this isn't the same root cause as the
  still-open Wayne County, MI Akamai block (BACKLOG.md): re-resolving
  that page live with the new UA is still fully blocked, so that one's a
  deeper fingerprint check, not just a stale UA string.

  **Sacramento County's OnBase-family agenda-link `title` attribute**
  (`_AGENDA_LINK_TITLE_RE`): a real, already-flagged cheap signal —
  `_find_agenda_link()` already finds and returns Sacramento's agenda PDF
  link; that same `<a>` tag's own `title` attribute carries real
  per-meeting text the code never read (`"View Agenda Packet for BOARD
  OF SUPERVISORS BOARD OF SUPERVISORS MEETING on 8/11/2026 9:30:00
  AM"`). `_find_agenda_link()` now returns `(url, title_attr)` instead of
  a bare URL, threaded through both `resolve()` call sites into
  `_backfill_metadata_from_page()` (now takes an optional
  `agenda_link_title` param). Backfills `title`/`date` only, each
  independently guarded by "only if still empty" — never jurisdiction,
  since the county/body name never appears in this attribute on the one
  confirmed example (the page's own `<title>` tag is too generic:
  "Sacramento County Board of Supervisors Meetings," no per-meeting
  text). The apparent word duplication in the real example
  ("BOARD OF SUPERVISORS BOARD OF SUPERVISORS MEETING") was left as-is
  rather than deduped — with only one real example in hand, it's
  plausibly a real "{meeting type} {body name} MEETING" template that
  happens to coincide here, not a confirmed universal artifact worth
  guessing a dedup rule for.

  Both fixes verified against the real live pages (not just mocked
  fixtures): `GenericFallbackAssetFinder().resolve()` run directly
  against both real URLs now returns `title="City Council Meeting
  January 6, 2026"`/`jurisdiction="City of Sebastopol, California"` for
  Sebastopol, and `title="Board Of Supervisors Board Of Supervisors
  Meeting"`/`date="2026-08-11"` for Sacramento. Sacramento's page was
  already archived (`meeting-38ca49`) — ran
  `scripts/backfill_archived_pages.py --url-contains saccounty` for real
  against production, confirmed via a direct fetch of
  `redtaperecordings.com/m/meeting-38ca49` that the live page now shows
  the fixed title. Sebastopol's page was never pushed to the permanent
  Archive (only viewed via the ephemeral best-effort flow), so there was
  nothing to backfill there.

  6 new tests in `tests/test_generic_fallback.py` (22 total in that
  file), full suite green (635 tests).

- **[Done 2026-08-14] Add IQM2 platform adapter (Atlanta, GA), a real
  Granicus-family wrapper with genuinely rich per-item timestamped
  agenda data.** New `app/platforms/iqm2.py`, confirmed live against a
  real Atlanta, GA meeting
  (`atlantacityga.iqm2.com/Citizens/Detail_Meeting.aspx?ID=4294`).

  **Video**: IQM2 doesn't host video itself. A past meeting's real
  "Video" link on the plain meeting-detail page carries a static
  `OnClick="javascript:OpenWindow('/Citizens/SplitView.aspx?Mode=Video&
  MeetingID={id}&...')"` — an upcoming/no-recording meeting's link stays
  a bare `href="#"` with no onclick, the reliable signal used to tell the
  two apart. That `SplitView.aspx` page's raw static HTML (a plain
  fetch, no JS/browser execution needed) carries a literal
  `<!-- MEDIA URL: https://archive-stream.granicus.com/... .m3u8-->`
  comment — a real, direct Granicus HLS URL. Confirmed the stream URL
  itself needs a real (non-default) User-Agent — CloudFront 403s a plain
  `curl` default UA, 200s with a current browser UA — and has **no**
  Referer restriction, unlike ChampDS's VOD2 path (`champds.py`). Since
  there's no Granicus *page* to hand off to (just a bare stream URL, not
  a `granicus.com` URL `GranicusAssetFinder.resolve()` could take), this
  adapter sets `video_url`/`video_format="m3u8"` directly rather than
  delegating — a new pattern in this codebase, not the Legistar/CivicPlus
  page-delegation shape.

  **Real per-item timestamps, found while researching video** — the same
  `Detail_Meeting.aspx?ID={id}` URL, requested with
  `Target=Detail&CssClass=AgendaOutline&Mode=Video&Frame=Nothing` added,
  renders every agenda item as a real
  `<a class="AgendaOutlineLink" onclick="javascript:SetPosition({seconds});">`
  — confirmed live with 65 real items on the one Atlanta example,
  spanning plain procedural entries ("Roll Call") and full real
  ordinance/resolution text with real council-member names. This
  "AgendaOutline" page conveniently carries the *same* `<title>` as the
  plain detail page, so this adapter only ever needs two fetches total
  (the AgendaOutline page for title/date/jurisdiction/agenda_items, plus
  `SplitView.aspx` for the video URL), not three. Items with no
  `SetPosition` onclick (real supporting-document links like "Minutes
  Packet," appointment letters, bio PDFs sharing the same CSS class) are
  filtered out rather than becoming bogus zero-duration agenda entries.
  `end` for each item is the next item's `start` (or its own `start` for
  the last item), mirroring `granicus.py`'s existing
  `_fetch_agenda_items()` convention exactly.

  **Title/date/jurisdiction**: the vendor's own generic "Web Outline"
  branding string (confirmed identical across both real customers, not
  per-city) is a reliable fixed separator in the page's `<title>` —
  `"{YYYY}/{MM}/{DD} {time} {meeting name} - Web Outline -
  {jurisdiction}"`. Jurisdiction already carries a spelled-out state name
  in both confirmed examples ("City of Atlanta, Georgia," "The County of
  Santa Clara, California"), so `jurisdiction_enrich.enrich_jurisdiction_text()`
  is called for consistency with every other adapter but is a no-op here
  in practice.

  **Santa Clara County, CA — the second real confirmed customer — title/
  date/jurisdiction extraction works identically there too**, but every
  real past committee/commission meeting checked had no video link
  populated at all, unlike Atlanta's (degrades to an honest "No video
  found for this meeting," not a crash or guess).

  **Update 2026-08-14, user-requested: checked a real past Board of
  Supervisors meeting specifically (`ID=17601`, Aug 11 2026 Regular
  Meeting) — resolves cleanly with zero code changes.** Real title/date/
  jurisdiction, a real playable Granicus HLS URL (same CloudFront
  403-without-a-real-UA / 200-with-one pattern as Atlanta, confirmed via
  direct `curl`), and 72 real timestamped agenda items. So the earlier
  "no video" finding was real but narrower than it looked: video
  population on this instance is body-type-dependent (smaller
  commissions/committees don't always get a recording attached), not a
  structural gap in this adapter or a per-customer limitation the way it
  first appeared. New regression test,
  `test_resolve_finds_real_video_on_scc_board_of_supervisors_meeting`
  (`tests/test_iqm2.py`), using a real trimmed fixture from this exact
  meeting. Full suite green (643 tests).

  `detect_platform()` (`app/platforms/base.py`) gets a new `"iqm2.com" in
  netloc` branch; registered in `app/platforms/__init__.py`. README's
  "Supported platforms" table gets a new IQM2 row — and, caught in the
  same pass, a missing CHAMP/ChampDS row that had never been added when
  that adapter shipped (a pre-existing documentation gap, unrelated to
  this build).

  7 new tests in `tests/test_iqm2.py`, using real trimmed fixtures (both
  the Atlanta success case and the Santa Clara no-video case are real
  confirmed shapes, not invented). Full suite green (642 tests). Verified
  directly against the real live Atlanta and Santa Clara pages (not just
  mocked fixtures) before writing tests, and again after, via
  `IQM2AssetFinder().resolve()` called directly against both real URLs.

- **[Done 2026-08-14] Generic-fallback rebuild: diagnose → route → point.**
  A five-phase rebuild of `app/platforms/generic_fallback.py` (plus
  `media_scan.py`), planned against every open coverage gap in BACKLOG.md
  and backtested against the real gap URLs themselves. Architecture per
  the user's own framing: the fallback is a *diagnostic router* — figure
  out what the page needs, then hand off to machinery that already exists
  (YouTube embed → `YouTubeAssetFinder`; known-platform link → that
  adapter's `resolve()`; blocked fetch → headless refetch, then the same
  diagnosis again). Scorecard, measured by the new backtest harness
  against the live pages: **8 PASS / 9 FAIL before → 17 PASS / 0 FAIL
  after** across the six non-headless corpus pages during the build,
  and — the final full run, 2026-08-14, after the headless flag shipped
  to prod — **22 PASS / 0 PARTIAL / 0 FAIL across all 9 corpus pages**
  with `--include-headless`: six pages fully extract, Sebastopol gets
  its recognized-host video pointer, and PBC/Tucson return their
  documented honest-empty (both genuinely have nothing static to give;
  Tucson's escalation reaches the rendered page and confirms no video
  exists there at all, matching the user's own expectation for it).

  **Phase 0 — backtest harness + fixtures** (`scripts/backtest_fallback.py`,
  `tests/fixtures/generic_fallback/`): runs the fallback live against the
  real coverage-gap corpus (Sacramento, Maricopa, Tarrant, Seattle,
  Sebastopol, OCFL, plus headless-gated Wayne/PBC/Tucson rows) and prints
  a per-URL scorecard; exits nonzero on any non-headless FAIL. Fixtures
  are trimmed real captures with source URL + date in each header,
  including the real 550-byte Akamai 403 body and the full Tucson
  client-rendered shell. Corpus intake also included classifying all 223
  archived pages' source URLs by `detect_platform()` (66% granicus / 15%
  swagit / 8 fallback-routed spanning 6 site families) — which surfaced
  two unlogged production fallback failures (OCFL, PBC) now in the corpus.

  **Phase 1 — media_scan.py correctness** (also the fix for the
  three-county OnBase "no video" production bug): `media_type()` ran
  `endswith(".m3u8")` on the FULL url, so `playlist.m3u8?instance=1&token=`
  classified "unknown" and was dropped — the same full-URL check was
  hand-rolled in four adapters' format-pick loops, all replaced with a
  shared `is_hls_url()`. Plus per-candidate `html.unescape()` (the raw
  HTML's `&amp;token=` would reach the CDN as a literal `amp;token`
  param), deterministic document-order results replacing `list(set())`,
  query-string support in the src= pattern, a new JW-config `file:`
  pattern (Sacramento/Maricopa absolute m3u8, Seattle protocol-relative
  mp4 + relative srt), tightened bare-URL termination, and a
  segment-aware blocklist ("silicon" no longer eaten by "icon").

  **Phase 2 — resolve() restructure**: layered video tiers (URL-shaped
  YouTube ids over raw AND entity-unescaped HTML, nocookie embeds,
  Tarrant's bare `videoId = '...'` assignment gated on the iframe_api
  loader + single-distinct-id agreement; platform-link delegation;
  direct media), a caption candidate chain (`<track>` elements → plain
  caption-file `<a href>`s → scan results incl. JW `tracks:`, capped at
  3 fetches), and metadata breadth (og:title/twitter:title, h1 assembly,
  `video_date` meta, `<time datetime>`, heading month-name dates,
  URL-slug humanization last — every extractor only-fills-empty,
  confirmed shapes first).

  **Phase 3 — two-tier video pointer** (the user's explicit call: "the
  pointer where the video lives would be a GREAT outcome"):
  `ResolvedMeeting.video_link` + `video_link_recognized`, never placed in
  `video_url`; curated tier (Vimeo video/showcase links, numeric-id
  gated) renders "we recognize {host} as a regular video host", loose
  tier (video-shaped anchor text, non-junk third-party iframes) renders
  "we don't recognize {host}... proceed with caution" — copy per the
  user's own words. Resolver-page-only: link-only results never pass the
  archive push gate, so no archive schema change. Verified in-browser on
  a local resolver against the real Sebastopol page.

  **Phase 4 — opt-in backstop for dedicated adapters**:
  `scan_page_for_video_evidence()` packages the page-analysis tiers for
  adapters whose own extraction found no video; eScribe wired first ("no
  video integration" is its documented common outcome, pages are
  per-meeting; Perry GA's plain Vimeo live-stream link is the confirmed
  beneficiary shape). Backstop hits set `best_effort=True` + a
  provenance warning. Opt-in per adapter only — the user's call — since
  a blanket second pass on e.g. Cablecast's related-shows carousel could
  attach the wrong meeting's video.

  **Phase 5 — headless escalation, env-gated OFF**
  (`GENERIC_FALLBACK_HEADLESS=1`): at most one Chromium retry per
  resolve, on a block-family status (Wayne County's real Akamai 403), a
  small challenge-interstitial body, or an empty-evidence resolve of a
  near-empty shell (threshold tuned to Tucson's real 153-char shell;
  agenda_link deliberately excluded from the evidence gate after the
  real Tucson shell's nav "Agenda" link — the site-root junk link prod
  already showed — turned out to veto escalation on exactly the page
  needing it). First caller anywhere to survive
  `HeadlessBrowserUnavailable`; shipped disabled until playwright was
  verified on Render. Verified locally flag-on against the LIVE pages:
  Wayne County resolves fully through the browser; Tucson escalates and
  stays honestly empty (its pages genuinely have no video). **Enabled
  in prod later the same day**, after playwright-on-Render was verified
  for real (a fresh, never-archived LIMS meeting — `MarkedAgenda/COW/
  6144` — resolved fully through production; LIMS has no non-browser
  path, so that's direct proof, closing render.yaml's open build
  question from the 2026-08-09 incidents). End-to-end confirmed
  post-deploy: the previously fully-Akamai-blocked Wayne County page
  resolved through production's own browser and got archived as a
  permanent page.

  Two corpus expectations needed loosening for a legitimate reason worth
  recording: on residential networks yt-dlp *succeeds*, so the real
  YouTube title correctly wins over the page's own backfill (Tarrant,
  Wayne) — expectations now accept both the yt-dlp-success and
  Render-blocked paths.

  36 new tests across `test_media_scan.py`/`test_generic_fallback.py`/
  `test_escribe.py`; full suite green (672, from 643). README's fallback
  section rewritten. Residuals logged as a new BACKLOG.md entry (OCFL
  multi-part, PBC's texty shell, the video-only push-gate nuance,
  backstop expansion rules, unconfirmed-shape comments). Existing
  archived pages deliberately NOT re-resolved — the user's call:
  forward-looking fixes only.

- **[Done 2026-08-14] Branch ruleset on `main` requiring the `test` check
  — the second half of WO-2 (`AUDIT_EXECUTION_BRIEF.md`), closing the gap
  BACKLOG.md's "CI/CD" entry left open (a red workflow was visible but
  didn't gate merges).** Ryan created the ruleset directly in the GitHub
  UI (`gh` lacked no permission for this — see below — the UI was just
  faster): enforcement active, PR required with 0 required approvals,
  force-push and branch-deletion blocked, `test` (from
  `.github/workflows/test.yml`) as a required status check.

  **Verified for real, per WO-2's acceptance criteria**, not just read
  back from the API: pushed a throwaway branch
  (`test/ruleset-verify-failing-check`) with a deliberately failing test,
  opened PR #49, waited for the `test` check to go red, then confirmed
  `gh pr view --json mergeable,mergeStateStatus` reported
  `mergeStateStatus: "BLOCKED"` and — the stronger proof — that
  `gh pr merge --squash` was actively rejected ("is not mergeable: the
  base branch policy prohibits the merge"), not merely displayed as
  unmergeable. Closed the PR and deleted the branch (both remote via
  `gh pr close --delete-branch` and the local worktree) immediately
  after. Work was done in an isolated `git worktree` rather than on the
  checked-out `main`, since `main` had unrelated uncommitted changes
  (`AUDIT_EXECUTION_BRIEF.md` edits, a `_to_delete/` scratch folder) that
  weren't safe to disturb.

  **`gh` has full API access to repository rulesets** (`gh api
  repos/.../rulesets` and `PUT .../rulesets/<id>` both worked with the
  existing `repo` token scope) — worth knowing for next time, since the
  session was prepared to stop and hand this back to the UI if scope was
  missing.

  **Two follow-up refinements, same session, both via `gh api ...
  --method PUT` with a JSON body** (the form-encoded `-F 'rules[][x]=y'`
  flat syntax does *not* build nested rule-array objects correctly —
  confirmed by a 422 "data matches no possible input" on every rule past
  index 1 when tried; a plain JSON file via `--input` is the reliable
  path for this endpoint):
  1. `.github/workflows/test.yml`'s `on: push` (unfiltered) plus
     `on: pull_request` ran the `test` check twice per feature-branch
     push — confirmed live during the verification above (PR #49 showed
     two separate `test` check runs). Changed to `push: branches: [main]`
     — `pull_request` alone already covers every feature-branch push in
     this repo's PR-first workflow, so this halves Actions minutes and
     removes the ambiguity of two runs reporting under one status-check
     context.
  2. `allowed_merge_methods` on the ruleset's `pull_request` rule
     defaulted to `["merge", "squash", "rebase"]`; restricted to
     `["squash"]` to match `CLAUDE.md`'s own git-workflow convention
     (`gh pr merge --squash --delete-branch`), converting a habit that
     was previously just followed into one GitHub now enforces.

  **Left as-is, a deliberate tradeoff, not an oversight:**
  `strict_required_status_checks_policy` stays `false` — requiring
  branches to be up to date with `main` before merge would force a
  rebase-and-rerun on every merge, which is disproportionate at this
  repo's PR volume. The real cost: a PR that passed CI against an older
  `main` can still merge without re-running against the latest `main`,
  which matters most exactly when two sessions are working the repo in
  parallel the same afternoon (a real, repeated situation — see
  `CLAUDE.md`'s "worked on by more than one session" note). If two
  sessions ever actually break each other this way, flip this flag.

## Security hardening

- **[Done 2026-08-14] SSRF guard on `/api/resolve`** — WO-5 of
  `AUDIT_EXECUTION_BRIEF.md`, executed exactly as specified, from
  `AUDIT_2026-08-14.md` finding #2: `/api/resolve` will fetch arbitrary
  URLs with no destination guard.

  **The gap.** `ResolveRequest.url` (`app/main.py`) was a bare `str`.
  Anything that didn't match a known platform fell through to
  `generic_fallback.py`'s `GenericFallbackAssetFinder`, which did a plain
  `aiohttp` GET with `allow_redirects=True` and no scheme allowlist, no
  private/loopback/link-local/reserved-IP rejection, no per-hop redirect
  re-validation, and no response-size cap. `GENERIC_FALLBACK_HEADLESS=1`
  is on in production, so a blocked/challenge-gated fetch could also
  escalate to a real headless Chromium tab that would load whatever it
  was pointed at. An anonymous POST of
  `http://169.254.169.254/latest/meta-data/...` (the AWS/GCP/Azure
  instance-metadata address) or an internal Render hostname would be
  fetched from inside the network, with the response returned in the
  resolve payload.

  **The fix.** One new module, `app/utils/url_guard.py`:
  - `check_scheme()` / `check_destination()` — scheme allowlist
    (`http`/`https` only) plus hostname resolution and rejection of
    private/loopback/link-local/multicast/reserved/unspecified addresses.
    A literal IP (including one found in a redirect `Location` header) is
    classified directly with no DNS involved; a real hostname is resolved
    via the stdlib resolver off the event loop, with DNS resolution
    factored into its own `_resolve_hostname()` specifically so it's
    monkeypatchable in tests without touching the network.
  - `guarded_get()` — drop-in replacement for
    `async with session.get(url, allow_redirects=True, ...)` that follows
    redirects manually (capped at `MAX_REDIRECTS = 5`) and re-runs
    `check_destination()` on **every hop**, not just the entry URL — the
    case the brief specifically flagged as "the one people forget": a
    permitted host can 302 straight to a private one, and aiohttp's own
    `allow_redirects=True` has no concept of re-checking that.
  - `read_capped_text()` / `read_capped_bytes()` — reject a response body
    over `MAX_RESPONSE_BYTES` (10 MB), checking `Content-Length` as a
    cheap short-circuit and the real decoded/read length regardless of
    what that header claims (it's caller-supplied, not trusted alone).
    Documented honestly as a buffered cap, not a true streaming abort —
    `aiohttp`'s own `.text()`/`.read()` already buffer the body first;
    this bounds worst-case memory for what gets returned/parsed, while
    the existing per-request `ClientTimeout` already bounds worst-case
    latency.

  **Wired in at three points**, per the brief's explicit scope (the
  resolve entrypoint and generic_fallback's own fetches — no other
  adapter or endpoint touched):
  1. `/api/resolve` (`app/main.py`) calls `check_destination(req.url)`
     before any dispatch — archive lookup, DB cache, platform detection,
     all of it. A rejected URL returns `{"error": "blocked_url",
     "message": ...}` (200, not a 500) — a clean, user-facing rejection,
     never the underlying fetch/resolve machinery's own exception text.
  2. `generic_fallback.py`'s `_fetch_page()` (the main page GET) and
     `_try_fetch_caption()` (a caption URL discovered on the fetched
     page's own markup, just as caller-influenced as the entry URL) both
     now use `guarded_get()` + `read_capped_text()`/`read_capped_bytes()`
     instead of a bare `session.get()`.
  3. `headless_browser.py`'s `fetch_via_browser()` — the escalation path
     the brief explicitly called out as needing its own guard, since a
     real Chromium tab follows redirects and loads sub-resources entirely
     on its own, with no concept of a guard applied once to the entry
     URL. `check_destination()` runs on the entry URL before the browser
     is even touched, and a new `_guard_route()` is installed via
     `context.route("**/*", ...)` on every request the page makes
     (navigation, every redirect Chromium follows mid-navigation, every
     sub-resource) — broader than a navigation-only guard, but a
     Playwright route handler can't selectively apply to only
     navigations without dropping that same protection for the exact
     redirect case this exists to close.

  **A real bug the test suite caught before it shipped**:
  `BlockedURLError` subclasses `ValueError` (deliberately, so callers can
  catch it as a validation error) — but the first draft of
  `_check_content_length()`'s oversized-`Content-Length` check *raised*
  `BlockedURLError` from inside a `try/except (TypeError, ValueError):
  pass` block meant to catch a non-numeric header, which silently
  swallowed its own exception. Caught by
  `test_read_capped_text_rejects_an_oversized_content_length_header` in
  the new `tests/test_url_guard.py` failing on the first run; fixed by
  parsing the header outside the `try`/`except` that's only meant to
  guard the `int()` call.

  **Test coverage** (`tests/test_url_guard.py`, plus additions to
  `tests/test_headless_browser.py` and `tests/test_generic_fallback.py`):
  every rejected class (bad scheme, no hostname, loopback, private
  ranges, link-local including the real cloud-metadata address,
  multicast, reserved, unspecified, a hostname that resolves to a
  private address, DNS failure), the redirect-to-private-IP case
  specifically (with the private target deliberately left **unmocked** in
  `mock_session`'s routes, so if the guard ever failed to block it before
  issuing the second request, the mock's own "unmocked request" assertion
  would fail the test independently of the `BlockedURLError` expectation
  — the test can't pass by accident), redirect-chain length capping,
  response-size capping (`Content-Length` header and real body length,
  both text and bytes), the headless route interceptor's abort/continue
  behavior, and the `/api/resolve` endpoint itself returning a clean
  `blocked_url` JSON body (never a stack trace) for a rejected URL.
  `tests/test_generic_fallback.py` gained an autouse `_fake_public_dns`
  fixture patching `url_guard._resolve_hostname()` to a fixed public IP —
  every existing test in that file uses real-looking domains
  (`crrma.org` etc.) purely as fixture data, never actually fetched, so
  without this the new guard would have made real DNS calls during the
  test suite. `tests/aiohttp_mock.py`'s `FakeResponse` gained a `headers`
  dict (previously absent) so the mock could simulate a redirect
  `Location` header and a `Content-Length` header.

  All 721 tests pass locally (up from 686 before this change — 32 new in
  `tests/test_url_guard.py`, plus 3 more in `tests/test_headless_browser.py`),
  `npm test` (29 tests, unaffected — no JS touched) passes. **Not yet
  verified live** — this PR
  had not been merged/deployed as of this writing; see the PR description
  for the live-verification plan once it lands (fetch a known-blocked
  target like `169.254.169.254` against the deployed `/api/resolve` and
  confirm a clean `blocked_url` response, then confirm a real, previously-
  working `generic_fallback` resolve — e.g. the Wayne County MI Akamai
  case — still resolves normally through the new guard).

  **Deliberately out of scope**, per the brief's own scoping: the other
  15+ platform adapters' own `session.get()` calls (Legistar, Granicus,
  CivicPlus, etc.) fetch from known, curated vendor hosts rather than an
  arbitrary caller-supplied one, and weren't touched; the two
  transcription endpoints (`/api/transcription/check-feasibility`,
  `/api/transcription/submit`) call `finder.resolve()` directly rather
  than through `/api/resolve`, so a URL that reaches generic_fallback via
  either of those still gets `guarded_get()`'s protection at the fetch
  layer, but not the entrypoint-level rejection `/api/resolve` gets before
  any dispatch happens — worth a follow-up if that gap ever matters in
  practice, not addressed here since the brief scoped this WO to "the
  resolve entrypoint" specifically.
