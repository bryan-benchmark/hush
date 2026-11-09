# What the desk mute is missing

The frozen acoustic head stays the champion. Nothing here trains a model or changes the volume. Prime remains a regression read. The published score stays on the original gold: 86.0% commercial coverage, 495 program seconds muted, 13.63 false interruptions an hour, longest mute 60.2 seconds. Reviewed boundaries stay in `OHUSH_STUDIO_HEAD_001` and are not mixed into that score.

## What was already measured

The acoustic classifier takes frozen `frame_mn10` embeddings. It never receives a speaker name, a clock, or a transcript. More studio labels and a 30-second history were measured. Both made the television worse. The long mutes are high probabilities, not the hysteresis: most of the 495 seconds are already at or above 0.90 before the controller holds them.

Speech meaning was measured on 47 causal windows. The words in the Odell, highlight, injury, and live-play windows are the show, and the words in Chili's, DraftKings, and the Platinum pitch are commercials. `qwen2.5:3b` answered `unsure` on 44 of the 47. That result is in `OHUSH_SEMANTIC_001`. It is not a production transcript path.

Speaker enrollment was measured in other systems, not as an input to this classifier. `SHOW_ROSTER_001` kept Thursday Night Football's commercial rules on and used Al Michaels only. `OHUSH_VOICE_ID_001` separated Michaels and Herbstreit on labeled clips and showed that 0.25 also accepts other announcers, and that Tony Gonzalez can lose to Andrew Whitworth. `NFL75_PROTECT_001` tried the same cosine as a veto on the older rolling-mean detector. It was rejected: the September desk remained, and commercial coverage fell.

## Andrew Whitworth, on the existing scores

The mute at 7406.8–7436.2 seconds on September 24 is 29.4 seconds. The causal ECAPA cache from `NFL75_PROTECT_001` already has Whitworth enrolled before that minute. His clear clips on this tape end at 4749.8, 5302.2, 6400.1, 7209.0, and 7265.6 seconds. The song clip ends at 6843.2. The score at the desk uses only clips that have finished.

Inside that mute, Whitworth's cosine reaches 0.535 and clears 0.25 for 8.3 seconds. Clarissa Thompson reaches 0.713 and is the name on most of the hot windows. Some enrolled voice clears 0.25 for 26.1 of the 29.4 seconds. Hearing "Whitworth" would protect about 8 seconds. Hearing "anyone we enrolled" would protect most of the minute, under a name that is usually not his.

The other two studio failures are different people.

| Span | Length | Whitworth at or above 0.25 | Any enrolled voice at or above 0.25 |
| --- | ---: | ---: | ---: |
| Palmer report, 6180.7–6207.8 | 27.1 s | 0.0 s | 23.1 s, Clarissa Thompson, max 0.672 |
| Injury desk, 6267.8–6287.2 | 19.4 s | 0.0 s, max 0.180 | 0.0 s |
| Odell discussion, 7035.0–7095.2 | 60.2 s | 17.4 s | 40.7 s |
| Whitworth desk, 7406.8–7436.2 | 29.4 s | 8.3 s | 26.1 s |

Palmer is a missing input. Thompson is already recognized for 23 seconds while the acoustic score stays near 1.00, and that cosine is not given to the classifier. The injury desk is a recognition miss. Nobody enrolled clears the line. Odell is a partial cast match, 41 of 60 seconds, with Whitworth himself on 17.

The commercials next to these desks stay mostly quiet. Chili's, before Whitworth is enrolled, has no cast match. The break before Palmer has 8.0 seconds of cast match in 152 seconds. The break before Odell has 7.0 in 166. The break after Whitworth has 8.6 in 85. The October Amex spot has 4.0 seconds in 53. A Whitworth-only rule would not open those spots. A rule that plays audio whenever any enrolled voice clears 0.25 is a different trade, measured across the whole game below.

## Clock

Wall-clock time and elapsed time are the same axis on these files. Each recording has one start stamp. A viewer who joins late is not in the file.

On September 24 the desk mutes sit in the last half hour, and so do the commercials. From 105 to 120 minutes the frozen controller mutes 116.8 desk seconds and 139.2 commercial seconds. Turning protection on after 100 minutes of this file would release 235 seconds of program and 317 seconds of commercials the controller currently covers. On October 8 the same cut releases 17 seconds of program and 817 seconds of commercials. October's large program mute is earlier, 65 seconds in the 45–60 minute bin, around the Amex spot and the return to the show.

A known "postgame" flag was not available as a causal label, so it was not scored. It would still have to yield to the commercial detector. The last half hour contains both the desk and long ad breaks. Protecting the phase would play those breaks.

## What an existing cast match would spend

Overlap of a finished ECAPA window at or above 0.25 with audio the frozen controller is currently muting:

| Game | Program seconds under a cast match | Commercial seconds under a cast match |
| --- | ---: | ---: |
| September 24 | 191 | 34 |
| October 8 | 50 | 172 |
| Both | 241 | 207 |

September looks helpful. October gives back about 172 commercial seconds to reach about 50 program seconds. That is the wrong trade on the game where the booth is enrolled from a prior tape. These are overlaps, not a hysteresis replay. They are already enough to reject a cast-wide veto. No new speaker model is required to see it.

## Next test

Send the 47 saved transcripts to one stronger instruction model. No new audio, no new window, no live controller, no speaker training, no clock rule.

Keep going only if that model calls the Odell lines, the Palmer narration, the injury report, and the live play the show, and calls the Platinum, Chili's, and DraftKings lines commercials. The experiment after that is a veto beside the frozen acoustic mute, scored on both Prime games with the original gold, and the reviewed boundaries reported separately.

Stop if that model still calls the Platinum pitch a sponsorship, or still will not call the Odell lines the show.

A gain on these two games is a regression result. The confirmation is a new Prime broadcast, labeled before anyone reads the model's mistakes. The sealed tapes stay closed.
