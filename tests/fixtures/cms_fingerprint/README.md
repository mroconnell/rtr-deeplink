# CMS fingerprint fixtures (WO-154, 2026-09-10)

Every file here is a real, raw-saved government home/agenda page — plain
`requests`-style GET, honest headers, no JS execution — fetched live
2026-09-10 while building `scripts/cms_fingerprint.py`. `<script>`,
`<style>` and comment blocks were stripped first (same convention as
`tests/fixtures/civiclive/README.md`), then each file was cut down
further to a ~20-30KB window: the first 20KB of the real page plus a
window around the specific marker string the fixture exists to test,
plus the last 6KB (footer badges live there). This keeps the fixtures
small while preserving the exact real evidence `cms_fingerprint.classify()`
looks for — every file still classifies correctly through the real
function, not a stub.

| File | Real government | Real URL | Family | What it tests |
| --- | --- | --- | --- | --- |
| `civicplus_eugene_or_agendacenter.html` | Eugene, OR | `https://www.eugene-or.gov/AgendaCenter` | civicplus | The literal footer badge "Government Websites by CivicPlus". |
| `revize_huron_sd_agendas_minutes.html` | Huron, SD | `https://cityofhuron.org/government/city_council/agendas_minutes.php` | revize | The `/revize/plugins/...` asset path. |
| `opencities_san_fernando_ca_home.html` | San Fernando, CA | `https://www.sanfernando.gov/Home` | opencities | The `<meta name="generator" content="OpenCities - https://granicus.com/product/opencities">` tag. |
| `opencities_syracuse_ny_false_positive_case.html` | Syracuse, NY | `https://www.syr.gov/Home` | opencities | The WO-163 case: this exact generator tag is also the one `app/platforms/base.py`'s `CORPORATE_HOSTS_BY_PLATFORM` check exists to stop from being read as a real `granicus.com` video tenant. This fixture confirms the two modules agree: `cms_fingerprint.classify()` correctly reads it as a real "opencities" CMS hint, while `detect_platform()` (tested separately in `tests/test_base.py`) correctly does not read it as a granicus tenant. |
| `municode_web_kaukauna_wi_home.html` | Kaukauna, WI | `https://kaukauna.gov` | municode_web | A footer link to `https://kaukauna-wi.municodemeetings.com/`. |
| `townweb_glen_cove_ny_livestream.html` | Glen Cove, NY | `https://glencoveny.gov/city-council-meeting-livestream` | townweb | A `cdn.townweb.com` dns-prefetch link. |
| `civiclive_lynn_ma_home.html` | Lynn, MA | `https://www.lynnma.gov/` | civiclive | An asset host reference to `cdnsm1-hosted2.civiclive.com` — note the domain itself (`lynnma.gov`) carries no civiclive signature; only the page's own asset host does. |
| `proudcity_fairfax_ca_home.html` | Town of Fairfax, CA | `https://townoffairfaxca.gov/` | proudcity | A `PROUDCITY_KNOWN_DOMAINS` tenant (see `app/platforms/proudcity.py`) whose page also carries the `proudcity-theme`/upload-path content markers independent of the domain list. |

See `scripts/cms_fingerprint.py`'s own rule-level comments for the fuller
evidence trail (how many real governments confirm each marker, and
where the full list lives).

## WO-179 additions (2026-09-10)

Same convention (raw fetch, honest headers, script/style/comment blocks
stripped, trimmed to a ~20-30KB window around the real marker) applied
to four new families learned from `wo174_candidates.csv`'s population.

| File | Real government | Real URL | Family | What it tests |
| --- | --- | --- | --- | --- |
| `govoffice_evansdale_ia_home.html` | Evansdale, IA | `https://evansdale.govoffice.com/` | govoffice | The domain itself is the vendor's shared `govoffice.com` host. |
| `municipalimpact_delhi_la_home.html` | Delhi, LA (Town of Delhi) | `https://townofdelhi.municipalimpact.com/` | municipalimpact | The domain itself is the vendor's shared `municipalimpact.com` host; also carries the real `/agendas` and `/minutes` nav links this family's meetings-page rule relies on. |
| `in_gov_towns_portal_georgetown_in_meetings.html` | Georgetown, IN (a town with no domain of its own) | `https://www.in.gov/towns/georgetown/meetings` | in_gov_towns_portal | Indiana's own shared `www.in.gov/towns/{slug}/` portal; this exact page is a real, populated agenda-PDF listing. |
| `wv_local_gov_williamstown_home.html` | Williamstown, WV | `https://local.wv.gov/williamstown/` | wv_local_gov | West Virginia's own shared SharePoint portal (`local.wv.gov/{slug}/`), recognised by host. |
