# Pin audit 2026-10-06: proposed fixes for the 52 high rows (not applied)

Evidence per row, from saved data plus a few polite page reads (none on YouTube).

# WO-1185 fixes, rows 1-17

Note on fetching: every *.civicweb.net host has a robots.txt of "User-agent: * / Disallow: /", so no civicweb page was fetched (only robots.txt). Bare *.escribemeetings.com hosts (no pub- prefix) return 404.

### Row 1 — albemarle.granicus.com
- Right government: Albemarle County, VA (us:county:51003) — high
- Evidence: "Board of Supervisors on 2026-08-19 1:00 PM - Regular Second Meeting" (discovery candidates, gov_id us:county:51003); Archive pages 1320, 3767, 5531 all keyed Albemarle County, VA; pin line 31 evidence says Legistar API lists only the Board of Supervisors.
- Fix: pin: none — already right (tenant_overrides.csv line 31); research row: jurisdiction_coverage.csv line 14994 (Albemarle city, NC) — remove albemarle.granicus.com from domain and the https://albemarle.granicus.com/player/clip/1452 example URL; Archive pages: none; discovery ledger: none.

### Row 2 — armstrong.civicweb.net
- Right government: Armstrong (city), BC (ca:csd:5937028) — high
- Evidence: cityofarmstrong.bc.ca home page ("Welcome to the City of Armstrong") links armstrong.civicweb.net 22 times (one GET, 2026-10-06); research row 1769 (Armstrong, BC) already lists it as alternate domain with civicweb/filepro/documents/3171.
- Fix: pin: change armstrong.civicweb.net from ca:csd:3554036 to ca:csd:5937028 (tenant_overrides.csv line 63; ca:csd:5937028 resolves); research row: keep line 1769; also jurisdiction_coverage.csv line 23026 (Armstrong County, TX) has https://armstrong.civicweb.net/ as example_agenda url (reject_reason robots-disallowed) — clear that URL (separate small mis-attribution); Archive pages: none exist; ledger: no tenant.

### Row 3 — champlain.escribemeetings.com
- Right government: no such tenant. The real eScribe tenant is pub-champlain.escribemeetings.com = Township of Champlain, ON (ca:csd:3502010) — high that QC is wrong for this address
- Evidence: bare host returns HTTP 404 (one GET to /robots.txt); pin line 9145 for pub-champlain: "escribe: agenda: Township of Champlain Regular Council, UCPR Council Chambers, 59 Court Street, L'Orignal" (tenant_overrides.csv).
- Fix: pin: change champlain.escribemeetings.com from ca:csd:2437220 to ca:csd:3502010 (tenant_overrides.csv line 209; or delete the line, since the host does not exist); research/Archive/ledger: none.

### Row 4 — cityofdover.civicweb.net
- Right government: cannot tell
- Evidence: the NL pin (tenant_overrides.csv line 237) came from a name-match sweep ("DNS resolves"); civicweb wildcard DNS resolves any name (dig gives 64.95.180.212), so it proves nothing. No saved page, ledger candidate, Archive page or research row mentions this host. "City of Dover" does not fit Dover NL (a "Town"); Dover DE (us:place:1021200, cityofdover.com) and Dover NH are named "City of Dover" — but this is only a hint, not evidence. robots.txt blocks bots on civicweb; the host did not answer an HTTP request here.
- Fix: cannot tell. One check that settles it: a human opens https://cityofdover.civicweb.net/Portal/ in a browser and reads the portal heading/state. Until then the safest move is to delete pin line 237 (a blank is better than a guessed Dover). No Archive pages, no research row, no ledger entry to change.

### Row 5 — cityofkingston.escribemeetings.com
- Right government: Kingston (city), ON (ca:csd:3510010) — high that PE is wrong; the bare host does not exist
- Evidence: bare host returns HTTP 404; pin line 9146 for pub-cityofkingston: "escribe: agenda: City of Kingston Council; items cite the Province of Ontario and Eastern Ontario YMCA"; Archive page 11473 (Planning Committee, pub-cityofkingston) is keyed Kingston, ON; ledger tenant pub-cityofkingston → ca:csd:3510010.
- Fix: pin: change cityofkingston.escribemeetings.com from ca:csd:1102022 to ca:csd:3510010 (tenant_overrides.csv line 245; or delete — host 404s); others: none.

### Row 6 — cityofmenifee.primegov.com
- Right government: Menifee city, CA (us:place:0646842) — high
- Evidence: Archive pages 732, 1267, 3831, 7144, 10473 all "Menifee, CA" (e.g. "Menifee Special City Council Meeting - January 21, 2026"; 1267 is "Regular Meeting - 12/05/2019" with slug city-of-menifee-nbsp-ca); research row 2725 (Menifee city, CA, same host); pin line 251.
- Fix: research row: jurisdiction_coverage.csv line 8594 (Menifee County, KY) — remove cityofmenifee.primegov.com from domain; pin/Archive/ledger: none (already right).

### Row 7 — claytownship.granicus.com
- Right government: Clay township, MI (us:cousub:2614716180) — high
- Evidence: Granicus ViewPublisher page table summary reads "...Upcoming and In Progress Events as published by Clay, MI." (one GET 2026-10-06); research row 28702 (Clay Township, Michigan, claytwpmi.gov) lists this host and clip_id=309.
- Fix: none — false alarm. The "Clay County, FL" claim comes only from a pin on a different host (clayfl.new.swagit.com) that shares the town name. Optional: add a pin claytownship.granicus.com → us:cousub:2614716180 so it is not left to name matching (no pin exists today).

