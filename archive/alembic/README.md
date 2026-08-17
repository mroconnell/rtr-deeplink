# Archive database migrations (Alembic)

## How this works, in plain terms

Think of the database as a filing cabinet full of folders. Each folder is a
**table** — one folder for meeting pages, one for saved searches, one for
transcript versions, and so on. Inside each folder are individual paper
forms, one per row of real data (one form per saved search, one form per
meeting). Every form in the same folder is printed with the same layout —
the same blank fields, in the same order. Those fields are the **columns**:
"email," "date created," "search text," and so on.

There isn't just one of these cabinets. There are several, and they can
each be at a slightly different point in time:

- **Your own laptop's practice cabinet** — a throwaway copy used for
  testing. You can empty it out and rebuild it from scratch any time, no
  consequences.
- **The real cabinet the live website actually uses** — production, with
  real people's real saved searches sitting in real folders. You can never
  just replace it. You can only carefully, deliberately modify what's
  already there, one change at a time, without losing anything.

The code in this repo (`archive/db/models.py`) always describes the
newest, correct design for every form — what fields it's supposed to
have right now. But a cabinet that's already full of filled-out forms
doesn't magically redesign itself the moment that code changes. Somebody
has to actually go add the new field to every form already sitting in the
folder (or decide what to fill in for the ones that don't have it yet).
**That's the entire problem Alembic exists to solve.**

### What's actually in this cabinet

This isn't abstract — here are the five real folders (tables) that exist
in the Archive's database today, what's really written on the forms
inside each one, and which part of the actual website reads or writes
them:

- **`meeting_pages`** — one form per real meeting the site has ever
  archived: its title, date, jurisdiction, the video link, the agenda.
  **This is the content behind every `/m/{slug}` page** you can visit on
  the site, and what `/meetings` searches over and `/coverage` lists.
- **`transcript_versions`** — one form per *attempt* at transcribing a
  meeting. A single meeting can have more than one of these over time —
  the captions scraped straight from the source, and later, a better
  AI-generated one — with a marker on exactly one saying "this is the one
  to show by default." **This is what fills the transcript panel and the
  language-switcher dropdown** on a meeting page.
- **`transcription_jobs`** — one form per "please transcribe this from
  audio" request, tracking its progress in real time (queued, chunk 4 of
  12 done, failed, etc.). **This is what the "Request Transcript from
  Audio" button creates, and what the background worker service reads
  from and updates as it works**, chunk by chunk, and what triggers the
  "your transcript's ready" or "we hit a snag" emails once it's done.
- **`meeting_page_url_aliases`** — invisible plumbing, no visible page of
  its own. Every real URL that's ever been pasted in and successfully
  matched to a meeting gets a form here pointing back at that meeting.
  **This is why pasting a link you (or someone else) already used lands
  you on the *same* existing page instead of quietly creating a
  duplicate.**
- **`saved_items`** — one form per "Save this meeting" or "Save this
  search" click a signed-in visitor makes. **This is what your Account →
  Saved page reads**, and, as of this week, what the new daily alert
  sweep reads too (the `last_alerted_at` field this whole migration adds
  lives on this exact form).

**Why five separate folders instead of one giant one?** Because the real
relationships between these things genuinely aren't "one thing has one of
each" — and a single flat form can't represent that. A meeting can have
*zero, one, or several* transcript attempts, so each attempt needs its
own form, not a fixed set of blank lines on the meeting's own form (which
would either waste space or run out). The same meeting can be saved by
*many different people*, so each save needs its own form, not a growing
list crammed onto the meeting's one form. Instead, every one of these
smaller forms carries a small **reference number** in the corner — the
`meeting_page_id` column — pointing back at exactly which meeting-page
form it belongs to, the same way a claim form references a case number
instead of re-copying the entire case file onto itself. That reference
number is what a **foreign key** is, if you see that term in the code:
just a pointer from one folder's form back to a specific form in another
folder.

