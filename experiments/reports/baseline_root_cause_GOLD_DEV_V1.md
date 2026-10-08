# Root cause (truth frozen)

You already labeled commercials correctly. These rows explain **why the computer disagreed**, not whether your labels are wrong.

- Coverage: 0–6899s (~115 min)
- Truth: 15 commercials
- Score: TP 1 / FP 45 / FN 14
- Recall ±2s 6.7% · Precision ±2s 2.2%

## What the misses look like

- **evidence/weak_boundary**: 6
- **onset_timing**: 6
- **selection/top_k**: 2

## What the false alarms look like

- **fired_inside_break**: 20
- **isolated_over_trigger**: 18
- **near_program_return**: 5
- **near_break_wrong_onset**: 2

## Each commercial you marked

### FN #1 · your IN `166.6`
- Computer problem: **evidence/weak_boundary**
- best ±5s composite=2.48 at 169.0 (flux_z=1.9, jump_z=1.0)

### FN #2 · your IN `512.9`
- Computer problem: **onset_timing**
- detector keep nearby at 490.9 (Δ -22.0s). Fired on a different moment of the same transition cluster.

### FN #3 · your IN `1029.7`
- Computer problem: **onset_timing**
- detector keep nearby at 1038.0 (Δ +8.3s). Fired on a different moment of the same transition cluster.

### FN #4 · your IN `1243.2`
- Computer problem: **evidence/weak_boundary**
- best ±5s composite=3.37 at 1238.2 (flux_z=-0.3, jump_z=3.6)

### FN #5 · your IN `1538.9`
- Computer problem: **selection/top_k**
- boundary score 2.90 loses to chunk top_k floor 6.19

### FN #6 · your IN `2072.1`
- Computer problem: **selection/top_k**
- boundary score 4.60 loses to chunk top_k floor 6.43

### TP #7 · your IN `2658.5`
- Computer problem: **matched_±2s**
- keep Δ=+1.84s

### FN #8 · your IN `3180.1`
- Computer problem: **onset_timing**
- detector keep nearby at 3171.1 (Δ -9.0s). Fired on a different moment of the same transition cluster.

### FN #9 · your IN `3649.1`
- Computer problem: **evidence/weak_boundary**
- best ±5s composite=2.17 at 3649.6 (flux_z=1.5, jump_z=1.0)

### FN #10 · your IN `4244.2`
- Computer problem: **onset_timing**
- detector keep nearby at 4266.9 (Δ +22.6s). Fired on a different moment of the same transition cluster.

### FN #11 · your IN `4543.8`
- Computer problem: **onset_timing**
- detector keep nearby at 4559.6 (Δ +15.8s). Fired on a different moment of the same transition cluster.

### FN #12 · your IN `5019.6`
- Computer problem: **evidence/weak_boundary**
- best ±5s composite=3.94 at 5020.1 (flux_z=3.9, jump_z=1.0)

### FN #13 · your IN `5665.4`
- Computer problem: **evidence/weak_boundary**
- best ±5s composite=2.82 at 5668.6 (flux_z=1.2, jump_z=1.9)

### FN #14 · your IN `6344.6`
- Computer problem: **evidence/weak_boundary**
- best ±5s composite=0.63 at 6339.8 (flux_z=1.2, jump_z=-0.3)

### FN #15 · your IN `6852.6`
- Computer problem: **onset_timing**
- detector keep nearby at 6855.2 (Δ +2.7s). Fired on a different moment of the same transition cluster.


## What this means for v1

Do **not** collect another recording yet.

If timing-offset FNs dominate: the detector often hears the break but stamps the wrong instant — improve localization / peak picking, not ‘more ads data’.

If weak/missing evidence dominates: the acoustic cue at true IN is weak — need better features or a different evidence channel.

If top_k/min_gap dominates: the cue exists but selection throws it away — change selection policy.

FP mass (45 keeps vs 15 truth) means the detector is spraying — precision work matters as much as recall.
