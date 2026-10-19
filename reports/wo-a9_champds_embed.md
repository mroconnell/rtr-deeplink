# A9. ChampDS embed test, 2026-10-16

## What was tested and why

Our player cannot play ChampDS VOD2 streams. The stream only answers when the request carries `Referer: https://play.champds.com/` (`app/platforms/champds.py`). So we tested whether ChampDS's own event page can be shown in an iframe on our site, and whether it can start at a chosen time.

Events used: Cobb County GA event 155 (VOD2-only, 1 h 43 min), Largo FL event 342 (2 h 18 min), Atlanta GA event 1227. All requests were one at a time, 3 seconds apart. I used installed Google Chrome, headless. Playwright's own Chromium cannot play H.264.

## Result 1: framing is allowed

| Event page | `X-Frame-Options` | CSP `frame-ancestors` | Frame-busting script |
|---|---|---|---|
| `play.champds.com/cobbcoga/event/155` | none | none (no CSP header) | none found |
| `play.champds.com/atlantaga/event/1227` | none | none | none found |
| `play.champds.com/largofl/event/342` | none | none | none found |

## Result 2: it plays inside an iframe

A local page (`http://127.0.0.1`) held an `<iframe src="https://play.champds.com/...">`. I clicked the player's play button inside the frame and waited 20 seconds.

| Case | Plays? | Position after 20 s | Stream requests |
|---|---|---|---|
| Cobb 155, iframe | Yes | 19 s | 14, all 200; segments sent `Referer: https://play.champds.com/` |
| Cobb 155 `/s/600`, iframe | Yes | 619 s | 17, all 200 |
| Largo 342 `/s/120`, iframe | Yes | 138 s | 18, all 200 |
| Cobb 155 `/s/600`, page opened directly (control) | Yes | 619 s | 17, all 200 |

Inside the iframe, the stream requests come from ChampDS's own page. So they carry ChampDS's Referer, and the VOD2 check passes. This is why the iframe works where our own player cannot.

## Result 3: a start time works

The event page takes a start time in its path: **`/{customer}/event/{id}/s/{seconds}`**. The server writes it into the page (`var SC_AREA = 's'; var SC_ID = 600;`). The player's `embed.js` then seeks there (`SEEK_TO_SECS`) once the video loads. Tested: `/s/600` started at 600 s, and `/s/120` at 120 s. A query string (`?s=600`) does not do this. `s` in the query is the transcript search box.

## Caution

- The video starts only after a click on the play button. Forcing `play()` from script makes their player fail (`ReferenceError: mediaSrc is not defined`). The reader must press play inside the frame. The start time still applies.
- There is no message API from the parent page. Once the frame is loaded, our page cannot seek it or read its time. A new deep link means reloading the iframe with a new `/s/{seconds}`. So our transcript cannot follow the video's playback position.
- The frame shows ChampDS's whole event page (agenda, search), not a bare player.
- This was tested from this Mac only, on 2 tenants for playback and 3 for headers.

## Recommendation

**Embedding works: yes. A start time works: yes**, through `/event/{id}/s/{seconds}`. For VOD2-only ChampDS meetings, the meeting page could show ChampDS's own page in an iframe in place of the "stream-only" warning, and make transcript deep links reload it at `/s/{seconds}`. The live transcript highlight would not follow the video.
