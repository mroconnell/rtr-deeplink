# rtr-deeplink

A deliberately lean rebuild of the video+transcript+deep-link feature from
`rtr-transcripts` (the round-1 "Red Tape Recordings" MVP). No background
job queue — given a meeting URL, resolve its video and transcript on
demand and render them together. There's now an optional database
(`app/db/`) for caching resolves and admin reporting, added deliberately
narrow in scope to avoid reintroducing round 1's Mongo/NextAuth
complexity — it holds no user-facing state today, and the app still works
with zero persistence if it's unset or unreachable. See README's
"Caching and reporting" section for how it works.

**Accounts shipped 2026-08-11 and are live in production** — Clerk-based
sign-in plus saving meetings/searches to your own account, see README's
"Accounts (Clerk)" section for the full architecture. Round 1's mistake
was building full auth/accounts *before validating the core deep-link
feature*, not that accounts themselves were wrong — this repo's own
phase-1 accounts work only started once the core resolve/transcript/
Archive features were already built, tested, and live, and even then
stayed deliberately narrow (accounts + saved items only, via Clerk rather
than a hand-rolled session system, holding zero user PII in this app's
own database). See `ACCOUNTS_PLAN.md` for what's still ahead (profiles,
saved-search alert emails, billing) — split out of `BACKLOG.md`
2026-08-22, which keeps a stub entry under "Roadmap & strategy" — and
`BACKLOG_DONE.md`'s "Clerk production cutover" entry for the real
incidents hit switching from a Clerk development instance to production —
worth reading before ever touching Clerk env vars/DNS again.

**See `README.md` for architecture, the resolve flow, supported platforms,
and frontend features**, and **`STATE_HUB_PAGES.md` before touching
`/state/*` or `/j/*`** — it carries the design reasoning, the
tried-and-rejected list with measurements, a tuning table, and the
future-work ranking for those two surfaces. This file covers conventions and context specific
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
  As of 2026-08-08 it has at least one fresh, verified sample for every
  supported platform (rows ~68-77 on the "Sample Meetings" tab) — good
  starting points for caption-parsing work specifically: Dublin CA
  (Swagit, real transcript + agenda together), Boston/Lee's Summit MO
  (Legistar, one clean success + one full-fallback-chain case), Fountain
  Valley CA (Granicus via CivicPlus — also a real edge case: transcript
  genuinely garbled at the source, language misdetected as Portuguese as
  a result; video was missing until the 2026-08-08 fix for
  MediaPlayer.php pages that only embed a legacy Flash/RTMP player — see
  BACKLOG_DONE.md), Whitehall OH
  (CivicClerk, agenda-only), Calgary AB (eScribe, video but no captions
  yet). eScribe's populated-captions gap closed 2026-08-18: Peel Region,
  ON (`pub-peelregion.escribemeetings.com`, real "Regional Council"
  meeting, iSiLIVE video) resolves with 1101 real caption segments, zero
  warnings — add it to the sample sheet alongside the row above.
  CivicClerk's own version of the same gap is still real and unconfirmed
  either way, not addressed by this. Vimeo (added 2026-08-21, WO-29) is
  a deliberate, documented exception to "find a real caption sample
  first": its video half was built against 8 real jurisdictions, but
  captions genuinely cannot be fetched server-side at all — the signed
  config that holds them 403s every non-browser client — so that adapter
  ships video-only and says so, rather than waiting on a sample that a
  plain HTTP client will never be able to reach. Good starting samples:
  Salisbury NC (`vimeo.com/1212025580`, real captions visible in the
  player), Chicago IL (`chicityclerkelms.chicago.gov/Meeting/?meetingId=
  DF5C52EA-0D6B-F111-A823-001DD8019941`).
- **The same rule applies to a *caption-shape* fix, not just a new
  adapter — and one platform's real file is not enough.** WO-34
  (2026-08-21) fixed roll-up ("scrolling ticker") caption duplication,
  which had been shipped for YouTube alone. Every one of the other three
  platforms that serve it turned out to have a structurally different cue
  shape, and each one broke a rule that looked correct against the files
  already in hand: Granicus drops words off the *front* of the window,
  CivicClerk promotes the previous line inside the same cue, eScribe
  overlaps by a single word. Fixing it against fewer real files would
  have produced a fix that silently did nothing on the others — twice the
  detection heuristic scored a genuinely-broken real track *under* the
  threshold. Add these to the sample sheet: Tacoma WA
  (`cityoftacoma.granicus.com/player/clip/7460`), Antioch CA
  (`antiochca.portal.civicclerk.com/event/18/media`), Essex County ON
  (`coe-pub.escribemeetings.com/Meeting.aspx?Id=eb32e746-242f-4443-804a-fbdeeefc7eeb`),
  Philadelphia (YouTube `5LZqoNDRMYk`). Jacksonville FL
  (`jaxcityc.granicus.com/player/clip/7447`) is the useful negative
  control — same platform, ordinary non-roll-up captions that must come
  through untouched.
