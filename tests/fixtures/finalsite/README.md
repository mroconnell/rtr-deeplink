# Finalsite fixtures (2026-09-30)

Both files are real pages fetched 2026-09-30 with a generic browser
User-Agent and no personal data in headers.

| File | Real district | Real URL | What it tests |
| --- | --- | --- | --- |
| `client_challenge_nassau_k12_fl_us.html` | Nassau County SD, FL | `https://www.nassau.k12.fl.us/` | Finalsite's bot "Client Challenge" page: HTTP 200, 3,038 bytes, no links. Saved whole. |
| `home_isd623_org.html` | Roseville Area Schools 623, MN | `https://www.isd623.org/` | A readable Finalsite homepage. Scripts, styles and comments stripped, then cut to the first 20 KB plus a 3 KB window with `/fs/pages/N` links. |

Caution: the "Client Challenge" page is not proven to be Finalsite-only. The
Internet Archive copy of nassau.k12.fl.us (2026-09-04) was an Apptegy site.
The challenge is detected as a bot block regardless of builder; it is not used
to tag a site as Finalsite.
