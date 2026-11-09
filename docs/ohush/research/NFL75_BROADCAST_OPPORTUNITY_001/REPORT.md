# NFL75_BROADCAST_OPPORTUNITY_001

The frozen 10-second mean still starts a cover only while a broadcast transition is eligible. The line stays 0.163. Booth identity stays the 0.25 cosine to Al Michaels or Kirk Herbstreit. No model was trained. Speakers were not moved. The television was not changed.

Live-game scope starts at annotated coverage and ends at the postgame-show closer already transcribed in EXP-03: October 9604.9 s, September 5354.8 s. That closer, and everything after it, is out of scope. Halftime stays in. Pregame is not labeled on these two files. The postgame show that leads up to the closer is still inside the scope, because no whistle time is annotated. Gold did not arm any transition.

## Verdict

**REJECT** the broadcast-opportunity gate as a muter.

Hearing the booth recently does protect ordinary play, and the commercial score does confirm a pod once that protection has expired. The combination still leaves 12 and 11 false episodes per program hour, and the causal coverage falls to 64% and 63%. One false episode an hour and 75% coverage are not both available from these rules.

| Rule | October causal coverage | October episodes/hour | September causal coverage | September episodes/hour | Worst cut |
| --- | ---: | ---: | ---: | ---: | ---: |
| Unprotected, live-game scope | 95.1% | 36.6 | 94.4% | 22.8 | 54s, 34s |
| A. 30s since the booth | 63.6% | 12.0 | 62.8% | 11.0 | 21s, 26s |
| D. Acoustic change and a new speaker | 54.0% | 9.0 | 47.9% | 5.9 | 39s, 16s |
| A or D | 76.7% | 14.6 | 74.0% | 11.0 | 39s, 26s |
| B. Sign-off plus an acoustic change | 0% | 0 | 0% | 0 | — |
| C. Stoppage, then a departure | 0% | 0 | 0% | 0 | — |

Full-tape unprotected coverage is still 95.1% and 95.2%, with 35.5 and 27.3 episodes per hour. Dropping the nightcap pods does not create the product. Scoped program is 7175 s on October (20 breaks, 2430 commercial seconds) and 4257 s on September (9 breaks, 1098 commercial seconds). The full tapes are 23 and 13 breaks.

A and D together clear 75% causal coverage on October only. September is 74.0%. Both games stay an order of magnitude above one episode an hour. With gold endings, rule A would cover 78.4% and 78.8% and would still leave 6.5 and 5.9 episodes per hour, with cuts of 21 s and 26 s.

## Answers

1. **Nineteen of twenty October breaks, and eight of nine September breaks, become eligible under the 30-second booth rule before they end.** Seventeen and eight of those are eligible inside the first 30 seconds. The misses are the 34-second October pod at 2396 s, where the booth never stays gone, and the September opening at 1.6 s, where no booth vector exists yet. The acoustic speaker-change misses 6 and 4 breaks. The sign-off rule arms on none.

2. **The early path did not open.** Stoppage words do show up in the minute before some pods, and they showed up in none of the 144 control chunks or the 8 ordinary-absence chunks. Saying them, then waiting for a speaker change, produced zero arms: the booth is still talking between the word and the cut, and that continued match cancels the arm. A two-minute warning, a timeout, and a halftime mention muted nothing.

3. **The 30-second hypothesis is a coverage ceiling sitting on the product floor, and a measured gate well under it.** If the last booth word were exactly at the gold start and every later second were caught, a 30-second wait would leave 74.5% of October's full-tape ads and 75.3% of the live-game ads. September would leave 76.6% and 75.4%. The real clock is less regular. On the pods that do go eligible, the frozen score then covers essentially all of the remaining seconds when the ending is perfect: oracle coverage is 78.4% and 78.8%, against 1908 and 865 coverable seconds. Causal coverage is 63.6% and 62.8% because a booth-like match inside the pod resets the 30 seconds. A third of live-game ad time, 813 s and 329 s, still falls inside 30 seconds of such a match.

4. **Booth absence is the part that cuts false starts. The other two evidence sources do not.** Unprotected live-game episodes fall from 73 to 24 on October and from 27 to 13 on September. That is 12.0 and 11.0 per hour, down from 36.6 and 22.8. Hidden program falls from 386 and 300 seconds per hour to 69 and 92. The cap is 5. Adding the acoustic change lifts October's causal coverage over 75% and pushes the episode rate back up to 14.6. The spoken rules add no covers and remove no episodes.

5. **The state machine is the right shape, and it is not a substitute for a later classifier.** It shows that a hot score while Michaels or Herbstreit were just heard is the large class of false starts, and that class can be refused. What remains is smaller, and it is still about ten times the cap. Training should wait until those remaining episodes are separated. A general hard-negative model on every hot second would relearn a distinction this gate already makes.

6. **The highest-ROI next step is an inventory of the residual episodes, not a fingerprint and not another hold.** Rule A leaves 24 and 13 causal episodes. The longest are an Amex stretch at October 3425–3447 s (21 s), halftime-adjacent talk at 3270–3283 s (12 s), the postgame show at 9156–9169 s (12 s) and September 5031–5059 s (26 s), a late return at September 2338–2357 s (19 s), and the desk at 4532–4546 s (14 s). Those seconds are labeled program. A known-ad fingerprint does not clear them. The frozen score already confirms the seconds once eligibility is true, and the published fingerprint hit only a handful of pods.

## Where the 30 seconds actually falls

Booth age is measured at the gold start. Eligibility is the first live-game second at which the booth has been gone for 30 seconds. Coverable seconds assume a perfect confirm and a perfect return after that moment. They are a ceiling for rule A.

### October 8

