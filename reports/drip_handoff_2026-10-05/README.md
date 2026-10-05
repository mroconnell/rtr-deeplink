# Drip handoff 2026-10-05: 1500 leads from rtr-findmeeting run districts_combined

These come from the Find Meeting run `districts_combined` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 1500 |
|---|---|---|
| youtube | channel | 1203 |
| youtube | playlist | 38 |
| youtube | single_video | 259 |

## Low-confidence rows (5): please verify identity first

The handle names another body. `leads.csv` has no note column, so the doubt is written here (and in the drip-list note).

| Government | Address | Note |
|---|---|---|
| Chelsea School District, MA (us:sd:2503540) | https://www.youtube.com/channel/UC795R5jmLF9kwv7Ot6kTREw/videos | rtr-findmeeting run districts_combined (2026-10-04): also routed another way; 2 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; hand decision: districts routing 2026-10-05, hand decision (low confidence): the city, town or county of the same name has it on the list; one channel id, cannot read whose (as step 2: a body of the same place); also on the list under Chelsea city, Massachusetts (us:place:2513205) |
| Meriden School District, CT (us:sd:0902400) | https://www.youtube.com/embed/2K6194mhOds | rtr-findmeeting run districts_combined (2026-10-04): also routed another way; 1 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; hand decision: districts routing 2026-10-05, hand decision (low confidence): the city, town or county of the same name has it on the list; one channel id, cannot read whose (as step 2: a body of the same place); also on the list under Meriden city, Connecticut (us:place:0946450) |
| Bethel School District, CT (us:sd:0900270) | https://www.youtube.com/@Bethel-ctGov | rtr-findmeeting run districts_combined (2026-10-04): its meeting source has no video; 2 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; low confidence: handle names Bethel town, CT; suggested for Bethel School District, CT; address also on the list under Bethel town, CT (us:cousub:0919004720); drip judge please verify identity |
| Bethel School District, CT (us:sd:0900270) | https://www.youtube.com/channel/UCnm2GREVYVezvuoayA-gtZQ | rtr-findmeeting run districts_combined (2026-10-04): also routed another way; 2 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; hand decision: districts routing 2026-10-05, hand decision (low confidence): the city, town or county of the same name has it on the list; one channel id, cannot read whose (as step 2: a body of the same place); also on the list under Bethel town, Connecticut (us:cousub:0919004720) |
| Union County School District, FL (us:sd:1201890) | https://www.youtube.com/channel/UCf4SsugKwHEOKyFHzooIonQ | rtr-findmeeting run districts_combined (2026-10-04): 3 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; hand decision: districts routing 2026-10-05, hand decision (low confidence): the city, town or county of the same name has it on the list; one channel id, cannot read whose (as step 2: a body of the same place); also on the list under ,  (us:county:12125) |

## The pass

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
