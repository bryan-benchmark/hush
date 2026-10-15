# FIRST PRINCIPLES BROADCAST V2 — Batch A

Batch A measured three sources separately: millisecond production cuts, whether a television-timeout feed can be synced to the optical audio, and whether announcers sign off before a commercial. They were not combined into a mute policy. No live output was changed. Holdouts stayed closed. Gold and the frozen DSP and CNN14 results were not refit.

| Question | Answer | Status |
| --- | --- | --- |
| 1. Do subsecond production transitions occur consistently at commercial boundaries? | A 10 ms frame at or below −60 dB sits within ±0.5 s of 103 of 136 football starts. The minimum is not a brief hole that recovers. The causal 10–200 ms rule credits 4 of 136 starts within 1 second. | Level change: supported. Brief recoverable cut: refuted |
| 2. How often do those cuts occur in ordinary football, RedZone, and inside ads? | At the 40 ms short-dip rule: 134 football program episodes per hour, 4 on RedZone, 116 inside pod interiors, 491 on scripted Hulu program. | Measured |
| 3. Can we detect real NFL `tv_timeout` events from an authorized feed? | Sportradar documents the event. None were retrieved. The public 2026 play-by-play file has team timeouts and no `tv_timeout`. | Not measured |
| 4. Can those events be synchronized to viewer audio? | No mapping was built. The file start was not treated as the field clock. | Not measured |
| 5. How much advance warning do announcer handoffs provide? | A frozen sign-off phrase hits 12 of 133 football starts, 0 of 135 program controls, and 0 of 40 RedZone windows. Median automatic lead 6.1 s. Ten of the twelve transcripts are intelligible; six are one Monday game. | Supported as a sparse cue |
| 6. Do quarter, time remaining, and prior commercial inventory improve the probability of a break? | The inventory model was not fit. In the 20 s before a start, quarter words are as common as in program controls, and a digit clock appears in 0 windows. The rulebook names a designated count and does not give the number. | Not measured |
| 7. Which sources contribute unique boundaries? | The 40 ms rule marks 4 starts within 1 s. The sign-off marks 12, including 5 starts with no DSP episode within 3 s. The timeout feed contributed none. | Measured for audio; feed not measured |
| 8. What is the lowest-compute architecture the results support? | Both measurements ran on CPU. Neither is an always-on mute. A phrase check is the only Batch A signal with a clean control count, and it covers about one start in eleven. | Measured |
| 9. What still requires speaker identity or a trained audio model? | Commercial ends: the 40 ms rule credits 0 of 136 within 1 s. Unseen ads and unsigned breaks remain. No booth file was used as identity. | Open |
| 10. Next experiment | Verified announcer reappearance at the commercial end. | Recommendation |

## Evidence matrix

| Claim | Status |
| --- | --- |
| A 10–200 ms dip that recovers distinguishes NFL commercial starts | Refuted |
| Boundaries are deeper, in a ±0.25 s description, than ordinary football windows | Supported |
| The published −60 dB cut, with a short-and-recover filter, is specific and sensitive | Refuted on sensitivity. Football false episodes fall to 18 per hour and RedZone to 0, with 3 of 136 starts credited within 1 s |
| RedZone produces these short dips about as often as a football game | Refuted. RedZone is 4 per hour; football program is 134 |
| The same short dip is a universal television rule, including Hulu | Refuted. Scripted program is 491 per hour |
| Sportradar's API can emit `tv_timeout` | Supported as documentation only |
| That event was observed on these recordings and aligned to the audio | Not measured |
| Speech in the start neighborhood reconstructs the game clock | Refuted for the windows that were transcribed |
| A frozen sign-off phrase precedes some NFL commercials and was absent from the matched controls | Supported |
| That phrase covers most breaks, or scripted shows, or the return | Refuted |
| Prior commercial inventory changes the probability of the next break | Not measured |
| A fused state machine improves mute accuracy | Not measured |

## What Batch A changes

The 2018 silence method is the wrong shape for these optical NFL recordings. Ramires, Cocharro, and Davies mark 40 ms frames at or below −60 dB and then keep silences that are short and surrounded by loud audio. Their regression was not reproduced, because the coefficients are not published and fitting them here would train on this gold. The fixed −60 dB cut plus a 10–200 ms recovery rule credits 3 of 136 football starts within 1 second.

The relative rule that was frozen alongside it, an 18 dB drop against the previous 2 seconds with the same recovery requirement, credits 4 of 136 within 1 second and still produces 134 episodes per hour of football program. The frozen one-second DSP scan produces about 215. The research gate asked for a fivefold cut, to 43 per hour, while keeping at least 0.25 recall within 1 second. The gate is not met. Dropping the 200 ms cap and scoring a 500 ms frame instead raises recall to 65 of 136 within 1 second and leaves 87 football episodes per hour and 196 on RedZone. A longer energy drop is a coarser cousin of the DSP scan, not a millisecond edit.

The descriptive contrast is still there. The median drop from the preceding 2 seconds into the ±0.25 seconds around a football start is 42 dB once seven digital-zero frames on Oct 8 are set aside, against 6.6 dB in program windows far from pods. The scanner rejects that shape because the next frame usually does not jump back. At 40 ms it discarded 10,133 runs for failing recovery and 4,389 for lasting longer than 200 ms. A transition into a quieter bed is not a hole with loud audio on both sides.

Details, per-scale tables, and the gate arithmetic are in [EXP_01_MICRO_PRODUCTION_CUTS/REPORT.md](EXP_01_MICRO_PRODUCTION_CUTS/REPORT.md).

The television-timeout feed remains a documented possibility and an empty measurement. Sportradar lists `tv_timeout` and describes a 3-second refresh, with initial play results typically 5 to 10 seconds behind the broadcast. No key was purchased, no payload was stored, and no offset between viewer audio and the feed was estimated. The public 2026 play-by-play release does not contain the television-timeout field, so team timeouts in that file were not treated as commercials. Details are in [EXP_02_GAME_STATE/REPORT.md](EXP_02_GAME_STATE/REPORT.md).

Announcers do sometimes close the segment. On a phrase list frozen in advance, 12 of 133 football starts contain a sign-off before the label, and 0 of 135 matched program windows do. Five of those twelve are starts the DSP scan did not flag within 3 seconds. The lead is often a few seconds, six of the hits are one game, and scripted starts contribute zero. "Two-minute warning" also shows up on RedZone, which has no commercial in the scored span, so that phrase is not a commercial. Details and the twelve transcripts are in [EXP_03_HANDOFF_LANGUAGE/REPORT.md](EXP_03_HANDOFF_LANGUAGE/REPORT.md).

## Next experiment

Verified announcer reappearance when a commercial ends.

Batch A did not find a production cut that marks the return: the operating short-dip rule credits none of the 136 football ends within 1 second. The sign-off phrases are about leaving, not about the game being back. A purchased `tv_timeout` feed might still be worth a quote, and it is not the next measurement until that access is approved. Another recovery threshold on the same short dip is not justified. The 500 ms level drop was already scored, and it did not clear the false-episode gate.

The return check should use speech from program regions, with enrollment excerpts checked independently. `.booth.json` stays unused as identity. No mute rule comes out of that experiment until it is measured on its own.
