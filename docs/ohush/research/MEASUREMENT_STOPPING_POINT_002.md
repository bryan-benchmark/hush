# Measurement stopping point 002 — 13 October 2026

No live auto-output was enabled. The decision engine, thresholds, `.booth.json`, Exp001–005, and the frozen Thursday track were not modified. No new detector was built. Thursday engine decisions were not scored.

## 1. Is the measurement implementation safe for real playback logs?

It is safe only for a timeline that already meets the contract in `experiments/measurement/metrics.py`. A timeline that does not meet it raises `TimelineError`. The scorer does not sort, clip, or merge its way to a number.

Rejected, with a test for each:

| Input | Result |
|-------|--------|
| Overlapping playback, including `program` and `covered` on the same seconds | `TimelineError` |
| Playback out of time order, or a clock that moves backwards | `TimelineError` |
| A gold interval that extends outside coverage | `TimelineError` |
| Overlapping gold intervals, including a commercial overlapping a program mark | `TimelineError` |
| A playback state other than `program` or `covered` | `TimelineError` |
| A forward gap | Kept as missing time, not called program and not called covered |

Repeated cover/uncover cycles stay legal. Each return to program inside a commercial counts. A commercial that is never covered has `starts_missed` set and `start_delay_median_s` left empty. Heard seconds are still heard seconds. Missing seconds are separate.

Every coverage second is one of: unsure, commercial heard, commercial covered, commercial missing, program heard, program covered, program missing. `observed_fraction` is the share of eligible time (coverage minus unsure) that has a playback state.

A raw Thursday track is not a legal timeline. It contains 32 clock resets. Concatenating those runs would now raise, which is the intended failure. A reconstructed single run can be scored only after its playback spans are ordered, non-overlapping, and on the same clock as the gold.

The four published degenerate-policy results are unchanged. `tests/test_measurement_v1.py` compares them to `gold_harness.json` field by field.

```text
PYTHONPATH=. .venv/bin/python -m unittest tests.test_measurement_v1 -v
```

14 tests, OK. Re-run after the later labels were appended. The four degenerate-policy rows in `gold_harness.json` still match.

## 2. Was run19 conclusively aligned?

No. The join is rejected.

`audio_0023.wav` is 675.328 s. Frozen `run19` ends at 675.029 s. The 0.299 s duration gap is not a join.

There is no sample lock. The frozen track has only relative `t`. It has no sample index and no wall clock. `decisions.jsonl` and `overrides.jsonl` are the same. `ChunkWriter` does not store the time a file was opened. File mtime is the last write, not a timestamp stored next to `t`. `dropped_frames` is the playback ring discarding output (max 13,171,328 frames on this run, about 274 s). It is not a count of samples missing from the WAV, and it does not point at a sample.

The frozen CNN14 distance was recomputed from the WAV with the live worker's own rule (10 s window, 1 s hop, 180 s memory, 15 s minimum reference). Commercial labels were not used. Search was ±120 s, then ±2 s around the peak.

| File | sha256 | Best offset | Pearson r | Mean absolute error |
|------|--------|------------:|----------:|--------------------:|
| `audio_0023.wav` | `b423248e609b1a9dc9699f5b5fb5e40a5dfb03bf4ce0523d48e91055ddfe7fb9` | about −1 s | 0.9915 | 0.0091 |
| `audio_0044.wav` | `b9156325da65b6637a7bc8f72d2da075a6f94522a3f992b6822a90023db8a170` | −86.5 s | 0.6757 | 0.0561 |
| `audio_0027.wav` | `a0b7a4be375d472eded8c6fc3c794e1b4e159479a064ba86a28504316a47fde1` | −50.5 s | 0.6774 | 0.0490 |

On `audio_0023.wav` the same −1.25 s bin won in all three thirds (r 0.9956, 0.9819, 0.9765). Offsets −1.25, −1.00, and −0.75 s produce the same pairs, because logged scores sit on a 1 s grid and the matcher snaps to the nearest second. The offset is about one second and is not resolved inside that second. That is feature alignment. It is not a sample lock, so engine decisions are not attributed to these samples.

Frozen track sha256: `f4850eccecfb8bbf734fefce0854fb3fe0677e6f339d9f6abe1672d4a02be442`.

Full table: `run19_alignment.json`.

```text
MPLCONFIGDIR=/tmp/mpl PYTHONPATH=src:. experiments/exp003/.venv/bin/python experiments/measurement/run19_align.py
```

`run19` was not mounted in the labeler. No Thursday intervals were created.

## 3. What commercial-detection metrics can now be reported credibly?

