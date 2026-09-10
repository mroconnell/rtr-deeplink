# Brief: the breadth sweep, platform-first (WO-144 onward)

Written 2026-09-10 from four read-only pilots run that morning (WO-140 to
WO-143) and Ryan's decisions in the coverage review. This is the brief for
the next round of coverage work. `docs/COVERAGE_HANDOVER.md` explains the
system; this file says what to build and run next, in what order, and
why. Findings come first. Untested ideas are at the end, marked optional.

## Goal

One meeting with video per government, for as many governments as
possible. Depth (many meetings per government) is not the goal here. If
the first video meeting fails to resolve, take the next one. That still
adds breadth.

Ryan's ingest rule stands. Only meetings with video become pages. Tier 1
(captions the server can fetch) and tier 2 (YouTube captions the local
fetch can get) are ingested with segments. Tier 3 (video, no reachable
captions) is queued for cloud auto-transcription. Agenda-only is
recorded as `no-video-found` and never ingested.

## What the pilots established

| Pilot | Question | Answer |
|---|---|---|
| WO-140 | If a sweep failed on a host with a known platform, does the platform's own listing API find video anyway? | Yes for 11 of 20. One of the 11 had 5,998 caption segments. |
| WO-142 | Should the platform API run before any site sweep? | Yes. On 29 untouched hosts it found real video for 8. On 20 already-swept hosts it agreed 18 of 19 times; the one miss was depth, fixed by thorough mode. |
| WO-141 | Which access rung answers a "blocked" host first? | Plain honest HTTP answered 12 of 30. Browser headers answered 3 more. The session rung answered 0. Headless answered 0 first and did worse than browser headers on the 4 hardest firewalls. 3 were real human-verification gates. |
| WO-143 | Can we learn a video's length, date and size without downloading it? | Yes, cheaply, on every platform in the queue. 6 of 25 queue entries were already dead links. |
| WO-157 | Does Granicus's RSS feed have a video mode? | Yes. Any mode value but "agendas" returns the video feed, about 100 KB against up to 8 MB for the archive table. Newest clip matched the table on 11 of 12 tenants; one lagged 12 days. "(No Video)" titles are closed-session placeholders. rtr-discovery's enumerator now reads it first in fast mode (WO-160). |
| WO-159 | Does a Legistar city's video live on a same-named Granicus tenant even when the Legistar page shows none? | Yes for 25 of 29. 16 of those 25 matched a real calendar meeting by body and date; 5 had video for a different body or government; 1 was empty. Same-name is a strong lead, never a proof. |
| WO-158 | Can a government's YouTube channel be joined to its own calendar by body and date? | 12 of 40 "no video found" CivicPlus sites link a channel; 2 of 40 produced a real match. About 5%. Shelved for now as a future project; see the YouTube section. |

Two things the pilots corrected:

- Headless browsing finds JavaScript-drawn links (the WO-133 result: 150
  hits on large governments). It does not get past firewalls. Firewalls
  detect a real browser's automation signals; a plain client with browser
  headers passes where headless does not.
- A "session" (load the page, keep its cookies, then call its endpoint)
  earned nothing on a blind sweep. It only helps on hosts studied one at
  a time. It is not a default rung.

## The method, in order

For every government in the candidate list:

