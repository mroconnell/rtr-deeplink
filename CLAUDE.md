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
  mentioned in conversation — it's the durable record. Mark items
  `[Done YYYY-MM-DD]` in place rather than deleting them, so the reasoning
  and verification history stays visible.
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
- **`app/db/outcomes.py` classifies reporting outcomes by matching specific
  substrings in `transcript_warnings`** (e.g. `_AGENDA_FALLBACK_MARKER`,
  `_GARBLED_MARKER`) rather than a stored enum/boolean, to avoid touching
  every adapter's model for reporting alone. If you change or add a
  fallback/quality warning message in an adapter, keep the shared marker
  substring intact (or update `outcomes.py` to match) — otherwise that
  warning silently stops being classified correctly and falls through to
  a more generic bucket.

## Related context

The essentials (why this pivot happened, per-platform findings, known
gaps) are captured directly in this repo — `README.md`, this file, code
comments, and `BACKLOG.md` — deliberately, so a session opened straight
against this repo has what it needs without depending on anything else.

Deeper session narrative (the original round-1 user-testing conversation,
day-by-day investigation detail) lives in Claude Code auto-memory scoped
to `~/Documents/rtr-transcript` — the *original* project directory this
one was spun out of, not this one. A Claude Code session opened at
`~/Documents/rtr-deeplink` (e.g. from VS Code) will *not* auto-load that
memory, since memory is scoped per working directory. It's rarely needed
day to day; if something here references a decision that isn't explained
in-repo, that's where to look, or just ask the user.
