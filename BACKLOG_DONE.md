# Backlog — done

Completed items moved out of [BACKLOG.md](BACKLOG.md) to keep the live
document short. Kept verbatim (not summarized) because the investigation
detail — what was checked, on which real cities, what turned out to be a
non-issue vs. a real bug — is itself useful project memory, not just a
changelog of task titles.

## Site polish

- **[Done 2026-08-10] Built a branded 404 page on both services, plus
  logging when one is hit — the "custom 404 / not-found page, plus an
  error log when it gets hit" ask.** Confirmed neither service had one
  before: every unmatched route fell through to FastAPI's default
  plain-JSON 404, and the one existing branded case (Archive's
  `/m/{slug}` for an unknown meeting page, already using its own
  `not_found.html`) logged nothing.

  Registered a `StarletteHTTPException` handler on both `app/main.py`
  and `archive/main.py` (`not_found_handler`) that intercepts only
  genuinely unmatched routes — confirmed via `grep` that neither service
  ever explicitly `raise`s `HTTPException`, so every existing deliberate
  404 (API/internal endpoints) is a plain `JSONResponse` return, not a
  raised exception, and never reaches this handler; verified this
  directly with a test hitting `/admin/stats` with no token (a real,
  network-free JSON-404 example) and confirming it stays JSON, not the
  new HTML page. For a real 404, both services now log
  `logger.warning("404: %s (referer=%s)", ...)` (the referer is exactly
  the "old bookmark / stale external link" signal that was invisible
  before) and render a matching `not_found.html` — reused the Archive's
  existing template as-is, added a new equivalent for the resolver
  (`app/templates/not_found.html`, linking back to `/`, the resolver's
  actual primary action). Also added the same logging to the Archive's
  existing `/m/{slug}` not-found path, previously silent.

  5 new tests (`tests/test_404_handling.py`): branded-page rendering on
  both services, the warning log firing with the right path/referer,
  the existing API-404 JSON path staying unaffected, and the Archive's
  `/m/{slug}` case now logging too. Full suite: 326 passed (321 + 5 new).
  Live-verified in-browser against local dev servers (resolver proxying
  to a real local Archive instance, matching production's reverse-proxy
  shape): a genuinely unmatched resolver path, a bad `/m/{slug}` proxied
  through to the Archive's own page, and a real valid `/m/{slug}` (to
  confirm the happy path wasn't accidentally caught by the new handler)
  — all three rendered exactly as expected, and both dev server logs
  showed the new warning line firing (including, as a bonus real-world
  confirmation, a genuine browser-requested `/favicon.ico` correctly
  triggering the resolver's handler too).

  Sitemap and the site footer (the other two "site polish" asks from the
  same message) were still open at the time this was written.

- **[Found already done 2026-08-10] Sitemap turned out to already exist
  — the BACKLOG.md entry describing it as unbuilt was stale, not a real
  gap.** Went looking to scope it as its own task and found `GET
  /sitemap.xml` already fully built on the Archive
  (`archive/main.py`/`archive/templates/sitemap.xml.jinja`, backed by
  `crud.list_all_page_slugs()`), proxied through the resolver at the
  same path (matching the `/m/*`/`/archive-static/*`/`/feed.xml`
  pattern, keeping SEO authority on `redtaperecordings.com`), and
  already referenced in the resolver's dynamically-generated
  `robots.txt` (`Sitemap: https://redtaperecordings.com/sitemap.xml`).
  Confirmed live in production, not just in code: `curl`ed
  `https://redtaperecordings.com/sitemap.xml` directly and got a real
  200 with real `<loc>`/`<lastmod>` entries for actual archived
  meetings, and confirmed `robots.txt` really does point at it. No work
  needed — removed the stale bullet from BACKLOG.md rather than leaving
  a "not yet built" note describing something that already works.

- **[Done 2026-08-10] Built a universal site footer with Sitemap/RSS/
  Coverage/Contact links, closing out the last open "site polish" ask.**
  Clarified scope with the user first (real ambiguity, not guessed):
  both services get it (not just the resolver, which already had a
  minimal one), the existing subscribe prompt gets folded into the same
  footer rather than staying a lone paragraph, and the extra links are
  specifically RSS feed, Coverage, and Contact/report-a-problem (the
  user didn't pick "About," so it wasn't added).

  The resolver (`app/templates/base.html`) already had a `<footer>`
  with just the subscribe prompt, conditionally hidden on `/subscribe`
  itself; restructured it into a `.footer-links` nav row (always shown)
  plus the subscribe prompt (still conditionally hidden there). The
  Archive (`archive/templates/base.html`) had no footer at all —
  added the identical structure, matching this codebase's existing
  precedent of deliberately duplicating shared markup/CSS across the
  two services' independent templates (see `archive/static/style.css`'s
  own header comment) rather than building new cross-service template
  sharing infra just for this. CSS (`.site-footer`/`.footer-links`/
  `.footer-subscribe-prompt`) added to both stylesheets identically.

  Contact links to `mailto:ryan@redtaperecordings.com` rather than a
  new contact form or the existing per-meeting "Report a problem" flow
  (which needs a specific meeting URL to POST against, so isn't a good
  fit for a global footer link) — reuses the real forwarding mailbox
  set up earlier the same day (see "Email deliverability" above) rather
  than building new infrastructure.

  Coverage links to a new placeholder page (`GET /coverage`,
  `app/templates/coverage.html`) rather than a dead link — the user
  asked for it in the footer despite the real Coverage page (a public
  sortable jurisdiction/platform table, see "Archive roadmap") not
  being built yet. Built on the **resolver**, not the Archive: the real
  future version will read from `/admin/stats`'s underlying data, which
  lives in `app/db` on the resolver, not `archive/db` — confirmed by
  checking where `/admin/stats` itself is actually defined before
  picking a home for the stub, rather than assuming Archive because
  that's where the sitemap/feed live. `noindex`'d via `head_extra`
  (`<meta name="robots" content="noindex">`) since thin placeholder
  content isn't worth indexing until the real page replaces it.

  5 new tests (`tests/test_footer_and_coverage.py`): the coverage page
  renders and is noindexed, both services' footers carry all four
  links, and `/subscribe` still hides the redundant prompt while
  keeping the footer links. Full suite: 341 passed (336 + 5 new).

  Live-verified in the browser on both services through the resolver's
  proxy (matching production's reverse-proxy shape): screenshotted the
  homepage footer, clicked through to the real Coverage stub and
  confirmed its own noindex tag via `javascript_tool`, confirmed a real
  Archive `/m/{slug}` page (proxied) renders the same footer, and
  confirmed `/subscribe` correctly drops the redundant prompt while
  keeping all four links. One real tooling mixup caught immediately, no
  lasting effect: a first screenshot attempt landed on a stray
  `file://` tab the edit-preview hook had auto-opened for one of the
  edited templates, not the actual local dev server — caught from the
  tab context (`file://.../base.html`, raw unrendered Jinja syntax
  visible) and corrected by explicitly re-selecting the real
  `localhost:8010` tab before continuing.

## Email deliverability

- **[Done 2026-08-10, verified live against the real Resend API] Built a
  real one-click unsubscribe mechanism across every email
  `archive/utils/email.py` sends, and started the `noreply@` →
  `ryan@` sender-address migration.** Prompted directly by the user: "can
  we add an unsub link to the footer of all our resend emails?" plus,
  separately, a link to Resend's own deliverability docs flagging
  `noreply@` addresses as a real sender-reputation risk.

  `archive/utils/email.py` gained `_unsubscribe_footer_html(to)`, which
  builds a real link to a new `GET /unsubscribe` route — injected
  centrally inside `_send()` (`html = html + _unsubscribe_footer_html(to)`)
  so all four existing `send_*()` functions get it automatically, rather
  than each one needing to remember to add it. Returns `""` (no footer)
  when `PUBLIC_BASE_URL` isn't set, since local dev has no real public
  URL to build a working link from.

  The actual unsubscribe route lives on the **resolver**
  (`app/main.py`), not the Archive — matching `/confirm-transcription`'s
  existing precedent, since the resolver owns the public domain a plain
  email-link click needs to work from, and already has its own Resend
  credentials (`/api/newsletter/signup`). Refactored that route's inline
  POST logic into a shared `_resend_audience_upsert(email, *,
  unsubscribed)` helper, reused by the new `GET /unsubscribe` route (new
  template `app/templates/unsubscribed.html`). No login or confirmation
  step, matching CAN-SPAM's one-click requirement.

  Initially added a mirror-image `unsubscribe_contact()` function
  directly to `archive/utils/email.py`, then recognized it would never
  actually be called (the real unsubscribe write happens via the
  resolver's own `_resend_audience_upsert()`, a separate service with
  its own credentials) — removed before it became dead code, and
  `_unsubscribe_footer_html()`'s docstring was corrected to describe
  where the real route actually lives.

  Testing needed new ground: `tests/aiohttp_mock.py`'s existing
  `mock_session()` only ever patched `.get()`, and a grep of the whole
  suite found no existing `.post()`-mocking pattern at all — every
  Resend call in this codebase (`_send()`, `_resend_audience_upsert()`,
  `upsert_audience_contact()`) is a POST. Rather than extend the shared
  mock helper, each new test file (`tests/test_email_unsubscribe.py`,
  `tests/test_unsubscribe_route.py`) monkeypatches a small local fake
  `aiohttp.ClientSession` directly, scoped to just that test — simpler
  than generalizing a shared helper for a pattern used in exactly two
  files so far. 12 new tests total: footer generation (empty when
  unconfigured, real link when configured, trailing-slash and
  special-character URL handling), `_send()`'s footer-injection
  guarantee (verified by capturing the real POST payload), the
  `/unsubscribe` route's full matrix (missing/malformed email, Resend
  success/failure/unconfigured), and `_resend_audience_upsert()`'s own
  HTTP-calling logic directly. Full suite: 319 passed (307 pre-existing
  + 12 new), no regressions.

  Live-verified end-to-end, not just via mocks: started the resolver's
  dev server locally against the real (gitignored) `.env`, which holds
  real production `RESEND_API_KEY`/`RESEND_AUDIENCE_ID` credentials (the
  user's own established local-dev-against-prod workflow, confirmed
  pre-existing, not something started this session) and hit
  `GET /unsubscribe?email=ryan@example.com` in the browser — confirmed
  the real page renders ("You're unsubscribed", the email echoed back)
  and that it made a real Resend API call (see BACKLOG.md's note on the
  resulting test contact left in the real audience — harmless, flagged
  for visibility). The footer-injection guarantee inside `_send()` was
  verified via a mocked-POST unit test rather than sending a real email
  to a real inbox, to avoid live-spamming anyone during verification.

  Changed local `.env`'s `RESEND_FROM_ADDRESS` from
  `Ryan <noreply@ally.redtaperecordings.com>` to
  `Ryan <ryan@ally.redtaperecordings.com>`. Confirmed via a real DNS
  lookup (`dig MX`/`dig NS`) that neither `redtaperecordings.com` nor
  `ally.redtaperecordings.com` has any MX record today, and that the
  domain's nameservers are Namecheap's default
  (`dns1/dns2.registrar-servers.com`) — matching the user's own
  "not sure, I think it's just resend" read when asked.

  Follow-up the same day: the user asked directly who a reply to a
  Resend email would reach, and asked for it to forward to
  `ryan@how-to-adu.com`. `ally.redtaperecordings.com` itself turned out
  to have no MX of its own — the only MX in that zone was on
  `send.ally.redtaperecordings.com` (`feedback-smtp.us-east-1.amazonses.com`),
  Resend's own SES bounce-handling record, unrelated to receiving real
  mail. That record is what made Namecheap's simplified "Redirect Email"
  widget report "Your domain is using other email service" when the
  user first tried it directly on `ally` — a false positive from a
  record one host down, not a real conflict, but confirmed live that
  Namecheap's wizard doesn't distinguish. Switching Namecheap's
  domain-wide "Mail Settings" dropdown to "Email Forwarding" was also
  ruled out live: the preview after switching showed only a bare SPF TXT
  record and no MX at all, meaning `send.ally`'s existing MX had already
  dropped out of view pre-save — too risky to save blind given it could
  have deleted Resend's real bounce-handling record for the whole zone,
  not just added forwarding.

  Landed on two changes instead, both confirmed working live, not just
  in theory:
  1. **Code**: `_send()` (`archive/utils/email.py`) now sends a
     `reply_to` field (confirmed via Resend's own API docs that this is
     a real supported field, string or array) read from a new
     `RESEND_REPLY_TO_ADDRESS` env var, independent of
     `RESEND_FROM_ADDRESS`. Lets the visible From stay on `ally` (the
     subdomain Resend has actually verified for sending — its DNS was
     never touched) while replies route to the root domain instead. 2
     new tests (`tests/test_email_unsubscribe.py`) confirm `reply_to` is
     included when configured and omitted when not. Added to both
     `.env.example` files and `render.yaml` (`sync: false`, matching
     `RESEND_FROM_ADDRESS`'s existing pattern) for both
     `rtr-deeplink-archive` and `rtr-transcription-worker`.
  2. **DNS**: rather than Namecheap's own forwarding wizard, set up free
     forwarding via **ImprovMX** instead — a decoupled service that only
     needs 2 MX records + 1 SPF TXT record added manually (while staying
     in Namecheap's "Custom MX" mode the whole time), so the existing
     `send.ally` MX record was never at risk. Records added at host `@`
     on `redtaperecordings.com`: `MX mx1.improvmx.com` (priority 10),
     `MX mx2.improvmx.com` (priority 20), `TXT "v=spf1
     include:spf.improvmx.com -all"`. Discovered mid-setup that
     Namecheap splits Advanced DNS into two separate sections — MX
     records go under "Mail Settings" (grayed out for other types while
     Custom MX is selected), while the TXT record needed the separate
     general-purpose "Host Records" section instead. `ryan@redtaperecordings.com`
     → `ryan@how-to-adu.com` set up as an alias in ImprovMX (plus a
     wildcard catch-all ImprovMX created by default). Verified twice,
     independently: once in ImprovMX's own dashboard (all three DNS
     checks green/"Active"), and again directly via `dig MX`/`dig TXT
     redtaperecordings.com` from this session, confirming the exact
     records live in real DNS, not just ImprovMX's cached view of them.

  **Closed out 2026-08-10, same day**: user set both env vars
  (`RESEND_FROM_ADDRESS=Ryan <ryan@ally.redtaperecordings.com>`,
  `RESEND_REPLY_TO_ADDRESS=ryan@redtaperecordings.com`) on all three
  Render services — `rtr-deeplink-archive` and `rtr-transcription-worker`
  as expected, plus `rtr-deeplink` (the resolver) too. The last one was a
  real surprise: `rtr-deeplink`'s code never reads
  `RESEND_FROM_ADDRESS` (confirmed via grep — it only calls Resend's
  audience-contacts endpoint, which needs no From address) and the var
  isn't declared in that service's `render.yaml` block either, so
  assumed it wasn't configured there — but the user had it set directly
  in Render's dashboard anyway (real drift between the manifest and
  actual dashboard state, from whenever they first set the resolver's
  Resend vars up). Updated there too for consistency, harmless either
  way since it's unused in that service's code. Saved without a redeploy
  (not urgent) — Render only applies env var changes on the next
  deploy/restart, so the old `noreply@` value is still what's actually
  in use by the Archive/worker processes until that happens next.

## Search

- **[Done 2026-08-10] Fixed quoted phrase search on `/meetings` —
  reported directly by the user, confirmed against the real code before
  fixing, not guessed.** `archive/utils/search.py`'s `matches()` used to
  split a query on whitespace with no quote-awareness at all, so
  `"data center"` became two literal terms, `"data` and `center"`,
  quote characters glued on — since real transcript/agenda text never
  has a literal `"` stuck against a word, this guaranteed zero results,
  not a graceful "quotes ignored" fallback. Confirmed directly before
  building anything: `matches('"data center"', ...)` on a corpus
  containing "a new data center project" returned `False`, while
  `matches('data center', ...)` (no quotes) on the same corpus returned
  `True`.

  Also clarified something the user's own description was close on but
  not quite exact about: unquoted multi-word search
  (`all(term in corpus for term in terms)`) was, and still is, **AND**,
  not OR — a corpus missing either word entirely returns `False`. It
  just never required the words to be *adjacent*, which is what likely
  read as looser/OR-like (a match where "data" is in the title and
  "center" is three paragraphs into the transcript was, and remains, a
  hit for the unquoted case).

  New `_parse_query()` splits a query into `(phrases, words)` —
  `"quoted phrases"` (`_PHRASE_RE = re.compile(r'"([^"]*)"')`) are
  extracted first and required as one continuous adjacent substring
  match (reusing the same plain-substring mechanism single-word exact
  matching already used, just applied to the whole phrase); the
  remainder is split into words as before, each still required
  independently (AND). Phrases are **always** matched as an exact
  literal substring, even when `fuzzy=True` — phrase-level fuzzy
  matching (an adjacent run of near-matching words) is a meaningfully
  harder problem than what was asked for, and quoting is itself a
  reasonable signal the caller wants a literal match. `find_snippet()`
  checks phrases before unquoted words within each candidate text, so a
  phrase match wins the highlighted snippet when both would otherwise
  match. An unclosed quote (e.g. `"data center` with no closing mark)
  isn't a syntax error — `_PHRASE_RE` simply doesn't match it, so the
  stray `"` character rides along as part of whatever word it's glued
  to, same "that one term won't match" behavior as before this fix,
  just scoped to the single malformed term instead of guaranteeing the
  whole query returns nothing.

  Deliberately did **not** build a full advanced-search query language
  (explicit AND/OR/NEAR operators) — also asked about directly by the
  user, and explicitly declined for now: `search.py`'s own docstring
  already flags this whole approach as deliberately naive, "fine at
  today's scale... not meant to scale past a few hundred [meetings],"
  and a real boolean-operator grammar is more machinery than that scale
  justifies. The phrase-quote fix alone covers the concrete case that
  was actually hit.

  Added a small `.subtitle` hint line under the search box on
  `/meetings` (`archive/templates/meeting_list.html`) — `Tip: put a
  phrase in "quotes" to match it exactly, e.g. "data center".` — since
  the feature would otherwise be entirely undiscoverable; no existing
  UI anywhere mentioned quote support.

  14 new tests (`tests/test_archive_search.py`, 21 total in that file):
  adjacent-vs-non-adjacent phrase matching, unquoted behavior unchanged,
  a phrase combined with an unquoted word, a missing phrase failing even
  when its individual words are both present, case-insensitivity, the
  unclosed-quote fallback (doesn't crash), an empty `""` phrase being
  ignored rather than becoming a stray literal token, snippet
  highlighting the full phrase, phrase-over-word snippet precedence, and
  phrase matching staying exact even with `fuzzy=True`. Full suite: 336
  passed (326 + 14 new, plus 4 pre-existing search tests already
  covered exact/fuzzy word behavior unaffected by this change). One
  real near-miss caught while writing tests, not left in: the regex
  originally required `[^"]+` (one or more chars), so a literal `""`
  (empty quotes) didn't match the phrase pattern at all and fell through
  as a stray 2-character literal token instead of being cleanly ignored
  — switched to `[^"]*` (zero or more) so it's captured and filtered by
  the existing `if p.strip()` check like any other whitespace-only
  phrase would be.

  Live-verified end-to-end in the browser, not just via unit tests:
  ingested a real test meeting locally with two segments — one with
  "data center" adjacent, one with "data" and "center" both present but
  *not* adjacent ("...the data collected showed the community center
  needs repairs") — through the actual `/internal/ingest` endpoint (not
  a direct DB write), then drove the real `/meetings` search UI through
  the resolver's proxy (matching production's reverse-proxy shape).
  Confirmed `q="data center"` finds the meeting and highlights exactly
  `<mark class="search-match">data center</mark>` (the phrase, not just
  one word), and that `q="community data"` (present but non-adjacent in
  the seeded text) correctly returns zero results — the phrase
  requirement is real, not just passing in isolated unit tests.

  Caught and corrected a real mistake mid-verification, no lasting
  harm: initially started the local Archive dev server without
  overriding `DATABASE_URL`, which fell back to the real production
  Postgres URL from `.env` — but that's the *resolver's* production
  database (confirmed earlier the same day during the `/meetings`
  outage investigation above), not Archive's. `init_models()` runs
  `create_all()` unconditionally on startup, so this could in principle
  have tried creating Archive's tables in the wrong production
  database — confirmed via a direct `information_schema` query,
  immediately after noticing the mistake, that the table list was
  unchanged (still just `alembic_version`/`meeting_resolutions`/
  `problem_reports`, no `meeting_pages` or anything else new). No
  writes occurred; the only request made before catching this was a
  read-only `/api/health` check. Restarted with an explicit absolute
  `DATABASE_URL=sqlite+aiosqlite:///<repo-root>/archive_dev.db` before
  doing anything further.

## Incidents