1. **Platform API first.** If the government has a platform signature
   (the research file's suspected provider, a discovery tenant, or a
   YouTube channel matched to its gov id), list its meetings through
   rtr-discovery's enumerator for that platform, in thorough mode. Pass
   the gov id from the registry into the resolve step so a delegated
   video (a CivicPlus page linking to YouTube) keeps the government's
   identity. Take the newest meeting with a video signal. Resolve it. If
   it fails, take the next.
   Three platform rules from the 2026-09-10 pilots:
   - **Granicus**: read the video feed (`ViewPublisherRSS.php?view_id=N&mode=videos`)
     before the archive table; drop "(No Video)" titles; take the newest
     date, not the feed order. The enumerator does this now.
   - **Legistar**: whatever the meeting page says about video, probe the
     same-named Granicus tenant (`<slug>.granicus.com`, view ids 1 to 15)
     and accept a clip only when its body and date match the Legistar
     calendar. The adapter has this fallback for Yonkers (PR #858); the
     sweep version is filed in `BACKLOG.md`.
   - **CivicPlus**: `RSSFeed.aspx?ModID=` on a government's own domain is
     a CivicPlus signature; the calendar feed is a cheap meeting list
     (body, date, time) for sites without an AgendaCenter. Feeds carry no
     video.
2. **Plain HTTP with honest headers** for governments with a domain but
   no signature: fetch the home page and one hop of meeting links, look
   for a platform link. "Works" means the listing or a platform link was
   found, not merely a 200.
3. **Browser headers**, once, only after a 403 or a dropped connection.
   Never after a 404. Remember the answer per host.
4. **Headless browser**, only for hosts that answered 2 or 3 with a page
   that has no visible meeting link. One browser, one host at a time,
   real delay. This is where the JavaScript-drawn links are.
5. **Stop at a human-verification gate.** Record it. Never retry past
   it.

Whichever rung answers, record it per host as `access_mode`: `api`,
`plain`, `browser-headers`, `headless`, `challenge`, `dead`.

### YouTube

Prefer the delegating platform. A government page that links to YouTube
is the source; the YouTube video is delegated from it, and the page
carries the body, the date and the agenda. Enumerate a YouTube channel
directly only when no delegating platform exists after rungs 1 to 4. A
channel matched to a gov id counts as a platform signature for step 1.
The video-to-calendar join (WO-158: accept a channel video only when it
matches the site's own calendar by body name and a date within one day)
works, at about 5% yield, with some risk of off-mission video. Ryan
shelved it on 2026-09-10 as a future project; see
`docs/VIDEO_TO_CALENDAR_JOIN.md` and the parked entry in `BACKLOG.md`.

### The probe before queuing

Before a tier-3 video goes into the queue, probe it without downloading:
yt-dlp metadata for YouTube; two playlist fetches for HLS; one HEAD plus a
header-only ffprobe for a direct file; Vimeo's oEmbed; TelVue's page
JSON. Record duration, date and size in a sidecar CSV beside the queue.
Rules:

- Refuse a dead link (404, 403, empty playlist, removed video, TelVue
  duration zero, which means a live placeholder).
- Prefer meetings over nine minutes. Prefer shorter and smaller among
  plausible ones, so tier 3 transcribes faster. Do not reject long
  meetings outright; an 8.45-hour Anaheim meeting is real.
- Prefer recent dates.

### Reject reasons, two classes

Access reasons mean we could not look: `blocked-plain-http`,
`blocked-browser-headers`, `blocked-headless`, `cloudflare-challenge-blocked`,
`dns-unresolvable`, `timeout`. A later rung is worth trying.

Content reasons mean we looked and it was not there:
`no-platform-link-found` (after the full ladder), `meeting-without-video`
(a real, current meeting found, no video), `no-meeting-nor-video` (no
meeting found at all, so no video either), `video-without-meeting` (a
real video exists but no meeting to attach it to — a channel or feed
with recordings but no listing, date, or body; use only when that is
what actually happened), `off-mission`, `unsupported-platform-no-adapter`.
Do not re-run these. Re-run a content reason only when a platform gains a
new video signal we did not check.

`no-video-found` and `no-meetings-found` are older spellings of
`meeting-without-video` and `no-meeting-nor-video` respectively, still
present on rows written before 2026-09-10 (WO-164). They mean the same
thing; a sweep's own close-out retags its rows onto the newer names —
see `~/Documents/rtr-business/research/wo164_retag_rules.md` for the
exact mapping.

### After each government

Hand the tenant to rtr-discovery as a seed, with its gov id and the
`access_mode`, so depth happens later on discovery's own schedule.
Discovery today seeds only from Archive pages, so this needs a small
"seed from a candidates file" path.

## Candidate lists, in priority order

1. Governments with a platform signature and no page, never listed
   through the API. Pilot yield: about 1 in 4.
2. Last night's failures that carry a signature (resolve-failed,
   no-meetings-found, no-video-found on API platforms). Pilot yield: about
   1 in 2.
3. Signature-less rejects with an access reason: the hub sweep's 311,
   the headless run's 35 still blocked, the counties' 214 "dead" domains,
   the two-hop scan's 172 fetch errors. Expect roughly 40% to answer a
   plain honest client.
4. The 1,183 smaller governments the headless pass has not reached.

## Dashboard changes

- `access_mode` per host on the coverage registry.
- Reject reason split into the two classes above, as a column, so the
  "tested but not in Archive" table shows what is still worth trying.
- Queued hours, from the probe's sidecar file.

## Data quality to fix alongside (each is its own small pass)

- Four registry domains belong to a same-named government in another
  state (Ventura IA carries Ventura County CA's domain).
- About 1,300 gov ids appear on more than one research-file row; 87
  are genuinely ambiguous and need a human.
- Consolidated city-counties are in the research file but keyed badly,
  two ways. (1) Blank gov id on the Census long-form names
  ("Lexington-Fayette urban county", "Athens-Clarke County unified
  government (balance)", Macon-Bibb, Butte-Silver Bow, Anaconda-Deer
  Lodge, Hartsville/Trousdale, Greeley County). PR #842 makes those
  names resolve; re-run `rtr-business/research/add_gov_id_to_coverage.py`
  against a checkout at or after becf0f3 to fill them. (2) Two rows for
  one government with different ids (Philadelphia, San Francisco,
  Denver, Lafayette LA: a county id on one row, a city id on the other).
  The Fable - Q&A session is adding a county-to-city map in the
  resolver; after it lands, the same re-run keys both rows to one id and
  the duplicate pass can collapse them. Sitka is fine.

## Optional next steps, not yet tested

- The session rung for specific hosts: the Fremont pattern (load the
  page, take its token, call its endpoint). Worth a per-host study on
  the four hosts that stayed blocked under every rung.
- The full ladder on a sample of 50 hosts per firewall family, once, to
  learn each family's profile for the field guide.
- Re-check the 217 "confirmed no platform" headless verdicts with the
  platform-API step once signatures exist for them.
- Discovery in thorough mode on the governments that ingested last
  night, to add depth where breadth is already done.
- A shared apply helper for the research file so no script carries its
  own writer (the write protocol is `ENUMERATION_METHODS.md` §158).
