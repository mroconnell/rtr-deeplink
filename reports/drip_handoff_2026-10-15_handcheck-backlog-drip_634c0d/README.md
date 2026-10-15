# Drip handoff 2026-10-15_handcheck-backlog-drip_634c0d: 14 leads from rtr-findmeeting run handcheck_backlog_drip

These come from the Find Meeting run `handcheck_backlog_drip` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 14 |
|---|---|---|
| vimeo | vimeo | 2 |
| youtube | channel | 3 |
| youtube | playlist | 3 |
| youtube | single_video | 6 |

## Why each lead was suggested (14 of 14 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Franklin Community School Corporation, Indiana (us:sd:1803690) | https://www.youtube.com/@fcsschoolboard6926/videos | Ryan's Hand Checks answer, 2026-10-15: Hand Checks card accepted (LIKELY YES: the handle names the board) |
| Springfield School District, Massachusetts (us:sd:2511130) | https://www.youtube.com/@schoolcommitteeSPS/streams | Ryan's Hand Checks answer, 2026-10-15: Hand Checks card accepted (LIKELY YES: the handle names the school committee) |
| Portland School District 1J, Oregon (us:sd:4110040) | https://www.youtube.com/@ppsboardofeducation | Ryan's Hand Checks answer, 2026-10-15: Hand Checks card accepted (LIKELY YES: the handle names the board) |
| Missoula Elementary School District, Montana (us:sd:3018570) | https://www.youtube.com/playlist?list=PLw502-5ltXpzIg6i6p10PBdbcIp1fCyEr | Ryan's Hand Checks answer, 2026-10-15: Ryan's Hand Checks answer: this playlist is good, the rest of the channel is mostly off mission |
| Oswego City School District, New York (us:sd:3622050) | https://www.youtube.com/playlist?list=PLz0yeHSffI23HGv4yl5l2GtgdXDSQgNBR | Ryan's Hand Checks answer, 2026-10-15: Ryan's Hand Checks answer: this playlist is meetings, the rest of the channel is mostly off mission |
| Stephenville Independent School District, Texas (us:sd:4841520) | https://www.youtube.com/playlist?list=PL9X3sai5SSq8aWV2tznWX95i_L74YFwP- | Ryan's Hand Checks answer, 2026-10-15: Ryan's Hand Checks answer: playlists with meetings |
| Indian River County School District, Florida (us:sd:1200930) | https://www.youtube.com/watch?v=wSAeJ3IIusc | Ryan's Hand Checks answer, 2026-10-15: Ryan's Hand Checks answer: not the shown video, but this one is a meeting |
| York City School District, Pennsylvania (us:sd:4226820) | https://www.youtube.com/watch?v=HMFsGNMEn9A | Ryan's Hand Checks answer, 2026-10-15: Ryan's Hand Checks answer: yes, a meeting of this government |
| Cherokee County School District, South Carolina (us:sd:4501500) | https://www.youtube.com/watch?v=2qxEfqM9jZk | Ryan's Hand Checks answer, 2026-10-15: Ryan's Hand Checks answer: not the shown video, but this one is a meeting |
| Needville Independent School District, Texas (us:sd:4832310) | https://www.youtube.com/watch?v=neRxq6S2qHA | Ryan's Hand Checks answer, 2026-10-15: Ryan's Hand Checks answer: yes, a meeting of this government |
| Les Îles-de-la-Madeleine, Quebec (ca:csd:2401023) | https://www.youtube.com/watch?v=mSPopK9EtKs | Ryan's Hand Checks answer, 2026-10-15: Ryan's Hand Checks answer: the embedded video is off mission, use this instead |
| Val-Brillant, Quebec (ca:csd:2407080) | https://www.youtube.com/watch?v=6xTLIFQZqSM | Ryan's Hand Checks answer, 2026-10-15: Ryan's Hand Checks answer: right town; this is an example video |
| La Malbaie, Quebec (ca:csd:2415013) | https://player.vimeo.com/video/896612143 | Ryan's Hand Checks answer, 2026-10-15: Ryan's Hand Checks answer: it is a council meeting, Vimeo goes to the tier 2 drip feed |
| Senneville, Quebec (ca:csd:2466127) | https://vimeo.com/1229614697 | Ryan's Hand Checks answer, 2026-10-15: Hand Checks card accepted: a council meeting recording (Vimeo goes to the drip lane) |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
