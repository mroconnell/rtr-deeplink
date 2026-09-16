# Platform fingerprint fixtures (WO-267, 2026-09-12)

Every file here is a real, raw-saved page -- plain `aiohttp`-style GET,
honest headers, no JS execution -- fetched live while measuring the
signals in `app/utils/jurisdiction_data/platform_signatures.csv` (see
`docs/investigations/platform_fingerprints.md` for the full measurement).
`<script>`/`<style>`/HTML comment blocks were stripped, then (for a page
over ~30KB) cut down to the first 20KB plus a window around the real
signal marker plus the last 4KB, same convention as
`tests/fixtures/civicplus/README.md`'s Durham fixture and
`tests/fixtures/cms_fingerprint/README.md`.

| File | Real government | Real URL | Signal it exercises |
| --- | --- | --- | --- |
| `granicus_liberty_hill_tx_player_clip.html` | Liberty Hill city, TX | `https://libertyhilltx.granicus.com/player/clip/694` | `granicus-player-clip-path` (`/player/clip/{id}`) |
| `civicclerk_lincoln_ri_event_media.html` | Lincoln, RI | `https://lincolnri.portal.civicclerk.com/event/5463/media` | `civicclerk-portal-host` -- a real CivicClerk portal page is a client-side-only JS shell (confirmed: no server-rendered agenda/video markup at all, same shape as ChampDS), so this fixture's signal match comes from the page's own URL, not its body -- pass the real `url` to `fingerprint()` when testing it, not just the HTML. |
| `civicweb_quesnel_bc_meetinginformation.html` | Quesnel, BC | `https://quesnel.civicweb.net/Portal/MeetingInformation.aspx?Id=1796` | `civicweb-portal-meetinginfo-path` (`Portal/MeetingInformation.aspx`) |
| `iqm2_colonie_ny_citizens_splitview.html` | Colonie village, NY | `http://colonieny.iqm2.com/Citizens/SplitView.aspx?Format=Minutes&MeetingID=1083&Mode=Video` | `iqm2-citizens-path` (`/Citizens/`) |
| `escribe_peelregion_on_pub_subdomain.html` | Peel Region, ON (via a Caledon, ON meeting row) | `https://pub-peelregion.escribemeetings.com/Meeting.aspx?Agenda=Agenda&Id=c129beef-a3cf-49ae-827d-27c6b3a547a5&lang=English` | `escribe-pub-subdomain` (`pub-<tenant>.escribemeetings.com`) |
| `swagit_middleburg_va_videos.html` | Middleburg town, VA | `https://middleburgva.new.swagit.com/videos/344455` | `swagit-videos-path` (`.swagit.com/videos/{id}`) |
| `hyland_santa_barbara_ca_agendaonline.html` | Santa Barbara city, CA | `https://docs.santabarbaraca.gov/OnBaseAgendaOnline/Meetings/ViewMeeting?doctype=1&id=1184` | `hyland-agendaonline-path` -- this is the WO's central finding: the page's own HOST (`docs.santabarbaraca.gov`) carries no `hylandcloud.com` anywhere, so `hyland-vendor-host` would miss this real tenant entirely; the literal page body shows `/OnBaseAgendaOnline/Images/...` but the exact `Meetings/ViewMeeting` path only appears in the URL, so (same as the CivicClerk fixture above) pass the real `url` when testing this one. |
| `municode_meetings_douglas_mi.html` | Douglas city, MI | `https://douglas-mi.municodemeetings.com/bc-citycouncil/page/regular-meeting-city-council-91` | `municode-meetings-vendor-host` |

See `docs/investigations/platform_fingerprints.md` for the full signal
table (hit rates, false-positive rates, and which signals did NOT clear
the bar and why) and for which of these signals are confirmation-only
(found because the hub URL already had this shape) versus genuinely
found by a blind fetch of an unrelated homepage.
