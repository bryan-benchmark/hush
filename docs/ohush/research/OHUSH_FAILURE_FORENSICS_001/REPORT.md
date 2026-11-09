# OHUSH_FAILURE_FORENSICS_001

The frozen 10-second mean already has a usable announcer match on most of the programming it mutes. The mean mutes anyway because that policy does not read the match.

This is a diagnosis of one candidate: the NFL75 mean, line 0.163, fit on the two NBC games, with the SpeechBrain ECAPA cosine at 0.25 measured beside it. The live booth rule is a different system. Its match line is 0.55, its audio line is 0.22, and its state machine was not the code that produced these episodes. A 0.55 cut of this same ECAPA cosine is reported below so the two numbers are not treated as one score. Nothing was retuned. Gold was not edited. The television was not changed.

The recount of fresh matches is 35 of 70 on October 8 and 10 of 37 on September 24. That matches NFL75_PROTECT_001.

## Verdict

**The decision code is the dominant obstacle.** On the unprotected oracle, 677 of the 906 genuine false-mute seconds had a research cosine at or above 0.25 at the open or in the five seconds around it. The speaker model had already fired. The mean covered the audio because speaker evidence is not an input to that policy.

The model-or-enrollment miss is real and smaller. It is 82 seconds, all on September 24. October's unprotected oracle has zero seconds in that bucket.

Announcer-voiced reads stay last. Amex reaches 0.54 to an enrolled voice inside the read. Chili's reaches 0.66 to Al Michaels. Reacher reaches 0.70 to Al Michaels. Protecting those voices will leave those reads playing. That is the accepted tradeoff.

## The candidate

| Piece | What decided these episodes |
| --- | --- |
| Classifier | 10-second mean of the NBC logistic. A cover opens when the mean is at or above 0.163. |
| Return | The raw score stays at or below zero for three seconds. Oracle rows snap the end to gold instead. |
| Speaker | ECAPA cosine to Al Michaels, Kirk Herbstreit, Clarissa Thompson, Andrew Whitworth, and Tony Gonzalez. The research line is 0.25. A missing window does not veto. |
| Unprotected policy | The mean does not read the cosine. |
| One-second veto | A window that ended in the last second at or above 0.25 can block an open or release a cover. The hold ends when that second ends. |

Logs that were not available, and were not filled in: raw VAD region times, a human name on each window, the live 0.55 similarity on these tapes, an AST class such as music or jingle, and word times past the first 20 seconds of a listen. A football-event count is stored on each row and was not an input to the mute.

Every row is in `episodes.jsonl`, separated by policy (`unprotected`, `hold_1`) and by clock (`oracle`, `actual`).

## Why the mutes happen

Unprotected rule, gold endings. Seconds are program seconds the mean covered.

| Group | October episodes | October seconds | September episodes | September seconds |
| --- | ---: | ---: | ---: | ---: |
| Recognized voice, mean muted anyway | 51 | 406 | 20 | 271 |
| Voice the cosine never reached 0.25 | 0 | 0 | 7 | 82 |
| Other programming | 14 | 74 | 8 | 73 |
| Promotional read, scored last | 5 | 137 | 2 | 48 |
| Total | 70 | 618 | 37 | 473 |

The recognized-voice row splits in two.

| What the cosine did | October | September |
| --- | ---: | ---: |
| At or above 0.25 in the second the mute opened | 34 episodes, 225s | 10 episodes, 115s |
| At or above 0.25 in the episode or the five seconds before it, and not in that opening second | 17 episodes, 181s | 10 episodes, 155s |
| Opens where the prior five seconds already held a match | 19 episodes, 180s | 9 episodes, 109s |

October's published 35 opening matches include one promotional read. The 34 in the table are the genuine ones. September's 10 opening matches are all genuine. Chili's reaches Michaels later in the read, not in the opening second.

A pause is the second pattern. The dropped pass at October 9156 opens with a cosine of 0.14. Inside the same cut the cosine reaches 0.70 to Andrew Whitworth. The unprotected mean never consults it. The injury desk at September 6266 is the other pattern: speech is there, and the peak cosine on the whole cut is 0.18. That one is the model or the enrollment, not the state machine.

