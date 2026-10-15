# Drip handoff 2026-10-14_waveb-govs_10aa44: 10 leads from rtr-findmeeting run waveB_govs

These come from the Find Meeting run `waveB_govs` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 10 |
|---|---|---|
| youtube | channel | 7 |
| youtube | single_video | 3 |

## Why each lead was suggested (10 of 10 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Blair township, Michigan (us:cousub:2605508880) | https://youtu.be/A5BbaVpWKV8 | found on https://www.blairtownshipmi.gov/about/minutes___agendas/board_of_trustees.php; flagged (Jev moment 4: no title evidence): the videos shown with it on the government's page had too few titles to judge |
| Northport village, Michigan (us:place:2658740) | https://www.youtube.com/@villageofnorthport172 | found on https://villageofnorthport.net/village-council/#Agenda |
| Ferrysburg city, Michigan (us:place:2627960) | https://www.youtube.com/channel/UCMqr_ibvxyZlVajOzl-Tr3g | found on https://ferrysburg.org/boards/city-council/ |
| Rapid River township, Michigan (us:cousub:2607967180) | https://www.youtube.com/channel/UCR81ERE6QdrIdK0i_e_41qw?view_as=subscriber | found on https://rapidrivertownship.org/ |
| Port Sheldon township, Michigan (us:cousub:2613965940) | https://www.youtube.com/watch?v=FNRhsito7nA | found on https://www.portsheldontwp.org/wp-json/wp/v2/posts?search=video&per_page=10&_fields=link,title,date,content |
| Pulaski Township, Michigan (us:cousub:2607566440) | https://www.youtube.com/watch?v=erk7NNMgdvU | found on https://pulaskitownship.org/ |
| Fairplain Township, Michigan (us:cousub:2611727180) | https://www.youtube.com/channel/UCSvKMbcuF6-xsMnVWs8OhYA | found on https://www.montcalm.us/286/Planning-Commission |
| Grand Rapids Public Schools, Michigan (us:sd:2616440) | https://www.youtube.com/channel/UCj6i3ufSOaunwbg1RxWcR8A | found on https://grps.org/departments/public-safety-security/ |
| Gratiot County, Michigan (us:county:26057) | https://www.youtube.com/channel/UC7HUh9ZNkTPINUTl_BZrT4A | found on https://gratiotmi.com/514/Live-Stream-65B-District-Court-Proceedin |
| Gratiot County, Michigan (us:county:26057) | https://www.youtube.com/channel/UC11nMyCVJKSiol9tS9Bbyfw | found on https://gratiotmi.com/515/Live-Stream-Judge-Bakkers-Proceedings |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
