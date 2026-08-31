# Agenda text as a first-class, versioned asset — design reference and trap list

**Status: undecided proposal, not started.** This is not an investigation
of a bug and not finished work — it's the design reasoning and
real-world trap list for a large (`[BIG]`) roadmap item, moved out of the
live `BACKLOG.md` Roadmap entry so that entry can stay scannable. Nothing
here is done or actively being investigated; it's reference material a
future session needs verbatim before building any of this. See
`AGENDA_TEXT_BIG_VERSION_BRIEF.md` for proposed sequencing/options, and
the live `BACKLOG.md` Roadmap entry ("Agenda text as a first-class,
versioned asset") for the current-state summary that points here.

Three linked pieces make up the full proposal. None of them is
Chicago-specific; Chicago ELMS (City Clerk ELMS, which embeds a Vimeo
video) is one instance of the underlying gap, not the reason for it.

**The small, non-versioned slice of piece 2 already shipped** 2026-08-31
(PR #640) — see `BACKLOG_DONE.md`. Ryan's explicit call: no nightly sweep,
no versioning, no diffing, just a better link at resolve time. CivicPlus
and CivicClerk previously shipped no `agenda_link` at all despite already
fetching the data:

- CivicPlus's `td.downloads` cell can hold up to three renditions
  (`?html=true`, bare PDF, `?packet=true`, distinguished by href query
  string), confirmed on the real Durham NC fixture.
- CivicClerk's `event["publishedFiles"]` (vendor-typed `"Agenda"`/`"Agenda
  Packet"` entries), confirmed on Clovis CA and Emporia KS fixtures.

Both now set `agenda_link`, and a new `ResolvedMeeting.packet_link` field
threads through the Archive (new `meeting_pages.packet_link` column,
rendered as a plain outbound link below the agenda section, only when it
differs from `agenda_link`). This is resolve-time linking only — the
model/versioning/diffing/every-other-adapter work below is unchanged and
still needs a real decision before it's built.

## 1. The data model

`MeetingPage` has no agenda text at all today, and the two fields that
look like it are not it:

- `agenda_items` is `List[TranscriptSegment]` — `{start, end, text}`
  chapter markers tied to a video position. Filling it from an agenda
  would mean inventing timestamps.
- `agenda_link` ([archive/db/models.py:83](archive/db/models.py:83)) is a
  bare URL that is never fetched, so nothing about the agenda is
  searchable.

What it needs is **not a column — it is a versioned child table**,
mirroring `TranscriptVersion`'s shape, because **agendas get amended and
transcripts do not.** That is the one real semantic difference between the
two assets. An agenda is republished before the meeting: items added,
struck, continued. Content-hash dedupe means an unchanged re-fetch stores
nothing while a genuine revision becomes a first-class event — which is
exactly what an alert should fire on, and what a reader should be able to
see ("this item was added on Monday").

## 2. The resolver and every adapter

Resolving a meeting should *fetch and extract* the agenda, not merely link
it. Today ~23 adapters surface `agenda_link` at best. This is the largest
part of the work and the part with the most hidden traps — all of them
already hit and solved in `rtr-upcoming`, listed below so they are not
rediscovered one adapter at a time.

## 3. Display and search

Templates for agenda text and its versions, a diff view between versions,
and inclusion in `search_corpus` so the text is actually findable. Without
this the other two pieces are invisible.

## Why now: it also unblocks `rtr-upcoming`

That repo (separate, local, `~/src/rtr-upcoming` — deliberately NOT under
`~/Documents`, because macOS blocks scheduled background jobs from reading
it there) resolves upcoming agendas across **all 108 Bay Area
jurisdictions** and extracts their text. It has no accounts, saved
searches, query language or email delivery, and should never grow its own
— this repo has all four. The ingest gate already accepts a video-less
page (`result.segments or result.agenda_items or result.agenda_link or
result.video_url`, [app/main.py:744](app/main.py:744)); agenda **text** is
the only thing it cannot carry. So this work is a prerequisite for that
integration and independently worth doing for the archive's own pages.

## Reference implementation: read these in `rtr-upcoming` first

It is a working reference implementation of piece 2, and every claim in it
is measured, not assumed:

| file | what it answers |
|---|---|
| `UPCOMING_AGENDAS_FIELD_GUIDE.md` | The whole thing. "Getting the document, not just the link" covers extraction; the per-vendor guide covers every platform's traps. |
| `app/agenda_text.py` | Format dispatch and extraction (PDF/HTML/RTF/TXT/DOCX). |
| `app/agenda_diff.py` | What *changed* between versions, in blocks rather than lines. |
| `app/db.py` | `agenda_versions`: content-hash dedupe and version `kind`. |
| `COVERAGE.md` / `coverage.csv` | Every jurisdiction, provider, example agenda URL, and where the document really resolves after redirects. |

## Traps that will each cost a day, all measured 2026-08-26

- **~70% of agenda links are PDF**, 18% HTML. PDF extraction is the main
  path, not an edge case — and sniff the *response*, never the URL:
  Legistar's `View.ashx?M=A` and CivicPlus's `/AgendaCenter/ViewFile/` both
  return `application/pdf` with no `.pdf` in the link.
- **Never truncate a response body.** A PDF's cross-reference table is at
  the END of the file, so a sliced PDF is corrupt rather than partial
  (`pypdf`: "EOF marker not found"). A 25 MB cap silently destroyed five
  jurisdictions' agendas that extract 23k–762k characters when handed over
  whole. Packets run to 90 MB.
- **Prefer the agenda PACKET over the agenda** — it is additive, so a
  keyword appearing only in a staff report is still found. Morgan Hill
  12,659 → 762,698 characters. Whole corpus 17.4 MB across 283 versions,
  ~85 KB average.
- **A cell often holds several renditions and the best is not first**, and
  which format wins depends on which column it came from. Los Gatos:
  agenda column PDF 8,702 / HTML 8,141 (equivalent — take HTML); packet
  column PDF 290,592 / HTML 10,079 (Municode serves the same
  `adaHtmlDocument` in both columns, so preferring HTML discards the staff
  reports).
- **A content type lies.** Martinez serves `application/msword` for bytes
  that begin `PK` — a .docx. Trust the magic number.
- **A zero-byte body is "not published yet", not "unreadable"** —
  CivicClerk streams 0 bytes for an agenda that does not exist yet, while
  the event already carries a non-zero `agendaId`.
- **Classify a new version by CONTENT similarity, not by URL.**
  Jurisdictions publish amended agendas as **new attachments under new
  URLs**, so a URL rule both misses real amendments and manufactures false
  ones whenever an adapter changes where it fetches from — that happened
  here: switching one adapter produced 9 false "amendments" in a single
  run.
- **A scanned PDF is not a broken one.** No `/Font` resource on any page
  means a scan; label it rather than reporting a parser failure. Measured
  at one document across 108 jurisdictions, which is why OCR is not worth
  building.

## One design mismatch to plan for, not code around

The saved-search alert cursor is `created_after` — *archive* time, when a
page was ingested ([archive/db/crud.py:3994](archive/db/crud.py:3994)).
Agenda events are different: a first agenda appearing, and an amendment to
one already seen. `rtr-upcoming` classifies exactly that (`initial` /
`amendment` / `reissued` / `alternate`) and `created_after` cannot express
it.

## PDF extraction quality: two distinct mangling shapes, both real

Some PDFs extract mangled, and it costs SEARCH more than display — a query
for "participate" can never match `parBcipate`. Two distinct shapes, both
real:

- **Ligature loss** (`parBcipate`, `submiLed` — `ti`→`B`, `tt`→`L`/`M`,
  from a broken ToUnicode CMap).
- **Space loss** (`reportedRequest`, `firstBank`).

`pdfplumber` reads all of them cleanly where `pypdf` does not (Cloverdale
19 mangled → 0, Colma 25 → 0, Oakley 94 → 0) at roughly **3x the time** —
54s against 16s on an 81 MB packet — so `rtr-upcoming` uses it as a
*fallback* triggered only on detected damage, keeping whichever result
measures better.

Not everything that looks mangled is: Millbrae's 58 `supportLists` come
from the city exporting Word HTML to PDF with
`<!--[if !supportLists]-->` rendered into the page, so there is nothing to
repair.

## Improving extraction must not itself read as an amendment

Repairing a document already stored rewrites every affected block — that
is our change, not the jurisdiction's, and alerting on it is the same
false positive as the URL-based versioning case above. Exclude blocks
whose old side carried mangled words and whose new side does not.
