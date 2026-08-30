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
