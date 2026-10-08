# Drip handoff 2026-10-07_run-batch-domains_f9e607: 45 leads from rtr-findmeeting run run_batch_domains

These come from the Find Meeting run `run_batch_domains` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 45 |
|---|---|---|
| youtube | channel | 32 |
| youtube | playlist | 1 |
| youtube | single_video | 12 |

## Why each lead was suggested (41 of 45 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Sangerville town, Maine (us:cousub:2302165865) | https://www.youtube.com/@townofsangerville | found on https://sangervilleme.com/: "YouTube" under heading "Special Town Meeting"; page "Official Web Site of Town of Sangerville, ME"; nearby: "51°F 8 mph Feels like: 49°F Facebook YouTube" |
| Colonie village, New York (us:place:3617332) | https://www.youtube.com/channel/UCYR1exEIlSCYxMV3LxDRR0w | found on https://colonievillage.gov/agendas-minutes/ |
| Dwight city, Kansas (us:place:2019125) | https://www.youtube.com/channel/UCFNbKD8CuLCkCdWDFiO9hqQ | found on https://eficor.org/: "Visit our YouTube channel"; page "The Evangelical Fellowship of India Commission on Relief - EFICOR"; nearby: "Visit our Facebook Visit our Instagram Visit our YouTube channel" |
| Warwick village, New York (us:place:3678355) | https://www.youtube.com/channel/UCK7D7KGbZF6nYfbcWGH6-VA/featured | found on https://villageofwarwickny.gov/: "Youtube"; page "Village of Warwick NY Home Page - Village of Warwick"; nearby: "Facebook Youtube Residents 28 Church Street – West Warwick 3 Battery Energy Storage Site Fire: Information & Updates Brush Disposal Chicken Ordinance Review Fair Housing Information FAQs Housing Progr" |
| Shawnee Hills village, Ohio (us:place:3971976) | https://www.youtube.com/channel/UCMEhk7pNuBMUYafXGNkoNkA | found on https://shawneehillsoh.org/government/city_council |
| Southwest Utah Public Health Department, Utah (rtr:us:ut:southwest-utah-public-health-department) | https://www.youtube.com/channel/UC98dqld8xOOAAlWGq_8sE4w | found on https://swuhealth.gov/: "Follow" under heading "Prevent • Promote • Protect"; page "Southwest Utah Public Health Department - Home"; nearby: "Follow Follow Follow Follow" |
| Grand Water and Sewer Service Agency, Utah (rtr:us:ut:grand-water-and-sewer-service-agency) | https://youtu.be/R-YF3fi8UrQ?si=5Oc_8Uk0XOL7MdLB | found on https://www.grandwatersewerut.gov/: "Tier Rates - Youtube Video"; page "Grand Water & Sewer Service Agency / 3025 E Spanish Trail Road, Moab, UT, USA"; nearby: "Tier Rates - Youtube Video" |
| Troup County School District, Georgia (us:sd:1300001) | https://www.youtube.com/@TroupCountySchoolSystem | found on https://www.troup.org/: "YouTube(opens in new window/tab)" under heading "nav-social"; page "Home - Troup County Schools"; nearby: "YouTube (opens in new window/tab)" |
| Moreau town, New York (us:cousub:3609148318) | https://www.youtube.com/watch?v=BidggwKiNv8&t=15s | found on https://townofmoreau.org/: "QUALITY OF LIFE"; page "The Town of Moreau in Saratoga County, New York"; nearby: "EXPLORE SARATOGA COUNTY!!"; flagged (Jev moment 4: no title evidence): the videos shown with it on the government's page had too few titles to judge |
| Franklin County, Pennsylvania (us:county:42055) | http://www.youtube.com/@countycommissioners8113/streams | found on https://www.franklincountypa.gov/departments/commissioners-office/ |
| Northville Public Schools, Michigan (us:sd:2625980) | https://www.youtube.com/@NorthvillePublicSchools | found on https://www.northvilleschools.org/: "YouTube(opens in new window/tab)" under heading "Connect & Share"; page "Home - Northville Public Schools"; nearby: "YouTube (opens in new window/tab)" |
| Plymouth County, Massachusetts (us:county:25023) | https://youtu.be/Qy0MVDbxOXk | found on https://plymouthcountyma.gov/204/Meetings |
| Honey Grove city, Texas (us:place:4834700) | http://www.youtube.com/@CityofHoneyGroveTexas | found on https://cityofhoneygrove.org/government/city_hall/city_council_agenda.php |
| Marlboro town, Vermont (us:cousub:5002543375) | https://www.youtube.com/channel/UC5LJFAyXoNvZihDFa03q0wQ | found on https://marlborovt.us/boards-minutes/select-board/ |
| Dickenson County, Virginia (us:county:51051) | https://youtu.be/0aVhYmAzouE | found on https://dickensonva.org/27/Government; flagged (Jev moment 4: no title evidence): the videos shown with it on the government's page had too few titles to judge |
| Ozark city, Arkansas (us:place:0552970) | https://www.youtube.com/@OzarkCityHall | found on https://www.cityofozarkar.com/: "Visit us on Youtube" under heading "Stay Connected"; page "Home / City of Ozark"; nearby: "Find Us City of Ozark 2910 West Commercial Ozark, AR 72949 Phone: (479) 667-2238 Employment Opportunity Job Application Stay Connected" |
| Granville town, Vermont (us:cousub:5000129575) | https://www.youtube.com/@Granville_OpenMeetings | found on https://granvillevermont.org/: "Stop on by our YouTube channel here!"; page "Granville, Vermont / Chartered 1781"; nearby: "Stop on by our YouTube channel here!" |
| Rockport city, Indiana (us:place:1865484) | https://www.youtube.com/@CityofRockportIN | found on https://rockport.in.gov/: "Live Streaming of Meetings"; page "City of Rockport, IN – Established 1808!"; nearby: "Live Streaming of Meetings" |
| Gladbrook city, Iowa (us:place:1931035) | https://www.youtube.com/watch?v=ddtR3vuwbiY&feature=youtu.be | found on https://www.gladbrook.org/: "Community Video" under heading "Community Video"; page "City of Gladbrook"; nearby: "________________________________________________________ Gladbrook Community Community Video Gladbrook is a town of 799 people that is “Alive and Growing.” Located in central Iowa, it is about 45 mile" |
| Plymouth city, California (us:place:0657834) | https://www.youtube.com/@cityofplymouth1463/streams | found on https://cityofplymouth.org/agendas-and-reports/ |
| Plymouth city, California (us:place:0657834) | https://www.youtube.com/channel/UCkjXhhD4MPQqteClvzD0Q8g | found on https://cityofplymouth.org/planning-commission/ |
| Claypool town, Indiana (us:place:1813312) | https://youtu.be/3D6B7gVEDCg?si=etRdx6t_yO7sxttT | found on https://townofclaypool.org/august-19th-2025-meeting-minutes/ |
| Mulberry town, Indiana (us:place:1851840) | https://www.youtube.com/@townofmulberryin/ | found on https://www.townofmulberry.com/: "Follow" under heading "Livestream"; page "Town of Mulberry, Indiana"; nearby: "Follow Follow Follow" |
| Lake View city, Iowa (us:place:1942690) | https://www.youtube.com/channel/UCq6sZSJqILgfmXxIWsIsAHw | found on https://lakeviewlifestyle.com/; page "Lake View, Home of Beautiful Black Hawk Lake"; nearby: "Our Community Churches Education Healthcare History/Museum Library Service Organizations Our Partners City Government City Information City Officials City Council City Boards Economic Development City" |
| Central Lake village, Michigan (us:place:2614400) | https://www.youtube.com/channel/UC-KDTVrj8Kn5v_PshHfo80g | found on https://centrallakemi.org/village-council-meetings/ |
| Lattingtown village, New York (us:place:3641432) | https://youtu.be/ATNy-vaIPXI | found on https://www.lattingtown.gov/stormwater-management.html |
| Port Orford city, Oregon (us:place:4159250) | https://www.youtube.com/watch?v=QmO8D_UoyXo&list=PLN96qwhczpU8MSqFFhVQJlPeqJt_Jz5ZB&index=8 | found on https://portorford.org/city-council-meetings/; flagged (Jev moment 4: unsure): Jev could not tell whether the videos shown with it on the government's page are meetings |
| Trimble town, Tennessee (us:place:4775160) | http://www.youtube.com/watch?v=bVgFp4nZOBM | found on http://www.trimbletennessee.com/videos.htm |
| Oscoda Area Schools, Michigan (us:sd:2626970) | https://www.youtube.com/channel/UCJRt4QY19diWndoD2Yf4K9w?view_as=subscriber&fbclid=IwAR1VCcWaZpUGAi_Hllo7oh61HR3BqJC1Adbt8_4C2UaCEXWdlGevZCKMm2c | found on https://www.oscodaschools.org/live-feed/?page_no=8 |
| Natchitoches Parish School District, Louisiana (us:sd:2201140) | https://www.youtube.com/channel/UC9VL1zOvnRz7QJLmhxLvyrA | found on https://www.npsb.la/: "Visit us on Youtube" under heading "Stay Connected"; page "Natchitoches Parish School Board / Home"; nearby: "Natchitoches Parish School Board 310 Royal Street Natchitoches, Louisiana 71457 Call 318-352-2358 Fax 318-352-8138 Contact Us Privacy Policy Report Child Abuse Stay Connected" |
| East Washington borough, Pennsylvania (us:place:4222016) | https://www.youtube.com/watch?v=E63f5UPJaLo | found on https://eastwash.com/washington-school-district-city-wide-clap-parade-video/ |
| Dawson County School District, Georgia (us:sd:1301650) | https://www.youtube.com/channel/UCSGt08ap7ZNbNV6sHT7QtAg | found on https://www.dawsoncountyschools.org/: "Watch Us on Youtube" under heading "EVENTS"; page "Home - Dawson County Schools"; nearby: "Dawson County School District 28 Main Street, Dawsonville, GA 30534 706-265-3246" |
| Rockford Public Schools, Michigan (us:sd:2630030) | https://www.youtube.com/@RockfordPublicSchoolsMI | found on https://www.rockfordschools.org/our-district/board-of-education/: "Rockford Public Schools - YouTube" under heading "2025 Meetings"; page "Board of Education - Our District - Rockford Public Schools"; nearby: "Rockford Public Schools - YouTube" |
| Chase County Schools, Nebraska (us:sd:3100163) | https://www.youtube.com/channel/UCtG3OV7VgyiF5_6DXJr9FSA/featured | found on https://www.chasecountyschools.org/: "Visit us on Youtube" under heading "Stay Connected"; page "Home / Chase County Schools"; nearby: "Find Us Chase County Schools 520 East 9th Street Imperial, Nebraska 69033 ph: 308-882-4304 fax 308-882-5629 https://www.chasecountyschools.org/ BUS DISPATCH ph: 308-882-4214 Schools Chase County Schoo" |
| Shaker Regional School District, New Hampshire (us:sd:3306180) | https://www.youtube.com/channel/UCMXnQfgXwci6yLN2RN3HwLw | found on https://www.sau80.org/: "Youtube Channel" under heading "Shaker Regional School District“Engaging All Learners to Succeed in Their Ever-Changing World.”"; page "Home - Shaker Regional School District"; nearby: "Facebook Page Youtube Channel Send Email" |
| Ypsilanti Community Schools, Michigan (us:sd:2636630) | https://www.youtube.com/c/YpsilantiCommunitySchools?fbclid=IwAR0oXym6gRrcCn2Ank1GtoRG6Y9cNgxI6J-21q1Mjv_-AoUGLMb-bW8zjT0 | found on https://www.ycschools.us/board-of-education/board-meeting-archives/2023-meeting-packets-agendas-minutes/: "https://www.youtube.com/c/YpsilantiCommunitySchools" under heading "Board Meetings Streamed"; page "2026 Meeting Packets, Agendas, Minutes - Board Meetings - Board of Education - Ypsilanti Community…"; nearby: "Meetings will also be streamed through our YouTube Channel: https://www.youtube.com/c/YpsilantiCommunitySchools ." |
| Crawford Public Schools, Nebraska (us:sd:3105520) | https://www.youtube.com/@kerihoman6097 | found on https://www.cpsrams.org/: "YouTube(opens in new window/tab)"; page "Home - Crawford Public Schools"; nearby: "YouTube (opens in new window/tab)" |
| Assumption Parish School District, Louisiana (us:sd:2200120) | https://www.youtube.com/channel/UC0kvFJX6imuUlE87mx1yNHg/featured?disable_polymer=1 | found on https://assumptionschools.com/; page "Assumption Parish Schools" |
| Aurora Public Schools, Nebraska (us:sd:3103360) | https://www.youtube.com/@aurorahuskystrength | found on https://www.aurorahuskies.org/: "Husky Strength Youtube Channel" under heading "Aurora Public Schools - Home of the Huskies"; page "Aurora Public Schools"; nearby: "Husky Strength Youtube Channel" |
| Hartford city, Wisconsin (us:place:5533000) | https://www.youtube.com/user/hartfordcitytech | found on https://ci.hartford.wi.us/: "YouTube" under heading "Quick Links"; page "Hartford, WI / Official Website" |
| Western Wayne School District, Pennsylvania (us:sd:4226070) | https://www.youtube.com/channel/UCivdVZzPKkiu_JoQMETEByw/ | found on https://ww3.westernwayne.org/: "Subscribe" under heading "How can busy parents make a positive difference every day?"; page "Western Wayne School District / Lake Ariel, PA 18436"; nearby: "0 0 READING 01 READING 01 Western Wayne Streaming March 5, 2024 12:19 pm 0 0 READING 02 READING 02 Western Wayne Streaming March 5, 2024 12:19 pm 0 0 READING 03 READING 03 Western Wayne Streaming Marc" |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
