# Drip handoff 2026-10-15_us_883157: 14 leads from rtr-findmeeting run us

These come from the Find Meeting run `us` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 14 |
|---|---|---|
| youtube | channel | 14 |

## Why each lead was suggested (14 of 14 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Teche-Vermilion Freshwater District Board of Commissioners, Louisiana (rtr:us:la:teche-vermilion-freshwater-district-board-of-commissioners) | https://www.youtube.com/channel/UCCYbDVlQR6CCE9K93e2jsYQ | found on https://teche-vermilion.org/: "Follow Us on youtube" under heading "Loreauville Canal Control Structure"; page "Teche Vermilion – Fresh Water District"; nearby: "315 South College Road, Suite 110, Lafayette, LA 70503 Email: waterdistrict@aol.com Phone: (337) 233-6902 Fax: (337) 233-6941" |
| Kenai city, Alaska (us:place:0238420) | https://www.youtube.com/@cityofkenaipublicmeetings7557 | found on https://www.kenai.city/citycouncil/page/city-council-regular-meeting-165 |
| Kenai city, Alaska (us:place:0238420) | https://www.youtube.com/channel/UCV3n3CIEfWrYaCYdlJv94sg/ | found on https://www.kenai.city/citycouncil/page/city-council-meeting-live-streaming |
| Park City Fire Service District, Utah (rtr:us:ut:park-city-fire-service-district) | https://www.youtube.com/channel/UCP306vxkBjo3Y-r1RbzuvAQ | found on https://www.pcfdut.gov/: "Social media icon for youtubeSocial media icon for youtube" under heading "Homepage of Park City Fire District"; page "Homepage Park City Fire District"; nearby: "Social media icon for youtube Social media icon for youtube Social media icon for twitter Social media icon for twitter Social media icon for facebook Social media icon for facebook" |
| Montmorency County, Michigan (us:county:26119) | https://www.youtube.com/channel/UCf3SjwH1z-tkjykycSG4JDQ | found on https://www.montcounty.org/meeting-agendas-minutes--recordings.html |
| Wheaton Park District, Illinois (rtr:us:il:wheaton-park-district) | https://www.youtube.com/user/WheatonParkDistrict | found on https://wheatonparkdistrict.com/: "YouTube page opens in new window"; page "Wheaton Park District – create. discover. play!"; nearby: "CONTACT US / FOLLOW US:" |
| Wheaton Park District, Illinois (rtr:us:il:wheaton-park-district) | https://www.youtube.com/channel/UCrPtiLYD2zGOosnzkPXONWg | found on https://wheatonparkdistrict.com/transparency-portal/board-meetings/: "Wheaton Park District YouTube channel" under heading "Meeting Documents and Videos for the Wheaton Park District Board of Commissioners and Subcommittees"; page "Board Meetings – Wheaton Park District"; nearby: "Board meeting packets for regularly scheduled monthly park board meetings will be posted by 12P the day of the meeting. Documents that are significant in size will be hosted on an external site, and v" |
| Port of South Louisiana Commission, Louisiana (rtr:us:la:port-of-south-louisiana-commission) | https://www.youtube.com/channel/UCYNy7cj1XdrC6F1xTd1nkCw | found on https://portsl.com/: "YouTube" under heading "Contact"; page "Port of South Louisiana"; nearby: "Privacy Policy / Sitemap Website Design by Curran & Connors" |
| Greater Lafourche Port Commission, Louisiana (rtr:us:la:greater-lafourche-port-commission) | https://youtube.com/@portfourchon226 | found on https://www.portfourchon.com/: "youtube" under heading "South Lafourche Airport (GAO)"; page "Offshore Energy Hub & Deepwater Port / Port Fourchon" |
| Caddo-Bossier Parishes Port Commission, Louisiana (rtr:us:la:caddo-bossier-parishes-port-commission) | https://www.youtube.com/channel/UCtBvcCLy11wAjFp3mQBS9Mg | found on https://portcb.com/: "Follow" under heading "About Us"; page "home - The Port"; nearby: "Follow Follow Follow Follow" |
| Painesville township, Ohio (us:cousub:3908559430) | https://www.youtube.com/@painesvilletownship3146/featured | found on https://painesvilletwp.com/: "YouTube" under heading "Where CommunityComes First."; page "Home - Painesville Township"; nearby: "Where Community Comes First." |
| Lake Charles Harbor and Terminal District Board of Commissioners, Louisiana (rtr:us:la:lake-charles-harbor-and-terminal-district-board-of-commissioners) | https://www.youtube.com/channel/UCvMhDM-XP6vQsUay4uY-vfQ | found on https://portlc.com/: "Youtube" under heading "Stay Connected"; page "Port of Lake Charles / Dry Bulk & Global LNG Export Hub"; nearby: "Facebook-f Linkedin-in X-twitter Youtube" |
| Morgan City Harbor and Terminal District Board of Commissioners, Louisiana (rtr:us:la:morgan-city-harbor-and-terminal-district-board-of-commissioners) | https://www.youtube.com/@PortOfMorganCity | found on https://portofmc.com/: "YouTube page opens in new window"; page "Port of Morgan City. Marine Shipping & Transportation -"; nearby: "Facebook page opens in new window YouTube page opens in new window Linkedin page opens in new window" |
| Zion Elementary School District 6, Illinois (us:sd:1743860) | https://www.youtube.com/channel/UCWQJCz5-OykqV8_kmoVttUg | found on https://www.zion6.org/: "YouTube(opens in new window/tab)" under heading "Connect with us!"; page "Home - Zion Elementary School District 6"; nearby: "YouTube (opens in new window/tab)" |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