The one-second veto shows the same split in the code that does read the cosine. It clears a match only for that second. When the second ends and the mean is still hot, the cover returns. After the veto, October still has 233 genuine seconds in the recognized-voice bucket, and the episode count rises from 70 to 87 because a one-second hole splits one mute into two. Causal coverage moves from 95.1% to 90.0% on October and from 95.2% to 93.4% on September. Oracle coverage stays 98.6% and 98.5% because a gold ending fills any hole that still touches the break.

No unprotected break is missed entirely. Nine October breaks and four September breaks start more than a second late. The mean at those gold starts is still cold, often well below zero, and it does cross inside the break. The late start is the 10-second window still containing the show. October break 7 also has a 0.46 cosine at the boundary. The unprotected rule does not use it, and the mean at that instant is −5.2, so the delay is the window, not a speaker veto.

Causal late returns are separate and large: 18 tails, 225 seconds, on October, and 11 tails, 236 seconds, on September. The worst is 83.6 seconds after September's break at 6854–7020. The mean at that gold end is 1.66, so three cold seconds never accumulate. The same one-second veto cuts those tails to 87 and 91 seconds. The voice was available for the return. The unprotected return rule did not ask for it.

## Four ceilings

Each of these is an oracle diagnostic. None of them is a deployable accuracy.

**A. Perfect identity, on time.** No person was named on these windows, so this ceiling cannot be measured as a speaker fact. If the retrospective listen is right, the speech it called announcer or desk talk is 406 October seconds and 353 September seconds. Removing those seconds uses the episode boundary and the listen. It is not a claim that a model can see them in time.

**B. Trust the matches that already exist.** The on-time matches are 225 and 115 genuine seconds. Adding the matches that sit in the surrounding five seconds raises that to 406 and 271 seconds. Deleting those episodes after the fact spends no commercial seconds, because the deletion only touches program. The measured rule that actually consults the match, the one-second veto, spends the coverage in the paragraph above and does not remove the whole 406 and 271. A blind five-second hold, already measured, gives back 399 October commercial seconds and 100 September commercial seconds. Rearm after one second leaves causal coverage at 35.5% and 51.9%. A longer timer is not the same thing as trusting the match.

**C. Enroll the voices the cosine never reaches.** That bucket is 82 September seconds and 0 October seconds on this oracle inventory. The injury desk is in it. Ryan Fitzpatrick is on the October labels and is not in this cast. Four enrollment clips are songs (`e0101`, `e0112`, `e0116`, `e0124`). Neither fact was traced to a specific mute in this run. They stay hypotheses.

**D. Let announcer-voiced reads play.** That removes 137 and 48 seconds from the false-mute total and removes nothing from gold commercial coverage, because gold already calls those reads program. Inside gold commercials, 203 October seconds and 44 September seconds contain a 0.25 window. That is the advertising this cosine can give back if every such second is protected. A 0.55 cut of this same cosine covers 6 and 3 of those commercial seconds. It is not the live booth similarity, and it would drop matches this diagnosis is using.

## Cases

Clips are the listens already cut for NFL75_PROTECT_001. The timeline on each row is in `episodes.jsonl`.

Genuine programming, longest first. The mean at the open is above 0.163 on every one of these.

| Tape | Span | Seconds | Cosine | What authorized the mute |
| --- | ---: | ---: | --- | --- |
| September | 3874–3907 | 31 | not in the opening second; a 0.25 match is in the surrounding five | Mean 0.40. Desk talk, other games. |
| September | 7489–7515 | 26 | 0.67 Clarissa Thompson at the open | Mean 0.40. The code does not read it. Tour, then the anthem. |
| September | 5031–5059 | 26 | 0.53 Clarissa Thompson at the open | Mean 0.66. Play call. |
| October | 9453–9480 | 25 | not in the opening second | Mean 0.92. Cowboys desk. |
| September | 6266–6292 | 25 | peak 0.18 on the whole cut | Mean 0.25. Injury desk. The cosine never arrives. |
| September | 6723–6747 | 23 | not in the opening second | Mean 0.45. Other-game desk. |
| September | 6832–6854 | 22 | 0.11 at the open | Mean 0.65. Bumper. No person was named. |
| September | 6318–6341 | 22 | not in the opening second | Mean 0.36. Locker-room report. |
| October | 1744–1764 | 19 | not in the opening second | Mean 1.48. Feature. |
| October | 9803–9822 | 19 | not in the opening second | Mean 0.32. Nightcap. A sponsor tag, then the Buccaneers. |

