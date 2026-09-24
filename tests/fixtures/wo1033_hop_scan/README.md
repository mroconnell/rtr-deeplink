# WO-1033 fixtures: Dublin CA and Emporia KS

Real pages, saved 2026-09-23 for WO-1033's Hop/Scan link-quality fixes.
Ryan hand-checked both governments and gave the real ground truth these
fixtures test against (see `docs/MEETING_FINDER.md`'s Hop/Scan sections
and `hop.py`/`scan.py`'s own module docstrings for what each bug was).

## Dublin, CA -- fetched live

Politely, one request per page, `Crawl-delay: 20` honored between them
(`robots.txt` sets it).

- `dublin_home.html` -- `https://dublin.ca.gov/`, fetched live 2026-09-23.
  Real link to the meetings hub: `/1604/Meetings-Agendas-Minutes-Video-on-
  Demand`.
- `dublin_1604.html` -- `https://dublin.ca.gov/1604/Meetings-Agendas-
  Minutes-Video-on-Demand`, fetched live 2026-09-23 (20s after the
  homepage). Links `/2875/Watch-Meetings` (the real Swagit video page,
  `https://dublinca.new.swagit.com/videos/389917`) and `/915/Meetings-
  Agendas-and-Video-On-Demand`.

## Emporia, KS -- fetched via Wayback (live fetching paused)

**Emporia started 403ing this Mac after repeated requests during this
WO's own investigation -- do not fetch `emporiaks.gov` live again without
checking with Ryan first.** Both pages below are real, unmodified page
captures (`id_` Wayback suffix -- raw HTML, no toolbar injection, no
link-rewriting), so their own hrefs are still relative/real, exactly as
served originally.

- `emporia_home_wayback.html` -- `https://web.archive.org/web/
  20260912161855id_/https://www.emporiaks.gov/`, captured 2026-09-12,
  fetched via Wayback 2026-09-23. Real, load-bearing markup this fixture
  exists to test:
  - `<a href="/1300" ... class="fancyButton fancyButton55">` with nested
    `<span><span><span class="text">Agendas &amp; Minutes</span></span>
    </span>` inside `<nav class="widgetGraphicLinksNav">` -- CivicPlus's
    "graphic links" quick-link-button widget, confirmed by Ryan to be "a
    really common format for pages by CivicPlus." No path words at all
    (`/1300`), so the real meetings hub link scored nothing before this
    WO's `_looks_like_nav_hub_label()` rescue (`hop.py`).
  - `<a class="widgetDesc widgetGraphicLinksLink" href="/youtube" ...
    aria-label="YouTube"><img ... alt="YouTube" ...></a>` -- the same
    quick-link widget's YouTube button, no visible anchor text at all.
  - Several `Calendar.aspx?EID=...`/`calendar.aspx?view=list&...` links
    in the page's own events widget -- the real source of the "calendar
    events crowd out hub links" bug.
- `emporia_1310_wayback.html` -- `https://web.archive.org/web/
  20260905161849id_/https://www.emporiaks.gov/1310/City-Commission`,
  captured 2026-09-05, fetched via Wayback 2026-09-23. Real page Ryan
  checked by hand: links only `href="/youtube"` (CivicPlus's redirect to
  the city's YouTube channel), no direct video link of its own.

Neither Wayback capture's own YouTube/CivicAlerts/GovDelivery links were
followed or fetched -- Scan/Hop treat them as leads/dead ends only, and
this WO's own test/verification work made no YouTube request either
(`scripts/youtube_fetch_guard.py`'s rule; see CLAUDE.md).
