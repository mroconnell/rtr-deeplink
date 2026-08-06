# rtr-deeplink

A deliberately lean rebuild of the video+transcript+deep-link feature from
`rtr-transcripts` (the round-1 "Red Tape Recordings" MVP). No database, no
auth, no background job queue — the whole app is stateless: given a meeting
URL, resolve its video and transcript on demand and render them together.

## Why this exists

Round 1 (`rtr-transcripts`, private repo at github.com/mroconnell/rtr-transcripts,
also cloned locally at `~/Documents/rtr-transcripts`) built a much bigger
product: FastAPI + MongoDB + Beanie, Google OAuth/JWT, a WebSocket-driven
background job queue for Whisper transcription, full search/archive. User
testing showed people wanted two specific things out of all of that: (1) an
approximate transcript for multi-hour meetings, and (2) the ability to
deep-link to a specific timestamp. That feature was already shipped inside
`rtr-transcripts` (see its `docs/video_embed_deeplink_*.md`), just buried
under everything else. This repo extracts and fixes just that part.

## Architecture

- `app/platforms/base.py` — `detect_platform(url)` classifies a meeting URL
  by hosting platform (Granicus, Legistar, CivicClerk, CivicPlus, PrimeGov),
  and dispatches to a registered `AssetFinder` for that platform. One adapter
  per **platform**, not per city — validated empirically: the Granicus
  adapter worked structurally across 11 of 12 very different Granicus-hosted
  cities (San Diego, Oakland, Berkeley, Alexandria VA, Boston, SF, etc.) in
  testing against `rtr-transcripts`. This also mirrors the dispatch pattern
  used by the `civic-scraper` OSS tool, which solves an adjacent problem
  (agenda/minutes discovery, not video/transcript resolution).
- `app/platforms/granicus.py` — the only implemented adapter so far. Ported
  from `rtr-transcripts/app/services/granicus.py` with two bugs fixed found
  during cross-city testing: (1) relative media URLs (e.g.
  `/videos/5361/captions.vtt`) are now resolved with `urljoin()` instead of
  being left relative and failing to fetch; (2) parsed caption text is
  returned directly in the API response instead of only being persisted to
  a database that this app doesn't have.
- `app/utils/vtt_parser.py` — pure WebVTT parser, ported unchanged (it
  already worked correctly).
- No Legistar/CivicClerk/CivicPlus/PrimeGov adapter exists yet. Hitting one
  of those URLs returns a clean "unsupported platform" response instead of
  crashing (unlike `rtr-transcripts`, which crashes with a low-level error
  when handed a non-Granicus URL — see `UnsupportedPlatformError`).
- No persistence: `/meeting?url=<source>` re-resolves on every load. Deep
  links encode `?t=<seconds>` or `?line=seg-<n>` and are entirely
  self-contained — no database record required to reproduce them.

## Known gaps carried over from rtr-transcripts testing (not yet fixed here)

- Metadata extraction (title/date/jurisdiction) is regex/selector-based
  against static HTML and is unreliable for JS-heavy Granicus clip pages.
  `civic-scraper`'s Granicus adapter gets cleaner metadata from an RSS feed
  (`ViewPublisherRSS.php`) instead of scraping the clip page — worth
  revisiting if metadata quality becomes a blocker.
- Only the first successful caption track is used per meeting; multiple
  caption tracks aren't merged.

## Related context

Full background — the MVP pivot decision, sample test URLs, and the
dozen-city test findings against `rtr-transcripts` — lives in this
project's Claude Code memory (auto-loaded from the `rtr-transcript` working
directory's memory index), not duplicated here.
