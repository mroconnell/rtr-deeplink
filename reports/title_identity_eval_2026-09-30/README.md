# Title identity rules: measured results

All numbers come from `scripts/eval_title_identity.py`. No network was used.

## 1. Archive pages (every one is a real meeting)

Question: for a US Archive page, does the classifier say it is a meeting, and does it return the page's own government?
The second run gives the classifier the page's state only. The third run also tells it the page's own government is one the station carries (an upper bound, because a real station lists other governments too).

| Result | State only | State and known government |
|---|---|---|
| US pages scored | 8920 | 8920 |
| Says meeting | 8493 (95.2%) | 8493 (95.2%) |
| Says meeting at high confidence | 1716 (19.2%) | 2020 (22.6%) |
| Says not a meeting (wrong) | 41 (0.5%) | 41 (0.5%) |
| Says not a meeting at high confidence (wrong) | 41 (0.5%) | 41 (0.5%) |
| Cannot tell (blank) | 386 (4.3%) | 386 (4.3%) |
| Of the blanks: no body, meeting or non-meeting word at all | 383 (4.3%) | 383 (4.3%) |
| Returns a government | 2308 (25.9%) | 7224 (81.0%) |
| Government matches the page | 2242 (25.1%) | 7160 (80.3%) |
| Government differs from the page | 66 (0.7%) | 64 (0.7%) |
| No government returned | 6612 (74.1%) | 1696 (19.0%) |
| Settled: meeting, high confidence, right government | 1679 (18.8%) | 1983 (22.2%) |

Not in the table above: 936 minted rtr: special-district pages. Says meeting: 855. (An rtr: page is filed under its local government by Ryan's rule, so its id is not compared.)
Not in the table above: 994 non-US pages. Says meeting: 948. (An rtr: page is filed under its local government by Ryan's rule, so its id is not compared.)

Government precision at high identity confidence (state only): 97.7% (1891 of 1935).
Government precision at medium identity confidence (state only): 94.2% (340 of 361).
Government precision at low identity confidence (state only): 91.7% (11 of 12).

Precision of the government when one is returned (state only): 97.1% (2242 of 2308).

## 2. Census hand-read (2026-09-30, both runs)

Question: on the proposals for governments with no Archive page, how does the classifier compare with what a person decided?
Held items are left out: a person did not decide them.

| Hand-read label | Count |
|---|---|
| accept | 304 |
| reject_non_meeting | 15 |
| reject_wrong_gov | 12 |
| held | 17 |

| Hand-read label | Classifier result | Count |
|---|---|---|
| reject_non_meeting | caught | 13 |
| reject_non_meeting | missed (says meeting) | 1 |
| reject_non_meeting | unsettled (goes to a model) | 1 |
| reject_wrong_gov | caught (no government, or a different one) | 12 |
| accept | agrees (meeting, same government) | 212 |
| accept | contradicts (different government) | 2 |
| accept | unsettled (goes to a model) | 90 |

## 3. Meeting yes/no: precision and recall

Actual meetings here are the Archive pages plus the accepted proposals. Actual non-meetings are the hand-rejected non-meeting proposals, so that side is a small sample.

| Measure | Count | Share |
|---|---|---|
| Actual meetings scored | 9224 | |
| Said meeting | 8792 | 95.3% recall |
| Said not a meeting (wrong) | 41 | 0.4% |
| Cannot tell | 391 | 4.2% |
| Actual non-meetings scored | 15 | |
| Said not a meeting | 13 | 86.7% recall |
| Said meeting (wrong) | 1 | 6.7% |
| Cannot tell | 1 | 6.7% |
| Precision of yes | 8792 of 8793 | 100.0% |

## 4. What a model no longer has to read (all census list titles)

Question: of 27814 playlist, gallery and channel titles from both census runs, how many does the classifier settle at high confidence?
The second column counts titles the census script also flagged off-mission (a script guess, not a hand-read label).

| Result | Count of titles | Of which census script said off-mission |
|---|---|---|
| Settled: not a meeting (high) | 3082 (11.1%) | 2965 |
| Settled: meeting and government (high) | 1135 (4.1%) | 14 |
| Meeting, not high confidence | 5098 (18.3%) | 145 |
| Cannot tell: no body, meeting or non-meeting word at all | 18494 (66.5%) | 16060 |
| Cannot tell: any other reason | 5 (0.0%) | 4 |

Share settled completely (not a meeting, or meeting with a government) at high confidence: 4217 of 27814 (15.2%).
Where both the census script and the classifier name a government: 4574 titles, same government in 4002 (87.5%). The census script is itself a guess, not a label.

Two narrower questions, counted on the same titles:

| Question | Count of titles | Share |
|---|---|---|
| Meeting yes/no settled at high confidence | 6323 | 22.7% |
| Government named at high confidence | 1758 | 6.3% of all titles; 28.2% of the 6233 titles that say meeting |

