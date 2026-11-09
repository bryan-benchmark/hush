# Hush progress handoff

23 October 2026. This note is for a new session. The operational entry point is still `HANDOFF.md`. Nothing in the restart below was wired into the television.

## What Hush is

OHush listens to a television through an optical cable. The computer can play that audio or play a cover instead. The open problem is the start of a commercial. The return of the show is a different decision.

A muted second of the game breaks a shipped mute. That run has no accuracy. On a run that stays off the game, accuracy is commercial seconds held, divided by 17,648.4. That denominator is the nine labeled football games. The rules are `docs/ohush/research/ACCURACY_LADDER_001/KPI.md`. The contract is `docs/ohush/swarm/RESEARCH_CONTRACT.md`.

The live desk is `ohush_live`. Monitor: http://127.0.0.1:3010/. Engine: http://127.0.0.1:8770/. The research copy in `src/hush` is not the test. A locked result is what the television plays: wire it into `ohush_live` and restart the sports daemon. A return does not start a cover. Do not retune a number while wiring it.

## Standing decisions

| Decision | State |
| --- | --- |
| Champion | No authorized mute. Nothing automatic may hide the game. |
| Count-200 fingerprint | The only research cover. Whole-pod replay holds 25.0 commercial seconds, 0 program seconds, 2 of 136 pods (0.14%). |
| Hold those two covers until music is under 0.30 | Measured, not installed. 116.0 commercial seconds, 0 program seconds, 0.66%. Same two pods. Median start lag 132.5 s. `docs/ohush/research/V1_HOLD_001/`, `docs/ohush/research/V1_SCORECARD_001/`. |
| Enrolled-show return at 0.10 | Locked in the live engine. A 30-second rolling max at or over 0.10 brings the game back. It does not start a cover. `src/hush/voice_floor.py`. |
| 180-second fail-open | Wired. If a cover never lets go, the television comes back. |
| October tapes | Already inspected. A threshold fit on them is not a held-out result. |
| Sealed, leave closed | `hush_20260917_205513`, `hush_20260920_200635`. |
| Live mute during this restart | Not changed. |

The nine football games, in capture order: Sept 9 NBC `hush_20260909_213047`, Sept 13 NBC `hush_20260913_210542`, Sept 14 ESPN `hush_20260914_212529`, Sept 24 Prime `hush_20260924_220624`, Oct 8 Prime Video `hush_20261008_205100`, Oct 10 cable `hush_20261010_222400`, Oct 11 afternoon `hush_20261011_135700`, Oct 11 night `hush_20261011_204300`, Oct 12 `hush_20261012_204200`. RedZone `hush_20260913_150934` is a control with no labeled commercials.

## The restart

The agreed first step was one question, whole sessions held out, causal audio, both commercial seconds and program seconds written down. Product targets of 50/70/90 percent, a controller, a live shadow, and hardware were left for later. They are still later. Fifty percent of 17,648.4 seconds is about 8,800 seconds. The best measured line on these tapes is 146.0 seconds.

Question: can a logistic classifier, trained only on labeled seconds from Sept 9 NBC and Sept 13 NBC, tell advertising from programming on other broadcasts, using audio that has already ended?

The vectors were already cached: 5-second windows of `MIT/ast-finetuned-audioset-10-10-0.4593`, CLS token, stamped at the end of the window. Shorter than the model's native 10.24 seconds is zero-padded with silence. Label `1` is a second entirely inside a verified commercial, `0` is entirely program, `-1` is mixed or unsure and is not programming. The fit used 21,400 labeled seconds (5,863 commercial, 15,537 program). Agreement with those labels at the head's own boundary is 92.73%. That figure is not a mute line.

The mute line is one step above the highest score that touches program audio on the two NBC games. It was locked before ESPN, Prime, RedZone, or October were scored. No new network was trained. `NEED.json`, gold, and the sealed tapes were left alone.

## Classifier results

