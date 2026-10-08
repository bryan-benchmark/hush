# EXP004 result

Status: **measured, not closed**. Verdict: **negative for a precise commercial clock. Weak support only for a broad duration prior.** The 110–140 s pile is context, not a decision rule. Spec `exp004-v1` was written before this run's ledger was opened. The 15/30/60 and 60/90/120/150/180 clock, the ±3 s tolerance, and the peak listing were not moved after the durations were known. The apparent ~15 s spacing is the 12 s refractory, not a spot clock.

Session `hush_20260914_212529`, 0–6899 s. This ESPN recording is development data. A result here is not independent confirmation.

The run reads the frozen Exp003 embeddings. Nothing was re-embedded. The jump at time t is the distance between the 10 s window ending then and the 10 s window ending 10 s earlier. A listed cut is a rise above the 90th percentile of the prior 10 minutes, then the listing waits 12 s. That listing is not a mute rule. The frozen-program distances from Exp003b are read only for the return-clock check. No return threshold was fit.

## Internal cuts

The jump series has no commercial period in it. Its autocorrelation falls smoothly with lag. The value at 15 s is lower than the value at 10 s, and 30 s and 60 s are not peaks.

Listed cuts are more common inside pods than outside them. The median gap between cuts that sit inside the same pod is 16 s. The median gap between cuts that sit outside every pod is 34 s.

They are not on a 15/30/60 grid. Of 50 gaps inside a single pod, 29 fall within 3 s of 15, 6 within 3 s of 30, and 2 within 3 s of 60. Outside pods, those counts are 15, 3, and 2. The near-15 count is mostly the 12 s refractory: those gaps pile up from 12 s to 18 s, which is the soonest the listing is allowed to fire again. Cuts inside a pod are also no closer to a multiple of 15 s from the pod start than a uniform scatter would be. The median absolute residual is 4.6 s. A uniform residual on a 15 s grid has median 3.75 s.

## Pod length

Three of the 14 complete pods fall within 3 s of 60, 90, 120, 150, or 180. They last 121.9, 121.9, and 120.3 s. The fourteen durations are 139, 122, 49, 65, 229, 135, 122, 110, 136, 135, 132, 138, 120, and 126 s. Eleven of them sit between 110 and 140 s. The last pod is still open at the analysis end.

A coarse pile near two minutes is visible. The pre-registered ±3 s clock mostly misses it. The tolerance was not widened.

## Return clock

The largest 10 s drop in frozen-program distance, during the 180 s after a commercial start, lands within 3 s of 60, 90, 120, or 150 on 2 of 14 breaks. A time drawn uniformly in that window would do so about 14% of the time, and 2 of 14 is that rate. The median distance to the nearest of those four marks is 6.4 s, compared with about 11 s for a uniform draw.

The same drop measured from the start of a program stretch has a median clock error of 44 s. Those windows open where the frozen distance is already falling back toward the program, so the largest drop sits near the beginning, far from 60. Several of the drops after a break start are the return itself, so their timing restates the pod length.

This was not turned into a PLAY rule.

## Reading

On this recording, a 15/30/60 internal clock is not there in the embedding jumps, and whole pods are only loosely two minutes long. The clock has not earned a place as a boundary detector. It remains a prior that could corroborate a return once some other signal already says a break is underway. That use was not demonstrated by the ±3 s hits.

The constants were not changed. Prime football, linear scripted, and ad-supported streaming scripted are still the measurements that would count as confirmation.

## Where the numbers live

- Unlabeled plot: `hush_20260914_212529/temporal.png`
- Labeled plot: `hush_20260914_212529/plots_labeled/temporal.png`
- Listed cuts: `peaks.json`
- Per-pod table: `overlay_pods.csv`
- Drop times: `overlay_drops.csv`
- Counts: `overlay_summary.json`
