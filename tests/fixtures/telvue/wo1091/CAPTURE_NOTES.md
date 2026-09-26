# TelVue fixtures for WO-1091: capture notes

Copied unchanged (byte for byte) on 2026-09-26 from rtr-discovery's
`tests/fixtures/telvue/` (commit `3324188`, 2026-09-25). No new requests
were made for WO-1091. Full notes for every file are in that repo's own
`tests/fixtures/telvue/CAPTURE_NOTES.md`; the lines for these files are
repeated here.

All are real responses from `videoplayer.telvue.com`, captured on
2026-09-25 with one plain GET each, the User-Agent
`rtr-discovery/0.1 (Red Tape Recordings meeting-discovery; +https://redtaperecordings.com/about)`,
at least 2.5 seconds apart. None is trimmed. Times are UTC.

Listing pages were fetched with `urllib`. Media pages were fetched inside
rtr-deeplink's own `TelvueAssetFinder.resolve()` (origin/main `a393043`)
with the same User-Agent forced.

| Customer | Org token |
| --- | --- |
| Kalamazoo, MI station | `2bm0gzQWeVRzdCgvjXziXKwO3icSKh05` |
| Derry, NH | `CXN6V2zmqTebSQfLjvlDzEql3BwiQh_l` |
| Queen Anne's County, MD (QACTV) | `AbfNhigIqnG-4roGCxaFupXEKfme9dfT` |
| Pierre, SD (OaheTV) | `5nQYx7H7WpbP8AVWnkzXsWu69pAXI7Yq` |

| File | Request | Captured (UTC) | HTTP |
| --- | --- | --- | --- |
| `kalamazoo_videos.html` | `GET https://videoplayer.telvue.com/player/2bm0gzQWeVRzdCgvjXziXKwO3icSKh05/videos` | 2026-09-25T19:55:19+00:00 | 200 |
| `derry_videos.html` | `GET https://videoplayer.telvue.com/player/CXN6V2zmqTebSQfLjvlDzEql3BwiQh_l/videos` | 2026-09-25T19:56:40+00:00 | 200 |
| `queenannes_videos.html` | `GET https://videoplayer.telvue.com/player/AbfNhigIqnG-4roGCxaFupXEKfme9dfT/videos` | 2026-09-25T19:56:55+00:00 | 200 |
| `pierre_videos.html` | `GET https://videoplayer.telvue.com/player/5nQYx7H7WpbP8AVWnkzXsWu69pAXI7Yq/videos` | 2026-09-25T19:57:10+00:00 | 200 |
| `derry_media_1047520_page.html` | `GET https://videoplayer.telvue.com/player/CXN6V2zmqTebSQfLjvlDzEql3BwiQh_l/media/1047520` | 2026-09-25T19:58:29+00:00 | 200 |
| `derry_media_1046119_page.html` | `GET https://videoplayer.telvue.com/player/CXN6V2zmqTebSQfLjvlDzEql3BwiQh_l/media/1046119` | 2026-09-25T19:58:37+00:00 | 200 |
| `kalamazoo_media_1045901_page.html` | `GET https://videoplayer.telvue.com/player/2bm0gzQWeVRzdCgvjXziXKwO3icSKh05/media/1045901` | 2026-09-25T19:59:24+00:00 | 200 |
| `queenannes_media_1047511_page.html` | `GET https://videoplayer.telvue.com/player/AbfNhigIqnG-4roGCxaFupXEKfme9dfT/media/1047511` | 2026-09-25T19:59:33+00:00 | 200 |
| `queenannes_media_1047333_page.html` | `GET https://videoplayer.telvue.com/player/AbfNhigIqnG-4roGCxaFupXEKfme9dfT/media/1047333` | 2026-09-25T19:59:38+00:00 | 200 |
| `pierre_media_1047373_page.html` | `GET https://videoplayer.telvue.com/player/5nQYx7H7WpbP8AVWnkzXsWu69pAXI7Yq/media/1047373` | 2026-09-25T19:59:44+00:00 | 200 |
| `pierre_media_1045603_page.html` | `GET https://videoplayer.telvue.com/player/5nQYx7H7WpbP8AVWnkzXsWu69pAXI7Yq/media/1045603` | 2026-09-25T19:59:47+00:00 | 200 |
| `kalamazoo_media_1047784_page.html` | `GET https://videoplayer.telvue.com/player/2bm0gzQWeVRzdCgvjXziXKwO3icSKh05/media/1047784` | 2026-09-25T20:00:00+00:00 | 200 |
| `pierre_playlist_11342_items_offset0.html` | `GET https://videoplayer.telvue.com/player/5nQYx7H7WpbP8AVWnkzXsWu69pAXI7Yq/playlists/11342/playlist_items?offset=0` | 2026-09-25T20:01:23+00:00 | 200 |

The caption and chapter files these media pages point to were not
copied. The tests answer those requests with a 404, which the adapter
already handles; nothing in WO-1091 reads them.

One correction to rtr-discovery's note, which says "No date field was
found on any media page": there is no date *field*, but Pierre's media
page 1047373 carries the meeting date as text in its `og:description`
("9-22-2026"). WO-1091 reads it.
