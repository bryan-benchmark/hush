# Causal onset probe v1

Probe: `causal_onset_probe_v1` · transitions from `20260921T173219Z_discontinuity_v1_1`
Session `hush_20260914_212529` · gold `GOLD_DEV_V1`

Future evidence is **forbidden**. Features are current acoustics + past transition intensity only.

## Cohorts

- true_onset (transition within ±2s of gold IN): **13**
- program (outside breaks, not near OUT): **1091**
- inside_break (excluded from separation): 479
- near_return (excluded): 79

## Feature table — TRUE IN vs PROGRAM

| feature | true median | program median | median gap | sep/IQR | IQR overlap? |
|---|---:|---:|---:|---:|:---:|
| `past_rate_5s` | 0.000 | 0.200 | 0.200 | 4.00 | NO |
| `gap_from_prev_s` | 7.125 | 3.500 | 3.625 | 1.43 | NO |
| `jump_z` | 1.020 | 0.139 | 0.881 | 0.66 | yes |
| `past_n_30s` | 8.000 | 7.000 | 1.000 | 0.57 | yes |
| `past_rate_30s` | 0.267 | 0.233 | 0.033 | 0.57 | yes |
| `rms_db` | -24.386 | -22.959 | 1.426 | 0.34 | yes |
| `boundary_score` | 2.167 | 1.877 | 0.290 | 0.19 | yes |
| `flux_z` | 1.950 | 2.089 | 0.139 | 0.08 | yes |
| `near_silence` | 0.000 | 0.000 | 0.000 | 0.00 | yes |
| `silence_bonus` | 0.000 | 0.000 | 0.000 | 0.00 | yes |
| `past_rate_15s` | 0.200 | 0.200 | 0.000 | 0.00 | yes |
| `past_rate_60s` | 0.233 | 0.233 | 0.000 | 0.00 | yes |
| `past_strong_rate_5s` | 0.000 | 0.000 | 0.000 | 0.00 | yes |
| `past_strong_rate_15s` | 0.000 | 0.000 | 0.000 | 0.00 | yes |
| `past_strong_rate_30s` | 0.000 | 0.000 | 0.000 | 0.00 | yes |
| `past_strong_rate_60s` | 0.017 | 0.017 | 0.000 | 0.00 | yes |
| `past_silence_rate_15s` | 0.000 | 0.000 | 0.000 | 0.00 | yes |
| `past_silence_rate_30s` | 0.000 | 0.000 | 0.000 | 0.00 | yes |
| `past_silence_rate_60s` | 0.017 | 0.017 | 0.000 | 0.00 | yes |
| `past_strong_n_30s` | 0.000 | 0.000 | 0.000 | 0.00 | yes |

## Ranking probes (local ±90s, causal scores only)

For each gold IN: rank of the oracle nearest-transition among eligible local non-inside-break candidates.

### `boundary_only` — oracle ranked #1 for 2/15

| gold IN | oracle Δ | rank / n | top t |
|---:|---:|---:|---:|
| 166.6 | +2.360 | 5/20 | 96.125 |
| 512.9 | +1.895 | 17/20 | 490.875 |
| 1029.7 | -3.164 | 12/34 | 941.625 |
| 1243.2 | +2.081 | 8/29 | 1314.875 |
| 1538.9 | -0.232 | 4/26 | 1492.875 |
| 2072.1 | +0.763 | 4/20 | 2022.500 |
| 2658.5 | -0.409 | 5/20 | 2608.750 |
| 3180.1 | +0.143 | 11/22 | 3171.125 |
| 3649.1 | +0.535 | 5/23 | 3568.375 |
| 4244.2 | -0.241 | 15/24 | 4188.625 |
| 4543.8 | +1.456 | 1/20 | 4545.250 |
| 5019.6 | +0.510 | 1/20 | 5020.125 |
| 5665.4 | -0.243 | 19/24 | 5630.375 |
| 6344.6 | +5.366 | 22/26 | 6265.750 |
| 6852.6 | +0.186 | 15/26 | 6824.875 |

### `boundary_plus_silence` — oracle ranked #1 for 3/15

| gold IN | oracle Δ | rank / n | top t |
|---:|---:|---:|---:|
| 166.6 | +2.360 | 6/20 | 96.125 |
| 512.9 | +1.895 | 17/20 | 490.875 |
| 1029.7 | -3.164 | 12/34 | 1010.625 |
| 1243.2 | +2.081 | 9/29 | 1156.250 |
| 1538.9 | -0.232 | 4/26 | 1492.875 |
| 2072.1 | +0.763 | 2/20 | 2022.500 |
| 2658.5 | -0.409 | 2/20 | 2608.750 |
| 3180.1 | +0.143 | 11/22 | 3171.125 |
| 3649.1 | +0.535 | 5/23 | 3568.375 |
| 4244.2 | -0.241 | 15/24 | 4188.625 |
| 4543.8 | +1.456 | 1/20 | 4545.250 |
| 5019.6 | +0.510 | 2/20 | 4965.000 |
| 5665.4 | -0.243 | 19/24 | 5630.375 |
| 6344.6 | +5.366 | 1/26 | 6350.000 |
| 6852.6 | +0.186 | 1/26 | 6852.750 |