- **[Resolved 2026-08-10] Live production outage: `/meetings` 500ing on
  both services, caused by the pending `video_warnings`/`agenda_link`
  migration (see "Bugs" below) never having been applied — no longer
  hypothetical once a fresh Archive deploy actually ran the code
  expecting those columns.** Reported directly by the user ("our
  /meetings page is currently not loading"). Confirmed root cause before
  touching anything: `curl`ing the Archive service directly (not through
  the resolver's proxy) also 500'd while `/api/health` stayed fine,
  isolating it to `MeetingPage` queries specifically;
  `archive/db/models.py` confirmed to declare `video_warnings`/
  `agenda_link` as real ORM-mapped columns (added in `fb9ae9e`, before
  this session's current thread) — any query against that model,
  including `list_pages()` (which backs `/meetings`), was always going
  to try selecting columns that didn't exist yet in the real production
  table.

  Real mistake caught mid-fix, no actual harm done: initially believed
  local `.env`'s `DATABASE_URL` could be used to run the migration
  directly against Archive's real production database (having real
  production credentials sitting in a local, gitignored `.env` for
  exactly this kind of local-dev-against-prod work is this repo's
  established pattern) — but a direct query confirmed that database only
  has `alembic_version`/`meeting_resolutions`/`problem_reports` (the
  *resolver's* own `app/db` tables), no `meeting_pages` at all. The
  resolver and Archive use two separate real production Postgres
  instances, each with its own `DATABASE_URL` set independently in
  Render's dashboard (`sync: false` in `render.yaml` for both) — local
  `.env` only ever had the resolver's. Caught before any write was
  attempted (only read-only `alembic current` and an
  `information_schema` query were run against the wrong database) — an
  initial hypothesis about the two services sharing one physical
  database and clobbering each other's `alembic_version` tracking was
  raised, then retracted once this was confirmed: they're genuinely
  separate databases, so that specific risk doesn't actually exist.

  Real fix: user ran the exact commands already drafted in BACKLOG.md
  from the `rtr-deeplink-archive` service's own Render Shell (real
  prod credentials, no separate URL needed) — `alembic current`
  confirmed `8e7cf3b20f86` first, `alembic upgrade head` ran the real
  `ALTER TABLE meeting_pages ADD COLUMN` DDL
  (`8e7cf3b20f86 -> 76a4a2820a2b`), `alembic current` confirmed
  `76a4a2820a2b (head)`. Verified independently, not just trusting the
  Shell output: `curl`ed both `https://rtr-deeplink-archive.onrender.com/
  meetings` and `https://redtaperecordings.com/meetings` directly,
  confirmed 200 on both.

- **[Resolved 2026-08-10] Root-caused a real, recurring problem the user
  had separately noticed: Render service plans kept silently reverting
  to `free` after being manually upgraded in Render's dashboard.**
  `render.yaml` is a Render Blueprint, and Render reconciles every
  Blueprint-managed service (including its `plan:`) to match this file
  on every Blueprint sync — which fires automatically on every push to
  `main` by default. `render.yaml` had `plan: free` hardcoded for both
  `rtr-deeplink` and `rtr-deeplink-archive`
  (`rtr-transcription-worker`'s `plan: standard` was already correct and
  unaffected), so any manual dashboard upgrade survived only until the
  next push — and this session alone had already pushed 5 commits by the
  time this came up, meaning it had almost certainly been reverting
  repeatedly and recently, not as a one-off. Not a Render bug — the file
  genuinely was out of date with a decision that had only ever been made
  in Render's dashboard, never reflected back into the repo.

  Fixed by declaring the real intended plan (`starter`) for both
  services directly in `render.yaml`, and added a top-of-file comment
  explaining the Blueprint-sync mechanism and instructing that every
  `plan:` (and, implicitly, anything else Blueprint-managed) needs to
  stay in sync with decisions made in chat or the dashboard — a
  dashboard-only change will keep getting silently undone otherwise.
  User independently re-upgraded `rtr-deeplink-archive` in the dashboard
  first in order to get Shell access to run the migration above (real
  evidence that Render's Shell feature itself may require a paid plan,
  not available on `free`) — the `render.yaml` fix here is what stops
  that specific service from reverting again on the next push.

## Bugs

- **[Done 2026-08-11] Fixed `GranicusAssetFinder._fetch_agenda_items()`
  silently discarding its own PDF-fallback link when `AgendaViewer.php`
  redirects to a *raw binary* PDF, instead of the HTML/Google-Docs-preview
  PDF the existing Berkeley/Paradise Valley AZ fallback path was built
  for.** Found live while bulk-ingesting Napa's City Council/Housing
  Authority/Measure G Granicus channel (`view_id=12`, clip 3470 and 34
  others) via `scripts/bulk_ingest.py` — every single one came back with
  `agenda_items=0` and no fallback warning either, unlike Napa's Planning
  Commission channel (`view_id=2`) resolved earlier the same session,
  which got real agenda items. Root cause: `response.text()` on a raw PDF
  raises `UnicodeDecodeError`, which was being caught by the same blanket
  `except Exception: return [], None` guarding real request failures
  (bad status/connection error) — so a 200 response with a real,
  fetchable agenda on it was treated identically to "the request itself
  failed," discarding `final_url` along with it. Fix (`app/platforms/
  granicus.py`): capture `final_url` before attempting the text read, and
  catch `UnicodeDecodeError`/`LookupError` from `response.text()`
  separately, returning `([], final_url)` — the same fallback shape the
  Berkeley/Paradise Valley case already produces. Verified live against
  the real Napa clip (agenda_items still `[]`, since there's genuinely no
  timestamped structure to parse, but `transcript_warnings` now correctly
  links the real PDF instead of saying nothing) and added a
  fixture-backed regression test (`tests/test_granicus.py`,
  `test_agenda_viewer_redirect_to_raw_pdf_surfaces_as_fallback_link`,
  using a new `FakeResponse(text_raises=...)` param in `tests/
  aiohttp_mock.py`) so this doesn't silently regress. Does **not** change
  whether these 35 meetings get ingested — they still have no transcript
  (blank captions) and no parseable chapter data, so `/api/resolve` and
  `bulk_ingest.py`'s existing "only push real content" gate correctly
  skips them either way; this only fixes what gets surfaced to a user who
  resolves one of these URLs directly instead of losing the agenda link
  entirely.

- **[Done 2026-08-10, verified end-to-end locally] Built real
  `video_warnings`/`agenda_link` support on the Archive, replacing the
  generic stand-in message shipped earlier the same day.** Corrected a
  real mistake in this item's own earlier BACKLOG.md phrasing along the
  way: it referenced `agenda_warnings`, a field that existed only
  briefly in an earlier session and was deliberately replaced by
  `agenda_link` (a raw URL, not a pre-formatted sentence) before
  anything else in the codebase started depending on it — confirmed via
  a real grep (zero occurrences of `agenda_warnings` anywhere in the
  current code) before building anything, not assumed from the stale
  note.

  Two new nullable columns on `MeetingPage`
  (`archive/db/models.py`): `video_warnings` (JSON list) and
  `agenda_link` (text). `IngestRequest` (`archive/main.py`) gained both
  fields (previously silently dropped by Pydantic on every ingest,
  since `MeetingPage` had nowhere to put them).
  `crud._find_or_create_page()` stores them with the same truthy-gated
  "keep fresh, don't blindly overwrite" semantic `agenda_items` already
  uses — deliberately not an unconditional overwrite, since a partial
  ingest payload that omits these fields entirely (e.g.
  `scripts/fetch_youtube_transcripts.py`'s transcript-only push)
  defaults to `[]`/`None` via Pydantic, and an unconditional overwrite
  would silently wipe a real warning/link a fuller earlier resolve had
  found.

  New `archive/utils/render_warnings.py` (`render_warnings_html()`) is
  the server-side Jinja2 equivalent of `shared_static/deep_link.js`'s
  `linkifyWarning()` + `player.js`'s `renderWarnings()` phrase-button
  behavior — the Archive renders warnings server-side, not via client
  JS, so it needed its own version, registered as a `warnings_html`
  Jinja2 filter (`archive/main.py`, wrapped in `Markup` so a template
  call site doesn't also need `|safe`). Applied to the existing
  `transcript_warnings` spots (previously plain `|join(" ")`, no
  linkify/button behavior at all) and the new `video_warnings` spot
  (replacing the "No video available for this meeting." stand-in when
  real warnings exist, falling back to it only when they genuinely
  don't). `agenda_link` renders as its own "We think we found an agenda
  here: `<link>`" line under the Agenda heading — the section's own
  gating condition changed from `page.agenda_items` alone to `(page.
  agenda_items or page.agenda_link)`, so the heading now appears even
  for a meeting with only a link and no real per-item timestamps,
  matching the original design intent ("own heading, not nested under
  Transcript"). `.source-guess` CSS (the deliberately-not-`.warnings`-
  styled treatment for "we think we found this" lines) mirrored from
  `app/static/style.css` into `archive/static/style.css` — didn't exist
  there before, since the Archive never had this kind of line at all.
  `archive/static/meeting_page.js` gained `wireTranscribeInlineTriggers()`,
  called before the early `if (!wrapper) return` in its
  `DOMContentLoaded` handler on purpose — the no-video case (no
  `#videoWrapper` at all) is exactly the case most likely to have the
  transcribe-request phrase in its warning text, and that early return
  would otherwise skip wiring it entirely.

  7 new tests (`tests/test_render_warnings.py`): escaping, linkifying,
  the transcribe-button wrap (case-insensitive), multi-warning joining,
  empty-list handling, and a real defense-in-depth check (escape-then-
  linkify order means injected markup in a warning string can never
  smuggle a fake link past the escaping). Migration
  (`76a4a2820a2b_add_video_warnings_and_agenda_link_to_.py`) generated
  correctly by diffing against a database first brought to the *current*
  head (`8e7cf3b20f86`), not a fresh empty one — confirms it's a real
  incremental `ALTER TABLE`, not an accidental second baseline. Verified
  upgrade/downgrade both work cleanly, and diffed the resulting schema
  against a fresh `create_all()` build: identical except column
  order (SQLite's `ALTER TABLE ADD COLUMN` always appends at the end
  regardless of where the model declares a field — a real, harmless,
  already-established pattern from every previous migration in this
  session, not a new concern). Local `archive_dev.db` (the repo-root
  file, not `create_all()`-built) stamped at `8e7cf3b20f86` then
  upgraded for real to pick up both new columns, confirmed real existing
  data (1 row) survived intact.

  **Caught two of my own mistakes while doing this, both self-corrected
  before they became real problems**: (1) generating the migration
  against a fresh empty database first, which would have produced a
  second incorrect baseline instead of an incremental diff — caught by
  reviewing the generated file by hand before trusting it, redone
  correctly against a database first brought to head. (2) Running
  `alembic` commands from inside `archive/` without an explicit
  `DATABASE_URL` twice in a row, which resolves the default relative
  `./archive_dev.db` path relative to *that* directory instead of the
  repo root — created a stray empty `archive/archive_dev.db` file (and,
  separately, an `app/dev.db` one from earlier `app/alembic` testing);
  both caught by checking file sizes/schemas before trusting them,
  neither ever touched the real data.

  Full live end-to-end verification, not just unit tests: ingested a
  real test meeting with both fields populated against a local Archive,
  viewed the rendered page through the resolver's proxy (port 8010, not
  the Archive directly on 8020 — hitting it directly 404s on
  `/archive-static/*`, the same pre-existing quirk noted earlier this
  session) — confirmed the real `video_warnings` text renders (not the
  generic stand-in), the real `agenda_link` renders as an actual
  `<a target="_blank">` under its own Agenda heading, and — the part a
  pure server-render check can't prove — clicking the inline transcribe
  phrase actually reveals the transcribe form (`form.hidden` flips from
  `true` to `false`), confirming `wireTranscribeInlineTriggers()`'s
  click wiring genuinely works, not just that the button element exists
  in the DOM. Full suite green throughout (307 tests, up from 300).
  Production still needs the real migration applied — left as a live
  `BACKLOG.md` item with the exact command, not run blind.

- **[Done 2026-08-10, confirmed in production] Built `app/alembic/`,
  mirroring `archive/alembic/`'s existing structure and conventions
  exactly, closing the gap that caused the same day's earlier
  `/admin/stats` production incident.** `env.py`/`script.py.mako` are
  near-identical adaptations (s/archive/app/ throughout — same
  `DATABASE_URL`-from-the-app's-own-engine pattern, no separate config to
  keep in sync). Generated the baseline migration
  (`ee8f7ff76fb3_baseline_schema.py`) by autogenerating against a
  genuinely empty SQLite database, same method `archive/alembic`'s own
  baseline used — correctly includes both existing tables
  (`meeting_resolutions`, `problem_reports`) with every current column,
  including the two (`archive_pushed_at`, `archive_push_attempts`) that
  caused the incident this closes.

  `alembic>=1.13` was missing from the root `requirements.txt` entirely
  — only `archive/requirements.txt` had it, since only the Archive
  service's own deploy had ever needed to run `alembic` commands from
  its Render Shell before. Added to the resolver's own `requirements.txt`
  too, or `app/alembic/` would exist in the repo but not actually be
  runnable in the resolver's production shell.

  Verified locally, same method `archive/alembic/README.md` already
  established: `alembic upgrade head` against a fresh empty SQLite
  database, diffed against a separate `create_all()`-built database —
  identical except the `alembic_version` bookkeeping table itself and
  the same cosmetic `(CURRENT_TIMESTAMP)` vs `CURRENT_TIMESTAMP`
  default-clause rendering difference already documented as harmless on
  the Archive side; `alembic downgrade base` cleanly drops both tables
  back to just `alembic_version`. Also stamped the local `dev.db` file
  at this new baseline (it already had the correct schema from the same
  day's earlier manual `ALTER TABLE` fix, confirmed before stamping, not
  assumed) — `dev.db` is gitignored, so this only fixes this one
  machine's copy; a fresh clone starts from a genuinely empty `dev.db`
  via `create_all()`, which needs no migration at all.

  **Production adoption completed the same day**, via the user's own
  Render Shell run of `app/alembic/README.md`'s documented sequence:
  `alembic current` printed nothing first (confirming the expected
  "schema correct, bookkeeping never started" state, not assumed),
  then `alembic stamp ee8f7ff76fb3` — bookkeeping-only, no DDL, since
  production's schema already matched this baseline exactly (fixed by
  hand earlier the same day) — brought it to `ee8f7ff76fb3 (head)`.
  Independently re-confirmed via `GET /admin/stats` against real
  production immediately after: `pending_archive_pushes: 0`, no error,
  same clean state as before the stamp. Unlike `archive/alembic`'s
  original adoption (which needed a real `stamp` + `upgrade` because
  production was genuinely missing a whole table), this one only ever
  needed the bookkeeping-only `stamp` — matches this repo's
  now-twice-learned lesson (Archive's own Alembic incident, then this
  same day's `app/db` one) to verify real current state before trusting
  any account of it, including this one.

- **[Done 2026-08-10, found and fixed against real production data]
  `get_pending_archive_pushes()`'s sweep query could silently miss real
  candidates.** Found while manually clearing the pending-push backlog
  the schema-fix incident (entry above) left behind — not a hypothetical,
  a real production symptom: `/admin/sweep-pending-pushes` returned `0`
  retried while `/admin/stats`' unfiltered `pending_archive_pushes` count
  still showed `10`. Root cause: the query over-fetched with
  `.limit(limit * 3)` at the SQL level, then filtered by
  `_worth_pushing()` (checks `resolved_payload["agenda_items"]`, JSON,
  not filterable portably at the SQL level) in Python afterward.
  Production genuinely has plenty of `status="success"` rows with no
  real content (`blank_transcript`/`no_video` outcomes are still
  `"success"` at the DB-status level) — when enough of those sit ahead
  of a real candidate in `created_at` order, the fixed-size over-fetch
  window can exhaust itself on non-candidates before ever reaching a
  row actually worth pushing, silently. Fixed by dropping the SQL-level
  limit entirely and filtering the full matching set in Python before
  slicing to the caller's `limit` — same "personal reporting log, a full
  scan per call is fine for now" reasoning `get_stats()` already uses
  for this table (per that function's own docstring). New regression
  test (`test_pending_pushes_finds_a_real_candidate_behind_many_
  content_free_rows`) reproduces the exact shape (15 content-free rows
  ahead of one real candidate) and was confirmed to actually fail
  against the pre-fix code (temporarily reintroduced the old `.limit(limit
  * 3)`, watched the test fail with the real candidate missing, restored
  the fix) before trusting it as a real regression guard. Verified
  against production itself, not just the test: re-ran the sweep after
  deploying the fix, found and successfully retried all 10 previously-
  hidden rows, confirmed `pending_archive_pushes` reached a genuine `0`.

- **[Done 2026-08-10, fixed live in production] Deploying the durable-push
  fix (entry below) itself broke production `/admin/stats` for a real,
  avoidable reason: `app/db` has no migration tooling, and this was its
  first-ever schema change that wasn't a brand-new table.** Real
  incident, not a hypothetical: added two new columns to the existing
  `meeting_resolutions` table, verified thoroughly against fresh local
  SQLite databases (where `create_all()` correctly creates a table with
  every current column, since there's no pre-existing schema to
  reconcile against) — but never against a database that already had the
  *old* schema, which is exactly production's situation. `create_all()`
  can only ever add new tables, never alter an existing one — the exact
  same wall `archive/db` hit three times before adopting Alembic
  (2026-08-09, see this file's earlier entries), just never hit by
  `app/db` before because it had never needed an `ALTER` until now.
  `/admin/stats` returned 503 in production (`get_stats()`'s full-table
  scan touches the new columns on every row via the ORM, failing on
  "column does not exist"); `/api/resolve` itself kept working (confirmed
  live, twice) because `log_resolution()`'s `INSERT` failure was already
  caught by the existing `safe()` wrapper, silently degrading to the old
  bare-`archive_client.push` fallback exactly as that fallback was
  designed to do — the *feature* was inert, not the *site*.

  Fixed live: gave the user a one-off `ALTER TABLE meeting_resolutions
  ADD COLUMN IF NOT EXISTS ...` (both new columns), run via the
  `rtr-deeplink` (resolver) service's Render Shell — same "Python
  one-liner via SQLAlchemy" pattern as the day's earlier Baltimore/
  Memphis one-off DB corrections, adapted to `app/db.engine` instead of
  `archive/db`. Confirmed fixed: `/admin/stats` returns 200 with the new
  `pending_archive_pushes` field.

  That field then read `30` — alarming at first glance, but explainable
  and not a new bug: every pre-existing row got `archive_pushed_at =
  NULL` by definition when the column was added (Postgres can't
  retroactively know an old push already succeeded), so every
  successful resolve from *before* this session's fix showed up as
  "pending" even though most were already real Archive pages. Manually
  triggered `/admin/sweep-pending-pushes` repeatedly to clear the
  backlog rather than waiting on organic traffic — which surfaced a
  second real bug (`get_pending_archive_pushes()`'s `limit * 3`
  over-fetch heuristic silently missing real candidates behind a run of
  content-free rows, fixed in its own entry above/nearby) before the
  count finally reached a genuine `0`.

  **Real lesson, not just this one incident**: "verified end-to-end"
  against a fresh local database is not the same claim as "verified
  against production's actual current schema" — this repo already knew
  that in the abstract (it's the whole reason `archive/db` has Alembic),
  but the lesson hadn't yet been generalized to `app/db`, which uses the
  identical `create_all()`-only mechanism and was always going to hit
  the same wall on its first real `ALTER`. Worth deciding whether
  `app/db` should get its own Alembic setup now, matching
  `archive/db/alembic/`, so a future column addition here doesn't need
  another live production incident to catch it — logged as its own live
  item in `BACKLOG.md`.

- **[Done 2026-08-10, verified end-to-end] Built the real fix for the
  silent-Archive-push-loss bug: durable push tracking plus an
  opportunistic retry sweep, instead of trusting a bare fire-and-forget
  `BackgroundTasks` call alone.** Closes out the item logged earlier the
  same day (a real LA PrimeGov/YouTube meeting that resolved with 3,101
  real segments but never reached the Archive, leading theory being a
  resolver process restart losing the in-flight background task with
  zero log trace).

  **Design**: reused `app/db/models.py`'s existing `MeetingResolution`
  table (already stores the full resolved payload for every successful
  resolve) rather than a new outbox table — added `archive_pushed_at`
  (null until a push actually succeeds) and `archive_push_attempts`.
  `crud.log_resolution()` now returns the new row's id (`flush()` before
  `commit()`); a new `_push_and_track(resolution_id, payload,
  normalized)` in `app/main.py` wraps `archive_client.push()` (which now
  returns `bool` instead of bare `None`) and marks the row pushed on
  success or records a failed attempt otherwise. Both places that fire a
  background push — the fresh-resolve success path and the cache-hit
  opportunistic-push path — now go through this wrapper instead of
  calling `archive_client.push` directly (the fresh-resolve path falls
  back to the old bare-push behavior only if `log_resolution` itself
  failed, i.e. `resolution_id is None`, since there's nothing to track
  against in that case). `crud.get_cached_resolution()`'s return shape
  changed from a bare payload dict to `{"resolution_id", "payload"}` so
  the cache-hit path has an id to track against too; both call sites in
  `app/main.py` updated.

  **The actual retry mechanism**: `crud.get_pending_archive_pushes(min_age_minutes,
  limit)` finds rows with real content (`transcript_found` or
  `resolved_payload["agenda_items"]`), `status == "success"`,
  `archive_pushed_at IS NULL`, under `MAX_ARCHIVE_PUSH_ATTEMPTS` (5,
  after which a permanently-broken payload stops being retried but stays
  visible), older than a grace period (default 5 minutes — deliberately
  excludes a just-created row, so the sweep never races the normal fast
  path seconds after a response returns). This app has no background job
  queue by design (per CLAUDE.md), so the sweep isn't a real scheduler:
  `_maybe_schedule_push_sweep()` is an in-memory time-gated check fired
  opportunistically at the top of every `/api/resolve` call, the same
  pattern `ARCHIVE_RECHECK_AFTER`'s stale-page recheck already uses —
  fine for a single-instance deploy, not a distributed-lock guarantee.
  New `GET /admin/sweep-pending-pushes` (token-gated, matching
  `/admin/recheck-archive-page`'s shape) triggers and awaits the same
  sweep synchronously, for checking on or forcing it directly.
  `crud.get_stats()` gained a `pending_archive_pushes` count (no
  age/attempts filtering, unlike the retry-candidate query — a
  visibility count should still surface a row past the retry cap) so
  `/admin/stats` finally has something to show for this failure mode,
  directly closing the "even monitoring wouldn't catch this" gap the
  original report identified.

  **Verification**: `tests/conftest.py` now also initializes `app/db`'s
  schema (it shares `DATABASE_URL` with `archive/db`, just never had its
  own tables created in the test fixture before). 18 new tests across
  `tests/test_app_db_crud.py` (grace period, content-free/agenda-only/
  non-success exclusions, max-attempts cutoff, the cache shape change,
  the stats count) and `tests/test_archive_push_tracking.py`
  (`_push_and_track`/`_sweep_pending_archive_pushes` success and failure
  paths via a monkeypatched `archive_client.push`, the admin endpoint's
  token gating and real behavior, the sweep gate not double-scheduling).
  Then a full live end-to-end run, not just unit tests: started the
  resolver pointed at a deliberately unreachable Archive URL, resolved
  the real Baltimore meeting from the original report — confirmed the
  push failure was correctly recorded (`pending_archive_pushes: 1`,
  `attempts: 1`) — pointed the resolver at a real local Archive,
  backdated the row past the grace period, called `/admin/sweep-pending-
  pushes` for real, and confirmed the retry succeeded: the pending count
  dropped to 0 and the meeting genuinely appeared in the local Archive's
  `/meetings` search. Full suite green throughout (299 tests, up from
  281); also fixed the same `load_dotenv()`-as-import-side-effect test
  flake found earlier the same day (see the entry below), this time
  triggered by the new push-tracking test file importing `app.main` —
  moved both `ARCHIVE_INGEST_TOKEN` and `ADMIN_STATS_TOKEN` test
  defaults into `conftest.py` itself (guaranteed to run before any test
  module's own import), a permanent fix rather than patching each
  affected file's import order individually.

- **[Done 2026-08-10] `scripts/fetch_youtube_transcripts.py` now emails a
  report after every real run — every transcript actually added, plus
  a distinctly different alert if the run fails to complete.** Reuses
  the Archive's existing Resend integration (`archive/utils/email.py`)
  rather than building a second one-off implementation — same
  `RESEND_API_KEY`/`RESEND_FROM_ADDRESS` the Archive service already
  has. Two new functions there: `send_youtube_transcript_report()`
  (lists every ingested meeting with a real clickable link built from
  `PUBLIC_BASE_URL`, not the Archive's own internal `ARCHIVE_BASE_URL`
  — plus skipped/failed counts — sent on *every* normal completion,
  even an empty one, so silence itself becomes a signal the daily
  `launchd` job stopped firing rather than reading as "nothing new
  today") and `send_youtube_transcript_failure()` (a different subject/
  shape, sent when the run doesn't complete normally at all — an
  IP-level block aborting mid-run, missing `ARCHIVE_BASE_URL`/
  `ARCHIVE_INGEST_TOKEN`, or any unhandled exception). Recipient
  defaults to `ryan@how-to-adu.com`, overridable via
  `YOUTUBE_FETCH_REPORT_EMAIL`. Titles/slugs/error text are
  `html.escape()`d before insertion, since they ultimately trace back
  to scraped government page content. `--dry-run` sends no email
  either way, matching its existing "preview only" contract.

  The whole body of `main()` now runs under one try/except specifically
  so every real failure mode reaches the alert path, not just the
  already-handled IP-block case — confirmed no regression to the
  existing per-video "failed" vs. fatal-abort distinction (an
  individual video failing to fetch still just shows up in the normal
  report's failed list; only a run that can't complete at all triggers
  the separate alert). Verified for real, not just via the return
  value: called both new email functions directly with real
  `RESEND_API_KEY`, confirmed `True` from both, and a real end-to-end
  script run (fresh local Archive, one queued page, non-dry-run) that
  successfully sent the report as its very last step with no exception.

- **[Done 2026-08-10] `scripts/fetch_youtube_transcripts.py` runs
  automatically once a day now, via a `launchd` job on the user's Mac
  (`scripts/com.redtaperecordings.fetch-youtube-transcripts.plist`,
  checked into the repo for documentation/reinstall, actually installed
  at `~/Library/LaunchAgents/`).** Must run on the user's own machine,
  not Render — the whole reason this script exists is that YouTube
  blocks caption fetches from Render's cloud IP (see the entry below).
  Daily at 9:00am, `RunAtLoad` deliberately `false` so it only fires on
  the schedule (LaunchAgents auto-load at every login, which would
  otherwise add extra runs beyond the intended cadence); if the Mac is
  asleep at the scheduled time, macOS runs it after the next wake rather
  than skipping it. Output goes to `~/Library/Logs/fetch-youtube-
  transcripts.log`. Verified for real: `launchctl load`, then `launchctl
  start` to fire it immediately without waiting for the schedule,
  confirmed the log file was written with the script's real output
  ("Transcript-wanted queue is empty -- nothing to do," correct since
  the one real queued page had just been drained manually). The plist's
  own header comment documents install/test/uninstall commands so this
  doesn't depend on tribal knowledge.

  Also ran the script for real against production for the first time
  (prompted by verifying the new timing output below): the queue had
  exactly one real page waiting — Minneapolis's BHZ committee meeting —
  fetched and pushed successfully, 3,377 real segments with clean
  speaker markers, now live at `/m/city-of-minneapolis-2026-07-07-
  business-housing-zoning-committee`.

- **[Done 2026-08-10] Per-video timing added to `scripts/fetch_youtube_transcripts.py`,
  which surfaced and fixed a real, order-dependent test flake.** User
  asked how long a run would take for several long meetings -- answer
  ("seconds each, independent of meeting length, since this fetches an
  already-generated caption track in one API call rather than processing
  audio") is now printed directly (wall-clock timestamp + per-item
  elapsed + a final total/average) instead of just asserted. While
  verifying the new output, `tests/test_transcript_wanted.py::
  test_transcript_wanted_route_returns_queue` started failing, but only
  when run alongside `tests/test_fetch_youtube_transcripts.py` --
  isolated, it passed. Root cause: that new test file imports
  `snippets_to_segments` from the script for pure-function testing, and
  the script had a module-level `load_dotenv()` call as an import side
  effect -- when pytest happened to collect that file first (alphabetical
  order put `test_fetch_...` before `test_transcript_...`), it loaded the
  repo's real local `.env` (including the real `ARCHIVE_INGEST_TOKEN`)
  into the environment before `test_transcript_wanted.py`'s own
  `os.environ.setdefault("ARCHIVE_INGEST_TOKEN", "test-token")` line ever
  ran -- `setdefault()` is a no-op once a real value already won the
  race, so the test's requests using `Bearer test-token` got a real 404
  against the real token instead of the isolated test one. Fixed by
  moving `load_dotenv()` out of module scope and into the `if __name__ ==
  "__main__":` guard -- the only code path that actually needs real env
  vars (`main()`'s `_base_url()`/`_headers()` calls) already lives behind
  that same guard, so this is a pure side-effect removal, not a behavior
  change for real script runs (re-verified: `--dry-run` against
  production still resolves `ARCHIVE_BASE_URL`/`ARCHIVE_INGEST_TOKEN`
  correctly). `scripts/bulk_ingest.py` has the identical top-level
  `load_dotenv()` pattern but has never been imported by a test file, so
  it was never exposed to this same race -- worth keeping in mind if it
  ever becomes importable too.

- **[Done 2026-08-10, verified end-to-end] Built the YouTube transcript
  recovery pipeline: a "transcript wanted" queue on the Archive plus a
  local residential-IP fetcher script — after a deliberate experiment
  killed the last hope of fetching server-side.** Closes out the
  2026-08-09 "Minneapolis LIMS resolves failing at the YouTube step"
  production incident (degrade-gracefully fix confirmed working in
  production 2026-08-10: the user's own BHZ/6105→6073 tests rendered
  video + LIMS's real metadata/agenda with the transcript honestly
  absent) and replaces that item's open "options for the IP block not
  yet evaluated" tail with a decided, built answer.

  **The experiment (analysis option b5)**: before building anything,
  tested whether YouTube's InnerTube `get_transcript` endpoint — a
  genuinely different endpoint from the already-blocked timedtext URLs
  and yt-dlp's player API — escapes the cloud-IP block. Hand-rolled
  calls failed `FAILED_PRECONDITION` even from a residential IP with
  the watch page's own full `INNERTUBE_CONTEXT`, cookies, and the
  page-embedded `params` (extracted from a real watch page's
  `ytInitialData`); rather than reverse-engineer further, switched to
  `youtube-transcript-api` (the maintained library that already solves
  the current attestation recipe): **locally it works perfectly** —
  1,556 real segments for the real Minneapolis video `YgAu_4xWvGU`,
  including the *human-typed* CC1 track (real `>>` speaker markers),
  not just auto-captions — **and from Render's shell the identical
  call raises `IpBlocked`** (the library's own cloud-provider-IP error,
  run by the user directly). Also re-confirmed in passing:
  `get_video_info` (the classic StackOverflow-era trick) returns HTTP
  410 Gone, and the official Data API's `captions.download` requires
  the video owner's OAuth — neither is a path. Conclusion: fetching
  must happen off-server, full stop.

  **The build**: `crud.list_youtube_pages_missing_transcripts()` +
  token-gated `GET /internal/transcript-wanted` on the Archive — every
  YouTube-backed `MeetingPage` with no `is_default=True`
  `TranscriptVersion` ("no default" rather than "no rows," so a page
  whose only version was demoted as a copied agenda is re-fetchable
  too), returning exactly the identity fields `_find_or_create_page()`
  needs to match the existing page on push (platform, external_id,
  source_url_normalized). `scripts/fetch_youtube_transcripts.py`
  (same shape as `bulk_ingest.py`: local `.env`, `--dry-run`,
  `--limit`, per-item results + totals) drains the queue via
  `youtube-transcript-api` and pushes through the normal
  `/internal/ingest` — idempotent by the existing content-hash dedupe.
  Conversion details that came from the real data: blank timing-padding
  snippets dropped; leading real `>>` becomes the site's `»` marker
  (the existing `normalize_speaker_change_marker()` handles the
  *literal-entity* `&gt;&gt;` case, a different artifact); the whole
  track reuses `normalize_shouting_caption()` for ALL-CAPS CC tracks,
  plus an explicit capitalize-after-`»` pass since sentence-casing
  can't see through the marker prefix. 5s inter-video delay (gentler
  than bulk_ingest's 1.5s — these hit YouTube from the operator's own
  home IP, which the library warns can also get temporarily blocked);
  an `IpBlocked`/`RequestBlocked` aborts the whole run instead of
  burning the queue on identical failures. `youtube-transcript-api`
  added to `requirements-dev.txt` only, deliberately not
  `requirements.txt` — useless on the deployed services' blocked IPs.

  **Verification**: 12 new tests (`tests/test_transcript_wanted.py`:
  queue includes a transcriptless YouTube page / excludes one with a
  transcript / excludes non-YouTube pages / route token-gating;
  `tests/test_fetch_youtube_transcripts.py`: snippet conversion incl.
  blank-drop, marker replacement, de-shout, mid-text `>>` untouched),
  plus a real end-to-end run against a local Archive: ingested a
  transcriptless YouTube page, confirmed it appeared in the queue, ran
  the script for real (real YouTube fetch, 1,555 segments), confirmed
  the transcript landed on the same page (no duplicate), the queue
  drained to empty, and the rendered page shows clean de-shouted text
  with `»` markers — visibly better output than the pre-block scraped
  version of the same video (which has rolling-duplicate lines and raw
  `&gt;&gt;` artifacts). Follow-ups (actually running it against
  production, automating it, the no-captions Whisper fallback) tracked
  as a live BACKLOG.md item.

- **[Done 2026-08-10, verified live] YouTube-embedded meetings' `t=`
  deep link silently landed at 0:00 instead of the requested moment.**
  Reported live by the user on a real Minneapolis LIMS/YouTube meeting
  (`.../meeting?url=https://lims.minneapolismn.gov/MarkedAgenda/BHZ/6073&t=1168`),
  alongside a UX question about whether the "no transcript, but we're
  tracking the playhead" copy was overpromising given the seek didn't
  actually work. Root cause: both `initYouTubeVideo()` (`app/static/
  player.js` and `archive/static/meeting_page.js`) constructed the
  `YT.Player` bare (just `videoId`, cued at 0), then called
  `applyDeepLink()` in `onReady`, which sets `video.currentTime = t` ->
  `ytPlayer.seekTo(t, true)`. That's a well-known YouTube IFrame API
  race: a `seekTo()` issued immediately after `onReady`, before any
  buffering or user interaction, doesn't reliably stick.

  Fix: a new shared `buildYouTubePlayerVars(baseVars)` in
  `shared_static/deep_link.js` folds the current deep-link time in as
  `playerVars.start` (rounded down) at player *construction* time, which
  YouTube treats as part of the initial load/cue itself rather than a
  race-y follow-up call -- both `player.js` and `meeting_page.js` now
  call it instead of duplicating the same inline logic (matches this
  file's whole reason for existing: shared deep-link mechanics kept in
  one place, not copy-pasted twice). `applyDeepLink()` still runs
  unchanged in `onReady` for the line-only case (no `t`) and for
  highlighting the matching transcript/agenda row -- its own `seekTo()`
  call in the `t`-present case is now redundant but harmless, since the
  position is already correctly cued by then.

  Verified two ways: (1) three new `tests_js/deep_link.test.js` cases
  for `buildYouTubePlayerVars` (folds `t` in as `start`, rounds down;
  omits `start` entirely with no `t`; doesn't mutate the caller's base
  object) -- sanity-checked real by temporarily disabling the fix and
  confirming exactly 1 test fails, 25/26 still passing. (2) Live in a
  real browser against local dev servers for *both* pages: the
  resolver's ephemeral `/meeting` page (a fresh, never-archived
  `youtube.com/watch?v=YgAu_4xWvGU` resolve) and the Archive's permanent
  `/m/{slug}` page (a locally-ingested test meeting, reached through the
  resolver's proxy so `/archive-static/*` resolves correctly -- hitting
  the Archive service directly 404s on that path, a known pre-existing
  quirk, not new). Both real rendered `<iframe>` `src` attributes
  contained the requested `start=` value exactly
  (`.../embed/YgAu_4xWvGU?...&start=1168...` and `...&start=2500...`
  respectively) -- direct proof YouTube received the correct starting
  position at construction time, not just a passing unit test. Full
  Python suite unaffected (268 tests, no Python code touched); full JS
  suite green (26 tests, up from 23).

- **[Done 2026-08-10, confirmed in production] Alembic one-time production
  adoption incident: my own instructions, based on a stale doc, pushed
  production's migration bookkeeping backward instead of forward.**
  `archive/alembic/README.md` claimed production had never been stamped
  and gave a fixed recovery recipe (`stamp a8dc5aad7eff` then `upgrade
  head`) to run unconditionally. That claim had gone stale without the
  doc being updated — a real `alembic current` run in the user's Render
  shell showed production was *already* correctly at `8e7cf3b20f86`
  (head) before any of that recipe ran, almost certainly because someone
  had already recovered from the original 2026-08-09 stamp-head incident
  (see that entry) without updating this doc to match. Following the
  stale recipe anyway force-stamped production backward to the baseline
  revision, then the redundant `alembic upgrade head` correctly failed
  with `DuplicateColumnError` on `transcription_jobs.priority` (it
  already existed) — caught immediately, not silently, and no DDL
  actually ran (transactional, rolled back cleanly) — but it left the
  bookkeeping row one step behind reality until corrected.

  Real fix, in two parts: (1) `archive/alembic/README.md`'s one-time
  adoption section rewritten to require running `alembic current` first
  and branching on its actual output, instead of presenting a fixed
  narrative as fact — the doc itself now says explicitly not to trust
  its own account of "what production's state is" without checking.
  (2) The user ran the actual correction from the Render shell:
  `alembic stamp 8e7cf3b20f86` (bookkeeping-only, no DDL) followed by
  `alembic current`, confirming `8e7cf3b20f86 (head)`. Independently
  re-confirmed via the new `GET /internal/schema-info` endpoint (see
  below) hit directly against real production: `alembic_version:
  "8e7cf3b20f86"`, `mismatched_tables: []`, `schema_matches_models:
  true` — the real schema and the bookkeeping now agree, checked two
  different ways.

  **The broader lesson, not just this one file**: a doc's account of
  live infrastructure state is a snapshot from whenever it was last
  written, not a live fact — verify against the real thing before acting
  on it, the same "verify against the real thing" convention this repo
  already applies to adapters and sample data. Directly prompted building
  `/internal/schema-info` (below) so that verification is a real API call
  going forward, not a manual command someone has to run and paste back.

- **[Done 2026-08-10] Added `GET /internal/schema-info` (`archive/main.py`)
  so confirming the Archive's real production DB schema no longer
  requires someone with `DATABASE_URL` access to run `psql`/`alembic`
  commands by hand and paste the output back.** Directly prompted by the
  Alembic incident just above/nearby: a stale doc's account of
  "production has never been stamped" turned out to be wrong, and acting
  on it without checking first caused a real (contained) mistake. This
  endpoint gives a way to check the real, live state directly instead.
  Token-gated the same way as every other `/internal/*` route (bearer
  token matching `ARCHIVE_INGEST_TOKEN`, 404 not 401/403 on a missing/
  wrong token). Reflects actual live columns per table via SQLAlchemy's
  `Inspector` against a real connection, next to what `archive/db/
  models.py`'s `Base.metadata` currently expects, and reports any
  mismatch directly (`mismatched_tables`, `schema_matches_models`) --
  deliberately treats the *actual reflected schema* as ground truth, not
  `alembic_version`'s own bookkeeping row (still reported, as context
  only), since it was exactly that bookkeeping row going stale that
  caused the incident this exists to prevent a repeat of. Three new
  tests (`tests/test_schema_info_endpoint.py`, matching the existing
  `test_correct_language_endpoint.py`'s pattern): missing-token and
  wrong-token both 404, and a real call against the test suite's own
  isolated SQLite DB confirms `mismatched_tables == []` /
  `schema_matches_models is True` when the DB genuinely matches the
  models (which it always does in a `create_all()`-built test DB).
  Documented in `README.md`'s "Permanent pages" section, including that
  this route is deliberately not one of the paths `redtaperecordings.com`
  proxies through (only `/m/*`/`/archive-static/*` are) -- it's only
  reachable at the Archive service's own base URL directly.

- **[Done 2026-08-10] Minneapolis LIMS URLs for any committee other than
  City Council failed with "Could not find a meeting id in this LIMS
  URL," never reaching video/agenda resolution at all.** Reported live
  by the user with a real URL: `https://lims.minneapolismn.gov/
  MarkedAgenda/BHZ/6105` (Business, Housing & Zoning committee). Root
  cause: `app/platforms/lims.py`'s `_ID_RE = re.compile(r"/MarkedAgenda/
  CI/(\d+)")` hardcoded the literal committee code `CI` (City Council --
  the only committee the adapter had been built/tested against, matching
  `tests/test_lims.py`'s own fixture URL) instead of treating that path
  segment as a variable. Confirmed the numeric id is the only part any
  downstream step actually uses -- `json_url = f".../MeetingYoutubeVideo/
  {meeting_id}"` takes just the number, no committee code at all -- so
  the fix is a general `[A-Za-z]+` match on that segment (`_ID_RE =
  re.compile(r"/MarkedAgenda/[A-Za-z]+/(\d+)")`) rather than trying to
  enumerate every real Minneapolis committee code. New regression test
  (`test_resolve_works_for_a_non_ci_committee_code`) resolves the real
  reported BHZ URL end-to-end through the existing mocked fixtures,
  confirming it now succeeds the same way the CI case always did. Could
  not get a fresh live fetch of the real BHZ page directly during this
  session (LIMS's Cloudflare protection blocked a plain `curl`, and the
  in-session browser tool was intermittently unavailable) -- confidence
  here instead comes from the user's own real report (the exact URL and
  exact failure message), plus the fact that no downstream code path
  touches the committee-code letters at all, so broadening the match is
  safe by construction, not a guess.

- **[Done 2026-08-10, confirmed in production] Production incident: the
  `worker` service crashed outright at startup** (`Exited with status 1
  while running your code`, `ModuleNotFoundError: No module named
  'playwright'` — a real Render worker crash log, not a hypothetical).
  Cause: `worker/main.py` imports `app.platforms` for fresh `video_url`
  re-resolution before each transcription chunk, which registers every
  adapter including `LimsAssetFinder`/`SlcAssetFinder` — both import
  `app/platforms/headless_browser.py`, which had a top-level `from
  playwright.async_api import ...`. `playwright` is deliberately absent
  from `worker/requirements.txt` (kept lean on purpose, per that file's
  own comment) — this app/worker requirements split predates the
  playwright-dependent LIMS/SLC adapters, and wasn't reconciled when
  they were added, so just importing `app.platforms` took down the
  *entire* worker process, not just LIMS/SLC-related jobs.

  Fix (`app/platforms/headless_browser.py`): made the playwright import
  lazy (`try`/`except ImportError`, sentinel `None`), so
  `register_all_finders()` always succeeds regardless of whether
  playwright is installed — only a resolve that actually needs a real
  browser now fails, with the same clean `HeadlessBrowserUnavailable`
  message as the missing-binary case, not a whole-service outage.
  Verified locally at the time by simulating a playwright-less import
  environment; **confirmed against the real production deploy 2026-08-10
  per the user** ("worker looks like it was running great all night") —
  no crash-loop, stayed up overnight.

  **Real, deliberate decision, not an accident: the worker will NOT get
  playwright/Chromium added, for now.** The obvious next question —
  "just add it to `worker/Dockerfile` too" — was checked for real
  tradeoffs rather than assumed safe. Measured directly (real Playwright
  launch + a real fetch of the actual Minneapolis LIMS Cloudflare-
  challenge page): Chromium's *own subprocess tree* (separate from the
  Python process, purely additive to total container memory) uses
  ~266MB just launched with no page loaded, ~535MB after actually
  loading that real page. `headless_browser.py` keeps one shared browser
  alive for the whole process lifetime (launched once, reused) — fine
  for the resolver web service, but on this worker the whisper model is
  *also* loaded for the whole process lifetime, so that ~266MB becomes a
  permanent tax on top of it, and a LIMS/SLC job's per-chunk re-resolve
  overlapping with active whisper inference on `standard`'s 2GB plan
  works out to roughly `1421MB (whisper, 900s chunk) + 535MB (Chromium
  mid-fetch) ≈ 1956MB` — only ~92MB under the ceiling, a thinner margin
  than the ~600MB that was already proven too tight once (two real OOM
  crashes) before this same plan was sized. **Decision (2026-08-09):
  leave the gap as-is** — a transcription job for a LIMS/SLC meeting
  fails cleanly (no browser available) rather than risking a third OOM
  crash for a platform combo no real request has hit yet. Per the user:
  revisit as a natural follow-on next time the worker's Render plan is
  upgraded anyway (for this or any other reason) — not worth a dedicated
  plan bump on its own just for this.

- **[Done 2026-08-10] Added the first automated test coverage for
  `shared_static/deep_link.js`'s `t`/`line`/`version` contract — deep
  linking is the entire reason this repo exists, and it had zero
  regression protection before this.** Every prior verification of this
  file's behavior, including the version-mismatch precedence fix itself,
  was manual/in-browser or a throwaway one-off Node script (see the
  deep-link versioning entry above/nearby) — a real regression (`line`
  regaining precedence over `t`, the version-mismatch fallback silently
  breaking) would only ever have been caught by live-testing, same gap
  the Python `pytest` suite already closed on that side.

  New `package.json` (repo root, `type: "commonjs"`) + `tests_js/` — the
  first JS tooling this repo has needed. Uses Node's built-in test runner
  (`node --test`, no test-framework dependency) plus `jsdom` (the one
  real devDependency, needed for `document`/`window`/`URLSearchParams`/
  `history.replaceState`, all of which `deep_link.js` uses directly).
  `tests_js/helpers.js`'s `makeWindow()` loads the real file into a fresh
  `jsdom` window as an actual appended `<script>` element, not
  `vm.runInContext` or `eval()` — deliberately reproducing the same
  "separate classic `<script>` tags share top-level `let`/`const`
  bindings" behavior that mattered when this file was first split out of
  `player.js`/`meeting_page.js` (a plain `eval()` creates its own nested
  lexical scope and would silently misrepresent this). Function
  declarations (`getDeepLinkTime`, `applyDeepLink`, etc.) land on
  `window` this way and are called directly in tests; the module-level
  `let segments` does not (per spec, unlike function declarations,
  `let`/`const` never become properties of the global object) —
  `setSegments()` reaches it the same way real callers do, via a second
  appended `<script>` doing a bare (no `let`/`const`) assignment into the
  shared scope.

  23 tests across `getDeepLinkTime`/`getDeepLinkLine`/`getDeepLinkVersion`/
  `updateUrlParams`/`findActiveSegment`/`highlightSegment`, plus the full
  `applyDeepLink` contract: the same 9 cases originally checked manually
  (t-always-wins-the-seek with a trustworthy line present, version-match,
  version-mismatch-with-t falling back to time-proximity not the stale
  line, version-mismatch-with-no-t leaving playback untouched, no-version-
  on-either-side trusting `line` — including the resolver's page
  specifically, which has no version concept at all even if a shared URL
  happens to carry a stray `version` param). Sanity-checked the suite is
  real, not tautological: temporarily short-circuited the `t`-always-wins
  branch in `deep_link.js`, confirmed exactly the 2 tests exercising it
  failed (21/23 still passing), reverted, confirmed clean 23/23 again.
  `README.md`'s "Running tests" section documents `npm install && npm
  test` alongside the existing `pytest` instructions. `node_modules/`
  added to `.gitignore`; `package-lock.json` committed for reproducible
  installs. Full Python suite unaffected (264 tests, pure test-only
  addition, no application code touched).

- **[Done 2026-08-10, partial] Archive's `meeting_page.html` no longer
  shows a silent empty gap when a meeting has no video at all.** One of
  three real bugs the resolver-side "Live-tested the generic fallback"
  entry (below) found and fixed was an invisible `video_warnings`
  message when no video was found — this mirrors that fix's *spirit*
  server-side, not the full fix. When `page.video_url` is falsy, the
  video column now shows a plain `<div class="warnings">No video
  available for this meeting.</div>` instead of rendering nothing at
  all between the title and the "Report a problem"/"Request Transcript"
  buttons, which previously left a reader guessing whether that gap was
  a bug. **Deliberately not the real fix** — the resolver shows the
  actual, specific per-meeting reason (e.g. "No video link found on this
  Legistar page." or one of `generic_fallback.py`'s tentative "we think
  we found..." messages); the Archive can't yet, because `MeetingPage`
  has no column to store that text in and reaching that requires a real
  Alembic migration + a production DB-access step this session doesn't
  have (split back out as its own live item in BACKLOG.md, along with
  the still-unaddressed agenda-link and transcribe-button-phrasing parts
  of the same original gap). Verified live against the local archive dev
  server (port 8020): POSTed a real `/internal/ingest` payload with no
  `video_url` but real `agenda_items`, confirmed the fallback message
  renders correctly in-browser with no crash, both `#videoColumn`'s
  layout and the existing "Report a problem"/"Request Transcript"
  buttons unaffected. Full suite green (264 tests, no Python logic
  touched — template-only change).

- **[Done 2026-08-10] Viebit/NYCC meetings now resolve `jurisdiction` to
  "New York City, NY" (the city+state format most other platforms use),
  not "New York City Council" (a legislative body name).** Not a
  correctness bug exactly — `LegistarAssetFinder._extract_page_meeting_
  info()` was deliberately extracting the real legislative body name from
  the Legistar page's own `<title>` tag — but the wrong shape for this
  app's convention (Swagit's `f"{city}, {state}"`, PrimeGov's "City of X"
  fix). Took the hardcode option the live item laid out rather than
  trying to generalize "extract the city, not the body name" from a
  single confirmed sample: `ViebitAssetFinder` (`app/platforms/viebit.py`)
  is confirmed used only by NYC Council, so a `_JURISDICTION = "New York
  City, NY"` class constant, set directly on every `ResolvedMeeting` it
  returns, is the narrow, accurate fix — matches this repo's "narrow fix
  until real examples exist" convention (see the `collect_edge_case_urls`
  memory). Setting it in `viebit.py` itself (not `legistar.py`) also fixes the
  Legistar-delegated path for free: `legistar.py`'s primary override
  path does `resolved.jurisdiction = resolved.jurisdiction or
  page_info["jurisdiction"]`, so once Viebit's own resolve() always
  returns a truthy jurisdiction, the Legistar page title's "New York City
  Council" never gets a chance to overwrite it via that `or`. Two
  existing `tests/test_legistar.py` assertions (`result.jurisdiction ==
  "New York City Council"` and `is None`) updated to the new, correct
  expected value; `tests/test_viebit.py`'s real end-to-end NYC Council
  fixture test gained a `result.jurisdiction == "New York City, NY"`
  assertion. Full suite green (264 tests).

