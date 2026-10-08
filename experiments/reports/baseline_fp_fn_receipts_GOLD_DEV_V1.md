# Baseline FP/FN receipts — GOLD_DEV_V1

- Coverage: **115.0 minutes** fully annotated (`hush_20260914_212529` 0–6899)
- Truth: **15** commercial breaks
- legacy_v0: **TP 1 / FP 45 / FN 14**
- Recall ±2s: **6.7%** · Precision ±2s: **2.2%**
- IN MAE (1 match): **1.84s**
- OUT end-to-end MAE: **7.99s** · oracle-IN MAE: **7.90s**

Awful is expected. Do not tune yet — use these rows to group causes.

## Gold events

### FN #1
- Gold IN `166.6` · OUT `305.8`
- Nearest keep `96.1` (Δ `-70.5s`, score `7.547`, rank `1`)
- Nearest IN proposal `96.1` (Δ `-70.5s`, score `7.547`, action `keep`, reason `ranked_nonsuppressed`)
- Root-cause hypothesis: **no useful nearby discontinuity — evidence/features**

### FN #2
- Gold IN `512.9` · OUT `634.7`
- Nearest keep `490.9` (Δ `-22.0s`, score `6.413`, rank `4`)
- Nearest IN proposal `490.9` (Δ `-22.0s`, score `6.413`, action `keep`, reason `ranked_nonsuppressed`)
- Root-cause hypothesis: **nearby keep, onset timing off (>2s collar)**

### FN #3
- Gold IN `1029.7` · OUT `1079.1`
- Nearest keep `1038.0` (Δ `+8.3s`, score `6.858`, rank `2`)
- Nearest IN proposal `1038.0` (Δ `+8.3s`, score `6.858`, action `keep`, reason `ranked_nonsuppressed`)
- Root-cause hypothesis: **nearby keep, onset timing off (>2s collar)**

### FN #4
- Gold IN `1243.2` · OUT `1308.2`
- Nearest keep `1282.2` (Δ `+39.1s`, score `7.31`, rank `1`)
- Nearest IN proposal `1282.2` (Δ `+39.1s`, score `7.31`, action `keep`, reason `ranked_nonsuppressed`)
- Root-cause hypothesis: **no useful nearby discontinuity — evidence/features**

### FN #5
- Gold IN `1538.9` · OUT `1767.5`
- Nearest keep `1442.1` (Δ `-96.7s`, score `7.35`, rank `0`)
- Nearest IN proposal `1442.1` (Δ `-96.7s`, score `7.35`, action `keep`, reason `ranked_nonsuppressed`)
- Root-cause hypothesis: **no useful nearby discontinuity — evidence/features**

### FN #6
- Gold IN `2072.1` · OUT `2207.4`
- Nearest keep `2119.8` (Δ `+47.6s`, score `7.452`, rank `1`)
- Nearest IN proposal `2119.8` (Δ `+47.6s`, score `7.452`, action `keep`, reason `ranked_nonsuppressed`)
- Root-cause hypothesis: **no useful nearby discontinuity — evidence/features**

### TP #7
- Gold IN `2658.5` · OUT `2780.4`
- Nearest keep `2660.4` (Δ `+1.8s`, score `6.431`, rank `5`)
- Nearest IN proposal `2660.4` (Δ `+1.8s`, score `6.431`, action `keep`, reason `ranked_nonsuppressed`)
- Root-cause hypothesis: **matched within ±2s**

### FN #8
- Gold IN `3180.1` · OUT `3290.2`
- Nearest keep `3171.1` (Δ `-9.0s`, score `7.343`, rank `3`)
- Nearest IN proposal `3171.5` (Δ `-8.6s`, score `6.024`, action `suppress`, reason `min_gap`)
- Root-cause hypothesis: **nearby keep, onset timing off (>2s collar)**

### FN #9
- Gold IN `3649.1` · OUT `3785.2`
- Nearest keep `3784.0` (Δ `+134.9s`, score `10.217`, rank `1`)
- Nearest IN proposal `3783.9` (Δ `+134.8s`, score `9.839`, action `suppress`, reason `min_gap`)
- Root-cause hypothesis: **no useful nearby discontinuity — evidence/features**

### FN #10
- Gold IN `4244.2` · OUT `4379.0`
- Nearest keep `4266.9` (Δ `+22.6s`, score `7.025`, rank `2`)
- Nearest IN proposal `4266.9` (Δ `+22.6s`, score `7.025`, action `keep`, reason `ranked_nonsuppressed`)
- Root-cause hypothesis: **nearby keep, onset timing off (>2s collar)**

