# OHUSH_PAUSE_TRUST_001

A three-second pause before a mute opens passes the coverage gate. It uses the frozen 10-second mean at 0.163 and the frozen 0.25 cosine. It does not close a mute that has already started. The late returns stay where they are.

The gate was causal coverage within half a percentage point of the unprotected baseline on each tape, and a drop in genuine programming muted on each tape. `entry_3` is the passing rule with the largest drop: 288 seconds on October 8 and 144 seconds on September 24. Net commercial coverage moves from 95.06% to 94.73% on October, 8.5 seconds, and stays 95.15% on September. Nothing was deployed. The television was not changed. The live 0.55 booth was not in this replay.

## What the replay held still

Decisions use only audio that has already arrived. A speaker window counts at its end. A gap of three seconds protects a decision whose last 0.25 match ended within those three seconds. Gold endings are not an input. Oracle rows were not scored.

The unprotected mean, the published one-second veto, and the blind five-second hold were replayed as baselines. Their causal coverage, covered seconds, program seconds, and episode counts match NFL75_BOOTH_HOLD_001.

Two families were scored separately.

| Family | What it is allowed to do |
| --- | --- |
| Entry | Refuse to open a mute for the gap. An open mute ends only when the raw score stays at or below zero for three seconds. |
| Release | Close an open mute when a match falls inside the gap, and stay open until that gap ends. |

The release family reproduces the published holds. `release_1` and the one-second veto make the same decisions. `release_5` and the blind five-second hold make the same decisions. A release that stays open for the whole gap is that hold. The entry numbers below are the new measurement.

A second entry timer, marked cold, refreshes only when the 10-second mean is below 0.163 at the match. A hot mean does not extend it. That reuses the frozen line.

## The gate

Genuine programming muted is program seconds under a cover, with the promotional-read overlay removed. Amex and Chili's sit in that overlay. Late-return tails sit in the genuine total, and every entry rule leaves those tails unchanged: 224.5 seconds on October and 236.2 seconds on September.

| Rule | October coverage | October genuine | October ads given back | September coverage | September genuine | September ads given back | October episodes | September episodes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Unprotected | 95.06% | 684.3s | 0 | 95.15% | 661.5s | 0 | 77 | 45 |
| Entry 1s | 94.87% | 573.3s | 5.0 | 95.15% | 617.5s | 0 | 72 | 42 |
| Entry 2s | 94.73% | 474.0s | 8.5 | 95.15% | 545.5s | 0 | 62 | 41 |
| Entry 3s | 94.73% | 396.0s | 14.5 gross, 8.5 net | 95.15% | 517.5s | 1.0 gross, 0 net | 55 | 38 |
| Entry 5s | 93.56% | 323.0s | 39.5 | 95.06% | 489.1s | 2.6 | 45 | 35 |
| Entry 3s, cold mean | 94.99% | 594.0s | 1.7 | 95.15% | 634.5s | 0 | 69 | 43 |
| Entry 5s, cold mean | 94.61% | 529.0s | 11.7 | 95.03% | 607.5s | 2.0 | 61 | 41 |
| One-second veto | 90.03% | 385.2s | 141.9 | 93.35% | 423.5s | 30.0 | 99 | 66 |
| Blind five-second hold | 79.96% | 180.4s | 400.9 | 89.17% | 301.1s | 100.6 | 46 | 43 |

Entry 5 fails October by 1.50 percentage points. Entry 3 passes. Of the 14.5 October seconds it gives back, 6.0 seconds are muted again a little later in the same break, at 2301–2307, because the return clock started later. The net is 8.5 seconds, 0.32 percentage points. September's one given-back second is matched by one newly muted second at 7516. No break is missed on either tape. Episode counts fall. The one-second veto moves them the other way, 77 to 99 and 45 to 66, because a release punches a hole and the mean opens again.

The ads given back by the one-second veto are mostly inside the break: 131 of 142 October seconds, and all 30 September seconds. That is a match during the commercial closing the mute and holding it open. The entry rule does not do that.

The cold timer keeps interior ad loss at zero and gives up the programming. Entry 3 cold saves 90 and 27 seconds. Unconditional entry 3 saves 288 and 144. The matches that protect the game are arriving while the mean is already hot. Ending the pause because the mean is hot ends the protection on the same seconds it was for.

A gap of zero saves 21 October seconds and no September seconds. Only 422 of 4,512 October matches, and 242 of 3,141 September matches, land within 50 milliseconds of a score time. The window ends between decisions. A linger of zero usually misses the decision that would have used it.

## Mandatory traces

Second-by-second rows are in `traces.jsonl`. The gold label on those rows is retrospective. It was not an input.

**Dropped pass, October 9156–9169.** The unprotected cover is 12 seconds. Entry 3 leaves 9. At 9156 the mean is 0.55 and the last 0.25 match is 9.8 seconds old, so the three-second pause does not block the open. At 9165 the raw score has been cold for three seconds and the cover ends. At 9166 a 0.43 match is 0.7 seconds old and the pause blocks the reopen. The rise toward 0.70 happens after the mute has started. Entry protection does not go back and undo it.

**Injury desk, September 6266–6292.** Stays 25 seconds under every entry gap, including five seconds. At the open the mean is 0.25 and the last 0.25 match, Clarissa Thompson at 0.46, is 5.6 seconds old. Nothing during the desk reaches 0.25. This remains the enrollment miss from the forensics file.

**October boundary at 1003.3.** The unprotected mute is already on. The mean at the boundary is about 2.5 and still rising. Al Michaels matched about a second earlier. Entry 3 delays the cover 1.7 seconds into the ad. The cold start on this tape is a different break, 2396.2, delayed 8.8 seconds with the mean still cold. Entry 3 leaves that delay at 8.815 seconds.

**September break 6854–7020.** The unprotected tail is 83.6 seconds. Entry 3 leaves it at 83.6 seconds. The one-second veto cuts it to 13.6 seconds, and that is the same rule that gives back 30 seconds of September advertising from inside breaks.

**Amex, 3391–3447.** Unprotected mutes 54 seconds. Entry 3 mutes 44. Ten seconds of the read play after the raw score dips and a match holds the reopen off. Chili's, 2978–3014, goes from 34 seconds muted to 31. Across the promotional-read overlay that is 22.2 October seconds and 3.0 September seconds. Those seconds are the accepted tradeoff, and they are not in the genuine drop above.

## Recommendation

Use the three-second entry pause as the measured candidate. It is not a deployable change and it was not wired into the live booth. It removes 432 seconds of genuine programming mutes on these two tapes and spends 8.5 net commercial seconds on October. It does not touch the 461 seconds of late returns. It does not clear the injury desk. It leaves nine seconds of the dropped pass muted.

Do not ship the one-second veto or the five-second hold as the way to get this save. Their coverage cost is the release inside the ad.

The cold-mean cutoff is the wrong terminator for this pause. The score is already hot on the seconds the pause is there to save.

**Next experiment: OHUSH_RETURN_TRUST_001.** Keep this mean and this cosine. Ask whether a match can end a mute that is already open, without the gap then holding the television open through the rest of the commercial. Score isolated matches and sustained matches separately. The 83.6-second September tail and the other 377 seconds of late return are the target. The one-second veto is the caution: it already cuts that tail to 13.6 seconds and spends 30 September seconds plus 142 October seconds of advertising to do it. Do not enroll a new voice in that run. The injury desk stays the control a speaker-gap rule must not claim.