- **[Done 2026-08-10] Transcripts no longer show a raw `&gt;&gt;` encoding
  artifact in place of a clean speaker-change marker.** Confirmed root
  cause 2026-08-09: YouTube's own raw auto-caption VTT source contains
  the *literal* 8-character string `&gt;&gt;` as real cue text at the
  start of a new speaker's first cue (not an actual `>` character this
  app was mis-escaping) — this app's rendering was doing the technically
  correct, safe thing with that literal text (escaping the `&` for safe
  HTML output), the ugliness was a display/polish gap, not a correctness
  or security bug. New `normalize_speaker_change_marker()` in
  `app/utils/vtt_parser.py`, called from `parse_vtt()` right after the
  existing `normalize_shouting_caption()` call — matches only the exact
  literal `^&gt;&gt;\s*` prefix (anchored to the very start of a cue's
  text, deliberately not a general entity-decoding pass) and replaces it
  with a real, inert Unicode marker (`»`, U+00BB) instead of stripping
  the "new speaker" signal outright. Placed in the shared `parse_vtt()`
  (used by every platform that funnels through it, not just YouTube's
  own adapter) rather than `youtube.py` specifically, which also settles
  the live item's open "not yet checked whether this shows up on a
  non-YouTube source" question — since the fix lives in the shared
  parser, any source that happens to hit the same artifact is already
  covered without needing a second confirmed sample first. `parse_ttml()`
  deliberately left untouched — TTML/XML text goes through
  `ElementTree.itertext()`, which already resolves real XML entities
  during parsing, so a literal `&gt;&gt;` artifact can't arise there the
  same way. Two new regression tests in `tests/test_vtt_parser.py`: one
  end-to-end through `parse_vtt()` confirming the real YouTube-shaped
  input renders as `» Welcome everyone...`, one directly against
  `normalize_speaker_change_marker()` confirming a mid-text `&gt;&gt;`
  (not at the very start of a cue) is deliberately left untouched, so a
  caption that legitimately mentions an ampersand or angle bracket
  elsewhere never gets a second, unintended round of interpretation.
  Full suite green (264 tests, up from 262).

- **[Done 2026-08-10] `/meetings` results now break the jurisdiction/date
  onto its own line under the title, instead of running inline right
  after it.** `archive/templates/meeting_list.html`'s
  `.calendar-candidate-main` renders the title `<a>` and a
  `.calendar-candidate-date` `<span>` back to back with no separator
  markup — the fix is CSS-only. `.calendar-candidate-date`
  (`archive/static/style.css`) changed from `margin-left: 0.5rem` (an
  inline sibling) to `display: block; margin-top: 0.15rem`, so a reader
  scanning down the page gets one consistent left-aligned jurisdiction/
  date column instead of hunting for it after a variable-length title.
  Deliberately scoped to `archive/static/style.css` only, not mirrored
  into `app/static/style.css` — the resolver's own use of the same
  `.calendar-candidate`/`.calendar-candidate-date` classes
  (`renderCalendarPage()` in `app/static/player.js`) is a different,
  more compact UI (an ambiguous-URL disambiguation dropdown, not a
  spacious search-results page) that the original complaint wasn't
  about; forcing it onto two lines there would just make that dropdown
  taller for no benefit. Verified visually in-browser with a static test
  harness reusing the real stylesheet against the local archive dev
  server (port 8020) — confirmed the date line now sits directly under
  the title on its own line for both a short and a long/wrapping title.

