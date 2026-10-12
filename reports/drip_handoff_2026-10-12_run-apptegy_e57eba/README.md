# Drip handoff 2026-10-12_run-apptegy_e57eba: 120 leads from rtr-findmeeting run run_apptegy

These come from the Find Meeting run `run_apptegy` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 120 |
|---|---|---|
| youtube | channel | 110 |
| youtube | playlist | 4 |
| youtube | single_video | 6 |

## Low-confidence rows (1): verify skeptically

The handle names another body. Add a row only if the channel or video shows clear meetings of this government's board or school district body. `leads.csv` has no note column, so the doubt is written here (and in the drip-list note).

| Government | Address | Note |
|---|---|---|
| Milton School District, Massachusetts (us:sd:2507980) | https://www.youtube.com/@miltonaccesstv | rtr-findmeeting run run_apptegy (2026-10-12): its meeting source has no video; 6 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; low confidence: handle names Milton town, Massachusetts; suggested for Milton School District, Massachusetts; address also on the list under Milton town, Massachusetts (us:cousub:2502141690); drip: verify skeptically: add only if the channel or video shows clear meetings of this government's board or school district body |

## Why each lead was suggested (54 of 120 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Vail Unified District, Arizona (us:sd:0408850) | https://www.youtube.com/channel/UCEbo7IVBlGe0b4NKN7eO6Og | found on https://www.vailschooldistrict.org/live-feed/?page_no=1 |
| Vail Unified District, Arizona (us:sd:0408850) | https://www.youtube.com/channel/UCEbo7IVBlGe0b4N | found on https://www.vailschooldistrict.org/live-feed/?page_no=1 |
| Vail Unified District, Arizona (us:sd:0408850) | https://www.youtube.com/channel/UCEbo7IVBlGe0b4NKN | found on https://www.vailschooldistrict.org/live-feed/?page_no=1 |
| Kingman Unified School District, Arizona (us:sd:0400295) | https://www.youtube.com/@KUSD20 | found on https://www.kusd.org/: "Visit us on Youtube" under heading "Stay Connected"; page "Home / Kingman Unified School District #20"; nearby: "Find Us Kingman USD #20 3033 MacDonald Avenue Kingman, AZ 86401 Phone: (928) 753-5678 Fax: (928) 753-6910 webmaster@kusd.org Career Opportunities Find your Career with KUSD20 Utility Accessibility Sta" |
| Springdale School District, Arkansas (us:sd:0512660) | https://www.youtube.com/@SpringdaleSchoolsTV | found on https://www.sdale.org/page/school-board |
| Illini Central Community Unit School District 189, Illinois (us:sd:1700113) | https://www.youtube.com/@ion.television | found on https://iontelevision.com/ |
| Bethalto Consolidated Unit School District 8, Illinois (us:sd:1706120) | https://www.youtube.com/watch?v=WKY5rbVoUc0 | found on https://www.bethalto.org/live-feed/?page_no=1 |
| Dixon Unit School District 170, Illinois (us:sd:1712330) | https://www.youtube.com/@dixonpublicschools1706 | found on https://www.dps170.org/: "Visit us on Youtube" under heading "Stay Connected"; page "Home / Dixon Public Schools"; nearby: "Find Us Dixon Public Schools 1335 Franklin Grove Rd Dixon, IL 61021 Phone: (815) 373-4966 Fax: (815) 284-8576 Stay Connected" |
| Limestone Community High School District 310, Illinois (us:sd:1722950) | https://www.youtube.com/channel/UC8ODtIFkaaZKiQtwOJll5SA | found on https://www.limestone310.org/: "Dunlap" under heading "Athletics"; page "Limestone Community High School" |
| Limestone Community High School District 310, Illinois (us:sd:1722950) | https://www.youtube.com/channel/UCe2C0ga6nZ9LJEoiNiYwIcA | found on https://www.limestone310.org/: "East Peoria" under heading "Athletics"; page "Limestone Community High School" |
| Limestone Community High School District 310, Illinois (us:sd:1722950) | https://www.youtube.com/channel/UCxYpjdlXOvsqBkuvRsWcdMQ | found on https://www.limestone310.org/: "Metamora" under heading "Athletics"; page "Limestone Community High School" |
| Limestone Community High School District 310, Illinois (us:sd:1722950) | https://www.youtube.com/channel/UCiXoRkCWqu-qK-YA2ij11sw?c=UCiXoRkCWqu-qK-YA2ij11sw | found on https://www.limestone310.org/: "Washington" under heading "Athletics"; page "Limestone Community High School" |
| Olympia Community Unit School District 16, Illinois (us:sd:1729890) | https://www.youtube.com/channel/UCVOxrb6NPFm9b0Gq5CdHZ4Q | found on https://www.olympia.org/: "Visit us on Youtube" under heading "Stay Connected"; page "Olympia CUSD 16 / Home"; nearby: "Find Us Olympia CUSD 16 903 East 800 North Road Stanford, IL 61774 1- 309-379-6011 309-379-2328 Privacy Policy Privacy Policy Schools Olympia CUSD 16 Olympia High School Olympia Middle School Olympia" |
| Riverside School District 96, Illinois (us:sd:1733990) | https://youtube.com/live/RKw-Z7Rve-o?feature=share | found on https://www.district96.org/page/board-meeting-information |
| Fairfield Community High School District 225, Illinois (us:sd:1726180) | https://www.youtube.com/watch?v=DSnEYtQwC3M | found on https://www.fchsmules.com/live-feed/?page_no=70 |
| Triad Community Unit School District 2, Illinois (us:sd:1737350) | https://www.youtube.com/user/TriadKnightsTV | found on https://www.tcusd2.org/live-feed/?page_no=2 |
| Blackford County Schools, Indiana (us:sd:1800570) | https://www.youtube.com/@BCSBoardMeetings | found on https://www.bcs.k12.in.us/live-feed/?page_no=3 |
| South Harrison Community Schools, Indiana (us:sd:1810360) | https://www.youtube.com/@southharrisoncommunityscho3323 | found on https://www.shcsc.k12.in.us/o/shcsc/page/board-information |
| Saco Public Schools, Maine (us:sd:2310380) | https://www.youtube.com/@RyanDrBuckets | found on https://www.sacoschools.org/live-feed/?page_no=1 |
| Charles County Public Schools, Maryland (us:sd:2400270) | https://www.youtube.com/c/ccpsmd/featured | found on https://www.ccboe.com/: "Visit us on Youtube" under heading "Stay Connected"; page "Home / Charles County Public Schools"; nearby: "Find Us Charles County Public Schools 5980 Radio Station Road La Plata, MD 20646 Phone: 301-932-6610 301-392-7579 / TTY 301-932-6656 / Info Line 240-523-3032 / Spanish Hotline Popular Links At-A-Glanc" |
| Swartz Creek Community Schools, Michigan (us:sd:2633420) | https://www.youtube.com/@SwartzCreekCommunitySchools/live | found on https://www.swartzcreek.org/live-feed/?page_no=4 |
| Lincoln Consolidated School District, Michigan (us:sd:2621570) | https://www.youtube.com/@lincolnrailsplitters9284 | found on https://www.lincolnk12.org/: "Visit us on Youtube" under heading "Stay Connected"; page "Home / Lincoln Consolidated Schools"; nearby: "Find Us Lincoln Consolidated Schools 7425 Willis Road Ypsilanti, MI 48197 Phone: (734) 484-7000 Stay Connected" |
| Luverne Public School District, Minnesota (us:sd:2718330) | https://www.youtube.com/c/LuverneCardinalVision | found on https://www.isd2184.net/live-feed/?page_no=2 |
| Montevideo Public School District, Minnesota (us:sd:2721320) | https://youtu.be/z3o7xsUprc8 | found on https://www.montevideoschools.org/live-feed/?page_no=33 |
| Chase County Schools, Nebraska (us:sd:3100163) | https://www.youtube.com/channel/UCtG3OV7VgyiF5_6DXJr9FSA/featured | found on https://www.chasecountyschools.org/: "Visit us on Youtube" under heading "Stay Connected"; page "Home / Chase County Schools"; nearby: "Find Us Chase County Schools 520 East 9th Street Imperial, Nebraska 69033 ph: 308-882-4304 fax 308-882-5629 https://www.chasecountyschools.org/ BUS DISPATCH ph: 308-882-4214 Schools Chase County Schoo" |
| Aurora Public Schools, Nebraska (us:sd:3103360) | https://www.youtube.com/@aurorahuskystrength | found on https://www.aurorahuskies.org/: "Husky Strength Youtube Channel" under heading "Aurora Public Schools - Home of the Huskies"; page "Aurora Public Schools"; nearby: "Husky Strength Youtube Channel" |
| Hondo Valley Public Schools, New Mexico (us:sd:3501290) | https://www.youtube.com/watch?v=nv87eyvNxY0 | found on https://www.hondoeagles.org/live-feed/?page_no=19 |
| Coxsackie-Athens Central School District, New York (us:sd:3608490) | https://www.youtube.com/user/CommonSenseEducators | found on https://www.commonsense.org/education/video/digital-citizenship?page=1 |
| East Aurora Union Free School District, New York (us:sd:3609540) | https://www.youtube.com/@eastaurorabdtv9781 | found on https://www.eastauroraschools.org/: "EA BDTV LiveStreams" under heading "East Aurora Union Free School District"; page "Home / East Aurora Union Free School District"; nearby: "Events Download the EA App Blue Devil Design EA BDTV LiveStreams Athletics" |
| Norwich City School District, New York (us:sd:3621330) | https://www.youtube.com/channel/UCVfQ7LdPlEOTxV5wm4PUXpg | found on https://www.norwichcsd.org/live-feed/?page_no=277 |
| Sidney Central School District, New York (us:sd:3626850) | https://www.youtube.com/@SidneyCSD | found on https://www.sidneycsd.org/: "Visit us on Youtube" under heading "Stay Connected"; page "Home / Sidney Central School District"; nearby: "Find Us Sidney Central School District 95 West Main Street Sidney, NY 13838 Phone: 607-563-2135 Fax: 607-563-2386 Schools Sidney Central School District Sidney Jr/Sr High Sidney Elementary Stay Connec" |
| Locust Valley Central School District, New York (us:sd:3617700) | https://www.youtube.com/c/LocustValleyBoardofEducation | found on https://www.locustvalleyschools.org/: "Visit us on Youtube" under heading "Stay Connected"; page "Home / Locust Valley Central School District"; nearby: "Find Us Locust Valley Central School District 22 Horse Hollow Road Locust Valley, NY 11560 Phone: 516.277.5000 Schools Locust Valley Central School District Bayville Primary School Ann MacArthur Prima" |
| Marlboro Central School District, New York (us:sd:3618570) | https://www.youtube.com/@MarlboroCSDVideos | found on https://www.marlboroschools.org/live-feed/?page_no=3 |
| Owego-Apalachin Central School District, New York (us:sd:3622170) | https://www.youtube.com/@ABCNews | found on https://abcnews.com/video/127037028/ |
| Alden Central School District, New York (us:sd:3602550) | https://www.youtube.com/watch?v=osyRkL55Ows | found on https://www.aldenschools.org/live-feed/ |
| Alexander Local School District, Ohio (us:sd:3904590) | https://www.youtube.com/@alexdistrict8775/streams | found on https://www.alexanderschools.org/live-feed/?page_no=2 |
| Centerburg Local School District, Ohio (us:sd:3904782) | https://www.youtube.com/@OH.ReportLive04 | found on https://www.centerburgschools.org/live-feed/?page_no=1 |
| Mechanicsburg Area School District, Pennsylvania (us:sd:4215030) | https://www.youtube.com/@GoMechanicsburg/streams | found on https://www.mbgsd.org/o/gomechanicsburg/page/live-stream/ |
| Norristown Area School District, Pennsylvania (us:sd:4216980) | http://www.youtube.com/@nasdtv | found on https://www.nasd.k12.pa.us/live-feed/?page_no=1 |
| Mount Pleasant Area School District, Pennsylvania (us:sd:4216170) | https://www.youtube.com/@MountPleasantTV | found on https://www.mpasd.net/: "Board Meeting Video Archive" under heading "School Board"; page "Home / Mount Pleasant Area School District"; nearby: "Board Meeting Video Archive" |
| Elkton School District 05-3, South Dakota (us:sd:4621390) | https://www.youtube.com/@elksliveticket | found on https://www.elkton.k12.sd.us/live-feed/?page_no=3 |
| Elkton School District 05-3, South Dakota (us:sd:4621390) | https://www.youtube.com/@howardschooldistrict48-39 | found on https://www.elkton.k12.sd.us/live-feed/?page_no=2 |
| Marion School District 60-3, South Dakota (us:sd:4645450) | https://www.youtube.com/channel/UCKLAnmPeSCBcCQU48vahXgw | found on https://www.dakotanewsnow.com/community/user-content |
| Edgewood Independent School District, Texas (us:sd:4818120) | https://www.youtube.com/c/EISDLiveBroadcasts | found on https://www.edgewood-isd.net/: "Visit us on Youtube" under heading "Stay Connected"; page "Home / Edgewood ISD"; nearby: "Find Us Edgewood ISD 804 E Pine Edgewood, TX 75117 Phone: (903) 896-4332 *For all Budget information visit the Financial Transparency page* Title IX Coordinator and 504 Coordinator Title VI Coordinato" |
| Henrietta Independent School District, Texas (us:sd:4822980) | https://www.youtube.com/@henriettahs/streams | found on https://www.henrietta-isd.net/o/athletics/events |
| College Place School District, Washington (us:sd:5301470) | https://www.youtube.com/channel/UCaVxW5BYldpoNagbKDW_KEg | found on https://www.cpps.org/o/high-school/documents/graduation-/class-of-2020/class-of-2020-senior-awards-and-recognition-video/137174 |
| Montgomery County Public Schools, Virginia (us:sd:5102520) | https://www.youtube.com/@mcpsva | found on https://www.mcps.org/live-feed/?page_no=3 |
| Colfax School District, Wisconsin (us:sd:5502790) | http://www.youtube.com/@durandbroadcastingwrdn8401 | found on https://www.colfax.k12.wi.us/live-feed/?page_no=3 |
| Lakeland Union High School District, Wisconsin (us:sd:5509630) | https://www.youtube.com/@LUHSLiveStreams | found on https://www.luhs.k12.wi.us/: "LUHS Live YouTube" under heading "LIVESTREAM"; page "Home / Lakeland Union High School" |
| Clayton School District, Wisconsin (us:sd:5502580) | https://www.youtube.com/@wearegrantsburgYT/streams | found on https://www.claytonsd.k12.wi.us/live-feed/?page_no=2 |
| Middleton-Cross Plains School District, Wisconsin (us:sd:5509510) | https://www.youtube.com/c/Channel3000/ | found on https://www.channel3000.com/features/in-the-608-mcpasd-in-need-of-bus-drivers-for-new-school-year/article_bfae8c2c-e7ee-4e4c-b855-b2da086d55ac.html |
| Middleton-Cross Plains School District, Wisconsin (us:sd:5509510) | https://www.youtube.com/user/EduChannel96988/videos | found on https://www.mcpasd.k12.wi.us/o/mhs/page/daily-announcements-videos/ |
| Osseo-Fairchild School District, Wisconsin (us:sd:5511220) | https://www.youtube.com/@Osseo-Fairchild-Bands | found on https://www.ofsd.k12.wi.us/live-feed/?page_no=42 |
| Big Foot Union High School District, Wisconsin (us:sd:5515480) | https://www.youtube.com/@bigfoothighschool7288 | found on https://www.bigfoot.k12.wi.us/: "Visit us on Youtube" under heading "Stay Connected"; page "BIG FOOT HIGH SCHOOL / Home"; nearby: "Find Us Big Foot High School District 401 Devils Ln Walworth, WI 53184 Phone (262) 275-2116 Fax (262) 275-5117 Stay Connected" |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
