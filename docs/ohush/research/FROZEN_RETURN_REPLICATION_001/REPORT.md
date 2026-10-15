# Frozen return replication 001 — 13 October 2026

Verdict: **INCONCLUSIVE**.

A frozen copy of the football sound can stay distinct from the commercials on this NBC broadcast, when the snapshot is taken from a clean stretch before the break. The unchanged causal rule does not obtain that snapshot for most breaks. No return threshold was fit. The live machine was not changed, and automatic covering was not turned on.

## Stop rule, fixed before this table

A full oracle snapshot uses the known commercial start only to choose the window. The window is the same one Exp003b already uses: embeddings whose ends fall in (start − 210 s, start − 30 s]. It counts as full when that reference spans at least 60 s, which is the existing Exp003 minimum, and when the window does not overlap an earlier commercial.

A break is separated when the median oracle distance in the last 30 s of the commercial is above the snapshot's own median self-distance and above the median in the first 30 s after the true end. Oracle fails if that is not true for a majority of the full snapshots, or if a majority of those separated breaks also fall back to the self-distance while the ads are still playing.

Causal acquisition is a published freeze in (start, start + 60 s] whose reference ends at or before the commercial start and does not overlap a commercial. That bar fails unless it holds for a majority of the 21 breaks.

Oracle failure would have stopped this line. Oracle success with causal failure points at snapshot selection. Both succeeding would only have authorized a later experiment.

## 1. Scoring contract

The ledger resolves to 177 active marks: 166 commercial mute targets and 11 program-identity marks, across 12 closed ranges. Program marks may contain commercials. Two mute targets on the same second are still rejected. A show change is not a commercial boundary. A capture gap placed inside the coverage clock is rejected, because that hole is not elapsed audio.

`tests.test_measurement_v1`: 21 tests, OK. The four published never-cover and always-cover results are unchanged. All nine ranges in `GOLD_DATASET_20261013.json` now score, including Saturday, Sunday afternoon, and Monday, which previously raised `TimelineError` on a program mark containing a commercial.

```text
PYTHONPATH=. .venv/bin/python -m unittest tests.test_measurement_v1
```

## 2. NBC frozen return

Session `hush_20260913_210542`, recording clock 0–12,600 s, 21 certain commercials. Embeddings and the causal timeline were already on disk. They were not recomputed. The published freeze times match the stored hit mask. Gold was not used when those files were made.

The feature clock ends at 12,480 s. The last 120 s of the closed range have no embeddings. The last commercial ends at 9,820.857 s, so that tail contains no target.

Command:

```text
MPLCONFIGDIR=/tmp/mpl PYTHONPATH=src:. .venv/bin/python experiments/measurement/frozen_return_replication.py
```

### What the oracle snapshot did

Fifteen breaks have a full, uncontaminated snapshot. Twelve of those fifteen are separated by the median test. None of those twelve fall back to the self-distance during the ads. On one window inside two pods the distance touches the self-line; it does not cross back down after having risen.

Pooled over those fifteen breaks, the median oracle distance is 0.339 during commercials and 0.143 in the 120 s after the true end. The gap is 0.197. The adaptive 180 s reference on the same windows is 0.223 during commercials and 0.140 after, a gap of 0.084. The frozen reference widens the separation. The same direction was already published for ESPN (frozen pod median 0.289, program median 0.091). It is not only an ESPN result.

Reaching the snapshot's own self-distance is a harder event than the median comparison. Seven of the twelve separated breaks do it within 120 s. Five do not: the distance falls, and it stays above the line the snapshot uses for its own program audio. Where a crossing exists, it arrives 21–73 s after the true end, and it does not stay down. The share of the next 30 s that remains at or below the self-line is between 0.03 and 0.47.

Six breaks are not in the fifteen. Their 180 s reference reaches back into the previous commercial, because the program between those breaks is only 57–198 s. They were not counted as successes.

The first break starts at 100.1 s. Its reference is only 60 s long, taken from the opening of the file. The 30 s immediately before that break is already at distance 0.300, against a self-distance of 0.039. The opening minute is not a stable picture of the program that leads into the first pod.

