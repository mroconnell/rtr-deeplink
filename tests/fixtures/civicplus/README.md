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
If a fresh live CivicPlus site turns up (see `BACKLOG.md`'s open item on
this), replace this with a real saved page.
