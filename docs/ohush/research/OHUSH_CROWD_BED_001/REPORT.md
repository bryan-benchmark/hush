# Crowd-bed and acoustic patterns — second pass

Re-mined from raw windows with stereo, a gold-ad filter, and more samples. Chili’s and Amex are reviewed spots, not gold commercials; they are not in the ad column here. Rows: `acoustic_receipts/patterns.json`.

## Pattern 1 — live vs desk: quiet-crowd is clean

| Group | quiet-crowd | quiet-low |
| --- | --- | --- |
| Live play (n=7) | 0.622–0.901 | 0.001–0.176 |
| Desk mutes (n=9) | 0.186–0.591 | 0.030–0.666 |

Zero overlap on quiet-crowd. As quiet-crowd falls on the desks, quiet-low rises (Odell mid: crowd 0.186, low 0.666). Dry desks are bass-heavy in the quiet frames. Live is a midband floor.

## Pattern 2 — live vs gold ads: centroid is clean in this set

| Group | centroid Hz | quiet-crowd |
| --- | --- | --- |
| Live | 878–1558 | 0.62–0.90 |
| Gold ads (n=5) | 168–686 | 0.25–0.63 |

Centroid accuracy 100% on these rows. Quiet-crowd alone is 91.7% because `ad_hot24` sits at 0.627, just above the live floor.

## Pattern 3 — desk vs gold ads: no clean single axis yet

Best single-feature accuracy in the miner: 0.857 (modulation / crest). No feature has zero overlap. Whitworth is the boundary: crowd 0.591, centroid 1029 (live-like), frozen p still 0.97.

## Correction to the first pass

The first pass treated Chili’s and Amex as ads. Gold does not. That mixed reviewed spots into the ad distribution and made “crowd cannot separate desk from ads” sound more absolute than the gold-ad rows support. Crowd **does** separate live success from desk failure. Desk versus gold ad remains the open acoustic cut.
