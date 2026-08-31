# Agenda text as a first-class, versioned asset — sequencing brief

Written 2026-08-31, alongside the small version (PR #640 — see
`BACKLOG_DONE.md`). This is discussion material, not a plan: a proposal to
bring to Ryan, not a decision already made. The underlying ask is
BACKLOG.md's "Roadmap & strategy" entry of the same name — read that first
for the full trap list; this file is about *order*, not *what*.

## What the small version already did, and didn't do

PR #640 gave CivicPlus and CivicClerk a real `agenda_link`/`packet_link` at
resolve time, using data those adapters already fetched. No new network
call, no storage of the document itself, no versioning. That's the entire
scope Ryan asked for today ("no nightly sweeps... okay with just replacing
agendas... maybe a link to the packet"). It closes zero of the three
linked pieces the Roadmap entry actually describes:

1. A versioned child table (agendas get amended; transcripts don't)
2. Fetch-and-extract text across ~23 adapters
3. Display (versions, diff) and search-corpus inclusion

## Why sequencing is the real question, not scope

`rtr-upcoming` (sister repo, cloned locally, `UPCOMING_AGENDAS_FIELD_GUIDE.md`
read in full) is a working reference implementation of piece 2 and part of
piece 1, built for a different job (finding agendas with no video URL at
all, across all 108 Bay Area jurisdictions). Its existence changes the
calculus here: this isn't "design from scratch," it's "port a solution
that already survived contact with real jurisdictions," including several
traps that cost a day each when first hit there (full list in the Roadmap
entry — truncated-response corruption, packet-over-agenda preference,
wrong-rendition-in-cell, lying content-types, zero-byte "not published
yet," URL-based version detection producing false amendments, scanned
PDFs, ligature/space-loss mangling, and re-extraction misread as an
amendment).

## Proposal: model first, extraction second, adapters incrementally

**Step 1 — the data model and migration**, mirroring `TranscriptVersion`'s
shape (content-hash dedupe, a `kind` column: `initial`/`amendment`/
`reissued`/`alternate`, matching `rtr-upcoming`'s `agenda_versions` table).
Build this even before any adapter writes to it. Rationale: it's the one
piece every later step depends on, it's schema-only risk (an Alembic
migration, no adapter behavior change), and it lets extraction work
(step 2) be developed and tested against the real table shape rather than
against a stub.

**Step 2 — one extraction path, reused everywhere**: `app/agenda_text.py`
and `app/agenda_diff.py` from `rtr-upcoming` are close to directly
portable (format dispatch for PDF/HTML/RTF/TXT/DOCX; block-based diffing,
not line-based — `rtr-upcoming` measured line-diff reporting 64% of an
*unchanged* document as changed). Build and test this against 2-3 real
documents from platforms already in hand (CivicPlus's Durham fixture,
CivicClerk's Clovis/Emporia fixtures — the same ones PR #640 already
confirmed have real agenda/packet URLs) before touching a fourth adapter.

**Step 3 — roll out per-adapter, cheapest/highest-value first**, not all
~23 at once. CivicPlus and CivicClerk already have real `agenda_link`/
`packet_link` from step 0 (this small version), so they're the natural
first two to wire into extraction — zero new discovery work, straight to
testing the extraction path against real documents. Legistar/Granicus
(the largest jurisdiction count) next. Platforms with no confirmed
`agenda_link` at all (the ones the Roadmap entry's "~23 adapters surface
`agenda_link` at best" line refers to) come last, since each of those is
simultaneously new adapter-discovery work *and* new extraction-integration
work — don't conflate the two kinds of unknown in one PR.

**Step 4 — display and search**, once there's real versioned text to show:
template work for the current version, a diff view between versions
(reusing `agenda_diff.py`'s block-based output), and `search_corpus`
inclusion. This is the piece that makes 1-3 visible to a reader; doing it
last isn't deprioritizing it, it's sequencing it after there's real data to
render.

**Left out of the brief entirely, on purpose**: OCR (rtr-upcoming measured
one scanned document across 108 jurisdictions — not worth building), and
the alert-cursor mismatch (`created_after` is archive-ingest time; an
agenda amendment needs its own event type, distinct from `rtr-upcoming`'s
own `initial`/`amendment`/`reissued`/`alternate` classification carrying
through to a saved-search alert). Both are real, both are already flagged
in the Roadmap entry, neither blocks steps 1-4 above.

## What this buys, and what it costs

**Buys**: content-hash dedupe means a genuine revision is a real, alertable
event ("this item was added Monday") rather than noise; packet-over-agenda
preference makes a keyword in a staff report findable; and every trap in
the list above is pre-solved rather than rediscovered per-adapter, which is
exactly the kind of one-day-each cost this brief exists to avoid paying
twice.

**Costs**: this is still `[BIG]`. Step 2 alone is nontrivial (new
dependencies — `pypdf`/`pdfplumber`, neither currently in
`requirements.txt` — plus the fallback-on-detected-damage logic
`rtr-upcoming` needed to get ligature/space-loss mangling from ~19-94
occurrences down to 0 on real documents). Steps 1-2 are gated on nothing
external and could start independent of any single adapter decision; step
3's per-adapter rollout is where the real time goes, since each adapter
still needs a real live sample checked against the trap list before
shipping (this repo's own standing rule — never build from assumption).

## The actual question for Ryan

Is this worth starting now, and if so, at what step? Options as I see them,
roughly in order of how much they commit to before the first payoff:

- **Start at step 1 (model + migration) now**, treat 2-4 as normal backlog
  work over following sessions, same rhythm as everything else in this
  repo — lowest commitment, slowest visible payoff.
- **Start at steps 1-2 together** (model + a single working extraction
  path, tested against CivicPlus/CivicClerk's already-known real URLs) —
  the first slice where "agenda text is real and versioned" is
  demonstrably true for at least one jurisdiction, which is also the
  clearest point to decide whether to keep going.
- **Hold entirely** until there's a concrete forcing function — e.g. the
  `rtr-upcoming` integration this Roadmap entry calls out as the actual
  "why now" (that repo resolves 108 Bay Area jurisdictions today and has
  no accounts/saved-search/alerts of its own; this repo's ingest gate
  already accepts a video-less page on `agenda_link` alone, so agenda text
  is the one thing blocking that integration from being real).
