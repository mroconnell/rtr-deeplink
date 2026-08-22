# Repetition-run fixtures (WO-36)

Real, fetched data -- not hand-written. Every file here is a verbatim slice
of a live Archive transcript export, pulled from
`https://redtaperecordings.com/m/<slug>/transcript.srt` on 2026-08-21 while
fixing `detect_hallucination_warnings()`'s repetition-dilution bug. Each file
is the meeting's longest contiguous near-duplicate run plus 8 real cues of
context on either side; cue text and timings are untouched, only the cue
*numbers* were renumbered from 1 by the slicing.

They exist because the bug was a *scoring* bug -- a real local loop diluted
against total meeting length -- so a regression test needs a real local loop
sitting inside real surrounding speech, which no hand-written payload can
honestly stand in for.

`loop_*.srt` -- the six live, previously-unflagged cases named in
`BACKLOG_DONE.md`'s WO-36 entry. All six must be flagged.

| file | slug | run | of total cues | old ratio |
| --- | --- | --- | --- | --- |
| `loop_hermosa_beach_ca.srt` | `hermosa-beach-ca-2026-02-03-city-council` | 176 | 3764 | 0.047 |
| `loop_moraine_city_oh.srt` | `meeting-d09fc0` (version 1175, the original `cy` transcript) | 93 | 241 | 0.386 |
| `loop_north_kingstown_ri.srt` | `meeting-89d6b1` | 80 | 210 | 0.381 |
| `loop_cumberland_county_nj.srt` | `cumberland-county-nj-2020-01-28-board-of-county-commissioners-regular-board-meet` | 41 | 1291 | 0.032 |
| `loop_haines_city_fl.srt` | `meeting-16157c` | 6 | 525 | 0.011 |
| `loop_lincoln_city_or.srt` | `meeting-00bbd1` (version 1169, the original `cy` transcript) | 8 | 637 | 0.013 |

Moraine City and Lincoln City have since been re-transcribed; their current
default versions no longer contain the loop, which is why these two are
pinned to the original `?version=` exports rather than the live default.

`stutter_*.srt` / `rollcall_*.srt` -- the must-not-flag set, all real speech
from real meetings. The stutters are genuine words really said and then
duplicated by the decoder, with real pauses left between the cues (coverage
0.51 / 0.23 / 0.08); the roll calls are real "aye."/"yes." bursts.

`recess_halifax_ns.srt` -- kept deliberately as a *correction*.
`BACKLOG.md` listed Halifax's 28 repeated "thank you"s as a false positive
("a chair thanking distinct public commenters over a real 13-minute comment
period"). The real export says otherwise: they are 28 consecutive cues with
no other content between them, at an exact 30.000-second cadence, starting
immediately after the chair says "we'll resume at 6 p.m. for the appeal
here... enjoy your meal". It is a dinner recess, and this is a real
hallucination loop. See the test that asserts exactly that.