### `quiet_past` — oracle ranked #1 for 3/15

| gold IN | oracle Δ | rank / n | top t |
|---:|---:|---:|---:|
| 166.6 | +2.360 | 11/20 | 96.125 |
| 512.9 | +1.895 | 18/20 | 490.875 |
| 1029.7 | -3.164 | 23/34 | 1010.625 |
| 1243.2 | +2.081 | 17/29 | 1156.250 |
| 1538.9 | -0.232 | 2/26 | 1492.875 |
| 2072.1 | +0.763 | 2/20 | 2022.500 |
| 2658.5 | -0.409 | 2/20 | 2608.750 |
| 3180.1 | +0.143 | 13/22 | 3171.125 |
| 3649.1 | +0.535 | 5/23 | 3568.375 |
| 4244.2 | -0.241 | 15/24 | 4188.625 |
| 4543.8 | +1.456 | 1/20 | 4545.250 |
| 5019.6 | +0.510 | 1/20 | 5020.125 |
| 5665.4 | -0.243 | 19/24 | 5630.375 |
| 6344.6 | +5.366 | 4/26 | 6301.250 |
| 6852.6 | +0.186 | 1/26 | 6852.750 |

### `gap_and_quiet5` — oracle ranked #1 for 4/15

| gold IN | oracle Δ | rank / n | top t |
|---:|---:|---:|---:|
| 166.6 | +2.360 | 5/20 | 93.250 |
| 512.9 | +1.895 | 4/20 | 474.375 |
| 1029.7 | -3.164 | 34/34 | 992.000 |
| 1243.2 | +2.081 | 4/29 | 1180.750 |
| 1538.9 | -0.232 | 1/26 | 1538.625 |
| 2072.1 | +0.763 | 3/20 | 2022.500 |
| 2658.5 | -0.409 | 4/20 | 2631.375 |
| 3180.1 | +0.143 | 1/22 | 3180.250 |
| 3649.1 | +0.535 | 18/23 | 3608.125 |
| 4244.2 | -0.241 | 4/24 | 4157.500 |
| 4543.8 | +1.456 | 7/20 | 4505.375 |
| 5019.6 | +0.510 | 5/20 | 4984.625 |
| 5665.4 | -0.243 | 1/24 | 5665.125 |
| 6344.6 | +5.366 | 1/26 | 6350.000 |
| 6852.6 | +0.186 | 8/26 | 6773.000 |

### `handcrafted` — oracle ranked #1 for 2/15

| gold IN | oracle Δ | rank / n | top t |
|---:|---:|---:|---:|
| 166.6 | +2.360 | 18/20 | 96.125 |
| 512.9 | +1.895 | 19/20 | 490.875 |
| 1029.7 | -3.164 | 30/34 | 1010.625 |
| 1243.2 | +2.081 | 20/29 | 1156.250 |
| 1538.9 | -0.232 | 2/26 | 1492.875 |
| 2072.1 | +0.763 | 2/20 | 2022.500 |
| 2658.5 | -0.409 | 2/20 | 2608.750 |
| 3180.1 | +0.143 | 5/22 | 3171.125 |
| 3649.1 | +0.535 | 20/23 | 3616.500 |
| 4244.2 | -0.241 | 15/24 | 4188.625 |
| 4543.8 | +1.456 | 1/20 | 4545.250 |
| 5019.6 | +0.510 | 10/20 | 4984.625 |
| 5665.4 | -0.243 | 22/24 | 5630.375 |
| 6344.6 | +5.366 | 1/26 | 6350.000 |
| 6852.6 | +0.186 | 2/26 | 6814.375 |

## Verdict

WEAK_CAUSAL — population hints exist (2 non-overlapping/strong features: past_rate_5s, gap_from_prev_s), but best local ranking (`gap_and_quiet5`) is only 4/15 top-1. Handcrafted past+current evidence does not yet reliably identify which audible transition is the commercial IN. Probe further combinations before declaring another evidence channel mandatory.

## What this does / does not claim

- Does **not** claim a shipping causal detector.
- Does claim whether handcrafted past+current features contain enough information to prefer true INs over isolated program edits.
- V1.1 remains the offline teacher (future context allowed).