| # | Start | End | Oracle late 30 s | Post 30 s | Self | Return latency | Failure |
|---|------:|----:|-----------------:|----------:|-----:|---------------:|---------|
| 1 | 100.1 | 154.6 | 0.359 | 0.365 | 0.039 | — | return window not closer |
| 2 | 780.2 | 918.5 | 0.328 | 0.096 | 0.035 | 21.5 s | returned |
| 3 | 1547.2 | 1683.2 | 0.208 | 0.226 | 0.029 | 40.8 s | return window not closer |
| 4 | 1754.4 | 1890.9 | 0.174 | 0.120 | 0.104 | — | earlier commercial in the snapshot |
| 5 | 2089.3 | 2120.3 | 0.172 | 0.079 | 0.053 | — | earlier commercial in the snapshot |
| 6 | 2179.0 | 2315.3 | 0.306 | 0.037 | 0.047 | — | earlier commercial in the snapshot |
| 7 | 2689.6 | 2721.0 | 0.381 | 0.100 | 0.038 | 23.0 s | returned |
| 8 | 3073.0 | 3260.1 | 0.371 | 0.234 | 0.035 | — | no return within 120 s |
| 9 | 3471.0 | 3715.8 | 0.206 | 0.152 | 0.050 | — | no return within 120 s |
| 10 | 4479.5 | 4597.0 | 0.313 | 0.260 | 0.039 | 41.0 s | returned |
| 11 | 5289.1 | 5425.3 | 0.322 | 0.229 | 0.030 | — | no return within 120 s |
| 12 | 5482.6 | 5608.8 | 0.234 | 0.171 | 0.141 | — | earlier commercial in the snapshot |
| 13 | 5669.4 | 5805.7 | 0.197 | 0.124 | 0.139 | — | earlier commercial in the snapshot |
| 14 | 5870.3 | 5997.7 | 0.164 | 0.119 | 0.115 | — | earlier commercial in the snapshot |
| 15 | 6305.1 | 6441.4 | 0.313 | 0.254 | 0.030 | 33.6 s | returned |
| 16 | 6838.4 | 7256.3 | 0.419 | 0.053 | 0.032 | 46.7 s | returned |
| 17 | 7634.2 | 7754.3 | 0.387 | 0.290 | 0.034 | 72.7 s | returned |
| 18 | 8268.2 | 8406.4 | 0.392 | 0.245 | 0.028 | 39.6 s | returned |
| 19 | 8671.0 | 8834.6 | 0.248 | 0.303 | 0.019 | — | return window not closer |
| 20 | 9187.1 | 9383.0 | 0.252 | 0.193 | 0.046 | — | no return within 120 s |
| 21 | 9680.1 | 9820.9 | 0.337 | 0.336 | 0.052 | — | no return within 120 s |

Rows 4, 5, 6, 12, 13, and 14 are shown for completeness. They are not in the fifteen. Every row is in `nbc_breaks.csv`. The three distance series are in `nbc_distances.png`.

### What the causal snapshot did

Nine of the 21 breaks have a published freeze inside 60 s of the start. Six of those nine keep the reference entirely before the commercial. Six of 21 is not a majority, so the availability bar fails.

On those causal snapshots the same pattern appears. The distance can separate, a crossing of the self-line takes about 12–72 s when it happens, and the following 30 s does not stay down. No causal snapshot in this table shows a premature return by the self-line rule. Break 21's freeze is 37 s after the start, so its reference includes the beginning of the commercial. That snapshot is contaminated. It is not counted as clean.

## 3. RedZone negative control

Session `hush_20260913_150934`, closed range 0–7,200 s. Zero target commercials. One program mark, note `redzone`, from 139.9 s to 7,200 s. The opening 139.9 s has no show name. The catalog says a 90-minute capture hole begins at 7,200 s. That hole is outside this range and was not scored. Game-to-game changes inside RedZone were not labeled, so a freeze cannot be assigned to one.

Every departure event in this range is a false commercial start.

| Signal | Events | Per hour | What it is |
|--------|-------:|---------:|------------|
| Exp003b freeze, unchanged | 12 | 6.0 | The causal departure trigger |
| Exp002 continuity collapse | 17 | 8.5 | Drop of at least 0.35 from the previous 10 s, then 45 s refractory |
| Exp003 top-20 listing | 20 | — | A fixed-length list, not an alarm rate. All 20 sit in this commercial-free range |

ESPN's published in-program false-freeze rate is 1.4 per hour. RedZone's freeze rate is 6.0 per hour with no commercial present. Ordinary changes in this broadcast are enough to fire the departure trigger. The figure is `redzone_departures.png`.

## 4. Answers