- **Verify in-browser, not just via the API.** UI changes especially need
  an actual `mcp__Claude_Browser__*` check — several real bugs (duplicate
  chapter markers, a metadata-extraction ordering bug, a deep-link
  seek-priority bug) were only caught by looking at the rendered page or
  driving it, not by reading JSON responses.
- **Never read `BACKLOG.md` end to end — read its TOC block, then grep
  (WO-41, 2026-08-22).** The file opens with a generated
  `<!-- TOC-START -->`…`<!-- TOC-END -->` block listing every section
  with an entry count and every entry by title. **At session start, read
  only that block.** Each TOC line is a verbatim prefix of a real line
  further down, so pulling up one entry is
  `grep -n -F "<the quoted fragment>" BACKLOG.md` and reading from there;
  a whole section is `sed -n '/^## Ship next/,/^## Needs a human/p'`.
  Reading the whole file is the failure mode this replaced, not a
  thorough version of it — at 4,300 lines nobody did, which is how three
  real user-visible bugs went unread (see the actionability-ordering note
  below; the 2026-08-21 reorder and the 2026-08-22 compaction to ~2,300
  lines were the first two steps, this is the third). **After any edit to
  `BACKLOG.md`, rerun `python3 scripts/build_backlog_toc.py`** — CI
  regenerates and diffs it, so a stale TOC fails the build. Entry titles
  also carry optional secondary effort tags alongside the primary one,
  which is what makes the TOC skimmable for "what can I actually do right
  now": `[EASY]` small code change, `[BIG]` major lift, `[EXAMPLE]` needs
  a real live sample first, `[LOGIN]` needs a dashboard only Ryan has,
  `[WAIT]` blocked on a recrawl or another external event. They're
  discretionary — add one only where the entry itself already establishes
  it, never as a guess.
