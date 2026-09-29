# CivicMedia fixtures

Real, raw-saved pages from Hobart, IN (`cityofhobart.org`), fetched live
2026-09-13 (WO-341) -- the only confirmed real CivicMedia/TikiLive tenant
so far (see `BACKLOG.md`'s entry this WO closes, and
`app/platforms/civicmedia.py`'s own module docstring).

- `hobart_civicmedia_vid326.html` -- `https://www.cityofhobart.org/
  CivicMedia?VID=326` ("Park Board 08-10-26"). `<script>`/`<style>`/
  comment blocks stripped to keep the file size down (115KB -> 60KB),
  same convention `tests/fixtures/civicplus/README.md` already
  documents for `durham_agendacenter_citycouncil.html` -- every element
  the adapter actually reads (`<iframe id="videoPlayer">`, the sibling
  `<a href="/CivicMedia.aspx?VID=...">` related-video links) is
  untouched.
- `tikilive_embed_160547.html` -- the TikiLive embed itself,
  `https://civplus.tikiliveapi.com/embed?scheme=embedVod&videoId=160547
  &autoplay=yes`, kept as-is (already small, 11KB). Its `.m3u8` URL
  carries a real signed `token=`/`stime=`/`etime=` that will have long
  since expired by the time this is read -- fine for a test fixture,
  since the tests here only assert the URL/caption-track *extraction*
  regex, never an actual playback fetch.
- `hobart_160547_en_excerpt.vtt` -- the first 30 lines of the real
  closed-caption track this video carries
  (`.../closed-captions/160/160547_en.vtt`), confirmed live to be real,
  coherent dialogue (not garbled/placeholder text) -- see the module
  docstring's "only ONE real example is confirmed so far" note for what
  this one positive example does and doesn't establish.
- `snyder_civicmedia_vid133.html` -- `https://snydertx.gov/CivicMedia?
  VID=133`, fetched live 2026-09-25 (WO-1069), `<script>`/`<style>`/
  comments stripped. Kept because its site name, "City of Snyder", is the
  one CivicMedia tenant in the Archive whose site name carries no state;
  the state comes from the ZIP in the page's own footer address, so the
  body has to stay.

## Title fixtures (WO-1165, 2026-09-29)

Three government pages, fetched live 2026-09-29, `<script>`/`<style>`/
comments stripped like the files above. Each shows a different way the
TikiLive player's title differs from the government's own `og:title`.

| File | Page | og:title | Player title |
|---|---|---|---|
| `isanti_civicmedia_vid461.html` | `https://www.isanticountymn.gov/CivicMedia?VID=461` | Live Stream Committee of the Whole - July 14, 2026 | Autorecord Jul 14 2026, 10:18 AM |
| `seagoville_civicmedia_vid719.html` | `https://seagoville.us/CivicMedia?VID=20250519-Regular-Session-Part-2-719` | 2025-05-19 Regular Session (Part 2) | 2025-05-19 Regular Session (Part 3) |
| `stjoseph_civicmedia_vid1.html` | `https://stjosephmo.gov/CivicMedia?VID=St-Joseph-Stormwater-Protection-and-Insp-1` | St. Joseph Stormwater Protection and Inspection Me (cut at 50 characters) | St. Joseph Stormwater Protection and Inspection Meeting 2025 |
