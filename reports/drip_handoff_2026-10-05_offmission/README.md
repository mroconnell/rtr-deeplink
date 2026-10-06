# Drip handoff 2026-10-05 off-mission: 10 YouTube leads

The owner audit found Archive pages that are not meetings (concerts, parades, promos). Ryan approved deleting them. Some of those governments then have no meeting in the Archive, and their only lead is a YouTube channel. Two more leads came from Ryan's hand-checks the same day.
No YouTube or other web request was made for this handoff. Every address comes from the government's own site, the deleted page's channel, or Ryan.

## The file

`leads.csv`, one row per address. Count of 10. All 10 are on the rtr-business drip list (`research/youtube_channel_leads.csv`).

| Government | gov_id | Lead | Where it came from |
|---|---|---|---|
| North Utica village, IL | us:place:1754222 | @villageofnorthuticail7771 | the off-mission page's channel |
| Newnan city, GA | us:place:1355020 | @cityofnewnan | the off-mission page's channel; may be the same channel as an existing UC... row |
| Rooks County, KS | us:county:20163 | @RooksCounty | the off-mission page's channel |
| Spruce Pine town, NC | us:place:3764260 | @townofsprucepinencgovernment/streams | linked from sprucepine-nc.gov |
| Garrett Park town, MD | us:place:2431525 | @MontgomeryMunicipalCable | shared station for many Montgomery County bodies |
| Beach Haven borough, NJ | us:place:3403940 | user/OfficialBeachHaven | linked from beachhaven-nj.gov (weak) |
| Athens County Board of Developmental Disabilities, OH | rtr:us:oh:athens-county-board-of-developmental-disabilities (new, rtr-deeplink PR 1784) | @acbdd | the off-mission page's channel |
| West Hartford School District, CT | us:sd:0904920 | one video, 7V9HkrbyC54 | Ryan: the WHCI channel (@whci) carries some school district meetings; this is one |
| Portland Community College, OR | rtr:us:or:portland-community-college | one video, ZjeAsag9u_U | Ryan (2026-10-06): a Board of Directors meeting; hub https://www.pcc.edu/board/meetings/ links the YouTube recordings. Highest priority. |
| Falmouth town, ME | us:cousub:2300524495 | user/FalmouthMaine | town site; the town also has a tier-3 queue line, so lowest priority |

## Things to check

- **Shared channels:** @MontgomeryMunicipalCable and @whci carry several governments. Pin single videos only, never the whole channel. For WHCI, Town Council videos belong to West Hartford town (already covered).
- **Newnan:** if @cityofnewnan is the same channel as an existing row, record it once.
- **Beach Haven:** @VisitBeachHaven is tourism, not the borough. Check that OfficialBeachHaven carries council meetings.
- **Athens County Board of DD:** its government row lands with rtr-deeplink PR 1784. Pin to that id.

## The pass

1. Check that the channel is the government's own public body.
2. Check for meeting videos.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
