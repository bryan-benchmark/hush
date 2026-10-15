# Causal reference parity 001

Not a mute. `FINGERPRINT_BOUNDED_QUERY_001` was left closed. Counts 10 and 200, the gold, reference eligibility, and the holdouts were not changed. Playback stays PLAY. The ledger was not scored.

The question was whether the five verified advertisements return when the reference window is cut with the same seven-second method as the query. The reference locations used here are the alignments already measured on the long-block fingerprints, plus the waveform lags from the reference-content audit. A match at a location we already knew is feasibility evidence. It is not a detector.

## Published failure, reproduced

Bounded query against the original long-block reference, exact two-second lead:

| Query | Published | Reproduced |
| --- | ---: | ---: |
| Thursday 145 | 272 | 33 |
| Thursday 150 | 223 | 137 |
| Thursday 155 | 260 | 92 |
| Thursday 160 | 242 | 26 |
| Monday 5085 | 208 | 102 |

## Same extraction on both sides

Each reference window was re-extracted with the same lead and the same analyzer. `aligned` is where the long-block fingerprint places the query. The waveform column moves that cut by the lag already measured on the audio (38 to 53 ms).

| Query | Aligned reference | Same 2.0 s cut | Same 86-hop cut | Same 86-hop cut at the waveform lag |
| --- | ---: | ---: | ---: | ---: |
| Thursday 145 | 314.491 s | 39 | 37 | 258 |
| Thursday 150 | 319.483 s | 218 | 201 | 248 |
| Thursday 155 | 324.476 s | 53 | 67 | 280 |
| Thursday 160 | 329.491 s | 37 | 26 | 280 |
| Monday 5085 | 6873.803 s | 74 | 76 | 204 |

All five land inside the same gold pods as before. At the waveform lag the matched offset agrees with that placement (offset error 0 frames on four windows, −2 frames on Thursday 150). The query matched against itself still scores 333 to 434, so the low cross scores are disagreements between the two windows.

Identical geometry at the fingerprint's own alignment restores one window, Thursday 150. The other four stay at 39, 67, 26, and 76. Placing the reference cut on the waveform lag restores all five: 258, 248, 280, 280, and 204.

Thursday 150 at the waveform lag, and both Thursday 160 hop windows, cross a chunk boundary that the strict sample-count check refuses by one sample. Those three scores used the same slices concatenated. The strict reads beside them agree: Thursday 150 stays at or above 200 across several hops, and Thursday 160 stays near 26 until the cut sits at +37.5 ms.

## Phase

The hop-aligned query was matched again while the reference cut moved. Shifts that still score at least 200:

| Query | Shifts at or above 200 |
| --- | --- |
| Thursday 145 | +37.6 ms only (258). +40 ms is 158. −100 ms is 178. |
| Thursday 150 | −23 ms through +70 ms, and +139 ms. Seven grid points, scores 200 to 248. |
| Thursday 155 | −40 ms (293), +53 ms (280), +100 ms (244). |
| Thursday 160 | +37.5 ms only (280). The cut at the fingerprint alignment scores 26. |
| Monday 5085 | +51.3 ms only (204). −40 ms is 164. +100 ms is 137. |

A subsecond offset is enough to lose four of the five. One analyzer hop is 23.2 ms. Thursday 160 and Monday 5085 clear 200 at a single tested placement.

## The 13 block-start collisions

The afternoon false matches stay down. Bounded against the original reference they score 2, 3, or 4. Bounded against a bounded reference at the old alignment they score 0, 1, or 2. Where a one-hash residual remains, the offset is off by 13 to 186 frames, about 0.3 to 4.3 seconds. Those residuals are not the old alignment.

## What this can and cannot do

The five advertisements are still in the audio. When both windows are cut the same way and the reference cut sits on the waveform lag, audfprint scores them above 200 again. That placement was supplied by the earlier alignment. This run did not search the library.

A lookup cannot find that cut. The restoring window is narrower than a hop on three of the five ads. Covering an unknown location would mean extracting a fresh bounded reference every few tens of milliseconds through every eligible pod. That scan was not run. An oracle-aligned score is not a reason to score the ledger, and it is not a reason to sweep context length again.

The 25.1-second FanDuel interruption stays a separate category. That span is repeated audio on a program label. A closer waveform match will not change the label.