- **[Done 2026-08-10] Transcript/agenda rows now keep a wrapped line's
  left edge aligned under the first line's text, instead of falling back
  to the far-left margin under the timestamp.** User-reported: "do we
  have a backlog item about transcript styling? The fact that the text of
  the captions doesn't all left align to the same margin make it very
  hard to read." `.transcript-segment` (both `app/static/style.css` and
  `archive/static/style.css` — kept in sync manually per the note at the
  top of the latter) switched from plain inline flow to
  `display: grid; grid-template-columns: auto auto 1fr; column-gap:
  0.4rem; align-items: start;` — fixed-width timestamp/button columns
  (`white-space: nowrap` on `.segment-timestamp`, since the grid no
  longer needs a manual `margin-right`), text taking the remaining `1fr`
  column with `min-width: 0` so it wraps within its own column instead of
  overflowing.
  Found and fixed a real edge case while implementing: `renderAgenda()`
  (`app/static/player.js`) and `archive/templates/meeting_page.html`
  both have a second, *single-child* `.transcript-segment` shape — just
  a bare `<span class="segment-text">`, no timestamp/button — used when
  a source (confirmed: several CivicClerk cities' eventBookmarks) reports
  every agenda item at the identical timestamp, since rendering those as
  real clickable per-item links would be misleading. Under the naive
  3-column grid, that lone child would've landed in the first
  auto-sized column (squeezed to a narrow box) instead of the full row.
  Fixed with `.transcript-segment > .segment-text:only-child { grid-column:
  1 / -1; }` in both stylesheets, scoped narrowly enough it doesn't touch
  the normal 3-child case (real `:only-child` check, not a class toggle).
  Verified visually in-browser (`mcp__Claude_Browser__*`, local resolver
  dev server) with a static test harness reusing the real
  `app/static/style.css` covering both shapes side by side: a long
  wrapped transcript line (confirmed second line aligns under "This",
  not under "[12:34]") and a single-child agenda item (confirmed it
  spans the full row width, not squeezed left). Full `pytest` suite
  (262 tests) still green — pure CSS change, no Python logic touched.

- **[Done 2026-08-10] Fixed two real, user-caught data-quality bugs from
  the bulk-ingest batches: a wrong Legistar jurisdiction and a wrong
  Granicus date, plus a genuinely new date source (Granicus's own
  Minutes documents).**

  **Legistar jurisdiction**: Baltimore showed "CharmTV Citizens' Hub"
  (a YouTube channel/uploader name) instead of "City of Baltimore".
  Root cause was two separate bugs stacked: (1) `_extract_page_meeting_
  info()` only ever checked `<title>`, empty on Baltimore's page (unlike
  NYC's, which has the real info there) — but the identical "{jurisdiction}
  - Meeting of {body} on {date} at {time}" text is present in the page's
  own RSS `<link rel="alternate" type="application/rss+xml">` tag, a
  standard Legistar template element, confirmed present regardless of
  whether `<title>` itself is populated. (2) Even once found, the
  fallback path's jurisdiction override (`resolved.jurisdiction or
  page_info["jurisdiction"]`) only ever filled in an *empty* value —
  YouTube's uploader field wasn't empty, just wrong, so it never lost to
  page_info. Flipped the priority in the fallback path specifically
  (`page_info["jurisdiction"] or resolved.jurisdiction` — page_info wins
  outright when available) since Legistar's own official page is more
  authoritative than an arbitrary delegated platform's guess; left the
  primary, long-established `a.videolink` delegation path's own priority
  order untouched, out of caution.

  **Granicus date, wrong not missing**: a real Memphis, TN meeting
  (clip 9789) showed 2023-12-05 when the real date was 2023-12-19 (confirmed
  directly by the user). Root cause: the page's own body text has "V.
  APPROVAL OF PREVIOUS MEETING MINUTES (December 5, 2023)" — a standard
  agenda item referencing the *prior* meeting's date — which body-text
  date parsing grabbed as if it were this meeting's own. Fixed by
  stripping any `(previous|prior|last) meeting ... (parenthetical date)`
  match before date-parsing gets a chance to match inside it (scoped
  tightly to a parenthetical right after the phrase, not a loose
  character window, after an early version's test caught it eating a
  second, legitimate date too broadly). Confirmed via the real page that
  no other date-shaped text exists there at all, so the fix correctly
  turns a wrong date into an honest missing one, not a different wrong
  guess.

  **New date source found live**: investigating a second real Memphis
  clip (10031, "Parks & Environment", date silently missing rather than
  wrong) led to discovering Granicus's own Minutes-viewer feature
  (`MinutesViewer.php?clip_id=...&view_id=...`) — a real, plain HTTP-
  fetchable page (no headless browser needed, unlike the player page's
  own JS-driven "Minutes" tab click) with the real meeting date right at
  the top when a customer has published minutes for that meeting. Added
  `_fetch_minutes_date()`, tried after RSS but before the document-link-
  filename last resort. `allow_redirects=False` deliberately — confirmed
  live that clip 9789 (no published minutes) 302-redirects this same
  endpoint to a raw scanned PDF rather than 404ing; treating any redirect
  as "no minutes available" avoids ever handing binary PDF bytes to
  BeautifulSoup.

  **Real gap in the fix-and-forget flow, caught mid-correction**: neither
  bug's already-published Archive page got fixed by simply re-resolving
  the URL — `archive/db/crud.py`'s "keep page fields fresh" update logic
  (`page.date = payload.get("date") or page.date`) only ever *fills in* a
  previously-empty field, deliberately never clears/overwrites an
  existing (even if wrong) one, to protect against a later bad resolve
  erasing good data. Correcting Memphis's already-wrong date needed a
  direct one-off database correction (run by the user via Render's
  Postgres shell for the `rtr-deeplink-archive` service specifically);
  Baltimore turned out not to need one at all, since the original blank-
  page visit (before the Legistar fix existed) never found a video, so
  nothing had met the "worth archiving" bar to get pushed in the first
  place. The Parks & Environment page's previously-empty date *did* get
  filled in correctly by a normal re-ingest, once `_fetch_minutes_date()`
  gave it something to find.

- **[Done 2026-08-10] Legistar now falls back to a broader link scan when
  its own `a.videolink` pattern finds nothing, extracted into a shared,
  reusable function alongside the generic fallback's identical need.**
  Real user finding: Baltimore's Legistar instance
  (`baltimore.legistar.com`) has no `a.videolink` at all for a real
  meeting — its actual recording is a plain `<a href="https://youtu.be/
  ...">Recording</a>` link sitting in an attachments table, a completely
  different shape than the `a.videolink[onclick="window.open(...)"]`/
  `OpenTelerikWindow(...)` pattern confirmed across Maricopa AZ and NYC.
  Legistar's own adapter claims the domain and gave up with "No video
  link found," never reaching `generic_fallback.py`'s own delegation
  logic (built earlier the same day for the identical class of problem
  on Austin, TX's non-Legistar page).

  Extracted the shared scanning core into `app/platforms/base.py`'s new
  `find_platform_link(html, page_url, *, exclude=frozenset())` — scans
  every `<a href>`/`<iframe src>`/`<video src>`/`<source src>` through
  `detect_platform()`, returning `(url, platform)` for the first real
  match. `generic_fallback.py`'s own `_try_delegate_to_known_platform()`
  now calls this instead of duplicating the scan; `legistar.py` gained a
  new `_try_fallback_video_link()` called only when `_find_video_links()`
  finds nothing, trying a real YouTube link first (`YouTubeAssetFinder.
  extract_video_id(html)` — turns out this already works directly
  against raw HTML text, not just a URL, since it's a `.search()` not
  `.match()`; no new YouTube-specific function needed), then
  `find_platform_link()` for anything else, applying the same page-title
  metadata override (`_extract_page_meeting_info()`) real video-link
  delegation already uses.

  Both callers exclude `"youtube"` from the general scan and rely on
  their own tighter, video-ID-validated check instead —
  `detect_platform()`'s broad `"youtube.com" in netloc` match would
  otherwise false-positive on a bare channel/user link (the real case
  that motivated this exact split when `generic_fallback.py` was first
  built: Aurora, CO's "Watch Us on YouTube" footer icon).

  Verified live end-to-end against the real Baltimore meeting: real
  video plays (YouTube embed), real title/date/jurisdiction
  ("City Council Hearing; October 20, 2025", 2025-10-20, CharmTV
  Citizens' Hub — Baltimore's own Legistar page title didn't match the
  `_PAGE_TITLE_RE` pattern NYC's does, so this correctly fell back to
  YouTube's own real metadata rather than leaving anything blank), and
  2587 real transcript segments, replacing what was previously a page
  with no video and no transcript at all.

- **[Done 2026-08-10] Generic fallback now delegates to any other
  platform this app already supports, found as a plain link on the
  page.** Real user finding: Austin, TX's own council meeting pages
  (`austintexas.gov/council/{date}-reg`) don't embed video at all —
  they link out to their Swagit-hosted recording
  (`austintx.swagit.com/play/{id}/0/`) as a plain `<a href>`, which
  `SwagitAssetFinder` already resolves correctly on its own (confirmed
  directly: real video URL, real title, real date, all correct). Added
  `_try_delegate_to_known_platform()`: scans every `<a href>`/`<iframe
  src>`/`<video src>`/`<source src>` on the page through the same
  `detect_platform()` every URL gets classified by, and delegates to
  that adapter's real `resolve()` on the first match. Checked before
  `media_scan.py`'s generic media-URL scan (a full, real adapter's
  result is strictly richer than a raw `.m3u8`/`.mp4` guess) but after
  the existing YouTube-embed regex (kept as-is, first priority).

  Deliberately excludes `"youtube"` from the delegation scan — already
  handled by the narrower, embed/watch-URL-specific regex checked first;
  `detect_platform()`'s broader `"youtube.com" in netloc` check would
  otherwise also match a bare channel/user link (a real false positive
  confirmed live on Aurora, CO: a footer "Watch Us on YouTube" icon
  pointing at a channel page, not a specific video — would have raised
  inside the delegated `YouTubeAssetFinder.resolve()` since no 11-char
  video ID exists in a channel URL). Any delegation failure (a bad
  match, a `CalendarPageError` from e.g. a Legistar calendar link,
  network errors) is swallowed and treated as "no delegation possible,"
  never allowed to turn an honest "found nothing" into a crash.
  `source_url` is overridden back to the ORIGINAL page after a
  successful delegation (not the delegated platform's own URL), matching
  how LIMS/PrimeGov already preserve their own source_url through a
  YouTube delegation — a visitor who came from `austintexas.gov` should
  never see `swagit.com` as "the source."

  **Real CSS bug caught during live verification, not from a unit
  test**: `.source-guess` (the "we think the video/agenda is here:
  `<link>`" lines, added the previous session) had no `overflow-wrap`.
  A real long unbroken media URL (Swagit's own `archive-stream.
  granicus.com/.../playlist.m3u8` link, no natural break points) rendered
  595px wide inside a 300px-wide left column, visually overflowing 267px
  into the right column and colliding with the Agenda heading's own text
  — confirmed via `getBoundingClientRect()` on the actual rendered anchor
  (`right: 829`, while the right column starts at `left: 562`), not just
  eyeballed from a screenshot. Fixed with `overflow-wrap: break-word` on
  both `.source-guess` and `.source-guess a`.

  Verified live end-to-end against the real Austin URL: real video plays
  (real Austin City Council branding, real 4:51:27 duration), real
  agenda_items with real timestamps render (Swagit's own agenda-viewer
  data, not a guessed link), `source_url` stays the original
  austintexas.gov page, and the long-URL overflow no longer collides
  with the Agenda column after the CSS fix.

- **[Done 2026-08-10] Redesigned the generic-fallback meeting page per a
  detailed user spec, given directly against a real screenshot.** The
  previous pass (see the "Live-tested the generic fallback" entry just
  below) fixed real bugs but kept the declarative/warning-box tone; the
  user wanted the whole unsupported-platform experience to read as
  openly tentative instead. Concrete changes, all in `app/templates/
  meeting.html` / `app/static/player.js` / `app/static/style.css`:

  - A full-width banner ("This government website isn't supported yet,
    so we're going to try our best.") above both columns, plain weight/
    color (reuses `#meta`'s existing `<p>` styling, already full-width
    via `grid-column: 1 / -1`).
  - Left column: the old bold-on-yellow video warning box replaced with
    a plain "We think the video is here: `<link>`" line (or
    "[No video found]"), the "Request Transcript from Audio" button
    unchanged below it.
  - Right column: an "Agenda" heading now always shows for a best-effort
    result (previously only when something was found), with a plain
    "We think we found an agenda here: `<link>`" line (or
    "[No agenda found]") — above "Transcript", not nested under it.
  - Transcript section: the "No transcript to click through... we're
    tracking the playhead" copy (which implied a certainty the app
    doesn't have) replaced with just "Sometimes deep-linking to a
    specific moment works on a site we don't officially support yet, and
    sometimes it doesn't — still worth trying." The live-tracking "0:00"
    readout (which was frozen forever anyway when no video existed to
    track — a real latent bug this replacement also fixes) is replaced
    with a manual timestamp text input + a "Copy link to this moment"
    button that reads the typed value instead of a video adapter's
    current time, wired independently so it works even with zero video.

  **Real design fix caught mid-implementation**: gating all of this on
  `platform === 'unknown'` (the approach used in the previous pass) is
  wrong — `generic_fallback.py` delegates to `YouTubeAssetFinder` when it
  finds an embedded YouTube video (the single most common real outcome),
  and that finder's own `platform` field stays `"youtube"` regardless of
  caller. Added `ResolvedMeeting.best_effort: bool`, set `True` on every
  result this adapter produces (delegated or not), and switched all of
  the new UI's gating to that instead — the previous pass's deep-link
  caveat (built one session earlier) had this exact same latent flaw and
  got fixed retroactively in the same change.

  Also replaced `agenda_warnings: List[str]` (a sentence, added the
  previous session) with `agenda_link: Optional[str]` (a raw URL) — the
  new plain-line UI needed just the link, not a pre-formatted sentence,
  and nothing else in the codebase had started depending on the old
  field yet.

  Verified live against both real test cities from the previous pass:
  Aurora, CO (real video + real agenda link, both lines populated
  correctly, video still plays) and Accomack County, VA's BoardDocs (no
  video/agenda found, both correctly show the bracketed fallback text,
  manual timestamp entry copies a real working deep link). A real CSS
  gap caught in the same pass: `#agendaSection` showing unconditionally
  now exposed `#agendaList`'s empty container as a stray bordered box
  when there were no real `agenda_items` — fixed with `.transcript-list:
  empty { display: none; }`, matching `.warnings:empty`'s existing
  pattern.

- **[Done 2026-08-10] Live-tested the generic fallback against a real,
  never-before-seen city (Aurora, CO's auroratv.org) and fixed three real
  bugs it surfaced.** First real end-to-end test of `generic_fallback.py`
  (built 2026-08-09) against a genuinely unsupported site, per the user's
  own request ("let's test the fallback page you made") — found via a
  live check of the shared sample sheet's "50 cities" tab (BoardDocs
  entries there are explicitly documented as never getting a dedicated
  adapter, guaranteeing the fallback path), then Aurora came from the
  user's own follow-up test.

  **Real bug #1**: Aurora genuinely has a playable video (a real .mp4)
  and real captions (a real .vtt) on the page, but the resolver reported
  neither. Root cause: `media_scan.py`'s `MEDIA_URL_PATTERNS` all require
  a literal `https?://`, but both URLs live inside an inline `<script>`
  JSON blob (a JW Player config) with every `/` written as a JSON-escaped
  backslash-slash — confirmed by fetching the real raw HTML directly.
  Fixed by de-escaping before scanning (see `media_scan.py`'s own
  docstring for the full reasoning on why a blanket replace is safe).
  Verified against the real page: `video_url` now resolves to the real
  `vod.mp4`, and 5310 real transcript segments load from the real .vtt.

  **Real bug #2**: `video_warnings` was silently invisible whenever no
  video was found at all — confirmed live via a real BoardDocs page
  (Accomack County, VA) that genuinely has no video. Root cause:
  `#videoError` (where the warning rendered) is a child of `#videoSection`,
  which itself gets `hidden = true` whenever there's no `video_url` —
  taking the warning down with it even though the warning exists
  specifically to explain *why* there's no video. Fixed by splitting into
  a new, independently-visible `#videoWarnings` for the no-video case;
  `#videoError` stays reserved for genuine native-video/HLS playback
  failures where a video legitimately exists (a real, narrower, different
  case). A prior fix earlier in the same session (the YouTube IP-block
  degrade-gracefully change) had already exercised this exact code path
  with a video present — masking this bug, since it only reproduces when
  there's no video at all.

  **Design gap, not exactly a bug**: the agenda-link message (built
  2026-08-09) was nested under the Transcript heading via
  `transcript_warnings`, which the user correctly flagged as misleading
  (an agenda link isn't transcript-related). Added
  `ResolvedMeeting.agenda_warnings`, a new field mirroring the existing
  `video_warnings`/`transcript_warnings` pattern, rendered under its own
  Agenda heading regardless of whether real `agenda_items` exist.

  **UX improvements, from direct user feedback on a live screenshot**:
  messages mentioning requesting a transcript from the audio were plain
  dead text next to the real button elsewhere on the page — standardized
  the phrasing to a single matchable substring across `generic_fallback.py`
  and the three other adapters with a similar message
  (`civicclerk.py`/`escribe.py`/`granicus.py`'s garbled-transcript case),
  and made that exact phrase a real inline `<button>` triggering the same
  action (`document.getElementById('transcribeToggle').click()`). The
  no-transcript live-playhead panel's hint text now adds a caveat when
  `platform === 'unknown'`, since deep-link reliability there genuinely
  isn't confirmed the way it is on a supported platform.

  Also answered a real design question the user raised: does the
  "Request Transcript from Audio" flow re-check for video/captions
  independently, in case the initial page scan misses something?
  Confirmed yes already, structurally — `/api/transcription/
  check-feasibility` calls the exact same `get_finder(platform).resolve()`
  path as the main resolve, so fixing the shared `media_scan.py` bug
  above fixed both at once; no separate mechanism was needed.

  **Follow-up correction, same session**: the copy shipped in all of the
  above read as confident/declarative ("You can still...", matter-of-fact
  instructions) rather than the open-ended, tentative "hey, we're trying
  our best, this might not work" tone the user had originally specified
  for this exact feature (from the original request that led to building
  `generic_fallback.py` in the first place). Rewrote all four
  `generic_fallback.py` messages and the platform-specific deep-link
  caveat to match: "we think we found...", "might work, or it might
  not...", "we're trying our best" rather than definitive statements —
  caught only because the user asked directly whether their original
  copy suggestion had been dropped, a real reminder that copy tone from
  earlier in a long session can get lost across many intervening fixes.

  **Known residual gap, not yet addressed**: `archive/templates/
  meeting_page.html` and `archive/static/meeting_page.js` render the same
  video/agenda/transcript sections server-side (Jinja2, not this same JS
  render path) and likely have the identical underlying issues (warnings
  nested under the wrong heading, no equivalent of the new
  `agenda_warnings` field) — not yet mirrored, since no `platform="unknown"`
  meeting has ever actually been pushed to the Archive (confirmed via a
  real audit of all 22 archived meetings, see the YouTube-captions
  investigation entry above/nearby). Worth doing before the first such
  meeting actually gets archived, not urgent before then.

- **[Done 2026-08-09] Fixed production incident: Minneapolis LIMS (and
  likely SLC, same underlying cause) resolves failing with Playwright's
  own raw error text shown on the page.** Reported live by the user:
  pasting a real Minneapolis meeting URL showed `BrowserType.launch:
  Executable doesn't exist at /opt/render/.cache/ms-playwright/...`
  verbatim, including Playwright's multi-line ASCII-art box — confirmed
  the exact deployment risk flagged (but not yet verified) when these
  adapters shipped: `render.yaml`'s `playwright install --with-deps
  chromium` build step did not leave a working browser binary where the
  running service looks for it.

  Two real fixes shipped immediately: `app/platforms/
  headless_browser.py`'s `_get_browser()` now self-heals (runs
  `playwright install chromium` in-process on first launch failure, then
  retries once) so a broken/incomplete build step doesn't leave this
  permanently down until a redeploy; and `fetch_via_browser()` now raises
  a short, clean `HeadlessBrowserUnavailable` message instead of letting
  Playwright's own raw error text reach a real visitor's page.

  **That fix's own deploy then failed outright** ("Exited with status 1
  while building your code") — real evidence pointing at `--with-deps`
  specifically: it shells out to `apt-get install` for Chromium's system
  libraries, which needs root/sudo Render's build sandbox almost
  certainly doesn't grant, failing the whole chained build command
  before `pip install`'s own success even mattered. Switched to plain
  `playwright install chromium` (browser binary only, no system-package
  install attempt) — see `render.yaml`'s own comment for the full
  reasoning and the `runtime: docker` fallback if a plain binary download
  turns out not to be enough.

  **Confirmed working 2026-08-09**: the user retested a real Minneapolis
  meeting in production and Playwright launched/scraped successfully —
  the resolve got all the way through the LIMS agenda page and handed
  off a real YouTube video ID before hitting a *different*, later-stage
  failure (YouTube's own anti-bot check, logged as a new active incident
  in BACKLOG.md). That later failure signature is itself the proof this
  fix worked — it couldn't have been reached if Playwright were still
  failing to launch.

- **[Done 2026-08-09] Built auto-idle-time transcription job generation**,
  closing the last open piece of the on-demand-transcription feature —
  the worker no longer sits fully idle when the job queue is empty; it
  looks for a `MeetingPage` missing a good transcript and creates a
  self-generated job for it, so the Archive's transcript coverage grows
  passively instead of only when someone manually clicks "Transcribe."
  Design decided via a real interview (three questions: cooldown
  strategy after a failure, what `requester_email` an auto-job should
  use given the column is required and the worker emails it on
  completion, whether a separate volume cap is needed beyond the
  existing priority system) — landed on: escalating backoff (each
  consecutive failure for the same page doubles the cooldown, capped at
  30 days, matching `ARCHIVE_RECHECK_AFTER`'s existing precedent — a flat
  cooldown or a permanent give-up-after-N-failures cap were the two
  alternatives considered and rejected), a real configured email address
  (`AUTO_TRANSCRIPTION_REQUESTER_EMAIL`) doubling as a lightweight
  completion-email activity digest rather than a new no-email code path
  or a dedicated mailbox, and no separate cap — `PRIORITY_LOW` already
  means a real visitor's request always jumps ahead of self-generated
  work, so a growing backlog of auto-jobs can never block one.

  New pieces: `archive/db/crud.py`'s `find_auto_transcription_candidate()`
  (oldest-archived-first, skips pages with a good transcript or in
  cooldown — a full Python-side scan, deliberately, fine at today's scale
  same reasoning as `/meetings`' own search scan),
  `_in_auto_transcription_cooldown()` (the escalating-backoff math, walking
  back from the most recent job counting *consecutive* failures — an older
  failure before a later "completed" job is stale history, not part of
  the current streak), `create_failed_auto_transcription_job()` (records
  a re-resolve/feasibility failure as a real, already-`failed`
  `TranscriptionJob` row so it enters the same cooldown mechanism a real
  chunk-processing failure uses, rather than a separate "skip list" that
  would need its own schema), and `create_transcription_job()` gained a
  `priority` parameter (previously hardcoded to `PRIORITY_MEDIUM` — the
  only call site until now). `worker/main.py`'s `maybe_generate_auto_job()`
  reuses the exact feasibility-check logic `app/main.py`'s
  `/api/transcription/check-feasibility` has (`probe_duration`,
  `is_plausible_meeting_duration`, both already imported by the worker
  for its own chunk-processing path) rather than duplicating it, and is
  gated in `run_forever()`'s idle branch by both "the queue is completely
  empty" (implied for free once `claim_next_chunk()` returns nothing,
  since this repo runs exactly one worker process — see that function's
  own docstring) and a separate `AUTO_GENERATION_CHECK_INTERVAL_SECONDS`
  (5 minutes) so it doesn't re-scan the whole Archive on every single
  15-second empty poll.

  Verified end-to-end live (not just unit tests): created two real
  archived pages missing a transcript (one with a deliberately fake,
  unresolvable URL; one a real, live PrimeGov meeting confirmed
  resolvable earlier this session) and called `maybe_generate_auto_job()`
  directly against the real Archive DB. Confirmed correct oldest-first
  ordering, confirmed the fake-URL candidate correctly recorded a
  re-resolve failure, confirmed the real candidate's feasibility check ran
  for real (found a real video URL; `probe_duration` itself came back
  unreadable from this dev sandbox specifically — the same known
  environment-specific network limitation already diagnosed for other
  media URLs this session, not a bug in this feature), confirmed both
  landed in the DB with `priority=0` and the configured digest email as
  `requester_email`, and confirmed both were correctly excluded from
  candidacy immediately afterward (cooldown). 19 new tests: 15 crud-level
  in `tests/test_transcription_jobs.py` (including one that directly
  exercises the escalation math with backdated timestamps — 2 consecutive
  failures 36 hours ago must still be in cooldown under doubling, which
  would already have cleared a flat 1-day rule) and 4 in the new
  `tests/test_worker_auto_generation.py` covering the parts of
  `maybe_generate_auto_job()`'s control flow that don't need mocking a
  live resolve. Full suite (207 tests) passing. New env var
  `AUTO_TRANSCRIPTION_REQUESTER_EMAIL` documented in `.env.example` —
  auto-generation is simply disabled (not guessing a placeholder address)
  when it's unset.

- **[Done 2026-08-09] Built a language-track correction flow: "public
  report, admin fixes."** Real gap closed: a `TranscriptVersion`'s
  `language` was set once (langdetect's guess for a self-transcribed
  version, or the source's own label for a scraped one) and never
  correctable afterward short of a raw database edit. Design decided via
  a real interview (three questions: who can invoke the correction, does
  it need to handle genuine bilingual content, does it apply to any
  version or only self-transcribed ones) — landed on: public report via
  the existing "Report a problem" form (new `wrong_language` issue type,
  added to `VALID_ISSUE_TYPES` in `app/db/crud.py` and the dropdown in
  both `app/templates/meeting.html` and
  `archive/templates/meeting_page.html`), a human (Ryan) reviews via the
  existing `/admin/problem-reports` list and applies the fix, no
  bilingual/mixed-content support attempted, and any version can be
  corrected — not just self-transcribed ones.

  New pieces: `archive/db/crud.py`'s `correct_transcript_version_language()`
  (targets the page's current default version when no `version_id` is
  given, since that's what a reporter was actually looking at);
  `archive/main.py`'s token-gated `POST /internal/transcript-version/
  correct-language`; `app/archive_client.py`'s `correct_transcript_language()`
  proxy function; and `app/main.py`'s `GET /admin/correct-transcript-
  language?token=&url=&language=&version_id=`, which takes the reported
  meeting's raw source URL (same shape as the existing
  `/admin/recheck-archive-page`) and looks up the matching Archive page
  the same way a repeat paste would, rather than requiring the admin to
  already know the internal slug. Verified end-to-end against a real
  live-archived NYC meeting: submitted a real `wrong_language` report via
  `/api/report-problem`, confirmed it appeared in `/admin/problem-
  reports`, applied the correction via `/admin/correct-transcript-
  language`, confirmed the change actually rendered on the permanent
  page's `schema.org inLanguage` field, then reverted it back to the
  real correct value. 8 new tests (4 crud-level in
  `tests/test_ingest_promotion.py`, 4 HTTP-level in the new
  `tests/test_correct_language_endpoint.py` covering token gating and
  the not-found path, which live entirely in the route layer and aren't
  reachable from a crud-level test). Full suite (198 tests) passing.

- **[Done 2026-08-09] `/meetings` pagination threw a real 422 in production
  whenever a filter checkbox was left unset.** Reported live by the user
  with the exact broken URL: clicking "Next" on
  `https://redtaperecordings.com/meetings?page=2&q=&jurisdiction=&
  date_from=&date_to=&fuzzy=&has_agenda=&has_transcript=` returned a raw
  FastAPI validation error instead of the next page. Root cause:
  `archive/templates/meeting_list.html`'s pagination link always emitted
  all seven filter params via a `%`-format string, substituting `""` for
  any unset one — e.g. `...&fuzzy=&has_agenda=&has_transcript=`. FastAPI's
  bool-typed query params (`fuzzy: bool`, `has_agenda: Optional[bool]`,
  `has_transcript: Optional[bool]`) reject an empty string outright (422
  `bool_parsing`) rather than treating it as "not provided" — only an
  *omitted* param does that.

  Fixed both ends, not just the one that caused this specific report:
  the template now builds the querystring from a list of only the params
  that actually have a value (also fixes an adjacent, previously-unnoticed
  bug — a search query containing `&` or `#` would have corrupted the
  pagination link's other params, since the old format string never
  URL-encoded anything); and `archive/main.py`'s route itself now accepts
  `fuzzy`/`has_agenda`/`has_transcript` as plain strings and parses them
  tolerantly (`_parse_optional_bool()`), so URLs already bookmarked/shared
  with the old broken shape — including the exact one just reported —
  keep working instead of 404ing/500ing forever. First HTTP-level route
  test added to this suite (`tests/test_meetings_route.py`, via
  `fastapi.testclient.TestClient`) — every other test here exercises
  `crud`/pure functions directly, which never touches FastAPI's own
  query-param parsing layer where this bug actually lived. Verified live
  against a local server with the exact reported URL (confirmed 200, was
  422) and by rendering the fixed template logic directly against mock
  filter state (confirmed a clean `page=2` with no filters set, and
  correct `%26`-encoding of a query containing `&`). Full suite (190
  tests) passing.

- **[Done 2026-08-09] Added a static citymeetings.nyc cross-link to NYC
  Council meeting pages, and caught a real, unrelated bug while verifying
  it live: `archive/db/crud.py`'s `get_page_by_slug()` silently dropped
  `platform` from its returned dict entirely.** User pointed to Vikram
  Oberoi's citymeetings.nyc (an independent, AI-chapter-summary tool
  specifically for NYC Council meetings, covering ~80 meetings as of his
  own talk) as worth a mention on NYC pages — confirmed live first
  (`mcp__Claude_Browser__*` against a real citymeetings.nyc chapter
  permalink) that clicking a chapter there does *not* auto-seek the video
  either (`currentTime` stayed 0 through page load, only advanced normally
  once `.play()` was called directly — same deep-link gap this app exists
  to close), so this is a genuinely complementary link, not a
  better-alternative one. Decided against automated per-meeting
  cross-linking (his coverage isn't guaranteed to include any given
  meeting we resolve, and mapping meetings across two independent slug
  schemes would couple our reliability to his site's uptime) — a static
  note instead, shown whenever `platform == "viebit"` (confirmed Viebit is
  NYC-Council-only so far, see ViebitAssetFinder's docstring). Added to
  both `app/templates/meeting.html`/`app/static/player.js` (client-JS
  toggle, matching the resolver's render-after-`/api/resolve` pattern) and
  `archive/templates/meeting_page.html` (server-side Jinja2 conditional).

  **The Archive side silently failed on first live-verification pass** —
  the DB row genuinely had `platform="viebit"` (confirmed via direct
  sqlite3 query), but the rendered page never showed the note. Root cause:
  `get_page_by_slug()` builds and returns a hand-constructed dict (not the
  ORM object) for template consumption, and that dict's field list simply
  never included `platform` — Jinja2's `page.platform == "viebit"` on a
  dict without that key silently evaluates to `Undefined == "viebit"`
  (`False`), no exception, no missing-key error, just quietly wrong. Fixed
  by adding `"platform": page.platform,` to the returned dict. Real
  example of this repo's "verify in-browser, not just via the API"
  convention catching something a DB-level check alone would have missed
  — see `CLAUDE.md`. Added `test_get_page_by_slug_includes_platform` to
  `tests/test_ingest_promotion.py` as a regression guard (this dict has no
  other test asserting its exact key set, so this bug could otherwise
  recur silently for any future field). Verified end-to-end against a real
  live-resolved NYC meeting pushed through both local services together
  (resolver + Archive), confirmed absent on a non-Viebit Archive page
  (Dublin, CA) as a regression check. Full suite (187 tests) passing.

- **[Done 2026-08-09] NYC Legistar meetings delegated to Viebit showed
  Viebit's own raw uploaded filename as the meeting title
  ("NYCC-250-8-2_251218-120823.mp4") instead of anything human-readable.**
  Reported by the user against a real production URL
  (`legistar.council.nyc.gov/MeetingDetail.aspx?ID=1362373...`). Root
  cause: `LegistarAssetFinder._find_video_links()` already extracts a
  `title`/`date` per candidate via `_extract_row_info()` — but that
  extraction is shaped for *calendar* rows (each `<tr>` has a title cell
  and a date cell), and on a single-meeting `MeetingDetail.aspx` page the
  video link's parent `<tr>` is just a one-cell "Video" row, so the
  extracted title was always "Untitled meeting"/discarded, and the
  single-video-link resolve path threw the whole `video_links[0]` dict
  away anyway once it had the URL, delegating to `resolve_via_platform()`
  with nothing to fall back on. `ViebitAssetFinder` (the platform
  underneath NYC's Legistar instance) has no better title of its own —
  confirmed live, Viebit's own `video.title` field is just the raw
  uploaded filename, not a human title.

  Fix: confirmed live on two real NYC `MeetingDetail.aspx` pages that the
  outer page's own `<title>` tag reliably gives
  `"{jurisdiction} - Meeting of {body} on {M}/{D}/{YYYY} at {time}"` —
  e.g. `"The New York City Council - Meeting of Committee on Finance on
  12/18/2025 at 11:30 AM"` and `"...Meeting of City Council on
  12/18/2025 at 1:30 PM"`. Added `LegistarAssetFinder._extract_page_meeting_info()`
  (regex-parses that shape into `title`/`jurisdiction`/`date`) and
  `_looks_like_raw_filename()` (matches a trailing video file extension —
  `.mp4`/`.mov`/`.wmv`/`.avi`/`.mkv`/`.m4v`). After delegating, `resolve()`
  now overrides the delegated result's `title` only when it looks like a
  raw filename, and fills `jurisdiction`/`date` only when those are
  missing entirely — never silently replacing an already-good value from
  a platform that has its own real metadata (e.g. Granicus). Verified
  against both real live URLs end-to-end (direct `resolve_via_platform()`
  call and the real `/api/resolve` endpoint) — `ID=1362373` now resolves
  `title="Committee on Finance"`, `jurisdiction="New York City Council"`,
  `date="2025-12-18"` (previously the raw filename, `None`, and a
  coincidentally-correct date respectively). 6 new tests added to
  `tests/test_legistar.py` (11 total, up from 5) covering the override,
  the no-`<title>`-tag passthrough case (existing behavior unchanged), and
  both helper functions directly; full suite (186 tests) passing.

  **Separately reported in the same message: Viebit video playback itself
  is also broken in production ("Video failed to load; source link
  only.").** This is a real, larger, confirmed-but-deferred bug — see the
  live entry in `BACKLOG.md` for the full root-cause investigation
  (Referer/Origin-gated CDN, confirmed via direct browser testing) and why
  the fix (switching to an iframe embed of Viebit's own player, matching
  the YouTube precedent) isn't being built yet.

- **[Done 2026-08-09] Production incident: the worker was crash-looping on
  every `claim_next_chunk()` call with `column transcription_jobs.priority
  does not exist`.** Root cause: this session's own
  `archive/alembic/README.md` said `alembic stamp head` for the one-time
  production-adoption step — correct when written (only the baseline
  migration existed), but a second migration (`8e7cf3b20f86`, the priority
  column) landed in the same session before anyone ran it against
  production, so "`head`" silently became the wrong target the moment that
  second migration was committed. README fixed to reference the specific
  revision id (`a8dc5aad7eff`) instead of the word `head`, with an explicit
  "why `head` is unsafe here" paragraph — see `archive/alembic/README.md`.

  **Confirmed fixed by the user, run from a Render shell into the
  `archive` service** (note: `alembic` must be run from inside `archive/`
  — running it from the repo root fails with `FAILED: No 'script_location'
  key found in configuration`, since `alembic.ini` lives under
  `archive/`). `alembic current` before the fix printed nothing (production
  had genuinely never been stamped, matching the README's prediction);
  `alembic stamp a8dc5aad7eff` then `alembic upgrade head` ran clean, and
  a final `alembic current` confirmed `8e7cf3b20f86 (head)`. This confirms
  the database schema now has the `priority` column, which removes the
  root cause of the crash-loop — the running worker process's own recovery
  (whether it needed a restart, or picked this up on its next poll cycle)
  wasn't independently checked this session, since neither Render logs nor
  process state were available to it.

- **[Done 2026-08-09] PrimeGov's date/jurisdiction fixed for real, using the
  page's own visible "FORMAL AGENDA"/"REGULAR MEETING" header text — a
  different, more reliable signal than the embedded sub-document `<title>`
  approach tried and reverted earlier in this same investigation (see the
  entry directly below this one).** Real bug: `PrimeGovAssetFinder.resolve()`
  (`app/platforms/primegov.py`) delegated entirely to
  `YouTubeAssetFinder.resolve_video_id()`, which sets `date` from yt-dlp's
  `upload_date` and `jurisdiction` from the raw YouTube `uploader` handle.
  Confirmed live against both real samples that both were wrong: OKC's
  `upload_date` (`20260805`) and Thousand Oaks's (`20260708`) were each one
  day *after* the real meeting (both uploaded the morning after an evening
  session), and Thousand Oaks's `uploader` ("CTO Meetings") carries no
  identifiable city name at all (OKC's "cityofokc" is barely usable).

  Per the user's own suggestion — "look for the date and jurisdiction on
  the page/row that is linking off to that youtube URL... probably the
  most accurate and dependable solution" — checked the PrimeGov page's own
  rendered text (`mcp__Claude_Browser__get_page_text` first, then a plain
  `curl`/`aiohttp` fetch to confirm it's in the *raw static HTML*, no
  headless browser needed): both real samples have a plain, prominent
  agenda header giving the correct date —
  `https://okc.primegov.com/Portal/Meeting?meetingTemplateId=68482`: "THE
  CITY OF OKLAHOMA CITY / FORMAL AGENDA / CITY COUNCIL / August 4, 2026";
  `https://toaks.primegov.com/Portal/Meeting?meetingTemplateId=9446`:
  "City Council / REGULAR MEETING / Tuesday, July 07, 2026". Both dates
  match the video's own title exactly (`"...Meeting - August 4, 2026"`,
  `"...Meeting - July 7, 2026"`) — unlike the reverted embedded-`<title>`
  approach, which for Thousand Oaks picked up an unrelated "Closed
  Session" sub-document's date (July 8, coincidentally matching the wrong
  `upload_date` instead).

  Built `PrimeGovAssetFinder._extract_date()` (first full-month-name date —
  `(Monday|...|Sunday)?, Month D(D), YYYY` — found within the first 2000
  chars of `BeautifulSoup(...).get_text()`, converted to ISO) and
  `_extract_jurisdiction()` (`(city|county|town) of X` bounded by an HTML
  tag or punctuation, with a second-line-of-defense cap that stops
  collecting words at the first one that doesn't start with a capital
  letter). The tag/punctuation bound was necessary, not cosmetic: a naive
  `city of` regex run against Thousand Oaks's flattened page text matched
  clear across an unrelated mission-statement sentence ("...City of
  Thousand Oaks that all employees are to be treated with respect and
  dignity...") because nothing but a lowercase word follows the real city
  name there; OKC's all-caps table-cell header ("OKLAHOMA CITY" then
  "FORMAL AGENDA" then "CITY COUNCIL" with no punctuation between them
  once tags are stripped) needed the opposite fix, a tag-boundary stop
  instead of a punctuation one. `resolve()` now overrides
  `YouTubeAssetFinder`'s `date`/`jurisdiction` only when a real page match
  is found, otherwise keeps YouTube's better-than-nothing values (covered
  by a dedicated fallback test).

  Verified against both real live URLs end-to-end (not just the extraction
  methods) via a direct `resolve()` call and the real `/api/resolve`
  endpoint, then in-browser on the rendered meeting page — confirmed the
  page actually shows "City of Thousand Oaks · 2026-07-07" for the
  Thousand Oaks sample. 8 new unit tests + 3 new `resolve()`-level tests
  added to `tests/test_primegov.py` (15 total, up from 5), full suite
  (181 tests) passing.

- **[Done 2026-08-09, reverted before shipping — see the entry above for
  the fix that actually landed] PrimeGov's date/jurisdiction come entirely
  from YouTube's own metadata, which is measurably worse than what's
  already sitting on the PrimeGov page itself.** Confirmed live
  (2026-08-08) via
  `https://okc.primegov.com/Portal/Meeting?meetingTemplateId=68482`
  (Oklahoma City) — video and transcript resolve cleanly (3503 real
  English auto-caption segments, no warnings beyond the standard
  auto-caption disclaimer), but:
  - `date` resolved to `2026-08-05`, one day off from the real meeting.
    The PrimeGov page has an embedded agenda document titled `"City
    Council - 8/4/2026 1:30:00 PM"` and body text saying `"August 4,
    2026"` — the *video's own title* even says "Oklahoma City Council
    Meeting - August 4, 2026". Root cause: `PrimeGovAssetFinder.resolve()`
    (`app/platforms/primegov.py`) extracts only the YouTube video id from
    the page HTML and discards everything else, delegating entirely to
    `YouTubeAssetFinder.resolve_video_id()` — which sets `date` from
    yt-dlp's `upload_date` (`app/platforms/youtube.py` line ~80), i.e.
    when the video was *posted to YouTube*, not the real meeting date.
    Plausible mismatch for any meeting uploaded the next morning after an
    evening session.
  - `jurisdiction` resolved to `"cityofokc"` — YouTube's raw `uploader`
    field (the channel handle), not a real jurisdiction string like
    "Oklahoma City, OK".
  Only affects PrimeGov pages that actually have video (the common case
  per the item above) — agenda-only PrimeGov pages never hit
  `YouTubeAssetFinder` at all.

  **Tried building the "parse the page's own embedded date" fix
  2026-08-09, per the note above to check a second sample first — glad
  it was checked, since the second sample actively disproved it, not
  just failed to confirm it.** Found a real, consistent embedded-date
  signal on *both* OKC and a second sample, Thousand Oaks
  (`https://toaks.primegov.com/Portal/Meeting?meetingTemplateId=9446`):
  a nested agenda-document `<title>...- M/D/YYYY H:MM:SS AM/PM</title>`,
  distinct from the outer page's own generic `<title>Meeting</title>`
  (OKC: `"City Council - 8/4/2026 1:30:00 PM"`; Thousand Oaks:
  `"Thousand Oaks City Council Regular Meeting (Closed Session) -
  7/8/2026 12:00:00 AM"`). Built and initially verified against OKC
  (correctly produced `2026-08-04`, matching the video's own title,
  the page body text, and the docket title all agreeing) — but checking
  the *second* sample as planned caught a real problem before shipping:
  Thousand Oaks's embedded title gives **July 8**, while the video's own
  title says **"...Meeting - July 7, 2026"**. Cross-checked against
  yt-dlp's real `upload_date` for that video (`20260708`) — the embedded
  "July 8" exactly matches the *upload* date, not the real meeting date,
  meaning this specific page's embedded agenda document (labeled
  "Closed Session") is dated by when *it* was processed/logged, not
  necessarily the same date as the open session actually captured on
  video. Building this fix would have silently replaced one
  upload-lag-shaped bug with another, harder-to-notice one (both
  produce a plausible, only-one-day-off wrong date) rather than
  actually fixing it. **Reverted, not shipped** — the "page's own
  embedded date is more reliable than YouTube's" premise doesn't hold
  up as a general rule; a third real sample, or a way to independently
  corroborate the embedded date against the video's own title text
  before trusting it, would be needed before trying again.
  `jurisdiction` remains unfixed too — the embedded title only
  reliably includes a city name on some cities (Thousand Oaks yes, OKC
  no), so there's nothing consistent to extract there either.

- **[Done 2026-08-08] `media_scan.scan_media_urls`'s "sources" JSON-blob
  branch was dead code — removed rather than fixed.** The regex
  `r'({[^}]*"sources"\s*:\s*\[[^}]*\][^}]*})'` used `[^}]*` to span from
  the array's `[` to its closing `]`, but that character class excludes
  `}` entirely — so it could never match past the closing `}` of an
  object *inside* the array, meaning it never matched any real
  JWPlayer-style config blob. Confirmed dead via a unit test
  (`tests/test_media_scan.py`) before touching it. Deleted the branch and
  its now-unused `json` import rather than writing a fixed JSON-aware
  version, since a "fixed" version would still be unverified against any
  real page — exactly the kind of unverified parsing path this project's
  own convention avoids shipping (see the "never build from assumption"
  rule above). Both adapters that call `scan_media_urls` (Granicus,
  Swagit) already get every real media URL they've ever needed from the
  plain regex patterns tried first in the same function. Verified: full
  `pytest` suite green after the change (including an updated version of
  the pinning test, renamed to `..._was_removed_as_dead_code` and
  re-documented rather than left describing code that no longer exists),
  and live against a real Simi Valley Granicus meeting — video URL and
  394 real transcript segments still resolve correctly with the branch
  gone.
- **[Done 2026-08-07] Caption language track picker.** Follow-up from the
  caption language detection fix (below) — `GranicusAssetFinder` already
  detected the real language of every fetched caption track internally
  (the `candidates` list in `app/platforms/granicus.py`) but only ever
  exposed the one it chose, silently discarding any others. Added a new
  `AlternateTranscript {language, segments}` model and
  `ResolvedMeeting.alternate_transcripts` field (`app/platforms/models.py`);
  Granicus's `resolve()` now populates it from every fetched, non-blank
  candidate track other than the chosen one, full segments included (not
  just a language label), so the frontend can switch client-side with no
  second `/api/resolve` round-trip. Frontend: a "Language: [ ]" `<select>`
  next to the Transcript heading (`#transcriptLanguagePicker` in
  `meeting.html`), hidden whenever there's nothing to switch between (the
  common single-track case). `player.js`'s `setupTranscriptLanguagePicker()`
  builds its options from the chosen track + alternates, using
  `Intl.DisplayNames` for a real language name (e.g. "Spanish") rather than
  showing a raw ISO code, and falling back to the code itself if the
  browser can't resolve it; switching reassigns the module-level `segments`
  array and calls the existing `renderTranscript()`, so search/highlighting/
  auto-scroll all keep working against whichever track is active without
  separate wiring.

  No real multi-caption-track meeting has been found live yet (every
  sample checked so far, like Simi Valley clip 2840, turned out to have
  exactly one track, just sometimes mislabeled) — confirmed live against
  Simi Valley that the field correctly stays `[]` and the picker stays
  hidden in that case, no regression. The actual multi-track code path
  was verified with a mocked `resolve()` (two synthetic VTT tracks, one
  English one Spanish): correctly chose English (matches
  `TARGET_LANGUAGE`) and carried the Spanish track through
  `alternate_transcripts` with its full 20 segments intact. The frontend
  switcher was verified in a real browser (`mcp__Claude_Browser__*`) by
  injecting synthetic two-track data into a live-rendered meeting page and
  driving the actual shipped `setupTranscriptLanguagePicker()`/
  `renderTranscript()` functions: the picker showed "English"/"Spanish"
  options, selecting "Spanish" correctly swapped the rendered transcript
  text and the global `segments` state, and the heading-row layout
  (`.transcript-heading-row` flex, `justify-content: space-between`) placed
  the picker at the row's right edge with no overlap against the "Transcript"
  heading. Confirmed the new field round-trips harmlessly through
  `archive_client.push()` — the Archive's `IngestRequest` schema
  (`archive/main.py`) has no `alternate_transcripts` field and Pydantic
  ignores unrecognized fields by default, so it's silently dropped there;
  deliberately resolver-only, since the Archive already has its own
  separate mechanism for multiple languages (`TranscriptVersion` rows,
  its own version picker).
- **[Done 2026-08-07] Real bug: a URL already cached locally never got
  backfilled into the Archive.** `/api/resolve`'s local-cache-hit branch
  (`app/main.py`) returned the cached payload directly without ever
  reaching the "push to the Archive" step, which only ran on a fresh live
  resolve — so any URL cached before the Archive integration existed, or
  while `ARCHIVE_BASE_URL` was unset/misconfigured, could never become a
  permanent page on its own, since every future resolve of that exact URL
  just kept serving the local cache. Confirmed live via `psql` on Simi
  Valley's `meeting_resolutions` row (`hit_count: 3`, predating the Archive
  integration). Fixed by making the local-cache-hit branch opportunistic:
  if the cached payload has real content (`segments` or `agenda_items`)
  and the Archive lookup at the top of `resolve()` already came back empty
  for this URL, fire the same `archive_client.push()` background task the
  fresh-resolve path uses. Verified live end-to-end with two local uvicorn
  processes (resolver + Archive, SQLite fallback): resolved a real Simi
  Valley meeting (clip 2840, 394 segments + 17 agenda items) with
  `ARCHIVE_BASE_URL` unset to reproduce a pre-Archive cached row, then
  restarted the resolver with the Archive wired up and re-resolved the
  same URL — `/internal/lookup` 404'd (Archive genuinely didn't have it
  yet), the local cache served the response, and the new opportunistic
  push fired and succeeded (`/internal/ingest` 200), after which
  `/internal/lookup` for that URL correctly returned a real `/m/{slug}`.
  Didn't build the one-time backfill pass (the other option raised in the
  original item) — the code fix closes the gap going forward for every
  URL as it's next resolved, which covers the real-world case without a
  separate one-off script.
- **[Done 2026-08-06 for Legistar/CivicPlus; investigated for PrimeGov —
  not applicable] Unsupported-platform failure is too blunt.** Fixed for
  Legistar and CivicPlus specifically: both delegate to the embedded
  Granicus link when present, and a calendar/listing page returns a
  pick-list of real meetings rather than a bare error (see Platform
  coverage section below). The remaining "no adapter at all" case is only
  PrimeGov today (detected but unregistered) — investigated whether the
  same "find an embedded supported-platform link, then delegate" pattern
  would help there: checked 3 real PrimeGov cities (Los Angeles, San Jose,
  Petaluma) and all three embed video via a **YouTube** iframe player,
  not a link to any currently-supported vendor platform. Unlike
  Legistar/CivicPlus (which really are just wrappers around Granicus),
  PrimeGov is a genuine distinct video host — the "find a supported
  link" fallback had nothing to find here, so a real PrimeGov/YouTube
  adapter was needed. **[Done 2026-08-07] Built — see the PrimeGov/
  YouTube entry in Platform coverage below.** (The "video ID not
  statically present" claim above turned out to be based on checking a
  PrimeGov URL shape without a video at all -- the shape a real shared
  link uses does have it, directly in the page HTML.)
- **[Done 2026-08-06] Zero-caption Granicus meetings — investigated with
  fresh real meetings** (since the original test clip IDs weren't recorded
  anywhere, re-tested against a current real meeting per flagged city:
  Cupertino, Mountain View, Berkeley, Paradise Valley AZ, San Diego city).
  Findings: Cupertino and San Diego now resolve real captions fine
  (2191 and 7349 segments) — the original zero-caption cases were likely
  specific to those particular old meetings, not a systemic bug. Berkeley
  and Paradise Valley AZ have a genuinely blank source `captions.vtt`
  (confirmed by fetching it directly — the standard 8-byte
  `"WEBVTT\n\n"` placeholder Granicus creates whether or not captioning
  was ever generated) — already correctly detected and warned about, not
  a bug. Mountain View uncovered a real bug, now fixed (see below).
- **[Done 2026-08-06] Real bug: caption/video-ID guessing used the
  pre-redirect URL, so `MediaPlayer.php?clip_id=...` links (how Granicus's
  own UI shares a link) never got their captions.vtt path guessed at
  all.** Found via the Mountain View investigation above: its page has no
  `<track>` tag (Flowplayer-based UI, not native HTML5 captions), so the
  guessed-path heuristic in `_extract_media_urls` was the *only* way to
  find its captions.vtt — but that heuristic pattern-matched against
  `granicus.com/player/clip/` or `granicus.com/videos/`, which a
  `MediaPlayer.php?view_id=&clip_id=` URL never matches even though it
  redirects to `/player/clip/{id}` immediately. Fixed: `_fetch_page` now
  returns the post-redirect URL alongside the HTML, and all URL-shape
  matching (`_extract_clip_id`, media guessing, RSS view_id/clip_id
  lookup) runs against that instead of the originally-submitted URL.
  Confirmed via real Mountain View, San Francisco, and DC
  `MediaPlayer.php` links — jurisdiction/date/captions all resolve
  correctly now where they silently wouldn't have before.
- **[Done 2026-08-06] Date extraction fixed via RSS `pubDateParts`.**
  `_fetch_channel_info` (renamed in spirit, same function) now also
  matches the resolved meeting's `clip_id` against the
  `ViewPublisherRSS.php` feed's `<item>` entries and reads the structured
  `<gran:pubDateParts yr= mo= day=>` attributes — confirmed live against 3
  of the originally-failing cities: San Francisco (clip 52945, page has
  no date signal anywhere — title is just "Board of Supervisors - Regular
  Meeting" — RSS gives 2026-07-28 correctly), DC (clip 10801 → 2026-07-14),
  Mountain View (clip 5389 → 2026-07-09). San Diego and Cupertino's fresh
  test meetings already had dates in their titles, so weren't a live
  reproduction of the original bug, but the RSS path is exercised for
  them too. Alexandria VA remains unfixed and is tracked as a live item
  in [BACKLOG.md](BACKLOG.md).

- **[Done 2026-08-06] Jurisdiction/title metadata cleanup.** Fixed via three
  tiers: the Granicus RSS channel title (constant per `view_id`, confirmed
  format `"{Jurisdiction}: {Body} (Videos Feed)"` across 6 cities) is tried
  first and also used to prepend the governing body to titles that don't
  already name one; then a "City/County/Town of X" (or reversed "X
  County") text search across page body *and* meta description (the
  sdcounty.granicus.com case only had it in `<meta name="description">`,
  invisible to `soup.get_text()`); then `wordninja`-based subdomain
  segmentation as a last resort (`sandiego` &rarr; "San Diego" instead of
  "Sandiego"). Applies to Legistar/CivicPlus too since both delegate to
  GranicusAssetFinder. One known residual gap: `dc.granicus.com` still
  resolves to jurisdiction "Dc" — no page-text signal or view_id available
  to do better, and decided not worth a DC-specific hardcode for one city
  (wontfix, not tracked as a live item).

- **[Done 2026-08-06] Caption quality heuristic.** `is_likely_garbled()`
  (`app/utils/vtt_parser.py`, shared by Granicus/eScribe/CA Legislature)
  flags a transcript as likely-garbled-at-the-source when >6% of its
  words are short junk fragments (≤2 letters, not a real short English
  word like "a"/"to"/"is"). Threshold calibrated against real samples:
  Alexandria VA's confirmed-garbled captions (clip 6490 — fragments like
  "test meele first item on t", "last meeting.Oa") sit at ~17%, while four
  independently-confirmed clean real sources (Boston, San Diego, DC, San
  Francisco) all sit under 2% — comfortable margin on both sides. Live
  re-verified after implementation: Alexandria correctly gets the new
  warning message (with the same manual-transcription contact CTA as the
  blank-VTT case), Boston/SF/DC/San Diego/Cupertino all resolve with zero
  false positives.

- **[Done 2026-08-06] Caption language detection.** Fixed: found via live
  review that Simi Valley clip 2840's only caption track is labeled
  `srclang="en"` on the page but is actually Spanish content (confirmed by
  fetching the raw VTT). `GranicusAssetFinder` now detects the real
  language of caption text via `langdetect` rather than trusting the page
  label, prefers a track matching `TARGET_LANGUAGE` ("en") when multiple
  tracks exist, and surfaces a warning when the best available track
  doesn't match. Follow-up (UI dropdown to let the user pick between
  multiple language tracks when more than one exists) built 2026-08-07 —
  see the "Caption language track picker" entry above.

- **[Done 2026-08-06] San Francisco's ALL CAPS captions normalized.**
  `_normalize_shouting_caption()` (`app/utils/vtt_parser.py`, runs inside
  `parse_vtt` so every platform benefits) detects a track as
  all-caps-at-the-source (essentially zero lowercase letters across a
  40+-letter sample) and re-cases it to sentence case, capitalizing after
  real sentence punctuation across cue boundaries (cues are joined with a
  placeholder before casing, so a sentence split mid-cue isn't treated as
  two separate sentence starts) rather than per-cue. Confirmed live: a
  real San Francisco Board of Supervisors meeting (clip 52945) that was
  genuinely ALL CAPS at the source now renders as normal sentence-case
  text (e.g. "the july 28th 2026 regular meeting of the san francisco
  board of supervisors. Madam clerk, please call the roll."). Spot-checked
  the other 6 meetings with real transcripts (2026-08-06): 5 of 6 English
  ones (San Diego, Oakland, Boston, San Francisco, DC) are genuinely
  readable with only minor rough patches (a few garbled words
  mid-Boston); Alexandria VA remains the one clear outlier at genuinely
  unreadable quality — now caught by the caption quality-detection item
  above.

## UX polish (from live review, 2026-08-06)

- **[Done 2026-08-06] Video player sizing, play button, poster, and
  awkward-pause-on-play.** All four addressed together: the video wrapper
  now locks a 16:9 aspect-ratio via CSS so it never collapses to a tiny
  default box; a large, obvious overlay play button replaces the small
  native control-bar triangle; and a one-time muted-play-then-pause on
  `loadedmetadata` both renders a real first frame (serving as a poster,
  no separate thumbnail-fetch needed) and pre-buffers the initial
  segments, so the user's actual first play click starts instantly instead
  of visibly waiting to buffer — confirmed this measurably works in
  testing. Verified in-browser on desktop and mobile widths, and confirmed
  no regression to deep-link seeking (a real risk: the warm-up's play/pause
  could have clobbered a pending deep-link seek, since `currentTime` set
  before metadata loads just queues as the "default playback position" —
  fixed by capturing and restoring that value instead of resetting to 0).
- **[Done 2026-08-06] Transcript search, per-line link icon, manual
  timestamp entry, sticky toolbar.** All four verified end-to-end against
  a real 1073-segment Boston meeting. Search mirrors browser Ctrl+F
  (highlight all matches, "N/M" count, prev/next + Enter/Shift+Enter
  navigation — confirmed 21 real matches for "sidewalk"). Each transcript
  line has a chain-link icon that copies a link to that line without
  moving playback (distinct from clicking the timestamp, which seeks);
  after a follow-up look it was enlarged (14px&rarr;17px) and now also
  shows at rest (opacity 0.6) on whichever segment is current when the
  video is paused, suppressed during playback so it doesn't flicker line
  to line with auto-scroll. A "Go to time" input (accepts H:MM:SS, M:SS,
  or seconds) sits in the video toolbar and works even with no transcript,
  since deep-linking to a moment — not the transcript — is the primary
  goal. The toolbar itself is now `position: sticky` so it stays reachable
  when scrolling past it, addressing the original auto-scroll-fights-you
  complaint.
- **[Done 2026-08-07] "View original source" link on the meeting page.**
  Links back to the original government meeting page (`data.source_url`)
  in a new tab, styled small/muted so it reads as an outbound link rather
  than the page's own title. `source_url` is a required field on
  `ResolvedMeeting`, so this renders for every successfully-resolved
  meeting regardless of platform.
- **[Done 2026-08-07] Live playhead timestamp where the transcript
  would be.** Deep-linking to any moment already worked with zero
  transcript (`t=` has always been the sole seek-position authority),
  but nothing signaled that — a meeting with no transcript/agenda
  previously just showed a warning and a dead end. `#transcriptMissing`
  now shows a large live-updating timestamp (`updateNoTranscriptTime()`
  in `player.js`) plus a "Copy link to this moment" button, sharing one
  click handler with the existing toolbar button. Surfaced and fixed a
  real gap: the timestamp is now also updated immediately after
  `applyDeepLink()`, not just on `timeupdate` — for YouTube specifically,
  `timeupdate` is only polled while actually playing, so a paused/
  autoplay-blocked load would otherwise show a stale "0:00" instead of
  the real deep-linked position. Verified live against Paradise Valley
  AZ's confirmed blank-caption meeting.

- **[Done 2026-08-07] Newsletter signup box redesign.** Resolved the
  open question in favor of a new-but-consistent treatment: `.newsletter-btn`
  is a sibling to `cassette-btn` (same bold-mono/chunky-border family)
  but deliberately not `cassette-btn` itself — "sign up" isn't a "rewind
  to a moment" action, so it's solid navy instead of the reel-icon
  gimmick, keeping `cassette-btn` reserved for the two buttons its own
  scoping comment already calls out. Input now matches the homepage's
  fused-pill sizing (48px height, matching border-radius split) instead
  of plain unstyled Bootstrap. Added a small dymo-label-style kicker tag
  ("STAY IN THE LOOP") on the dedicated `/subscribe` page — reuses the
  wordmark's signature visual element as a secondary section tag.
  Verified visually and confirmed the submit flow still works unchanged.
- **[Done 2026-08-07] "Get Updates" link in the site nav pointing at
  the email signup.** Originally shipped as a same-page
  `#newsletterForm` anchor to a footer form; replaced same-day (see the
  dedicated `/subscribe` page item below) after the user pointed out
  three real problems with the anchor approach — no visible cue if
  you're already scrolled to the bottom, breaks Ctrl+click/open-in-new-
  tab, and a shared link lands people wherever the anchor happens to be
  rather than a clean destination. The nav link now points at
  `/subscribe` directly.
- **[Done 2026-08-07] Dedicated `/subscribe` page, replacing the
  footer-anchor approach above.** New `GET /subscribe` route +
  `subscribe.html` holds the actual signup form now (autofocused input,
  no anchor-jump needed). Nav's "Get Updates" and the About page's
  "Subscribe to get updates" both link straight to `/subscribe`. The
  sitewide footer keeps a plain text link to it (`request.url.path`
  check in `base.html` suppresses that link specifically on
  `/subscribe` itself, so the page doesn't show the same prompt twice).
  `newsletter.js`'s anchor-focus workaround was removed since it's no
  longer needed. Verified: page renders with the email input
  autofocused, footer link correctly present/absent on the right pages,
  and the full submit flow still works end-to-end (confirmed the
  graceful "not available" message renders when Resend isn't
  configured, via a direct programmatic submit after a manual click
  raced the screenshot).

- **[Done 2026-08-07] Spinning cassette-reel animation on the "please
  wait" fetch message.** `player.js`'s loading-state line now renders
  two `.cassette-reel` SVGs (reusing the existing icon markup) with a
  new `.spinning` modifier class — a slower 1.6s spin than the 0.8s
  hover flourish elsewhere, since this can run for up to ~20s and a
  quick spin reads frantic sustained that long. Verified the animation
  is actually wired (not just present in markup) via computed style —
  `animationName: "reel-spin", animationDuration: "1.6s"` — after
  confirming a byte-fresh fetch of `style.css` contains the rule.

## Platform coverage

- **[Done 2026-08-09] Built a generic "try our best" fallback for any
  URL `detect_platform()` doesn't recognize**, directly from the user's
  own request and mockup layout: today, pasting an unsupported city's
  URL got a flat `unsupported_platform` error with zero attempt made,
  every time. `app/platforms/generic_fallback.py`'s
  `GenericFallbackAssetFinder` is registered under `platform_name =
  "unknown"` — the exact string `detect_platform()` already returns for
  anything unmatched — so `get_finder("unknown")` now finds this instead
  of raising, with no changes needed anywhere else in the dispatch path.

  Reuses existing infrastructure almost entirely rather than building new
  parsing from scratch: a plain (non-headless-browser — that's reserved
  for known Cloudflare-gated platforms specifically) fetch, checked first
  for an embedded/linked YouTube video (a huge share of small-city sites
  just embed a YouTube video with no dedicated platform at all) —
  delegates to `YouTubeAssetFinder` for real video + real captions when
  found, the best possible outcome here. Falls back to `media_scan.py`'s
  existing generic `.m3u8`/`.mp4` scanner (the same one Granicus/Swagit
  already use, not reimplemented) plus any caption-shaped URL found in
  the same scan, parsed via the same `parse_captions_by_extension()`
  dispatch every real adapter goes through. Deliberately does **not**
  attempt agenda-item detection — every other adapter's agenda parsing is
  tied to that platform's own known page structure, and there's no
  reliable generic pattern to reuse the way there is for media URLs;
  guessing badly would be worse than agenda items just being absent
  (which the existing UI already handles fine everywhere it's optional).

  **Zero frontend changes needed** — `initVideo()` already handles any
  `video_url`/`video_format` combo generically, and the no-transcript
  live-playhead deep-link tracker (built earlier, see this same file)
  already covers "no transcript, but you can still link to a moment" for
  any video, not just ones from a known platform. Every outcome (nothing
  found / video found / video + transcript found) gets an honest,
  specific warning message instead of a flat error, matching the user's
  own requested copy fairly closely.

  Verified end-to-end through the real, unmodified running app (not just
  fixture tests) using a local test page standing in for a genuinely
  unrecognized small-city site with an embedded YouTube iframe — resolved
  correctly via real YouTube delegation with real auto-generated
  captions, rendered with the honest "we don't officially support this
  website yet, but found a video and did our best" message directly under
  the video, and the deep-link/live-playhead tools worked identically to
  every other platform. 5 new fixture-backed tests
  (`tests/test_generic_fallback.py`) covering the YouTube-embed path,
  direct-media-plus-captions path, no-video-found path, and a page fetch
  failure. Full suite (235 tests) passing.

  **Real architecture note, deliberate**: this makes the
  `unsupported_platform` error branch in `app/main.py`'s `/api/resolve`
  (and its matching outcome bucket in `app/db/outcomes.py`) effectively
  unreachable going forward — every URL now resolves to *something*.
  Left in place rather than removed, a conservative choice: `get_finder()`
  could still raise for a genuinely different reason later.

- **[Done 2026-08-09] Two new platforms shipped — Minneapolis LIMS and
  Salt Lake City's council meeting-recap pages — both previously
  completely unsupported, both needing this repo's first genuinely new
  kind of dependency: a real headless browser.** Real production
  impact: pasting either city's real URL into the app today returns a
  plain `unsupported_platform` error with zero results — confirmed by
  testing both against the live, unmodified app immediately before this
  work started, specifically so "does this actually work now" could be
  answered against a real before/after, not just a mockup.

  **The path here started from a live mockup** (see the "SLC multi-video"
  entry earlier the same day) that proved the UI needed zero frontend
  changes for this data shape, but used a hand-picked video id to
  sidestep the real blocker (Cloudflare) rather than solve it. This
  entry is that blocker actually getting solved for real.

  **`app/platforms/headless_browser.py`** — a shared, lazily-launched,
  reused Playwright Chromium instance (`fetch_via_browser(url) -> html`).
  The real fix that worked is much smaller than a full "stealth" setup,
  confirmed by isolating each variable independently rather than
  combining guesses: a plain headless launch still gets served the
  Cloudflare challenge page (Playwright's default context sends a
  User-Agent that identifies itself as headless — an easy signal for
  Cloudflare's bot detection); `--disable-blink-features=
  AutomationControlled` alone didn't fix it; extra wait time alone
  didn't fix it; **a normal desktop Chrome User-Agent + a real viewport,
  alone, did** — confirmed against both real sites independently before
  combining. Also confirmed and ruled out as easier alternatives:
  client-side `fetch()` from a real visitor's own browser (blocked by
  CORS on both sites, no `Access-Control-Allow-Origin`), and iframing
  the government's own page from a different origin (works for SLC, real
  content renders; blank for Minneapolis LIMS despite the site loading
  fine at the top level — a genuine difference between the two, not
  pursued further as a real feature once headless-browser fetching
  itself was confirmed to work for both).

  **`app/platforms/lims.py`** — Minneapolis's own "Legislative
  Information Management System"
  (`lims.minneapolismn.gov/MarkedAgenda/CI/{id}`). Two headless fetches
  per resolve (confirmed the JSON data isn't embedded in the agenda
  page's own HTML, so there's no way to get both from one fetch): the
  agenda page for title/date/jurisdiction (parsed from its own `<title>`
  tag, e.g. `"Climate & Infrastructure Committee Agenda 8/6/2026 1:30 PM
  - City of Minneapolis"`), and `GET /MeetingYoutubeVideo/{id}` (same
  numeric id) for the real video + `SerializedVideoTimestamps` — a
  genuinely richer signal than most already-supported platforms give:
  real per-agenda-item start times, not just a title. That JSON is a
  category → item tree, not a flat list (a "Discussion" category can
  itself have a real timestamp *and* contain several individually-
  timestamped items) — `_flatten_timestamps()` surfaces every entry with
  a real timestamp at any nesting level, confirmed live this matters (a
  real sample's "Consent" category has its own timestamp and no files,
  which a leaves-only flatten would have dropped entirely). Delegates to
  `YouTubeAssetFinder` for the video itself and real captions.

  **`app/platforms/slc.py`** — Salt Lake City's `slc.gov/council/
  *-meeting-recap/` pages. Built directly on the corrected finding from
  the same day's earlier mockup work: these pages do **not** embed
  multiple distinct videos (the original assumption) — every real page
  checked has exactly one video with several `t=`-timestamp links into
  it. Extracts every "(Watch)"-style link's timestamp (handles both real
  `t=1441` and `t=2455s` formats, confirmed mixed on the very same page)
  plus its nearest containing paragraph's own text as the topic, turning
  each into an `agenda_items` entry the same shape LIMS's structured
  data produces. One real, known gap found while building, not chased
  further: a page's single "highlight" story uses a different HTML
  pattern (a "Learn More"/"Watch the Briefing" promo box, not the plain
  "{topic}. (Watch)" shape every other item uses) and gets silently
  skipped rather than parsed — a safe failure mode (no garbage text),
  logged as an open follow-up in BACKLOG.md rather than risking a
  fragile heading-guessing heuristic.

  **`detect_platform()`** gained two new narrow rules —
  `lims.minneapolismn.gov` (exact domain) and `*.slc.gov` scoped
  specifically to the `-meeting-recap` path pattern confirmed across
  real pages, not the whole domain (most of `slc.gov` is ordinary city
  content this app has no reason to try to resolve).

  Verified end-to-end live, not just via unit tests: both real URLs
  against the real, unmodified local app (before: `unsupported_platform`
  for both) and after (real video, real jurisdiction/date, real agenda
  chapters, real transcript) — then in-browser for both, including
  clicking a real agenda-item chapter and confirming the video actually
  seeks (Minneapolis: 53:00 chapter → video jumped to 53:05, transcript
  auto-scrolled to the matching real moment). 15 new tests
  (`tests/test_lims.py`, `tests/test_slc.py`, plus two new
  `detect_platform()` cases in `tests/test_base.py`), all mocking
  `fetch_via_browser` rather than launching a real browser during the
  suite. Full suite (226 tests) passing.

  **Real, deliberately not fully resolved before shipping**: whether the
  new `playwright install --with-deps chromium` build step actually
  works on Render's plain `python` buildpack is unverified — Chromium
  needs real system shared libraries ffprobe never did, and this session
  has no real Render deploy access to test it. Documented prominently in
  `render.yaml`'s own comment and flagged as a live BACKLOG.md item,
  expecting a real possible failure the way the transcription worker's
  own first two deploys hit real OOM crashes, not assumed to work on the
  first try.

- **[Done 2026-08-06] Legistar adapter** — confirmed and built: Legistar is
  purely a calendar/agenda wrapper, video always redirects via
  `Video.aspx?Mode=Granicus&ID1={id}&Mode2=Video` straight to Granicus.
  See `app/platforms/legistar.py`.
- **[Done 2026-08-06] CivicPlus adapter** — confirmed and built, same
  pattern as Legistar: an AgendaCenter listing page (`tr.catAgendaRow`
  rows) has a direct per-meeting video link in `td.media` when video
  exists (confirmed real: `ca-westlakevillage.civicplus.com`, 16 real
  Granicus links across one listing page). No "single meeting" URL shape
  observed — every AgendaCenter URL is a listing, so >1 video row always
  raises the calendar pick-list. See `app/platforms/civicplus.py`.
- **[Done 2026-08-07] Granicus agenda-item chapter-marker fallback,
  same role as CivicClerk's `eventBookmarks`/Swagit's `.playerControl`.**
  When there's no usable transcript, `GranicusAssetFinder` now tries
  `AgendaViewer.php?clip_id={id}&embedded=1` — Granicus's own agenda-index
  feature, when a customer has it turned on, renders each item as
  `<a name="agenda{id}" onclick="top.SetPlayerPosition('0:{seconds}',null)">
  {title}</a>`. Confirmed live: works on Simi Valley (17 items) and San
  Francisco (82 items). Does not help either of the two jurisdictions
  confirmed genuinely blank-caption in the 2026-08-06 zero-caption
  investigation above: Berkeley redirects `AgendaViewer.php` to its own
  external site (`berkeleyca.gov`) instead, with an empty `cuepoints`
  array on the player page too; Paradise Valley AZ redirects it to a
  Google Docs PDF preview, and its `cuepoints` array has real
  timestamps/ids but no titles anywhere to pair them with. Both simply
  return zero items and fall through to the existing "no transcript"
  warning, so this is additive, not a regression, for jurisdictions that
  don't have it. Real ratio of "has native agenda index" vs. "redirects
  elsewhere" across Granicus's full customer base is unknown — worth
  revisiting once more jurisdictions are checked.
- **[Done 2026-08-07] Surface an agenda link even when there's no
  timestamped chapter data (Berkeley/Paradise Valley AZ style).**
  `_fetch_agenda_items()` now returns `(items, fallback_url)` — when
  the native `<a name="agenda...">` structure isn't found but the
  request still resolved to a real page, `fallback_url` is that page's
  URL (`response.url` after `AgendaViewer.php`'s redirect, same pattern
  `_fetch_page` uses for the main page), and `resolve()` appends a
  plain "agenda is available here: {url}" warning instead of
  discarding it. Also fixed to make it *actually* clickable: `player.js`
  was rendering all transcript warnings through `escapeHtml` (plain
  text only), so a URL in a warning would've shown as inert text — new
  `linkifyWarning()` escapes first, then wraps bare URLs in a real
  `<a target="_blank">`. Verified against live Berkeley and Paradise
  Valley AZ (both get `fallback_url`, Simi Valley's 17 real items
  correctly get `None`), and end-to-end in-browser that the rendered
  warning contains a real anchor tag. Not yet investigated: whether
  this redirect-target pattern holds generally across other Granicus
  customers who lack the native agenda index, or is specific to these
  two.
- **[Done 2026-08-07] Dedicated "Agenda" section, structurally separate
  from "Transcript," always loaded regardless of transcript
  availability.** Agenda/chapter-marker data (Granicus's
  `AgendaViewer.php` items, CivicClerk's `eventBookmarks`, Swagit's
  `.playerControl` markers) previously got folded directly into
  `ResolvedMeeting.segments` as if it were transcript content, and only
  when there was no real transcript at all — a reasonable v1 shortcut
  that didn't hold once agenda was meant to be its own thing. Added a
  new `agenda_items: List[TranscriptSegment]` field on `ResolvedMeeting`
  (`app/platforms/models.py`), kept structurally separate from
  `segments` so agenda/chapter data is never mistaken for real
  transcript content. Granicus, CivicClerk, and Swagit adapters now
  populate it unconditionally (agenda fetch decoupled from `if not
  segments:`), so a meeting with both a real transcript and a real
  agenda shows both simultaneously — verified live on Simi Valley
  Granicus (394 real transcript segments + 17 agenda items
  simultaneously). New `#agendaSection` in `meeting.html`, positioned
  between the video and transcript sections; `player.js`'s
  `renderAgenda()` reuses the transcript's `.segment-timestamp`/
  `.segment-link-btn`/`.segment-text` markup for click-to-seek and
  copy-link, but deliberately doesn't participate in
  `findActiveSegment()`'s "currently playing" highlighting or the
  `line=` deep-link param — agenda items are seek-only via `t=`,
  simpler than transcript's fine-grained tracking. `classify_outcome()`
  in `app/db/outcomes.py` now checks `resolved_payload.agenda_items`
  directly instead of inferring the `agenda_fallback` bucket from a
  warning-text marker (`_AGENDA_FALLBACK_MARKER` removed). Verified
  live across three real scenarios: Simi Valley Granicus (transcript +
  agenda both shown), Yountville Swagit (agenda only, 7 items,
  transcript-missing block shows a plain "No transcript found"
  message), Paradise Valley AZ Granicus (no agenda section — no
  timestamped agenda data available — but the existing blank-caption
  warning and clickable agenda-PDF fallback link still render
  correctly in the transcript-missing block). YouTube/PrimeGov adapter
  untouched this round — confirmed it still resolves cleanly with an
  empty `agenda_items: []` (no crash, no regression).
- **[Done 2026-08-06] CivicClerk, Swagit, eScribe adapters built.**
  BoardDocs deliberately excluded — confirmed across 2 real cities (South
  Portland ME, Taos NM) it's a document/agenda platform with no reliable
  video, despite a site-level `bd.videoservice` flag; not worth a
  video-resolver adapter. Also confirmed (Taos NM sample) that agendas
  embedding a live Zoom meeting ID/passcode give no path to a recording —
  Zoom join links and cloud-recording URLs are unrelated and unguessable
  from each other, and Zoom's Recordings API requires OAuth credentials
  tied to the hosting account, not a public lookup. Not building a Zoom
  integration; if a city happens to separately publish a real
  `zoom.us/rec/...` link on a page, normal page-scraping would already
  pick it up like any other link.
- **[Done 2026-08-07] PrimeGov + standalone YouTube adapters.** Two new
  platforms, `app/platforms/primegov.py` and `app/platforms/youtube.py`.
  Confirmed live end-to-end (LA City Council, a real ~100-minute meeting)
  through the full pipeline: resolve, iframe playback, transcript render,
  deep-link seek on page load, click-to-seek from a transcript line, and
  "Copy link to current time" — all working.

  **PrimeGov → YouTube delegation**: confirmed live (`lacity.primegov.com`)
  that a real shared-link meeting page (`Portal/Meeting?
  compiledMeetingDocumentFileId=...`) has `var videoUrl = "{11-char-
  YouTube-id}";` directly in the server-rendered HTML, right next to a
  `youtube.com/iframe_api` script tag — simple regex extraction, no JS
  execution needed. (An agenda-only URL shape, `?meetingTemplateId=...`,
  is what got checked in the original "not statically present"
  investigation above — that page genuinely has no matching recording.)
  Unlike Legistar/CivicPlus's delegation, this preserves the *original*
  PrimeGov URL as `source_url` (calls `YouTubeAssetFinder.
  resolve_video_id()` directly rather than going through
  `resolve_via_platform()`), so "View original source" points back to
  the actual meeting page, not a raw youtube.com URL.

  **YouTube playback**: no direct video file URL exists for YouTube,
  unlike every other platform here — needs an embedded iframe + the
  YouTube IFrame Player API, a structurally different control surface
  (`seekTo()` instead of `currentTime=`, no native `timeupdate` event,
  async player creation) than the native `<video>`/hls.js pathway.
  `player.js` now wraps whichever one is active behind a shared
  `{currentTime get/set, play, pause, addEventListener}` adapter shape
  (`createNativeAdapter` / `createYouTubeAdapter`) set once as
  `activeVideoAdapter`, so transcript click-to-seek, "Copy link to
  current time", "Go to time", and `applyDeepLink()` all work unchanged
  against either one — verified all of the above live against the real
  LA meeting, including deep-link seeking on a fresh page load (the
  trickier async case, gated on the player's `onReady`).

  **YouTube caption download is blocked for plain HTTP requests** —
  real finding, not assumption: every caption URL YouTube hands out
  (via the watch page's embedded `ytInitialPlayerResponse` JSON, itself
  fetched fine with plain HTTP) returned `200 OK` with **0 bytes**
  across 5 different request shapes tried live: aiohttp/curl, with a
  real browser User-Agent, cross-origin `fetch()`, same-origin `fetch()`
  from youtube.com itself, and a freshly-signed same-session URL grabbed
  via JS on the actual watch page. **yt-dlp works reliably** where all of
  those failed (confirmed against the real LA meeting: 570KB, ~2000
  real caption segments) — it evidently has its own way of working
  around whatever's blocking bare HTTP clients, so caption fetching goes
  through yt-dlp's `urlopen()` (called via `asyncio.to_thread` since
  yt-dlp is synchronous), not our own aiohttp session. **Ongoing
  maintenance risk**: yt-dlp is under active, frequent maintenance
  specifically because YouTube keeps changing things to block scraping
  — left unpinned (latest) in `requirements.txt` on purpose; pinning an
  old version would risk this breaking sooner. If YouTube/PrimeGov
  resolves start failing, check for a yt-dlp update first.

  **YouTube's caption VTT uses a "roll-up" cue style**, not one cue per
  line (confirmed on both an auto-generated and, per a different real
  track on the same video, a manual/CC-sourced track) — each cue repeats
  the previous settled line and grows the *next* line word-by-word, so
  treating each cue as its own segment produces massive duplicate text.
  New `dedupe_rollup_cues()` in `vtt_parser.py` collapses this into real
  segments — verified against the real 4035-cue/570KB sample: 2004 clean
  segments, no visible duplication, fully coherent reconstructed text.

  **Manual vs. auto-generated caption track selection**: prefers a
  manual (non-ASR) track when available, but only when its coverage is
  comparable to the auto-generated one — real finding on the LA sample:
  the "manual" CC track only starts at 18:49 into the video (likely a
  government CART feed that skips pre-meeting dead air), while the
  auto-generated track covers the full video from :01. A transcript
  with a 19-minute unlinkable gap at the start is worse for a deep-link
  tool than a slightly lower-quality but complete one, so manual is only
  used when it starts within 60s of the auto-generated track's start
  (`YouTubeAssetFinder._pick_caption_track()`). Confirmed live: correctly
  fell back to the (complete, auto-generated) track for this video and
  warned the user it's auto-generated, not human-transcribed.

  Follow-ups not yet investigated (non-English caption handling, and
  whether the manual-track coverage gap is typical or one-off) are
  tracked as live items in [BACKLOG.md](BACKLOG.md).

## Reporting & caching

- **[Done 2026-08-07] Per-adapter reporting log + read-through cache.**
  New `app/db/` layer (SQLAlchemy async, Postgres via `DATABASE_URL` in
  prod — Render Postgres, user's choice over Neon/Supabase — local SQLite
  fallback otherwise). `/api/resolve` now checks for a prior successful
  resolve of the same normalized URL before fetching live, and logs every
  attempt (success or failure) unconditionally to `meeting_resolutions`.
  All DB calls are wrapped so a down/misconfigured database degrades
  silently rather than breaking resolving — verified live by pointing
  `DATABASE_URL` at an unreachable host and confirming `/api/resolve`
  still returned correct results with no 500. Two token-gated endpoints:
  `GET /admin/stats` (aggregates) and `GET /admin/log` (unaggregated
  per-URL list, JSON or CSV). Also added `external_id` to `ResolvedMeeting`
  (populated so far by Granicus and CivicClerk from ids they already
  extract internally) as a foundation for future dedup.
- **[Done 2026-08-07] Outcome classification fixed to reflect content
  quality, not just resolve status.** Real gap found via live testing: a
  resolve that returns a video with zero transcript segments — or with
  only chapter-marker fallback data (Granicus/CivicClerk/Swagit) — was
  counting as `"success"` in the reporting log, since both `status="success"`
  and `segments` being non-empty (chapter markers still populate
  `segments`) looked identical to a real transcript from the logging
  code's point of view. `app/db/outcomes.py`'s `classify_outcome()` now
  buckets every row into `success` / `agenda_fallback` / `blank_transcript`
  / `garbled_transcript` / `non_english_transcript` / `no_video`, on top of
  the existing `resolve_failed` / `calendar_page` / `unsupported_platform`
  cases — verified against live Simi Valley (garbled Spanish captions),
  Paradise Valley AZ (genuinely blank, no fallback available), and a
  synthetic test covering all five content-quality buckets directly.
- **[Done 2026-08-07] Real bug: non-UTF-8 captions.vtt crashed the whole
  transcript fetch.** `_fetch_vtt` in Granicus/eScribe/CA Legislature all
  called aiohttp's `response.text()`, which decodes strictly as UTF-8 and
  raises `UnicodeDecodeError` on anything else — confirmed live on Simi
  Valley clip 2840, whose real Spanish-language `captions.vtt` isn't valid
  UTF-8 (`0xf3` at byte 241), producing zero segments and a transcript
  warning instead of the actual captions. New `decode_vtt_bytes()`
  (`app/utils/vtt_parser.py`) reads the response as raw bytes and tries
  UTF-8, then Windows-1252, then finally UTF-8 with `errors="replace"`,
  shared by all three platforms' `_fetch_vtt`. Verified live: Simi Valley
  clip 2840 now returns 394 real Spanish-language segments instead of the
  decode-error warning.

## Roadmap items completed

- **[Done 2026-08-07, live] Newsletter signup.** A footer signup form
  (sitewide, in `base.html`) POSTs to `/api/newsletter/signup`, which
  adds the email to a Resend audience. Chose Resend over Mailchimp
  specifically because it can also handle the future "email alerts for
  saved searches" item (triggered per-user sends) on the same
  account/API, not just newsletter broadcasts — Mailchimp would need a
  separate paid add-on (Mandrill) for that later. Degrades gracefully
  like the DB layer: with no `RESEND_API_KEY`/`RESEND_AUDIENCE_ID` set,
  signups return a clean "not available right now" message instead of
  erroring. Live on `redtaperecordings.com` (DNS via Namecheap).
  **Real gotcha hit and fixed**: the first `RESEND_API_KEY` created was
  scoped to "Sending access" only, which Resend rejects for the
  audiences/contacts endpoint with `401 restricted_api_key` — Resend API
  keys need **Full access** to manage audience contacts, not just send
  mail, and permission level can't be changed on an existing key
  (create a new one, revoke the old). Confirmed via Render's live logs
  (the `logger.error("Resend signup failed (%s): %s", ...)` line in
  `main.py` was what surfaced the exact cause) and a real end-to-end
  signup afterward.
- **[Done 2026-08-07, live] Basic analytics.** Google Analytics 4, per
  the user's choice. `base.html` conditionally loads `gtag.js` from
  `GA_MEASUREMENT_ID` and always defines a global
  `window.trackEvent(name, params)` — a real call to `gtag('event', ...)`
  when GA is configured, a no-op otherwise — so call sites never need to
  branch on whether GA is set up. Three events wired so far:
  `submit_meeting_url` (homepage form), `copy_link_to_time` (the core
  viral action — someone creating a shareable deep link),
  `newsletter_signup`. Deliberately did **not** send which meeting URLs
  get pasted in as a GA event parameter — that's redundant with the
  per-adapter reporting log above (which already tracks this
  server-side, with outcome detail GA has no equivalent for) and there's
  no reason to also hand government meeting URLs to Google.
- **[Done 2026-08-07] Permanent meeting pages** (the Archive's core
  feature). Built as a genuinely separate app, `archive/` — own FastAPI
  service, own database (same Render Postgres server as the resolver,
  but a separate logical database), own deploy — reachable at
  `redtaperecordings.com/m/{slug}` via a reverse-proxy in the resolver's
  `app/main.py` (`/m/*` and `/archive-static/*`), so the custom domain
  stays consolidated for SEO/sharing even though it's two services.
  Content model: `MeetingPage` (one per real-world meeting, identity via
  `(platform, external_id)` or normalized URL) + `TranscriptVersion`
  (many per page — language/source variants, deduped by a content hash
  of the segment text) + `MeetingPageUrlAlias` (every input URL that's
  ever pushed, so a lookup keyed on a wrapper-platform URL like Legistar
  still short-circuits even though its real identity lives on the
  platform it delegates to). Pages are fully server-rendered (real
  transcript/agenda content on first byte, not client-fetched JSON) for
  actual crawlability. Handoff: the resolver checks the Archive *before*
  resolving (`archive_client.lookup()`) and redirects to the permanent
  page if one exists, preserving `t=`/`line=`; after a live resolve
  with real content (transcript or agenda — never for blank/failed
  resolves), it pushes via `archive_client.push()` on a `BackgroundTasks`
  callback (not a bare `asyncio.create_task`, which risked the task
  being garbage-collected mid-flight). Both directions degrade silently
  through the same `safe()` pattern as the existing DB calls — a down
  Archive never breaks `/api/resolve`, and the resolver's `/m/*` proxy
  returns a clean 503 rather than hanging.

  Verified live end-to-end locally (two uvicorn processes): a real
  content-bearing resolve (Simi Valley Granicus, 394 segments + 17
  agenda items) correctly created a `MeetingPage`; re-pasting the same
  URL returned `{"redirect_url": "/m/{slug}"}` in ~20ms instead of
  re-scraping; the alias table correctly short-circuited a
  wrapper-platform-shaped URL pointed at the same `external_id`; deep
  links (`t=630&line=seg-4`) survived the redirect and correctly seeked
  + highlighted on the permanent page; a second transcript version
  (different language) correctly appeared in the version picker
  (`?version={id}`, full page reload) without disturbing the first; an
  identical re-push correctly did not create a duplicate version
  (content-hash dedup); a blank/no-content resolve (Paradise Valley AZ)
  correctly never reached the Archive at all; and killing the Archive
  process confirmed `/api/resolve` kept resolving live with no 500 while
  `/m/{slug}` degraded to a clean 503.

  Operational notes for when this goes live: Render's free web services
  spin down after 15 min idle (~30-60s cold start) — fine during
  testing, but the Archive service should move to a paid plan before
  `/m/*` links are actually shared or submitted for indexing, since a
  Googlebot fetch regularly eating that latency is a real crawl-health
  risk, not just a stray-visitor annoyance. Free Render web services can
  send private-network requests but not receive them, so the proxy
  targets the Archive's public `.onrender.com` URL for now — switching
  to Render's internal hostname once the Archive is paid is a one-line
  env var change. The second Postgres database
  (`CREATE DATABASE rtr_archive;` on the existing instance) and the
  second Render web service both still need to be provisioned by the
  user themselves before this is live in production.

  Explicitly not built in this pass (still gated on the Archive
  existing): the transcription crawler, search, accounts/billing, email
  alerts, on-demand crawl requests, video highlights — all tracked as
  live roadmap items in [BACKLOG.md](BACKLOG.md). Also not resolved:
  whether a genuine re-scrape of the same `(language, source)` with
  different content should replace that version in place or add a new
  one and flip which is default — flagged for a follow-up decision, not
  blocking.
- **[Done 2026-08-08] Meetings index page, sitemap.xml/robots.txt, and
  keyword search + filters — built together since search/filters narrow
  the same query the index page uses, not a separate feature.**
  `crud.list_pages()` (paginated, 20/page, `LIMIT`/`OFFSET`) backs a new
  `GET /meetings` route + `meeting_list.html`, reachable at
  `redtaperecordings.com/meetings` via a matching proxy route in
  `app/main.py`. Search box + jurisdiction/date-range/language filters
  are plain GET params on the same route (shareable/bookmarkable URLs,
  no JS required). v1 keyword search covers title + jurisdiction only,
  via a portable `.ilike()` (works on Postgres and the local SQLite
  fallback) — deliberately not full transcript-body search, since
  `segments` are JSON per `TranscriptVersion`, not a plain searchable
  column; that's flagged as a real follow-up in `BACKLOG.md`, not
  silently half-built. `GET /sitemap.xml` (`crud.list_all_page_slugs()`,
  unpaginated — fine at the current hundreds/thousands scale) plus a new
  `GET /robots.txt` on the resolver (`Disallow: /meeting` — the
  ephemeral resolver page — plus a `Sitemap:` line) give the Archive an
  actual crawl path for the first time; previously a `/m/{slug}` page
  was only reachable if you already had its exact URL. Verified live
  end-to-end (both locally and against `redtaperecordings.com`):
  pagination math, keyword search, jurisdiction/language filters
  (including a genuinely-correct edge case — `language=en` correctly
  excludes an agenda-only page with zero transcript versions, not a
  bug), combined filters, the empty-results state, and a real
  `sitemap.xml`/`robots.txt` render with absolute URLs in production.
- **[Done 2026-08-08] Bug: permanent Archive pages hardcoded `<html
  lang="en">` regardless of the actual transcript's language.**
  Confirmed live on the Simi Valley page, whose default transcript
  version is Spanish — the page declared `lang="en"` anyway. Fixed:
  `archive/main.py`'s `meeting_page()` route now passes the active
  `TranscriptVersion.language` into the template as `page_lang`
  (falling back to `"en"` for agenda-only pages with no transcript at
  all); `archive/templates/base.html` reads it via
  `{{ page_lang|default('en') }}`. Verified locally: the same Simi
  Valley page now renders `<html lang="es">`, and an agenda-only page
  (Yountville) correctly falls back to `<html lang="en">`. **Could not
  fully re-verify the non-English branch in production** against this
  specific URL — a real, separate gap surfaced while trying: Simi
  Valley had already been served 3 times from the resolver's own local
  `meeting_resolutions` cache (`hit_count: 3`, cached well before the
  Archive integration's env vars were fixed), so `/api/resolve` keeps
  short-circuiting on that local cache hit and never reaches the live
  resolve → Archive push path for this URL — confirmed directly via
  `psql` against `rtr_deeplink_db`. Production is running the identical
  code as the locally-verified build, so the fix itself isn't in doubt,
  but this exposed a real backfill gap — see the new "Bugs" entry in
  [BACKLOG.md](BACKLOG.md).
- **[Done 2026-08-08] Opportunistic re-check on a permanent-page hit.**
  Cadence decision made and built: a hit on an existing Archive page
  triggers a background re-resolve + re-push only if the page hasn't been
  touched in `ARCHIVE_RECHECK_AFTER` (30 days, `app/main.py` — not derived
  from measured data, a reasonable middle ground between "government
  caption pipelines can take weeks to catch up" and "don't hammer the
  source site on every visit to a popular meeting"). `GET /internal/lookup`
  (`archive/main.py`) now returns the page's `updated_at`; the resolver's
  `archived`-hit branch in `resolve()` parses it (`_parse_updated_at()`,
  treating a naive timestamp as UTC — SQLite doesn't enforce tz-awareness
  the way Postgres does, so which shape comes back depends on which DB the
  Archive happens to be running against) and fires
  `_recheck_archived_page()` via `BackgroundTasks` when stale, never
  blocking the redirect response. Reuses the same finder + `archive_client.
  push()` path as a fresh resolve.

  **Real bug found and fixed while verifying this**: `MeetingPage.
  updated_at`'s `onupdate=func.now()` (`archive/db/models.py`) only fires
  when SQLAlchemy actually detects a changed attribute — but
  `ingest_resolution`'s existing-page branch (`archive/db/crud.py`)
  reassigns `page.title`/`.date`/etc. to values that are usually identical
  to what's already stored, which doesn't dirty the row. Confirmed live
  with an isolated script: backdating `updated_at` and re-ingesting the
  exact same payload left it unchanged, meaning a re-check that found no
  new content would never stop being "stale" and would re-fire on *every*
  subsequent hit — precisely the hammering problem this feature exists to
  prevent. Fixed by having `ingest_resolution` explicitly set
  `page.updated_at = datetime.now(timezone.utc)` on every existing-page
  ingest, regardless of whether any field actually changed, so it reliably
  means "last time this page was checked."

  Verified live end-to-end with two local uvicorn processes (resolver +
  Archive, isolated ports/SQLite files to avoid colliding with other local
  activity against the conventional 8010/8020 dev ports): pushed a real
  Simi Valley meeting, backdated its `updated_at` to simulate a stale page,
  then resolved the same URL twice in a row. First hit: fast redirect
  response plus exactly one background `POST /internal/ingest` (the
  re-check). Second hit, immediately after: redirect only, no re-check —
  confirming the now-fresh `updated_at` correctly suppressed a repeat
  trigger. Ran the project's existing `pytest` suite (`tests/`, added
  concurrently by another session working this same backlog) before and
  after — all passing, no regressions from either change.

## Testing infrastructure

- **[Done 2026-08-07] Fixture-based pytest suite, from Claude's own
  suggested backlog (`CLAUDE_BACKLOG.md`).** 47 tests across
  `tests/test_vtt_parser.py`, `test_media_scan.py`, `test_base.py`, and
  end-to-end adapter tests for Granicus/Legistar/CivicPlus/CivicClerk.
  Built on branch `claude-backlog/round-1`.

  Real fixtures, not synthetic, wherever a live fetch was possible during
  this session (2026-08-07): Granicus — Napa City clip 3450 (genuinely
  blank captions.vtt, the real 8-byte placeholder) and Simi Valley clip
  2840 (the exact real Spanish-caption meeting `BACKLOG_DONE.md` already
  documents above); Legistar — a real `maricopa.legistar.com/Calendar.aspx`
  page (confirms the calendar pick-list against real markup); CivicClerk —
  real `clovisca.api.civicclerk.com` API responses for two real events (20:
  direct mp4 + 31 real agenda bookmarks; 17: `externalVideoUrl`/YouTube
  fallback, zero bookmarks). CivicPlus is the one exception: the real site
  this adapter was originally verified against
  (`ca-westlakevillage.civicplus.com`) has since been restructured (302s to
  a JS-redirect stub, no `AgendaCenter` markup) and the plain
  `civicplus.com` subdomain no longer resolves at all — that fixture is
  hand-built to match the exact real markup shape `civicplus.py`'s own
  docstring documents as confirmed live on 2026-08-06, not a guess (see
  `tests/fixtures/civicplus/README.md`).

  **Real tooling finding**: `aioresponses` (latest release, 0.7.9) doesn't
  support the aiohttp version this project's unpinned `aiohttp>=3.9`
  requirement resolves to today (3.14.3) — its `_build_response` omits the
  now-required `stream_writer` kwarg to `ClientResponse.__init__`, a hard
  `TypeError` on every mocked request. Rather than pin the app's real
  dependency down just to satisfy a test-only library, wrote a small
  self-contained `tests/aiohttp_mock.py` that monkeypatches
  `aiohttp.ClientSession.get` directly — a `FakeResponse`
  (status/text/read/json/raise_for_status) plus a `mock_session({url:
  FakeResponse})` context manager, exact-URL-keyed. Same "actively
  maintained dependency chasing a moving target" risk category as yt-dlp
  (see the working-conventions note in `CLAUDE.md`) — worth rechecking
  whether `aioresponses` has caught up next time this suite needs
  extending.

  **Two real bugs found while building this, unrelated to the feature
  being tested**:
  1. `media_scan.scan_media_urls`'s `"sources"` JSON-blob regex branch was
     dead code — confirmed via a unit test that its `[^}]*\]` could never
     span the closing `}` of an object inside the array, so no input shape
     that would produce a `source["src"]`-consumable dict could ever
     match. Not a live bug (both callers, Granicus and Swagit, already get
     real URLs from the plain regex patterns tried first) — flagged as a
     live `BACKLOG.md` item first, then removed outright (rather than
     fixed) the same day, since a "working" JSON-aware replacement would
     still be unverified against any real page. The regression test was
     renamed to `test_scan_media_urls_sources_json_branch_was_removed_as_
     dead_code` and still asserts the same input yields no URLs, now
     because the branch is gone rather than because it never matched.
  2. A test-writing mistake that would have hidden a **real fixture bug**
     if not caught: an early draft of the CivicClerk "externalVideoUrl
     fallback" test reused event 20's real `Events/20` JSON with only the
     `id` field patched to 17 — but event 20's `mediaStreamPath`/
     `mediaSourcePathMp4` fields are themselves populated with event 20's
     real direct mp4 URL, so the test would have silently asserted against
     the wrong video source (the shadowing field, not the fallback path it
     claimed to test) had the assertion not been checked against the real
     API response first. Fixed by fetching and saving event 17's own real
     `Events`/`EventsMedia` JSON instead of hand-editing a different
     event's — a reminder that even a "real fixture" test can lie if it's
     assembled from mismatched real pieces.

  Not yet covered: Swagit, eScribe, CA Legislature, PrimeGov/YouTube
  adapters (no test files yet — README's "Running tests" section flags
  this as the natural next extension), and the `app/db/` and `archive/`
  layers (no fixtures or tests for either). `requirements-dev.txt` and
  `pytest.ini` (`asyncio_mode = auto`) added; see README's new "Running
  tests" section for how to run it.

- **[Done 2026-08-08] Six more items from `CLAUDE_BACKLOG.md`, all on
  branch `claude-backlog/round-1`.** Verified live against real running
  instances of both services (not just unit tests) for every item below.

  **PWA manifest.** `app/static/manifest.json` + a new `app/static/icon.svg`
  (a square 192x192 SVG in the site's existing dymo-label red/navy, "RTR"
  monogram — SVG-only, no PNG fallback generated, so pre-maskable-icon
  Android/iOS install flows may not pick it up; a real gap, not silently
  claimed to be complete). Linked from both `app/templates/base.html` and
  `archive/templates/base.html` (`/static/manifest.json` is reachable from
  Archive-served pages too since `/static/` is mounted on the resolver,
  same-origin regardless of which service rendered the HTML).

  **schema.org `VideoObject` JSON-LD** on `archive/templates/meeting_page.html`,
  gated on `page.video_url` existing. `contentUrl` for a direct file
  (mp4/m3u8), `embedUrl` for YouTube (schema.org distinguishes the two).
  `duration` computed for real from the active transcript's last segment
  end time when one exists. No `thumbnailUrl` (this app doesn't generate
  one — same underlying gap as the missing `og:image`), so this likely
  isn't rich-result-eligible yet, just valid structured data. Verified via
  a standalone Jinja render (both a real-data case and a no-video case
  that correctly emits no `<script>` block at all).

  **Rate limiting on `/api/resolve`** via `slowapi`, keyed by client IP
  (`get_remote_address`), 20/minute. Verified live: 21 rapid requests
  against a real local server returned `200` x20 then `429` with
  `{"error":"Rate limit exceeded: 20 per 1 minute"}`. Real production
  correctness issue caught and fixed in the same pass: Render's edge
  proxy means `request.client.host` would otherwise show Render's own
  proxy IP for every request (making the limiter either a no-op shared
  across all real users, or a way one heavy caller starves everyone else)
  — `render.yaml`'s `startCommand` for the resolver now passes uvicorn
  `--proxy-headers --forwarded-allow-ips='*'` so `X-Forwarded-For` is
  trusted from Render's proxy specifically, a standard pattern for
  PaaS-hosted uvicorn. In-memory limiter storage (slowapi's default) is
  fine for the current single-instance free-tier deploy; would need a
  shared backend (Redis) to stay correct across multiple instances.

  **Transcript export (TXT/SRT).** Two different implementations for two
  different architectures, deliberately not shared code: the Archive's
  permanent pages get real server-side download endpoints
  (`GET /m/{slug}/transcript.{txt,srt}` in `archive/main.py`, formatting
  via new `archive/utils/transcript_export.py`, covered by
  `tests/test_transcript_export.py`) since the data is actually persisted
  there; the ephemeral resolver page (`app/templates/meeting.html`) has no
  server-side persistence at all (that's the whole point of this app per
  README), so its "Text"/"SRT" buttons build the file **client-side** in
  `app/static/player.js` from the `segments` array already in memory, via
  a `Blob` + synthetic download link. Verified live end-to-end: real HTTP
  downloads from the Archive endpoint (content-disposition header and
  body both correct, against a real 394-segment Simi Valley transcript),
  and the resolver's client-side path exercised directly in-browser
  (`downloadTranscript('txt')` triggered with no errors, output format
  confirmed to match the server-side formatter byte-for-byte in
  structure).

  **RSS feed of newly-archived meetings**, `GET /feed.xml` on the Archive
  (optionally `?jurisdiction=`), proxied through the resolver the same
  way `/sitemap.xml` already is. New `crud.list_recent_pages_for_feed()`
  (deliberately separate from the `/meetings` index's `list_pages()` —
  a feed just wants "last N, optionally scoped to one jurisdiction," no
  pagination). Autodiscovery `<link rel="alternate">` plus a visible "RSS
  feed" link added to `/meetings`. **Real bug found and fixed before
  shipping**: `feed.xml.jinja`'s name ends in `.jinja`, not `.xml` —
  `jinja2.select_autoescape()` keys off the literal extension, so
  autoescape was silently OFF for this template (same latent gap already
  present in `sitemap.xml.jinja`, harmless there only because it
  interpolates slug/date, not free-text titles). A real meeting title
  containing a bare `&` or `<` produced invalid, unparseable XML —
  confirmed via `xml.etree.ElementTree.fromstring()` failing on the
  unescaped output. Fixed by explicitly `|e`-escaping every interpolated
  value rather than relying on filename-based autoescape detection;
  `tests/test_feed.py` pins this down as a regression test. Also fixed:
  the feed's own `atom:link[rel=self]` initially built itself from
  `str(request.url)`, which — since this service is only ever reached
  through the resolver's proxy — reflected the Archive's own internal
  host:port, not the public one; switched to the same `PUBLIC_BASE_URL`-based
  `base_url` already used for canonical/OpenGraph URLs elsewhere in this
  app. Verified live through the real proxy chain (resolver → Archive →
  real SQLite-backed `MeetingPage` row), both unfiltered and with a real
  `?jurisdiction=` filter.

  **"Report a problem" feedback control**, on both the resolver's
  ephemeral page and the Archive's permanent pages. New `ProblemReport`
  table (`app/db/models.py`) + `POST /api/report-problem` (rate-limited,
  10/minute) + a token-gated `GET /admin/problem-reports`, mirroring the
  existing `/admin/log` pattern. Deliberately lives only on the resolver's
  DB (not a second table on the Archive) — reports from an Archive page
  reach it via a same-origin `fetch()`, since `/api/*` isn't part of the
  Archive proxy and Archive pages are served from the same public domain
  either way. **Real bug caught before shipping, not just after**: the
  first version wrapped `crud.log_problem_report()` in the existing
  `safe()` helper and checked `if result is None` to detect a storage
  failure — but `log_problem_report` itself returned `None` on *success*
  too (a bare `-> None` function), making success and failure
  indistinguishable and the error path effectively unreachable. Fixed by
  having it return `True` on success before ever running it live. Also
  corrected mid-build: an initial draft only treated `result is None` as
  a failure when `DATABASE_URL` was set, based on a false assumption that
  no-`DATABASE_URL` meant "no database" — this app always has *some*
  database (local SQLite fallback, per `engine.py`), so that condition
  would have silently swallowed real write failures in local/no-Postgres
  setups. Verified live end-to-end in-browser on both surfaces: a real
  submission from the resolver's `/meeting` page (filled form, submitted,
  "Thanks — we'll take a look." shown) confirmed to actually land in the
  DB via `GET /admin/problem-reports`; the Archive page's toggle/form
  confirmed to reveal correctly too. `.cassette-btn` reused for the
  submit button — technically outside the "just two buttons" scope
  `app/static/style.css`'s own comment claims, but consistent with
  `archive/templates/meeting_list.html`'s pre-existing "Search"/"Apply
  filters" buttons already extending past that scope; not re-litigated
  here, just noted.

- **[Done 2026-08-08] CivicClerk closed captions, previously unverified,
  now implemented from a real user-supplied example.** The user found a
  real CivicClerk event with populated captions —
  `emporiaks.portal.civicclerk.com/event/585/media` (Emporia, KS) —
  after 8 sampled cities across two sessions had all come back with null
  caption fields (`BACKLOG.md` had accumulated a theory that captioning
  is an opt-in add-on most customers don't turn on; this doesn't disprove
  that, just confirms it's real and working when a city does).

  **Real format finding, not assumed**: the caption file is **SRT, not
  VTT** — `closedCaptionTracks[].file` is a `.srt` URL
  (`cpmedia.azureedge.net/emporiaks/ClosedCaption/....srt`). This
  codebase had no SRT parser at all before this (`app/utils/vtt_parser.py`
  was VTT-only). New `parse_srt()` added there.

  **Real bug caught before shipping**: SRT differs from VTT in that each
  cue is preceded by a standalone sequence-number line ("1", "2", ...).
  Feeding raw SRT text into the existing `parse_vtt()` directly is unsafe
  — once the first cue is open, a later sequence-number line doesn't
  match the timestamp regex, so `parse_vtt`'s loop treats it as more cue
  *text*, silently appending the next cue's index number to the end of
  the current cue. Confirmed on the real 3677-cue Emporia file before the
  fix (every cue but the last corrupted); `parse_srt()` strips
  sequence-number lines first (only when immediately followed by a
  timestamp line, so a caption that's legitimately just a number is never
  touched) before reusing `parse_vtt`'s cue-accumulation logic.
  `tests/test_vtt_parser.py` pins this down with both a minimal synthetic
  case and the real fixture, asserting no cue's text is left over as a
  bare number.

  `app/platforms/civicclerk.py`'s `resolve()` rewritten to actually fetch
  and parse captions instead of showing a "not verified yet" warning:
  tries `closedCaptionTracks` first (richer — supports multiple language
  tracks, mirroring Granicus/eScribe's real-content-language-detection
  pattern rather than trusting any `label` field), falls back to a bare
  `closedCaptionUrl`/`transcriptionUrl` when there's no tracks array
  (matching the fallback order in the reference implementation the user
  supplied). Dispatches VTT vs. SRT parsing by the caption URL's file
  extension, since there's no other signal available. Verified live
  end-to-end against the real Emporia event: 3677 real segments, English
  correctly detected from content (not a label), zero transcript
  warnings, real title/date/jurisdiction/video/26 real agenda items — and
  in-browser, confirming the transcript actually renders on the page with
  no console errors. `tests/test_civicclerk.py` gained a third real-fixture
  test (`Events/585` + `EventsMedia/585` + the real 272KB `.srt` file) for
  this exact case, and `BACKLOG.md`'s "unverified" bug item was removed
  since it's now a positively-confirmed, tested, working path.

- **[Done 2026-08-08] Generalized the CivicClerk SRT lesson across every
  caption-fetching adapter: wider format *detection* everywhere, real
  *parsing* for TTML/DFXP/ITT, best-effort text fallback for the rest.**
  Directly prompted by discussing what the SRT fix implied more broadly —
  the same "assumed VTT because that's what everything else uses" mistake
  was a live risk on Granicus and CA Legislature specifically, which both
  filtered caption candidates to `.endswith(".vtt")` even though the
  shared page scanner already recognized `.srt` as a subtitle URL and
  would have silently skipped one if a customer ever linked to it.

  **New in `app/utils/vtt_parser.py`**: `parse_ttml()` (real structured
  parser for TTML/DFXP/ITT — XML `<p begin= end=>` cues, namespace-agnostic
  tag matching since vendors vary on `tt:p` vs. a default namespace,
  clock-time and offset-time timeExpression support, frame/tick-based
  timing explicitly skipped rather than guessed at since there's no frame
  rate available to convert with); `strip_unknown_caption_markup()` (a
  deliberately generic, format-agnostic best-effort text extractor for
  SBV/SUB/SMI/SAMI/plain-.txt — strips markup tags, MicroDVD-style
  `{123}{456}` frame markers, and SRT/SBV-style timing lines, keeps
  whatever real text remains, no per-line timestamps); and
  `parse_captions_by_extension(url, content)`, a single dispatch point
  every adapter now goes through instead of each reimplementing its own
  extension-sniffing — returns `(cues, fallback_text)`, exactly one
  populated on success, both empty for a genuinely unreadable format
  (`.scc`/`.stl`, real binary/encoded formats with nothing extractable
  without real codec decoding). A bare `.xml` extension is ambiguous
  (some vendors export real TTML with a plain `.xml` extension rather
  than `.ttml`), so that case probes `parse_ttml()` first — a safe probe
  since it returns `[]` cleanly on non-TTML-shaped input, not a guess
  that could corrupt anything — before falling through to the generic
  text fallback.

  **`app/platforms/media_scan.py`** (the shared scanner Granicus/Swagit/CA
  Legislature all use) now recognizes `.ttml`/`.dfxp`/`.itt`/`.scc`/
  `.stl`/`.sbv`/`.sub`/`.smi`/`.sami` unconditionally, plus `.xml`/`.txt`
  only when the URL path also looks caption-related (`caption`,
  `subtitle`, `transcript`, or `/cc[_./-]`) — those two extensions are too
  generic to match unconditionally (would also catch sitemap references,
  analytics config, any random text file on the page); confirmed via a
  real test that a real `sitemap.xml` correctly stays unmatched while a
  `ClosedCaption/....srt`-shaped URL correctly matches. `media_type()`
  applies the same keyword gate independently (not just relying on
  callers to have already gone through the gated scanner), since it's a
  general classifier some caller might run on an un-scanned URL (e.g. a
  caption URL straight from an API field, as CivicClerk does).

  **Adapter changes** (Granicus, CA Legislature, Swagit, CivicClerk — the
  four that ever fetch a caption file): each now tries every detected
  caption URL through `parse_captions_by_extension`. Structured results
  (`cues`) go through the exact same language-detection/best-track/
  garbled-check logic as before (Granicus/CivicClerk's multi-track
  selection was untouched, just fed from a wider candidate pool).
  Unstructured `fallback_text` becomes `segments` with every non-blank
  line as its own pseudo-cue at `start=0.0, end=0.0` (deliberately not a
  new model field — reuses the existing transcript-list rendering path
  for free, and a click still seeks to a valid position, just not a
  precise one), with a warning explaining the format limitation. Neither
  produced anything (binary formats, or a text-based one that came back
  genuinely empty) surfaces a direct "you can view it directly: {url}"
  warning instead of silence, mirroring the existing `AgendaViewer.php`
  fallback-link pattern. Swagit gained an entirely new code path here —
  it previously only ever tried `#transcript-fragments` (a DOM mechanism,
  still unverified per BACKLOG.md) and never looked at `media_urls` for a
  real caption *file* at all.

  **Everything re-verified live against the real meetings already used to
  build these adapters, confirming zero regressions**: Simi Valley
  (Granicus, 394 Spanish segments, same warnings, same language
  detection), Napa City (Granicus, blank-caption case, same "blank"
  message + agenda fallback link), Yountville CA (Swagit, 7 agenda items,
  same video resolution), Emporia KS (CivicClerk, 3677 SRT segments, zero
  warnings) — all byte-for-byte identical output to before this change.
  CA Legislature's real hearing samples from earlier sessions couldn't be
  re-located (no ID was ever recorded, and a live search for a current
  hearing with a populated caption track didn't turn one up in a
  reasonable amount of searching) — covered instead by new synthetic
  tests, including one confirming the real `/thumbnails/` scrubber-sprite
  VTT exclusion still holds under the wider extension list.

  **New test coverage**: 31 tests in `tests/test_vtt_parser.py` (up from
  14) covering `parse_ttml` (clock-time, offset-time, namespace prefixes,
  nested markup, frame-based-time skipping, malformed XML),
  `strip_unknown_caption_markup` (SBV/MicroDVD/SAMI shapes), and
  `parse_captions_by_extension`'s full dispatch tree; `test_media_scan.py`
  gained detection tests for every new extension plus the xml/txt
  keyword-gate (both positive and negative cases); Granicus/CivicClerk
  gained synthetic (not real — no non-VTT/SRT caption file has ever been
  observed on either platform) tests for both the text-fallback and
  link-only paths; and **CA Legislature and Swagit each got their first
  test file ever** (`test_ca_legislature.py`, `test_swagit.py`), scoped
  to the new caption-fallback logic specifically rather than full adapter
  coverage — the broader gap (no coverage of these two adapters' core
  resolve() flow at all) is still open, noted in the "Testing
  infrastructure" entry above.

- **[Done 2026-08-08] Permanent Archive page stuck showing no transcript
  after an adapter fix, with no way to refresh it besides waiting up to
  30 days — fixed with an on-demand admin recheck endpoint.** Found while
  investigating why `redtaperecordings.com/m/emporia-ks-2026-07-22-commission-meeting`
  (CivicClerk event 585) showed no transcript despite the SRT caption fix
  above being able to find one: that page had been pushed to the Archive
  *before* the fix landed, and `/api/resolve` checks the Archive before
  ever calling the adapter again ([app/main.py](app/main.py)) — so once a
  permanent page exists, every repeat visit just redirects to it,
  confirmed live by re-pasting the source URL and watching it bounce
  straight back with no new resolve. The only existing refresh path,
  `ARCHIVE_RECHECK_AFTER` (a 30-day passive background recheck on a stale
  lookup hit), hadn't elapsed for this page.

  **Fix**: `_recheck_archived_page()` (the function the passive recheck
  already used) changed from a fire-and-forget `-> None` to returning a
  summary dict (`pushed`, `platform`, `title`, `segment_count`,
  `agenda_item_count`, `transcript_warnings`, `video_warnings`) — the
  passive `BackgroundTasks` caller still discards it, unaffected. New
  `GET /admin/recheck-archive-page?token=&url=` calls it directly and
  awaits it synchronously (unlike the passive path, the caller here is
  explicitly waiting to see the outcome), gated by the same
  `ADMIN_STATS_TOKEN` pattern as the other `/admin/*` routes (404 on a
  bad/missing token, not 401/403, so it's not distinguishable from a
  typo).

  An earlier version of this fix was a one-off shell script
  (`scripts/refresh_archive_page.py`) meant to be run from a Render
  Shell, written before discovering the production plan doesn't have
  Shell access. Removed once the HTTP endpoint made it unnecessary — no
  reason to maintain two ways to do the same thing, and the endpoint
  works from anywhere (browser, curl, no Render access needed at all)
  rather than only from a shell on that one service.

  **Verified live end-to-end**: 84/84 tests still pass locally after the
  refactor. Once deployed, `curl
  ".../admin/recheck-archive-page?token=$ADMIN_STATS_TOKEN&url=https://emporiaks.portal.civicclerk.com/event/585/media"`
  (run from the user's own Render Shell, token substituted from that
  container's own env — never typed/pasted anywhere) returned
  `{"pushed":true,"platform":"civicclerk","title":"Commission
  Meeting","segment_count":3677,"agenda_item_count":26,
  "transcript_warnings":[],"video_warnings":[]}`. Reloading the permanent
  page immediately after confirmed the Transcript section now renders (a
  `<h2>Transcript</h2>` heading present, 3703 `.transcript-segment`
  elements — 3677 transcript lines + 26 agenda items, both reusing the
  same CSS class per the Agenda section's markup-reuse design — with the
  first three real lines: "CALL MEETING TO ORDER", "MEMBERS PRESENT",
  "PROCLAMATIONS").

  Residual gaps intentionally left open, split back out into
  [BACKLOG.md](BACKLOG.md): the *passive* 30-day recheck cadence still
  doesn't vary by transcript quality (this fix only added the on-demand
  manual path, not a smarter automatic one), and Emporia's own
  `eventBookmarks` all reporting `markerTimeStart: 0` (a separate, real
  source-data quirk noticed during this same investigation, unrelated to
  the missing-transcript bug) is still unaddressed.

- **[Done 2026-08-08] Granicus: video missing on cities whose
  `MediaPlayer.php` only embeds a legacy Flash player, fixed with a
  fallback to Granicus's newer `/videos/{id}/player` page.** Found via a
  user-reported real meeting,
  `redtaperecordings.com/m/city-of-fountain-valley-city-council-meeting-jun-16th-2026`
  (source: `fountainvalley.granicus.com/MediaPlayer.php?clip_id=607`),
  which showed no video at all. Root cause, confirmed directly against
  the live page: `MediaPlayer.php`'s HTML embeds only a `modernplayer.swf`
  Flash object whose `VideoUrl` param points at `ASX.php?...&stream_type=
  rtmp` — RTMP, unplayable in any modern browser, not a bug in our
  scanner correctly ignoring it. `GranicusAssetFinder` only ever fetched
  the originally-submitted page, so for a city on this legacy template
  there was never any `.m3u8`/`.mp4` to find. Separately confirmed
  Granicus does have a real, working HLS stream for the same clip, just
  on a page this adapter never fetched:
  `fountainvalley.granicus.com/videos/607/player`, which loads `hls.js`
  against a genuine `archive-stream.granicus.com/.../playlist.m3u8`.

  **Fix** (`app/platforms/granicus.py`): extracted the existing
  m3u8-preferred/mp4-fallback selection logic into a new
  `_pick_video_url()` staticmethod (previously inlined in `resolve()`),
  and added `_fetch_video_from_player_page()` — only called when the main
  page's candidates yield no video, so cities where it's already found
  there (the common case) pay no extra request. Single-attempt, not
  `_fetch_page`'s retry-with-backoff (matching `_fetch_caption_file`'s
  style) — this is an opportunistic fallback probe, not the one request
  the whole resolve depends on, so a slow/dead player page fails cheap
  rather than costing multiple retries with exponential backoff on every
  affected city.

  **Verified live end-to-end, twice**: first against Granicus's own
  `/videos/607/player` page directly in-browser (`readyState: 4`,
  i.e. fully loaded and playable, confirmed by actually calling
  `.play()` and watching `currentTime` advance) — ruling out that the
  discovered stream URL itself was somehow dead despite existing (a real
  risk: a bare `curl` to the same m3u8 URL got a 403 from Granicus's CDN,
  almost certainly hotlink/bot protection rather than a broken stream,
  since the real browser fetch succeeded fine). Then against this
  resolver's *own* frontend, run locally (`uvicorn app.main:app --port
  8010`) against `/meeting?url=<the real clip 607 URL>` — confirmed the
  video element reaches `readyState: 4` and visibly renders the real
  Fountain Valley council chamber footage (screenshot: title card "City
  Council Study Session Meeting, June 16, 2026", duration 7:31:13
  matching the stream's real `duration: 27073.36`s), ruling out a
  same-origin-only quirk (Granicus's own domain vs. a cross-origin
  `hls.js` fetch from `redtaperecordings.com` could plausibly have hit a
  different CORS/referrer outcome — it didn't).

  Incidentally, this is the same meeting CLAUDE.md already flagged as a
  useful caption-parsing sample ("language misdetected as Portuguese")
  — separately confirmed during this same investigation to be genuinely
  garbled at the source: fetched the real `.vtt` directly from Granicus,
  it's structurally valid WebVTT (correct header/timestamps) but the cue
  *text* is garbage (`###...@@@@@@@kkIkkkkk~kkkkkkkook?Ek?E?E?E`) —
  Granicus's own captioning pipeline failing for this meeting, not a
  decoding bug on our end. `langdetect` calling that noise `'pt'` is
  expected garbage-in/garbage-out behavior; the system already handles
  it correctly (`is_likely_garbled` fires, the "looks garbled at the
  source... treat it as approximate" warning shows). Nothing to fix
  there — CLAUDE.md's sample-list entry updated to describe it
  accurately (garbled-hence-misdetected, not just misdetected) and to
  note the video gap is now fixed.

  **New test coverage**: `tests/test_granicus.py::
  test_resolve_falls_back_to_player_page_for_video_when_mediaplayer_has_none`,
  backed by three new real fixtures (`fountainvalley_clip607_mediaplayer.html`,
  `fountainvalley_clip607_player.html`, `fountainvalley_clip607_captions.vtt`,
  all fetched live 2026-08-08) — pins the exact real m3u8 URL, `m3u8`
  format, zero video warnings, 146 real (garbled) segments, and the
  `'pt'`/garbled transcript warnings together, so this exact case can't
  silently regress. The three existing synthetic caption-fallback tests
  (blank-guessed-captions, unstructured-text-fallback, unreadable-format)
  needed a `/videos/{id}/player` 404 route added to their existing mocks,
  since none of their fixtures have a video either and would otherwise
  now trigger the new fallback request unmocked.

- **[Done 2026-08-08] Swagit and CA Legislature never ran language
  detection, so real English transcripts showed no "en" on the
  `/meetings` listing.** User-reported from the Browse Meetings page:
  "Jan 13, 2026 City Council" (Dublin, CA, Swagit) showed a bare
  jurisdiction/date with no language and no "agenda only" tag despite
  clearly having a real transcript. Root cause, confirmed by reading
  every adapter: Granicus and CivicClerk both call content-based language
  detection (never trusting a source `srclang` label — see the Simi
  Valley Spanish-mislabeled-`en` finding elsewhere in this file) and pass
  `transcript_language` through; `SwagitAssetFinder` and
  `CaliforniaLegislatureAssetFinder` never called it at all, leaving the
  field permanently `None` for every meeting on either platform,
  regardless of transcript quality. Masked on each individual meeting
  page because `archive/main.py`'s `page_lang` defaults to `"en"` when
  the stored value is falsy (`(active_version["language"] if
  active_version else None) or "en"`) — correct for the `<html lang>`
  attribute's own purpose, but it meant the gap was invisible anywhere
  except the `/meetings` list, which shows the raw stored value with no
  such fallback.

  Incidentally confirms a previously-"unverified" path for real: Dublin's
  Jan 13, 2026 meeting (Swagit clip 372020) has a genuine 36,072-cue
  English transcript via `#transcript-fragments a[data-ts]` (one word per
  cue) — `SwagitAssetFinder`'s class docstring and
  [BACKLOG.md](BACKLOG.md) both said this DOM path had "never been
  populated in any sample checked." It's real; that unverified note is
  removed. Separately confirmed a real Senate floor session
  (`senate.ca.gov/media/senate-floor-session-20260806`, 3,084 cues) has
  the same missing-language gap on the CA Legislature side.

  **Fix**: extracted the two byte-identical `_detect_cue_language`
  copies already duplicated across `granicus.py` and `civicclerk.py` into
  one shared `detect_language_from_texts()` in `app/utils/vtt_parser.py`
  (took a plain `Iterable[str]` rather than a cue-dict shape, since
  Swagit/CA Legislature's segments are already `TranscriptSegment`
  objects, not raw dicts, at the point language needs detecting) — three-
  strikes-you-extract, not premature, since this was about to become a
  fourth copy. `swagit.py` now detects language once from whichever real
  segments it found (`#transcript-fragments` or the caption-file
  fallback); `ca_legislature.py` detects it for both its structured-cue
  and unstructured-text-fallback paths.

  **Verified live end-to-end** against both real meetings that surfaced
  the gap: Dublin clip 372020 (`transcript_language: "en"`, 36,072
  segments) and the Senate floor session (`transcript_language: "en"`,
  3,084 segments, real `.m3u8` video URL too). 87/87 tests pass (85
  existing + 2 new: `test_swagit.py::
  test_resolve_detects_language_from_transcript_fragments` and
  `test_ca_legislature.py::test_resolve_detects_language_from_real_captions`,
  both synthetic — coherent English sentences fed through the same
  `#transcript-fragments`/caption-file code paths, pinning that language
  detection actually fires and gets wired through to
  `ResolvedMeeting.transcript_language`). Only fixes future resolves —
  the two real meetings' existing permanent Archive pages still need the
  same `/admin/recheck-archive-page` treatment as Emporia/Fountain Valley
  before this shows up live on `/meetings`.

  While auditing the `/meetings` listing for this, found a third,
  structurally different bug on the same page (a permanent page frozen
  with output from a since-removed code path, not fixable by a recheck at
  all) — kept as its own open item in [BACKLOG.md](BACKLOG.md) rather than
  folded in here, since the fix shape is completely different.

- **[Done 2026-08-08] `/meetings` search now covers transcript/agenda
  text, with an exact/fuzzy toggle, replacing the old title/jurisdiction-
  only keyword box.** User-requested: transcription errors mean a
  literal word like "traffic" can show up in a real transcript as
  "trafic" or "traffiq", so a plain substring search would silently miss
  real matches. Also dropped the `language` text-filter field per the
  request and added `has_transcript`/`has_agenda` checkboxes instead —
  more directly useful than a free-text language guess, and fixes real
  cases already found in this session (Yountville's stale/misleading
  transcript-shaped agenda, the Emporia/Fountain Valley pages before
  their admin-recheck refresh) being invisible to filter on before.

  **Design decision, made deliberately, not a placeholder:** no schema
  change, no Postgres-only extension. `archive/utils/search.py` does
  exact (plain substring) and fuzzy (bounded Levenshtein per word,
  threshold scaled by word length: 0 for <=4 chars, 1 for 5-7, 2 for 8+)
  matching in pure Python, over text read from the same JSON columns
  that already exist — no new column, so nothing to migrate. Exact is
  the default (per the user's explicit ask, "that way when searches run,
  they'll default to the faster one") since it skips per-word distance
  computation entirely. This is a real, acknowledged scale limit, not an
  oversight — see the new "Search: move to a materialized/indexed
  column" entry in [BACKLOG.md](BACKLOG.md) for what outgrowing it looks
  like and why it isn't built that way yet.

  **`archive/db/crud.py`'s `list_pages()` rewritten**: `has_transcript`
  still filters in SQL (cheap, no JSON involved — it's just "does a
  default `TranscriptVersion` row exist"). Transcript `segments` are only
  ever pulled from the DB when a keyword search is actually running,
  so a plain filter-only browse of `/meetings` never drags every
  meeting's full transcript JSON over the wire for nothing (Dublin's
  real 36k-segment transcript alone is over a megabyte of JSON — see the
  Swagit language-detection entry above). `has_agenda` and keyword
  matching can only be evaluated once content is in hand, so pagination
  for those runs in Python over the SQL-filtered candidate set instead
  of `LIMIT`/`OFFSET` — a real behavior change from before, fine at
  today's scale, called out explicitly in the function's own docstring
  for whoever touches this next.

  **Verified**: `tests/test_archive_search.py` (5 new tests, pure
  functions, no DB/mocking needed) pins the exact-vs-fuzzy behavior
  directly, including the motivating "traffic"/"trafic"/"traffiq"
  example and that short words (<=4 chars) require an exact token match
  rather than fuzzing into unrelated words ("cat" must not match "car").
  End-to-end verified live against a local archive service + seeded
  SQLite data (not synthetic-only): exact search for "traffic" found a
  real transcript containing it, the same search for the typo "trafic"
  correctly found nothing in exact mode and correctly found it in fuzzy
  mode, `has_agenda`/`has_transcript` checkboxes correctly filtered a
  two-meeting seed set, and the rendered `/meetings` page (screenshotted)
  showed both checkboxes, the language/​"agenda only" badges, and
  filter-state persistence through a real "Apply filters" submit — not
  just checked via the Python API. 92/92 tests pass.

- **[Done 2026-08-08] On-demand transcription from audio — a viewer can
  request our own transcript when the source's own captions are missing,
  garbled, or wrong-language.** User-designed feature, planned in detail
  before building (job execution infra, transcription engine, and
  email-verification strictness were all explicit decisions the user made
  rather than defaults picked silently). Real product goals stated
  alongside the request, intentionally not built now but designed around:
  speaker diarization + a name-mapping UI, and comparing the finished
  transcript against the agenda for topic coverage — both moved to
  `CLAUDE_BACKLOG.md`.

  **Architecture: a third service.** Neither the resolver nor the Archive
  web service can run something that might take hours, so a new
  `worker/` — a persistent, paid Render Background Worker (the first
  paid, always-on infrastructure this project has needed; no free tier
  exists for this) — processes jobs in the background. Deliberately
  breaks the resolver/Archive HTTP-only separation in one direction only:
  the worker imports `archive.db`/`archive.utils.email` directly (it *is*
  Archive backend logic, just in a process shape the Archive's own web
  dyno can't offer) and `app.platforms` directly (read-only, to re-resolve
  a fresh media URL before each chunk — HLS/signed URLs can go stale over
  a long job). `app/platforms/media_probe.py`'s ffmpeg/ffprobe wrapper and
  the adapter-registration helper (`app/platforms/__init__.py`'s new
  `register_all_finders()`, extracted from what used to be nine inline
  `register()` calls in `app/main.py`) both live under `app/platforms/`
  specifically so `app/main.py`'s synchronous feasibility-check endpoint
  and `worker/main.py`'s chunk processing can share them without `app/`
  ever depending on `worker/`.

  **The flow**: feasibility check (`POST /api/transcription/check-
  feasibility` — live-resolves, then `ffprobe`s the real duration, reject
  under 5min/over 14h) → submit (`POST /api/transcription/submit`,
  re-checks feasibility server-side, never trusts a client flag) → the
  Archive creates a `TranscriptionJob`
  (`POST /internal/transcription/create-job`) → **email-verification
  rule, exactly as specified**: if the address is already in the Resend
  newsletter audience, the job queues immediately; a first-time address
  requires one confirmation-email click
  (`GET /confirm-transcription` on the resolver →
  `POST /internal/transcription/confirm`), which also opts them into the
  audience so every request after their first is frictionless → the
  worker loops claiming one chunk at a time
  (`archive/db/crud.py`'s `claim_next_chunk()`), extracting that chunk's
  audio with `ffmpeg` (re-resolved media URL, realistic User-Agent/
  Referer headers — see the Fountain Valley 403 workaround below),
  transcribing it with self-hosted `faster-whisper` (model loaded once at
  worker startup, reused for every job/chunk after that — **exactly the
  "free service that won't suck" the user asked for**, since the worker's
  cost is already fixed regardless of how much gets transcribed, no
  per-minute API meter on top), shifting timestamps from chunk-relative to
  full-meeting-relative seconds (`worker/segment_utils.py`'s
  `shift_segments()`), and persisting the result
  (`report_chunk_result()`) before moving on — checkpointed after every
  chunk specifically so a worker restart/redeploy loses at most one
  in-flight chunk, never the whole job. On the last chunk: a new
  `TranscriptVersion(source="transcribed")` is created, its language
  detected from its own real text
  (`archive/utils/language.py`, a deliberate duplicate of `app/utils/
  vtt_parser.py`'s `detect_language_from_texts()` — same reasoning as the
  existing `url_normalize.py` duplicate, keeps the Archive's web service
  from gaining a dependency on `app/`), and — closing a real,
  independently-confirmed gap — promoted to the page's default via new
  `promote_transcript_version()`.

  **Real, previously-existing bug fixed as part of this**: before this
  build, only the very first `TranscriptVersion` a `MeetingPage` ever got
  was set `is_default=True` — nothing later ever promoted a subsequent
  one, an unresolved question already flagged in this file's own Archive-
  build entry above. `promote_transcript_version()` closes it: demotes
  the previous default, promotes the new one, never deletes anything (the
  demoted version stays reachable through the existing `?version=`
  picker).

  **Schema, deliberately minimal**: new `TranscriptionJob` table
  (`archive/db/models.py`) — status machine `pending_confirmation` →
  `queued` → `in_progress` → `completed`/`failed`, `partial_segments`
  accumulated as the durable per-chunk checkpoint, `confirmation_token`.
  No migration needed (`create_all()` handles a new table, per this
  repo's existing convention). One shared-code addition to a model that's
  used everywhere: `TranscriptSegment` (`app/platforms/models.py`) gained
  an optional `speaker` field, unused by every path today including this
  one — added now, cheaply, since it's free and saves a schema touch when
  diarization is actually built (the same base `faster-whisper` model
  WhisperX already builds real diarization on top of via
  `pyannote.audio`, so this wasn't a speculative guess at the eventual
  design).

  **`ingest_resolution()` refactored**: its inline find-or-create-
  `MeetingPage` logic was extracted into `_find_or_create_page()`, since
  `create_transcription_job()` needed the exact same "find this meeting's
  permanent page, or create one" behavior (a transcription request can be
  the very first thing that ever creates a page for a meeting, same as a
  normal resolve).

  **Verified live, not just unit-tested, at every layer**:
  - `app/platforms/media_probe.py`'s `ffprobe`/`ffmpeg` wrappers against a
    real public HLS stream (Apple's bipbop test stream, 1800.00059s probed
    duration matching the stream's actual real length) — and, the
    motivating case — the **exact** Granicus CDN URL that returned a bare
    403 earlier this session (Fountain Valley clip 607, `BACKLOG_DONE.md`
    entry above): with the realistic-headers workaround, `ffprobe`
    correctly returned `27073.362074`s, matching the `7:31:13` observed
    in-browser in that earlier entry exactly.
  - `worker/transcription_engine.py`'s `FasterWhisperEngine` against real
    speech (macOS `say` → `ffmpeg`-converted audio): produced an accurate
    transcript with correct per-segment timestamps; chained with
    `shift_segments()` at a simulated chunk-3 offset (2700s) and confirmed
    the shifted timestamps were exactly right.
  - The full `TranscriptionJob` lifecycle against a real (file-based,
    isolated) SQLite session — creation, the per-page duplicate-job lock,
    the global concurrent-job cap, chunk-by-chunk claim/report,
    finalization, promotion, and the confirm-token flow (including that a
    used/wrong token correctly fails) — both by hand and as 8 real pytest
    integration tests (`tests/test_transcription_jobs.py`, using a new
    session-scoped isolated-SQLite-file fixture in `tests/conftest.py`
    added specifically for this, since no archive/db test infra existed
    before this feature).
  - Every new HTTP endpoint over real HTTP (not just direct Python calls):
    `archive/main.py`'s new `/internal/transcription/*` routes (including
    confirming the 404-not-401 auth pattern holds, and that a
    validly-shaped-but-unauthenticated request is correctly rejected) and
    `app/main.py`'s new `/api/transcription/*` routes, run together as two
    live local services — feasibility check and submit both verified
    against the real Fountain Valley meeting, including the real
    `pending_confirmation` → confirm-link → `queued` transition and the
    correctly-stripped `requester_email` in every public-facing response.
  - `worker/main.py`'s actual `process_next_chunk()` end-to-end against a
    real seeded job (real bipbop audio, real `faster-whisper` "tiny"
    model, graceful fallback when the platform re-resolve legitimately
    fails, graceful degradation when Resend isn't configured for the
    completion email) — and separately, the real `run_forever()` polling
    loop (not just the underlying function) driven end-to-end with the
    actual default `"small"` model, confirming the full production
    startup → model-load → poll → claim → process → complete path works,
    not just its pieces in isolation.
  - The full frontend flow (toggle → feasibility check → email step →
    submit → correct success/error messaging) on **both** the resolver's
    ephemeral `/meeting` page and the Archive's permanent `/m/{slug}`
    page, screenshotted, against the real Fountain Valley meeting on both.
  - `render.yaml` validated as parseable YAML with the expected structure;
    `worker/Dockerfile` reviewed by hand but **not** build-tested (no
    Docker daemon available in the build environment) — flagged as a real
    gap in `BACKLOG.md`, not silently assumed to work.
  - 111/111 tests pass (was 92 before this feature; +19 new: 5
    `test_worker_segment_utils.py`, 1 `test_media_probe.py`, 8
    `test_transcription_jobs.py` covering the DB lifecycle including the
    new language-detection-on-completion behavior, plus the
    `TranscriptSegment.speaker` field addition needed no new test since
    it's a passive schema addition with no behavior to verify yet).

  Real gaps intentionally left open (see `BACKLOG.md`'s "On-demand
  transcription" section for the full list): ffmpeg availability on the
  resolver service is unverified (may need a Docker runtime switch, same
  as the worker), the worker's Render plan sizing for `faster-whisper` is
  a guess pending real memory profiling, Resend's contact-lookup-by-email
  endpoint shape is unverified against a real account, an unconfirmed
  `pending_confirmation` job blocks new requests for that meeting with no
  expiry, and — most importantly — **nothing here has been exercised
  against actual deployed Render infrastructure yet**, only locally and
  against real external services (Granicus's CDN, Apple's test stream,
  Hugging Face's model hub) from a local/sandboxed environment.

- **[Done 2026-08-08] First real deploy of the transcription worker
  crash-looped: `worker/requirements.txt` was missing `pydantic`.** Real
  production failure, confirmed from Render's own logs immediately after
  the entry above shipped:
  `ModuleNotFoundError: No module named 'pydantic'` at `worker/main.py`'s
  very first import (`app.platforms.base` → `app.platforms.models`,
  which imports `pydantic` directly) — `worker/Dockerfile`'s image built
  fine (a real, useful data point: the un-build-tested-locally risk
  flagged above turned out fine), but the container crashed on every
  start, Render restarting it in a loop.

  **Root cause of why local testing missed this**: every local
  verification of `worker/main.py` (BACKLOG_DONE.md's entry above lists
  several) ran inside this repo's one shared dev `.venv`, which already
  had `app/`'s full `requirements.txt` (including `pydantic`, via
  `fastapi`) installed alongside `worker/requirements.txt`'s packages —
  so a genuinely missing entry in `worker/requirements.txt` specifically
  was invisible no matter how thoroughly the *code* was exercised.
  **Fix, and the methodology lesson that matters more than the one-line
  diff**: added `pydantic>=2.0` to `worker/requirements.txt`, then
  re-verified all three services — not just the worker — each in a
  freshly created, genuinely isolated venv containing *only* that
  service's own `requirements.txt` (`python3 -m venv ...` +
  `pip install -r .../requirements.txt` + a plain import, nothing
  borrowed from the shared dev environment). `app/`, `archive/`, and
  `worker/` all now confirmed to import cleanly on their own declared
  dependencies alone. Worth remembering for any future change that
  touches more than one of these three services: a shared local dev venv
  is fine for iterating quickly, but the *last* check before pushing
  anything that adds a new cross-file import needs to happen against
  each service's real, isolated dependency set, or a missing-package bug
  like this one won't surface until it's already live and crash-looping.

- **[Done 2026-08-08] Set up `HF_TOKEN` for the worker.** No code change
  needed — `huggingface_hub` (a `faster-whisper` dependency) already
  reads `HF_TOKEN` from the environment on its own; this was purely an
  infra step. `render.yaml` updated to document the (optional) env var
  slot on `rtr-transcription-worker`. User created a free Hugging Face
  account, generated a read-only access token, and added it to the
  worker's environment in Render — future model-load logs should stop
  showing the "sending unauthenticated requests" warning.

- **[Done 2026-08-08] Unconfirmed `pending_confirmation` transcription
  jobs now expire instead of blocking a page forever.** Was: an
  unconfirmed first-time request had no expiry, so it would block any
  new request for that meeting indefinitely. Fixed exactly as previously
  scoped: `archive/db/crud.py` gained `PENDING_CONFIRMATION_EXPIRY =
  timedelta(hours=48)`; `create_transcription_job()`'s duplicate-request
  check now treats a `pending_confirmation` job older than that as not
  blocking (a fresh request creates a new job instead of returning the
  stale one); `confirm_transcription_job()` was updated to match — a
  stale confirmation-email link for an expired job now returns `None`
  (same "invalid or already used" response as an unknown token) rather
  than being able to resurrect an abandoned job after a newer one may
  have already superseded it. The now-unused `ACTIVE_JOB_STATUSES`
  constant was removed rather than left dead. Verified with new tests
  (`tests/test_transcription_jobs.py::test_expired_pending_confirmation_
  is_superseded_and_unconfirmable`, backdating a real row's `created_at`
  directly): a fresh request after expiry gets a new job id, and the old
  token no longer confirms. Full suite green (115 tests) after the
  change.

- **[Done 2026-08-08] All-zero agenda timestamps (Emporia, KS's CivicClerk
  `eventBookmarks`) no longer render as false clickable `[0:00]` links.**
  User picked the "suppress + plain outline" option over "keep the links
  with a warning" — a link that looks actionable but silently does
  nothing is worse than no link at all. Implemented generically (not
  CivicClerk-specific) since the root pattern — "more than one agenda
  item, all sharing the exact same start time" — could show up on any
  platform, not just this one: `app/static/player.js`'s `renderAgenda()`
  and `archive/templates/meeting_page.html`'s agenda block (mirroring
  each other, same pattern as the rest of this codebase's duplicated
  frontend logic) both detect `items.length > 1 and every item.start ===
  items[0].start`, and when true render a plain unlinked outline with a
  one-line note ("This source doesn't provide real per-item timestamps,
  so these agenda items aren't clickable.") instead of the normal
  clickable-timestamp treatment. A single item at `0:00` is deliberately
  *not* suppressed — that's the normal case of the first agenda topic
  starting at the top of the video. Verified: full pytest suite green
  (116 tests) plus a direct Jinja-render check of all three cases
  (all-zero, normal distinct times, single item at 0:00) confirming the
  right branch renders in each.

- **[Done 2026-08-08] Worker's chunk-failure log now uses the same
  1-indexed chunk numbering as the claim-success log.** Found while
  investigating a real production timeout (`worker/main.py`'s ffmpeg
  extraction hit `_SUBPROCESS_TIMEOUT_SECONDS` on one chunk of a real
  job): the claim log used `chunk_index + 1` (1-indexed, e.g. "chunk
  11/12") while the two failure logs used the raw 0-indexed `chunk_index`
  directly, so a failure and its immediate retry looked like two
  *different* chunks in the logs (off by one) even though
  `report_chunk_result()`'s failure path never advances
  `chunks_completed`, meaning the same chunk really was retried
  correctly with no data loss. Confirmed via the actual production log:
  "ffmpeg extraction failed for chunk 11" (0-indexed = the 12th/last
  chunk) immediately followed by "Claimed job 2: chunk 12/12" (1-indexed
  = the same chunk) — genuinely confusing to read together, not a real
  bug in the retry logic itself. Fixed both failure log lines to use
  `chunk_index + 1, total_chunks` and spell out "(will retry on next
  poll)" explicitly, so a future read of these logs doesn't need this
  same investigation to know the outcome.

- **[Done 2026-08-08] Swagit's `#transcript-fragments` word-level
  segments now get grouped into readable multi-word lines.** Was: real
  data confirmed on a Dublin, CA meeting — six separate clickable
  `[0:04]`/`[0:05]` lines for the single six-word phrase "GOOD EVENING
  AND HAPPY NEW YEAR," spoken in under two seconds, since Swagit's
  `#transcript-fragments` DOM emits one `<a data-ts>` per word
  (`start == end`, a true instant) rather than real multi-word VTT/SRT
  cues like every other adapter. Fixed with a new pure function,
  `_group_word_fragments()` (`app/platforms/swagit.py`), applied only to
  the `#transcript-fragments` DOM path (not the real-caption-file path,
  which already has proper cues and shouldn't be re-merged) — a rolling
  4-second time window per line, chosen over a fixed word count or
  sentence-aware grouping (these fragments carry no punctuation at all
  to key off of). Each group's `start` is its first word's real
  timestamp, `end` its last word's. Verified against the exact real
  Dublin timestamps from the bug report
  (`tests/test_swagit.py::test_group_word_fragments_merges_real_dublin_example`)
  plus three more unit tests (empty input, single word, window-boundary
  behavior) and an updated integration test confirming the existing
  language-detection test still passes with grouped (not one-per-word)
  segments. Full suite green (121 tests).

- **[Done 2026-08-08] `ingest_resolution()` now promotes/demotes a
  page's default `TranscriptVersion` when warranted — the general fix
  for both the Yountville stale-transcript bug and the Dublin
  missing-language bug.** Was: a recheck could never improve a page's
  displayed default — `ingest_resolution()` (`archive/db/crud.py`) only
  ever *added* a new version `if segments:`, and only the very first
  version a page ever got was `is_default=True`; nothing later ever
  promoted or demoted anything. Two confirmed real bugs from this: a
  Yountville page permanently stuck showing 10 fake "transcript" rows
  that were actually a copy of the agenda (from a since-removed code
  path), and a Dublin page permanently stuck showing no language on
  `/meetings` even after `swagit.py`'s language-detection fix landed,
  because a fresh recheck would only ever add a *second*,
  correctly-labeled version without promoting it over the stale one.

  Fixed with two new helper functions plus a new `current_default`
  lookup at the top of `ingest_resolution()`, before any version is
  created:
  - `_is_real_improvement(current_default, new_language)` — narrowly
    scoped to the two confirmed real cases, not a blanket "always
    promote the newest": true if the current default has no real
    segments at all, or has segments but no detected language while the
    fresh version has one. If the current default already has both real
    segments and a language, a fresh duplicate-ish version isn't
    confidently better and is left alone — avoids flip-flopping the
    default unpredictably. When true and a new version was actually
    created this ingest, `promote_transcript_version()` (already built
    for the transcription-job completion path) is called on it — the
    Dublin-style half.
  - `_default_looks_like_copied_agenda(current_default, agenda_items)`
    — true if the current default's segment texts are structurally
    identical, in order, to the *freshly resolved* agenda_items in this
    same ingest. Detects the Yountville failure mode generally (any
    page with that same data shape), not by matching old warning-message
    text, which would only ever catch that one historical bug. When true
    and no new version was created this ingest (nothing better found
    either), the stale default is demoted (`is_default = False`) even
    without a replacement, rather than staying stuck forever.
  Both checks only ever run when a `current_default` already exists — a
  brand-new page's first version keeps its existing simple
  `is_default=True`-on-creation behavior unchanged.

  Verified with 5 new real-DB integration tests
  (`tests/test_ingest_promotion.py`): the Dublin case (promotes a newly
  language-detected version over a language-less default), the
  Yountville case (demotes a copied-agenda default when a recheck finds
  real agenda but no segments), a stability check (no promotion when the
  default already has both segments and a language), a brand-new-page
  sanity check (no crash with no existing default), and a negative case
  for the agenda-copy detector (a default with real, non-agenda-matching
  segments is correctly left alone). Full suite green (126 tests).

  Not yet done, left as a residual live item: actually running
  `/admin/recheck-archive-page` against the two real motivating pages
  (Yountville, Dublin) to confirm this fires correctly outside of tests
  too — needs `ADMIN_STATS_TOKEN`, which this session doesn't have — and
  the originally-planned audit of all 12 permanent pages for the same
  stale-shape issue, now that there's a real fix to apply if any others
  turn up. See BACKLOG.md.

- **[Done 2026-08-08] Swagit's ALL-CAPS `#transcript-fragments` text now
  gets re-cased for readability, reusing the existing shouting-caption
  standard instead of inventing a second one.** Confirmed live on the
  real Dublin, CA meeting: the grouped word-fragments (see the grouping
  entry above) were still genuinely ALL CAPS at the source ("GOOD EVENING
  AND HAPPY NEW YEAR..."), reading as shouting even once grouped into
  real lines. `app/utils/vtt_parser.py` already had exactly this problem
  solved for Granicus's VTT captions (confirmed real on San Francisco's
  all-caps live captions) via `normalize_shouting_caption()` (renamed
  from `_normalize_shouting_caption` to make it importable — no other
  behavior change) + `_sentence_case()`: detects roughly-all-uppercase
  content (not per-cue, so a normal transcript with a few capitalized
  acronyms is never touched) and re-cases it. `swagit.py`'s
  `#transcript-fragments` branch now calls the same function on its
  grouped segments (converted to the dict shape the function expects,
  written back onto the `TranscriptSegment` objects afterward) right
  after grouping — reuses the exact tested detection/casing logic rather
  than a second Swagit-specific implementation, and correctly no-ops on
  a hypothetical future Swagit deployment that turns out to emit
  normal-case text. Verified with a new integration test
  (`tests/test_swagit.py::test_resolve_normalizes_all_caps_transcript_fragments`)
  using the real all-caps Dublin wording end-to-end through `resolve()`.
  Full suite green (127 tests).

- **[Done 2026-08-08] `/meetings`' fuzzy/exact search toggle moved into
  the filters dropdown; filters laid out in deliberate rows; a real
  "Clear all filters" button added.** The fuzzy checkbox had been hidden
  entirely in an earlier pass (per an explicit request, based on a
  mistaken belief it was already inside the filters dropdown when it was
  actually in the main search bar) — real regression, since that left it
  reachable only via a raw `?fuzzy=true` URL param with no UI control at
  all. Restored into `archive/templates/meeting_list.html`'s actual
  filters `<form>` this time, alongside "Has transcript"/"Has agenda."
  Also fixed the messy layout the user flagged: the filters form used to
  be one flat `flex-wrap` container, so narrow checkboxes landed on
  whatever row had leftover horizontal space next to unrelated text/date
  fields — accidental grouping, not deliberate. Now three explicit
  `.filters-row` groups (fields / checkboxes / actions) stacked in a
  column, each wrapping independently. "Clear all" already existed as a
  plain muted text link shown only when a filter was active (an existing,
  easy-to-miss `.clear-filters` class matching this session's recurring
  "small text link, easy to miss" pattern) — now a real always-visible
  `.cassette-btn-outline` button (a new, visually lighter sibling to the
  existing bold `.cassette-btn`, so it doesn't compete with "Apply
  filters" for attention) next to "Apply filters." Verified with a Jinja
  render check; no backend changes needed (`fuzzy: bool = False` in
  `archive/main.py` already parsed the checkbox correctly, same
  convention as the existing `has_agenda`/`has_transcript` checkboxes).

- **[Done 2026-08-08] The AI-transcript disclaimer now appears everywhere
  an AI-generated transcript is actually shown, not just the meeting
  page, and has real visual identity.** Audited every surface: the
  on-page disclaimer (`archive/templates/meeting_page.html`) was the
  *only* place it existed — the `.txt` transcript export
  (`/m/{slug}/transcript.txt`) and the transcription-completion email
  (`archive/utils/email.py`) both quoted/exported AI-generated text with
  zero indication it might be wrong. Fixed:
  - `.txt` export: the same disclaimer text prepended when
    `active_version.source == "transcribed"`. Deliberately *not* added to
    the `.srt` export — SRT is a strict cue format meant for subtitle
    players, and a fake cue at 00:00 would visually overlay the video as
    if it were spoken dialogue, competing with the real first line;
    plain text has no such constraint.
  - Completion email: added unconditionally (every completion email is,
    by definition, about an AI-transcribed version — `send_completion_
    email()` only ever gets called from the transcription-job completion
    path), matching the on-page wording.
  - Styling: the on-page disclaimer moved off the plain amber `.warnings`
    pill every other transcript-quality message uses, onto a new
    `.ai-disclaimer` treatment that reuses the site's `.dymo-label-small`
    motif (the same "label-maker tag" look as the site wordmark and the
    `/subscribe` page's section tag) as a real visual flag — a small
    "AI TRANSCRIPT" badge next to the text, per an explicit request to
    give this one more identity than a generic warning, since it's
    telling a reader the text might contain fabricated sentences, not
    just "approximate."
  Verified with Jinja render checks (both templates) and the full pytest
  suite (127 tests, unaffected — template/CSS/email-copy changes only).

- **[Done 2026-08-08] `/meetings` search results now show a "✓
  Transcript" badge instead of a raw language code, and it's
  quality-aware, not just presence-aware.** Was: the listing showed
  `· en` (or `· es`, etc.) — not intuitive at a glance, per direct
  feedback, and beside the point anyway since the real question a viewer
  has is just "does this meeting have a transcript," not which language
  it's in. Replaced with a `✓ Transcript` badge, shown regardless of
  language (per explicit follow-up: language-independent, but *only* for
  quality transcripts) — `archive/db/crud.py`'s `list_pages()` used to
  set `has_transcript` from bare row presence (`version_id is not
  None`), which would badge a genuinely garbled transcript the same as a
  clean one. Now reuses the same `_GARBLED_MARKER` signal
  `_has_good_transcript()` already uses (built earlier this session for
  the Archive recheck cadence), inlined directly in `list_pages()`'s row
  loop rather than calling that function per row -- it does its own DB
  query per page, which would be a real N+1 across a results page;
  `transcript_warnings` is now pulled in the same single batched query
  `list_pages()` already runs, cheap since it's a short list unlike full
  segment JSON. Styled with `.has-transcript-badge` (`--accent` blue,
  no new hardcoded color). Verified with a new real-DB test
  (`tests/test_list_pages_search.py::test_has_transcript_badge_is_quality_aware_not_just_presence`,
  a garbled page and a clean page in the same query, asserting the badge
  differs) plus a Jinja render check. Full suite green (128 tests).

- **[Done 2026-08-08] "✓ Transcript" restyled as a real pill badge, pinned
  to a fixed right-hand column, with a light rubber-stamp treatment.**
  Direct design feedback on the badge added earlier the same session:
  the word "Transcript" only needs reading once before a viewer
  recognizes it by shape/color afterward, so it can run small; making it
  a real graphic element keeps it on one line; and it should land in the
  same vertical line of sight on every row regardless of how long that
  row's title/jurisdiction/date text happens to be, which inline
  middot-separated text can't guarantee.
  - Layout: `archive/templates/meeting_list.html`'s row markup split
    into `.calendar-candidate-main` (title + meta, grows/wraps
    naturally) and the badge as a sibling, with a new `.meeting-result-
    row` modifier class (`display:flex; justify-content:space-between`)
    added *alongside* the existing `.calendar-candidate` class rather
    than changing that class's own rules — `.calendar-candidate` is
    also used unmodified by the resolver's calendar-picker list
    (`renderCalendarPage()` in `player.js`), which doesn't have this
    two-level structure and would have misrendered if the base class
    itself became a flex container.
  - Visual: new `--success-bg`/`--success-fg` CSS variables (soft
    green), following the same paired-token pattern the existing
    `--pill-bg`/`--pill-fg` amber warning color already established,
    rather than a one-off hardcoded hex. Styled as a small stamped-
    looking pill — 2px border (not the soft pill-radius look), monospace
    uppercase text, a slight `rotate(-4deg)` tilt — matching the site's
    existing "Red Tape Recordings" government-document motifs (the
    dymo-label wordmark, cassette buttons) per an explicit "make it a
    tiny bit rubber-stamped, government aesthetic, don't overdo it"
    request. No texture/grunge image, just typography + a small rotation.
  Verified live in-browser (not just rendered HTML) against a real local
  resolver+Archive pair (matching production's reverse-proxy shape) with
  seeded real pages — checked both desktop and mobile widths: the badge
  stays pinned to the right/top-right as titles wrap, the filters
  dropdown (fuzzy toggle + rows) renders as intended, and the resolver's
  separate calendar-picker list is unaffected. Full suite green (128
  tests, no test changes needed — this was a pure CSS/template layout
  pass on already-tested data).

- **[Done 2026-08-08] The "Red Tape Recordings" dymo-label wordmark no
  longer forces the navbar hamburger onto a second line on mobile.**
  Confirmed live at 375px width (a real iPhone-class viewport): the
  full-size label alone measured 312px wide, leaving the 56px toggler no
  room in the 351px available (375px viewport minus the navbar
  container's own padding) — it wrapped to its own row below the
  wordmark. Added the codebase's first `@media` query (none existed in
  either stylesheet before this) to both `app/static/style.css` and
  `archive/static/style.css` (kept in sync manually, per that file's own
  header comment): below 576px, `.navbar-brand .dymo-label` gets a
  smaller font-size/padding/letter-spacing, scoped to the navbar
  wordmark specifically so the desktop-size `.dymo-label` used for the
  `/subscribe` page's larger heading elsewhere is unaffected. Verified
  live in-browser at both 375px (label now 203px, ~91px of real margin
  before the toggler, confirmed via `getBoundingClientRect()` that both
  elements' vertical ranges genuinely overlap on one row, not just
  visually close) and desktop width (font-size unchanged at 19.52px,
  confirming the media query doesn't affect wider viewports). Full suite
  green (128 tests, unaffected — pure CSS change).

- **[Done 2026-08-08] Transcript auto-scroll softened; video pinned in a
  sticky column on desktop — the two fixes decided together for the
  jarring-jump complaint.** Was: watching via the playhead jerked the
  page down to the transcript continuously (a `timeupdate`-driven
  `highlightSegment()` call ran `scrollIntoView({block: 'center'})` on
  every tick, even when the active line was already visible), and
  because the video wasn't pinned, there was nothing to jump back up
  *to* once it scrolled away. Built exactly as decided (Picture-in-
  Picture ruled out: this app renders video two different ways — native
  `<video>` vs. a YouTube iframe — and PiP only works cleanly against
  the former, so it'd behave inconsistently by platform):
  - **Softened auto-scroll**: `highlightSegment()`
    (`shared_static/deep_link.js`) gained an optional third parameter,
    `scrollBlock`, defaulting to `'center'`. The continuous
    `timeupdate`-driven call sites (`app/static/player.js` and
    `archive/static/meeting_page.js`, both `wireSharedControls()`) now
    pass `'nearest'` — a real no-op per the `scrollIntoView` spec when
    the target is already visible, so it only moves the page when the
    active line has genuinely scrolled out of view, and moves it the
    minimum distance rather than forcefully recentering every tick.
    Every *deliberate* one-time jump (`applyDeepLink()` on page load, a
    "Go to time" submit, a transcript-line click) was left on the
    default `'center'` — those are cases where firmly centering the
    target is exactly what was asked for, so only the passive
    follow-along behavior needed softening, not `highlightSegment()`
    itself.
  - **Sticky video on desktop**: a genuine two-column CSS Grid layout,
    not just a `position: sticky` bolted onto the existing single-column
    page — a full-width sticky video would have been impractically tall
    on wide screens (16:9 scales with width), leaving little room to
    read the transcript beneath it. Deliberately narrow (`minmax(220px,
    300px)`), per direct product framing: most viewers here are
    deep-linking to a specific moment and just need audio plus a visual
    confirmation of who's speaking, not a large frame for reading
    slides — someone who genuinely needs to read a presentation would
    open the source video fullscreen directly rather than use this
    tool's transcript view. `app/templates/meeting.html` and
    `archive/templates/meeting_page.html` both gained a new
    `#transcriptColumn` wrapper around the agenda/transcript sections
    (no ID changes to existing elements, so no JS changes needed beyond
    the scroll-block fix above) — sharing one grid cell/row with
    `#videoSection` in the other column gives the sticky video real
    vertical room to move within, bounded by that row's full height
    rather than just the video's own short natural height. `#meta` and
    the report-problem/transcribe forms stay full-width via `grid-column:
    1 / -1`, above/below the two-column area. The pre-existing `.toolbar`
    sticky-to-viewport-top rule (a prior, narrower fix for the same
    underlying complaint) is now redundant once the whole `#videoSection`
    sticks as one unit, and would otherwise nest two independent sticky
    contexts against each other — set to `position: static` specifically
    within the new desktop breakpoint, left untouched (still doing its
    original job) below it. Below `900px` (comfortably above
    `.meeting-page`'s own 860px max content width + padding) everything
    stays single-column, matching mobile's prior behavior unchanged.
  Verified live in-browser on both pages (not just rendered HTML) against
  real local resolver+Archive pairs with seeded multi-line transcripts,
  at a genuine 1280px desktop width: confirmed the video's on-screen
  position is pixel-identical across two screenshots taken before and
  after scrolling the transcript column, and confirmed it naturally
  scrolls away once its shared row's content is exhausted (correct
  sticky behavior, not a bug) rather than floating forever. Full suite
  green (128 tests, unaffected — template/CSS/JS layout change only).

- **[Done 2026-08-08] Real transcribe button styling + a full round of
  live-review feedback on the sticky video column above, on both
  `app/templates/meeting.html` and `archive/templates/meeting_page.html`
  (kept in sync, per convention).** Started as a small styling pass
  (`.link-button` → `.cassette-btn` on the "Transcribe this meeting from
  audio" toggle; `.report-problem-status`/`.transcribe-status` rewritten
  from hardcoded `#2f855a` green into a shared pill treatment using new
  `--success-bg`/`--success-fg`/`--error-bg` CSS variable pairs, matching
  `.warnings`' existing amber-pill language), then substantially expanded
  after live testing surfaced a real layout bug plus several rounds of
  direct feedback:
  - **`#reportProblemForm`/`#reportProblemToggleWrap` and
    `#toggleAutoScrollBtn`/`#seekForm` overlapping the sticky video on
    scroll (real bug).** These started as separate grid items sharing
    `#videoSection`'s grid row via explicit `grid-row` line numbers — but
    a sticky element's "stick range" is bounded by its own row, and two
    independently-sized sticky-adjacent siblings in the same row fought/
    rode over each other as the page scrolled. Fixed by wrapping
    `#videoSection` together with the report-problem toggle/form *and*
    the transcribe-request toggle/form into one new `#videoColumn`
    container, made sticky as a single unit — removes the whole class of
    problem (one sticky box, sized to its own real content) and lets
    `#videoColumn`/`#transcriptColumn` use plain column-only grid
    auto-placement again, no more explicit row numbering needed. On
    Archive specifically, this also required hoisting the
    "should the transcribe CTA show at all" condition (`not
    (active_version and active_version.segments and active_version.source
    == "transcribed")`) out of two duplicated inline conditionals (one in
    the "has a transcript" transcript-section branch, one in the "no
    transcript" branch) into a single `show_transcribe_cta` template
    variable computed once, since the CTA now lives in one place instead
    of inline with whichever branch happened to render.
  - **Auto-scroll toggle + "Go to time" moved below the video** (resolver
    only — Archive never had these), into a new `.video-subtoolbar` div,
    per direct feedback ("let's move those to below the video," after an
    initial too-narrow assumption that only the seek form needed to
    move). Found and fixed a real CSS bug in the same pass: a blanket
    `.video-subtoolbar .btn { width: 100% }` rule also matched the seek
    form's own submit button (it carries `.btn` too), fighting the seek
    form's flex layout and squashing the timestamp input to ~21px while
    pushing the button past the column's right edge. Narrowed to
    `#toggleAutoScrollBtn` specifically; both controls now stack full-
    width (`flex-direction: column; align-items: stretch`) so their
    left/right edges always align regardless of column width — confirmed
    via `getBoundingClientRect()` (both rows: left 234px, right 534px,
    exact match) after a follow-up request to align them.
  - **"Copy Link to Current Time" → live "Share video at X:XX" label +
    fading toast.** The toolbar button's label now updates every
    `timeupdate` tick (`Share video at ${formatTime(...)}`, mirroring the
    existing `updateNoTranscriptTime()` pattern), so a click can no longer
    swap the label to "Copied!" the way it used to — a separate
    `#linkToCurrentToast` element handles that instead. Iterated twice
    more per feedback: text changed to "Copied to clipboard", duration
    5s (was 2s), and repositioned from beside/below the button to
    floating *above* it — implemented as a `position: absolute` overlay
    (`bottom: 100%`, centered, its own pill background/shadow) inside a
    new `.copy-control` positioning wrapper around just the button (not
    the whole `.toolbar`, whose own `position` flips between sticky/
    static across the desktop breakpoint and would've made an
    inconsistent containing block).
  - **Transcribe button relocated + relabeled.** Moved into the new
    `#videoColumn` (previously lived at the bottom of the transcript
    column) so it sits directly under the video alongside "Report a
    problem," and renamed from "Transcribe this meeting from audio" to
    "Request Transcript from Audio" per direct feedback.
  - **Tighter meta-block spacing.** `.meta p` had no `margin-bottom`
    override on either stylesheet, so the browser's ~1em default
    paragraph spacing (not `.source-link`'s own already-tight margin) was
    the real cause of "too much space" between the jurisdiction/date line
    and "View original source" below it. Fixed with `margin: 0 0
    0.25rem`.
  - **Always-visible transcript scrollbar.** `.transcript-list` gained
    `scrollbar-width: thin` + `scrollbar-color` (Firefox) and styled
    `::-webkit-scrollbar*` rules (Chrome/Safari/Edge — merely styling
    `::-webkit-scrollbar` switches these browsers from invisible overlay
    scrollbars to always-reserved-space classic ones), so the box reads
    as a scrollable window at a glance instead of looking like a hard
    content cutoff.
  - **Shorter agenda box.** A long agenda was pushing the "Transcript"
    heading below the fold. `.agenda-section .transcript-list` now caps
    at `max-height: 220px` (vs. the main transcript list's `60vh`) — the
    agenda is secondary/reference material here, not the primary content.
  Verified live in-browser against a real local resolver+Archive pair
  (seeded Dublin, CA sample data, genuine 1280px desktop width) —
  discovered mid-verification that hitting the Archive dev server
  directly on its own port skips the resolver's `/archive-static/*`
  proxy route entirely (Archive's `base.html` references
  `/archive-static/...`, but Archive itself only mounts `/static`; the
  resolver's `app/main.py` has the actual `/archive-static/{path}` proxy
  route), silently serving an unstyled page — not a real bug, just a
  reminder to always test Archive pages through the resolver
  (`ARCHIVE_BASE_URL` pointed at the local Archive instance) rather than
  Archive's own port directly. Confirmed on both pages: no overlap
  scrolling all the way to the page bottom, seek-form/auto-scroll edges
  pixel-aligned, toast reads "Copied to clipboard" and floats above the
  button, agenda visibly shorter with "Transcript" on-screen without
  scrolling. Full suite green (128 tests, unaffected — template/CSS/JS
  layout change only).

- **[Done 2026-08-08] Transcription-complete email: brand-lite styling +
  a "forward this" ask, per the four open questions decided the same
  day (see prior BACKLOG.md entry, now removed).** `archive/utils/
  email.py`'s `send_completion_email()` was three unstyled `<p>` tags;
  rewritten as a table-based HTML email (a single outer `<table>`, not
  just divs, since Outlook desktop's Word rendering engine handles
  table layouts far more predictably) with the site's real colors/font
  hand-inlined as literal hex/font-family values on each tag — `--primary`
  navy `#2c3e50`, the amber warning-pill pair `#ffe6a1`/`#a84b00`, Georgia
  serif — since most email clients strip `<style>` blocks and CSS
  variables outright. No logo asset exists in this repo yet (confirmed,
  same gap as `CLAUDE_BACKLOG.md`'s og:image note) so the "brand" header
  is a plain red bar with the wordmark as styled monospace text, not an
  image. The AI-transcript disclaimer keeps its exact existing wording
  (matches the on-page/on-export versions) but now renders in the same
  amber-pill visual language as `.warnings`/`.ai-disclaimer` instead of
  plain colored text. The excerpt gets a left-border blockquote treatment;
  "Read the full transcript" is now a real button-styled link (white bg,
  2px black border, monospace bold — same visual family as `.cassette-btn`,
  hand-inlined since email clients can't load the real stylesheet). Per
  the decided scope: no "support us" ask (site has nothing concrete to
  point it at yet — split back out as its own live BACKLOG.md entry for
  later), reframed as a plain one-line "forward this email, or share the
  link" ask instead — no new share-button code, just copy; the naive
  first-500-characters excerpt was left unchanged (already built, no
  known complaints yet to justify a smarter picker). Verified by
  rendering the real function's output (monkeypatched `_send()` to
  capture the HTML instead of calling Resend) with real sample content
  and viewing it live in-browser — confirmed the header bar, navy
  heading, amber disclaimer pill, italic bordered excerpt, button-styled
  link, and forward-this line all render as intended. Full suite green
  (128 tests, unaffected — no tests assert on this function's HTML
  content).

- **[Done 2026-08-08] Matched-context snippet under each `/meetings`
  search result**, e.g. "...5.4 City <mark>Council</mark> Participation
  in the 2026 St. Patrick's Day Parad..." — real quoted excerpt from the
  meeting's own agenda/transcript text, not just the bare title/date/
  jurisdiction row. New `find_snippet()` in `archive/utils/search.py`
  (alongside the existing `matches()`/`tokenize()`/`build_corpus()`):
  given a query and an ordered list of body texts, returns the first
  match with ~50 chars of surrounding context on each side (ellipsis
  only where the text was actually truncated), the matched span wrapped
  in `<mark class="search-match">` — reusing the exact highlight class
  the in-page transcript search already uses, rather than inventing a
  second visual language for "this is a matched term." Fuzzy mode
  matters here specifically: a fuzzy match's span is the *real* word
  found in the source text (e.g. a transcript's actual typo "trafic"),
  never the query term itself, so a snippet always quotes what the
  source genuinely says — the alternative (splicing the query term into
  someone else's sentence) would read as silently doctored. Non-matched
  portions of the snippet are HTML-escaped; only the deliberately
  inserted `<mark>` tag is left raw, so the caller can render with a
  `safe` filter without reopening any injection risk from scraped or
  AI-transcribed source text.

  `archive/db/crud.py`'s `list_pages()` calls `find_snippet()` per
  *displayed* row only (not every filtered match — a snippet nobody's
  about to see costs nothing to skip), passing `[transcript_text,
  agenda_text]` — deliberately excluding title/jurisdiction, which
  already render directly above any snippet in `meeting_list.html`, so
  a title-only match (e.g. searching "Council" against "Jan 13, 2026
  City Council") correctly shows no redundant snippet, falling through
  to whichever other field actually matched instead (confirmed live:
  that exact query surfaced the agenda's "5.4 City Council
  Participation..." line, not a repeat of the title). New `.search-
  snippet` CSS in `archive/static/style.css` (Archive-only, like the
  rest of `/meetings`' layout — the resolver has no keyword search over
  transcripts).

  Verified with 6 new unit tests (`tests/test_archive_search.py`):
  exact-match context extraction, fuzzy match quoting the real
  misspelled word rather than the query term, multi-text ordering/empty-
  text skipping, no-match returns `None`, HTML-escaping of surrounding
  text while leaving the inserted `<mark>` tag raw, and ellipsis only
  appearing where truncation actually happened. Also verified live
  in-browser against the real seeded Dublin, CA sample through the
  resolver's proxy: an agenda-body match ("fireworks"), a transcript-
  body match ("pledge"), and the title-suppression case ("Council")
  above. Full suite green (134 tests — 6 new).

- **[Done 2026-08-08] Real pytest coverage for the PrimeGov and YouTube
  adapters — both previously at zero, per BACKLOG.md's "zero test
  coverage" note.** Prompted directly by a user-found real sample
  (`https://okc.primegov.com/Portal/Meeting?meetingTemplateId=68482`,
  Oklahoma City) resolved live against the actual adapters first — real
  video (delegates to a YouTube embed), 3503 real English auto-caption
  segments — which also surfaced the separate date/jurisdiction gap
  logged as its own live BACKLOG.md entry.

  New `tests/test_youtube.py` (11 tests) and `tests/test_primegov.py` (5
  tests), both using the exact real video id/title/uploader/upload_date
  from that OKC sample as fixture data rather than synthetic values.
  YouTube's real dependency, yt-dlp, stays genuinely untouched/unmocked
  — these monkeypatch `YouTubeAssetFinder._extract_info()` instead (a
  plain staticmethod, the exact seam `resolve_video_id()` calls through),
  so only *yt-dlp's result* is stubbed, not the library itself. Covers:
  `extract_video_id()`'s regex across every real URL shape (watch,
  youtu.be, embed, shorts, live); the full `resolve_video_id()` happy
  path (title/date/jurisdiction/video_url/segments all pinned against
  the real OKC values, including the *current, imperfect* upload_date-
  derived date — see the companion BACKLOG.md entry, this test
  deliberately pins today's real behavior rather than the eventually-
  fixed one); manual-vs-auto-generated caption warning; non-English
  caption warning; no-captions-available warning; a missing `upload_date`
  correctly leaving `date` as `None`; and the 2026-08-08
  `ignoreerrors: False` fix specifically — a `yt_dlp.utils.DownloadError`
  now surfaces its real message through the raised `ValueError` instead
  of a generic guess (see that same day's YouTube removed/blocked bug
  fix in this file).

  `test_primegov.py` covers `PrimeGovAssetFinder`'s own scraping/
  delegation logic (using `aiohttp_mock`'s existing `FakeResponse`/
  `mock_session` pattern for the page fetch, same as every other
  fixture-backed adapter test): extracting the real `var videoUrl =
  "..."` shape and delegating to `YouTubeAssetFinder`; the documented
  `source_url` quirk (stays the original PrimeGov URL, not the delegated
  YouTube one — pinned directly, since this is the one behavior this
  class exists to provide over a plain Legistar/CivicPlus-style
  delegation); and the no-video-found case (agenda-only
  `meetingTemplateId` page) returning a warning instead of raising.

  eScribe is now the only adapter of the original three still at zero
  coverage — narrowed BACKLOG.md's entry accordingly. `dedupe_rollup_cues`
  itself already had direct unit tests in `tests/test_vtt_parser.py`
  before this pass; not re-tested here through the YouTube adapter, since
  that would just be redundant coverage of the same pure function. Full
  suite green (149 tests — 15 new).

- **[Done 2026-08-08] Real bug found and fixed via the first-ever eScribe
  sample with actually-populated captions: `parse_vtt()` was silently
  corrupting every single cue's text with the *next* cue's number.**
  User-found live sample:
  `https://pub-bakersfield.escribemeetings.com/Meeting.aspx?Id=981f78d7-8211-4b4b-b066-5f93b4fd5e74`
  (Bakersfield, CA) — resolved cleanly end-to-end (video, 174 real
  English caption segments, no warnings) except every segment's text
  ended with a stray trailing number: `"...City Council\n2"`,
  `"...pleasure to\n3"`, etc. This closes BACKLOG.md's long-standing
  "eScribe caption content-quality unverified... none were populated"
  gap — the per-language VTT filename convention (confirmed structurally
  on Richmond, CA) turns out to work as designed once a city's captions
  are actually populated.

  Root cause, confirmed by fetching the real raw `.vtt` file directly:
  Bakersfield's captions number every cue on its own line immediately
  before the timestamp line — e.g. `1\n00:26:21.932 --> 00:26:24.711\n
  The 330 p.m. meeting...`. This is spec-legal WebVTT (section 4.1
  explicitly allows an optional cue-identifier line, the same convention
  SRT uses for its sequence numbers), but `app/utils/vtt_parser.py`'s
  `parse_vtt()` only ever recognized `WEBVTT` and blank lines as
  non-text lines — any other non-blank, non-timestamp line got appended
  as trailing text onto whichever cue was still open, which for an
  identifier line is always the *previous* cue (the one that just closed,
  not the one about to start).

  Fixed with a one-line lookahead: rewrote the line-by-line loop to check
  whether the *next* line matches the timestamp regex before deciding a
  non-timestamp line is real cue text — if the next line is a timestamp,
  the current line is a cue identifier and gets skipped instead of
  appended. Deliberately lookahead-based rather than "skip any line that
  looks like a bare number," so a genuinely short real cue (e.g. "Yes.")
  is never mistaken for an identifier just because it's short (pinned by
  its own test). No other real fixture (Granicus/YouTube/CivicClerk/CA
  Legislature/Swagit-via-caption-file) showed this contamination symptom
  before or after the fix, so this was a pure correctness fix, not a
  behavior change for any already-passing case.

  Three new tests in `tests/test_vtt_parser.py`: the exact minimal repro
  (numbered identifier lines swallowing the wrong cue's text), a
  guard against the short-real-cue false positive, and a real trimmed
  25-cue fixture (`tests/fixtures/escribe/bakersfield_ccm330_captions.vtt`,
  the actual Bakersfield file's first 25 cues) pinning the live bug and
  its fix together. Verified live in-browser too, not just via
  `resolve()`/unit tests: the actual `/meeting?url=...` page renders the
  full clean transcript with correct clickable `[26:21]`-style timestamps
  and no stray trailing digits anywhere. Full suite green (152 tests — 3
  new here, on top of the prior PrimeGov/YouTube entry's 15).

- **[Done 2026-08-08] `/meetings` added to the site nav.** User ran this
  directly (not this session) — confirmed live: `redtaperecordings.com`'s
  navbar now links to `/meetings` as "Search Meetings," and the prior
  "Look Up a Meeting" link reads "Add Meeting."

- **[Done 2026-08-08] All three real live pages confirmed stuck on stale
  pre-fix data are now fixed — user ran `/admin/recheck-archive-page`
  directly (this session never had `ADMIN_STATS_TOKEN`).** Verified live
  against all three, not just taken on faith:
  - `.../m/dublin-ca-2026-01-13-jan-13-2026-city-council` — transcript
    now renders as clean, de-shouted, word-grouped sentences ("3, 2, 1.
    Good evening and happy new year to everyone...") instead of the old
    36,085 ALL-CAPS word fragments; `/meetings` now shows the "✓
    Transcript" badge; page shows two versions ("en (scraped)" active,
    "unknown (scraped)" demoted) confirming the promotion logic kept the
    old version reachable rather than deleting it.
  - `.../m/yountville-ca-2026-04-21-apr-21-2026-town-council-budget-workshop`
    — even better than expected: the fake agenda-copied-into-segments
    version is now demoted ("unknown (scraped)"), and the *active*
    default is a real, good-quality self-transcribed AI version ("en
    (transcribed)") with the AI-transcript disclaimer rendering
    correctly — a transcription job evidently completed for this page
    since the original bug was found.
  - `.../m/california-state-senate-2026-08-06-senate-floor-session` —
    transcript renders normally with real content (Senate roll call),
    confirming the language-detection fix applied.

  One minor side-effect noticed while verifying, logged as its own new
  BACKLOG.md entry: Dublin's `/meetings` search-result *snippet*
  (distinct from the page itself) still shows old ALL-CAPS text, since
  `find_snippet()` searches across every `TranscriptVersion`'s
  concatenated text (including demoted ones) without distinguishing
  which version actually matched.

- **[Done 2026-08-08] Archive permanent pages now have the resolver's
  "no transcript yet" live-playhead + copy-link feature.** Ported
  `app/templates/meeting.html`'s `#transcriptMissing` block and
  `app/static/player.js`'s `updateNoTranscriptTime()`/`noTranscriptLinkBtn`
  wiring into `archive/templates/meeting_page.html` and
  `archive/static/meeting_page.js` — same pattern as the transcribe-
  request and report-a-problem features, each deliberately duplicated
  into both services rather than shared, since Archive's page is
  server-rendered while the resolver's is built from JSON client-side.

  One deliberate adaptation, not a straight copy: the live-timestamp
  block only renders when `page.video_url` is present (`{% if
  page.video_url %}` inside the new `#transcriptMissing` branch) — a
  real Archive-only case the resolver doesn't need to handle the same
  way, since a server-rendered page can genuinely have no video *and*
  no transcript at once (e.g. an eScribe page with only a live Vimeo
  stream, no archive — see `EscribeAssetFinder`'s own docstring), where
  "tracking the playhead" wouldn't make sense with nothing to play. That
  case still falls back to the original plain "No transcript available
  for this meeting" text. `updateNoTranscriptTime()`/`noTranscriptLinkBtn`
  wiring lives inside `wireSharedControls()` (the same function that
  already drives `linkToCurrentBtn`'s live label), since both need the
  same `adapter` — `noTranscriptLinkBtn` keeps the resolver's simpler
  swap-the-label-text-to-"Copied!" behavior (not the dynamic-label
  version `linkToCurrentBtn` needed, since this button's label isn't
  itself dynamic), and — being Archive-only — doesn't call the
  resolver's `trackEvent()`, which doesn't exist on this service at all
  (confirmed: no analytics setup anywhere in `archive/templates/base.html`).

  Verified live against two freshly-seeded real Archive pages through
  the resolver's proxy (the established correct way to test Archive
  pages — hitting Archive's own port directly skips `/archive-static/*`
  and breaks styling, a lesson from earlier this session): a video-
  present/no-transcript page, where seeking the video and dispatching a
  real `timeupdate` event moved `#noTranscriptTime` from "0:00" to
  "0:45" in sync with the video's own displayed time, and a direct
  `.click()` on `#noTranscriptLinkBtn` correctly appended `?t=45` (no
  `line=`, since there are no segments to match) to the URL; and a
  no-video/no-transcript page, confirmed still falling back to the
  original plain "No transcript available for this meeting" text
  unchanged. Full suite green (152 tests, unaffected — template/JS
  change only, no existing Jinja-render tests cover this template).

- **[Done 2026-08-08] `MAX_CONCURRENT_TRANSCRIPTION_JOBS` raised from 3
  to 15, per direct request.** `archive/db/crud.py`'s
  `create_transcription_job()` — a plain constant, no other logic
  touched. Note for later: raising this widens the *queue* (more
  requests get accepted into `queued`/`in_progress` instead of a 429
  "at capacity" rejection), it doesn't speed up processing — the single
  worker process still claims and processes one chunk at a time,
  serially (`worker/main.py`'s `run_forever()`), so a deeper queue means
  longer real wait times per job, not more throughput. No test asserted
  the specific value (only a docstring comment referenced the constant
  by name), so nothing else needed updating. Full suite green (152
  tests, unaffected).

- **[Done 2026-08-08] Fixed `/meetings` search-result snippets surfacing
  stale text from a demoted `TranscriptVersion`.** Found while verifying
  the Dublin recheck fix earlier the same day: the meeting page itself
  rendered a clean, de-shouted transcript, but its search-result snippet
  still showed the old ALL-CAPS text. `list_pages()` (`archive/db/
  crud.py`) already builds `transcript_text_by_page` by concatenating
  *every* version's segments (needed so a query matching only a demoted
  version's text still finds the page), but `_snippet_for()` was reusing
  that same all-versions blob for the *displayed* excerpt too, with no
  way to tell "matched in the current version" from "matched in an old
  one."

  Fixed by tracking a second dict, `default_transcript_text_by_page`,
  populated only from the version with `is_default=True` (one extra
  column, `TranscriptVersion.is_default`, added to the existing
  per-version query rather than a new query) — `_snippet_for()` now
  builds its excerpt only from that. `_matches_page()`'s boolean check is
  untouched, still searching every version, so the page still correctly
  shows up in results even when the only match is in demoted text — it
  just shows no snippet in that case, rather than a misleading one, since
  a viewer clicking through would never actually see that text on the
  page itself.

  Two new tests in `tests/test_list_pages_search.py`: extended the
  existing demoted-version test to assert `snippet is None` once the
  matching keyword only exists in the demoted version, and added a new
  positive-case test confirming a keyword matching the *current* default
  version still produces a real snippet as before. Full suite green (153
  tests — 1 new, on top of the demoted-version test's new assertion).

- **[Done 2026-08-08] Archive passive recheck cadence now depends on
  transcript quality, not just page age — built earlier this session,
  documented retroactively here after its BACKLOG.md entry was found
  still marked open despite the code already existing.** Exactly the
  two-piece design BACKLOG.md described: (1) `lookup_page_for_url()`
  (`archive/db/crud.py`) now returns a `has_transcript` field alongside
  `{slug, url, updated_at}`, via a new `_has_good_transcript()` helper —
  true only when the page's default `TranscriptVersion` has real,
  non-empty, non-garbled segments (same signal `/meetings`' quality-aware
  badge already uses); (2) `app/main.py` gained
  `ARCHIVE_RECHECK_AFTER_NO_TRANSCRIPT = timedelta(hours=1)` alongside the
  existing 30-day `ARCHIVE_RECHECK_AFTER`, and `/api/resolve`'s
  archive-redirect path picks between them based on the looked-up page's
  `has_transcript` flag — missing/falsy defaults to the shorter window
  (including the case where the Archive being talked to predates this
  field entirely, so an old deployed Archive doesn't accidentally get a
  30-day-only viewer stuck rechecking too rarely). Covered by
  `tests/test_lookup_has_transcript.py` (3 tests: real transcript → true,
  no version at all → false, garbled version → false).

- **[Done 2026-08-08] New platform: Viebit, the real video platform
  underneath NYC Council's Legistar instance — a real second gap fixed
  along the way (NYC's own domain was never actually reachable through
  `LegistarAssetFinder.resolve()` at all, a bug in the fix that was
  believed done), plus real, populated, correctly-parsed transcript
  captions for NYC Council meetings (a first).** Fully traced live from
  the NYC Legistar calendar page down to real caption content, entirely
  via plain HTTP — no headless browser needed anywhere in the chain,
  despite Minneapolis's LIMS platform (found the same day) needing one
  for a structurally similar-looking problem.

  **The trace**: NYC's video links (`a.videolink[onclick]`, confirmed on
  a real 40-video-link calendar page) call `OpenTelerikWindow('Video.aspx
  ?Mode=Auto&URL={base64}&Mode2=Video', 'video')` instead of every other
  Legistar city's plain `window.open('Video.aspx?Mode=Granicus&ID1=...')`
  — but `Video.aspx?Mode=Auto&...` itself does a real server-side 302
  redirect chain straight through to a Viebit `/embed/vod?v={id}` URL
  (confirmed via `curl -I -L`), so no base64-decoding is needed in this
  repo's own code at all — `LegistarAssetFinder`'s existing
  `allow_redirects=True` fetch already lands there directly once it
  recognizes the onclick shape. The landed page's plain HTML (confirmed
  identical whether fetched via the outer `/vod/?v=...` URL the base64
  decodes to, or the `/embed/vod?v=...` URL it redirects to) contains a
  `var pageConfig = {...};` JS object with everything needed: a real HLS
  `master.m3u8` URL, a real populated VTT caption URL (1748 raw cues on
  the real sample checked), and a title.

  **Real second bug found and fixed**: `LegistarAssetFinder.resolve()`'s
  own domain check (`"legistar.com" not in netloc`) was a bare substring
  check that evaluates `True` (i.e. "not Legistar") for NYC's actual
  `legistar.council.nyc.gov` pages too, since that string doesn't contain
  "legistar.com" as a substring — meaning even after `detect_platform()`
  was taught to route nyc.gov to `LegistarAssetFinder` (the earlier
  2026-08-08 fix, believed complete), `resolve()` itself would have sent
  NYC's own domain straight back into `resolve_via_platform()`, which
  re-detects "legistar" and would have recursed on the exact same URL
  rather than ever reaching `_find_video_links()`. Fixed by extracting a
  shared `_is_legistar_domain()` static method (used at both of the two
  call sites that previously duplicated the buggy check), matching
  `detect_platform()`'s own domain list instead of drifting from it.

  **Build**: new `app/platforms/viebit.py` (`ViebitAssetFinder`) — parses
  `pageConfig` via a small regex + `json.loads`, builds the m3u8 URL from
  `video.src[0].storage + .url`, and reuses existing shared utilities
  rather than writing new caption-format logic: `dedupe_rollup_cues()`
  (built for YouTube's differently-shaped growing-word rollup) turns out
  to already correctly collapse Viebit's two-line rolling-caption shape
  too — confirmed empirically (1748 raw cues → 876 clean segments) — since
  an exact-duplicate-text cue is just the trivial case of that function's
  existing prefix-matching merge logic, no new dedup code needed; and
  `normalize_shouting_caption` (already called inside `parse_vtt`)
  handles the source's ALL-CAPS text. Registered in
  `app/platforms/__init__.py`; `"viebit.com"` added to `detect_platform()`.
  `LegistarAssetFinder._find_video_links()`'s onclick regex extended to
  match `OpenTelerikWindow(...)` alongside the existing `window.open(...)`
  pattern (same `a.videolink` selector for both).

  **Real, disprove-not-just-unverified finding, documented honestly, not
  swept under a "should work" assumption**: fetching the real
  `master.m3u8` from this session's own sandboxed dev environment gets a
  403 from a Varnish-fronted CDN (`vbfast-vod.viebit.com`) even with
  realistic Referer/Origin/User-Agent headers, while a real browser (this
  session's own Browser tool) loads the identical URL successfully with
  no errors. Checked several hypotheses (Referer, Origin, a `vv=` token
  from the page's own `vod-check-in` POST) without finding the real
  gating mechanism — left as an open BACKLOG.md item to recheck from
  production rather than guessed at further. Transcript/caption fetching
  is a completely different, ungated path on the same CDN domain and is
  unaffected either way — confirmed via the real 876-segment result
  rendering correctly on the actual `/meeting?url=...` page, live, not
  just via `resolve()`.

  **Tests**: `tests/test_viebit.py` (4 tests, using real fixtures —
  `tests/fixtures/viebit/nycc_vod_page.html` and `nycc_captions.vtt`,
  both fetched live from the real sample) covering the full happy path
  (title/date/video_url/segment-count/language/de-shouting all pinned
  together against real data), a missing-`pageConfig` page returning a
  warning not a crash, a page with no caption track, and `_format_date`'s
  edge cases. Three new tests added to `tests/test_legistar.py`: the real
  40-candidate NYC calendar page (`tests/fixtures/legistar/
  nyc_council_calendar.html`) raising a proper pick-list via the
  `OpenTelerikWindow` onclick shape, a single NYC meeting delegating all
  the way through to a real Viebit result, and a direct pin of the
  `_is_legistar_domain()` fix (NYC's domain now correctly recognized,
  Viebit's correctly rejected). Verified live end-to-end via a real local
  resolver: `/api/resolve` and the rendered `/meeting?url=...` page both
  confirmed against the actual NYC URL, not just the mocked tests — the
  transcript renders with correct clickable timestamps and clean,
  de-shouted text; the video element shows a load failure, consistent
  with the CDN-403 finding above. Full suite green (160 tests — 7 new).

- **[Done 2026-08-09] eScribe: real per-item agenda timestamps and a
  jurisdiction fallback, both built from the same real Bakersfield, CA
  sample the `parse_vtt()` cue-identifier fix used, plus the last of the
  original three zero-coverage adapters now has real tests.** Investigated
  further than the original "no start-time attribute spotted" note in
  BACKLOG.md (written from a first look at just the `.AgendaItem` DOM) —
  a deeper look at the full page source found a `var video = {
  Bookmarks: [...] }` JS array with real per-item timestamps
  (`{"AgendaItemId": N, "TimeStart": ms, "TimeEnd": ms}`), keyed by the
  same numeric id each `.AgendaItem`'s title link passes to
  `SelectItem(N)`.

  Not every agenda item gets a bookmark — confirmed live: only 4 of the
  real page's 10 items did (apparently only substantive/voted-on items,
  not procedural ones like "ROLL CALL"). Rather than fabricate a start
  time for the other 6 (a real, unverified claim, and risky besides:
  `TranscriptSegment.start` is a required field, and several items
  sharing a made-up identical timestamp would likely trip the frontend's
  existing "unreliable timestamps" all-identical heuristic and cost the
  4 real ones their clickability too), `_extract_agenda_items()`
  (`app/platforms/escribe.py`) simply omits items with no matching
  bookmark rather than guessing. An item with more than one bookmark
  (confirmed: one real item had two, presumably discussed then revisited
  later) uses its earliest occurrence.

  Separately, `jurisdiction` fixed the same way BACKLOG.md's open
  question framed it: Bakersfield's page body has no "City of X" phrase
  (just a plain address), so a new `_jurisdiction_from_subdomain()`
  fallback derives it from the reliable `pub-{city}.escribemeetings.com`
  subdomain instead, used only when the body-text regex doesn't match.

  New `tests/test_escribe.py` (7 tests, closing the last gap of the
  original three zero-coverage adapters — PrimeGov/YouTube closed
  2026-08-08): the real Bakersfield sample end-to-end (title/date/
  jurisdiction/video_url/segment-count all pinned, plus all 4 real
  agenda items' text and timestamps), the subdomain-fallback helper
  directly, malformed/missing-Bookmarks-array handling, an item
  correctly skipped when it has no matching bookmark, and the two
  existing no-video/no-caption warning paths (previously entirely
  unverified by any test). New fixtures: `tests/fixtures/escribe/
  bakersfield_ccm330_page.html` (the full real page) alongside the
  already-existing trimmed captions fixture from the `parse_vtt()` fix.

  Verified live end-to-end through a real local resolver, not just the
  mocked tests: `/api/resolve` and the rendered `/meeting?url=...` page
  both confirmed against the actual Bakersfield URL — "Bakersfield ·
  2026-07-15" renders in the meta line, and a real clickable 4-item
  Agenda section renders with correct `[29:13]`/`[1:08:36]`/`[1:48:40]`/
  `[2:09:36]` timestamps. (Hit a stale local dev-cache red herring
  first — `/api/resolve` returned 0 agenda items even after the fix was
  confirmed correct via direct Python calls; turned out to be `dev.db`
  caching a resolution from earlier the same session, before this fix
  existed — cleared by deleting the local cache file, not a bug in the
  new code.) Full suite green (167 tests — 7 new).

- **[Done 2026-08-09] Alexandria VA's "meeting dates can't be extracted"
  gap closed — the real cause was one specific attribute-value blind
  spot, not a genuinely dateless page.** The original BACKLOG.md entry
  said "no date signal anywhere in the page body" — true for *visible
  text* specifically (confirmed live: Alexandria's real Granicus pages
  are thin client-rendered shells, no `og:title`, no `<h1>`, under 700
  characters of body text total, and no `view_id` to cross-reference an
  RSS feed either), but a closer look found the page's Agenda/Minutes
  document links are still server-rendered as plain `data-url="...pdf"`
  attributes — invisible to every existing date source here since none
  of them ever look at attribute values, only `soup.get_text()`. Those
  filenames follow a real, consistent Legistar-hosted-Granicus
  convention: `..._YY-MM-DD_Docket.pdf` (confirmed live on clip 6490's
  real Agenda *and* Minutes links both landing on the same
  `_25-04-02_` date fragment).

  New `GranicusAssetFinder._extract_date_from_document_links()`
  (`app/platforms/granicus.py`) scans every `[data-url]` element for that
  pattern, converting the 2-digit year to `20XX`. Wired in as a true
  last resort in `resolve()` — after page-text extraction *and* the RSS
  fallback have both already failed — preserving the file's existing
  documented priority order (page's own signals > RSS > this new
  fallback) rather than risking it preempting a more authoritative
  source on some other city's page.

  New tests in `tests/test_granicus.py` (3 tests, using a new real
  fixture `tests/fixtures/granicus/alexandria_clip6490.html`): the full
  resolve path landing on `date == "2025-04-02"` with the real fixture,
  plus two direct unit tests of the extraction helper (a real match, and
  a document link with no date pattern returning `None`). Verified live
  end-to-end: both a direct `resolve()` call and the actual rendered
  `/meeting?url=...` page (`"City of Alexandria · 2025-04-02"` in the
  meta line) against the real clip 6490 URL. Full suite green (170
  tests — 3 new).

- **[Done 2026-08-09] Adopted Alembic for the Archive's Postgres
  schema** — the real fix, decided 2026-08-08, for a wall this repo hit
  three separate times: `Base.metadata.create_all()` (still run
  unconditionally on every startup, unchanged) can only ever *add new
  tables*, never alter an existing one, and the job-priority column and
  the materialized search column both need exactly that.

  New `archive/alembic/` (async template, `alembic init -t async`) +
  `archive/alembic.ini`. `env.py` doesn't hardcode a database URL or a
  placeholder metadata object — it imports the real
  `archive.db.engine.DATABASE_URL` (same resolution the app itself uses,
  so dev/test/prod all naturally point at the right database with
  nothing to keep in sync) and `archive.db.models.Base.metadata` (so
  `alembic revision --autogenerate` diffs against the real
  `MeetingPage`/`TranscriptVersion`/`TranscriptionJob`/
  `MeetingPageUrlAlias` models directly, not a stub).

  Generated the baseline migration
  (`archive/alembic/versions/..._baseline_schema.py`) by autogenerating
  against a genuinely empty SQLite database (not the local dev DB, which
  already has these tables and would've diffed as "no changes") —
  `CREATE TABLE` for all four tables plus every index/foreign key.
  Verified locally: `alembic upgrade head` against a fresh empty SQLite
  file produces a schema that diffs identical to `create_all()`'s own
  output (only real difference: the `alembic_version` bookkeeping table
  itself, plus a cosmetic `(CURRENT_TIMESTAMP)` vs `CURRENT_TIMESTAMP`
  default-clause rendering quirk — same value, just how SQLite's own
  introspection reports a `server_default` either way); `alembic
  downgrade base` cleanly drops everything back out. **Not verified
  against real Postgres** — this sandboxed dev environment has Postgres
  *client* tools (`psql`/`initdb`/`pg_ctl` via Homebrew) but no server
  binary, and installing one felt like more system-level footprint than
  this check warranted; flagged honestly in `archive/alembic/README.md`
  as worth a real check before the first production `stamp head`, since
  Postgres's own type/default rendering can differ from SQLite's.

  `archive/db/engine.py`'s `init_models()` gained a doc comment
  explaining the new split responsibility rather than being changed
  itself — it stays exactly as it was (unconditional `create_all()` on
  every startup) since that's still the right zero-friction behavior for
  fresh local/test databases; Alembic is additive, the real source of
  truth for *production* schema changes specifically, not a replacement
  for `create_all()` everywhere.

  **Deliberately not run against production** — this session has no
  production `DATABASE_URL` access, and the one-time adoption step
  (`alembic stamp head`, telling production "you're already at the
  baseline, don't try to `CREATE TABLE` over existing rows") is exactly
  the kind of real, hard-to-reverse production-database action that
  needs the person who actually has that access to run it deliberately,
  not something to do on their behalf. Full instructions, including the
  exact one-time command, written into `archive/alembic/README.md`
  rather than left to be reconstructed later. Full suite green (170
  tests, unaffected — new tooling/config only, no application code
  changed).

- **[Done 2026-08-09] Job priority, built the moment Alembic unblocked
  it — `TranscriptionJob` gets a real `priority` column, and the one
  real call site (a live visitor's own request) now uses it.** Exactly
  the plan already written down: `priority: Mapped[int]` added to
  `TranscriptionJob` (`archive/db/models.py`, `default=10,
  server_default="10"` so the Alembic migration safely backfills every
  already-existing row rather than needing them nullable first). New
  named constants in `archive/db/crud.py` — `PRIORITY_LOW = 0` (reserved
  for the still-unbuilt self-generated idle-time batch work),
  `PRIORITY_MEDIUM = 10` (every real request today) — kept as literals
  in the model rather than imported, avoiding a `models` → `crud` import
  cycle, with a comment on each side pointing at the other so they don't
  quietly drift apart. `claim_next_chunk()`'s `.order_by()` gained
  `priority.desc()` ahead of the existing `created_at.asc()`, and
  `create_transcription_job()` — confirmed still the only real call site
  creating a job from an actual request — now sets
  `priority=PRIORITY_MEDIUM` explicitly.

  New migration `archive/alembic/versions/..._add_priority_to_
  transcription_jobs.py`, generated by autogenerating against a fresh
  copy of the baseline schema (not the shared local dev DB). Verified
  the backfill specifically, not just "applies without erroring": a real
  row inserted *before* running the migration correctly ended up with
  `priority=10` after `alembic upgrade head`, and `alembic downgrade -1`
  cleanly dropped the column back out.

  New test in `tests/test_transcription_jobs.py`:
  `test_claim_next_chunk_prefers_higher_priority_over_older_job` —
  creates an older job, drops its priority to `PRIORITY_LOW` directly via
  the DB (mirroring how `test_list_pages_search.py` already reaches past
  the public API for a scenario it doesn't expose), then creates a
  newer `PRIORITY_MEDIUM` job through the real `create_transcription_job()`
  path and confirms `claim_next_chunk()` picks the *newer, higher-priority*
  one first — proving priority actually overrides FIFO order, not just
  coincidentally agreeing with it. Full suite green (171 tests — 1 new).
