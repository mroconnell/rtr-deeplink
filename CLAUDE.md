# rtr-deeplink

A deliberately lean rebuild of the video+transcript+deep-link feature from
`rtr-transcripts` (the round-1 "Red Tape Recordings" MVP). No accounts, no
auth, no background job queue — given a meeting URL, resolve its video and
transcript on demand and render them together. There's now an optional
database (`app/db/`) for caching resolves and admin reporting, added
deliberately narrow in scope to avoid reintroducing round 1's auth/Mongo/
NextAuth complexity — it holds no user-facing state, and the app still works
with zero persistence if it's unset or unreachable. See README's
"Caching and reporting" section for how it works.

**See `README.md` for architecture, the resolve flow, supported platforms,
and frontend features.** This file covers conventions and context specific
to working on this codebase; don't duplicate README content here.

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

## Working conventions established in this repo

- **Never build a platform adapter from assumption — always test against a
  real, live URL first**, ideally several from different cities on that
  platform. Every adapter in `app/platforms/` was built by first fetching
  a real page/API response, reading the actual structure, and only then
  writing the parser. Sample URLs across platforms live in a shared Google
  Sheet the user maintains and adds to over time: "Watchdog Sample meetings
  - Red Tape Recordings - public hearings" —
  https://docs.google.com/spreadsheets/d/1WJvohdOhdUzP0C-0CUfj_pMSjPwYTtMQU3IOeppp54s/edit
  Check it for a real sample before building or debugging any adapter.
- **Verify in-browser, not just via the API.** UI changes especially need
  an actual `mcp__Claude_Browser__*` check — several real bugs (duplicate
  chapter markers, a metadata-extraction ordering bug, a deep-link
  seek-priority bug) were only caught by looking at the rendered page or
  driving it, not by reading JSON responses.
- **New bugs/gaps found while working go in `BACKLOG.md`**, not just
  mentioned in conversation — it's the durable record. `BACKLOG.md` holds
  only live/open items, kept short on purpose; once an item is actually
  fixed/built and verified, move its entry (marked `[Done YYYY-MM-DD]`,
  full reasoning and verification detail intact) into `BACKLOG_DONE.md`
  rather than marking it done in place — that keeps `BACKLOG.md` fast to
  read while still preserving the investigation history. If a completed
  item left behind a real residual gap (a follow-up not yet built, an
  edge case still unfixed), split that part back out as its own live
  entry in `BACKLOG.md`, cross-linking to `BACKLOG_DONE.md` for context.
- **`CLAUDE_BACKLOG.md` is a separate, unreviewed suggestions list**,
  distinct from `BACKLOG.md`. When asked to brainstorm improvements/
  features rather than record a bug or gap found while working, write them
  there instead of directly into `BACKLOG.md` — it holds ideas the user
  hasn't triaged yet, so they don't get mixed in with `BACKLOG.md`'s
  verified, live-tested findings. Once the user accepts an item from it,
  move it into `BACKLOG.md` proper (in that file's style, with real
  verification) rather than marking it done in place.
- **Don't claim a caption/data path works without a positive example.**
  Several adapters have fields that are schema-verified but not
  content-verified (e.g. CivicClerk's `closedCaptionTracks`, Swagit's
  `#transcript-fragments`) because no real meeting with that data
  populated has been found yet — these are explicitly flagged as
  best-effort in code comments and BACKLOG.md, not silently assumed.
- **When a platform turns out to be a wrapper around another** (confirmed
  so far: Legistar and CivicPlus both just link out to Granicus, and
  PrimeGov embeds a YouTube video), delegate rather than writing a
  redundant native parser — usually via `resolve_via_platform()` in
  `base.py`, though PrimeGov calls `YouTubeAssetFinder.resolve_video_id()`
  directly instead so it can pass the *original* PrimeGov URL through as
  `source_url` (Legistar/CivicPlus's delegation ends up with the
  delegated platform's URL as `source_url`, a known quirk — see
  BACKLOG.md).
- **yt-dlp is a different kind of dependency than everything else here**
  — every other adapter reads a stable public API or a page structure
  that isn't actively trying to block scraping; YouTube caption fetching
  specifically is (plain HTTP requests to its caption endpoints return
  200 OK with 0 bytes — confirmed live, see BACKLOG.md), and yt-dlp only
  works around that because it's under continuous maintenance chasing
  YouTube's changes. Left unpinned in `requirements.txt` on purpose. If
  YouTube/PrimeGov resolves start failing, check for a yt-dlp update
  before assuming it's a bug in this repo's code.
- **A pytest suite exists now (`tests/`, see README's "Running tests")** —
  run it (`pytest`) before/after touching `app/utils/vtt_parser.py`,
  `app/platforms/media_scan.py`, `app/platforms/base.py`, or the
  Granicus/Legistar/CivicPlus/CivicClerk adapters, since those are the
  ones with real coverage today. It doesn't replace live-testing a new
  adapter or a genuinely new real-world case (see the first bullet above)
  — it exists to catch a *previously-covered* case silently regressing
  between sessions, which live-testing alone doesn't protect against.
  When you fix a bug found via live testing, consider adding a fixture-
  backed regression test for it in the same pass, the way the Simi Valley
  Spanish-caption and blank-VTT cases already are.
- **`app/db/outcomes.py` classifies reporting outcomes from real signal on
  the row where one exists, and falls back to substring-matching
  `transcript_warnings` only where it doesn't.** `agenda_fallback` is
  decided from `resolved_payload["agenda_items"]` directly (a real field
  on `ResolvedMeeting`, separate from `segments` — see the "Supported
  platforms" table in README.md), not warning text. `garbled_transcript`
  still matches `_GARBLED_MARKER` against `transcript_warnings`, since
  garbled-ness isn't (yet) a first-class field. If you change or add a
  quality warning message in an adapter, keep `_GARBLED_MARKER`'s
  substring intact (or update `outcomes.py` to match) — otherwise that
  warning silently stops being classified correctly and falls through to
  a more generic bucket.

## Related context

The essentials (why this pivot happened, per-platform findings, known
gaps) are captured directly in this repo — `README.md`, this file, code
comments, and `BACKLOG.md` (plus `BACKLOG_DONE.md` for completed items and
`CLAUDE_BACKLOG.md` for unreviewed, Claude-proposed ideas) — deliberately,
so a session opened straight against this repo has what it needs without
depending on anything else.

Deeper session narrative (the original round-1 user-testing conversation,
day-by-day investigation detail) lives in Claude Code auto-memory scoped
to `~/Documents/rtr-transcript` — the *original* project directory this
one was spun out of, not this one. A Claude Code session opened at
`~/Documents/rtr-deeplink` (e.g. from VS Code) will *not* auto-load that
memory, since memory is scoped per working directory. It's rarely needed
day to day; if something here references a decision that isn't explained
in-repo, that's where to look, or just ask the user.
