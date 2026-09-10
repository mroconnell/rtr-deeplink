# CivicPlus fixture note

`agendacenter_listing.html` is **not** a raw-saved live page like the other
platforms' fixtures. The site this adapter was originally verified against
(`ca-westlakevillage.civicplus.com`, per `app/platforms/civicplus.py`'s
docstring and `BACKLOG_DONE.md`, confirmed 2026-08-06) has since been
restructured — as of 2026-08-07 it 302s to a JS-redirect stub with no
`AgendaCenter` markup at all, and the plain `civicplus.com` subdomain no
longer resolves.

Instead, this fixture is hand-built to match the exact real markup shape
documented in `civicplus.py`'s docstring (`tr.catAgendaRow` rows, `h3 >
strong` date, `td > p > a` title, `td.media` video link) — the structure
that was confirmed against the live site before it changed, not a guess.

**2026-08-30 update: that fresh live site turned up.**
`durham_agendacenter_citycouncil.html` is a real, raw-saved page —
`nc-durham.civicplus.com/AgendaCenter/City-Council-4`, fetched live
2026-08-30 (31 `tr.catAgendaRow` rows, 22 with a real video link in
`td.media`: 21 Granicus + 1 YouTube; `durham.granicus.com/player/clip/3313`
spot-checked live). Only `<script>`/`<style>`/comment blocks were
stripped to keep the file size down (213KB -> 129KB) — every element the
adapter actually reads is untouched. `agendacenter_listing.html` and
`agendacenter_single.html` above are kept as-is (still useful for
exercising the single-video delegation and 2-candidate pick-list paths
with a small, easy-to-read fixture), but `durham_agendacenter_
citycouncil.html` is now the adapter's real, live-verified sample —
see `test_real_durham_listing_page_parses_correctly` in
`tests/test_civicplus.py` and the class docstring in
`app/platforms/civicplus.py`.

**2026-09-01: `ks_desoto_agendacenter.html`** — another real, raw-saved
page (`ks-desoto.civicplus.com/AgendaCenter`, fetched live 2026-09-01,
same `<script>`/`<style>`/comment stripping as Durham above). Every one
of its 12 `td.media` links is a YouTube *channel* or `@handle` link
(`/user/DeSotoKansas/live.`, `@DeSotoKansas`) — zero real single-meeting
videos anywhere on the page. This is the regression fixture for the
YouTube-channel-link bug fixed the same day: see `_is_real_video_link()`
in `app/platforms/civicplus.py` and
`test_real_desoto_listing_page_finds_zero_video_candidates` in
`tests/test_civicplus.py`.

**2026-09-10 (WO-162): `temple_city_agendacenter.html`** — another real,
raw-saved page, this one **self-hosted** rather than on a
`*.civicplus.com` subdomain: `www.templecityca.gov/agendacenter`, fetched
live 2026-09-10 (same `<script>`/`<style>`/comment stripping as the two
above, 295KB -> 202KB). This is the fixture for the corporate-host bug
fixed the same day (see `CIVICPLUS_CORPORATE_HOSTS` in
`app/platforms/base.py`): its real footer carries the same
`<a href="https://connect.civicplus.com/referral">CivicPlus (r)</a>`
credit every CivicPlus tenant's page does, confirmed here verbatim. Used
by `test_find_platform_link_skips_civicplus_corporate_footer_link_on_a_
real_page` in `tests/test_base.py`.

**Caution for future readers**: this real page's own 103
`tr.catAgendaRow` rows all link their `td.media` video to
`templecity.ec1c24.com/citycouncil/...` — a video-index wrapper domain
`detect_platform()` doesn't recognize at all (confirmed live 2026-09-10:
that wrapper page itself embeds a real YouTube video,
`youtube.com/embed/hXcwEqIekkc`, with per-agenda-item start-time links).
So fixing the corporate-host bug does NOT by itself make this specific
real page resolve to a video end-to-end — it only stops the scan from
wasting a request on CivicPlus's own corporate host (confirmed live: a
403 on `https://www.civicplus.com/referral`) before correctly finding
nothing else recognizable on the page. The `ec1c24.com` gap is a
separate, real platform-coverage gap, filed in `BACKLOG.md` rather than
fixed here.
