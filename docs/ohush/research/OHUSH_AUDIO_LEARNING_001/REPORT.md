# OHUSH_AUDIO_LEARNING_001

Question: can PretrainedSED `frame_mn10`, trained on labeled football audio other than Prime, distinguish commercials from programming on the two labeled Prime games well enough to operate the volume better than the locked NBC logistic?

The live television path was not changed. Sealed sessions were not opened. The historical logistic lines were not moved.

## Split

Every split is a whole game. Prime tapes are absent from the fit and from controller selection. ESPN selects the controller and is not part of the product claim. These Prime tapes were inspected by earlier experiments; this model did not train on them, and there is still no sealed Prime exam.

Truth ledger sha256 `c658530b39099866229e9cefd20efe158e2b853890e0f982acffa0b75ecd7bd4`.

Train:

| Session | Day | Network | Show | Audio |
| --- | --- | --- | --- | --- |
| `hush_20260909_213047` | 2026-09-09 | NBC | football | yes |
| `hush_20260913_210542` | 2026-09-13 | NBC | football | yes |
| `hush_20260913_150934` | 2026-09-13 | FOX | RedZone | yes |
| `hush_20261011_135700` | 2026-10-11 | Cable | Sunday afternoon | yes |
| `hush_20261012_204200` | 2026-10-12 | Cable | Monday Night Football | yes |

Calibration (controller only):

| Session | Day | Network | Show | Audio |
| --- | --- | --- | --- | --- |
| `hush_20260914_212529` | 2026-09-14 | ESPN | football | yes |

Evaluation:

| Session | Day | Network | Show | Audio |
| --- | --- | --- | --- | --- |
| `hush_20261008_205100` | 2026-10-08 | Prime Video | Thursday Night Football | yes |
| `hush_20260924_220624` | 2026-09-24 | Prime Video | Prime football | yes |

Reserved, not used:

| Session | Day | Network | Show | Audio |
| --- | --- | --- | --- | --- |
| `hush_20261010_222400` | 2026-10-10 | Cable | Saturday football | yes |
| `hush_20261011_204300` | 2026-10-11 | Cable | Sunday night | yes |
| `hush_20260827_135935` | 2026-08-27 | Hulu | scripted | yes |
| `hush_20261007_220650` | 2026-10-07 | Hulu | scripted | yes |

Sealed, not opened:

- `hush_20260917_205513`
- `hush_20260920_200635`

## Method

Encoder: PretrainedSED `frame_mn10`, AudioSet-strong checkpoint `4a0fe320d536`.
Each decision at time t reads audio `[t-4, t)` right-aligned in a 10-second buffer. The front of the buffer is silence. Decisions land every 0.25s.
A GRU of 16 consecutive embeddings, hidden size 64, is the classification head. It is trained on the training games only. The calibration game chooses one setting from the predeclared hysteresis grid. Prime probabilities are scored after that choice.
Fine-tuning updates MobileNet features 12–16 on the training games, then the same head procedure is repeated on the new embeddings. Batch-norm stays on the published eval statistics.
Playback is `experiments.nfl75.score.playback_from_decisions`. The baseline is the published NBC logistic: cover after 10 seconds at or above the locked start line, return after 3 seconds at or below the locked clear-program line.

Assignment gate, experimental: commercial coverage ≥ 75%, false-mute episodes < 1 per program hour, longest false mute < 10s, and every cover returns to the game before the tape ends. The NFL75 scorer also requires hidden program under 5 seconds per program hour. Both are reported. A pass here is not a live installation.

## Are the probabilities separating the classes?

| Model | ESPN AUROC | Prime AUROC |
| --- | ---: | ---: |
| Frozen encoder | 0.979 | 0.972 |
| Fine-tuned tail | 0.983 | 0.975 |

AUROC uses labeled hops only. It is not the volume gate, and it was not used to pick the controller.

## Controller chosen on ESPN

| Model | On | Off | On streak | Off streak | ESPN coverage | ESPN false mutes / hour |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Frozen | 0.90 | 0.50 | 8 | 2 | 91.8% | 12.01 |
| Fine-tuned | 0.90 | 0.35 | 8 | 2 | 95.3% | 12.01 |

