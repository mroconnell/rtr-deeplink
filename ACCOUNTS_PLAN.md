# Accounts + token billing — phases 2-6

Phase 1 (Clerk sign-in, saved meetings and searches) shipped
2026-08-11 and is live; its build history is in `BACKLOG_DONE.md`,
and `README.md`'s "Accounts (Clerk)" section has the shipped
architecture. This file is everything *after* phase 1: the proposed
data model, the phased plan, the business-model framing, and the
open questions that need Ryan's call before anything past phase 1
gets built.

Nothing here is committed to. The one live compliance gap split out
of phase 1 — the never-fired Clerk `user.deleted` purge — stays in
`BACKLOG.md` under **Needs a human**, because it is real work on
shipped code rather than a plan.

Split out of [BACKLOG.md](BACKLOG.md) 2026-08-22; that file keeps a
short stub entry pointing here. Update both together.

---

**Phase 1 shipped 2026-08-11 and is live in production** (Clerk-based
sign-in, saving meetings and searches, `SavedItem`); its full build
history moved to `BACKLOG_DONE.md`. `CLAUDE.md` points here for what's
still ahead. The one live compliance gap split out of phase 1 — the
never-fired `user.deleted` purge — is under **Needs a human**.

**Expanded scope, per user request 2026-08-10 — a real social/content
layer, not just accounts + saved searches.** The user wants: a profile
page (public or private) made of independently public/private notes
(saving a meeting or search as a note; subscribing to in-profile and/or
email alerts for a search; reposting anything as a quote-repost;
eventually attaching media to notes; eventually sorting `/meetings` by
popularity). Capturing now since it reshapes the data model — not
committing to build any of it yet.

**Revised proposed data model**: a single polymorphic **`Note`** table
(account_id, `note_type` — `saved_meeting`/`saved_search`/`post`/
`repost`, `visibility` set per note, nullable `meeting_page_id`,
nullable `search_params` JSON, nullable self-referential
`parent_note_id` for reposts, `body_text`) replaces the original
separate `SavedSearch` table, since all four turn out to be the same
underlying shape. `Account`/`AccountSession` stay as originally sketched.
`NoteSubscription` (account_id, `search_params`, `notify_in_profile`,
`notify_by_email`) makes the two subscription channels independent
toggles on one row — `notify_by_email` is what "email alerts for saved
searches" actually becomes once accounts exist, not a separate build.
Media attachments and popularity-sort are both flagged "eventually" by
the user and need real new decisions (object storage — currently zero
file-upload capability anywhere in this codebase) not touched by this
scoping pass.

**Proposed phased plan, deliberately still not one big build:**
1. Passwordless accounts (magic link, session cookie) + base `Note`
   model (`saved_meeting`/`saved_search` only) — no billing, could ship
   free.
2. Public/private profile pages; `NoteSubscription` (both channels) —
   this is what unlocks "email alerts."
3. `post`/`repost` note types — the profile becomes a real feed.
4. Batch lookup, gated by account (rate-limited per-account instead of
   anonymous) — removes the anonymous-abuse-vector concern the batch-
   lookup item below flags.
5. Billing (Stripe the obvious default) layered on once there's a real
   paid tier — e.g. unlimited batch lookups, higher alert frequency,
   priority transcription queue position (`TranscriptionJob.priority`
   already supports this with zero schema change).
6. Media attachments and popularity-based sort — both "eventually,"
   sequenced last since both need real usage of earlier phases to be
   worth building against.

**Business-model framing, from the user, 2026-08-12 — replaces the
original "journalists are the paying user" framing entirely.** Advocates
and grassroots organizers are the primary intended audience —
journalists are a good example user but a smaller group, and shouldn't
be built into the product's core definition (`README.md`'s Vision
section now reflects this). The intended *paying* customer is different
again: institutional users with real budgets (special interest groups,
corporations, city staff/management).

**The likely shape of the split, directionally — not priced or built
yet.** A light user (one or two meetings/month for one body) vs. a heavy
individual user, plus a separate B2B/institutional tier for an
organization tracking a topic across many jurisdictions. Rough shape
floated by the user (not a commitment): free monthly credits sized for
the light-user case, a paid tier (reference point: ~$40/month) raising
the ceiling for heavy individual users, B2B priced/scoped separately.
Search itself stays free as long as it's cheap to run; if that stops
being true, a real explicit free tier (credits, or narrower scope) is
the plan, not a paywall outright. Not yet decided: actual credit
amounts, exact paid-tier price/limits, B2B pricing structure, or the
usage/cost threshold that triggers building any of this.

**Real open questions, not decided yet — need the user's call before
building past phase 1:** what's actually free vs. paid; whether "token
billing" means a metered credit system, flat tiers, or both; whether
Stripe is the intended provider or just this write-up's default
assumption; free tier size for saved searches/alerts; whether a repost
of a repost chains to the original or nests; moderation for public
notes/profiles in general — public+free-text `post`/`repost` messages
are real new user-generated-content surface area this app has never had,
worth its own look before phase 3 ships.

**Timestamp-level annotations on a note — proposed by the user,
2026-08-14.** Example: save a deep link with a user-written notation
pinned to one moment (`t`/`line`/`version`), not the meeting as a whole
— a real gap in the `Note` model above, since `saved_meeting` currently
only carries a whole-meeting reference and `body_text` is reserved for
`post`/`repost`. Cheapest fit: let `saved_meeting` notes also set
`body_text` and add nullable `t`/`line`/`version` columns (or a single
`deeplink_params` JSON blob, matching `search_params`'s existing
precedent). Directly useful for the advocate/organizer audience this app
targets, and a natural building block toward `post`/`repost` (a
moment-annotation is close to a first-class quote-post). Sequence
alongside or just after phase 2's profile pages. Distinct from
`CLAUDE_BACKLOG.md`'s "Quote-clip sharing" idea (that one is a *public*
shareable image/card; this is a personal notation, no image generation
required). Not yet built or scoped further.