### FN #11
- Gold IN `4543.8` · OUT `4675.3`
- Nearest keep `4559.6` (Δ `+15.8s`, score `6.6`, rank `3`)
- Nearest IN proposal `4552.5` (Δ `+8.7s`, score `4.995`, action `suppress`, reason `min_gap`)
- Root-cause hypothesis: **nearby keep, onset timing off (>2s collar)**

### FN #12
- Gold IN `5019.6` · OUT `5157.3`
- Nearest keep `5065.5` (Δ `+45.9s`, score `13.383`, rank `0`)
- Nearest IN proposal `5045.1` (Δ `+25.5s`, score `7.09`, action `suppress`, reason `min_gap`)
- Root-cause hypothesis: **nearby proposal not kept · action=suppress reason=min_gap**

### FN #13
- Gold IN `5665.4` · OUT `5785.7`
- Nearest keep `5707.8` (Δ `+42.4s`, score `9.424`, rank `1`)
- Nearest IN proposal `5689.5` (Δ `+24.1s`, score `5.084`, action `suppress`, reason `min_gap`)
- Root-cause hypothesis: **nearby proposal not kept · action=suppress reason=min_gap**

### FN #14
- Gold IN `6344.6` · OUT `6470.6`
- Nearest keep `6379.9` (Δ `+35.2s`, score `5.49`, rank `5`)
- Nearest IN proposal `6379.9` (Δ `+35.2s`, score `5.49`, action `keep`, reason `ranked_nonsuppressed`)
- Root-cause hypothesis: **no useful nearby discontinuity — evidence/features**

### FN #15
- Gold IN `6852.6` · OUT `6898.9`
- Nearest keep `6855.2` (Δ `+2.7s`, score `7.996`, rank `4`)
- Nearest IN proposal `6854.9` (Δ `+2.3s`, score `6.246`, action `suppress`, reason `min_gap`)
- Root-cause hypothesis: **nearby keep, onset timing off (>2s collar)**

## False positives