None of the 66 predeclared settings passes the assignment gate on ESPN. The quietest settings still produce 12.01 false-mute episodes per program hour, and those episodes remain when the cover threshold is 0.90. The mistakes are scored above the top of the grid, so moving the threshold inside this grid does not buy the false-mute cap.

## Prime games, same playback scorer

| Run | Ad coverage | False mutes / hour | Longest false mute | Recovery | Assignment gate |
| --- | ---: | ---: | ---: | ---: | --- |
| Always play | 0.0% | 0.00 | 0.00 | 100.0% | fail |
| Locked NBC logistic, 10s persist | 0.0% | 0.00 | 0.00 | 100.0% | fail |
| Frozen frame_mn10 | 86.0% | 13.63 | 60.25 | 100.0% | fail |
| Fine-tuned frame_mn10 | 91.9% | 16.25 | 74.50 | 100.0% | fail |

Hidden program on the two Prime games: frozen 494.9s (129.7s per program hour), fine-tuned 682.5s (178.9s per program hour). The NFL75 cap is 5s per program hour. Both fail it. Commercial seconds covered: frozen 3,702 of 4,306, fine-tuned 3,959 of 4,306.

### Frozen

- `hush_20261008_205100`: coverage 87.0%, false mutes/hour 11.54, longest false mute 55.00s, recovery 100.0%, median start delay 3.03s, median late return 0.02s, breaks never covered 0 of 23.
- `hush_20260924_220624`: coverage 84.4%, false mutes/hour 16.38, longest false mute 60.25s, recovery 100.0%, median start delay 0.91s, median late return 0.00s, breaks never covered 0 of 13.

### Fine-tuned

- `hush_20261008_205100`: coverage 93.8%, false mutes/hour 14.31, longest false mute 59.25s, recovery 100.0%, median start delay 2.23s, median late return 0.08s, breaks never covered 0 of 23.
- `hush_20260924_220624`: coverage 88.9%, false mutes/hour 18.80, longest false mute 74.50s, recovery 100.0%, median start delay 1.51s, median late return 0.04s, breaks never covered 0 of 13.

## Break bootstrap

Commercial breaks are the resample unit. Hops inside one break are not independent trials. The interval is a 95% bootstrap of second-weighted coverage, 2000 resamples.

- Frozen minus locked logistic: [82.4%, 89.5%] on 36 breaks. Frozen coverage [82.4%, 89.5%].
- Fine-tuned minus locked logistic: [89.6%, 94.2%] on 36 breaks. Fine-tuned coverage [89.6%, 94.2%].

## Plots and failure clips

Full-game plots overlay P(commercial) on the gold commercial spans. Orange bands are commercials.

- `frozen_hush_20261008_205100.png`
- `frozen_hush_20260924_220624.png`
- `finetuned_hush_20261008_205100.png`
- `finetuned_hush_20260924_220624.png`

Representative mistakes, with two seconds of context on either side:

