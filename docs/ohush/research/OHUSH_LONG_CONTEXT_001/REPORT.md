# Longer causal context

The published frozen head already hears 7.75 seconds: sixteen embeddings, each four seconds long, stepped every quarter-second. This run changes only that history, to 30.0 seconds (105 embeddings), still ending at the decision. The encoder, the training games, the controller, and the frozen checkpoint are the ones already published. Prime is a regression score on the original gold.

## Listener score

| | Frozen, 7.75 s | Long context, 30 s |
| --- | ---: | ---: |
| Commercial coverage | 86.0% | 95.6% |
| Commercial seconds covered | 3,702 | 4,115 |
| Program seconds covered | 495 | 666 |
| Interruptions per hour | 13.6 | 14.2 |
| Longest mute | 60.2 s | 71.2 s |
| Named desk spans still covered | 288 s | 154 s |

The named-desk total falls by 134 seconds. The television gets worse. Program seconds silenced rise by 171, and the longest mute grows from 60 seconds to 71.

## The three studio scenes

P(commercial) at the start, middle, and end. The 30-second history is fully available at every one of these stamps.

| Scene | Model | Start | Middle | End |
| --- | --- | ---: | ---: | ---: |
| Odell, 60 s | 7.75 s | 0.97 | 0.97 | 0.42 |
| Odell, 60 s | 30 s | 0.61 | 1.00 | 1.00 |
| Whitworth, 30 s | 7.75 s | 0.95 | 0.97 | 0.37 |
| Whitworth, 30 s | 30 s | 0.01 | 1.00 | 0.99 |
| Palmer, 27 s | 7.75 s | 0.98 | 1.00 | 0.35 |
| Palmer, 27 s | 30 s | 0.99 | 1.00 | 0.92 |

At the first moment of Odell and Whitworth, the longer window still contains the show that came before, and the probability drops. By the middle, the window is the discussion itself and the probability is 1.00. It stays there. Palmer, which begins as the previous break ends, is 0.99 from the first sample through the report. Hearing more of the studio audio makes the classifier more sure it is a commercial.

The Odell mute moves from 7035–7095 (60 s) to 7041–7112 (71 s). Whitworth moves from 30 seconds to 36. Palmer stays the whole report.

## What this says

Thirty seconds is long enough to contain the discussion the model is muting. The classification does not turn around as that discussion accumulates. Another longer window of this same embedding would be more of the audio that already scores 1.00. The frozen 7.75-second head remains the champion.

Reviewed label boundaries stay in `OHUSH_STUDIO_HEAD_001/reviewed_boundaries.json`. They are not part of this comparison.

## Next experiment

One causal transcript test, on clips already in hand. At the middle of Odell, Whitworth, and Palmer, transcribe only the 30 seconds that end at that moment. Do the same for three live-play windows the frozen head leaves alone, three commercials it covers, and the State Farm in-show sponsorship. Ask a text model, from those words alone, whether the viewer is hearing the show or a standalone spot. No new audio encoder, no threshold search, no Prime retraining.

If the words mark the three desks as the show while this embedding marks them 1.00, the missing piece is speech meaning and the following build is a causal transcript beside the frozen acoustic score. If the words are ambiguous in that same window, stop and say so before building anything.