### Row 8 — cooper.granicus.com
- Right government: Cooper City city, FL (us:place:1214125) — high
- Evidence: discovery candidates "CC City Commission Meeting", "Special Magistrate Code Enforcement and Building Department Hearings" (gov us:place:1214125); research row 3417 (Cooper City, FL, coopercity.gov) cites https://cooper.granicus.com/player/clip/183?view_id=2; Archive page 284 clip 692 sits between clips 183 and 749-754 of the same account and its video is under the same archive-stream.granicus.com/.../cooper/ path; clip page title just "City Commission Meeting" (no state).
- Fix: Archive pages: re-key page id 284 from us:place:4816564 to us:place:1214125 (its slug is cooper-tx-city-commission-meeting); research row: jurisdiction_coverage.csv line 23247 (Cooper city, TX) — remove cooper.granicus.com from domain and the clip/692 example URL; discovery ledger: none (already Cooper City FL); pin: none exists (consider adding one).

### Row 9 — desmoines.civicweb.net
- Right government: Des Moines city, WA (us:place:5317635) — medium-high
- Evidence: Archive pages 1493 ("Airport Advisory Committee - 08 Dec 2025") and 3213 keyed Des Moines, WA, YouTube channel @desmoinescouncilmember308; research row 25056 (Des Moines city, WA, desmoineswa.gov) lists this host and MeetingInformation.aspx?Id=586 = page 1493's source URL; discovery tenant → WA. Not independently confirmed from the portal (civicweb blocks bots; desmoineswa.gov city_council page answered 301, not read).
- Fix: research row: jurisdiction_coverage.csv line 6826 (Des Moines County, IA) — remove desmoines.civicweb.net from domain; line 6827 (Des Moines city, IA, desmoines.civicweb.net set as its primary domain, us:place:1921000) — clear that domain (it has a youtube-based record and its own site dmgov.org); Archive/ledger: none; pin: none exists. One check to raise to high: a human opens the portal and reads the city name.

