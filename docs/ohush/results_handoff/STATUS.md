# Measurement results through 13 October 2026

Three offline measurements, in the order they were closed. None of them changed the live muter, a threshold, a booth identity, or a closed label.

## 1. Measurement contract and the Thursday join

Report: `docs/ohush/research/MEASUREMENT_STOPPING_POINT_002.md`

Verdict: the scorer is safe only on a timeline that already meets the contract. `run19` is not joined to `audio_0023.wav`.

The contract is `experiments/measurement/metrics.py`. Tests are `tests/test_measurement_v1.py`. A bad timeline raises `TimelineError`. A program-name mark may contain a commercial. That overlap is context, not a second claim on the same seconds. Missing playback stays missing. The four degenerate never-cover and always-cover rows in `docs/ohush/research/gold_harness.json` were preserved.

`docs/ohush/research/run19_alignment.json` is the join test. Duration delta 0.299 s. Best feature offset about −1 s, Pearson r 0.9915, same offset in all three thirds. Alternatives `audio_0044.wav` and `audio_0027.wav` reach about 0.68. There is no sample counter tying engine time to a WAV sample. Feature alignment was not accepted as a join. Thursday engine decisions were not scored.

`experiments/measurement/run19_align.py` is the code. It does not need to be re-run to read the json.

## 2. Frozen program memory on September 13 NBC

Report: `docs/ohush/research/FROZEN_RETURN_REPLICATION_001/REPORT.md`

Verdict: **INCONCLUSIVE**.

Session `hush_20260913_210542`, recording clock 0–12600 s, 21 commercials. The oracle snapshot uses the labeled start only to choose a window. The causal snapshot is the one already stored by Exp003b. No distance threshold was fit.

Artifacts:

- `results.json` — verdict counts, pooled gaps, every break, RedZone control
- `nbc_breaks.csv` — one row per commercial
- `nbc_distances.png` — adaptive, oracle, and causal series
- `redzone_departures.png` — zero-commercial control

Of 15 clean oracle snapshots, 12 separate the end of the commercial from the following 30 s. None of those 12 fall back to the snapshot's own distance during the ads. Crossings after the true end take 21–73 s and do not stay down. A clean causal snapshot exists for 6 of 21 breaks. RedZone, with zero commercials, produces 6 Exp003b freezes per hour and 8.5 speaker-collapse events per hour.

The ESPN comparison this replicates is `experiments/exp003b/EXP003B_RESULT.md` and `experiments/exp003b/hush_20260914_212529/overlay_summary.json`.

## 3. Adaptive audio distance on September 9 NBC

Report: `docs/ohush/research/AUDIO_SIGNAL_REPLICATION_001/REPORT.md`

Verdict: **INCONCLUSIVE**. This is the latest decision gate.

Session `hush_20260909_213047`, recording clock 0–9373 s, 20 commercials, 2849.911 s. The series was already on disk and was built without these labels. The script recomputed the distance from the stored embeddings and required it to match. No mute policy exists, so commercial-heard time was not computed.

Artifacts:

- `results.json` — verdict, distributions, freeze split, every break, RedZone peaks
- `nbc_breaks.csv` — one row per commercial
- `nbc_audio_distance.parquet` — `window_end` and `anomaly` only. Not audio.
- `nbc_distance.png`, `redzone_distance.png`, `distributions.png`

Eighteen of 19 evaluable starts have a higher median in the 30 s after the start than in the 30 s before. Commercial median 0.213, program median 0.072. Top 20 peaks: 17 associated with a commercial, the same count published for ESPN. The causal 99th-percentile hit arrives within 30 s on 9 of 19 evaluable starts, and five of those nine still contain pre-break audio. Program-time freezes: 1.66 per hour. RedZone median distance is 0.049, with 6.0 causal false starts per hour. Two of the ten strongest RedZone peaks coincide with a speaker-cluster change. Game changes were not labeled.

The ESPN comparison is `experiments/exp003/EXP003_RESULT.md` and `experiments/exp003/hush_20260914_212529/overlay_summary.json`.

The code that wrote this folder is `experiments/measurement/audio_signal_replication.py`. The frozen score definition is `src/hush/program_cloud.py`. The causal hit definition is `src/hush/frozen_identity.py`.

## What the labels are

`experiments/gold/LABEL_POLICY_V1.md` defines the scoring target: commercial, mute, confidence not unsure. A program mark names the show and may contain commercials.

Coverage manifests:

- `experiments/gold/GOLD_DATASET_20261013.json` — nine closed ranges, including both NBC games and RedZone
- `experiments/gold/GOLD_DEV_V1.json` — ESPN 0–6899 s
- `experiments/gold/GOLD_REPLICATION_V1.json` — Prime and August Hulu

`experiments/annotations/truth_events.jsonl` is the ledger. Resolve superseded ids and drop retracted rows before counting. The active total used here was 177 marks: 166 commercials and 11 program marks. Holdouts are not in the scored ranges.

## Next measurement named by the latest report

A shorter causal window on the same CNN14 embedding. Not a new model. Not a threshold fit on September 9. Not a live mute. Frozen-return work stays unauthorized until a start signal is fast enough to be the thing a return would undo.

## Not in this zip

WAV files, embeddings, booth excerpts, the Thursday engine track, and the live decision engine. The distance parquet is scores, not samples.