**Alembic is a librarian for the cabinet.** It keeps a small logbook — a
real table in the database itself, called `alembic_version` — with a
single line written in it: "the forms in this cabinet currently match
design #14." Every time the intended design changes, someone writes up a
new, individually-numbered **instruction card** — a "migration" — saying
exactly how to update the forms to match ("add a field called
`last_alerted_at` to every saved-search form"). The librarian's whole job
is: read the logbook to see which cards have already been carried out,
apply every card newer than that, and update the logbook line to match.

A few words that come up constantly below, defined in plain terms:

- **Migration** — one instruction card. Lives as one Python file under
  `archive/alembic/versions/`, e.g. `..._add_last_alerted_at_to_saved_items.py`.
- **Revision id** — the serial number stamped on that card (e.g.
  `a6556277a68d`). It's a random-looking label, not a count — there's
  nothing to read into the digits themselves, it's just a unique name so
  two people can each write a new card on the same day without clashing.
- **`head`** — "whichever instruction card is newest, right now." This is
  a moving target, not a fixed point. Write a new card tomorrow, and
  `head` means something different tomorrow than it does today. Confusing
  this with a fixed name has already broken production for real once on
  this project, and nearly did a second time (see below) — it's the
  single most important idea on this page.
- **`alembic current`** — asks the librarian to read the logbook line out
  loud: "which card does *this specific* cabinet's forms currently match?"
  Always run this before doing anything else. The logbook can be wrong
  (see below), and acting on a wrong logbook is exactly how the past
  mistakes on this page happened.
- **`alembic upgrade head`** — tells the librarian: "go apply every card
  after the one written in the logbook, all the way to the newest one."
  This is the command that actually changes the real forms in the cabinet.
- **`alembic stamp <revision id>`** — tells the librarian: "don't touch a
  single form. Just cross out whatever the logbook currently says, and
  write this instead." Used when the cabinet secretly *already* matches a
  design (usually because the forms were changed by some other means and
  the logbook was simply never told), so this fixes the paperwork without
  redoing work that's already done. No real change happens to the actual
  forms — this command only ever rewrites that one line.

**Why the logbook can drift out of sync with reality in the first place**:
this app has a second, older, simpler way of changing the cabinet —
`create_all()`, which runs automatically every single time the app starts
up, and which is allowed to add a brand-new, empty folder to the cabinet
entirely on its own. That's convenient for a folder that doesn't exist
yet at all, but `create_all()` has never heard of instruction cards — it
never writes anything in the logbook, ever. So a table can be real,
correct, and already in use, while the logbook still insists an older
design is current. That exact mismatch is the root cause of every
incident recorded further down this page.

---

## Creating a new migration

*(Local, on your own laptop — this is the "write a new instruction card"
step, not something you do against production.)*

After changing a model in `archive/db/models.py`:

```bash
cd archive
alembic revision --autogenerate -m "add priority column to transcription_jobs"
```

**In plain terms**: this compares the design your code now describes
against whatever your *local* practice cabinet currently looks like, and
writes a brand-new instruction card describing the difference — a new
file under `archive/alembic/versions/`.

Autogenerate diffs the real models against whatever the target database
currently looks like -- **always review the generated file by hand**
before committing it (autogenerate is a good first draft, not a
guarantee: it can miss things like column renames, which it sees as a
drop-and-add instead, and check constraints/server-side defaults
sometimes need a manual touch-up).

## Applying migrations

*(Local, against your own practice cabinet — freely, no consequences.)*

```bash
cd archive
alembic upgrade head
```

**In plain terms**: this is the librarian actually doing the work —
walking through every card newer than what your local logbook says, and
making those changes for real.

Run this against local dev/test databases freely. **Do not run this
against the production database without a real, deliberate decision to
do so** -- see the one-time adoption step below first.

## Running this against production

**As of 2026-08-17 (WO-10) you normally don't — the deploy does.**
`render.yaml`'s `rtr-deeplink-archive` service has
`preDeployCommand: cd archive && alembic upgrade head`: Render runs it
after the build and *before* the new instance is switched live, so any
migration merged to `main` is applied to production before the code
that needs it starts. If the migration fails, the deploy is cancelled
and the previous build keeps running (Render's Events tab shows the
pre-deploy step and its log). "Already at head" is a fast no-op, so
doc-only pushes cost nothing. `archive/db/engine.py`'s `init_models()`
is a no-op on Postgres since the same change — this history is the
*only* thing that writes to the production schema — and CI runs
`alembic check` (models vs. a fresh migration-built SQLite) on every PR
so a model edit with no migration fails before merge. Two things to
keep in mind writing a migration now that it runs unattended: (1) code
in the same PR must tolerate the schema *before* the migration too, or
be gated on the column's existence (see `crud._fts_available()` — the
2026-08-17 `search_tsv` migration was designed to land in either order
and did); (2) a long table rewrite (a `GENERATED ... STORED` column, a
type change) holds an ACCESS EXCLUSIVE lock for its duration — the
`search_tsv` add was ~30s on the 77MB corpus — during which reads
block, so merge those at a quiet moment.

