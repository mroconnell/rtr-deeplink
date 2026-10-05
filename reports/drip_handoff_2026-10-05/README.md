# Drip handoff 2026-10-05: 2631 leads from rtr-findmeeting run districts_combined

These come from the Find Meeting run `districts_combined` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

This folder holds two parts of the same run, merged into one `leads.csv`:

| Part | Rows in `leads.csv` | Also |
|---|---|---|
| Part 1 (PR 1745) | 1500 | plus 1 re-key |
| Part 2 (PR 1746) | 1131 | none |
| Total | 2631 | no duplicate rows (checked by gov_id and address) |

## The file, part 1

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 1500 (part 1) |
|---|---|---|
| youtube | channel | 1203 |
| youtube | playlist | 38 |
| youtube | single_video | 259 |

## The file, part 2

| Lane | Kind | Count of 1131 (part 2) |
|---|---|---|
| youtube | channel | 773 |
| youtube | playlist | 38 |
| youtube | single_video | 320 |

## Low-confidence rows, part 1 (5): please verify identity first

The handle names another body. `leads.csv` has no note column, so the doubt is written here (and in the drip-list note).

| Government | Address | Note |
|---|---|---|
| Chelsea School District, MA (us:sd:2503540) | https://www.youtube.com/channel/UC795R5jmLF9kwv7Ot6kTREw/videos | rtr-findmeeting run districts_combined (2026-10-04): also routed another way; 2 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; hand decision: districts routing 2026-10-05, hand decision (low confidence): the city, town or county of the same name has it on the list; one channel id, cannot read whose (as step 2: a body of the same place); also on the list under Chelsea city, Massachusetts (us:place:2513205) |
| Meriden School District, CT (us:sd:0902400) | https://www.youtube.com/embed/2K6194mhOds | rtr-findmeeting run districts_combined (2026-10-04): also routed another way; 1 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; hand decision: districts routing 2026-10-05, hand decision (low confidence): the city, town or county of the same name has it on the list; one channel id, cannot read whose (as step 2: a body of the same place); also on the list under Meriden city, Connecticut (us:place:0946450) |
| Bethel School District, CT (us:sd:0900270) | https://www.youtube.com/@Bethel-ctGov | rtr-findmeeting run districts_combined (2026-10-04): its meeting source has no video; 2 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; low confidence: handle names Bethel town, CT; suggested for Bethel School District, CT; address also on the list under Bethel town, CT (us:cousub:0919004720); drip judge please verify identity |
| Bethel School District, CT (us:sd:0900270) | https://www.youtube.com/channel/UCnm2GREVYVezvuoayA-gtZQ | rtr-findmeeting run districts_combined (2026-10-04): also routed another way; 2 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; hand decision: districts routing 2026-10-05, hand decision (low confidence): the city, town or county of the same name has it on the list; one channel id, cannot read whose (as step 2: a body of the same place); also on the list under Bethel town, Connecticut (us:cousub:0919004720) |
| Union County School District, FL (us:sd:1201890) | https://www.youtube.com/channel/UCf4SsugKwHEOKyFHzooIonQ | rtr-findmeeting run districts_combined (2026-10-04): 3 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; hand decision: districts routing 2026-10-05, hand decision (low confidence): the city, town or county of the same name has it on the list; one channel id, cannot read whose (as step 2: a body of the same place); also on the list under ,  (us:county:12125) |

## Low-confidence rows, part 2 (7): please verify identity first

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

Verify skeptically: add only if the channel or video shows clear meetings of this government's board or school district body.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
