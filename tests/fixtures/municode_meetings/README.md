# Municode Meetings fixture note

Built while scoping `app/platforms/municode_meetings.py` (WO pending,
2026-09-01) -- see that module's own docstring for the confirmed real page
structure this was built against.

All four `.html` files here are real, raw-saved live pages -- only
`<script>`/`<style>` blocks and HTML comments were stripped to keep file
size down (same convention as `tests/fixtures/civicplus/README.md`); every
element the adapter actually reads is untouched.

- **`bristol_home.html`** -- `bristol-ri.municodemeetings.com/`, fetched
  live 2026-09-01. A real, busy tenant homepage: 25 meeting rows, of which
  **4** have a populated `views-field-field-video-link` cell, each holding
  a *relative* link to a same-tenant meeting detail page (not a direct
  video URL) -- this is the fixture that answers this adapter's own
  "does a real homepage ever have more than one populated video row"
  question: yes, confirmed live, not assumed. Used for the multi-candidate
  `CalendarPageError` pick-list test.
- **`bristol_meeting_278.html`** -- the detail page one of those rows
  points at (`/bc-towncouncil/page/town-council-meeting-278`), fetched
  live 2026-09-01. Its `#mcc_agenda_video` iframe embeds a real YouTube
  video (`//www.youtube.com/embed/bhpXBnBdpZc?rel=0`, protocol-relative).
  Used for the second-hop (relative-href) single-candidate delegation
  test, and as the fixture behind the multi-candidate pick's first
  candidate when a test resolves one by hand.
- **`hamburg_meeting_pc12.html`** -- `hamburg-mi.municodemeetings.com/
  bc-pc/page/planning-commission-meeting-12`, fetched live 2026-09-01. Its
  `#mcc_agenda_video` iframe embeds a real **Vimeo** video
  (`https://player.vimeo.com/video/1221763469`) -- confirms the delegated
  video platform is genuinely not YouTube-only on this platform. Used for
  the Vimeo-delegation regression test (this repo's own
  `is_vimeo_host()`/`parse_vimeo_video()` recognize `player.vimeo.com/
  video/{id}` directly, no config-fetch needed for detection).
- **`fairoaks_home.html`** -- `fairoaksranch-tx.municodemeetings.com/`,
  fetched live 2026-09-01. A second real busy-tenant homepage, structurally
  different from Bristol's: all 14 of its populated video-link cells hold
  an *absolute* link straight to the real video platform already (bare
  `https://www.youtube.com/live/{id}?si=...`/`https://youtu.be/{id}...`
  URLs right in the table cell) -- no second hop needed at all. Confirms
  both real href shapes this adapter has to handle exist on real, live
  tenants, not just in the throwaway research script's single sample.

**The "video-link href is a Google account login wall" false positive
described in this adapter's own module docstring (found scoping this
adapter, 2026-08-31) was not reproducible on a live re-check of
`fairoaksranch-tx` on 2026-09-01** -- every populated row on the current
live page holds a real, direct, already-valid YouTube URL, and the
no-video rows' own detail pages have no `#mcc_agenda_video` iframe at all
(not a login wall, just genuinely no video yet). Rather than skip this
case, `test_login_wall_iframe_is_treated_as_no_video` below is a
synthetic fixture (documented as such, per this repo's synthetic-test
convention) built from the exact real URL shape recorded when it *was*
observed (`accounts.google.com/ServiceLogin?service=youtube&...`) -- the
markup shell around it copies `bristol_meeting_278.html`'s own confirmed
`#mcc_agenda_video` iframe structure, only the `src` differs. This is the
regression fixture for `_is_real_video_link()`'s domain-based check (as
opposed to a naive substring match on "youtube" anywhere in the URL).