- false_mute `hush_20261008_205100` 3388.0–3443.0s (55.0s) `C:\OHushData\gpu_lab\audio_learn\clips\frozen\hush_20261008_205100\false_mute_3388.0_3443.0.wav`
- false_mute `hush_20261008_205100` 1749.8–1760.8s (11.0s) `C:\OHushData\gpu_lab\audio_learn\clips\frozen\hush_20261008_205100\false_mute_1749.8_1760.8.wav`
- false_mute `hush_20261008_205100` 376.9–386.2s (9.3s) `C:\OHushData\gpu_lab\audio_learn\clips\frozen\hush_20261008_205100\false_mute_376.9_386.2.wav`
- false_mute `hush_20261008_205100` 3702.0–3709.2s (7.2s) `C:\OHushData\gpu_lab\audio_learn\clips\frozen\hush_20261008_205100\false_mute_3702.0_3709.2.wav`
- missed_commercial `hush_20261008_205100` 139.9–151.9s (62.8s) `C:\OHushData\gpu_lab\audio_learn\clips\frozen\hush_20261008_205100\missed_commercial_139.9_151.9.wav`
- missed_commercial `hush_20261008_205100` 2230.0–2242.0s (48.4s) `C:\OHushData\gpu_lab\audio_learn\clips\frozen\hush_20261008_205100\missed_commercial_2230.0_2242.0.wav`
- missed_commercial `hush_20261008_205100` 8802.6–8814.6s (32.3s) `C:\OHushData\gpu_lab\audio_learn\clips\frozen\hush_20261008_205100\missed_commercial_8802.6_8814.6.wav`
- missed_commercial `hush_20261008_205100` 3548.8–3560.8s (21.8s) `C:\OHushData\gpu_lab\audio_learn\clips\frozen\hush_20261008_205100\missed_commercial_3548.8_3560.8.wav`
- false_mute `hush_20260924_220624` 7035.0–7095.2s (60.2s) `C:\OHushData\gpu_lab\audio_learn\clips\frozen\hush_20260924_220624\false_mute_7035.0_7095.2.wav`
- false_mute `hush_20260924_220624` 2975.2–3007.2s (32.0s) `C:\OHushData\gpu_lab\audio_learn\clips\frozen\hush_20260924_220624\false_mute_2975.2_3007.2.wav`
- false_mute `hush_20260924_220624` 7406.8–7436.2s (29.5s) `C:\OHushData\gpu_lab\audio_learn\clips\frozen\hush_20260924_220624\false_mute_7406.8_7436.2.wav`
- false_mute `hush_20260924_220624` 6180.7–6207.8s (27.0s) `C:\OHushData\gpu_lab\audio_learn\clips\frozen\hush_20260924_220624\false_mute_6180.7_6207.8.wav`
- missed_commercial `hush_20260924_220624` 4337.2–4349.2s (55.1s) `C:\OHushData\gpu_lab\audio_learn\clips\frozen\hush_20260924_220624\missed_commercial_4337.2_4349.2.wav`
- missed_commercial `hush_20260924_220624` 6028.8–6040.8s (44.7s) `C:\OHushData\gpu_lab\audio_learn\clips\frozen\hush_20260924_220624\missed_commercial_6028.8_6040.8.wav`
- missed_commercial `hush_20260924_220624` 5354.8–5366.8s (33.4s) `C:\OHushData\gpu_lab\audio_learn\clips\frozen\hush_20260924_220624\missed_commercial_5354.8_5366.8.wav`
- missed_commercial `hush_20260924_220624` 6854.0–6866.0s (27.2s) `C:\OHushData\gpu_lab\audio_learn\clips\frozen\hush_20260924_220624\missed_commercial_6854.0_6866.0.wav`
- false_mute `hush_20261008_205100` 3385.0–3444.2s (59.2s) `C:\OHushData\gpu_lab\audio_learn\clips\finetuned\hush_20261008_205100\false_mute_3385.0_3444.2.wav`
- false_mute `hush_20261008_205100` 3178.4–3195.8s (17.3s) `C:\OHushData\gpu_lab\audio_learn\clips\finetuned\hush_20261008_205100\false_mute_3178.4_3195.8.wav`
- false_mute `hush_20261008_205100` 9769.8–9786.8s (16.9s) `C:\OHushData\gpu_lab\audio_learn\clips\finetuned\hush_20261008_205100\false_mute_9769.8_9786.8.wav`
- false_mute `hush_20261008_205100` 3267.5–3284.2s (16.8s) `C:\OHushData\gpu_lab\audio_learn\clips\finetuned\hush_20261008_205100\false_mute_3267.5_3284.2.wav`
- missed_commercial `hush_20261008_205100` 8802.6–8814.6s (19.8s) `C:\OHushData\gpu_lab\audio_learn\clips\finetuned\hush_20261008_205100\missed_commercial_8802.6_8814.6.wav`
- missed_commercial `hush_20261008_205100` 139.9–151.9s (19.2s) `C:\OHushData\gpu_lab\audio_learn\clips\finetuned\hush_20261008_205100\missed_commercial_139.9_151.9.wav`
- missed_commercial `hush_20261008_205100` 3548.8–3560.8s (17.0s) `C:\OHushData\gpu_lab\audio_learn\clips\finetuned\hush_20261008_205100\missed_commercial_3548.8_3560.8.wav`
- missed_commercial `hush_20261008_205100` 1973.0–1985.0s (16.2s) `C:\OHushData\gpu_lab\audio_learn\clips\finetuned\hush_20261008_205100\missed_commercial_1973.0_1985.0.wav`
- false_mute `hush_20260924_220624` 7021.8–7096.2s (74.5s) `C:\OHushData\gpu_lab\audio_learn\clips\finetuned\hush_20260924_220624\false_mute_7021.8_7096.2.wav`
- false_mute `hush_20260924_220624` 7133.2–7171.8s (38.5s) `C:\OHushData\gpu_lab\audio_learn\clips\finetuned\hush_20260924_220624\false_mute_7133.2_7171.8.wav`
- false_mute `hush_20260924_220624` 2976.5–3006.8s (30.2s) `C:\OHushData\gpu_lab\audio_learn\clips\finetuned\hush_20260924_220624\false_mute_2976.5_3006.8.wav`
- false_mute `hush_20260924_220624` 6180.7–6207.8s (27.0s) `C:\OHushData\gpu_lab\audio_learn\clips\finetuned\hush_20260924_220624\false_mute_6180.7_6207.8.wav`
- missed_commercial `hush_20260924_220624` 6028.8–6040.8s (34.0s) `C:\OHushData\gpu_lab\audio_learn\clips\finetuned\hush_20260924_220624\missed_commercial_6028.8_6040.8.wav`
- missed_commercial `hush_20260924_220624` 4337.2–4349.2s (30.6s) `C:\OHushData\gpu_lab\audio_learn\clips\finetuned\hush_20260924_220624\missed_commercial_4337.2_4349.2.wav`
- missed_commercial `hush_20260924_220624` 3496.4–3508.4s (25.8s) `C:\OHushData\gpu_lab\audio_learn\clips\finetuned\hush_20260924_220624\missed_commercial_3496.4_3508.4.wav`
- missed_commercial `hush_20260924_220624` 5354.8–5366.8s (25.2s) `C:\OHushData\gpu_lab\audio_learn\clips\finetuned\hush_20260924_220624\missed_commercial_5354.8_5366.8.wav`

