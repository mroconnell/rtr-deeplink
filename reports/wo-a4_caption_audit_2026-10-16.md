# A4. Caption alignment audit, 100 random pages (2026-10-16/17)

## What was tested and why

The WO-1960 backlog entry found a few pages whose stored captions do not line up with the video, so deep links land at the wrong moment. It was not known how common this is. So I checked 100 random Archive pages whose transcript is a **source caption track** (not our Whisper). YouTube pages were excluded.

**Method.** For each page I took a 4-minute stretch of audio at three points: early (10% into the captions), middle (50%) and late (85%). I transcribed each stretch with a local Whisper model (`small`) and matched its words to the stored captions with `match_window()` from `scripts/align_captions_to_audio.py`. Like `align_windows()`, the search tries offsets out to ±1,000 s. If nothing matches, it then tries every 60 s out to ±30 minutes. The **offset** is caption time minus audio time, the median over the matched words. A **deep link** lands within 5 s when the offset at that point is 5 s or less.

**Sample.** I drew pages at random (seed 1016) from the sitemap's 12,777 `/m/` pages, with at most 20 per platform. To reach 100, I passed over 168 pages with our own transcription, 148 YouTube pages, 11 with no transcript, 1 with no video, and 6 over a platform's cap. I only read the Archive's public pages (`/m/{slug}` and `/m/{slug}/transcript.srt`), and I made no writes. Audio came from each city's own media host, one request at a time, with the source page's Referer.

**Sanity check first, on the known bad pages:**

| Page | Known | This method |
|---|---|---|
| Coral Gables FL 2023-06-01 | 32.6 s off, then 4.3 s after a step | −31.2 s, −31.4 s, then −2.5 s late: a step |
| Venice FL 2026-08-25 | aligned to the middle, breaks in the last third | +5.5 s, +5.7 s, then no match late |
| Dunnellon FL 2026-07-15 | 0% agreement at three points | no match at any point, even with the ±30-minute scan |

## Result

| Result | Count of 100 |
|---|---|
| Aligned (all checked points within 5 s) | 60 |
| Constant offset, 5 to 10 s (normal live-caption lag) | 12 |
| Constant offset, over 10 s | 2 |
| Drift or step, reaching over 10 s | 9 |
| Drift or step, staying under 10 s | 2 |
| Captions never match the audio | 2 |
| Could not check | 13 |

Of the 87 pages that could be checked, **13 (15%) have at least one point where a deep link is more than 10 s off, or no match at all.** Over all 245 measured points, a deep link landed within 5 s at 191 (78%).

**The 13 pages that are clearly wrong somewhere:**

| Page | Platform | Early | Middle | Late |
|---|---|---|---|---|
| county-of-orange-board-meeting | Granicus | +867.6 s | +5.0 s | +4.9 s |
| lighthouse-point-fl-city-commission-meeting-partial | Granicus | +656.7 s | +403.7 s | +141.2 s |
| city-of-port-moody-bc-2026-07-28-regular-council | eScribe | +244.3 s | +244.2 s | +244.2 s |
| mississauga-2022-07-07-regional-council | eScribe | +207.8 s | +207.6 s | +207.5 s |
| san-antonio-tx-2026-08-26 city council budget | Swagit | −174.4 s | −106.6 s | −191.1 s |
| southfield-city-mi-2026-08-25-council-meeting | Cablecast | −121.2 s | −119.3 s | −12.3 s |
| cabarrus-county-schools-nc-2026-05-11-boe-business-meeting | Cablecast | −30.0 s | −103.7 s | −100.1 s |
| cambridge-school-district-ma-2026-06-18 school climate | Cablecast | −21.8 s | −40.7 s | −74.8 s |
| redlands-ca-2026-07-22-redlands-city-council-meeting | Cablecast | −47.9 s | −20.8 s | −25.4 s |
| palmer-town-ma-2026-09-14 town council | Cablecast | −11.4 s | −4.6 s | −12.4 s |
| beaconsfield-qc-2025-08-25 conseil municipal | webtv.coop | −2.6 s | no match | +29.6 s |
| dunnellon-fl-2026-07-15-city-council | Granicus | no match | no match | no match |
| lauderdale-by-the-sea-fl-2023-06-27-town-commission | Granicus | no match | no match | no match |

**By platform**, among pages that could be checked:

| Platform | Checked | Aligned | Over 10 s off somewhere, or never matching |
|---|---|---|---|
| Granicus | 19 | 10 | 4 |
| Swagit | 13 | 12 | 1 |
| TelVue | 11 | 11 | 0 |
| Cablecast | 9 | 1 | 5 |
| eScribe | 6 | 4 | 2 |
| webtv.coop | 5 | 2 | 1 |
| CivicClerk | 4 | 2 | 0 |
| ChampDS | 3 | 2 | 0 |
| Other (archive.org, direct files and others) | 17 | 16 | 0 |

**Could not check (13):**
- 6 Vimeo pages: the video is a player, not a file.
- 5 with too few caption cues: two Cablecast, two Swagit, one PrimeGov.
- 1 Granicus: the stored video answers 404, so that page's video is gone.
- 1 BoxCast: its player address is the Archive's own `/m/{slug}/video` redirect, which my script did not pass correctly to ffmpeg. This is my script's fault, not the page's.

## Caution

- Three points per page is a sample. A page called aligned can still have a step between the points, as Venice shows.
- Whisper was run in English. The webtv.coop pages are Quebec council meetings partly in French, so their "no match" points may come from the language, not from a bad offset. Treat those 5 as unsure.
- A 5 to 7 s constant lag is normal for live captions. Those 12 pages are not broken, but a deep link starts a few seconds late.
- Cablecast stands out: 5 of 9 checked are badly off, in both directions, and some drift within one meeting.

## Recommendation

The problem is real and not rare: about 1 in 7 checkable sourced pages has deep links more than 10 s off somewhere. A per-page offset map is worth building, as the WO-1960 entry proposed. Start with Cablecast, and with the large constant offsets on eScribe (a single fixed shift fixes Port Moody and Mississauga). Pages whose captions never match (Dunnellon, Lauderdale-by-the-Sea) should be flagged, or their transcript replaced with our own.

Data: `wo-a4_caption_audit_2026-10-16.csv` (one row per page: platform, media host, caption span, offset and agreement at each point, whether a deep link lands within 5 s, result, note). This report changes nothing in the repo; the BACKLOG entry still needs these numbers.
