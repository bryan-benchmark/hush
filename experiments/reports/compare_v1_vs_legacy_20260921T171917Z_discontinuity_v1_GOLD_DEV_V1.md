# V1 vs legacy_v0 — frozen GOLD_DEV_V1

Does temporal break structure explain enough of the current errors that this should become the next detector architecture?

**Verdict:** PROMISING — iterate with param receipts, do not abandon

## Scores (±2s collar)

| | legacy_v0 | discontinuity_v1 | Δ |
|---|---:|---:|---:|
| TP | 1 | 3 | +2 |
| FP | 45 | 46 | +1 |
| FN | 14 | 12 | -2 |
| Recall | 6.7% | 20.0% | |
| Precision | 2.2% | 6.1% | |
| Proposals in coverage | 46 | 49 | |
| FPs inside a true break | 20 | 12 | |

## Change by baseline FN cause

- **evidence/weak_boundary**: still_fn=6
- **matched_±2s**: still_tp=1
- **onset_timing**: still_fn=6
- **selection/top_k**: improved_fn_to_tp=2

## Each gold commercial

- `166.6` · evidence/weak_boundary · **still_fn** · legacy Δ=-70.515 · v1 Δ=-44.265
- `512.9` · onset_timing · **still_fn** · legacy Δ=-21.98 · v1 Δ=29.395
- `1029.7` · onset_timing · **still_fn** · legacy Δ=8.336 · v1 Δ=58.336
- `1243.2` · evidence/weak_boundary · **still_fn** · legacy Δ=39.081 · v1 Δ=-47.669
- `1538.9` · selection/top_k · **improved_fn_to_tp** · legacy Δ=-96.732 · v1 Δ=-0.232
- `2072.1` · selection/top_k · **improved_fn_to_tp** · legacy Δ=47.638 · v1 Δ=0.763
- `2658.5` · matched_±2s · **still_tp** · legacy Δ=1.841 · v1 Δ=-0.409
- `3180.1` · onset_timing · **still_fn** · legacy Δ=-8.982 · v1 Δ=52.518
- `3649.1` · evidence/weak_boundary · **still_fn** · legacy Δ=134.91 · v1 Δ=-32.59
- `4244.2` · onset_timing · **still_fn** · legacy Δ=22.634 · v1 Δ=-77.741
- `4543.8` · onset_timing · **still_fn** · legacy Δ=15.831 · v1 Δ=-10.919
- `5019.6` · evidence/weak_boundary · **still_fn** · legacy Δ=45.885 · v1 Δ=-24.24
- `5665.4` · evidence/weak_boundary · **still_fn** · legacy Δ=42.382 · v1 Δ=21.882
- `6344.6` · evidence/weak_boundary · **still_fn** · legacy Δ=35.241 · v1 Δ=39.991
- `6852.6` · onset_timing · **still_fn** · legacy Δ=2.686 · v1 Δ=-53.314
