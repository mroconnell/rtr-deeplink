# Drip handoff 2026-10-11_run-pass_589bbf: 65 leads from rtr-findmeeting run run_pass

These come from the Find Meeting run `run_pass` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 65 |
|---|---|---|
| youtube | channel | 39 |
| youtube | playlist | 3 |
| youtube | single_video | 23 |

## Low-confidence rows (2): verify skeptically

The handle names another body. Add a row only if the channel or video shows clear meetings of this government's board or school district body. `leads.csv` has no note column, so the doubt is written here (and in the drip-list note).

| Government | Address | Note |
|---|---|---|
| State of New Jersey, New Jersey (us:state:34) | https://www.youtube.com/user/NewJerseyGovernment | rtr-findmeeting run run_pass (2026-10-11): 1 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; low confidence: handle names a school district (the address is on a school district's row); suggested for State of New Jersey, New Jersey; address also on the list under Milford Borough School District, New Jersey (us:sd:3410170); drip: verify skeptically: add only if the channel or video shows clear meetings of this government's board or school district body; found on https://nj.gov/: "Youtube" under heading "NJ.gov"; page "The Official Web Site for The State of New Jersey"; nearby: "Toggle Social Links Open/Close X Facebook Youtube LinkedIn" |
| York, Maine (us:sd:2314130) | https://youtube.com/@townofyork?si=IzSA3WxnQNAS-sYs | rtr-findmeeting run run_pass (2026-10-11): also routed another way; 4 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; low confidence: handle names York County, Maine; suggested for York, Maine; address also on the list under York County, Maine (us:county:23031); drip: verify skeptically: add only if the channel or video shows clear meetings of this government's board or school district body; found on https://www.yorkschools.org/o/ysd/page/media-and-news |

## Shared with a neighbouring body (1)

Ryan (2026-10-03): fine to give each neighbouring body the row.

| Government | Address | Note |
|---|---|---|
| Empire Township, Michigan (us:cousub:2608926000) | https://www.youtube.com/channel/UCNQTgIgcTedF2qB8floC1GQ/ | rtr-findmeeting run run_pass (2026-10-11): 1 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; shared with neighbouring body Suttons Bay township (us:cousub:2608977620, also in Leelanau County); found on https://www.leelanau.cc/: "Subscribe to Leelanau County YouTube Video Service" under heading "Quick Links"; page "Leelanau County | Leelanau County"; nearby: "Subscribe to Leelanau County YouTube Video Service" |

