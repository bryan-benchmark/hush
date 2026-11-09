# NFL75_PROTECT_001

Can the enrolled TNF voices veto a false mute from the frozen rolling mean?

The start rule is unchanged: the 10-second mean, line 0.163, frozen in NFL75_MEAN_001 on the two NBC games. October 8 and September 24 did not move that line, and they did not choose the 0.25 cosine. Both Prime tapes are development inspections. The oracle column uses gold endings and is not a deployable result. Nothing was trained. Speakers were not moved. The television was not changed.

## Verdict

**REJECT** the existing protective evidence as a gate.

A current SpeechBrain match, cosine at or above 0.25 on a window that ended in the last second, leaves both games far from the NFL75 caps. With gold endings, October still has 40 false-mute episodes per program hour and September has 35. The worst cuts are 46 seconds and 31 seconds. Hidden programming is 186 and 229 seconds per program hour. The caps are under 1 episode per hour, under 10 seconds, and under 5 hidden seconds per hour.

The same gate does keep the commercials. Oracle coverage stays 98.6% and 98.5%, because a gold ending refills any hole that still touches the break. On the causal path, coverage falls from 95.1% to 90.0% on October 8 and from 95.2% to 93.4% on September 24. That is 133 seconds and 30 seconds of advertising opened back up. The break's first start does not move. Median extra delay is 0.0 seconds, and no break is lost.

The 30-second memory at 0.10 is the other existing rule, measured only as a cost. It drives the false mutes to zero on October and to 3 on September, and it also drops oracle coverage to 15.9% and 26.8%. It misses 18 of 23 October breaks and 7 of 13 September breaks. A blanket memory of the announcer spends the commercial budget.

## Answers

1. **Most of the false-mute time is people talking.** On the oracle episodes, announcer and color commentary is 323 of 618 seconds on October 8. Sponsor and network reads that the gold file still marks as program are the next 137 seconds, including the Amex lounge read (54s), the Reacher promo (41s), and Crucial Catch (33s). September is led by the nightcap and other-game desk, 196 of 473 seconds, then announcer commentary at 114 seconds and sponsor reads at 107 seconds. The Chili's spot at 2978s is 34 of those seconds. Stadium seconds with no transcribed speech are 35 and 17. Ordinary football, more than 60 seconds from every break, is still the largest boundary slice: 331 and 272 seconds.

2. **The cosine sees many of those moments and does not hold them.** At the second the unprotected episode opens, October has a current match on 35 of 70 episodes and September on 10 of 37. A match at that second clears 14 of the 35 October episodes and 4 of the 10 September episodes. The other matches only shorten the cut, because the 10-second mean is still hot on the next second and the mute resumes. Every October episode, and 35 of 37 September episodes, has some cosine at or above 0.10 in the prior 30 seconds. September's first episode, at 64 seconds, has no enrollment yet. The first usable clip on that tape ends at 183 seconds.

3. **No.** The gate does not approach NFL75. It fully clears 14 of 70 October episodes (20%) and 4 of 37 September episodes (11%). It releases 270 and 158 seconds of the original interruptions, then the delayed opens create 55 and 62 seconds of new program prefixes, so the net drop in hidden programming is 215 and 96 seconds. The scorer's episode count rises, from 70 to 87 and from 37 to 57, because a split wider than 2 seconds counts as two episodes. Net hidden programming falls 35% on October and 20% on September. About two-thirds of October's hidden time, and four-fifths of September's, is still there. The rate is still about 40 times the cap.

4. **The missing piece on October is a hold of a match we already have. The missing piece on September is the desk.** After the gate, the original October episodes still contribute 148 seconds of announcer commentary and 87 seconds of sponsor reads. September still contributes 130 seconds of nightcap and other-game talk and 85 seconds of announcer commentary. Stadium prefixes barely move. Ryan Fitzpatrick has labels on October 8 and none on September 24, so his voice is in neither prototype. The next ticket should measure a short hold of this same 0.25 cosine, a few seconds and not the 0.10 floor, and report the commercial cost. If that hold still leaves the nightcap and the booth stretches that never reach 0.25, the training set is those remaining hot seconds. Not another general commercial model.

5. **False starts still dominate.** After the gate, ordinary football accounts for 171 of the 403 oracle-hidden seconds on October and 203 of 377 on September. The return shoulder falls from 127 to 110 seconds on October and stays near 53 on September. Causal late returns shrink from 225 seconds to 87, and from 236 seconds to 91. September's worst cut falls from 84 seconds to 31 because a voice ends that tail. The oracle column already misses every cap, so the return is not what is keeping this candidate out.

## What the 107 episodes are

Diagnostic labels from a Whisper base transcript of the first 20 seconds of each oracle episode. Shorter episodes are the whole cut. Gold labels were not edited. A sponsor read inside program audio stays in the false-mute total. The transcript is a listening aid. Names in it are often wrong.

| What is audible | October episodes | October seconds | September episodes | September seconds |
| --- | ---: | ---: | ---: | ---: |
| Announcer commentary | 43 | 322.9 | 11 | 114.2 |
| Studio, nightcap, other games | 5 | 75.0 | 12 | 196.0 |
| Sponsor or network read | 5 | 137.2 | 6 | 107.2 |
| No transcribed speech | 7 | 35.3 | 4 | 16.7 |
| Sting, music, stay-with-us | 4 | 28.0 | 1 | 22.0 |
| Too short or garbled | 6 | 19.3 | 3 | 17.0 |

