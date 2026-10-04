# Drip handoff, part e: 28 YouTube leads from Ryan's hand review (2026-10-03)

These come from Ryan's review of the chunks 2 and 3 routing (part d, #1716). No YouTube request was made.
The same rows were added to the rtr-business drip list (`research/youtube_channel_leads.csv`).

## The file

`leads.csv`, one row per address. Same columns as part d. `meeting_source_has_no_video` is blank: it was not checked.

| Where the rows come from | Verified by Ryan | Count of 28 |
|---|---|---|
| Neighbouring bodies that share one address (Ryan: fine to give each body the row) | no | 11 |
| Valley View Village council channel, for both Valleyview and Valley View villages OH | yes | 2 |
| Tampa FL: City Council playlist and the meeting livestreams channel | yes | 2 |
| Low confidence: the handle names another body (see the table below) | no | 13 |

The 11 shared addresses: one Leelanau County MI channel (Bingham, Elmwood, Kasson, Leland, Solon townships), Buchanan
Township MI, French township MN, Park Township MI (single video), Lakeville MA (LakeCAM TV), Sunderland MA (Franklin
County Access TV), Northfield MA (Bernardston-Northfield community channel). The neighbouring body already had its own row.

Tampa already has Archive pages. These two rows add depth: City Council meetings from the playlist and the streams.

## Low-confidence rows (13): please verify identity first

The routing step dropped these because the handle names another body. Ryan asked to pass them anyway, since this pass
checks every address. `leads.csv` has no note column, so the doubt is written here (and in the rtr-business drip-list note,
source `findmeeting_low_confidence_2026-10-03`).

| Suggested government | Address | The handle names | Address also on the list under |
|---|---|---|---|
| Dale town, Indiana | https://youtube.com/@GovBraun | the Governor of Indiana | Wabash County IN and Porter town IN (both rows removed 2026-10-03) |
| Georgetown town, Indiana | https://www.youtube.com/@GovBraun | the Governor of Indiana | Wabash County IN and Porter town IN (both rows removed 2026-10-03) |
| Beaumont town, Mississippi | https://www.youtube.com/@MississippiLegislature/streams | the Mississippi Legislature | State of Mississippi (us:state:28) |
| Houston city, Mississippi | https://www.youtube.com/user/TheMSArtsComm | the Mississippi Arts Commission | Monticello town MS (row removed 2026-10-03) |
| Glen Dale city, West Virginia | https://www.youtube.com/c/WestVirginiaHouseofDelegates | the West Virginia House of Delegates | Benwood city WV (row removed 2026-10-03) |
| Mill Creek borough, Pennsylvania | https://www.youtube.com/@millcreektownshippa | Millcreek township PA | Millcreek township PA (us:cousub:4204949548) |
| Birmingham township, Pennsylvania | https://www.youtube.com/@GovernorShapiro | the Governor of Pennsylvania | Duryea borough PA (row removed 2026-10-03) |
| Waverly Township, Michigan | https://www.youtube.com/@vanburencountymi2620 | Van Buren County MI | Bangor Township MI (row removed 2026-10-03) |
| Wells Township, Michigan | https://www.youtube.com/@deltacountymi/streams | Delta County MI | Masonville Township MI (row removed 2026-10-03) |
| Loxley city, Alabama | http://www.youtube.com/@bcbeboardvideos9344 | the Baldwin County Board of Education | Baldwin County School District AL (us:sd:0100270) |
| Pomfret town, Vermont | https://www.youtube.com/c/WoodstockCommunityTelevision/search?query=WCSU | Woodstock Community Television, searched for WCSU (a school supervisory union) | Mountain Views Unified Union School District VT (us:sd:5000450) |
| Milford borough, New Jersey | https://www.youtube.com/@DelValTVMedia | Delaware Valley regional schools | Frenchtown Borough School District NJ (us:sd:3405700) |
| Milford borough, New Jersey | https://www.youtube.com/@delawarevalleyregionalhs | Delaware Valley Regional High School | Frenchtown Borough School District NJ (us:sd:3405700) |

If the channel belongs to the other body (a governor, a legislature, a county, a school district), record
"not this government's channel" for the suggested government.

## Rows sent earlier that should now be rejected

Ryan removed these from the rtr-business drip list on 2026-10-03. They were already sent, so please judge them as
"not this government's channel" if they come up.

| Address | Sent in | Why removed | Count |
|---|---|---|---|
| https://www.youtube.com/channel/UCW84nM-EAuCsIO7jHRtnOwg (59 West Virginia towns plus Madison city WV) | part d (`drip_handoff_2026-10-03d`) | Probably the State of West Virginia's channel (found on local.wv.gov), not the towns' | 60 |
| https://www.youtube.com/embed/21oUVHhbhws?feature=oembed (Newtown village OH) | `drip_handoff_2026-10-03` | A template embed seen on sites in four states | 1 |
| https://www.youtube.com/@vanburencountymi2620 (Bangor Township MI) | `drip_handoff_2026-10-03` | Van Buren County MI's channel, not the township's | 1 |

## The pass

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