### FP #1
- Proposal `96.1` · score `7.547` · `audio_0001.wav`
- Nearest gold IN `166.6` (Δ `-70.5s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #2
- Proposal `274.5` · score `7.713` · `audio_0001.wav`
- Nearest gold IN `166.6` (Δ `+107.9s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #3
- Proposal `490.9` · score `6.413` · `audio_0001.wav`
- Nearest gold IN `512.9` (Δ `-22.0s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #4
- Proposal `549.4` · score `7.248` · `audio_0001.wav`
- Nearest gold IN `512.9` (Δ `+36.5s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #5
- Proposal `577.9` · score `6.346` · `audio_0001.wav`
- Nearest gold IN `512.9` (Δ `+65.0s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #6
- Proposal `644.9` · score `6.469` · `audio_0001.wav`
- Nearest gold IN `512.9` (Δ `+132.0s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #7
- Proposal `1038.0` · score `6.858` · `audio_0002.wav`
- Nearest gold IN `1029.7` (Δ `+8.3s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #8
- Proposal `1120.5` · score `6.189` · `audio_0002.wav`
- Nearest gold IN `1029.7` (Δ `+90.8s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #9
- Proposal `1282.2` · score `7.31` · `audio_0002.wav`
- Nearest gold IN `1243.2` (Δ `+39.1s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #10
- Proposal `1314.9` · score `6.612` · `audio_0002.wav`
- Nearest gold IN `1243.2` (Δ `+71.7s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #11
- Proposal `1359.9` · score `6.524` · `audio_0002.wav`
- Nearest gold IN `1243.2` (Δ `+116.7s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #12
- Proposal `1442.1` · score `7.35` · `audio_0002.wav`
- Nearest gold IN `1538.9` (Δ `-96.7s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #13
- Proposal `1892.1` · score `9.068` · `audio_0003.wav`
- Nearest gold IN `2072.1` (Δ `-180.0s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #14
- Proposal `2119.8` · score `7.452` · `audio_0003.wav`
- Nearest gold IN `2072.1` (Δ `+47.6s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #15
- Proposal `2222.0` · score `7.382` · `audio_0003.wav`
- Nearest gold IN `2072.1` (Δ `+149.9s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #16
- Proposal `2279.9` · score `6.805` · `audio_0003.wav`
- Nearest gold IN `2072.1` (Δ `+207.8s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #17
- Proposal `2525.2` · score `6.779` · `audio_0003.wav`
- Nearest gold IN `2658.5` (Δ `-133.3s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #18
- Proposal `2788.9` · score `7.461` · `audio_0004.wav`
- Nearest gold IN `2658.5` (Δ `+130.3s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #19
- Proposal `3018.8` · score `6.638` · `audio_0004.wav`
- Nearest gold IN `3180.1` (Δ `-161.4s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #20
- Proposal `3138.5` · score `5.94` · `audio_0004.wav`
- Nearest gold IN `3180.1` (Δ `-41.6s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #21
- Proposal `3171.1` · score `7.343` · `audio_0004.wav`
- Nearest gold IN `3180.1` (Δ `-9.0s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #22
- Proposal `3232.6` · score `7.962` · `audio_0004.wav`
- Nearest gold IN `3180.1` (Δ `+52.5s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #23
- Proposal `3346.8` · score `7.527` · `audio_0004.wav`
- Nearest gold IN `3180.1` (Δ `+166.6s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #24
- Proposal `3784.0` · score `10.217` · `audio_0005.wav`
- Nearest gold IN `3649.1` (Δ `+134.9s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #25
- Proposal `4124.4` · score `12.107` · `audio_0005.wav`
- Nearest gold IN `4244.2` (Δ `-119.9s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #26
- Proposal `4266.9` · score `7.025` · `audio_0005.wav`
- Nearest gold IN `4244.2` (Δ `+22.6s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #27
- Proposal `4318.9` · score `6.984` · `audio_0005.wav`
- Nearest gold IN `4244.2` (Δ `+74.6s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #28
- Proposal `4349.9` · score `6.26` · `audio_0005.wav`
- Nearest gold IN `4244.2` (Δ `+105.6s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #29
- Proposal `4431.2` · score `6.442` · `audio_0005.wav`
- Nearest gold IN `4543.8` (Δ `-112.5s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #30
- Proposal `4559.6` · score `6.6` · `audio_0006.wav`
- Nearest gold IN `4543.8` (Δ `+15.8s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #31
- Proposal `4663.8` · score `9.067` · `audio_0006.wav`
- Nearest gold IN `4543.8` (Δ `+120.0s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #32
- Proposal `5065.5` · score `13.383` · `audio_0006.wav`
- Nearest gold IN `5019.6` (Δ `+45.9s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #33
- Proposal `5155.2` · score `8.566` · `audio_0006.wav`
- Nearest gold IN `5019.6` (Δ `+135.6s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #34
- Proposal `5244.5` · score `4.885` · `audio_0006.wav`
- Nearest gold IN `5019.6` (Δ `+224.9s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #35
- Proposal `5372.6` · score `5.945` · `audio_0006.wav`
- Nearest gold IN `5665.4` (Δ `-292.7s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #36
- Proposal `5423.5` · score `4.989` · `audio_0007.wav`
- Nearest gold IN `5665.4` (Δ `-241.9s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #37
- Proposal `5450.0` · score `4.586` · `audio_0007.wav`
- Nearest gold IN `5665.4` (Δ `-215.4s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #38
- Proposal `5707.8` · score `9.424` · `audio_0007.wav`
- Nearest gold IN `5665.4` (Δ `+42.4s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #39
- Proposal `5785.8` · score `9.437` · `audio_0007.wav`
- Nearest gold IN `5665.4` (Δ `+120.4s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #40
- Proposal `6065.2` · score `4.819` · `audio_0007.wav`
- Nearest gold IN `6344.6` (Δ `-279.4s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #41
- Proposal `6244.2` · score `5.102` · `audio_0007.wav`
- Nearest gold IN `6344.6` (Δ `-100.4s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #42
- Proposal `6379.9` · score `5.49` · `audio_0008.wav`
- Nearest gold IN `6344.6` (Δ `+35.2s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #43
- Proposal `6439.9` · score `10.55` · `audio_0008.wav`
- Nearest gold IN `6344.6` (Δ `+95.2s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #44
- Proposal `6470.0` · score `8.349` · `audio_0008.wav`
- Nearest gold IN `6344.6` (Δ `+125.4s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

### FP #45
- Proposal `6855.2` · score `7.996` · `audio_0008.wav`
- Nearest gold IN `6852.6` (Δ `+2.7s`)
- Root-cause hypothesis: **needs listen** (likely program transition / over-trigger)

## Tentative grouping (hypotheses only)

- no useful nearby discontinuity — evidence/features: 6
- nearby keep, onset timing off: 6
- nearby proposal not kept: 2
- matched within ±2s: 1
