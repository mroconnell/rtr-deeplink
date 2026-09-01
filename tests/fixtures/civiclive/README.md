# CivicLive fixture note

`escalon_city_council_agendas.html` is a real, raw-saved live page —
`escalon.hosted.civiclive.com/government/agenda_packets/
city_council_agendas_and_minutes`, fetched live 2026-09-01 (plain
`aiohttp`-style GET, no JS execution) — with only `<script>`/`<style>`/
comment blocks stripped to keep the file a reasonable size (528KB ->
98KB), same convention as `tests/fixtures/civicplus/README.md`'s Durham
fixture.

**What it does and doesn't show.** The page's real Date/Time/Meeting/
Agenda/Packet/Minutes table — visible in a browser — is loaded via a
client-side AJAX call and is genuinely absent from this raw HTML; only
the site's static chrome (nav, footer, a single page-wide "City of
Escalon YouTube Channel" link) is server-rendered. That's not a fixture
mistake — it's the real, confirmed shape of a plain-fetched CivicLive
page, and exactly why `civiclive.py` doesn't attempt CivicPlus-style
per-meeting row scraping. This fixture is the regression test for the
honest negative outcome: a real CivicLive tenant page whose only video
reference is a channel-level link (`youtube.com/channel/
UCnj5AyZbMnaFmpNtaAxXRMA`) correctly resolves to "no video found," not a
false-positive channel match. See `test_real_escalon_agenda_page_finds_
no_per_meeting_video` in `tests/test_civiclive.py` and `civiclive.py`'s
own module docstring for the rest of the investigation (Auburn, WA's
confirmed real 302-redirect-to-CivicClerk shape, and Crystal, MN's
confirmed real cable-access-channel link).