## Recommendation

The probabilities separate Prime ads from Prime programming (AUROC 0.972 frozen, 0.975 fine-tuned), and the coverage gain over the locked logistic is real: the break bootstrap for the frozen model sits at 82.4% to 89.5%. The experimental gate still fails. Fine-tuning raises coverage from 86.0% to 91.9% and raises false mutes from 13.6 to 16.3 per hour, so the frozen head is the better of the two volume controllers, and neither is safe to install.

The misses inside a break are real, and the plot of the first October 8 break shows the score falling in the middle of the commercial and rising again. The gate failure is the other tail: program stretches scored above 0.90. Adding those Prime stretches to the next fit would spend the exam. The next fit can add hard program examples from the training games. These two Prime games stay untouched. A new detector is not indicated. The live path was not changed.

Checkpoints:

- Frozen head: `C:\OHushData\gpu_lab\audio_learn\checkpoints\frozen_head.pt`
- Fine-tuned encoder: `C:\OHushData\gpu_lab\audio_learn\checkpoints\finetuned_encoder.pt`
- Fine-tuned head: `C:\OHushData\gpu_lab\audio_learn\checkpoints\finetuned_head.pt`

Labeled hop counts from the frozen extract:

| Session | Commercial hops | Program hops | Excluded hops |
| --- | ---: | ---: | ---: |
| `hush_20260909_213047` | 11383 | 24127 | 1966 |
| `hush_20260913_210542` | 12192 | 38150 | 42 |
| `hush_20260913_150934` | 0 | 28784 | 0 |
| `hush_20261011_135700` | 3924 | 15631 | 16 |
| `hush_20261012_204200` | 11748 | 40635 | 48 |
| `hush_20260914_212529` | 7199 | 20351 | 30 |
| `hush_20261008_205100` | 10546 | 31154 | 45 |
| `hush_20260924_220624` | 6635 | 23725 | 24 |

Head fit loss by epoch, frozen then fine-tuned:

- Frozen: [0.3047871002771107, 0.2465474714494778, 0.22483137604142106, 0.21270310726575534, 0.21130967577471368, 0.19907337320800672, 0.19108838501805597, 0.18931032806651452]
- Fine-tuned encoder loss first/last: 0.7031846642494202 / 0.033319421112537384
- Fine-tuned head: [0.2859020667916985, 0.23835637400276496, 0.21763686911931654, 0.20695926833207126, 0.20360556515547787, 0.19498473108773026, 0.18740418124021363, 0.17978621514042528]

