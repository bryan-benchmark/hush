# NFL75_BOOTH_HOLD_001

A recognized TNF voice can hold a mute off for a few seconds, and it can refuse to mute again until the frozen commercial score dips and crosses 0.163 a second time.

The start rule is unchanged: the 10-second mean, line 0.163, frozen in NFL75_MEAN_001. The voice line is the published SpeechBrain cosine, 0.25. Holds are 1, 3, 5, and 8 seconds after a speaker window ends. A window ending at T protects decisions from T through T plus the hold. It cannot protect anything before T. One second is the veto already measured in NFL75_PROTECT_001, and this run reproduces it (October oracle 87 episodes, September 57).

Rearm adds no new threshold. After a 0.25 match blocks an open or releases a cover, that same hot run cannot open another cover. The mean has to fall below 0.163 and cross it again. A voice heard while the mean is still cold does not disarm the next crossing.

October 8 and September 24 are development inspections. Oracle rows use gold endings and are not deployable. Nothing was trained. Speakers were not moved. The television was not changed. Gold labels were not edited.

## Verdict

**REJECT** both the short hold and the rearm as a path to NFL75.

A hold by itself misses no commercial break. It does cut false mutes. At 5 seconds, the causal coverage is 80.0% on October 8 and 89.2% on September 24, inside the coverage room left after the one-second veto. The oracle episode rate is still 14.8 and 19.4 per program hour. The worst cuts are 20 seconds and 30 seconds. The caps are under 1 episode per hour, under 10 seconds, and under 5 hidden seconds per hour.

Eight seconds reaches 12.0 and 15.2 oracle episodes per hour and puts October's causal coverage at 74.2%, under the 75% floor. The longest September cut is still 30 seconds.

Rearm is the rule that spends the commercials. The one-second hold plus rearm leaves causal coverage at 35.5% and 51.9%. It misses 2 breaks on each game. On every one of those four breaks the 10-second mean never falls below 0.163 inside the gold ad, so the score never rearms. Longer holds miss more breaks the same way.

## Answers

1. **A few extra seconds of a real match help, and they do not get near one false mute an hour.** From the unprotected oracle rate of 32.3 and 22.4 episodes per hour, five seconds lands at 14.8 and 19.4, and eight seconds at 12.0 and 15.2. That is a large cut on October and a small one on September. Getting under one per hour from the five-second row would mean removing about 30 of the 32 episodes still left on each game.

2. **Rearm preserves football by leaving the ad on.** Timed holds miss zero breaks at every length. With rearm, the missed breaks are:

| Hold | October breaks missed | No reset inside the break | September breaks missed | No reset inside the break |
| --- | ---: | ---: | ---: | ---: |
| 1s | 2 | 2 | 2 | 2 |
| 3s | 3 | 3 | 2 | 2 |
| 5s | 6 | 4 | 4 | 4 |
| 8s | 11 | 6 | 6 | 4 |

The other misses did dip below 0.163, by one to five samples, and the fresh cross still did not open a cover. The unprotected rule covered every one of these breaks. Five-second rearm gives up 1,699 causal ad seconds on October and 912 on September.

3. **The episodes that survive a hold are the ones a longer memory of this cosine cannot see.** At five seconds the longest remaining cuts are an Amex read at October 3420–3440s (20s), nightcap talk at October 9805–9822s (17s), the Chili's read at September 2978–3009s (30s), and other-game desk talk at September 6266–6292s (25s). Eight seconds still leaves the Chili's read at 30 seconds and the desk at 22 seconds. Ryan Fitzpatrick is on the October labels and in neither prototype.

## Timed holds

A match refreshes the hold. Silence does not start one. No break is missed in this table.

| | October causal coverage | October episodes / hour, oracle then causal | October worst, oracle then causal | September causal coverage | September episodes / hour, oracle then causal | September worst, oracle then causal |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| No voice | 95.1% | 32.3, 35.5 | 54s, 54s | 95.2% | 22.4, 27.3 | 34s, 84s |
| 1s | 90.0% | 40.2, 45.7 | 46s, 46s | 93.4% | 34.6, 40.0 | 31s, 31s |
| 3s | 84.5% | 22.2, 29.1 | 20s, 20s | 91.1% | 23.0, 29.7 | 30s, 30s |
| 5s | 80.0% | 14.8, 21.2 | 20s, 20s | 89.2% | 19.4, 26.1 | 30s, 30s |
| 8s | 74.2% | 12.0, 16.6 | 19s, 19s | 85.7% | 15.2, 21.8 | 30s, 30s |

Hidden programming per hour, oracle then causal: at 5 seconds, 76 and 104 on October, 154 and 209 on September. At 8 seconds, 58 and 77, and 125 and 180.

Oracle coverage stays high because a gold ending refills a hole that still touches the break. The causal column is the advertising actually given back. Five seconds gives back 399 commercial seconds on October and 100 on September. Eight seconds gives back 550 and 157. Oracle ad loss at those same rows is 22 and 3 seconds, then 44 and 16.

What happens to the original false-mute episodes. Eliminated means the episode's program seconds are gone. Split means one episode comes back as two or more. Recreated means a new episode that does not overlap an original one. The one-second row splits episodes, which is why its rate goes up. From three seconds on, the rate falls.

| Oracle | October eliminated | October split | October recreated | October episodes left | September eliminated | September split | September recreated | September episodes left |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1s | 14 of 70 | 10 | 16 | 87 | 4 of 37 | 7 | 14 | 57 |
| 3s | 35 of 70 | 5 | 5 | 48 | 11 of 37 | 6 | 4 | 38 |
| 5s | 45 of 70 | 3 | 3 | 32 | 13 of 37 | 4 | 3 | 32 |
| 8s | 53 of 70 | 2 | 6 | 26 | 17 of 37 | 2 | 2 | 25 |

