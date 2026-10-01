# New drip leads: HighBond portals and blocked-site review (2026-09-30)

39 leads added to the rtr-business drip list (`research/youtube_channel_leads.csv`)
after the first handoff today. Work them in the drip lane like any other lead.

| Source (`source_wo`) | Count of 39 |
|---|---|
| `highbond-walk-2026-09-30`: one meeting video each, embedded on the government's own Diligent Community portal (older HighBond address) | 31 |
| `blocked-review-2026-09-30`: channel, Live tab or playlist Ryan found by hand on sites that block scripts | 8 |

- HighBond rows are `kind=single_video`: a specific meeting the portal embeds.
  The portal title was hand-read; the video was not opened.
- Blocked-review rows were found by Ryan on the government's own site.
- 13 of the HighBond governments are new ids, added to `governments.csv` in
  rtr-deeplink PR #1665. If that PR isn't merged yet when you reach them, the
  Archive will reject the id; hold those until it is.
- One row (Tarrant County, TX) notes `meeting body: Tarrant Appraisal
  District`: the meeting belongs to that body, filed under the county.

If a lead is wrong, record it in `drip_leads_out.csv` here and push; don't merge.