### Row 10 — ellington-ct.gov
- Right government: Ellington town, CT (us:cousub:0911025360) — high
- Evidence: Archive page 9387 source URL is www.ellington-ct.gov/...schedule-of-budget-related-meetings, title "BoE Special Budget Meeting @ EHS 1/10/2026", YouTube channel @EllingtonPublicSchoolsCT; research row 26412 (Ellington, Connecticut, www.ellington-ct.gov).
- Fix: Archive pages: re-key page id 9387 from us:place:2921844 (Ellington, MO) to us:cousub:0911025360 (note: the page is a Board of Education meeting, so a school-district id may be the better target — Ryan's call; the town id is the only CT id the host maps to); others: none.

### Row 11 — glendale.granicus.com
- Right government: Glendale city, CA (us:place:0630000) — high
- Evidence: pin line 474: feed "City of Glendale: Archive View" ... clip 8524 agenda reads "Municipal Services Building - 633 E. Broadway ... Glendale, CA 91206" (tenant_overrides.csv); research row 2624 (Glendale city, CA) lists this host's ViewPublisher.
- Fix: Archive pages: re-key page id 10203 (clip 8524, stored "City of Glendale", filed as Glendale, UT) from us:place:4929360 to us:place:0630000; discovery ledger: candidates rows for this tenant still carrying gov_id us:place:4929360 (e.g. clips 8539, 8529, 8528) -> us:place:0630000 (tenant row itself is already CA); pin: none (already right).

### Row 12 — highlands-nj.municodemeetings.com
- Right government: Highlands borough, NJ (us:place:3431500) — high
- Evidence: the host name itself ("highlands-nj"); Archive page 1443 video channel @boroughofhighlands782 (Highlands Borough), meeting "LUB August 13th, 2026 Regular Meeting" (Land Use Board); discovery candidates "Council Regular Meeting", "Land Use Board Meeting" keyed us:place:3431500; research row 13646 (Highlands borough, NJ).
- Fix: Archive pages: re-key page id 1443 from us:county:12055 to us:place:3431500 (its slug highlands-borough-fl-... will keep the wrong state unless regenerated); research row: jurisdiction_coverage.csv line 3501 (Highlands County, FL) — remove highlands-nj.municodemeetings.com from domain and the bc-lub example URL; pin/ledger: none.

### Row 13 — hopewellboroughnj.gov
- Right government: Hopewell borough, NJ (us:place:3433150) — high
- Evidence: Archive page 3172 title "October 9, 2025 Hopewell Borough Council Meeting", stored jurisdiction "Hopewell Borough, Mercer County New Jersey", YouTube channel @hopewellboroughNJ, source www.hopewellboroughnj.gov/AgendaCenter; research row 13651 (Hopewell borough, New Jersey).
- Fix: Archive pages: re-key page id 3172 from us:place:5138424 (Hopewell city, VA) to us:place:3433150; discovery ledger: tenants hopewellboroughnj.gov and www.hopewellboroughnj.gov gov_id us:place:5138424 -> us:place:3433150, and the candidate row (youtube em1HM4Ft4FU) gov_id -> us:place:3433150; pin: none exists today (R2 refers to the ledger entries; consider adding a pin for both host forms). Hopewell township, NJ is a separate government, not this one.

### Row 14 — jamescitycova.portal.civicclerk.com
- Right government: James City County, VA (us:county:51095) — high
- Evidence: host slug "jamescitycova"; meeting "Board of Supervisors Business Meeting" (a Virginia county body, not an Ontario one); Archive page 2724 same portal, keyed James City County, VA; research row 24846 (James City County, Virginia, jamescitycountyva.gov) lists event 2687; tier3 queue line 770 us:county:51095.
- Fix: Archive pages: re-key page id 1758 (event 1021, 2022-01-25) from ca:csd:3554042 (James, ON) to us:county:51095; others: none.

### Row 15 — juneauak.portal.civicclerk.com
- Right government: Juneau (City and Borough), AK (us:place:0236400) — high
- Evidence: authoritative Ryan-stated pin line 585; "Assembly Committee of the Whole", "Assembly Finance Committee" (Archive pages 1130, 3129); host slug "juneauak"; ledger candidate titles "Eaglecrest Finance Committee Meeting", "Docks & Harbors Board Meeting".
- Fix: pin: none — already right; research row: jurisdiction_coverage.csv line 25842 (Juneau city, WI) — remove juneauak.portal.civicclerk.com from domain and the event/240 example URL; discovery ledger: candidate row event/4899 (Planning Commission Meeting) gov_id us:place:5538675 -> us:place:0236400; note: the flag also names an id rtr:us:ak:juneau, a second id for the same city (not checked further, out of scope).

### Row 16 — lakeshore.escribemeetings.com
- Right government: Lakeshore, ON (ca:csd:3537064) for the real tenant pub-lakeshore; the bare host does not exist — high that MB is wrong
- Evidence: bare host returns HTTP 404; pin line 10115: "Lakeshore, ON -- route_resolved 2026-09-29: dns_step0 lead pub-lakeshore.escribemeetings.com resolved to this government"; research row 30796 (Lakeshore, Ontario) lists pub-lakeshore.escribemeetings.com; ledger tenant lakeshoreon.new.swagit.com → ca:csd:3537064.
- Fix: pin: change lakeshore.escribemeetings.com from ca:csd:4617075 to ca:csd:3537064 (tenant_overrides.csv line 632; or delete the line, host 404s); others: none.

### Row 17 — lambton.civicweb.net
- Right government: Lambton County, ON (ca:cd:3538) — high
- Evidence: Archive pages 1266, 3968, 11613 titled "Lambton County Council (OPEN SESSION) - 02 Jul 2026" / "Committee of the Whole" with YouTube channel @CountyofLambton; discovery candidate "Lambton County Council (OPEN SESSION)"; research row 46514 (Lambton, Ontario, lambtononline.ca) lists meeting Id=1491 of this portal. Lambton QC is a tiny municipality (pop 1,630) with no county council. The tier3 queue line is already right.
- Fix: pin: change lambton.civicweb.net from ca:csd:2430095 to ca:cd:3538 (tenant_overrides.csv line 634); research row: jurisdiction_coverage.csv line 20103 (Lambton, Quebec) — remove lambton.civicweb.net from domain and the Id=1485 example URL; Archive pages: re-key page ids 1266, 3968, 11613 from ca:csd:2430095 to ca:cd:3538 (slugs say lambton-qc); discovery ledger: tenants lambton.civicweb.net gov_id ca:csd:2430095 -> ca:cd:3538 and candidate row Id=1483 gov_id -> ca:cd:3538; queue line 257: none — already ca:cd:3538.
# WO-1185 fixes, rows 18-39

Short key: pin file = app/utils/jurisdiction_data/tenant_overrides.csv; research = rtr-business research/jurisdiction_coverage.csv; ledger = rtr-discovery ledger.db; queue = scripts/tier3_auto_transcription_queue.txt. Archive page ids come from /tmp/rtr_meeting_inventory/meeting_inventory.csv.

### Row 18 — limerick.civicweb.net
- Right government: Limerick, ON (ca:csd:3512051) — medium
- Evidence: research line 17974 (Limerick, Ontario, domain www.township.limerick.on.ca) lists https://limerick.civicweb.net as its meeting-portal link; portal home title "Township of Limerick - Home" (page title, ON and PA both use "Township of Limerick", so it does not settle it alone). The only PA claim is a different host (pa-limerick.civicplus.com), a name match.
- Fix: none — false alarm (the other claim is a different address). To lift to high: one meeting title naming Hastings County / Ontario; the portal robots.txt disallows everything, so not fetched further.

### Row 19 — liveoakcity.primegov.com
- Right government: Live Oak city, CA (us:place:0641936) — high
- Evidence: "Live Oak, California 95953" and "Live Oak Council Chambers" (pin evidence, tenant_overrides.csv:673, WO-1153); Archive page 10479 video is "archive-stream.granicus.com/.../liveoakca/liveoakca_b55d..." (meeting_inventory.csv), a California stream path, yet it is filed under FL.
- Fix: Archive pages: re-key page 10479 from us:place:1240875 to us:place:0641936; discovery ledger: candidates for tenant liveoakcity.primegov.com that carry gov_id us:place:1240875 (City Council 2024-07-17, 2024-08-07, 2024-08-21) -> us:place:0641936; pin and queue line 518 and tenants row already correct (none needed).

### Row 20 — lowell.civicweb.net
- Right government: Lowell charter township, MI (us:cousub:2608149560) — high
- Evidence: "Charter Township of Lowell - Home" (portal page title, one GET); research line 31431 (Lowell charter township, Michigan, domain lowell.civicweb.net); candidate titles "Regular Board Meeting", "Planning Commission Meeting" (ledger candidates), board/township style.
- Fix: pin: change lowell.civicweb.net from us:cousub:2301941435 to us:cousub:2608149560 (tenant_overrides.csv line 691); discovery ledger: tenants lowell.civicweb.net gov_id us:cousub:2301941435 -> us:cousub:2608149560; research: none (already right). Note: this host's robots.txt is "Disallow: /", and I read its page title before reading robots (one GET).

### Row 21 — mapleton.civicweb.net
- Right government: Mapleton, ON (ca:csd:3523033) — high
- Evidence: 4 Archive pages (1515, 3211, 3992, 11618) with "Regular Council Meeting - 11 Aug 2026", "Committee of Adjustment" and channel @townshipofmapleton1082 (meeting_inventory.csv); ledger candidate Id=371 is titled "Regular Council Meeting" under this tenant, inside the same Id range 355-371 as the ON pages.
- Fix: queue line 266: gov_id us:sd:0805550 -> ca:csd:3523033; research: line 34026 (Mapleton School District 1, CO) — clear example_meeting_url (the Id=371 civicweb link; domain mapleton.us is fine); line 7144 (Mapleton city IA) — clear example_agenda_or_calendar_url (mapleton.civicweb.net); line 10720 (Mapleton city MN) — clear example_meeting_url (civicweb Id=359). Pin and ledger already right.

### Row 22 — middleton.civicweb.net
- Right government: Middleton town, WI (us:cousub:5502551600) — high
- Evidence: the Town of Middleton WI homepage (town.middleton.wi.us, title "Middleton, Wisconsin") links to "https://middleton.civicweb.net/Portal/" and "/Portal/MeetingSchedule.aspx" (one GET); research line 29570 (T Middleton, Wisconsin) names this portal. No NS evidence exists.
- Fix: pin: change middleton.civicweb.net from ca:csd:1205016 to us:cousub:5502551600 (tenant_overrides.csv line 762). Note the flag's wi-middleton2.civicplus.com is Middleton city WI (a different gov); the town, not the city, owns this link.

### Row 23 — montague.civicweb.net
- Right government: Montague, ON (ca:csd:3509001) — high
- Evidence: the Township of Montague site (www.township.montague.on.ca) links to "https://montague.civicweb.net/document/83697" (one GET); research line 18016 (Montague, Ontario) has civicweb as its link provider. Research line 23831 (Montague County TX) only has the host in its example agenda column.
- Fix: none for the pin (already right; the flagged CA city is a different host). research: line 23831 (Montague County, TX) — clear example_agenda_or_calendar_url (https://montague.civicweb.net/) and the civicweb provider guess. (co.montague.tx.us has no civicweb link.)

### Row 24 — niagarafalls.civicweb.net
- Right government: Niagara Falls, ON (ca:csd:3526043) — high
- Evidence: pin evidence "single-government tenant, confirmed live 2026-09-04 after deleting and resubmitting 3 pages that had wrongly resolved to Niagara Falls, NY" (tenant_overrides.csv:836, ryan_stated); 3 Archive pages (5271-5273) under ON, channel @niagarafallsontario.
- Fix: research: line 14362 (Niagara Falls city, NY) — remove niagarafalls.civicweb.net from domain (set domain to niagarafallsny.gov or niagarafallsusa.org as that row's own site; its example URLs point at Lockport/NY); pin: none; Archive: none; queue line 148 has no gov_id (the ON host is fine).

### Row 25 — oregon.granicus.com
- Right government: State of Oregon (us:state:41) — medium
- Evidence: Archive page 2230 "House Interim Committee On Agriculture and Natural Resources 2014-09-16" from this host's clip 7616 (meeting_inventory.csv) — a state legislature body, not a city or county. Pin evidence "HTTP 404 -> unverified: minted from 'Oregon, OR'" (tenant_overrides.csv:902). The research row's clip 7616 is that same legislature clip.
- Fix: pin: change oregon.granicus.com from rtr:us:or:oregon to us:state:41 (line 902) — Ryan call, since rtr:us:or:oregon is a minted stand-in for the state; research: line 12172 (Oregon County, MO) — remove oregon.granicus.com from domain and clear example_meeting_url; ledger tenants oregon.granicus.com has blank gov_id -> us:state:41; Archive pages: page 2230 has no gov_id, set to us:state:41. Note Oregon County MO is wrong on the evidence (the clip is the OR legislature); no title names MO.

### Row 26 — pub-grey.escribemeetings.com
- Right government: Grey County, ON (ca:cd:3542) — high
- Evidence: Archive page 793 "County of Grey, ON", "Committee of the Whole" 2026-07-09, video host cdn1.isilive.ca/.../countygrey/ (meeting_inventory.csv); research line 46518 (Grey, Ontario) lists pub-grey.escribemeetings.com; line 9273's own reject_reason is already "wrong-domain-mapping"; ledger candidates "County Council", "Committee of the Whole".
- Fix: research: line 9273 (Grey, Manitoba) — remove pub-grey.escribemeetings.com from domain and clear its example_meeting_url (which is this eScribe meeting); pin: none exists (could add pub-grey.escribemeetings.com -> ca:cd:3542, optional); ledger and Archive already right.

### Row 27 — pub-laporte.escribemeetings.com
- Right government: La Porte city, TX (us:place:4841440) — high
- Evidence: "City Hall Council Chamber / 604 West Fairmont Parkway, La Porte, Texas, 77571" (pin evidence, tenant_overrides.csv:848, escribe re-read 2026-10-05).
- Fix: research: line 6251 (LaPorte County, IN) — remove pub-laporte.escribemeetings.com from alternate_domains; pin: none.

### Row 28 — pub-livingston.escribemeetings.com
- Right government: Livingston County, MI (us:county:26093) — high
- Evidence: "304 E. Grand River, Board Chambers, Howell MI 48843" (pin evidence, tenant_overrides.csv:11361); research line 9957 (Livingston County, Michigan) names this portal. The NY claim is only a different host (ny-livingstoncounty2.civicplus.com).
- Fix: none — false alarm.

### Row 29 — pulaskigov.com
- Right government: Pulaski County, KY (us:county:21199) — medium
- Evidence: Archive page 6108 "Fiscal Court Agendas Minutes Videos" at www.pulaskigov.com/fiscal-court-documents/fiscal-court-minutes, YouTube channel @pulaskicounty2196 (meeting_inventory.csv; "Fiscal Court" is Kentucky's county governing body); pin evidence line 3128 "owner title 'Pulaski County'". MO's own site is pulaskicountymo.org (research line 12241).
- Fix: research: line 12241 (Pulaski County, MO) — remove pulaskigov.com from alternate_domains; line 8674 (Pulaski County, Kentucky) — add pulaskigov.com to alternate_domains (its domain is a chamber site); Archive and pins: none.

### Row 30 — reflect-yarmouth.cablecast.tv
- Right government: Yarmouth town, MA (us:cousub:2500182525) — high
- Evidence: "Yarmouth town, MA -- WO-1149: page 11313 'Select Board 12-16-2025' was filed under Yarmouth, Nova Scotia; the channel is Yarmouth, Massachusetts (show page names Cape Cod/Barnstable, MA)" (tenant_overrides.csv:6434, authoritative); research line 26650 (Yarmouth, Massachusetts) names this host; titles "Select Board", "Conservation Commission" (ledger candidates).
- Fix: discovery ledger: tenants reflect-yarmouth.cablecast.tv gov_id ca:cd:1202 -> us:cousub:2500182525; Archive: page 11313 gov_id already MA; its stored title label still says "Yarmouth, NS" (slug yarmouth-ns-...) — relabel to Yarmouth, MA if the display name is separate; pin and queue (line 519) already right.

### Row 31 — santa-rosa.granicus.com
- Right government: Santa Rosa city, CA (us:place:0670098) — high
- Evidence: "landing page https://santa-rosa.granicus.com/ reads 'City of Santa Rosa'" (pin evidence, tenant_overrides.csv:1226, re-verified 2026-09-03); 4 Archive pages (1310, 1456, 4200, 5923) "City Council", "Board of Public Utilities", all CA; ledger candidate "Board of Public Utilities" with CA id. (Santa Rosa County FL has its own site santarosa.fl.gov, research line 3678.)
- Fix: research: line 3678 (Santa Rosa County, FL) — remove santa-rosa.granicus.com from domain and clear its example_meeting_url (clip 3422); everything else already right.

### Row 32 — sunnyside.primegov.com
- Right government: Sunnyside city, WA (us:place:5368750) — high
- Evidence: "Sunnyside city WA (Ryan approved 2026-10-05; was wrongly ca:csd:1001277 Sunnyside NL by wildcard_http_sweep_2 name match): linked from sunnyside-wa.gov; its meetings' video is YouTube @cityofsunnysidewa" (tenant_overrides.csv:1327); Archive page 7492 and 11201 channel @cityofsunnysidewa; research line 25245 (Sunnyside city, Washington).
- Fix: Archive pages: re-key pages 7492, 9865, 11201 from ca:csd:1001277 to us:place:5368750; discovery ledger: tenants sunnyside.primegov.com gov_id ca:csd:1001277 -> us:place:5368750, and candidates carrying ca:csd:1001277 (Civil Service Commission Meeting 2026-09-09, Planning Meeting 2026-09-08) likewise; pin and queue line 129 already right/blank.

### Row 33 — taylor.civicweb.net
- Right government: Taylor, BC (ca:csd:5955030) — high
- Evidence: the District of Taylor site (www.districtoftaylor.com) links to "https://taylor.civicweb.net/Portal/MeetingTypeList.aspx" and "/Portal/Subscribe.aspx" (one GET); research line 2390 (Taylor, British Columbia) has the same link.
- Fix: none — false alarm (the MI claim is a different host, cityoftaylormi.gov).

### Row 34 — texarkanatexas.gov
- Right government: Texarkana city, TX (us:place:4872368) — high
- Evidence: the domain names Texas; research line 24225 (Texarkana city, Texas) has texarkanatexas.gov as its domain, example meeting texarkanatx.portal.civicclerk.com; ledger tenants texarkanatx.portal.civicclerk.com and texarkanacitytx.iqm2.com both -> us:place:4872368. AR's own domain is texarkanaar.gov (line 1680).
- Fix: research: line 1680 (Texarkana city, Arkansas) — remove texarkanatexas.gov from alternate_domains; line 24225 unchanged.

### Row 35 — uxbridge-ma.gov (and www.uxbridge-ma.gov, same problem)
- Right government: Uxbridge town, MA (us:cousub:2502771620) — high
- Evidence: Archive page 9404 source https://uxbridge-ma.gov/m/newsflash/home/detail/165, title "F.Y.I. Uxbridge - '2025 Spring Annual Town Meeting'" (Annual Town Meeting is Massachusetts), channel @uxbridgetv, filed under ON; pins tenant_overrides.csv:4977 (youtube izHtAtNqIwA, "Uxbridge town, MA -- government name found in video title/channel") and :6022 (youtu.be izHtAtNqIwA) both say MA; ma-uxbridge.civicplus.com title "Uxbridge, MA | Official Website" (:7592).
- Fix: Archive pages: re-key page 9404 from ca:csd:3518029 to us:cousub:2502771620; research: none (line 31423 already right). The two hosts (uxbridge-ma.gov and www.) are one problem; pins on youtube.com and youtu.be for the same video are the same fact.

### Row 36 — ventura.primegov.com
- Right government: Ventura County, CA (us:county:06111) — high
- Evidence: 3 Archive pages (912, 4259, 4700) "Board of Supervisors Meeting", "Assessment Appeals Hearing Officer Meeting", channel @countyofventuragovernment; ledger candidates "Board of Supervisors Special Meeting", "Air Pollution Control Board", "Local Agency Formation Commission". City of Ventura has its own host: cityofventura.granicus.com -> us:place:0665042 (tenant_overrides.csv:269).
- Fix: research: line 7501 (Ventura city, Iowa) — remove ventura.primegov.com from domain (keep venturaiowa.com) and clear example_meeting_url; pin, ledger, Archive: none (already right). The flagged rtr:us:ca:ventura is a flag-only name match to a different host.

### Row 37 — washingtonwilkes.org
- Right government: Wilkes County, GA (us:county:13317) — medium
- Evidence: homepage title "Home - Washington-Wilkes Chamber of Commerce, GA" and body text naming "Wilkes County" and "Georgia" (one GET). "WA" in the address is "Washington-Wilkes", the county seat Washington, GA, not Washington state.
- Fix: none — false alarm. Note: the site belongs to a chamber of commerce, not the county government; the research row's own status "no-platform-link-found" already shows no meeting source (a domain-ownership point, not an identity error).

### Row 38 — woodstock.escribemeetings.com
- Right government: cannot tell (Woodstock, NB vs Woodstock, ON) — low
- Evidence: bare-host page returned only an eScribe shell with no municipality name (one GET); the pin is a name-match sweep ("bare form resolves -> unverified: minted from 'Woodstock, NB'", tenant_overrides.csv:1559); pub-woodstock.escribemeetings.com is already pinned to Woodstock, ON (line 10109, route-resolved). No saved title, Archive page or candidate exists for the bare host.
- Fix: cannot tell — missing: any meeting title or address from this account. One check: open the account's meeting list in a browser (or the ledger candidates for pub-woodstock vs this host) and read a body name or address. Until then this pin is a guess; consider removing it.

### Row 39 — wyandottemi.gov (and www.wyandottemi.gov)
- Right government: Wyandotte city, MI (us:place:2688900) — high
- Evidence: Archive page 7120 "Wyandotte Zoning Board Meeting - 9/2/26", source https://www.wyandottemi.gov/AgendaCenter, slug "wyandotte-mi-2026-09-02-...", filed under OK; pin evidence "domain names Wyandotte MI; Ryan 'ok' 2026-10-03" (tenant_overrides.csv:11329); mi-wyandotte.civicplus.com title "Wyandotte, MI | Official Website" (:9099).
- Fix: Archive pages: re-key page 7120 from us:place:4082250 to us:place:2688900; pin, research (line 10209) and ledger already right.
# Rows 40-52 (no host fetches made; saved data only)
Abbreviations: pin file = app/utils/jurisdiction_data/tenant_overrides.csv ("TO"); inventory = /tmp/rtr_meeting_inventory/meeting_inventory.csv; JC = rtr-business research/jurisdiction_coverage.csv; verdicts = rtr-business research/wo171_channel_verdicts.csv.

### Row 40 — youtu.be [izHtAtNqIwA]  (same video and problem as Row 50)
- Right government: Uxbridge town, MA (us:cousub:2502771620) — high
- Evidence: video title "F.Y.I. Uxbridge - '2025 Spring Annual Town Meeting'", channel 'Uxbridge Community Television' (TO line 4977 evidence); Archive page 9404 source_url is https://uxbridge-ma.gov/m/newsflash/home/detail/165 and channel @uxbridgetv (inventory); JC line 31423 Uxbridge town, Massachusetts lists this exact video as its example meeting. "Annual Town Meeting" is a New England form; Uxbridge ON is a council town.
- Fix: pin: none — TO line 6022 (youtu.be) and line 4977 are correct; Archive pages: re-key page 9404 from ca:csd:3518029 to us:cousub:2502771620.

### Row 41 — youtube.com [HeEK_yE6UFc]
- Right government: North Miami city, FL (us:place:1249450) — high
- Evidence: verdicts row for @CityofNorthMiami: oEmbed author "North Miami FL"; JC line 3617 North Miami city, Florida (northmiamifl.gov) names this meeting page as example; Archive page 7316 "Citizens Investigative Board Meeting - 02/26/2024" is filed under North Miami FL (inventory).
- Fix: pin: none — TO line 1876 is correct. The conflict comes from the channel pin in Row 42 (fix there). Same underlying problem as Row 42.

### Row 42 — youtube.com [channel=@CityofNorthMiami]
- Right government: North Miami city, FL (us:place:1249450) — high
- Evidence: "North Miami FL" is the oEmbed author recorded for this channel (verdicts file, the very row the pin was built from); pin evidence text says "Miami city, TX -- ... oEmbed author confirms", so the author text "North Miami FL" was matched to the wrong government (Miami, TX). Page 9984 "Long Meeting Short with City Clerk Vanessa Joseph, Esq." is on this channel and was filed under Miami, TX. JC line 3617 lists youtube-lead-only for North Miami FL; youtube_channel_leads.csv lists the channel under North Miami city, Florida.
- Fix: pin: change www.youtube.com [channel=@CityofNorthMiami] from us:place:4847988 to us:place:1249450 (TO line 2357); pin: change www.youtube.com [irtYu6lNKb8] from us:place:4847988 to us:place:1249450 (TO line 3391, same mistake, not in my row list); verdicts file row for @CityofNorthMiami should read us:place:1249450 (source of the bad pin); Archive pages: re-key page 9984 from us:place:4847988 to us:place:1249450.

### Row 43 — youtube.com [channel=@CityofWashington]
- Right government: Washington city, MO (us:place:2977416) — medium
- Evidence: oEmbed author "City of Washington" names no state (verdicts). The channel's video UFU20VhLXp8 "City of Washington Council Meeting 03/02/26" is the example meeting in JC line 12438 (Washington city, Missouri, washmo.gov), and TO line 2073 pins it to MO. The R1 conflict is against washingtonnc.gov, a different address whose own meeting video is on Vimeo, not this channel (JC line 15549).
- Fix: none — false alarm (the NC pin is for a different host; no stored record ties this channel to NC). To raise to high: confirm washmo.gov links to @CityofWashington (one page read; no YouTube fetch needed).

### Row 44 — youtube.com [channel=@DeSotoKansas]
- Right government: De Soto city, KS (us:place:2017850) — high
- Evidence: oEmbed author "DeSotoKansas" (verdicts file) — the handle itself names Kansas; wo913_handcheck.csv: "handle DeSotoKansas; YouTube icon on the city's own home page" for De Soto city KS (right_gov); JC line 7721 De Soto KS (desotoks.us) has youtube video provider. The pin was set to MO although the same verdict row says the name is "DeSotoKansas".
- Fix: pin: change www.youtube.com [channel=@DeSotoKansas] from us:place:2919252 to us:place:2017850 (TO line 2420); pin: change www.youtube.com [n5OEcV-2kOc] from us:place:2919252 to us:place:2017850 (TO line 3455); verdicts file row for @DeSotoKansas: gov_id us:place:2017850; Archive pages: re-key page 9802 ("August 12, 2025, Special Planning Commission Meeting") from us:place:2919252 to us:place:2017850.

### Row 45 — youtube.com [channel=@hopewellboroughNJ]
- Right government: Hopewell borough, NJ (us:place:3433150) — high
- Evidence: "Hopewell Borough, Mercer County New Jersey" (owner title in TO line 3033 evidence, same string as Archive page 3172 title); JC line 13651 Hopewell borough, New Jersey, hopewellboroughnj.gov, gov_id us:place:3433150; "October 9, 2025 Hopewell Borough Council Meeting" (page 3172); registry resolves us:place:3433150 as Hopewell borough NJ. The flag's "Hopewell township, NJ" is a different government and not the answer; the pin to Hopewell city, VA is simply wrong.
- Fix: pin: change www.youtube.com [channel=@hopewellboroughNJ] from us:place:5138424 to us:place:3433150 (TO line 3033); Archive pages: re-key page 3172 from us:place:5138424 to us:place:3433150; discovery ledger: tenants hopewellboroughnj.gov gov_id us:place:5138424 -> us:place:3433150; discovery ledger: tenants www.hopewellboroughnj.gov gov_id us:place:5138424 -> us:place:3433150 (these two tenants rows are also flagged separately).

### Row 46 — youtube.com [channel=@townofgranville4545]
- Right government: Granville town, NY (us:cousub:3611530037) — high for the pin; the Archive page is medium
- Evidence: TO line 4718: "confirmed live 2026-09-11 as the Town's own small (1 subscriber, 2 videos), single-purpose channel, distinct from Granville village, NY"; its other video pinned at line 4719 is titled "Town of Granville, NY March 2021 Board Meeting"; the oEmbed author is "Town of Granville" (wo221_report.csv). The R1 conflict (Granville MA, ma-granville.civicplus.com, title "Granville, MA | Official Website") is a different address with no link to this channel.
- Fix: pin: none — false alarm for the MA claim; the channel pin is correct. Archive pages: re-key page 10088 ("Granville February 11, 2021", video 7u90sjTNDy4, this channel) from us:place:3630026 (village) to us:cousub:3611530037 (town); note only: JC line 14190 (Granville village NY) lists townofgranvilleny.gov as its domain and TO line 1595 pins www.townofgranvilleny.gov to the village, but the site's name says "Town of Granville" and the village has its own sites (villageofgranvilleny.com, villageofgranville.com) — cannot tell from saved data which government townofgranvilleny.gov serves; one page read of the site header would settle it.

### Row 47 — youtube.com [channel=@townofwiggins5934]
- Right government: Wiggins town, CO (us:place:0884770) — high
- Evidence: oEmbed author "Town of Wiggins" (verdicts); Archive page 9678 "Board of Trustee Special Meeting 06/21/2024" (Trustees is the Colorado town form); JC line 3243 Wiggins town, Colorado (wigginsco.gov) example meeting is https://www.youtube.com/watch?v=Vy407PP6Vvs, the same video as page 9678. Wiggins MS is a "city" with a Board of Aldermen (JC line 11461), and its address is cityofwiggins.gov.
- Fix: none — false alarm (the MS claim is a different host, ms-wiggins.civicplus.com).

### Row 48 — youtube.com [kGepCh07dg4]  (same video and problem as Row 51)
- Right government: Osage County, KS (us:county:20139) — high
- Evidence: video "Commission Meeting Dec 31" is on channel @osagecounty1099 (shared_host_lookups.csv; inventory page 7531). That channel is pinned to Osage County, KS in TO line 5264: "the government's own YouTube channel @osagecounty1099 ... (Ryan's WO-237 decision, 2026-09-11)"; coverage registry has us:county:20139 with that channel and this video as ingested. The MO pin (TO lines 3412 and 3980, "WO-134 confirmed hit", from ryan_flagged_replacement_2026-09-10) matched on the name "Osage County" only; the MO row (JC line 12177) has no meeting found of its own, and its own saved video fNPJQbqn9ms was flagged channel-mismatch (wo231_pin_audit.csv).
- Fix: pin: change www.youtube.com [kGepCh07dg4] from us:county:29151 to us:county:20139 (TO line 3412); pin: change www.youtube.com [youtube:kGepCh07dg4] from us:county:29151 to us:county:20139 (TO line 3980); Archive pages: none — page 7531 is already correct (KS).

### Row 49 — youtube.com [youtube:g4PAoFyp-nE]
- Right government: Ellington town, CT (us:cousub:0911025360) — high (the town; see note on the school board)
- Evidence: video title 'BoE Special Budget Meeting @ EHS 1/10/2026', channel 'Ellington Public Schools' / handle @EllingtonPublicSchoolsCT (TO line 4953 evidence; inventory page 9387); Archive source_url https://www.ellington-ct.gov/government/budget-process/schedule-of-budget-related-meetings; JC line 26412 Ellington, Connecticut (www.ellington-ct.gov) lists this exact video. Ellington city, MO has no link to this channel.
- Fix: pin: none — TO line 4953 is correct; Archive pages: re-key page 9387 from us:place:2921844 to us:cousub:0911025360. Note: the meeting is the Board of Education, and the registry also has Ellington School District, CT (us:sd:0901440, JC line 34130); filing under the town follows Ryan's accepted coarse-filing rule, but that is his call.

### Row 50 — youtube.com [youtube:izHtAtNqIwA]  (same video as Row 40)
- Right government: Uxbridge town, MA (us:cousub:2502771620) — high
- Evidence: same as Row 40 (TO line 4977 title/channel evidence; page 9404 source_url uxbridge-ma.gov; JC line 31423).
- Fix: pin: none — TO line 4977 is correct; Archive pages: re-key page 9404 from ca:csd:3518029 to us:cousub:2502771620 (one fix covers Rows 40 and 50).

### Row 51 — youtube.com [youtube:kGepCh07dg4]  (same video as Row 48)
- Right government: Osage County, KS (us:county:20139) — high
- Evidence: same as Row 48.
- Fix: pin: change www.youtube.com [youtube:kGepCh07dg4] from us:county:29151 to us:county:20139 (TO line 3980); the plain-id pin on TO line 3412 needs the same change (one fix covers Rows 48 and 51).

### Row 52 — youtube.com [youtube:vXvnuqAOpCQ]
- Right government: Sunnyside city, WA (us:place:5368750) — high
- Evidence: Ryan approved 2026-10-05 (TO line 1327): "Sunnyside city WA ... was wrongly ca:csd:1001277 Sunnyside NL by wildcard_http_sweep_2 name match ... its meetings' video is YouTube @cityofsunnysidewa"; Archive page 7492 "City Council Regular Meeting - 9/9/2026" has source_url sunnyside.primegov.com and channel @cityofsunnysidewa (inventory); JC line 25245 Sunnyside city, Washington (sunnyside-wa.gov) uses sunnyside.primegov.com; JC line 14964 Sunnyside NL has no domain. The video pin on TO line 4057 is already correct; the pages were never re-keyed after Ryan's host fix.
- Fix: pin: none — TO line 4057 is correct; Archive pages: re-key pages 7492 (this video), 9865 ("Planning Commission Regular Meeting - 9/8/2026") and 11201 ("City Council Regular Meeting 9/23/26"), all sunnyside.primegov.com pages, from ca:csd:1001277 to us:place:5368750.
