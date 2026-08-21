# Claude-generated Backlog

Ideas proposed by Claude on 2026-08-07, after reviewing the full `BACKLOG.md`
and current repo state, specifically to avoid duplicating anything already
tracked there. Not yet reviewed/prioritized by the user — treat this as a
suggestions list, not a committed roadmap. Once an item is accepted, move it
into `BACKLOG.md` proper (in that file's style) rather than marking it done
here.

**Status (2026-08-08):** 6 of the original 12 items are done — test suite,
rate limiting, schema.org markup, transcript export, RSS feed, and
report-a-problem all shipped, each with real bugs caught along the way (see
`BACKLOG_DONE.md`'s entries dated 2026-08-07/08 for the full writeups).

**Status (2026-08-21):** the whole "Reliability / engineering health"
section is now done and has been moved to `BACKLOG_DONE.md` (see its
"CLAUDE_BACKLOG reliability items" entry) — both the adapter health canary
(shipped 2026-08-16 as WO-13, with real daily run history including a real
failure on 2026-08-18) and Sentry error monitoring (live on all three
services, with real production issue IDs already triaged). Both had sat
here described as open for two weeks after shipping, which is exactly the
doc-drift `CLAUDE.md`'s own promotion rule exists to prevent; the entries
below this line have *not* been re-checked against the current repo state
with the same rigor, so verify before assuming any of them is still open.

## Growth mechanics

Ties directly to the app's stated growth mechanism: shareable deep link →
organic growth (see `BACKLOG.md`'s roadmap intro and the newsletter/GA
items).

- **Social share previews with an image.** ~~No `og:image` or
  `twitter:card` at all~~ — partially shipped 2026-08-14: YouTube-backed
  pages now unfurl with the video's real `i.ytimg.com` thumbnail (see
  `BACKLOG_DONE.md`'s "VideoObject.thumbnailUrl + Clip key moments"
  entry). ~~The `twitter:card` half regressed the non-YouTube majority,
  though: that tag shipped *inside* the thumbnail guard, so every
  non-YouTube page emitted none at all~~ — **fixed 2026-08-21 (WO-27),
  see `BACKLOG_DONE.md`**; every page now emits a card
  (`summary_large_image` with an image, `summary` without). **Still
  open, the original idea's real remainder**: mp4/m3u8
  pages (the majority) still have no *image* to put on that card, and a
  *generated* branded share-card (jurisdiction + meeting title + maybe a
  quoted transcript line) would beat a raw video frame even where the
  thumbnail now exists — overlaps with "Quote-clip sharing" below.
- **Quote-clip sharing.** Let a user select a transcript excerpt and
  generate a shareable image/card of that quote + timestamp + a link back
  to that exact moment — a much stronger viral unit than a bare link, and
  journalists/advocates already do this manually with screenshots.
- **Social auto-posting: durable queue instead of drop-on-burst.**
  Discussed with Ryan 2026-08-21 while building the between-posts buffer
  (`SOCIAL_MIN_POST_INTERVAL_SECONDS`, see README's "Social
  auto-posting" section); his call was "fine for now" on the shipped
  drop-based design, so this is parked, not accepted. Today a burst of
  qualifying new pages posts one announcement per 180s window and
  permanently drops the rest (a page's only shot is at creation). If
  dropped bursts ever start feeling like lost reach, the upgrade path is
  already shaped: claim burst candidates as `status="queued"` rows in
  the existing `SocialPost` table and release the oldest whenever the
  window is open, driven opportunistically off ingest traffic — the
  exact durable-sweep pattern `app/main.py`'s Archive push-retry already
  uses, so it survives restarts without a scheduler or sleeping tasks.
  Must ship with a max-age cutoff (e.g. skip anything queued >24h) —
  "Somebody looked up X" reads wrong days late, and 500 queued posts at
  180s spacing is a full day of nonstop posting without one.
- **Newsletter subscribe copy is generic — could be more specific about
  what a subscriber actually gets.** Current copy (`app/templates/
  subscribe.html`, `app/templates/base.html`'s footer prompt): "Get
  notified about new features and tools for finding public meetings."
  Inspiration flagged by the user (2026-08-09): Vikram Oberoi's
  citymeetings.nyc (see BACKLOG.md's NYC/Viebit entries for how this came
  up) uses "Highlights of meeting moments and curious claims every 1-2
  weeks" — concrete, content-focused, and sets a real cadence expectation,
  vs. our vague "new features" framing. Worth rewriting once there's
  actually a recurring content cadence to describe honestly (a newsletter
  promising specific content needs to actually deliver it) — not just a
  copy swap today.

- ~~**A real example URL under the paste box on the landing page.**~~
  **Built 2026-08-21 (WO-27) — see `BACKLOG_DONE.md`.** Shipped with the
  user's own design (plain text, not a link) and the two open questions
  decided as: one fixed example, and copy that does state what the
  visitor gets. Also replaced the fabricated `citycouncil.granicus.com/
  player/clip/1234` placeholder that was the only "try this" affordance
  before it.

## Utility for the actual audience

Journalists, watchdog orgs, researchers — the people `BACKLOG.md`'s "manual
transcription" contact CTAs and the civic-scraper research were already
oriented toward.

- **Read-only public API with API keys**, sitting on top of the Archive
  once search/filters exist (per `BACKLOG.md`'s roadmap). Civic-tech orgs —
  the `civic-scraper`/OpenGov community already evaluated for this project —
  are a natural audience to build on top of resolved data rather than
  duplicate the scraping work themselves.

## Reach

- **Lightweight jurisdiction "follow" (email-only, no account).** A
  magic-link-style "notify me when a new X meeting is archived" that
  doesn't require the full accounts+billing system already scoped in
  `BACKLOG.md`'s roadmap — much smaller than that item and could ship well
  before it. Its core mechanism (email address, confirm once via a
  clicked link, frictionless after that) is now proven out for real —
  on-demand transcription (built 2026-08-08, see `BACKLOG_DONE.md`) uses
  exactly this pattern for its own email step, so building this would
  mostly mean reusing `archive/utils/email.py`'s confirmation-email/
  audience-membership functions for a different trigger, not inventing
  the mechanism from scratch.

## YouTube transcript acquisition — further-out ideas

From the 2026-08-10 analysis session that produced the transcript-wanted
queue + local fetcher (see BACKLOG_DONE.md); these are the not-chosen
options worth remembering if the local-script approach ever stops
scaling.

- **A visitor-powered "contribute this transcript" bookmarklet.** A
  plain button on our page *cannot* fetch YouTube captions from the
  visitor's browser — CORS blocks cross-origin reads regardless of IP.
  But a bookmarklet clicked *while on the youtube.com watch page itself*
  runs same-origin: it could call the same InnerTube endpoints the
  page's own "Show transcript" panel uses (visitor's residential IP,
  visitor's session) and POST the result to a new Archive endpoint.
  Flow: meeting page says "no transcript yet — help us get it" → deep
  link to the video on YouTube → visitor clicks the (once-installed)
  bookmarklet → transcript lands in the Archive. Real challenges before
  building: an inbound public submission endpoint needs real abuse
  hardening (validate segment monotonicity/density against the video's
  known duration, land as a non-default version pending review, rate
  limit), bookmarklets are a power-user ask, and browser CSP handling of
  `javascript:` URLs varies. A browser extension is the heavier,
  more-legitimate version of the same idea. Neither is worth building
  while one person running one script covers the volume.
- **Residential-proxy or third-party transcript API fallbacks** (Bright
  Data-style proxies for server-side yt-dlp; Supadata/SearchAPI-style
  paid transcript APIs). Both work without any local machine, both cost
  real money per month/call, and both outsource a ToS-gray dependency.
  The decision record and per-option tradeoffs live in BACKLOG_DONE.md's
  2026-08-10 experiment entry; revisit only if the local script becomes
  the bottleneck.

## Agenda/minutes PDF text extraction

Proposed by the user (2026-08-11), right after `agenda_link` (a raw URL,
no extracted content) shipped for Granicus meetings whose `AgendaViewer.php`
redirects to a plain agenda PDF instead of Granicus's native timestamped
agenda-index — see `BACKLOG_DONE.md`'s 2026-08-11 entry. No PDF
text-extraction library exists anywhere in this codebase today (checked
`requirements.txt` and grepped for `pdfplumber`/`pypdf`/`pdfminer`/`fitz` —
nothing), so this is new infrastructure, not a tweak to the existing
`agenda_link` fallback.

- **Extract and display the actual text of the agenda/minutes PDF**, not
  just a link to it, in the meeting page's Agenda section. The user's
  framing for why this matters beyond just "nice to have": these PDFs
  routinely carry two things the transcript pipeline gets wrong or
  misses entirely --
  - **Speaker names.** Names are spoken aloud in the audio but are a
    common Whisper mis-transcription target (unusual surnames, names
    that sound like other words). A PDF with a real roster/attendee list
    is a much more reliable source than trying to get the ASR to spell
    them right.
  - **The actual agenda content/topic list**, for meetings where no
    parseable per-item chapter data exists at all (exactly today's
    Napa City Council/Housing Authority case) -- right now those
    meetings have literally nothing describing what was discussed
    beyond the raw video and a bare link.
  - Meeting **date** is a third, lower-stakes but still useful field
    these PDFs usually carry near the top, and a few existing adapters
    already lean on that today in a narrower form (Granicus's own
    `_fetch_minutes_date()`, and the Alexandria docket-PDF-filename date
    fallback in `granicus.py` -- see `BACKLOG_DONE.md`) -- this would
    generalize that pattern rather than inventing something new.
  - **No timestamps expected from these PDFs, and that's fine** --
    unlike `agenda_items` (real per-item chapter markers with start
    times), this would be plain extracted text, the same "not
    clickable, just readable" treatment already used elsewhere for
    caption formats we can't parse into a clickable transcript.

  **Which document to use, when there's more than one.** A single
  meeting often has multiple candidate PDFs -- an original agenda, a
  later "updated agenda," and eventually minutes -- and per the user,
  which one most closely matches the actual meeting order is
  unpredictable case by case (an updated agenda is usually closer to
  what actually happened than the original, but not reliably so, and
  minutes may or may not exist yet depending on how soon after the
  meeting this runs). Proposed approach: try candidates in some
  descending priority order (e.g. minutes, if published > updated
  agenda > original agenda) and use the first one that resolves,
  rather than trying to merge/reconcile multiple documents.

  **How to classify a given PDF at all** (agenda vs. minutes vs. some
  unrelated attachment): the user's proposed default heuristic is
  simply checking whether the extracted text says "agenda" (or
  "minutes") near the top of the document, rather than trying to
  identify it from the URL/filename alone -- filenames vary too much
  across jurisdictions to rely on (this repo's own adapters already
  each parse differently-shaped Legistar-style filenames per city).

  Open questions before building: which PDF library to add (scanned
  government PDFs with no real text layer are a real, likely-common
  failure mode any choice needs to degrade gracefully on -- same
  "some will look great, others garbled or empty" risk flagged when
  this was first discussed in conversation); where extracted text lives
  (`ResolvedMeeting.agenda_link` is a single URL field today, so this
  likely needs a new field, e.g. `agenda_text`, not a repurposing of
  the existing one, so a direct link is never lost even when extraction
  partially fails); the matching Archive-side schema change (a new
  `MeetingPage` column needs an Alembic migration, per this repo's
  established convention for altering an existing table -- see
  `archive/alembic/README.md`); and whether this is Granicus-specific
  at first (today's real, confirmed-live motivating case) or worth
  generalizing to every adapter that can produce an `agenda_link`
  (`generic_fallback.py` also produces one, for a differently-shaped
  problem -- best-effort unknown-platform sites, not Granicus's
  PDF-redirect case specifically).

  Per the user (2026-08-11) and consistent with this repo's established
  "test against a real, live URL first, ideally several from different
  cities" convention (see this file's header note and `CLAUDE.md`):
  before/while building, pull real agenda and minutes PDFs from a
  handful of cities -- Napa (today's motivating case) plus a few others
  already in the sample sheet -- to see how extraction quality actually
  varies across real government PDF layouts (text-layer vs. scanned,
  single- vs. multi-column, tables) rather than assuming one city's
  PDFs are representative.

## On-demand transcription follow-ups

Both raised directly by the user alongside the original transcription
request, deliberately not built as part of it — see `BACKLOG_DONE.md`'s
2026-08-08 entry for the full feature this extends.

- **Speaker diarization + a UI to map detected speakers to real names —
  confirmed 2026-08-09 as a good future feature, journalistic-value
  framing added.** For journalistic use, an unattributed quote is much
  weaker than one that can be cited as "Councilmember X said..." — this
  is the difference between a transcript being a navigation aid and being
  a citable source. The transcription pipeline already uses self-hosted
  `faster-whisper` specifically because it's the same base model WhisperX
  builds real diarization on top of (via `pyannote.audio`) — and
  `TranscriptSegment` (`app/platforms/models.py`) already carries an
  unused `speaker` field for exactly this, added cheaply now rather than
  needing a schema touch later, so this is additive to the existing data
  model, not a redesign. Real work still needed: running the diarization
  pass itself (a real compute/latency cost on top of transcription — size
  it before committing), and a UI for someone to label "Speaker 1" as an
  actual name (per meeting, or per recurring seat/role if a
  jurisdiction's council composition is known) — no design started on
  that UI yet. Real name resolution is the harder, longer-term half of
  this — worth explicitly sequencing unlabeled diarization first (ship
  "Speaker 1 vs. Speaker 2" attribution on its own) rather than blocking
  the whole feature on solving name-mapping too.
- **Compare the finished transcript against the meeting's agenda for
  topic-coverage accuracy.** E.g. flag agenda items that don't seem to
  have been discussed, or roughly locate where each agenda item's
  discussion starts in the transcript beyond what the source's own
  chapter markers (when present) already provide. No design started —
  open questions include what "coverage" even means precisely (exact
  phrase match against agenda text would miss most real discussion,
  which paraphrases rather than reads the agenda aloud) and whether this
  needs an LLM pass over the transcript or something simpler.
- **Reader-facing low-confidence/quality flag on Whisper-generated
  transcripts -- raised by the user 2026-08-18, alongside a real bug this
  same conversation found and moved to `BACKLOG.md` (the
  `detect_language_from_texts()` first-2000-characters mislabeling
  entry).** Today `detect_hallucination_warnings()`'s output
  (`transcript_warnings`, `_GARBLED_MARKER`) only feeds
  `app/db/outcomes.py`'s internal admin-reporting classification -- not
  shown to readers at all. The user's framing: something like Wikipedia's
  confidence banners ("this section needs more detail" / "needs human
  verification") -- surface *and* explicitly acknowledge that a given
  transcript (or section of one) hasn't been human-verified, rather than
  presenting AI-generated text with the same visual confidence as a real
  scraped government caption. Root cause context from the user, worth
  keeping when this gets designed: these sources often have short (2-3
  min) genuinely-foreign-language stretches (proclamations, a single
  speaker) or dead air/loud music (meeting open, or a recess in a 4+ hour
  meeting) that Whisper isn't built to handle well, embedded in meetings
  that are otherwise clearly one language throughout -- so a good flag
  should probably be scoped to the *offending stretch*, not just a
  whole-page badge. Not designed yet -- open questions: page-level banner
  vs. inline per-segment/per-chunk marking (today's warnings are
  chunk-scoped, not whole-page), and whether it should also fire on the
  language-mislabeling failure mode even when
  `detect_hallucination_warnings()` itself sees nothing wrong (a
  confidently-wrong language label isn't currently a "warning" at all).
- **Compare `large-v2`/`large-v3` faster-whisper output against the
  production `small`/`tiny` defaults on a real bad chunk -- raised by the
  user 2026-08-18, not yet run.** Proposed protocol (the user's own): once
  a specific meeting/chunk is confirmed low-quality (e.g. via the
  reader-facing flag above once it exists, or by manual review), re-run
  just that chunk -- not the whole meeting -- through both the
  currently-used model size and `large-v2`/`large-v3`, then compare
  outputs by eye. Needs a small standalone harness against
  `FasterWhisperEngine` (`worker/transcription_engine.py`) rather than a
  full `transcribe_backlog_locally.py` run, to target one chunk cheaply.
  Purpose: find out whether the quiet-audio/hallucination pattern above
  is a `small`-model-specific weakness `large-v2` genuinely does better
  on, or a more fundamental Whisper-family limitation on real crowd
  noise/music that a bigger model won't meaningfully fix -- informs
  whether it's worth widening `_pick_default_model_size()`'s RAM tiers or
  whether the reader-facing flag above is the more honest fix regardless
  of model size.

## SEO / LLM-discoverability

From a full-site audit run 2026-08-13, prompted by the user asking what
would help this site "stand out for our target users doing search engine
search or LLM research" — both classic SEO (ranking for queries like
"watch [city] council meeting") and AI-agent discoverability (an LLM-powered
browsing/research tool finding, citing, or recommending this tool). Audited
directly against the real templates/routes, not assumed. Two items already
confirmed working and not re-flagged here: `meeting_page.html`'s canonical
`<link>`/`og:url` (already correctly points at the bare `/m/{slug}` URL even
when viewing a non-default transcript version) and its existing `VideoObject`
JSON-LD block. `robots.txt` already allows GPTBot/ClaudeBot/PerplexityBot/
Google-Extended by default (`User-agent: *`, no bot-specific blocks) — no
crawler-access problem to fix, only documentation to optionally add.

**Tier 1 — highest value, matches this product's actual differentiator:**

~~The first two Tier-1 items — `Clip`/`hasPart` "key moments" JSON-LD and
`thumbnailUrl` reused for `og:image`/Twitter Card — were accepted and
built 2026-08-14~~ (per this file's convention: moved out once accepted —
full build/verification detail in `BACKLOG_DONE.md`'s
"VideoObject.thumbnailUrl + Clip key moments" entry). The residual —
mp4/m3u8 pages still thumbnail-less pending real `ffmpeg` frame
extraction — is tracked in `BACKLOG.md`'s Google Search Console entry,
not here.

~~**ISO-8601 timezone on `uploadDate`.**~~ Built 2026-08-14 alongside the
other Wave 1 fixes — full detail in `BACKLOG_DONE.md`.

~~**Tier 2 — solid, low-cost, template-only:** canonical links on
`/meetings`/`/coverage`, `Event` JSON-LD alongside `VideoObject`, meta
descriptions on `index.html`/`about.html`.~~ All three built 2026-08-14
alongside the other Wave 1 fixes — full detail in `BACKLOG_DONE.md`.

**Tier 3 — lower priority / more experimental:**

- **`llms.txt`.** Research finding, not assumption: adoption sits around
  8-10% of major sites, but AI search crawlers (ChatGPT, Perplexity, Claude)
  essentially don't fetch it in practice, and its presence doesn't correlate
  with being cited more — consensus framing is "low-cost, low-yield bet,"
  not a ranking lever. Where it *does* get used is dev-tooling agents
  (Cursor, Claude Code) pointed at documentation sites, which isn't this
  product's shape. If built at all, frame it as a machine-readable
  navigation aid for an agent trying to *use* the tool on a visitor's
  behalf (site shape, URL patterns like `/m/{slug}`), not an SEO play —
  set expectations accordingly.
- **Semantic `<time datetime="...">`.** ~~Nothing in this codebase used
  `<time>` anywhere.~~ **Meeting dates done 2026-08-21 (WO-27) — see
  `BACKLOG_DONE.md`**: `page.date` and its list/hub/state/saved
  equivalents now render through a `meeting_date_html` filter, validated
  so an unparseable stored date falls back to plain text rather than an
  invalid `datetime` attribute. **Deliberately still open, and not
  obviously worth doing**: the *transcript/agenda offsets* this entry
  originally named (`[12:34]`). Those are **durations, not datetimes** —
  HTML's `datetime` attribute would need `PT12M34S` for them, which is a
  different change with a much weaker case: a duration-valued `<time>`
  says "this lasted 12m34s," not "this moment is 12m34s into the video,"
  so it doesn't actually express what the timestamp means, and no
  crawler or screen reader is known to do anything useful with it here.
  Pick this up only with a concrete consumer in mind.
- **Explicit AI-crawler naming in `robots.txt`.** Already permissive via
  `User-agent: *`; this would only add documentation value, not function.

**Considered and explicitly rejected, so a future pass doesn't re-litigate:**

- **`GovernmentOrganization` markup describing the jurisdiction.** Real
  conflict with this app's own documented spoofing/trust-risk concerns
  (`BACKLOG.md`'s trust & safety section already flags that an unverified
  `generic_fallback` page could become "a seemingly-legitimate, SEO-indexed
  permanent page under a real-sounding jurisdiction name") — marking up the
  jurisdiction itself as a `GovernmentOrganization` would actively worsen
  that risk. If ever used, it should describe the actual verified
  publisher/platform, never the jurisdiction, and never on a
  `generic_fallback`/`noindex` page.
- **`BroadcastEvent`.** For live-streamed content only; this product is
  archived/on-demand playback of past meetings.
- **`Legislation`/`GovernmentPermit` schema types.** No matching fields
  anywhere in the real `MeetingPage` data model (no bill numbers, no
  legislative text) — would be inventing structure that doesn't exist.
- **`rel="next"`/`rel="prev"` pagination on `/meetings`.** Google
  deprecated using this signal for indexing in 2019; not worth building.

## Discoverability additions (2026-08-14)

From a discoverability strategy discussion with the user. The marketing-
shaped half of that session (newsjacking playbook, partnership targets,
launch timing) lives in `~/Documents/rtr-business/marketing/
discoverability-ideas.md`, not here; the user is separately already
executing personalized deeplink outreach and native social clips
themselves. Two of the session's four product-shaped ideas were **already
tracked above and are deliberately not re-added**: "key moments"
`Clip`/`hasPart` JSON-LD (SEO Tier 1) and the thumbnail/`og:image`
share-card pair (Growth mechanics' "Social share previews" +
"Quote-clip sharing" and SEO Tier 1's `thumbnailUrl` entry — the
session's discussion reinforces their priority rather than changing
their content). The two genuinely new:

## Data sourcing / coverage growth (2026-08-15)

Raised by the user after the jurisdiction pipeline shipped, asking what
a *future* Granicus/Swagit bulk-pull round (like the ~1154-URL Granicus
batch and its Swagit companion this session ingested, 204/204 and
207/207 clean after filtering) should do differently. Confirmed first:
that batch's success/failure was entirely a video/caption-availability
question (dead links, 0-segment archive.org captures) — completely
orthogonal to jurisdiction quality, since this session never touched
Granicus's/Swagit's own video/caption-fetching code. So these ideas are
about *finding more real candidate URLs*, not about anything the
jurisdiction work itself would unlock.

- **Census-place-table-driven candidate generation.** Didn't exist as
  reusable data before this session; `app/utils/jurisdiction_data/
  places.csv` (real US Census Gazetteer incorporated places, ~2,243
  unique names) is now a complete, systematic list that could seed
  candidate discovery instead of only classifying URLs already found —
  e.g. probing `{place-slug}.granicus.com` / `.new.swagit.com` for every
  Census place, or as search-query seed terms. Real, unverified
  question before building anything: how well Census place *names* map
  to actual Granicus/Swagit *subdomain* conventions (the "(balance)"/
  consolidated-government naming quirks this session's own data fix
  dealt with are one small example of the mismatch risk) — would need
  checking against a sample of known-real customer subdomains first,
  same "verify before generalizing" convention as everywhere else in
  this repo.
- **Legistar as a second discovery channel for Granicus cities.**
  Legistar doesn't host its own video — confirmed this repo already
  delegates it straight to Granicus (`resolve_via_platform()`, see
  CLAUDE.md's platform-wrapper convention). So a Legistar-sourced URL
  list isn't new resolution capability, it's a *different candidate
  list* that might contain real Granicus customers the archive.org
  scrape missed. Worth doing only if a real Legistar URL source (a
  directory, another archive.org query) turns up — not worth inventing
  one from scratch.
- **Whether to exclude school districts/MPOs/transit authorities from a
  future pull is a scope decision, not a data-quality one — flagged,
  not recommended either way.** The jurisdiction pipeline was
  deliberately built so these don't need excluding (`finalize_jurisdiction()`'s
  "unverified" tier stores them as-is rather than mangling or dropping
  them — real examples confirmed live: Warren County Public Schools VA,
  Broward MPO). Filtering them at *sourcing* time would only make sense
  if the product goal narrows to "cities and counties specifically"
  rather than "public government meetings broadly" — that's the user's
  call to make, not a technical fix to build.
- **How much headroom is actually left in "going deeper" on the
  existing Granicus/Swagit lists is unknown** — nobody has checked how
  complete the original archive.org-sourced Granicus list or the Swagit
  companion list actually are against the real universe of Granicus/
  Swagit customers. Worth a real check (even a rough one, e.g. sampling
  known customer directories if either platform publishes one) before
  assuming there's more to find there versus the Census-driven approach
  above finding it more systematically.
- **Civic-tech/intelligence-aggregator sites as a candidate-URL source —
  raised by the user 2026-08-19 via a researcher note, followed up with
  real web research the same day.** The note named two products (Hamlet,
  "Curated Civic Data") plus CHiME/AMI as ASR research corpora. Findings:
  - **Hamlet (myhamlet.com) is real** — AI civic-intelligence platform,
    3,000+ local governments, ~30,000+ meeting transcripts, freemium
    search UI (basic search free, 14-day trial for full transcripts/
    alerts). Customer base (real estate developers, data center
    operators, journalists, nonprofits) matches the note. **No public
    API or bulk-licensing page found** — nothing suggesting a scrapable
    jurisdiction list or dev access beyond the search UI itself. No
    associated open-source project.
  - **"Curated Civic Data" doesn't exist under that name.** Closest real
    matches, likely what the note actually meant: **GatherGov**
    (gathergov.com/api) has an actual documented API — Transcript,
    Search, and Custom endpoints, docs at `api.gathergov.com/docs`,
    covering 6,200+ municipalities / 1,600+ counties / "94%+ of the US
    population" — and is positioned explicitly for "real estate and
    hyper-local municipality intelligence," closer to the note's
    monetization claim than Hamlet is. No pricing or free tier listed;
    gated behind a demo request, so still unconfirmed whether the API
    is usable without a paid contract. Also found: **Curate**
    (curatesolutions.com, now part of FiscalNote — minutes/agendas from
    12,000+ entities into a dashboard/digest, a documents product, not
    video/transcript) and **CivicTranscript** (civictranscript.com,
    per-jurisdiction transcript search e.g. `solvang.civictranscript.com`,
    no API found). All four are paid/gated — none expose a free
    jurisdiction list or bulk API without a sales conversation, so none
    of them directly solve "enumerate more meeting hosts" for free.
  - **CHiME/AMI confirmed as real ASR research corpora** but they don't
    lean on *government* meetings specifically enough to be a useful
    jurisdiction-discovery lead — a dead end for this specific purpose,
    despite being real datasets.
  - **The one genuinely actionable find: [LocalView]
    (https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/NJTBEM)**,
    an academic dataset (Barari & Simko, *Scientific Data*, 2023). Free,
    **CC-BY-4.0, no login required**, downloadable as Parquet/CSV/JSON/
    Stata/RDS. Covers 139,616 YouTube videos + transcripts from **2,861
    distinct local governments**, 2006–2022, with fields for state,
    place name, FIPS code, **YouTube video ID and channel ID**, meeting
    date, and full transcript/caption text. This is directly a
    jurisdiction→YouTube-channel candidate list, and this repo's
    resolver already handles YouTube natively (`YouTubeAssetFinder`, see
    CLAUDE.md's PrimeGov-wrapper note) — no new adapter needed, just a
    candidate-URL feed. Real caveat: data stops at 2022, so it's a
    historical-coverage snapshot, not live discovery of brand-new
    channels — though the channel IDs are very likely still active and
    could be probed for newer uploads the same way the Census-place
    idea above proposes probing subdomains.
  - **Also found (real, active, but Chicago-scoped): [City-Bureau/
    city-scrapers](https://github.com/City-Bureau/city-scrapers)**,
    Scrapy-based, 2,570 commits, actively maintained. Ships a template
    repo for adapting to other cities but doesn't itself cover a
    national list.

  **Before building anything with LocalView:** same "test against real,
  live data first" convention as everywhere else in this repo — pull the
  actual dataset (or a year slice), spot-check a sample of its YouTube
  channel IDs against jurisdictions already in the sample sheet /
  `app/utils/jurisdiction_data/places.csv` for overlap vs. new coverage,
  and confirm a handful of those channels are still live and posting
  before treating this as a real candidate-URL source. Also worth
  cross-checking `~/Documents/rtr-business/research/CDX_QUERIES.md` and
  `HYLAND_DISCOVERY.md` first, per [[reference_source_discovery_research]]
  — this may turn out to substantially overlap with archive.org-sourced
  YouTube coverage already pulled in past sessions rather than being
  wholly new.

- **"Famous moments in public comment" curated collection page.** A
  hand-curated, permanent page of notable public-hearing moments (the
  user's example: Dave Chappelle speaking against a housing development
  at a Yellow Springs, OH council meeting), each deep-linked to its
  archived moment with a transcript excerpt. Durable listicle-bait that
  earns backlinks between news cycles, and pairs directly with the
  user's in-motion native-clips marketing (each clip's "full context"
  link can point here or at the specific page). Curation stays manual by
  design — trust posture: only confirmed-real meetings, consistent with
  `BACKLOG.md`'s trust-tier thinking. Open questions: where the curated
  list lives (a checked-in data file rendered by the Archive vs. a DB
  table — a small checked-in file matches this repo's lean bias); and
  the real prerequisite that each featured meeting must first resolve
  and archive successfully (many candidates are on city YouTube
  channels, which the resolver already handles — worth confirming
  per-moment before it makes the page).

## Google Search Console — indexing-exclusion alerts (2026-08-16/17)

First surfaced via the user manually pasting one email; the rest read
directly from Gmail (`RTR-Claude` label) once the connector was enabled
for this session, 2026-08-17 — 9 threads total under that label, all from
`sc-noreply@google.com`. Two (`how-to-adu.com`'s indexing/performance
alerts) are about a different site entirely, not this repo, and correctly
excluded from any of this. One (2026-08-12, "Videos structured data
issues") duplicates the alert already tracked in `BACKLOG.md` (same
`thumbnailUrl`/`uploadDate` issues) — no new entry needed. The rest are
onboarding/informational (GA property association, "monitor search
traffic," generic "improve your presence" tips) — not actionable findings.

Three real, distinct indexing-exclusion reasons across two alert emails,
site-wide for `redtaperecordings.com`:

- **"Excluded by 'noindex' tag" — root cause found and confirmed via code,
  moved to `BACKLOG.md`.** The 2026-08-17 alert scoped specifically to
  **sitemap-submitted pages** (not just any crawled page) turned out to be
  a real, traceable bug, not the "probably intentional" guess this entry
  originally had: `archive/db/crud.py`'s `list_all_page_slugs()` (feeds
  `/sitemap.xml`) selects every `MeetingPage` slug with no
  `platform != "unknown"` filter, while `meeting_page.html` deliberately
  `noindex`es exactly those `generic_fallback` (`platform == "unknown"`)
  pages. Full write-up and fix direction now in `BACKLOG.md`, right after
  the existing 2026-08-12 Search Console entry.
- **"Page indexed without content" — likely resolved by PR #136's
  empty-page exclusion (shipped 2026-08-17, same day as this finding);
  not confirmed done, needs a Search Console re-crawl to confirm the flag
  actually clears.** `meeting_page.html`'s transcript text is confirmed
  server-rendered (verified 2026-08-14, see "SEO / LLM-discoverability"
  above), which rules out the obvious client-side-render explanation for
  `/m/*` pages specifically. The plausible shape was a real meeting with
  neither transcript nor agenda items rendering as a genuinely thin
  page — title, date, video embed, no real text body. This file's own
  "Agenda/minutes PDF text extraction" section already documents exactly
  this shape on a real page: the Napa City Council/Housing Authority
  case, which today "has literally nothing describing what was discussed
  beyond the raw video and a bare link." This bullet originally framed
  the fix as a choice between "exclude truly-empty pages from the
  sitemap" and "just a handful of real thin meetings that improve as
  caption/agenda coverage grows" — `BACKLOG_DONE.md`'s "Empty
  ('zero-value') meeting pages excluded from browse/sitemap/feed" entry
  (PR #136) built the former: pages with no video, no agenda, and no
  transcript version (17 of ~1,200 live at the time) now get `noindex`ed
  and excluded from `/meetings`, the sitemap, and the feed at query time
  (`_is_empty_page_condition()` in `archive/db/crud.py`, the noindex meta
  tag in `archive/templates/meeting_page.html`), and that entry
  explicitly names this Search Console finding as the target. Still not
  confirmed as the actual page(s) Search Console flagged — just the
  closest known real example of the shape that would produce this
  symptom, and the auth-walled Search Console dashboard itself hasn't
  been re-checked. See `BACKLOG.md`'s matching ClerkBase-theory
  `[HUMAN]` entry, which already carries the same "closes on recrawl with
  no further code change, if the flagged URLs turn out to be this shape"
  caveat.
- **"Page with redirect" — application code ruled out (same 2026-08-17
  second-pass run), still open on the real cause.** Its own separate
  alert, received 2026-08-16, one day before the other two. Grepped both
  `app/` and `archive/` for anything redirect-issuing
  (`RedirectResponse`/`redirect_slashes`/3xx status codes): the Archive
  service — where `/m/*` meeting pages actually live — issues no
  redirects anywhere in its own code. The only `RedirectResponse` in the
  whole repo is `app/main.py:1370`, the *resolver* service's unrelated
  root-path fallback, nothing to do with meeting pages. So if real `/m/*`
  URLs are genuinely redirecting, it isn't this app's code — most likely
  a host/DNS-level canonicalization redirect (bare domain → `www`, or
  HTTP → HTTPS), which Search Console can flag informationally even when
  it's intentional and harmless. Real remaining candidate if it's *not*
  that: `MeetingPageUrlAlias`-driven redirects, if alias (not canonical)
  slugs somehow ended up in the sitemap. Needs the report opened to see
  which URLs are actually affected before guessing further — flagging
  this one as a genuine question for the user rather than a hypothesis,
  since there isn't yet enough signal to reason from.
