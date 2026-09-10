# YouTube caption-fetch 429 / sustained IP block

**Status: open.** First case using this repo's `docs/investigations/`
pattern (2026-08-31) — a living investigation that keeps accumulating
findings across sessions without being close to "done," so it doesn't fit
`BACKLOG_DONE.md`'s done/dated-investigation model either. The live
`BACKLOG.md` entry stays short and links here; this file is where new
findings get added as new dated sections, oldest first.

**Scope note (2026-09-09, WO-136):** this file was originally scoped to
the caption-fetch endpoint specifically. A second, related-but-distinct
symptom on the *audio download* path (yt-dlp's own "Sign in to confirm
you're not a bot" check, not an HTTP 429) is now tracked here too — see
that section below — since both are the same underlying YouTube
anti-bot system reacting to sustained request volume from one IP, just
tripped by different request shapes.

**Why it matters**: `/coverage`'s live jurisdiction data puts **184** real
jurisdictions on `platform="YouTube"` (confirmed 2026-08-26) — not just
the four curated `youtube_channel.py` cities, but every jurisdiction whose
*final* resolved video comes through `YouTubeAssetFinder`, including
everything delegated there from CivicWeb, PrimeGov, ClerkBase, and
Minneapolis LIMS. Captions for all 184 go through the same yt-dlp call
this block hits, so a sustained block is a real single point of failure
behind roughly a tenth of this app's jurisdiction coverage.

## 2026-08-22: original finding

A corpus-scale `dedupe_rollup_transcripts.py --apply` failed 10/10
YouTube resolves with `HTTP 429`, zero failures on any other platform. A
retry at `--resolve-delay 60`, starting after ~9 minutes of no YouTube
traffic at all, failed identically on all 10, with the *first* request of
that run 429ing cold — ruling out "too fast, pace it" as the whole story.
The burst appears to earn a sustained IP-level block that outlives at
least ten minutes of idling; duration was (and still is) unmeasured.

Two real, separate bugs were found and fixed alongside this same
incident — both closed, see `BACKLOG_DONE.md`:

- `dedupe_rollup_transcripts.py`'s circuit breaker couldn't actually trip
  on an in-band resolve failure (only checked inside an `except` branch a
  429 never reached) — fixed 2026-08-22, PR #318.
- A YouTube caption-fetch 429 crashed `resolve()` outright instead of
  degrading gracefully (`HTTPError` wasn't caught by the existing
  anti-bot `except` clause) — fixed 2026-08-29, widened to the shared
  `YoutubeDLError` base.

Both of those are done. This file is about the harder half neither fix
touches: **does the underlying IP block ever clear, and is there a way to
pace around it at all?**

## 2026-08-29: re-tested, still unresolved

Seven days later, a single, isolated, cold `resolve()` call (no burst at
all) against two different real videos both hit the identical 429 on the
caption-fetch step. That does *not* confirm pacing is hopeless — a lone
request 429ing is a different, more concerning shape than "burst earns a
block" — but there was no way to get a clean, unblocked baseline to test
against from this environment (a residential IP), so the real questions
stayed open:

- Does the block ever clear, and if so, after how long?
- Is it IP-specific, or something broader (account/fingerprint-level)?
- Does Render's own outbound IP behave differently from the residential
  IP every test so far has used?

**Do not re-run a bulk YouTube sweep to test this.** A single isolated
check is enough to know whether the situation has meaningfully changed;
running more only risks extending whatever is causing it.

## 2026-08-30: one clearance data point

A re-probe of the same 10 slugs that failed 10/10 in the original
2026-08-22 finding resolved cleanly — zero 429s, 8 days after the
original block. This doesn't settle pacing, IP-specificity, or a
Render-vs-residential difference, and it doesn't reconcile with the
2026-08-29 re-test above (a lone cold request still 429ing, one day
earlier) — but it does show the block isn't permanent. Read together, the
two data points suggest the block's duration/scope is inconsistent
rather than a simple fixed-length cooldown, which is itself useful
signal: whatever is happening probably isn't as simple as "wait N days."

## Next step

Someone testing from Render's own outbound IP (not a residential one) is
the most likely way to separate "this IP is blocked" from "YouTube caption
fetching is blocked more broadly" — no session so far has had that vantage
point. A single isolated `resolve()` call against one real YouTube-backed
meeting, run from Render's shell, would be enough; still not a bulk sweep.

## 2026-09-09: the *audio download* path hits the same anti-bot system too, after only 3 real downloads

WO-136 added `scripts/transcribe_backlog_locally.py --urls-file`
support for downloading a YouTube video's audio via yt-dlp when the
video has no fetchable captions. Before the bulk run, a single isolated
download (a real ~100MB/79-minute file) and a metadata-only check both
worked cleanly on the same day this Mac's caption-fetch calls were
independently 429-blocked (see the 63-identity-checked-pages `[WAIT]`
entry in `BACKLOG.md`) — real evidence the two request shapes have at
least *some* independent budget, which the code comment in
`_yt_dlp_download_best_audio()` reads as "the two are expected to have
independent availability."

**That held for exactly 3 real downloads, not indefinitely.** A real,
unattended `--urls-file` run against 17 candidates succeeded on meetings
1-3 (952, 3, and 2,631 real segments, all live on production) — total
wall time ~44 minutes, meeting 3 alone a ~4-hour recording (16 real
chunks). Every one of the remaining 14 meetings then failed on its very
first yt-dlp call with `ERROR: [youtube] <id>: Sign in to confirm you're
not a bot.` — the same anti-bot check `app/platforms/youtube.py`'s own
module docstring already documents hitting Render's server IP
(2026-08-09), now hit from a residential Mac after real, moderate
audio-download volume rather than a burst of caption requests. This is
a **different mechanism from the 429 above** (no HTTP 429 in the error
text, a distinct yt-dlp-reported message, and it followed real
successful downloads rather than failing cold), but it's the same
practical shape: this IP's relationship with YouTube degrades under
sustained use and nothing here has measured what "sustained" means or
how long recovery takes for *this* symptom specifically.

**Open questions, unmeasured**: does this clear on its own (like the
caption 429 did, 8 days later, in the original finding above), and if
so how fast — a short cooldown between meetings would make a real
difference to `--chunk-cooldown-seconds`-style pacing if the block is
per-download-burst rather than a long-lived ban. Whether a smaller
`--cpu-threads`/slower pace changes anything (unlikely, since the block
is presumably about request pattern, not local CPU load, but unconfirmed).
Whether it's tied to the *volume of bytes* downloaded (3 real files,
combined several hundred MB to ~1GB+) or simply *elapsed wall time*
active against YouTube (~44 minutes).

**Do not re-run a bulk `--urls-file` sweep to test this** — same
standing rule as the caption-fetch block above; a single isolated
`--url` retry against one of the 14 skipped meetings, after some idle
time, is the right next probe, not another full batch.
