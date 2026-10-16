# Drip handoff 2026-10-16_us-b_0791c1: 11 leads from rtr-findmeeting run us_b

These come from the Find Meeting run `us_b` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 11 |
|---|---|---|
| youtube | channel | 8 |
| youtube | single_video | 3 |

## Why each lead was suggested (11 of 11 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Douglas ESD, Oregon (rtr:us:or:douglas-esd) | https://www.youtube.com/@DouglasESDComms | found on https://www.douglasesd.k12.or.us/: "YouTube(opens in new window/tab)" under heading "Logo Title"; page "Home - Douglas Education Service District"; nearby: "YouTube (opens in new window/tab)" |
| Hunt Memorial Hospital District, Texas (rtr:us:tx:hunt-memorial-hospital-district) | https://www.youtube.com/@huntregionalhealthcare9057 | found on https://www.huntregional.org/: "YouTube" under heading "Looking for support?"; page "Hunt Regional Healthcare / Close To Home, Caring For You"; nearby: "Contact Us Newsletter Sign-Up Give Now Connect with Us:" |
| Clackamas ESD, Oregon (rtr:us:or:clackamas-esd) | https://www.youtube.com/channel/UC81YKu77JdKtb8-OXfQyOPw/featured | found on https://www.clackesd.org/: "YouTube"; page "Educational Support for All" |
| Block House Municipal Utility District, Texas (rtr:us:tx:block-house-municipal-utility-district) | https://www.youtube.com/redirect?event=video_description&redir_token=QUFFLUhqbDRGN0dudURBd0IwdG5EZDV5N282UVR0ZW51Z3xBQ3Jtc0trWkp6LXJrSUY5VUN2RzZSd2JKOS1MS0l4NTQ3Q2Z0RnFpRFFlYm5Gdl9NX1BpTll6WHNjaWwySjRRNDRxbFkxa1A0RzFjRHFUdVc5emVKbnZ3UVkyd0cwNWl0eXVDWmVNLXRpM0o3TUhSbGJkeTFqNA&q=https%3A%2F%2FThisIsTexasWater.org%2F&v=2qDS-D9i66U | found on https://www.blockhousemudtx.gov/: "https://ThisIsTexasWater.org" under heading "BHC Campout"; page "Block House Municipal Utility District - Your Community Utility District for Water, Wastewater, and…"; nearby: "https://ThisIsTexasWater.org" |
| Harris County Emergency Services District #16, Texas (rtr:us:tx:harris-county-emergency-services-district-16) | https://www.youtube.com/channel/UCE-7nv8ygOGLy4I5wbPcDlA | found on https://www.hcesd16.org/: "youtube" under heading "Contact Us"; page "HCESD 16 / Harris County / Emergency Dial 911"; nearby: "Mailing and Physical Address: 18606 Stuebner Airline Rd Spring, TX 77379 Phone: (281) 607-4660 email: info@hcesd16.org Follow Us" |
| County Line Special Utility District, Texas (rtr:us:tx:county-line-special-utility-district) | https://www.youtube.com/watch?v=2TZ0VUfoswo | found on https://clsud.com/wp-json/wp/v2/posts?search=video&per_page=10&_fields=link,title,date,content |
| Montgomery County Emergency Services District #4, Texas (rtr:us:tx:montgomery-county-emergency-services-district-4) | https://www.youtube.com/channel/UCm1hH6gOKAer1iHiYDCMNug | found on https://www.mcesd4.com/: "Social media icon for youtubeSocial media icon for youtube" under heading "Homepage of Montgomery County Emergency Services District #4"; page "Homepage Montgomery County Emergency Services District #4"; nearby: "Social media icon for youtube Social media icon for youtube Social media icon for instagram Social media icon for instagram Social media icon for twitter Social media icon for twitter Social media ico" |
| Port of Beaumont Navigation District, Texas (rtr:us:tx:port-of-beaumont-navigation-district) | https://www.youtube.com/channel/UCcSAgAyxhItMENAhGjPRW4w | found on https://www.pobtx.com/: "Black YouTube Icon" under heading "PROGRESS"; page "HOME / Port of Beaumont"; nearby: "Geared Port of Beaumont 1225 Main Street, Beaumont, TX 77701 P.O. Drawer 2297, Beaumont, TX 77704 Phone: 409.835.5367 / Fax: 409.835.0512 / 877.835.7678 info@pobtx.com ​ © Port of Beaumont. All Rights" |
| Medina County Emergency Services District #1, Texas (rtr:us:tx:medina-county-emergency-services-district-1) | https://www.youtube.com/watch?v=XHOmBV4js_E | found on https://medinacountyfireems.org/ |
| Wilson County Memorial Hospital District, Texas (rtr:us:tx:wilson-county-memorial-hospital-district) | https://www.youtube.com/channel/UCETkrcCZ-NiXiDuhYPZAHdQ | found on https://www.connallymmc.org/: "YouTube"; page "Connally Memorial Medical Center"; nearby: "Custom Facebook Custom Instagram YouTube" |
| Montgomery County Emergency Services District #1, Texas (rtr:us:tx:montgomery-county-emergency-services-district-1) | https://www.youtube.com/channel/UCFbP2K6xDhzQutEBqQB2BqA | found on https://mcesd1.org/: "Youtube" under heading "FIRETRUCKS BLUE?"; page "Home - Montgomery County ESD 1"; nearby: "Facebook Youtube Instagram" |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