The rest of this section is still worth reading: it's the history of
how the production logbook got to `head` by hand (twice, painfully),
and it's the procedure to fall back to if the pre-deploy step ever
fails and you need to see or fix the state yourself.

*(When you do need the shell: a Render Shell tab for the
`rtr-deeplink-archive` service — `DATABASE_URL` is already set there
automatically as an environment variable, so every command below just
works as typed. You never need to type, paste, or export a database URL
yourself.)*

The very first migration in this history (`a8dc5aad7eff`,
`..._baseline_schema.py`) creates all four original tables from scratch,
since it was written by comparing the models against a genuinely empty
cabinet. Production's cabinet already has all four folders in it (built
up over this repo's life via `create_all()`, with real rows already
sitting in them) -- running `alembic upgrade head` against it exactly as
written would try to create folders that already exist, and fail.

Instead, production's logbook needs to be told "you're already at this
point, don't actually redo the work" -- that's exactly what `stamp` is
for (see the plain-language definition above): it writes a revision id
into the logbook without touching a single form.

**Real incident, 2026-08-09: an earlier version of this README said
`alembic stamp head` here.** That was correct for about twenty minutes --
right up until the very next migration (`8e7cf3b20f86`, the priority
column) was added to this same history. **In plain terms: "head" isn't a
fixed name, it's "whatever's newest right now" — so a note that says
"stamp head" can quietly mean something different by the time someone
actually reads and runs it.** Stamping production at `head` after a
second migration existed marked its logbook as "already has the priority
column" when it genuinely didn't, and the live app immediately started
failing every query with `column transcription_jobs.priority does not
exist`. **Always stamp the one specific revision id that matches what the
cabinet's forms actually look like right now**, never the word `head`,
unless you've personally confirmed `head` and that revision are still the
exact same thing.

**This needs to be run deliberately, by a person, never automatically.**

**Always run `alembic current` first and read its actual output before
running anything else here.** An earlier version of this section said
production "was never stamped at all yet" and told the reader to run a
fixed stamp+upgrade sequence unconditionally. That claim went stale
without this file being updated: a real 2026-08-10 run showed
`alembic current` printing `8e7cf3b20f86 (head)` *before* any command in
that stale sequence ran -- production had already been correctly
migrated at some earlier point (almost certainly as part of recovering
from the 2026-08-09 incident described above), just without this doc
being corrected to match. Blindly running the old recipe anyway
force-stamped production's logbook backward to the baseline revision,
even though the real cabinet was several designs ahead of that --
`alembic upgrade head` correctly refused with `DuplicateColumnError`
(the `priority` column already existed), caught immediately rather than
silently, but it still left the logbook one step behind reality until a
follow-up `alembic stamp 8e7cf3b20f86` corrected it. **The lesson: this
document's account of "what production's state is" is a snapshot from
whenever it was last written, not a live fact — verify against a real
`alembic current` (and ideally `GET /internal/schema-info`, which reads
the actual, live column list directly, no guessing involved) before
trusting it, every single time.**

