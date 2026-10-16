# Drip handoff 2026-10-16_stray-leads-sliceb_8f12e9: 4 leads from rtr-findmeeting run stray_leads_sliceB

These come from the Find Meeting run `stray_leads_sliceB` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 4 |
|---|---|---|
| youtube | channel | 4 |

## Why each lead was suggested (4 of 4 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Beaufort city, South Carolina (us:place:4504690) | https://www.youtube.com/channel/UCUmEP7F7KSWK5jhw76pZM_g | titles read 2026-10-16: City of Beaufort Government channel: Planning Commission, City Work Session, City Regular Meeting, Waterfront Advisory and Historic District committee meetings (newest Aug 17 2026) |
| Shelter Island town, New York (us:cousub:3610366839) | https://www.youtube.com/channel/UCgUMWZ3obKJWAlDnhnxQAkw | titles read 2026-10-16: Town of Shelter Island channel: Planning Board, Zoning Board of Appeals and advisory board meetings through 10.13.26 |
| Hot Springs town, North Carolina (us:place:3732840) | https://www.youtube.com/channel/UCdW5CMas2mShNMMnNoWRAbg | titles read 2026-10-16: Town of Hot Springs Board of Aldermen meetings (Aug 10, Jul 13, Jun 8, Apr 13 2026) |
| Ulen town, Indiana (us:place:1877066) | https://www.youtube.com/channel/UC0kzqs6alFDrJgi8XDWWqig | titles read 2026-10-16: Ulen Town Council meetings monthly through September 2026 |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