## Why each lead was suggested (63 of 65 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Tolland, Connecticut (us:cousub:0911076290) | https://www.youtube.com/watch?v=RczwSHjuS2M&list=PLDCiapCnjSw1abSuf6n1-cLDlZk9gbsK7&index=52 | found on https://www.tolland.org/town-council/pages/town-council-meeting-videos |
| Butte County, South Dakota (us:county:46019) | https://www.youtube.com/watch?v=OaupvtNWJWI | found on https://www.buttesd.gov/index |
| Empire Township, Michigan (us:cousub:2608926000) | https://www.youtube.com/channel/UCNQTgIgcTedF2qB8floC1GQ/ | found on https://www.leelanau.cc/: "Subscribe to Leelanau County YouTube Video Service" under heading "Quick Links"; page "Leelanau County / Leelanau County"; nearby: "Subscribe to Leelanau County YouTube Video Service" |
| Cameron County, Pennsylvania (us:county:42023) | https://youtu.be/EBE6IUuk3Sk?feature=shared | found on https://www.cameroncountypa.com/government/commissioners/commissioner_meeting_videos.php |
| Oswego County, New York (us:county:36075) | https://www.youtube.com/channel/UCzqesXLoccfX73hbftLEPpA | found on https://www.oswegocountyny.gov/government/county_legislature/index.php |
| Chattahoochee Hills city, Georgia (us:place:1315552) | https://youtu.be/QBdvRnGpD8s | found on https://chatthillsga.us/government/council_meeting.php; flagged (Jev moment 4: no title evidence): the videos shown with it on the government's page had too few titles to judge |
| Fremont County, Wyoming (us:county:56013) | https://youtube.com/channel/UCQGpoBzZrFyqJk3gcpuORsQ/live | found on https://fremontcountywy.gov/government/elected_officials/commissioners/meeting.php |
| Fremont County, Wyoming (us:county:56013) | https://www.youtube.com/channel/UC8kxna8rEO84aOXZjfVlmCA/live | found on https://fremontcountywy.gov/government/elected_officials/commissioners/meeting.php |
| Fairfield city, Iowa (us:place:1926445) | https://www.youtube.com/playlist?list=PLA4A63648EFCC4134 | found on https://www.fairfieldiowa.com/: "HERE" under heading "Fairfield City Council Meeting"; page "The Fairfield Area Chamber of Commerce - Prosper Together"; nearby: "Fairfield City Council meets every 2nd & 4th Monday of the month at 7pm. Meetings are open to the public. Agendas are posted 24 hours in advance and are live streamed via the City of Fairfield YouTube" |
| Willoughby Hills city, Ohio (us:place:3985512) | https://youtube.com/@willoughbyhillsoh?si=DMmQffo7kjbozI3C | found on https://willoughbyhills-oh.gov/community/whtv___website.php |
| Morgan County School District, Alabama (us:sd:0102480) | https://www.youtube.com/@morgancountyschools367 | found on https://morgank12.org/social-media |
| Huntington Beach City Elementary School District, California (us:sd:0618030) | https://www.youtube.com/channel/UCgfuSczbIl0_4mg2qre09xg | found on https://hbcsd.us/13724_3 |
| Weston School District, Connecticut (us:sd:0905010) | https://www.youtube.com/channel/UCfiS5TdWMVozkWFY1FS3knw/live | found on https://www.westonps.org/111692_3 |
| West Hartford School District, Connecticut (us:sd:0904920) | https://www.youtube.com/watch?v=9MEQqkdoa_g&feature=youtu.be | found on https://www.whps.org/offices-and-programs/open-choice |
| Wilmington Community Unit School District 209U, Illinois (us:sd:1742630) | https://www.youtube.com/channel/UCFfQiFddMZIJCS4SmI7EmcQ | found on https://www.wilmington.will.k12.il.us/: "Subscribe to us on Youtube"; page "Home - Wilmington School District"; nearby: "Proud Home of the WILDCATS" |
| Cherokee County School District, Georgia (us:sd:1301110) | https://www.youtube.com/channel/UC_vSSEZXzXaZK24pF_bNEPQ | found on https://www.sequoyahregionallibrary.org/events |
| Thief River Falls School District, Minnesota (us:sd:2738850) | https://youtu.be/lXpSNoLjluc | found on https://www.trfschools.org/district-info/k-12-education-subtraction/informational-video |
| Independence 30 School District, Missouri (us:sd:2915480) | https://www.youtube.com/@independenceschooldistrict1756 | found on https://www.isdschools.org/our-district/departments/public-relations |
| Papillion-La Vista Community Schools, Nebraska (us:sd:3175270) | https://www.youtube.com/channel/UCPiYuOYB1lzaERn-g4Dn-tg | found on https://www.plcschools.org/our-district/board-of-education/meetings: under heading "Meeting Livestream"; page "Meetings - Papillion La Vista Community Schools"; nearby: "PLCS Board of Education meetings are held on the 2nd and 4th Monday of each month at 6 p.m. All meetings are open to the public and are held at the PLCS Central Office located at 420 S. Washington Str" |
| Floyd Municipal Schools, New Mexico (us:sd:3501020) | https://www.youtube.com/@FloydEsports | found on https://floydbroncos.com/166193_2: "Floyd Esports on You­Tube" under heading "Live Stream Home"; page "Floyd Municipal Schools - Live Stream Home"; nearby: "Floyd Esports on You­Tube" |
| Marshall Public Schools, Michigan (us:sd:2622970) | https://www.youtube.com/channel/UCo_Dw2K8ptX5eFKauouPJZQ | found on https://www.marshallpublicschools.org/: "YouTube(opens in new window/tab)" under heading "Stay Connected"; page "Home - Marshall Public School District"; nearby: "YouTube (opens in new window/tab)" |
| Chippewa Local School District, Ohio (us:sd:3905053) | https://www.youtube.com/watch?v=zgmDx-vnhDQ | found on https://www.chippewaschools.org/wp-json/wp/v2/posts?search=video&per_page=10&_fields=link,title,date,content |
| Battiest Public Schools, Oklahoma (us:sd:4003660) | https://www.youtube.com/playlist?list=PLTTWdUcy0p-6iP1CjW34RdJHm4iR1NfZN | found on https://www.battiest.k12.ok.us/training-videos: "Promethean Nickel Training Videos" under heading "Training Videos"; page "Battiest Public Schools - Training Videos"; nearby: "Promethean Nickel Training Videos" |
| Plum Borough School District, Pennsylvania (us:sd:4219350) | https://youtu.be/5Br_W2f21I4 | found on https://www.pbsd.net/PlumBoroughSchoolDistrictLiveEvents.aspx: "Rachel's Story" under heading "Plum Borough School District Live Events"; page "Plum Borough School District Live Events"; nearby: "Rachel's Story Rachel's Challenge Goals Rachel's Code of Ethics" |
| McNairy County School District, Tennessee (us:sd:4702880) | https://www.youtube.com/watch?v=QgkBDMNMCV0 | found on https://www.mcnairycountyschools.com/apps/video/watch.jsp?v=349040: embed title "YouTube video player" under heading "Most Recent Videos"; page "Video Gallery / McNairy County School District"; nearby: "FERPA - 101 Student Privacy"; flagged (Jev moment 4: unsure): Jev could not tell whether the videos shown with it on the government's page are meetings |
| Lexington City School System, Tennessee (us:sd:4702460) | https://www.youtube.com/watch?v=qE2fEtHWWmc | found on https://caywood.org/129735_2: embed title "1:1 Refresher Video" under heading "1:1 Refresher Video"; page "Lexington City Schools - 1:1 Refresher Video" |
| Perkiomen Valley School District, Pennsylvania (us:sd:4218930) | https://www.youtube.com/user/PerkValleySD/videos | found on https://www.pvsd.org/2026/10/06/school-board-business-meeting-10-13/: "District’s YouTube page" under heading "School Board Business Meeting (10/13)"; page "School Board Business Meeting (10/13) - Perkiomen Valley School District"; nearby: "The School Board of Directors holds its monthly business meeting on the second Monday of each month @ 7:00pm, onsite in the PV High School Auditorium. The meeting is also broadcast on the District’s Y" |
| Crockett Independent School District, Texas (us:sd:4815720) | https://youtube.com/live/zKEWtWHoGbg?feature=share | found on https://www.crockettisd.net/live-feed/?page_no=1 |
| Marble Falls Independent School District, Texas (us:sd:4829010) | https://www.youtube.com/channel/UCYrBl4nAtpEponPMD62KF-g | found on https://mfisd.org/: under heading "District Events"; page "Marble Falls Independent School District - Home"; nearby: "Marble Falls Independent School District Address: 1800 Colt Circle Marble Falls, TX 78654 Phone: 830-693-4357 Email: postmaster@mfisd.txed.net" |
| Mineola Independent School District, Texas (us:sd:4830930) | https://youtu.be/mmCW76i56Ko | found on https://www.mineolaisd.net/live-feed/?page_no=68 |
| Navarro Independent School District, Texas (us:sd:4832160) | https://www.youtube.com/@NavarroPantherEvents | found on https://www.navarroisd.us/schoolboard: "YouTube Channel @NavarroPantherEvents" under heading "Live Stream & Recordings"; page "Navarro Independent School District - Board Members"; nearby: "Navarro ISD Board of Trustee regular and special meetings are live recorded and can be streamed online through our district YouTube Channel @NavarroPantherEvents Click the video to watch the latest re" |
| State of New Jersey, New Jersey (us:state:34) | https://www.youtube.com/user/NewJerseyGovernment | found on https://nj.gov/: "Youtube" under heading "NJ.gov"; page "The Official Web Site for The State of New Jersey"; nearby: "Toggle Social Links Open/Close X Facebook Youtube LinkedIn" |
| West Allis School District, Wisconsin (us:sd:5516260) | https://www.youtube.com/channel/UCXDzvBQStTwu_AFYKr7dRwg/ | found on https://www.wawmsd.org/apps/pages/index.jsp?uREC_ID=4430667&type=d&pREC_ID=2670167: "YouTube channel" under heading "School Board"; page "School Board - District - West Allis-West Milwaukee School District"; nearby: "Regular school board meetings can be viewed live via Zoom; please see the current agenda for the appropriate Zoom meeting link. Meetings are stored on YouTube and can be viewed on the district's YouTu" |
| River Valleys Unified School District 73, Vermont (us:sd:5000447) | https://www.youtube.com/watch?v=s9VAfxdX0h0 | found on https://www.windhamcentral.org/stratton-board-recordings |
| Bradley County, Tennessee (us:county:47011) | https://www.youtube.com/channel/UC-h00M-8N6jvJ0hiTtwPHgA | found on https://bradleycountytn.gov/: "Follow" under heading "Bradley County Mayor Gary Davis"; page "Home - Bradley County, TN"; nearby: "Follow Follow Follow Follow" |
| Cocke County, Tennessee (us:county:47029) | https://www.youtube.com/@cockecounty59 | found on https://www.cockecountytn.gov/county-legislative-body |
| Greenwich township, New Jersey (us:cousub:3401528185) | https://youtu.be/qPZj4IyLFlY | found on https://greenwichtwp.com/2196/Mayor |
| Irvington Township, New Jersey (us:cousub:3401334450) | https://www.youtube.com/channel/UCJbBM_pAPYcc_FkbD484p-A | found on https://irvingtonnj.gov/: "Youtube" under heading "Live Here. Play Here. Thrive Here!"; page "Township of Irvington New Jersey" |
| Lake Luzerne town, New York (us:cousub:3611340662) | https://www.youtube.com/channel/UCwmUjO7WSB0rEFvB8rC_V-w | found on https://www.lakeluzerneny.gov/: "Decorative YouTube logo on transparent background linking to the Town of Lake Luzerne YouTube page, reading, 'Subscribe…" under heading "Smart Growth Zoning Update"; page "Town of Lake Luzerne, NY"; nearby: "Website Home Page Last Updated on Monday, October 5th, 2026 (2:44 PM) Town of Lake Luzerne: Invitation to Bid Click here to find a PDF copy of the Invitation to bid. Town of Lake Luzerne: Solid Waste" |
| Auburn city, Georgia (us:place:1304140) | https://www.youtube.com/watch?v=7uMbQuGIrd8 | found on https://www.cityofauburn-ga.org/agendas-minutes |
| Halifax, Massachusetts (us:cousub:2502327795) | https://www.youtube.com/channel/UCKx085x3I6N7HXg7Zsr4T_g | found on https://halifaxma.gov/1965/Town-Government |
| Muscle Shoals city, Alabama (us:place:0153016) | https://www.youtube.com/@CityofMuscleShoals1 | found on https://www.cityofmuscleshoals.com/: "YouTube"; page "Muscle Shoals, AL / Official Website" |
| Callaway village, Nebraska (us:place:3107660) | https://www.youtube.com/watch?v=c9I6OZBoqxg | found on https://villageofcallawayne.gov/f/kite-flight-video |
| Dannemora village, New York (us:place:3619642) | https://www.youtube.com/watch?v=b532tUWfd5U | found on https://www.townofdannemora.gov/meeting-minutes |
| Homestead city, Florida (us:place:1232275) | https://www.youtube.com/@TheCityofHomestead/streams | found on https://homesteadfl.gov/: "Youtube" under heading "Social Links"; page "Homestead, FL - Official Website / Official Website"; nearby: "Facebook X Instagram Youtube Flickr Threads Nextdoor LinkedIn" |
| Ruidoso village, New Mexico (us:place:3565210) | https://www.youtube.com/channel/UCiI01gVEgmVcl-vZLOxTN0w/featured | found on https://www.ruidoso-nm.gov/village-council-agenda-packets |
| Brunswick town, North Carolina (us:place:3708420) | https://www.youtube.com/watch?v=WzqrwPhXmew | found on https://townofbrunswicknc.gov/council/ |
| University City city, Missouri (us:place:2975220) | https://www.youtube.com/c/UniversityCityGovernment | found on https://ucitymo.org/: "More here..." under heading "Video Spotlight"; page "University City, MO - Official Website / Official Website"; nearby: "Video Spotlight Check out our YouTube channel to watch Council Meetings streamed live and stay up-to-date with University City Updates More here..." |
| Trumansburg village, New York (us:place:3675506) | https://www.youtube.com/@trumansburgareameetings3194/streams | found on https://trumansburg-ny.gov/boards/board-of-trustees |
| Biltmore Forest town, North Carolina (us:place:3705880) | https://youtu.be/xQnIPRK51tQ | found on https://www.biltmoreforest.org/town-biltmore-forest-centennial-celebration |
| Grant Community Consolidated School District 110, Illinois (us:sd:1717310) | https://youtube.com/shorts/rPVXNb76hWs?feature=share | found on https://www.dist110.com/live-feed/?page_no=3 |
| Chester-East Lincoln Community CSD 61, Illinois (us:sd:1709850) | http://www.youtube.com/watch?v=V230m-K7im0&feature=youtu.be | found on https://www.cel61.com/extra_curricular/student_spectators_at_athletic_events |
| Zeigler-Royalton Community Unit School District 188, Illinois (us:sd:1743800) | https://www.youtube.com/watch?v=inPjxI9itok | found on https://www.zr188.org/live-feed/?page_no=11 |
| York, Maine (us:sd:2314130) | https://youtube.com/@townofyork?si=IzSA3WxnQNAS-sYs | found on https://www.yorkschools.org/o/ysd/page/media-and-news |
| York, Maine (us:sd:2314130) | http://www.youtube.com/@YorkSchoolDepartment.ysd1 | found on https://www.yorkschools.org/o/ysd/page/media-and-news |
| York, Maine (us:sd:2314130) | https://www.youtube.com/channel/UCcugqZHLsodp8sCCSk03ncA | found on https://www.yorkschools.org/o/ysd/page/media-and-news |
| Reed City Area Public Schools, Michigan (us:sd:2629490) | https://www.youtube.com/@reedcityareapublicschools834 | found on https://www.reedcityschools.org/live-feed/?page_no=1 |
| Westwood Heights Schools, Michigan (us:sd:2635970) | https://www.youtube.com/@westwoodheightsschoolsmedi2196/streams | found on https://www.hamadyhawks.net/administration/board_of_education/BoardMeetingPublicView |
| Hubbard Exempted Village School District, Ohio (us:sd:3904542) | https://youtu.be/AF_8F2RwE40 | found on https://www.hubbard.k12.oh.us/live-feed/?page_no=16 |
| Hamburg Area School District, Pennsylvania (us:sd:4211340) | https://youtu.be/URe1bs5mg84?si=yGdw0yRxTWvSpnhp | found on https://www.hasdhawks.org/live-feed/?page_no=3 |
| Valleyview village, Ohio (us:place:3979282) | https://www.youtube.com/channel/UCXKY84BRtavCkzWftZGquyA | found on https://valleyview.net/government/agendas___minutes/council_minutes.php |
| Calloway County School District, Kentucky (us:sd:2100870) | https://www.youtube.com/channel/UCTLfKiP72IY-e5F-Edo8a6g | found on https://www.calloway.kyschools.us/: "You Tube(opens in new window/tab)" under heading "District Calendar"; page "Home - Calloway County Schools"; nearby: "You Tube (opens in new window/tab)" |
| McCreary County School District, Kentucky (us:sd:2103990) | https://www.youtube.com/channel/UCf2BcMd-ENCfNBHI-Kgt47A | found on https://www.mccreary.k12.ky.us/: "McCreary Schools Youtube Sports Channel(opens in new window/tab)" under heading "Main Menu"; page "Home - McCreary County School District"; nearby: "McCreary Schools Youtube Sports Channel (opens in new window/tab)" |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