```bash
alembic current   # ALWAYS run this first -- don't assume this doc's account of prod's state is still accurate
```

**In plain terms**: this is you personally asking the librarian to read
today's logbook line out loud, instead of trusting what this document (or
anyone's memory) claims it says.

- **If it prints the real current head revision already**: the logbook
  and the real cabinet already agree, and production is fully caught up.
  Nothing else to do.
- **If it prints nothing / an empty history**: production's cabinet has
  genuinely never had a logbook page written in it at all. Run:
  ```bash
  alembic stamp a8dc5aad7eff   # tell it: the folders already exist, matching the very first design
  alembic upgrade head         # apply every card written after that
  alembic current              # confirm it now shows the real, current head revision
  ```
- **If it prints something else** (a stale/wrong revision, as happened
  2026-08-10 and again 2026-08-13 — see below): don't run `upgrade`
  blindly. First confirm what the cabinet's forms *actually* have on them
  right now, in reality — the easiest way is:
  ```bash
  curl -H "Authorization: Bearer $ARCHIVE_INGEST_TOKEN" http://localhost:$PORT/internal/schema-info
  ```
  which reports the real, live column list for every table (no guessing),
  compared directly against what the current code expects. Once you can
  see exactly which columns are actually there, `alembic stamp <the
  revision id matching that real state>` corrects just the logbook line —
  `stamp` never touches an actual form, so this correction is always safe
  regardless of which direction the mismatch runs. Then `alembic upgrade
  head` to apply whatever real work is still left.

**A third occurrence of the same drift, 2026-08-13, this time caught
cleanly by following the procedure above rather than causing an
incident**: deploying the `last_alerted_at` migration (`a6556277a68d`),
`alembic current` against production printed `76a4a2820a2b` -- two
migrations behind head, not one. Real cause: the `saved_items` table
(migration `34f94d49a2ac`) shipped 2026-08-11 and has been live and
working since, but whoever deployed it never ran `alembic stamp
34f94d49a2ac` (or `upgrade head`) against production afterward, so the
logbook's line simply never got updated when that table's own
`create_all()`-driven creation made the migration itself redundant to
actually *run*. `GET /internal/schema-info` confirmed production's real
`saved_items` columns exactly matched `34f94d49a2ac`'s shape (missing
only `last_alerted_at`) before anything was touched -- `alembic stamp
34f94d49a2ac` corrected the logbook (no real change to any form), then
`alembic upgrade head` applied only the one real remaining migration. No
incident this time specifically *because* `alembic current` was checked
first and `/internal/schema-info` was used to confirm before stamping --
exactly the procedure this section already prescribes -- included here
as a third data point that this drift (a migration whose table already
exists via `create_all()`, so its own `alembic upgrade` step is silently
never run against production) is a real, recurring failure mode for this
repo specifically, not a one-off.

Verified locally (2026-08-09): a fresh `alembic upgrade head` against an
empty SQLite database creates a schema that diffs identical to
`create_all()`'s (only difference: the `alembic_version` bookkeeping
table itself, plus a cosmetic `(CURRENT_TIMESTAMP)` vs `CURRENT_TIMESTAMP`
default-clause rendering difference SQLite's own introspection reports
either way); `alembic downgrade base` cleanly drops everything back out.
The priority-column migration was also verified against a real
pre-existing row, confirming the backfill (`server_default`) actually
works, not just that the DDL runs. Confirmed against real production
Postgres too as of the 2026-08-10 incident above -- the column exists
there, backfilled correctly, no reported query failures since.