## Rearm

| | October causal coverage | October episodes / hour, oracle | October breaks missed | September causal coverage | September episodes / hour, oracle | September breaks missed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1s + rearm | 35.5% | 13.8 | 2 | 51.9% | 16.4 | 2 |
| 3s + rearm | 35.2% | 8.3 | 3 | 51.9% | 12.7 | 2 |
| 5s + rearm | 30.7% | 7.4 | 6 | 40.4% | 10.3 | 4 |
| 8s + rearm | 20.4% | 4.2 | 11 | 29.3% | 8.5 | 6 |

On September, stretching the hold from 1 second to 3 with rearm on does not change causal coverage or the two missed breaks. The extra hold only trims football. The missed ads are the ones whose mean never comes back down.

Five-second rearm, breaks missed because the mean stays at or above 0.163 for the whole gold ad:

| Game | Break | Ad (s) |
| --- | ---: | --- |
| October 8 | 2 | 571.7–683.4 |
| October 8 | 3 | 1003.3–1125.2 |
| October 8 | 12 | 4858.5–4979.7 |
| October 8 | 22 | 9756.8–9769.8 |
| September 24 | 4 | 1490.0–1611.2 |
| September 24 | 6 | 2217.9–2338.3 |
| September 24 | 12 | 6854.0–7020.4 |
| September 24 | 13 | 7515.4–7600.0 |

October breaks 13 and 16 do dip, once and twice, and the new cross still does not open. Eight-second rearm adds October breaks 11 and 21, and September breaks 12 and 13 were already in the five-second list. The full miss list is in `results.json`.

## Largest cuts still standing

Five-second hold, the longest row that keeps causal coverage above 75% on both games. The same times appear in the causal column unless noted.

| Game | Start–end (s) | Duration | What the opening sounds like |
| --- | --- | ---: | --- |
| October 8 | 3420–3440 | 20s | Amex lounge read |
| October 8 | 9805–9822 | 17s | Nightcap |
| October 8 | 3400–3412 | 12s | Same Amex read, earlier piece |
| October 8 | 9156–9165 | 9s | Announcer, on a dropped pass |
| October 8 | 706–714 | 8s | Announcer, drive call |
| September 24 | 2978–3009 | 30s | Chili's |
| September 24 | 6266–6292 | 25s | Injury desk, other games |
| September 24 | 4200–4216 | 16s | Announcer |
| September 24 | 1396–1410 | 14s | Announcer |
| September 24 | 4532–4546 | 14s | Announcer, crowd |

September's causal column also keeps two late returns the oracle ends at the gold boundary: 2338–2357s (18.7s) and 4493–4509s (16.3s). Eight seconds still leaves Chili's at 2978–3009s (30s) and the desk at 6269–6292s (22s).

## Sponsor reads the gold file calls program

These stay inside every official false-mute total above. They are not relabeled. A listener can hear them as advertising. Training a protector to save them would teach OHush to keep spots the product may want muted. The transcripts are the first 20 seconds, from the same Whisper pass as NFL75_PROTECT_001.

| Game | Start (s) | Seconds | Opening |
| --- | ---: | ---: | --- |
| October 8 | 816 | 33 | Crucial Catch, NFL and the American Cancer Society |
| October 8 | 3018 | 6 | State Farm halftime show |
| October 8 | 3391 | 54 | Amex Platinum lounges and restaurants |
| October 8 | 4120 | 41 | Reacher, only on Prime |
| October 8 | 4989 | 3 | Matthew Lillard, only on Prime |
| September 24 | 1902 | 14 | Next matchup, only on Prime |
| September 24 | 2922 | 16 | Sony, official headphones of the NFL |
| September 24 | 2978 | 34 | Chili's |
| September 24 | 6014 | 14 | Thursday night, presented by Allstate |
| September 24 | 7470 | 3 | Cartman |
| September 24 | 7489 | 26 | Music tour, then the anthem is mentioned |

That is 137 seconds on October and 107 seconds on September, inside the unprotected oracle false-mute time. A five-second hold still mutes 45 seconds of the October list and 46 seconds of the September list. Those seconds are in the episode rates above.

## Whose voice this is

The prototypes are owner labels adjudicated on 2026-10-18, after both of these games. There is no enrollment file that was frozen before the season.

October's 29 clips are September 24 audio only: Al Michaels, Kirk Herbstreit, Clarissa Thompson, Andrew Whitworth, and Tony Gonzalez. The vectors predate October. The choice of which seconds to enroll does not. They are available from kickoff in this replay. October's own labels, including Ryan Fitzpatrick, are not in the prototype.

September has no earlier TNF enrollment. The same 29 clips are used, and each one starts counting at its own end. The first is available at 183 seconds. Four of the clips are labeled song, which the published keep-list includes. Ryan Fitzpatrick has no September label.

A missing cosine does not veto. Saved `enroll_tnf.npy` was not used.

## Stop

Reject another hold, and reject rearm. The five-second row is as far as this cosine can be pushed without giving up the coverage floor, and it leaves roughly 15 to 21 false episodes per program hour. The survivors are sponsor reads, nightcap and other-game desk, and announcer stretches this enrollment does not hold. Another timer on 0.25 will not separate those from commercials.

Next experiment: **OHUSH_NFL75_HARDNEG_001**. A lightweight veto on the existing AST scores, trained to tell a commercial from the football this detector still mutes: the announcer seconds that never reach cosine 0.25, the nightcap and other-game desk, and the transition audio. Decide the sponsor reads in the table above before any of them become a training label. Do not sweep another hold. Do not start that training in this step.