Seconds of those same episodes that the gate still mutes:

| What is audible | October still muted | September still muted |
| --- | ---: | ---: |
| Announcer commentary | 147.9 | 85.2 |
| Studio, nightcap, other games | 42.0 | 130.0 |
| Sponsor or network read | 87.2 | 64.2 |
| No transcribed speech | 35.3 | 13.7 |
| Sting, music, stay-with-us | 22.0 | 10.0 |
| Too short or garbled | 13.3 | 12.0 |

The four reads a listener would call commercials are Crucial Catch at October 816s (33s), Amex at October 3391s (54s), Reacher at October 4120s (41s), and Chili's at September 2978s (34s). Saving those seconds would be the wrong win. They stay in the totals because the gold file calls them program.

## The trade

| | October oracle | October causal | September oracle | September causal |
| --- | ---: | ---: | ---: | ---: |
| Coverage before | 98.6% | 95.1% | 98.5% | 95.2% |
| Coverage after the 1s gate | 98.6% | 90.0% | 98.5% | 93.4% |
| Episodes per hour before | 32.3 | 35.5 | 22.4 | 27.3 |
| Episodes per hour after | 40.2 | 45.7 | 34.6 | 40.0 |
| Worst cut before | 54.0s | 54.0s | 34.0s | 83.6s |
| Worst cut after | 46.0s | 46.0s | 31.0s | 31.0s |
| Hidden seconds per hour before | 285 | 379 | 287 | 430 |
| Hidden seconds per hour after | 186 | 219 | 229 | 284 |
| Episodes fully cleared | 14 of 70 | | 4 of 37 | |
| Ad seconds opened back up | 0 | 132.9 | 0 | 30.0 |
| Extra delay of a break that still starts | 0.0s | 0.0s | 0.0s | 0.0s |

Where the hidden seconds sit. A second in both the 30 seconds before a break and the 30 seconds after one is counted with the return.

| Slice | October before | October after | September before | September after |
| --- | ---: | ---: | ---: | ---: |
| Ordinary football | 331s | 171s | 272s | 203s |
| Other program | 88s | 59s | 52s | 59s |
| First 30s after a break | 127s | 110s | 52s | 53s |
| Last 30s before a break | 72s | 63s | 97s | 62s |

The causal return adds the rest. Before the gate that tail is 225 seconds on October and 236 on September. After the gate it is 87 and 91.

Episodes the gate does not touch at all: 10 on October, 15 on September. Seven of the October ones, and 11 of the September ones, have no speaker window ending in the last second. The others have a cosine under 0.25. Several of the silent ones are the last few seconds before a gold break. The 30-second memory at those same opens is usually above 0.10. Using that memory is the row below, and it takes the ads with it.

| 30s memory at 0.10 | October oracle | October causal | September oracle | September causal |
| --- | ---: | ---: | ---: | ---: |
| Commercial coverage | 15.9% | 2.1% | 26.8% | 7.6% |
| Breaks missed | 18 of 23 | 18 of 23 | 7 of 13 | 7 of 13 |
| False-mute episodes | 0 | 0 | 3 | 4 |
| Worst cut | 0s | 0s | 9.0s | 9.0s |

## How the voices were scored

The published ECAPA windows for these two games were not on disk. The replay uses `speechbrain/spkrec-ecapa-voxceleb`, 2-second windows, 1-second hop, the published SpeechBrain line 0.25, and Silero regions. October produced 6,845 windows against the old count of 6,846. The maximum cosine is 0.783. September produced 5,399 windows, maximum finite cosine 0.926. Saved `enroll_tnf.npy` was not used.

October's prototype is the September 24 enrollment only: Al Michaels, Kirk Herbstreit, Clarissa Thompson, Andrew Whitworth, and Tony Gonzalez, 29 clips, available from kickoff. October's own labels were not added. September has no earlier TNF enrollment. Its prototype is those same 29 labels from September 24, and each clip starts counting at its own end. That is the owner's enrollment clock, not an automatic booth tracker. One Kirk clip is labeled song, which the published keep-list includes, and it enters at 3896 seconds. Ryan Fitzpatrick is on the TNF cast list and in neither prototype.

A window can veto only after it has ended. A missing cosine does not veto. The future side of a window is ignored. September's speaker windows run to 7598.6 seconds. The annotated tape ends at 7600. The audio file continues to 7919.9, past the scored clock.

## Stop

Reject the 1-second match as a path to NFL75, and reject the 30-second 0.10 memory because it mutes the breaks. Keep the cosine. It is present on the false mutes, and a one-second reading of it cannot cover a hot 10-second mean.

Next ticket: **OHUSH_NFL75_BOOTH_HOLD_001**. Measure holds of a few seconds on this same 0.25 cosine. Do not drop the floor to 0.10. Do not train. If the commercial cost of that hold is already too high, or the nightcap and the unmatched booth stretches remain, the training set is those leftover hot seconds, including the desk and any Fitzpatrick stretches. Leave the unmarked sponsor reads in the commercial pile.