| Start | Duration | Booth age at start | Eligible after | Coverable | In the first 30s |
| ---: | ---: | ---: | ---: | ---: | --- |
| 140 | 237s | 6.6s | 24s | 213s | yes |
| 572 | 112s | 2.2s | 60s | 51s | no |
| 1003 | 122s | 1.4s | 29s | 93s | yes |
| 1616 | 121s | 4.8s | 25s | 96s | yes |
| 1973 | 33s | 2.5s | 28s | 5s | yes |
| 2230 | 136s | 8.3s | 22s | 114s | yes |
| 2396 | 34s | 0.5s | never | 0s | no |
| 3025 | 153s | 2.2s | 28s | 125s | yes |
| 3549 | 153s | 154s | 0s | 153s | yes |
| 3981 | 137s | 15.3s | 15s | 122s | yes |
| 4419 | 121s | 12.1s | 19s | 103s | yes |
| 4858 | 121s | 11.4s | 20s | 102s | yes |
| 5332 | 122s | 2.5s | 28s | 93s | yes |
| 5671 | 122s | 3.5s | 26s | 96s | yes |
| 6055 | 121s | 7.1s | 24s | 98s | yes |
| 6364 | 152s | 1.7s | 29s | 122s | yes |
| 7169 | 124s | 5.1s | 50s | 74s | no |
| 7677 | 121s | 7.7s | 23s | 98s | yes |
| 8137 | 40s | 5.2s | 25s | 14s | yes |
| 8803 | 148s | 18.3s | 12s | 135s | yes |

The 34-second pod at 2396 s is the one a 30-second rule cannot see. The two-minute warning and a halftime mention are both in the ten seconds before it. They did not become an arm. The pod at 572 s waits 60 seconds because a booth match inside the pod restarts the clock. The same restart happens at 7169 s.

### September 24

| Start | Duration | Booth age at start | Eligible after | Coverable | In the first 30s |
| ---: | ---: | ---: | ---: | ---: | --- |
| 2 | 48s | none | never | 0s | no |
| 234 | 122s | 5.0s | 26s | 97s | yes |
| 913 | 120s | 9.4s | 21s | 100s | yes |
| 1490 | 121s | 8.5s | 22s | 99s | yes |
| 1743 | 152s | 3.3s | 27s | 125s | yes |
| 2218 | 120s | 3.9s | 26s | 94s | yes |
| 2797 | 121s | 7.1s | 23s | 98s | yes |
| 3496 | 137s | 11.9s | 19s | 118s | yes |
| 4337 | 156s | 10.0s | 21s | 135s | yes |

The opening pod has no booth cosine yet. September's first usable enrollment clip ends at 183 s. Unknown is not treated as absence. One hundred thirty-five program seconds at the start of that file are in the same state.

## Spoken cues

Five-second chunks, `faster-whisper` `base.en`, int8, CPU. The recognizer was not fine-tuned. A chunk is evidence only after it ends and the recognizer returns. Median processing is 0.29 s, the 90th percentile is 0.58 s, and one chunk took 5.6 s. Five hundred forty-six chunks finished in 230 s of wall time. That is fast enough to follow a broadcast. It did not find a handoff we could act on.

The frozen sign-off list hits one chunk, October 8782–8787 s: "After all these messages." The chunk is known at 8787.9 s, fifteen seconds before the pod at 8803 s. No acoustic onset falls within three seconds of that time, so rule B does not arm. The same line was already read in EXP-03 as advertising copy. September has no sign-off hit. Control chunks and ordinary-absence chunks have none.

Stoppage language hits eight October lead chunks and one September lead chunk: two-minute warning, halftime, end of the quarter, and one knee-injury sentence forty seconds before the September pod at 2218 s. None of the 144 control chunks contain those phrases. None of them are followed by a speaker-change arm before the booth is heard again, so rule C arms zero times. A timeout was not allowed to mute, and on these windows it never had the chance to.

## What the booth cosine is doing

October has a finite booth cosine on all 6845 speech windows: 3821 at or above 0.25, 3024 below. September has 5280 finite windows: 1974 matches and 3306 below, plus 119 windows before enrollment. Speech and booth identity disagree on a large share of windows. That is expected. The studio, the crowd, and Ryan Fitzpatrick are not in this booth pair. Fitzpatrick remains in neither prototype. The prototypes were chosen on October 18. October's vectors are September audio. September's clips start at each clip's own end, and one of them is a song.

Ordinary 30-second absences, more than 60 seconds from every pod, start only four times on each game. The gate is not firing on every pause in the call. Nine hundred forty-nine October program seconds and 722 September program seconds are still inside an absence. That is 13% and 17% of scoped program. The false episodes live in those stretches: sponsor reads the gold file calls program, the postgame show before the closer, halftime-adjacent talk, and short late returns after a pod.

## Stop

Reject the 30-second absence rule as a muter, and reject the acoustic and spoken arms as well. Keep the shape: a hot commercial score is allowed to mute only after the booth has actually left. Do not sweep 20, 25, or 40 seconds. The perfect-wait ceiling is already 75% on the live-game cut, and the measured causal result is lower because booth-like matches inside the ads reset the clock.

Do not start `OHUSH_NFL75_HARDNEG_001` on every hot second. The seconds that still need a decision are the 24 and 13 causal episodes this gate still mutes.

Next measurement: **OHUSH_NFL75_ABSENCE_RESIDUAL_001**. Categorize those episodes as late return, sponsor read, halftime, postgame show, or live football with the booth quiet. Leave the gold labels where they are. Do not train, and do not move a speaker. A conditional commercial fingerprint stays behind that inventory: the score already covers an eligible pod when the return is given, and a fingerprint of a known spot does not relabel the program seconds this gate still cuts.
