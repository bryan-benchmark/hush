# EXP003 result

Status: **closed**. Spec `exp003-v1` is frozen. The 10 s window, 1 s hop, and 180 s memory were not changed after labels were opened. The overlay reads the already-computed program-cloud scores. Nothing was rescored.

Session `hush_20260914_212529`, 0–6899 s, ESPN Monday Night Football. One recording. PANNs CNN14 is used only as an L2-normalized penultimate embedding. The AudioSet class head is not used. There is no commercial classifier.

## Verdict

**Strong for detecting departure from the recent program sound-world. Negative for return with the adaptive reference as currently defined.**

A generic pretrained audio embedding, scored only against the previous three minutes of this broadcast, treats commercial starts as departures from the preceding program. That has earned a place as candidate evidence. It is not safe to mute on by itself. The same adaptive score has not earned a place as a return signal.

## Departure

All 15 commercial starts have a higher median distance in the 30 s after the start than in the 30 s before. Fourteen of the 15 peaks in that post-start window sit at or above the 94th percentile of every defined score. The weak start is the break at 1539 s: the median barely rises, and the peak is at the 81st percentile.

Latency from the start to the highest score in the next 30 s runs from about 2 s to 28 s. The middle of that list is near 12 s. The score at time t is the preceding 10 s of audio, so a latency near 2 s is still mostly pre-break sound.

## Specificity

Pod scores sit higher than program scores. The pod median is 0.213 and the program median is 0.092. The distributions overlap.

Of the 20 largest peaks, kept 45 s apart, 17 fall inside a pod or within 30 s of a start. Relative to time in each region, that is about 12× as dense. Of the 50 largest, 30 do, about 3× as dense. The top of the list is the specific part. The false peaks that remain are too many to mute on. They are few enough, at the very top, to keep as a major feature.

## Return

The reference is the previous 180 s, so it adapts toward whatever has been playing, including a commercial pod. A return to football can therefore look anomalous, and a long pod can stop looking anomalous. That is what the score did.

On 11 of the 14 ends with a full 30 s of audio after them, the median in that 30 s is flat or lower than the last 30 s of the pod. Three ends rise. This was not turned into a PLAY rule.

Many pods are highest in the first 20 s and lower by 40–60 s. Some stay elevated. That is the adaptation the 180 s memory was expected to produce. It was recorded and not used to change `exp003-v1`.

Preserving the pre-departure cloud and comparing later audio to that frozen snapshot is a different experiment. It is not a retune of this one.

## Where the numbers live

- Unlabeled plots: `hush_20260914_212529/program_distance.png`, `program_distance_hist.png`
- Labeled plots: `hush_20260914_212529/plots_labeled/`
- Per-start table: `overlay_starts.csv`
- Per-end table: `overlay_returns.csv`
- Peak listing: `overlay_events.csv`
- Counts: `overlay_summary.json`

Do not tune `exp003-v1` against this ledger. All of Exp001, Exp002, and Exp003 are still this one ESPN game.