No detection rate. The live algorithm was not replayed. Thursday still has no interval gold on a locked clock, so its engine decisions are not scored.

What can be said:

- The never-cover and always-cover numbers in `MEASUREMENT_V1_REPORT.md` still match `gold_harness.json`.
- The listener has now closed the dataset ranges, including September 9 NBC. These are label totals, not detector scores. `docs/ohush/dataset_handoff/digest.json` is the full table.

| Session | Closed range | Certain commercial marks | Commercial seconds |
|---------|--------------|-------------------------:|-------------------:|
| September 9 NBC `hush_20260909_213047` | 0–9373 | 20 | 2849.9 |
| September 13 FOX `hush_20260913_150934` | 0–7200 | 0 | 0 |
| September 13 NBC `hush_20260913_210542` | 0–12600 | 21 | 3052.5 |
| Thursday capture-order `hush_20261008_205100` | 0–10440.364 | 23 | 2642.1 |
| Sunday night `hush_20261011_204300` | 0–14405.376 | 6 | 626.4 |
| Monday night `hush_20261012_204200` | 0–13111.808 | 24 | 2944.3 |
| Saturday `hush_20261010_222400` | 0–6064.768 | 6 | 1081.8 |
| Sunday afternoon `hush_20261011_135700` | 0–4896.768 | 8 | 983.0 |

The FOX range has one program mark, note `redzone`. Unmarked time inside a closed range is program by the labeling rule. Thursday's 23 commercials are on the captured-audio clock. They do not score the mute log.

September 9 NBC is fully annotated, so the fallback in this work order is already done. The next measurement can use that file's own clock.

Truth ledger sha256: `a5e97a6d9b0af1a39355d610b32374cb974903b86b09cb625549019224a3313b`.

Dataset manifest sha256: `4944a8559e933593d74e20162d3bc695eff2c632370c004c042976ae9ab1b725`.

## 4. Are any trusted speaker identities demonstrably contaminated?

No. This pass did not listen, and it does not propose a correction.

The seven excerpts in `booth_excerpts/` match the sha256 values in `booth_excerpts/manifest.json`. They are 10 s cuts from `audio_0044.wav` at frozen `run29` times. That file is still only a duration candidate for `run29`. A voice heard in one of those cuts cannot yet be assigned to the logged cluster.

`.booth.json` still trusts `c0001`, `c0002`, `c0015`, `c0017`. It was not edited. A different cluster id is not proof of a different person, and the same id is not proof of the same person. No second listener has confirmed a change, so none is proposed. `c0013` at 221 s, `c0016` at 285 s, and `c0010` at 621 s remain the three cuts that matter, and they are still unheard in this record.

## 5. What is the single next experiment?

Score the existing frozen audio distance, with no threshold change, on September 9 NBC (`hush_20260909_213047`, 0–9373 s). The labels are already closed: 20 certain commercials, 2849.9 s. Publish heard seconds, missed seconds, false-cover incidents, and start delays, and list every gap the metric marks missing. The file's own clock is the clock the labels use, so this does not need the Thursday join.

Do not retune on that table. Do not score Thursday's engine log until a sample clock exists. A human listen of `c0013` at 221 s, `c0016` at 285 s, and `c0010` at 621 s can proceed beside that. A different cluster id is not proof of a different person. No listen in this pass changes `.booth.json`.

## Uncertainties

- The −1 s feature offset can be wrong by about one hop. Sub-second latency cannot be computed from it.
- Alternative-file correlations near 0.68 are high enough to show that distance series look somewhat alike across football audio. They are not high enough, and not close enough in error, to compete with `audio_0023.wav`.
- FOX's opening is closed as "no commercial" without a show name. The named program mark is `redzone`.
- The closed ranges above were labeled by ear. This pass did not re-listen to them.
- The seven booth excerpts were checked against their published hashes. They were not played as an identity verdict.

## Files this pass changed

| File | sha256 |
|------|--------|
| `experiments/measurement/metrics.py` | `35060aa56dc994e0909cfe703353126de994135d9a4f537999c3f3f8e0327341` |
| `tests/test_measurement_v1.py` | `a38e9bdeb7358aeb0e28adc3dd8db4c41449c9c8818582a647e0f29fd2d4cc3b` |
| `experiments/measurement/run19_align.py` | `652adffe8b7ed213928c1c1ab1a109f8526e212b5ef2abe00a7881d55e17ebce` |
| `docs/ohush/research/run19_alignment.json` | `0c0951d650145a3a1de26a53c02ee0cbcc269f7d5f06dc7f1cf2fea2da5f7615` |
| `docs/ohush/research/MEASUREMENT_STOPPING_POINT_002.md` | this file |
