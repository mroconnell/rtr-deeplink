# Drip handoff 2026-10-05: 1131 leads from rtr-findmeeting run districts_combined

These come from the Find Meeting run `districts_combined` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 1131 |
|---|---|---|
| youtube | channel | 773 |
| youtube | playlist | 38 |
| youtube | single_video | 320 |

## Low-confidence rows (7): please verify identity first

The handle names another body. `leads.csv` has no note column, so the doubt is written here (and in the drip-list note).

| Government | Address | Note |
|---|---|---|
| Clayton School District, WI (us:sd:5502580) | https://www.youtube.com/@GlenwoodCitySchoolDistrict/streams | rtr-findmeeting run districts_combined (2026-10-04): 2 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; low confidence: handle names Glenwood City School District, Wisconsin; suggested for Clayton School District, WI; address also on the list under Glenwood City School District, Wisconsin (us:sd:5505520); drip judge please verify identity |
| Fredon Township School District, NJ (us:sd:3405550) | https://youtube.com/@kittatinnyregionalhighscho4966?si=AHi5xLLDZFpZLzjm | rtr-findmeeting run districts_combined (2026-10-05): 1 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; low confidence: handle names Kittatinny Regional School District, New Jersey; suggested for Fredon Township School District, NJ; address also on the list under Kittatinny Regional School District, New Jersey (us:sd:3408060); drip judge please verify identity |
| Viborg Hurley School District 60-6, SD (us:sd:4674520) | https://www.youtube.com/channel/UCVc3920dOz8VU0qfX0IH_Dw/live | rtr-findmeeting run districts_combined (2026-10-05): 1 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; hand decision: districts routing 2026-10-05, hand decision (low confidence): the city, town or county of the same name has it on the list; one channel id, cannot read whose (as step 2: a body of the same place); also on the list under ,  (us:place:4667020) |
| Eureka School District 44-1, SD (us:sd:4622560) | https://www.youtube.com/@redfieldpheasantslive5652 | rtr-findmeeting run districts_combined (2026-10-05): 2 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; low confidence: handle names Redfield School District 56-4, South Dakota; suggested for Eureka School District 44-1, SD; address also on the list under Redfield School District 56-4, South Dakota (us:sd:4660450); drip judge please verify identity |
| Interlaken Borough School District, NJ (us:sd:3407650) | https://youtu.be/28qi2WIbM0s | rtr-findmeeting run districts_combined (2026-10-05): also routed another way; 1 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; hand decision: districts routing 2026-10-05, hand decision (low confidence): the city, town or county of the same name has it on the list; one channel id, cannot read whose (as step 2: a body of the same place); also on the list under ,  (us:place:3434200) |
| Twiggs County School District, GA (us:sd:1305220) | https://www.youtube.com/channel/UCqwu9YEYeDpjFAWJzlgdj1w | rtr-findmeeting run districts_combined (2026-10-05): also routed another way; 1 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; hand decision: districts routing 2026-10-05, hand decision (low confidence): the city, town or county of the same name has it on the list; one channel id, cannot read whose (as step 2: a body of the same place); also on the list under Twiggs County, GA (us:county:13289) |
| Charles City County Public Schools, VA (us:sd:5100720) | https://www.youtube.com/@charlescitycountyvacommuni9488/videos | rtr-findmeeting run districts_combined (2026-10-05): its meeting source has no video; 1 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; low confidence: handle names Charles City County, VA; suggested for Charles City County Public Schools, VA; address also on the list under Charles City County, VA (us:county:51036); drip judge please verify identity |

## The pass

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
