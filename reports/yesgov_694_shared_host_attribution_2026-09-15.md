# YesGov 694 shared-host attribution handoff — 2026-09-15

This scoped code change pins government identity only where first-party or observed meeting evidence supports a specific video, show, or playlist. Unmatched items on LMC Media and Merrimack TV remain unattributed, as do unrelated Vimeo and TelVue media.

| Government | Selected source | Outcome |
|---|---|---|
| Town of Mamaroneck, NY `us:cousub:3611944842` | LMC Swagit video 399987 (backup 396842) | Exact per-video pins; 399987 accepted for tier-3 queue, held until pin deploy; backup unqueued |
| Village of Mamaroneck, NY `us:place:3644831` | LMC Swagit video 376682 (long alternative 400555) | Exact per-video pins; shorter 376682 accepted for tier-3 queue, held until pin deploy; 400555 unqueued |
| Sycamore township, OH `us:cousub:3906175973` | Vimeo video 1202127455 on shared ESP account | Exact video pin; Archive page 10206 ingested with 1,047 sourced segments and verified gov ID |
| Halfmoon township, PA `us:cousub:4202731992` | C-NET TelVue playlist 4815, media 1006347 | Exact playlist pin; Archive page 10207 ingested with 1,008 sourced segments and verified gov ID; Bellefonte playlist 4806 preserved |
| Merrimack town, NH `us:cousub:3301147540` | Cablecast show 8878 (show 8909 is an alternate) | Existing Archive page 6590 re-keyed from unknown to the town, retaining 748 transcript segments; wrong Merrimack County video-URL pin replaced with exact show pins; 8909 unqueued as duplicate breadth |

Source handoff evidence is in `/Users/mroconnell/Documents/Codex/2026-09-15/cisa-dotgov-diff/outputs/yesgov_694_enumeration_2026-09-15/`, including `lmc_shared_host_pin_handoff.csv`, `halfmoon_telvue_pin_handoff.csv`, `merrimack_cablecast_pin_handoff.csv`, guarded resolver/probe summaries, and first-party source notes. The exact selected URLs were absent from the live Archive before ingest/queue. The two tier-1 ingests ran with a no-YouTube/no-browser-media guard and explicit government IDs; both readbacks confirmed the intended IDs, dates, video metadata, and sourced transcript counts.

## Rejected generated rule

The documented Archive identity endpoint's Merrimack page-6590 dry run returned a proposed `tenant_override_rules` row with `tenant_host=reflect-townofmerrimack.cablecast.tv`, **blank `match`**, `gov_id=us:cousub:3301147540`, `strength=authoritative`. Its apply response wrote one such draft to the server's staging path `/tmp/tenant_overrides_pending.csv`. That draft is **rejected**: the vault also carries School Board and other programs, so a blank match would claim unrelated media. The staging file is server-local, ephemeral, and was not read, copied, or imported into this repository. The standing handoff rule in `docs/handoffs/2026-09-14_conductor_and_breadth_handoff.md` explicitly says, “Never apply `/tmp/tenant_overrides_pending.csv`.” The committed registry instead classifies this host as shared and pins only `/internetchannel/show/8878` and `/internetchannel/show/8909`.

The production resolver version observed during this pass was `5da09b574fd6a5acdc485bdddb5991cb32b1f550`, before this shared-host change. The two accepted LMC queue candidates are preserved in `yesgov_694_pending_queue_2026-09-15.csv`, outside the active `scripts/tier3_auto_transcription_queue.txt`. Add the CSV's **bare Swagit `queue_line`** values to the active queue only after the app change merges and a deployment with these exact pins is verified. The LMC first-party pages are evidence URLs, not the queue line's second tab-field: the feeder replaces `ResolvedMeeting.source_url` with that field before its owner check, which would bypass the exact Swagit video pin. The existing page-6590 manual override is already live and protected against re-ingest overwrite.