- **A backlog entry is a lead, not a spec — verify its claims against
  the code and live data before building from it.** Entries are written
  at the moment a problem is *found*, often before it's fully understood,
  and the code moves underneath them. A parallel wave on 2026-08-22 hit
  this five times in one run: **three entries were wrong about their own
  subject** — one named the wrong file, one cited a line number as
  "confirmed via `od -c`" that was wrong anyway, one had a count off by
  **50×** — and **two more described work that was already done**. The
  same day, a separate session found an inbox-triage entry proposing an
  investigation into a bug that had been fixed 22 minutes after the alert
  fired (Sentry `PYTHON-FASTAPI-X` / PR #286), and a "real, current cost
  exposure" entry whose stated 5 GB limit was actually 25 GB. **So:
  before acting on an entry, re-derive its central claim** — open the
  file it names, re-run the count, `git log --grep` the crash site or
  symptom for a fix that already landed, and check the live value behind
  any production assertion. This costs a minute and it is the difference
  between fixing something and fixing nothing. It does not mean
  distrusting the entries — their *reasoning* is usually the most
  valuable thing in the repo — it means the specifics decay and the
  reasoning doesn't. Correct the entry as part of the same pass, so the
  next reader inherits the corrected version rather than repeating the
  check.
- **WO numbers: `git grep -ohE 'WO-[0-9]+' origin/main | sort -t- -k2 -n
  | tail -1`, then take max + 1 — never count + 1.** Check commit titles
  too (`git log origin/main --oneline | grep -oE 'WO-[0-9]+'`): the
  earlier form of this rule grepped `*.md` only, and on 2026-08-25 that
  returned WO-54 while WO-55 was already taken by a merged commit whose
  number never landed in any file — a collision the "against
  `origin/main`" part alone doesn't prevent. The
  sequence has real gaps, so counting existing numbers produces a
  collision every time. **Under a parallel wave this isn't sufficient
  either**: the grep only sees *merged* work, so two agents working
  concurrently both read the same max and both claim the same number.
  When more than one session is running, **the conductor assigns WO
  numbers centrally** and agents use the number they're given rather
  than deriving one. Same root cause as the multi-session working-tree
  rule below — concurrent sessions can't infer shared state from a
  snapshot of it.
- **An open backlog entry carries the *conclusion*; the investigation
  that produced it goes in `BACKLOG_DONE.md`.** `BACKLOG.md` is read
  before deciding what to build, so an entry earns its length only with
  what a builder needs: what's wrong, what to do, what to watch out for.
  The reasoning is genuinely valuable — that's why this repo keeps it —
  but its home is `BACKLOG_DONE.md`, with the live entry pointing there
  in one line. **A `Ship next` item should rarely need 50 lines.** If the
  evidence really is that long, split it: put the investigation in
  `BACKLOG_DONE.md` under a `[Investigated YYYY-MM-DD]` marker (not
  `[Done]` — nothing shipped), and leave the live entry saying what to
  build and why it's worth building.
  **This is measured, not a style preference.** WO-41's compaction took
  `BACKLOG.md` to **2,227** lines on the morning of 2026-08-22. By that
  afternoon it stood at **2,399** on `main`, and a single session of
  real findings took it to **3,009 — +610 in one PR**, with the
  `Ship next` section alone going **105 → 396 lines**. That is roughly a
  third of the morning's compaction eaten back in a day, by entries
  whose *content* was fine and whose findings were worth keeping. That is exactly how the file reached 4,300 lines
  before, and no amount of care about individual entries prevents it,
  because each one looks justified on its own. The TOC protocol above
  makes a long file survivable to *navigate*; it does nothing about a
  long file being slow to *decide* from.
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
  **`BACKLOG.md`'s sections are ordered by actionability, not by
  subsystem (WO-39, 2026-08-21)** — read that file's own header before
  filing into it; it carries the routing rule for which section a new
  entry belongs in. The subsystem buckets it replaced (`Bugs`, `Platform
  coverage`, `Archive roadmap`, `On-demand transcription`) failed
  measurably: four sections held ~79% of a 5,400-line file, mixed open
  bugs with finished work, and hid three real user-visible bugs near the
  bottom until an audit went looking. **Its `Standing decisions` section
  is the one to read before "fixing" anything** — it collects decisions
  already made *against* doing something (declined alerting, filters
  deliberately not widened, overrides to leave alone), which used to sit
  scattered at depths of 500-4,900 lines and got rediscovered repeatedly.
- **A PR that ships a feature must update every doc that named it as
  unbuilt, and the PR description must list which.** `README.md`,
  `BACKLOG.md`, and this file all describe real, current gaps — a PR that
  closes one of those gaps but leaves the doc still describing it as
  future/unbuilt work recreates exactly the kind of doc-drift this repo's
  own `AUDIT_BRIEF.md` (the "App-wide audit" brief) already flagged as a
  real, confirmed problem (see this file's pytest-suite bullet above for one concrete
  instance of it), not a hypothetical one.
- **`CLAUDE_BACKLOG.md` is a separate, unreviewed suggestions list**,
  distinct from `BACKLOG.md`. When asked to brainstorm improvements/
  features rather than record a bug or gap found while working, write them
  there instead of directly into `BACKLOG.md` — it holds ideas the user
  hasn't triaged yet, so they don't get mixed in with `BACKLOG.md`'s
  verified, live-tested findings. Once the user accepts an item from it,
  move it into `BACKLOG.md` proper (in that file's style, with real
  verification) rather than marking it done in place.
- **`CLAUDE_INBOX_TRIAGE.md` is a third, separate staging file — set up
  2026-08-17 — populated by a daily *unattended* scheduled Routine, not
  by an interactive session.** The Routine reads Gmail's `rtr-claude`
  label (Search Console, GitHub Actions failure notifications,
  UptimeRobot, eventually Sentry), reasons about each new item using the
  same standards as everywhere else in this file (chase a real report
  when one's reachable — e.g. GitHub Actions logs, via this repo's own
  API access — reason from the alert text plus real code when it isn't,
  e.g. Search Console's auth-walled dashboard; never guess without
  either), and appends findings there. It deliberately never writes
  directly to `BACKLOG.md`/`CLAUDE_BACKLOG.md`/`BACKLOG_DONE.md` — since
  it runs unattended once a day and opens+merges its own PR with no
  human in the loop, writing into files an interactive session might be
  mid-edit on (see the multi-session bullet below) would risk a real
  collision the dedicated file avoids entirely. A human (or a later
  session, explicitly asked) promotes anything that holds up into
  `BACKLOG.md`/`CLAUDE_BACKLOG.md` proper, same pattern as this bullet's
  `CLAUDE_BACKLOG.md` promotion step, then deletes it from the triage
  file rather than marking it done in place. `render.yaml`'s
  `buildFilter.ignoredPaths` (every service block) excludes all of these
  backlog/triage docs — plus the ledger file below — from triggering a
  Render redeploy, so this auto-merging is safe from a production
  standpoint even with zero human review; see that file's own comment.
  **The Routine dedupes against a repo-side ledger, not a Gmail label
  (WO-33, 2026-08-21).** It holds *no Gmail write scope* — Ryan's
  explicit, permanent decision: an unattended job that merges its own PRs
  shouldn't also be able to write to his mailbox — so `label_thread` and
  the old `label:rtr-claude -label:rtr-claude-processed` query are gone
  for good. Don't propose reauthorizing it. Instead it searches a
  30-day lookback window and filters candidates through
  `CLAUDE_INBOX_TRIAGE_SEEN.txt` via `scripts/inbox_triage_ledger.py`,
  committing the updated ledger in the same PR. Message IDs, not thread
  IDs: Gmail's label semantics are thread-level, which is what made the
  old query unreliable (a thread with one processed and one new message
  still came back). See `CLAUDE_INBOX_TRIAGE.md`'s "Dedupe protocol"
  section and the script's docstring for the reasoning behind the
  window/prune/append-only choices.
- **Don't claim a caption/data path works without a positive example.**
  Several adapters have fields that are schema-verified but not
  content-verified (e.g. CivicClerk's `closedCaptionTracks`, Swagit's
  `#transcript-fragments`) because no real meeting with that data
  populated has been found yet — these are explicitly flagged as
  best-effort in code comments and BACKLOG.md, not silently assumed.
- **Synthetic tests (hand-written HTML/JSON, not fetched from a real page)
  are for exercising one specific logic branch already confirmed against
  real data — never a substitute for the "test against a real URL first"
  rule above.** Reach for one only once the adapter's basic real-page
  parsing is already fixture/live-verified, and what's left to cover is a
  narrower edge case (an ambiguous-name collision, a missing-field
  fallback, a rare error path) that no real example has surfaced yet.
  Building one well means two things: (1) the payload's *shape* should
  reuse a schema already confirmed from a real fixture, never an invented
  field structure; (2) the *facts* inside it must be real and
  independently verifiable even though the page/response itself is
  hand-built — e.g. `test_resolve_fills_in_missing_state_via_shared_lookup`
  (`tests/test_civicclerk.py`) uses "Fresno, CA" because it's a
  confirmed-unambiguous real city, not a fabricated one, and
  `jurisdiction_enrich`'s "Kansas City" test relies on that being a real,
  confirmed-ambiguous KS/MO city, not an assumption. Always comment the
  test as synthetic and note what's still unconfirmed (e.g. "no CivicClerk
  customer with a blank `location.state` has been found yet") — that's
  what lets a later read of the suite tell real-verified coverage apart
  from a plausible-but-unconfirmed one, the same distinction the bullet
  above draws for data paths generally.
- **When a platform turns out to be a wrapper around another** (confirmed
  so far: Legistar and CivicPlus both just link out to Granicus, PrimeGov
  embeds a YouTube video, and Chicago's City Clerk ELMS embeds a Vimeo
  one), delegate rather than writing a redundant native parser — usually via `resolve_via_platform()` in
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
  before assuming it's a bug in this repo's code. **As of 2026-08-21
  (WO-30) there's a second, heavier yt-dlp call surface**: flat *channel
  listings* (`app/platforms/youtube_channel.py`, for the four Legistar
  cities whose recordings only exist on their own YouTube channel).
  Nothing was blocked when it was built, but it's a plausible separate
  block target from the single-video fetch, and it was only ever measured
  from a residential IP, never from Render's — if it starts failing in
  production while working locally, that asymmetry is the first thing to
  check, not the matching logic. Two real, live-measured facts worth
  knowing before touching it: a flat listing returns **no dates at all**
  (every date field is `None`, which is why the matcher parses dates out
  of video titles), and channel extraction is **not lazy** — it
  materializes the whole channel before returning, so `playlistend` is
  load-bearing, not an optimization.
- **We query sites politely — and "politely" means following a host's
  house rules, not avoiding every technical measure they've put up.** A
  realistic `Referer`/User-Agent so a naive hotlink check doesn't
  false-positive us as a bot (Granicus), or yt-dlp's actively-maintained
  handling of YouTube's caption-fetch shape (the bullet above): both are
  compliance, not defiance — the host is asking for a request that looks
  a certain way, not refusing to serve one, and we give it exactly that.
  The line we don't cross is a host's *explicit* human-verification
  gate — a Cloudflare "Verify you are human" challenge (hit live on
  Spokane WA building the Vimeo adapter, WO-29; that adapter ships
  video-only rather than going near it, see `BACKLOG.md`'s Standing
  decisions) — because that's the host saying no automated client gets
  through at all, not asking for a particular request shape. If a page
  is gated behind one, degrade gracefully — skip it and surface a plain
  warning to the *reader* on the page (the existing `transcript_warnings`
  pattern), not just a dev-facing log line.
- **CI runs four gates, and `pytest` is the third — run all four before
  pushing (learned the hard way, 2026-08-23).** `.github/workflows/
  test.yml` runs, in order: `ruff check app/ archive/ worker/ scripts/
  tests/`, `ruff format --check` on the same paths, `python -m pytest`,
  and `alembic check` (twice — once with `working-directory: archive`,
  once with `app`). A green local `pytest` says nothing about the first
  two, and they run *first*, so a lint slip fails the build before a
  single test executes. WO-46 burned a full CI round on exactly this:
  one unused import and six files needing `ruff format`, with 1,640
  tests passing locally the whole time. Run the same four commands
  locally, and when `ruff format` reports files to reformat, **check
  which files first** — formatting one you didn't touch drags an
  unrelated diff into your PR, and under a parallel wave (see the
  multi-session bullet below) possibly someone else's in-progress work.
- **A pytest suite exists now (`tests/`, see README's "Running tests")** —
  run it (`pytest`) before/after touching `app/utils/vtt_parser.py`,
  `app/platforms/media_scan.py`, `app/platforms/base.py`, or any platform
  adapter. Every adapter now has real fixture-backed coverage (see
  README's "Running tests" section for the current, authoritative list —
  this file previously claimed eScribe/PrimeGov/YouTube had zero coverage;
  that was stale as of this correction and is exactly the kind of doc-drift
  this repo's own `AUDIT_BRIEF.md` flags as a real, confirmed
  problem, not a hypothetical one). It doesn't replace live-testing a new
  adapter or a genuinely new real-world case (see the first bullet above)
  — it exists to catch a *previously-covered* case silently regressing
  between sessions, which live-testing alone doesn't protect against. When
  you fix a bug found via live testing, consider adding a fixture-backed
  regression test for it in the same pass, the way the Simi Valley
  Spanish-caption and blank-VTT cases already are.
- **Setting up a fresh local venv from scratch (e.g. a new Mac with no
  prior `.venv`) has two real, confirmed gotchas beyond what "Quick
  start"/"Running tests" describe — both cost real time on 2026-08-21.**
  (1) **Use the same Python minor version CI/render.yaml pin (3.12.x),
  not whatever bare `python3`/`python3 -m venv` resolves to on a fresh
  Homebrew install** — a brand-new Homebrew Python can be far ahead of
  that pin (confirmed: 3.14 on a machine set up that day), and `faster-
  whisper`'s `av` (PyAV) dependency has no prebuilt wheel for a Python
  that new, forcing a from-source Cython build that fails outright
  against it (`brew install python@3.12`, then `python3.12 -m venv .venv`
  — not bare `python3`). (2) **Plain `pytest` doesn't add the repo root
  to `sys.path`, so `import app.*`/`import archive.*` fails in every test
  module** — `.github/workflows/test.yml` already runs `python -m
  pytest` specifically to work around this (its own inline comment says
  so); do the same locally, don't assume bare `pytest` matches CI.
- **A fresh Homebrew-Python venv has an empty default SSL trust store —
  any local script here that uses `aiohttp` needs `os.environ.setdefault
  ("SSL_CERT_FILE", certifi.where())` to run *before* `import aiohttp`
  specifically, not just before that script's first network call.**
  Confirmed live 2026-08-21 (`ssl.create_default_context().cert_store_
  stats()` reported zero loaded CA certs on a brand-new venv) — every
  `aiohttp` call failed with `SSLCertVerificationError`, easy to mistake
  for a real network/DNS problem. The ordering matters because `aiohttp/
  connector.py` builds and caches its default `SSLContext` as a
  **module-level statement**, evaluated the instant `import aiohttp`
  runs, not lazily on first connection — setting the env var afterward,
  even moments before the first real request, is already too late. Real
  incident this caused: `scripts/feed_tier3_auto_transcription.py` got
  this fix applied *after* its own `import aiohttp` line once, and since
  that script advances (consumes) its queue file regardless of per-URL
  outcome, a full batch of 48 URLs got silently dropped from the queue
  without ever reaching Archive — recovered by hand from git history. See
  `scripts/transcribe_backlog_locally.py`'s own module-level fix (right
  before its `import aiohttp`) for the reference example to copy for any
  new script; seven existing scripts already needed the same fix applied
  — see BACKLOG_DONE.md's 2026-08-21 entry for the full list and recovery
  writeup.
- **`archive/db/crud.py` has a `transcript_warnings`-marker convention
  that gates real functionality, not just reporting — a new quality
  marker there needs updating in (at least) three places, not one.** A
  marker constant (`_GARBLED_MARKER`/`_HALLUCINATION_MARKER`/
  `_GRANICUS_TRUNCATION_MARKER`, the last added 2026-08-23) affects
  whether a page counts as "has a good transcript" at all —
  `_has_good_transcript()`/`find_auto_transcription_candidate()`/
  `list_transcription_backlog_candidates()` all skip a page that has one,
  meaning a warning-marked page **stays permanently un-re-transcribable**
  until its marker is checked somewhere. Update: `_has_real_warning_free_
  transcript()` (the shared Python check — deliberately factored out so
  this is normally the only line that needs touching), `_good_default_
  transcript_exists()` (a *separate* raw-SQL reimplementation of the same
  check, used by the cloud worker's own candidate search — doesn't call
  the Python helper, has to be updated by hand), and, if the new marker
  deserves its own bucket rather than folding into an existing one,
  `_classify_page_outcome()` + `_OUTCOME_LABELS`/`_OUTCOME_RANK` (the
  `/internal/transcript-quality-audit` reporting — see the 2026-08-23
  `truncated_transcript` bucket, kept separate from `garbled_transcript`
  since "content missing" and "content wrong" are different problems for
  a reader). `tests/test_transcription_jobs.py`'s `test_has_good_
  transcript_treats_*_as_not_good` tests exist specifically to catch the
  SQL predicate and the Python helper disagreeing — add a matching case
  for any new marker.
- **Every Archive schema change needs an Alembic migration — and that's
  all it needs (WO-10, landed 2026-08-17).** For `archive/`: write the
  migration in `archive/alembic/versions/` (see `archive/alembic/README.md`
  for how), and `render.yaml`'s `preDeployCommand: cd archive && alembic
  upgrade head` runs it *before* the new build starts serving — no shell
  step, no human in the loop, and a failed migration cancels the deploy
  and leaves the old build running. `archive/db/engine.py`'s
  `init_models()` is a **no-op on Postgres** now: `create_all()` runs
  only for the local/test SQLite path, so a model change without a
  migration fails loudly in prod instead of half-working — and CI runs
  `alembic check` against a fresh migration-built SQLite on every PR
  (`.github/workflows/test.yml`), so it fails *before* merge. This
  replaces the earlier guidance that "a brand-new table needs no manual
  migration because `create_all()` runs at startup": that convenience was
  precisely what let `alembic_version` drift silently and produced four
  incidents (2026-08-09/10/13, and the 2026-08-17 `UndefinedColumnError`
  outage when a model column deployed ~13 minutes ahead of its
  `ALTER TABLE` — see BACKLOG_DONE.md). Two rules that follow: **never
  reference a new column in code the same deploy it's added unless the
  code tolerates its absence** (the `search_tsv` feature-detect pattern in
  `crud._fts_available()` is the model — either order deploys safely),
  and **a generated/computed column beats "column + backfill script"**
  when Postgres can compute the value (no ingest change, no one-time
  script, no seam). **The resolver (`app/`) is now on the same footing,
  as of 2026-08-21 (WO-24)**: its `create_all()` is a no-op on Postgres,
  CI runs a second `alembic check` with `working-directory: app`, and
  `render.yaml` carries `preDeployCommand: cd app && alembic upgrade
  head` for the resolver service too. So both services now get the same
  guarantee — a schema change without a migration fails before merge,
  and migrations run before the new build serves traffic.
  `GET /admin/schema-info` (the resolver's port of the Archive's
  `/internal/schema-info`, same admin-token gate as every other
  `/admin/*` route) reports its real reflected columns and
  `alembic_version` without needing shell access.
  **A stale premise worth knowing about, since it survived in these docs
  for ~11 days:** they claimed the resolver's Alembic history "has never
  been stamped in prod" and that a one-time manual `alembic stamp` on the
  Render shell was the blocker. That was wrong. The first real call to
  `/admin/schema-info` (2026-08-21) returned `alembic_version:
  a9207c0eb761` — already at head, `schema_matches_models: true`, zero
  mismatched tables. Nobody had recorded the stamp. The lesson isn't
  about Alembic: **when a doc asserts a fact about production that
  nothing in the repo can verify, build the read-only endpoint that
  answers it before acting on the assertion.** Two sessions nearly
  opened a Render shell to run a destructive-ish command against a
  premise that a single `curl` disproved.
  **If you ever do need to stamp this history: name the literal revision
  (`a9207c0eb761` today), never the word `head`** — `head` was the
  baseline when older docs said "stamp head", a second revision landed
  2026-08-15, and that silently turned the advice into the same shape as
  the 2026-08-09 Archive incident. `app/alembic/README.md`'s runbook has
  the full decision table.
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
- **`render.yaml` can define more than one `type: worker` transcription
  service** (`rtr-transcription-worker` / `rtr-transcription-worker-2`,
  added 2026-08-21 for backlog catch-up) — a distinct service block per
  worker, not `numInstances` scaling on one, since the two need to differ
  in exactly one env var (`AUTO_TRANSCRIPTION_REQUESTER_EMAIL`); see that
  file's own comment on the second block for the full reasoning, and
  `BACKLOG.md`'s matching entry for the residual auto-generation race
  this avoids.

- **This repo is sometimes worked on by more than one session/dev at the
  same time — check before assuming the working tree is yours alone.**
  Real, repeated situation on 2026-08-08: another session was actively
  committing extensive changes (a pytest suite, RSS feed, PWA manifest, a
  transcript language picker, a real bug fix) while this session was
  running in parallel, sharing the same local clone. Concretely: **always
  run `git status` before editing**, and if it shows unrelated
  uncommitted changes that aren't yours, don't touch them — don't stage
  them, don't revert them, don't let them ride along in your commit. If
  you need to land your own change cleanly without disturbing that
  other in-progress work, isolate it: `git worktree add /tmp/some-name
  origin/main`, make your edit there, commit, push (a plain `git push
  origin <branch>` — pushing a differently-named local branch directly
  onto `main` via refspec, or force-recreating a local `main` with `-B`,
  both got flagged by the auto-mode safety classifier; a normal
  `gh pr create` + `gh pr merge --squash --delete-branch` from the
  worktree works reliably instead), then `git worktree remove
  <path> --force` to clean up. If `origin/main` has moved again by the
  time you push (it will, if the other session is active), `git fetch`
  + inspect *what* changed (`git log --oneline main..origin/main`)
  before reconciling — often it's your own already-merged work the local
  branch just hasn't caught up to yet, not a real conflict; `git pull
  --rebase` handles the genuine case cleanly as long as your change and
  theirs touch different regions of the file.
- **A `.claude/worktrees/<name>/` subdirectory silently inherits the
  shared checkout's `.env` if you run either service from inside it
  without setting `DATABASE_URL` explicitly.** Confirmed live 2026-08-17:
  starting `archive.main:app`/`app.main:app` from a worktree with no
  `.env` of its own still connected to the real shared Postgres via
  `asyncpg`, because `archive/main.py`'s/`app/main.py`'s `load_dotenv()`
  calls take no explicit path, so `python-dotenv` walks up from cwd and
  finds the *shared checkout's* `.env` two directories up.
  `load_dotenv()`'s default `override=False` means an explicitly-set
  `DATABASE_URL` in the launching shell command *does* take precedence
  (confirmed by re-running with `DATABASE_URL="sqlite+aiosqlite:///./
  some_file.db"` prefixed on the command) — so **always set
  `DATABASE_URL` explicitly before running either service locally from a
  worktree**; don't assume an unset `DATABASE_URL` means "no database," it
  means "whatever `.env` cwd-walks into." No data was written in the
  original incident (a test query failed with a schema mismatch before
  any write occurred), but the failure mode if forgotten is a worktree
  session silently reading — or writing test data into — a real shared
  database it has no business touching.
  **`DATABASE_URL` is not the only var with this shape — two more were
  confirmed live 2026-08-22 while verifying UI work from worktrees.**
  (1) **`ARCHIVE_BASE_URL` cwd-walks the same way**: a locally-run
  resolver picked up the *production* Archive from the shared `.env`,
  which short-circuited `/api/resolve` into an archive redirect, so the
  resolver's own page never rendered and the "before" measurements were
  silently meaningless. Set it explicitly alongside `DATABASE_URL`
  whenever you run the resolver to look at a page. (2) **Running
  `archive.main:app` standalone serves no stylesheet at all** —
  `base.html` links `/archive-static/style.css`, which only exists when
  the resolver proxies — so an unstyled local page will happily give you
  confident, wrong CSS measurements. Mount it in a scratchpad wrapper
  (no repo change) and re-measure; local then matches production
  exactly. Both cost a full round of bad measurements before being
  noticed, and neither fails loudly.
- **Run any backfill or bulk sweep from the service's Render shell, not
  from your laptop against the production `DATABASE_URL` (real mistake,
  2026-08-23).** `BACKLOG.md`'s Standing decisions already say "never
  run an unbounded scan or bulk workload against the production DB from
  an interactive session" — this bullet exists because that section was
  *read earlier the same day* and the mistake happened anyway, so the
  rule belongs where the scripts are described too, not only there.
  What it looked like: `scripts/backfill_meeting_highlights.py` run
  locally after a `TOPICS_VERSION` bump pulled **every** `segments` blob
  across the network (~1 GB), managed ~7 pages/minute — a **6-hour**
  run — and held production read load the whole time. Run from the
  Render shell it is local to the database, so the same sweep is minutes
  and competes with nothing. Every backfill script in `scripts/` says
  this in its own docstring; believe it. Two properties make stopping
  safe when you notice mid-run, and both are worth preserving in any new
  backfill: **commit per row** (killing leaves a consistent partial
  state) and **skip already-current rows** (so a re-run resumes rather
  than restarting). Locally is still fine against a *seeded local
  SQLite* — that is how the state/hub pages were verified — just never
  against the shared Postgres.

- **Never `grep`/`cat`/`Read` a gitignored file (`.env`, credentials,
  anything matching `.gitignore`) with a pattern broad enough that a
  secret's plaintext value could end up echoed into the conversation.**
  Real incident, 2026-08-11: a `grep -n "DATABASE_URL\|ARCHIVE"` intended
  to check whether `DATABASE_URL` was set also matched `.env`'s
  `ARCHIVE_INGEST_TOKEN=...` line and printed its real value verbatim —
  the sed redaction in place only masked `user:pass@host`-shaped DB URLs,
  not an arbitrary token. Required rotating that token in all 3 places it
  lives (both Render services' dashboards + local `.env`) after the fact.
  If a specific env var's value is genuinely needed, ask the user for it
  directly rather than reading it out of `.env` yourself; if only
  *presence* matters, use a check that doesn't print the value at all
  (e.g. `grep -q '^SOME_KEY=' .env && echo set || echo unset`, or `python
  -c "import os; print(bool(os.environ.get('SOME_KEY')))"` for an
  already-loaded process). Application code loading `.env` via
  `load_dotenv()` at runtime (as `app/main.py`/`archive/main.py` already
  do) is fine — the risk is specifically a shell command whose *output*
  lands in the conversation.

## Related context

The essentials (why this pivot happened, per-platform findings, known
gaps) are captured directly in this repo — `README.md`, this file, code
comments, and `BACKLOG.md` (plus `BACKLOG_DONE.md` for completed items and
`CLAUDE_BACKLOG.md` for unreviewed, Claude-proposed ideas) — deliberately,
so a session opened straight against this repo has what it needs without
depending on anything else.

**Business context lives outside this repo, on purpose.** Admin, planning,
strategy, research, and marketing for Red Tape Recordings are worked on in
`~/Documents/rtr-business` (its own CLAUDE.md, task backlog, and topic
folders, plus a linked Claude.ai Project). Product *roadmap* items still
live here in `BACKLOG.md`'s "Roadmap & strategy" section, next to the
constraints that shape them — that workspace reads them rather than
duplicating them. Keep code work in this repo and business work there; don't
let either drift into the other.

Deeper session narrative (the original round-1 user-testing conversation,
day-by-day investigation detail) lives in Claude Code auto-memory scoped
to `~/Documents/rtr-transcript` — the *original* project directory this
one was spun out of, not this one. A Claude Code session opened at
`~/Documents/rtr-deeplink` (e.g. from VS Code) will *not* auto-load that
memory, since memory is scoped per working directory. It's rarely needed
day to day; if something here references a decision that isn't explained
in-repo, that's where to look, or just ask the user.