| Step | Cutoff | How the cutoff was set | Held-out result |
| --- | ---: | --- | --- |
| `SUPERVISED_HELDOUT_001` | 12.155 | Any second that touches the show on the two NBC games | ESPN 28.0 commercial seconds, 0 program. Prime 39.0 commercial, 0 program. RedZone 0. Starts that fire are about half a minute late, then the score falls inside the break. |
| `SUPERVISED_PROGRAM_CEILING_001` | 9.893 | Highest second whose covered second is entirely program | ESPN 92.0 commercial, 0 program. Prime 117.0 commercial and 10.0 program seconds (8 interruptions). Sept 13, a fit game, loses 1.078 program seconds. |
| `SUPERVISED_CLEAR_CEILING_001` | 8.285 | Entirely program, and the five-second lookback contains no commercial | ESPN 186.28 commercial and 1.72 program. Prime 237.664 commercial and 20.336 program. RedZone 4.0 program. |

The middles do separate. On the two NBC games the commercial median is 4.103 and the program median is −6.155. ESPN's commercial median is 3.46 and its program median is −6.37. The safe line never sits in that gap. It sits on the tail.

The second that set 12.155 is not the show. It is Sept 13 NBC at session clock 154, label −1. The audio from 149 to 154 is inside a commercial. Of the second that would be covered, 0.391 seconds are program. The highest second that is entirely the show, with a clear lookback, is the same tape at 11412, score 8.285, AudioSet name Music, 1,591 seconds after the previous break. `docs/ohush/research/SUPERVISED_CEILING_001/`.

Inside one AudioSet name the tails still cross. For Music, 1,853 clear show seconds have median −2.425 and maximum 8.285. The 2,661 music-commercial seconds have median 4.594. A line above every clear show-music second leaves 2,257 of those ads unmarked. Speech has the same shape: show median −6.843, maximum 6.958, commercial median 4.036. The top AudioSet name is a weak call (median winning probability about 0.27 for show music and 0.36 for show speech). `docs/ohush/research/SUPERVISED_NAME_SCORES_001/`.

The loud Music seconds on Sept 13, in 1011–1124 and 10151–11419, are ordinary stretches of the game. At fingerprint count 200, the highest score between those two stretches is 3. A window matches itself at 511. Their embeddings are no tighter than ordinary show windows. The logistic head is finished as a commercial detector. `docs/ohush/research/SUPERVISED_STRETCH_001/`.

October was scored with the frozen cutoffs and labeled already-inspected. It loses program audio under every one of them. The weak tape is Oct 11 night.

A published comparison, left as it was: continuity collapse marks 12 of 13 evaluable ESPN starts inside 15 seconds, about 4.2 program collapses an hour, and 17 collapses on RedZone (8.5 an hour). It was not retuned. It is not a mute.

## Fingerprint results after the head was finished

Spot pieces, not a new count. Labeled breaks were split at the published 12 dB hole. Pieces of at least 2 seconds were enrolled from earlier football games only. A 5-second query at or above 200 covers the next 5 seconds, the Universal v1 clock. RedZone was queried against Sept 9 only and was never enrolled. A copy of an enrolled piece matches itself at 858.

| Broadcast | Commercial seconds at count 200 | Program seconds | Highest ad score | Highest show score |
| --- | ---: | ---: | ---: | ---: |
| Sept 13 RedZone | 0 | 0 | — | 10 |
| Sept 13 NBC | 0 | 0 | 189 | 148 |
| Sept 14 ESPN | 5.0 | 0 | 230 | 63 |
| Sept 24 Prime | 0 | 0 | 122 | 11 |
| Oct 8 Prime Video | 25.0 | 0 | 286 | 15 |
| Oct 10, both Oct 11, Oct 12 | 0 | 0 | under 200 | under 200 |

