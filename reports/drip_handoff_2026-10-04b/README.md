# Drip handoff 2026-10-04b: 3 leads re-keyed to the right government

Ryan asked in chat (2026-10-04) that six drip rows filed under the wrong county be filed under the right government.
The step 2 owner check (rtr-findmeeting `data/overnight_2026-10-04/audit_step2_owner/`) had flagged them. No YouTube or web request was made.

These addresses were first handed off under a county in `reports/drip_handoff_2026-10-04/leads.csv` (#1734). Each one is a lead for a different government.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs. Count of 3, all youtube channel.

| Address | Right government | gov_id | Was filed under |
|---|---|---|---|
| https://www.youtube.com/@shelbyalschools | Shelby County School District, AL | us:sd:0103030 | Shelby County, AL (us:county:01117) |
| https://www.youtube.com/@henrycountyschooldistrict | Henry County School District, AL | us:sd:0101740 | Henry County, AL (us:county:01067) |
| https://www.youtube.com/@GovBraun | State of Indiana | us:state:18 | Wabash County, IN (us:county:18169) and Crawford County, IN (us:county:18025) |

`@GovBraun` is the Indiana governor's channel. It is low confidence: drip judge please verify identity.

The two school district addresses were already on the rtr-business drip list under the school districts (since 2026-09-26) but were in no handoff folder.
The State of Indiana row was added to the drip list in this change.

## Not in the file

| Item | Why |
|---|---|
| Atoka city, OK (us:place:4003300), https://www.youtube.com/@CityofAtoka/streams | Already handed off under the city in `reports/drip_handoff_2026-10-03f`. It is the correct government for the Atoka County row below. |
| Huntingdon County, PA video https://www.youtube.com/shorts/FfUDzl6W9fE | Found on the Pennsylvania State Association of Township Supervisors site (psats.org). That is a state association, not a government. No government in the list owns it. Not filed. |

## Old wrong-government addresses the drip should reject

Please reject these four lines from `reports/drip_handoff_2026-10-04/leads.csv`. They were removed from the rtr-business drip list (commit 15d6c4f4).

| Address | Wrong government (gov_id) | Right government |
|---|---|---|
| https://www.youtube.com/@shelbyalschools | Shelby County, AL (us:county:01117) | Shelby County School District (us:sd:0103030) |
| https://www.youtube.com/@henrycountyschooldistrict | Henry County, AL (us:county:01067) | Henry County School District (us:sd:0101740) |
| https://www.youtube.com/@CityofAtoka/streams | Atoka County, OK (us:county:40005) | Atoka city (us:place:4003300) |
| https://www.youtube.com/shorts/FfUDzl6W9fE | Huntingdon County, PA (us:county:42061) | none (not filed) |

Still in `reports/drip_handoff_2026-10-04/leads.csv` and on the drip list: `@GovBraun` under Wabash County IN and Crawford County IN. Ryan has not decided to remove them.

## The pass

1. Check that the channel is the government's own public body.
2. Check for meeting videos.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
