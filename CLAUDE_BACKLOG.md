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
`BACKLOG_DONE.md`'s entries dated 2026-08-07/08 for the full writeups). This
file now holds only the 6 still-open ones.

## Reliability / engineering health

- **Adapter health canary / synthetic monitoring.** A scheduled job that
  re-resolves ~1 known-good sample URL per platform on a timer and alerts
  (email to Ryan, or a Slack webhook) on failure. Given how many real
  breakages have already surfaced this way — Mountain View's redirect bug,
  YouTube's caption-fetch blocking, yt-dlp being an unpinned moving target —
  better to find out from a canary than from a user's dead link. Still the
  highest-value remaining item: the test suite protects against
  *regressions* on known-good cases, but won't catch a government site
  changing its page structure out from under a working adapter, which is how
  every real breakage so far has actually been found.
- **Error monitoring (Sentry or similar)** in both the resolver and Archive,
  beyond the current `logger.error` calls — production exceptions currently
  only surface if someone happens to check Render logs. A smaller,
  complementary piece of the same reliability gap as the canary above.

## Growth mechanics

Ties directly to the app's stated growth mechanism: shareable deep link →
organic growth (see `BACKLOG.md`'s roadmap intro and the newsletter/GA
items).

- **Social share previews with an image.** ~~No `og:image` or
  `twitter:card` at all~~ — partially shipped 2026-08-14: YouTube-backed
  pages now unfurl with the video's real `i.ytimg.com` thumbnail (see
  `BACKLOG_DONE.md`'s "VideoObject.thumbnailUrl + Clip key moments"
  entry). **Still open, the original idea's real remainder**: mp4/m3u8
  pages (the majority) still render as bare text cards, and a
  *generated* branded share-card (jurisdiction + meeting title + maybe a
  quoted transcript line) would beat a raw video frame even where the
  thumbnail now exists — overlaps with "Quote-clip sharing" below.
- **Quote-clip sharing.** Let a user select a transcript excerpt and
  generate a shareable image/card of that quote + timestamp + a link back
  to that exact moment — a much stronger viral unit than a bare link, and
  journalists/advocates already do this manually with screenshots.
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

- **A real example URL under the paste box on the landing page.**
  Proposed by the user (2026-08-10): plain text (deliberately not a
  clickable link — the point is to model "paste this into the box
  above," not tempt a visitor to click through and leave), e.g. "For
  example: paste this into the box above:
  `https://jaxcityc.granicus.com/player/clip/7447?redirect=true&view_id=1`".
  A first-time visitor landing on a bare paste box with no context has
  to already know what kind of URL this tool wants — a real, working
  example removes that guesswork immediately, and ties directly into
  the growth mechanism this section is about (a visitor who
  successfully resolves something on their first try is far more likely
  to share the result). Open questions before building: one fixed
  example vs. rotating through a few (a rotating set could double as
  implicit "look how many platforms we support," but adds real
  complexity — a template pick, cache-busting concerns — for a first
  pass); whether it should link to a currently-live, well-known meeting
  (Jacksonville) or something more universally recognizable; and whether
  copy should explicitly say what the visitor will get (video + real
  transcript) so the example also sets expectations, not just
  demonstrates the paste action.

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

- **ISO-8601 timezone on `uploadDate`.** Second half of the same Search
  Console alert (flagged as non-critical). Real per-adapter time-of-day
  capture is a bigger, multi-adapter lift — `BACKLOG.md`'s WCAG-markup
  research entry found only Portland.gov actually exposes real
  time-of-day among 7 real government sites checked, so it won't be
  available broadly. Cheaper interim option: emit `date + "T00:00:00Z"`
  instead of a bare date string, at the cost of not being literally
  accurate — flagging the tradeoff rather than deciding it here.

**Tier 2 — solid, low-cost, template-only:**

- **`<link rel="canonical">` on `/meetings` and `/coverage`.** Neither has
  one today despite `public_base_url` already being a Jinja global. Without
  it, `/meetings`' seven independent query params (`q`, `jurisdiction`,
  `date_from`, `date_to`, `fuzzy`, `has_agenda`, `has_transcript`) create
  real duplicate-content surface area. Canonicalize every filtered variant
  to the bare unfiltered URL.
- **`Event` JSON-LD alongside the existing `VideoObject`** on
  `meeting_page.html` — `name`/`startDate`/`jurisdiction` are all fields
  already on the page, a meeting genuinely is an `Event`.
- **`<meta name="description">` on `app/templates/index.html` and
  `about.html`.** Currently empty on both — `base.html` defines
  `{% block meta %}{% endblock %}` but neither homepage nor about page fills
  it in, despite both being real indexable pages.

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
- **Semantic `<time datetime="...">` on visible transcript/agenda
  timestamps** (currently plain `<a>`/`<span>` text like `[12:34]`). Cheap,
  template-only, and directly mirrors the WCAG-driven pattern `BACKLOG.md`'s
  own accessibility-standards research already found valuable on
  Portland.gov — applying the same discipline to this site's own markup.
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

- **Jurisdiction hub pages (`/j/{slug}`).** A server-rendered per-city/
  county landing page ("Oakland City Council meetings — video,
  transcripts, deep links") listing that jurisdiction's archived
  meetings, built over the same `list_pages()` query `/meetings`'
  jurisdiction filter already runs — the new work is a stable URL,
  page copy, `<title>`/meta-description, and sitemap inclusion, not new
  querying. Targets the "[city] council meeting video/transcript"
  searches future users type today, and doubles as the hook page for
  city-specific outreach (stronger than linking a filtered `/meetings`
  URL). Foundation is real: transcript text is confirmed server-rendered
  on `/m/*` pages (`archive/templates/meeting_page.html:328`, verified
  2026-08-14), so these pages sit on genuinely indexable surface. Open
  questions before building: slug scheme, given stored jurisdiction
  strings are still messy (see `BACKLOG.md`'s open casing/no-state
  items — a hub page per raw string variant would fragment instead of
  consolidate); minimum-meeting-count threshold before a hub page
  exists (a one-meeting "hub" is thin-content risk); and whether hub
  pages join `sitemap.xml` immediately or after a corpus-growth pass
  gives them real content.

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