The 30.0 seconds are ESPN 2770–2775, against a Sept 9 piece, and five windows on Oct 8 against Sept 24 pieces: 145–150, 155–160, 170–175, and 6385–6395. Sept 13's show query of 148 is at session clock 90, before the first labeled break. A count chosen between 148 and 189 would be fit to that tape. Count 200 stays. `docs/ohush/research/SPOT_FINGERPRINT_001/`.

Those covers were then held until music fell under 0.30, on the 4-second steps already logged. No new cover was searched.

| Hold | From | Song drops | Commercial seconds | Program seconds |
| --- | ---: | ---: | ---: | ---: |
| ESPN break 2658.534–2780.388 | 2770 | 2780 | 10.0 | 0 |
| Oct 8 break 139.874–376.900 | 145 | 196 | 51.0 | 0 |
| Oct 8 break 6363.797–6515.381 | 6385 | 6400 | 15.0 | 0 |

That is 76.0 commercial seconds and 0 program seconds. The 30 fingerprint seconds sit inside these holds. The Oct 8 opening lets go at 196, the same step as the published whole-pod hold, and starts 5 seconds earlier (145 instead of 150).

Do not add 76 to 116. The published 116 is Oct 8 from 150 to 196 (46 seconds) plus Oct 12 from 5090 to 5160 (70 seconds). The opening would be counted twice.

Taken once each: Oct 8 from 145 to 196 (51), Oct 12 from 5090 to 5160 (70, already published), ESPN from 2770 to 2780 (10), and Oct 8 from 6385 to 6400 (15). **146.0 commercial seconds, 0 program seconds. 146.0 / 17,648.4 is 0.83%.** Four breaks start. The other 132 never do. The breaks that start still let go while most of the break is left. This is not installed. `docs/ohush/research/SPOT_HOLD_001/`.

## Where the build plan is

Step 1 is answered. The supervised head does not mark held-out ads under a line that leaves the show on. The product steps after that — a controller, half the ads on an unseen broadcast, a live shadow, a device — wait. They are not available from another threshold on these nine games.

The measured ceiling of the lines already in hand is 146.0 seconds, 0 program seconds, not wired. The installed research cover is still the whole-pod count-200 fingerprint at 25.0 seconds. The champion is still no authorized mute.

## What a next session may do

An owner lock of 146.0, or of the older 116.0, means wiring that hold into `ohush_live` and restarting the sports daemon. Leave 0.30 and count 200 where they are. A lock of the hold does not start a new cover.

New evidence has to come from a game watched on the desk. The next Prime Thursday game is 29 October. A replay has to be marked as a replay. Misses from that session are new labels. These nine tapes have already been used.

A commercial-break marker needs a new capture where the marker and the optical audio share a clock. The old WAV files cannot supply the marker.

## What stays put

Count 200 stays. The 0.10 return stays. The sealed tapes stay closed. October does not choose a cutoff. The logistic head is not refit into a mute. A higher score on these same tapes is not a new result. Adding 76 to 116 double-counts the Oct 8 opening.

## Reports from this restart

| Report | What it answers |
| --- | --- |
| `docs/ohush/research/SUPERVISED_HELDOUT_001/` | The two-NBC logistic at 12.155, on games it never trained on |
| `docs/ohush/research/SUPERVISED_CEILING_001/` | The second that set 12.155 |
| `docs/ohush/research/SUPERVISED_PROGRAM_CEILING_001/` | Cutoff from entirely-program seconds |
| `docs/ohush/research/SUPERVISED_CLEAR_CEILING_001/` | Cutoff from show seconds with a clear lookback |
| `docs/ohush/research/SUPERVISED_NAME_SCORES_001/` | Music and Speech on the two NBC games |
| `docs/ohush/research/SUPERVISED_STRETCH_001/` | Whether the loud NBC seconds are one repeated sound |
| `docs/ohush/research/SPOT_FINGERPRINT_001/` | Spot pieces, earlier games only, count 200 |
| `docs/ohush/research/SPOT_HOLD_001/` | Those covers held until music is under 0.30 |

Readers live next to the reports, under `experiments/measurement/`, with the same names.