The dropped pass is shorter than these ten and belongs with them. October 9156–9169, 12 seconds, mean 0.55, opening cosine 0.14, peak 0.70 inside the cut. Clip `clips/hush_20261008_205100/064.wav`.

Commercial failures, causal clock. No break is wholly missed.

| Tape | Break | Failure | Seconds | Mean at the boundary |
| --- | ---: | --- | ---: | ---: |
| September | 6854–7020 | return | 83.6 | 1.66 at the gold end |
| October | 7169–7293 | return | 37.6 | −0.68 at the gold start; the tail is after the end |
| September | 6028–6181 | return | 28.3 | 3.08 at the gold end |
| October | 140–377 | return | 28.1 | 5.28 at the gold end. The break itself was covered from the start. |
| October | 9605–9754 | return | 23.9 | 1.25 |
| September | 5355–5519 | start | 17.3 late | −3.56 at the gold start, and the mean does cross inside the break |
| October | 1003–1125 | start | 8.8 late | −5.17. A 0.46 cosine is also present. The mean is what is cold. |
| September | opening break | start | 12.4 late | no mean yet |
| October | 1973–2006 | start | 6.0 late | −6.87 |
| October | 8137–8176 | start | 5.4 late | −4.21 |

Five holds the one-second veto cleared. Each had a fresh match, and the veto removed the episode.

| Tape | Span | Seconds | Match | Heard |
| --- | ---: | ---: | --- | --- |
| September | 3692 | 11 | 0.45 Herbstreit | Packers rushing yards |
| October | 8352 | 8 | 0.42 Herbstreit | Clock and the two-point try |
| October | 4769 | 7 | 0.76 Herbstreit | "a matter of time until it clicks" |
| October | 3304 | 6 | 0.47 Whitworth | Getting the player back in |
| October | 8179 | 6 | 0.70 Michaels | Second and four |

Five breaks the unprotected mean covered from the start, with the return tail under a second on the oracle clock.

| Tape | Break | Length |
| --- | ---: | ---: |
| October | 140–377 | 237s |
| September | 6854–7020 | 166s |
| September | 4337–4493 | 156s |
| October | 3025–3178 | 153s |
| September | 6029–6181 | 152s |

The 237-second October break and the 166-second September break are also on the late-return list. Oracle coverage of the ad is complete. The causal tail after the gold end is the failure.

## What to do, and what not to ship

1. **Use the match the mean already ignores.** This is the state machine, not a new speaker model. The on-time matches plus the matches in the surrounding five seconds are 406 and 271 genuine seconds. The measured one-second version of this idea cuts hidden time and spends about five coverage points on October and two on September, then the mean resumes. Complexity is low because the veto exists. Shipping that one-second rule as it stands leaves the pause problem and splits episodes.

2. **Treat a short gap after a match as a pause.** Nineteen October episodes and nine September episodes open after a 0.25 match in the prior five seconds and no match in the opening second. A blind five-second hold already showed the cost of ignoring that distinction: 399 and 100 commercial seconds. The experiment has to separate "the window ended" from "the broadcast went to a commercial." Complexity is still the state machine. The coverage cost is the thing to measure, not to assume from the blind hold.

3. **Enroll the September voices that stay under 0.25.** That is 82 seconds and seven episodes, including the injury desk at a peak of 0.18. October does not have this bucket. Coverage risk is the chance those voices also appear inside gold ads, which this inventory did not find because the cosine never matched them. Complexity is labeling. The four song clips in the current prototype get inspected before any new clip is added. Fitzpatrick stays a hypothesis until a window of his is actually scored.

Do not raise this cosine to 0.55 to imitate the live booth. On this embedding that cut keeps 6 and 3 commercial seconds and would discard matches between 0.25 and 0.55 that this file is using. Do not add a model, a GPU, a sports feed, an antenna, or a video path for these episodes. The embedding that explains them is already on disk.

## Next experiment

**OHUSH_PAUSE_TRUST_001.** Keep the frozen mean and the frozen 0.25 cosine. After a matching window, hold protection across a predeclared gap and do not reopen while that hold is up. Score the gap lengths that this inventory already points at, including the five-second neighborhood above. Report causal commercial seconds given back, the dropped pass at 9156, and the injury desk at 6266. The injury desk is the control that a pause rule must not claim, because its cosine never reaches 0.25. Any figure that deletes a whole episode after the fact is an oracle ceiling. Do not deploy the rule. Do not enroll a new voice in that same run.
