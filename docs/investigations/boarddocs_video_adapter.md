# BoardDocs video adapter — spec from a live mechanism and two real examples

**Status: specced, not built (2026-09-14).** Ryan asked for an adapter
after Tallahassee FL turned out to run its City Commission on BoardDocs
with real per-meeting YouTube video (rtr-business
`ENUMERATION_METHODS.md`, "Follow-up to §43", 2026-09-13). §43
(2026-08-29) had excluded BoardDocs as "K-12 agendas, no reliable
video". Both are true: BoardDocs is mostly school boards, and video is
rare, but where it exists it is exposed through one fixed, unauthenticated
mechanism that an adapter can read. This file records that mechanism,
the two live examples, the negative controls, and the house rule that
shapes how the adapter may call the host.

## The mechanism, confirmed live 2026-09-14

All calls need a `Referer` header of the tenant's own Public page
(`https://go.boarddocs.com/{st}/{slug}/Board.nsf/Public`) and a browser
User-Agent; without the Referer, CloudFront answers 403 (§43's finding,
still true).

1. **Tenant page** `GET /{st}/{slug}/Board.nsf/Public` (HTML). The inline
   script carries `bd.videoservice = "N"`: `"0"` no video service, `"1"`
   YouTube, `"2"` Vimeo, `"3"` a third service (`video.js` has a
   `case "3"` branch; not yet seen live). Also present: `bd.app_is_plus`,
   `bd.app_is_pro`, `bd.app_is_lt` (tier), and the organisation name in
   `<div id="SiteTitle2">`.
2. **Meeting list** `GET /{st}/{slug}/Board.nsf/BD-GETMeetingsListForSEO`
   (JSON array). Fields: `Name`, `Description`, `Unique` (12-char meeting
   id), `Date` (ISO, midnight UTC). Newest first. Tallahassee returns 967
   meetings; the list includes future meetings, so filter `Date <= today`.
3. **Per-meeting video id** `POST /{st}/{slug}/Board.nsf/VIDEO-GetAgenda?open&{random}`
   with form body `id={Unique}`. The response is an HTML fragment whose
   first script sets two hidden inputs:
   `$("#video-dialog input[name=video_id]").val("IwHZSEpgwDw")`. The
   value is the YouTube video id (service 1) or Vimeo id (service 2); an
   empty string means no video for that meeting. The rest of the fragment
   is the agenda outline, one `<li>` per item, usable as agenda items.
4. **Player**: `video.js` builds `//www.youtube.com/embed/{id}?&rel=0`
   for service 1 and `//player.vimeo.com/video/{id}` for service 2.

So a resolve is: read the tenant flag once, list meetings, POST once per
meeting to get the id, then hand the id to `YouTubeAssetFinder` (service 1)
or the Vimeo adapter (service 2) for video and captions, keeping the
BoardDocs `goto?open&id={Unique}` page as `source_url` and the agenda
outline from the same fragment as `agenda_items`. Same delegation shape
as PrimeGov.

## Live examples (2026-09-14, from this Mac)

| Tenant | Organisation | `videoservice` | Recent meetings checked | With a video id | Newest with video |
|---|---|---|---|---|---|
| `fla/talgov` | City of Tallahassee, FL (City Commission) | 1 YouTube | 6 | 6 | 2026-09-09, `IwHZSEpgwDw` |
| `az/ccschools` | Colorado City Unified SD, AZ | 1 YouTube | 40 | 5 | 2025-06-09, `jbnk6tAyhlw` |

Negative controls, same method, same day:

| Tenant | Organisation | `videoservice` | Checked | With a video id |
|---|---|---|---|---|
| `tx/austinisd` | Austin ISD, TX | 2 Vimeo | 40 | 0 |
| `tx/nisd` | Northside ISD, TX | 1 | 40 | 0 |
| `ca/vusdca` | Vacaville USD, CA | 1 | 40 | 0 |
| `mo/cscsdr6` | City of St. Charles R-VI SD, MO | 1 | 40 | 0 |
| `md/cospmd` | Seat Pleasant, MD | 0 | — | — |
| `ca/sbcusd`, `ca/vusd` | San Bernardino City USD, Vista USD | 0 | — | — |

The flag alone is not a video signal: four of five flagged tenants
never fill in an id. The per-meeting POST is the only reliable check.
Ryan named Austin, Northside, St. Charles and Vacaville as test targets;
on today's data they are negative controls, and Vacaville in
`rtr-upcoming` is the *city* (Granicus), not the school district.

## House rule: on-demand reads only, never a scan

`https://go.boarddocs.com/robots.txt` is `User-agent: * / Disallow: / /
Crawl-delay: 1000`. This repo's politeness rule (CLAUDE.md) is to follow
a host's house rules. Reading one tenant's pages because a reader asked
for that government's meeting is what a browser does; walking hundreds of
tenants by script is what the file forbids. Therefore:

- The adapter resolves a meeting URL a user or the sweep already holds.
  It does not enumerate tenants.
- Per resolve: 1 tenant page + 1 list + at most N per-meeting POSTs
  (N = the number of meetings needed to find the newest with a video,
  capped at 40). Cache the tenant flag.
- No discovery sweep of `go.boarddocs.com`. Tenant slugs come from a
  government's own website links, the research file, or the Wayback
  index of Public pages (331 tenants captured before the index cut off;
  rtr-business scratch `bd/tenants_wayback.txt`), never from probing.

## What the adapter needs to handle

- URL shapes to recognise: `go.boarddocs.com/{st}/{slug}/Board.nsf/Public`,
  `.../Board.nsf/goto?open&id={Unique}`, `.../Board.nsf/vpublic?open`.
  `detect_platform()` should return `boarddocs` for the host.
- `videoservice` 3 is unmapped; log and return video-less until a real
  tenant shows it.
- The agenda outline in the fragment is plain `<li>` text with item
  numbers ("1.01 ..."); good enough for `agenda_items`, no times.
- Jurisdiction: `SiteTitle2` on the tenant page ("City of Tallahassee")
  plus the `{st}` prefix (`fla` = FL; the prefix is BoardDocs' own, not
  USPS: check the prefix table on first use of each new one).
- Tests: fixture the Tallahassee tenant page (flag), the list JSON (first
  3 rows), and one VIDEO-GetAgenda fragment; a synthetic empty-id fragment
  for the no-video branch; Colorado City as the second real fixture.

## Yield expectation

Honest and small. Of 972 research rows that mention BoardDocs, 969 are
school districts and 3 are municipal (Tallahassee, Seat Pleasant MD,
Culpeper County VA). Two tenants with live ids out of ten probed. The case
for building is Tallahassee's size (205,000) and that the mechanism is
fixed and cheap, not volume.
