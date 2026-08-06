# rtr-deeplink

A deliberately lean rebuild of the video+transcript+deep-link feature from
`rtr-transcripts` (the round-1 "Red Tape Recordings" MVP). No database, no
auth, no background job queue — the whole app is stateless: given a meeting
URL, resolve its video and transcript on demand and render them together.

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
  Sheet (see auto-memory: `reference-sample-meetings-sheet`) that the user
  adds to over time.
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
  so far: Legistar and CivicPlus both just link out to Granicus), delegate
  via `resolve_via_platform()` in `base.py` rather than writing a
  redundant native parser.

## Related context

Full background — the MVP pivot decision, why this project exists at all,
the dozen-city test findings against `rtr-transcripts`, and per-platform
research notes — lives in this project's Claude Code memory (auto-loaded
from the `rtr-transcript` working directory's memory index), not
duplicated here or in README.md.
