# EXP003b result

Status: **measured, not closed**. Spec `exp003b-v1` was written before this run's ledger was opened. The trigger was not moved after the freeze times were known.

Session `hush_20260914_212529`, 0–6899 s. This ESPN recording is development data. A result here is not independent confirmation.

The run reads the frozen Exp003 embeddings and distances. Nothing was re-embedded. Exp002, commercial timing, transcripts, and a mute rule were not added.

## The rule that was tested

A freeze fires when the current Exp003 distance exceeds the 99th percentile of its own prior 10 minutes of defined scores, on 3 of 5 consecutive seconds. At least 5 minutes of score history is required. After a freeze, the next one waits 60 seconds.

The snapshot is the embeddings whose windows end in (T−210 s, T−30 s]. The last 30 seconds before the trigger are left out. Two scores are kept: the original adaptive distance, and the distance to that frozen cloud.

The break at 167 s cannot produce a freeze. Defined scores begin at 80 s, and the rule refuses to fire until five minutes of them exist. That exclusion was part of the pre-registration.

## What the trigger did

Ten freezes: 522, 1639, 1831, 2078, 2664, 3823, 4552, 5667, 5727, 6345 s.

Six of the 15 commercial starts have a freeze in the next 60 seconds: the breaks at 513, 2072, 2659, 4544, 5665, and 6345 s. Latencies are about 9, 6, 5, 8, 2, and 0.4 s. Counting only the 14 starts that occur after the history requirement, that is 6 of 14.

Two freezes fall outside every pod and outside that 60-second start window: 1831 s and 3823 s. Against program time, that is 1.4 per hour. Both are in the minute after a pod ends, not in the middle of a long stretch of play. Two further freezes are inside a pod but later than 60 seconds after its start (1639 s, and a second freeze at 5727 s inside a pod that had already frozen).

## The two distances

Where a snapshot exists, frozen-program distance separates pods from later play more cleanly than the adaptive score does. The median frozen distance is 0.289 inside pods and 0.091 outside them.

On several pods the adaptive distance has already come back down by the last 30 seconds, while the frozen distance is still high. Examples, last 30 seconds of the pod, adaptive then frozen: break at 2659 s is 0.21 then 0.37; at 3180 s, 0.16 then 0.32; at 3649 s, 0.13 then 0.34; at 5020 s, 0.19 then 0.34; at 6345 s, 0.17 then 0.34. That is the failure mode Exp003 recorded, and the frozen snapshot keeps it visible.

It is not uniform. The pod at 4244 s stays near 0.10 on the frozen score, about the same as its own snapshot's self-distance. That snapshot does not see the break.

## Return

A return was counted when the frozen distance fell to the snapshot's own median self-distance, within 120 seconds after the pod ended. Eleven breaks do that. One of those eleven, the pod at 4244 s, never rose above that line, so the clock starts already satisfied. Two breaks stay above it for the whole 120 seconds (1243 s and 3649 s). The last break ends at the analysis boundary.

The first 30 seconds after the end is mixed. A few returns are already down: the break at 513 s has a post-30 median of 0.047 against a late-pod 0.285, and the lowest point in that 30 seconds is below the 1st percentile of all frozen scores. The break at 5020 s drops from a late-pod 0.341 to a post-30 median of 0.090. Several others are only partly down in that first half-minute (2659, 4544, 5665, 6345) and touch the snapshot's own level between about 20 and 60 seconds. The minimum in the 30 seconds after a real return is often in the lower third of all frozen scores, and sometimes in the bottom tenth. Ordinary program medians already sit near 0.09, so a low point by itself is not rare.

## Reading

Preserving the pre-departure cloud does make some program returns visible, and it keeps the pod looking unlike the program after the adaptive score has relaxed. On this recording it does not yet make return a reliable event. The trigger misses most starts, two returns stay far from the frozen cloud for two minutes, and the first 10–30 seconds after the end are often still elevated.

The constants were not changed. The status stays measured, not closed. The 99th-percentile trigger is not the way a break will be initiated, and it will not be rescued on this game. The useful part is the frozen cloud as memory of the program. Return to that snapshot is not an unmute event. No return threshold will be fit here.

Prime football, linear scripted, and ad-supported streaming scripted are still the measurements that would count as confirmation.

## Where the numbers live

- Unlabeled plot: `hush_20260914_212529/frozen_program.png`
- Labeled plot: `hush_20260914_212529/plots_labeled/frozen_program.png`
- Freeze list: `freezes.json`
- Per-break table: `overlay_breaks.csv`
- Counts: `overlay_summary.json`