1. The frozen reference does improve return separation against the adaptive reference. On the fifteen clean NBC snapshots the pooled gap is 0.197 versus 0.084.
2. The direction survives on this NBC game. It is not only the ESPN and Prime result. The return is still late, and it does not stay at the snapshot's own level.
3. The causal rule acquires a clean pre-break snapshot for 6 of 21 breaks. Not for most.
4. On the fifteen clean oracle snapshots, a fall back to the self-distance during the ads does not occur. One stray window touches the line in two pods.
5. Yes. RedZone produces 6 false Exp003b freezes per hour and 8.5 false Exp002 collapses per hour, with zero commercials.
6. These results are not strong enough for a return-only state machine. The oracle idea is not a failure, and it is not a detector. The next problem is how a clean snapshot is chosen. A return threshold fit on this game would be aimed at crossings that arrive tens of seconds late and do not persist.

## Uncertainty

- A score at time t is the preceding 10 s of audio. A latency of 21 s still contains audio from 11 s after the boundary.
- The oracle clock is the label clock. It is an upper bound, not a system that can run live.
- The causal percentile hits were not recomputed. The stored hit mask regenerates the stored freeze times.
- Six breaks were kept out of the oracle majority because the snapshot window overlaps the previous pod. Some of those still drop after the end. Leaving them out makes the oracle result harder, not easier.
- Return persistence was measured and was not part of the stop rule. It is poor enough that a later experiment should require the distance to stay down, not merely to touch the line.
- The catalog still describes this FOX file as Falcons at Steelers. The closed mark says RedZone. The mark is what was scored.
- Holdouts `hush_20260917_205513` and `hush_20260920_200635` were not opened.

## Hashes

| File | sha256 |
|------|--------|
| `experiments/annotations/truth_events.jsonl` | `a5e97a6d9b0af1a39355d610b32374cb974903b86b09cb625549019224a3313b` |
| `experiments/exp003/hush_20260913_210542/program_cloud.parquet` | `3b1ddae71e0aff69383868a2308f69bb4a55a46a2632139a6ad13720971e5100` |
| `experiments/exp003b/hush_20260913_210542/frozen_timeline.parquet` | `4f805af4ec5823054146bb8f9561db7cffdfe37660ad775f6026422d3941b10a` |
| `experiments/exp003b/hush_20260913_210542/freezes.json` | `5fbcd4f1d9feef9c64dd4a19e3b568df14da223e0cc6d498373435d9229c2bde` |
| `experiments/exp003/hush_20260913_150934/program_cloud.parquet` | `80ebe6a7672f42d221d2cd4a23f083cbc025a325fac601ed4bf9e3c1e160d0dc` |
| `experiments/exp003b/hush_20260913_150934/frozen_timeline.parquet` | `ab5a6b7f7332451c0f7faa5cf7066c8b36c0f7afa4c9c6efd713a8aa8589d293` |
| `experiments/exp002/hush_20260913_150934/speaker_timeline.parquet` | `1456170707e7f02cb4a907f4010f1d808a537cb7e6eaf687411d23498aea052a` |
| CNN14 checkpoint, from the existing metadata | `0dc499e40e9761ef5ea061ffc77697697f277f6a960894903df3ada000e34b31` |
| `experiments/measurement/metrics.py` | `bcb31ffd3132aec3169c25b0ea9c7ff6e1005b5aa951c1372ca075914e4ff024` |
| `experiments/measurement/frozen_return_replication.py` | `32f1b4113ad31586f636c62d0462e894c213937085419772582b759d71c9a27e` |
| `tests/test_measurement_v1.py` | `73317f0ec31d81c533ada811d177c9434c39ce752b8cb317fc767300ee3fe064` |
| `results.json` | `fa277c4bac09f8310887e7fec9c9b2b24d4e3edb9b186d0b099af9dacfd3d561` |
| `nbc_breaks.csv` | `ce77a88267025a43bf5043e3146b07dc85c8f585cdc9e2c48e5c9b0224a50ae4` |

## Files this pass changed

- `experiments/measurement/metrics.py`
- `tests/test_measurement_v1.py`
- `experiments/measurement/frozen_return_replication.py`
- `docs/ohush/research/FROZEN_RETURN_REPLICATION_001/` (`REPORT.md`, `results.json`, `nbc_breaks.csv`, `nbc_distances.png`, `redzone_departures.png`)

Truth events, Exp002, Exp003, Exp003b outputs, booth identities, thresholds, and the live decision engine were not modified.
