# V1.1 vs V1 vs legacy — frozen GOLD_DEV_V1

Does separating episode detection from onset localization, with rolling intensity instead of linked clusters, explain more of the frozen errors?

**Verdict:** NO — next evidence hypothesis

## Scores (±2s)

| | legacy_v0 | v1 | v1.1 |
|---|---:|---:|---:|
| TP | 1 | 3 | 0 |
| FP | 45 | 46 | 49 |
| FN | 14 | 12 | 15 |
| Recall | 6.7% | 20.0% | 0.0% |
| Precision | 2.2% | 6.1% | 0.0% |
| Proposals | 46 | 49 | 49 |

## FP taxonomy (re-rooted)

| class | legacy | v1 | v1.1 |
|---|---:|---:|---:|
| inside_break | 20 | 12 | 11 |
| near_onset | 2 | 2 | 4 |
| near_return | 5 | 3 | 1 |
| isolated_program | 13 | 23 | 26 |
| session_edge | 0 | 1 | 0 |
| other | 5 | 5 | 7 |

## Change vs legacy by baseline cause

- **evidence/weak_boundary**: still_fn=6
- **matched_±2s**: regressed_tp_to_fn=1
- **onset_timing**: still_fn=6
- **selection/top_k**: still_fn=2

## Each gold commercial

- `166.6` · evidence/weak_boundary · legacyΔ=-70.515 v1Δ=-44.265 v11Δ=-4.39 · **still_fn** (vs v1: still_fn)
- `512.9` · onset_timing · legacyΔ=-21.98 v1Δ=29.395 v11Δ=-28.855 · **still_fn** (vs v1: still_fn)
- `1029.7` · onset_timing · legacyΔ=8.336 v1Δ=58.336 v11Δ=-21.414 · **still_fn** (vs v1: still_fn)
- `1243.2` · evidence/weak_boundary · legacyΔ=39.081 v1Δ=-47.669 v11Δ=5.956 · **still_fn** (vs v1: still_fn)
- `1538.9` · selection/top_k · legacyΔ=-96.732 v1Δ=-0.232 v11Δ=53.143 · **still_fn** (vs v1: regressed_tp_to_fn)
- `2072.1` · selection/top_k · legacyΔ=47.638 v1Δ=0.763 v11Δ=39.888 · **still_fn** (vs v1: regressed_tp_to_fn)
- `2658.5` · matched_±2s · legacyΔ=1.841 v1Δ=-0.409 v11Δ=48.841 · **regressed_tp_to_fn** (vs v1: regressed_tp_to_fn)
- `3180.1` · onset_timing · legacyΔ=-8.982 v1Δ=52.518 v11Δ=31.268 · **still_fn** (vs v1: still_fn)
- `3649.1` · evidence/weak_boundary · legacyΔ=134.91 v1Δ=-32.59 v11Δ=8.285 · **still_fn** (vs v1: still_fn)
- `4244.2` · onset_timing · legacyΔ=22.634 v1Δ=-77.741 v11Δ=-45.616 · **still_fn** (vs v1: still_fn)
- `4543.8` · onset_timing · legacyΔ=15.831 v1Δ=-10.919 v11Δ=39.706 · **still_fn** (vs v1: still_fn)
- `5019.6` · evidence/weak_boundary · legacyΔ=45.885 v1Δ=-24.24 v11Δ=25.51 · **still_fn** (vs v1: still_fn)
- `5665.4` · evidence/weak_boundary · legacyΔ=42.382 v1Δ=21.882 v11Δ=-34.993 · **still_fn** (vs v1: still_fn)
- `6344.6` · evidence/weak_boundary · legacyΔ=35.241 v1Δ=39.991 v11Δ=-8.509 · **still_fn** (vs v1: still_fn)
- `6852.6` · onset_timing · legacyΔ=2.686 v1Δ=-53.314 v11Δ=-79.564 · **still_fn** (vs v1: still_fn)
