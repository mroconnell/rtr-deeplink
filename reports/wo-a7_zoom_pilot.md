# A7. Zoom recording pilot (5 links), 2026-10-16

## What was tested and why

The tier-3 probe CSV has 17 distinct Zoom recording links (the brief said 21; the CSV has 17 distinct ones, 16 of them marked `reject-dead`, "resolve returned no video_url"). We wanted to know if an adapter for them is worth building.

I opened 8 links in a headless Chromium (the same setup as the repo's `fetch_headless_sync`, YouTube blocked), one at a time, 3 seconds apart. I picked 5 from different governments for the table. For one link I also tested whether the video file can be fetched outside the browser. This was a one-time check of person-approved links. No crawl was built.

## Result

| Link | Meeting (page title) | Plays without sign-in? | Direct video file? | Passcode? | Zoom transcript or captions? | Recording date |
|---|---|---|---|---|---|---|
| `us06web.zoom.us/rec/share/CgvcJ...` (Sidney MT, in the tier-3 queue) | Impact Fee Committee 9/30/26 | Yes | Yes, `ssrweb.zoom.us/.../GMT20260930-175510_Recording_640x360.mp4` (34:35) | No | No transcript track loaded | 2026-09-30 |
| `us02web.zoom.us/rec/share/5zr1g...` | Androscoggin County Budget Meeting | Yes | Yes, 1280x720 MP4 (1:55:45) | No | No | 2026-09-23 |
| `us02web.zoom.us/rec/share/dctR-...` | Board of Health Meetings Jul 1 26 (the transcript names "Cascade Academy") | Yes | Yes, 1920x1080 MP4 (50:20) | No | Yes, an audio transcript (`/rec/play/vtt?type=transcript`) | 2026-07-01 |
| `us02web.zoom.us/rec/share/43hKL...` | Town of Mont Vernon's Zoom Meeting | Yes | Yes, 1280x720 MP4 (1:44:01) | No | Yes, captions (`/rec/play/vtt?type=cc`) | 2026-03-30 |
| `bristolct-gov.zoom.us/rec/play/8LsPI...` (Bristol CT) | (blank page) | No: the page returns an empty body, even after 15 s | No | Not shown | No | Unknown |

The other 3 links I opened (Board of Finance, 2026-04-15; BOS Meeting September 8, 2026; Planning Board, 2026-08-26) also played, each with an MP4 and no passcode. Their government is not named on the page.

So 7 of the 8 links play. The probe's "reject-dead" verdict was wrong for those 7. It came from a plain request, which gets no video.

## How the files can be read

- The MP4 address is on `ssrweb.zoom.us` and is signed. A plain request gets **403**, even with a `Referer`. The same request made with the browser's own cookies gets **206** (the video bytes).
- So the video can only be read through a headless browser session, the same pattern as our Vimeo captions.
- The transcript and caption VTT files work with a plain request (200, real text), once the page has given their address.
- The cookies include Cloudflare's `cf_clearance`. No "verify you are human" page was shown from this Mac. Like Vimeo, Render may be treated differently. That is not tested.
- `/rec/play/...` links (Bristol) look like short-lived play links. `/rec/share/...` links worked.

## Caution

- Zoom's robots.txt disallows `/rec/*`. This was a one-time check. An adapter should only open links a government published, never discover new ones.
- The page title is the host's meeting name. It often does not name the government (3 of 8), so the government must come from the page that linked to the recording.
- Captions were present on only 2 of the 8.

## Recommendation

**An adapter is feasible: yes**, for `/rec/share/` links, run from a Mac (like the Vimeo lane). It would open the page headlessly, read the MP4 address and duration, fetch the MP4 with the browser's cookies for our own transcription, and use Zoom's VTT when there is one (tier 2). Test from Render before relying on it there.
