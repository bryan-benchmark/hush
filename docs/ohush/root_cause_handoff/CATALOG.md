# OHush catalog — 15 October 2026

Read this before any report. A figure in an older handoff loses to the report and the json it names. `docs/ohush/swarm/MASTER_RESEARCH_STATUS.md` is dated 14 October and is stale in two places: the 53-clip table is no longer empty, and Universal v5 is still not authorized.

Champion: no mute. Research baseline: Universal v1. Playback stays play.

## How to read a number

Times in `experiments/annotations/truth_events.jsonl` are seconds on the recording. August Hulu experiment time is that clock minus 300 s. Feature parquets for `hush_20260827_135935` use the experiment clock. Thursday's live-engine `t` is not the gold clock. Do not score `decisions.jsonl` as commercial accuracy.

A `fully_annotated` coverage range means the span was heard. No commercial inside it means no commercial. Precision outside those ranges is not a result. Candidate reviews are not exhaustive negatives.

Python is `.venv/bin/python`. System `python3` does not have the research packages.

## Datasets you may read

| File | What it is |
| --- | --- |
| `experiments/annotations/truth_events.jsonl` | Gold events. Do not edit. |
| `experiments/gold/GOLD_DEV_V1.json` | ESPN `hush_20260914_212529`, 0–6899 s. Development. |
| `experiments/gold/GOLD_REPLICATION_V1.json` | Prime `hush_20260924_220624`, 0–7600 s. August Hulu `hush_20260827_135935`, recording 300–7200 s. |
| `experiments/gold/GOLD_DATASET_20261013.json` | Nine fully annotated spans. October games in this file were already inspected. Do not fit a threshold on them. |
| `experiments/gold/DATASETS_V1.json` | Roles. Holdouts are named there. |
| `experiments/SESSION_CATALOG.csv` | Network and content type. |
| `docs/ohush/swarm/adjudication/judgments.jsonl` | 248 saves, 53 clips. Latest row per id wins. |
| `docs/ohush/swarm/adjudication/queue_key.json` | Unblinds those clips. Do not copy it into a page the reviewer fetches. |
| `docs/ohush/research/BOUNDARY_EVIDENCE_001/adjudication_coding.json` | The coding of those words. |
| `docs/ohush/research/BOUNDARY_EVIDENCE_001/cue_table.csv` | One row per clip. |

`GOLD_DATASET_20261013.json` spans:

| Session | Range | Role in the work |
| --- | --- | --- |
| `hush_20261007_220650` | 20–11751 s | October Hulu. Inspected. Not a blind test. |
| `hush_20260909_213047` | 0–9373 s | NBC. Exp003 replication and the missed AWS break at 240 s. |
| `hush_20260913_150934` | 0–7200 s | FOX RedZone. Negative control. Zero commercials. |
| `hush_20260913_210542` | 0–12600 s | NBC. Frozen-return replication. |
| `hush_20261008_205100` | 0–10440 s | Thursday Prime Video. Gold clock, not the live-engine clock. |
| `hush_20261010_222400` | 0–6065 s | Cable. Inspected. |
| `hush_20261011_135700` | 0–4897 s | Cable afternoon. Inspected. |
| `hush_20261011_204300` | 0–14405 s | Cable night. Inspected. |
| `hush_20261012_204200` | 0–13112 s | Monday cable. Inspected. |

Sealed. Do not listen, do not tune, do not cite a score you computed from them: `hush_20260917_205513`, `hush_20260920_200635`.

Frozen feature caches, already computed. Do not re-embed.

| Cache | Sessions that have it | Clock |
| --- | --- | --- |
| `experiments/exp002/<session>/speaker_timeline.parquet` | ESPN, Prime, August Hulu | Hulu is experiment time |
| `experiments/exp003/<session>/program_cloud.parquet` | same | same |
| `experiments/exp003b/<session>/frozen_timeline.parquet` and `freezes.json` | same | same |
| `experiments/exp005/<session>/semantic.parquet` and `semantic_embeddings.npy` | same | same |

Large WAV trees and the CNN14 checkpoint are on disk. Do not re-decode them to answer a question a parquet or a report already answers.

## Verdicts

Each line is closed unless the status says otherwise. Do not reopen it by changing its threshold.

| Experiment | Status | Result | Read |
| --- | --- | --- | --- |
| Universal v1 | Research baseline. Not a mute. | Football: hears 17,530.7 commercial seconds, covers 25.0, covers 0 program seconds, touches 2 of 136 pods, lets go of both while the ad is still playing. Enrollment is label-informed. Count 10 is an ablation, not the policy. | `docs/ohush/research/UNIVERSAL_V1/REPORT.md` |
| Universal v2 | Fail. Retired as an action. | Mel logistic did not clear the development gate. Selected policy stays play. | `docs/ohush/research/UNIVERSAL_V2_CONTENT_STATE_001/REPORT.md` |
| Universal v3 embeddings | Fail. | CNN14 penultimate, thresholds from earlier games, covers 0 new commercial seconds on October and loses v1's 25.0 s. October is not blind. | `docs/ohush/research/UNIVERSAL_V3_EMBEDDINGS_001/REPORT.md` |
| Universal v3 speech | Not a policy. | 12 of 136 football pods have a strong phrase in the 30 s before the start. The recognizer knew 3 of those before the start. Phrases also occur in ads and once on RedZone. | `docs/ohush/research/UNIVERSAL_V3_SPEECH_001/REPORT.md` |
| Universal v4 sequence | Fail. | No feature set covered any commercial audio inside 10 program seconds on the calibration games. The rule never fires. RedZone was a training negative. | `docs/ohush/research/UNIVERSAL_V4_BROADCAST_SEQUENCE_001/REPORT.md` |
| Speaker enrollment | Not measured. | Verified enrollments: 0. `.booth.json` is not an enrollment. | `docs/ohush/research/UNIVERSAL_V4_SPEAKER_ENROLLMENT_001/REPORT.md` |
| Exp002 | Closed. Departure candidate. Return negative. | ESPN only. 12 of 13 evaluable starts collapse within 15 s. Median latency 9.6 s. About 4.2 collapses an hour in program. The 30 s absence-then-match return rule did not earn a place. | `experiments/exp002/EXP002_RESULT.md` |
| Exp003 / Exp003b | Measured on ESPN. Not closed. | Freeze: 99th percentile of the prior 10 min, 3 of 5 seconds. Snapshot (T−210, T−30]. 6 of 14 scorable starts freeze within 60 s. Two freezes sit outside pods, 1.4 per program hour. | `experiments/exp003b/EXP003B_RESULT.md` |
| Audio-signal replication | Inconclusive. | NBC `hush_20260909_213047`. Exp003 distance rises after 18 of 19 starts. The frozen causal point crosses within 30 s on 9 of 19, and five of those nine still contain pre-break audio. | `docs/ohush/research/AUDIO_SIGNAL_REPLICATION_001/REPORT.md` |
| Frozen-return replication | Inconclusive. | NBC plus RedZone. Oracle frozen distance can separate ads from the return. Reaching the snapshot's own self-distance is slow. Causal freeze acquisition is not a majority. | `docs/ohush/research/FROZEN_RETURN_REPLICATION_001/REPORT.md` |
| IDENTITY-RETURN-001 | Negative for a return switch. | ESPN, Prime, August Hulu. Oracle acoustic recovery medians about 34 s, 56 s, and 39 s. Announcer by 10 s: 5/10, 1/9, 5/11. Clean causal departure: 4/14, 2/12, 1/11. | `docs/ohush/research/IDENTITY_RETURN_001/IDENTITY_RETURN_001.md` |
| Known-ad fingerprint | Inconclusive. | Count 10: 13 of 41 evaluation DSP misses within 5 s, and about 2.08 false identifications per probed program hour. Count 200: 0 of 121 evaluation openings within 5 s, and 0 false identifications on that grid. A match is not a program return. | `docs/ohush/research/KNOWN_AD_FINGERPRINT_001/REPORT.md` |
| DSP ceiling | Accounting, not a timeline. | 86/136 football starts within 3 s. 50 missed pods still hold 6,406.8 ad seconds. Using the stream as the mute would hide 5,862 s of football and 1,369 s of RedZone. Median hit delay 1.12 s. | `docs/ohush/research/CONTINUOUS_DSP_001/REPORT.md` and `docs/ohush/swarm/MASTER_RESEARCH_STATUS.md` |
| Continuous DSP | Inconclusive as a mute. | Same scan. Ends: 63/132 within 3 s. RedZone fires more often than football. | `docs/ohush/research/CONTINUOUS_DSP_001/REPORT.md` |
| Candidate verification | Inconclusive. | Fresh DSP episodes were not verified into a policy. | `docs/ohush/research/CANDIDATE_VERIFICATION_001/REPORT.md` |
| Micro-production cuts | Level change supported. Short recoverable dip refuted. | A 10 ms frame at or below −60 dB is within ±0.5 s of 103/136 football starts. The 40 ms rule credits 4/136 starts within 1 s and fires 134 times an hour in football program. | `docs/ohush/research/FIRST_PRINCIPLES_BROADCAST_V2/EXP_01_MICRO_PRODUCTION_CUTS/REPORT.md` |
| Microgap census | Negative. Closed. | Absolute 5 ms silence is not a universal mute. Hulu and Prime cuts are deeper than the show. ESPN is not. No floor is an operating point. Stereo check did not rescue it. | `docs/ohush/research/MICROGAP_CENSUS_001/REPORT.md` |
| Sign-off phrases | Sparse cue. Not a policy. | 12/133 football starts, 0/135 sampled program controls, 0/40 RedZone windows. Six of the twelve are one Monday game. | `docs/ohush/research/FIRST_PRINCIPLES_BROADCAST_V2/EXP_03_HANDOFF_LANGUAGE/REPORT.md` |
| Game clock / tv timeout | Not measured. | Sportradar documents `tv_timeout`. None were retrieved. nflverse 2026 has team timeouts and no `tv_timeout`. | `docs/ohush/research/FIRST_PRINCIPLES_BROADCAST_V2/EXP_02_GAME_STATE/REPORT.md` |
| Batch 1 forensics | Inconclusive. | Flatness, RMS, and centroid mark 103/164 starts. A 3× flux splice marks nothing. RedZone still fires. | `docs/ohush/research/BROADCAST_INTELLIGENCE_001/REPORT.md` |
| Boundary listens | Done for 53 clips. | DSP misses are not a 200 ms label error. One program control is a real missed AWS break at NBC 240 s. Pod interiors are still ads. The 20-clip `/returns` page has no judgments. | `docs/ohush/research/BOUNDARY_EVIDENCE_001/REPORT.md` |
| Live recovery | Engine defects, not a commercial score. | Permanent booth veto, false booth return, and synthetic speaker ids are proven on the defect peak. Thursday has no interval gold. 32 clock resets. Do not concatenate runs. | `docs/ohush/experiments/LIVE_RECOVERY_001/REPORT.md` and `docs/ohush/research/MEASUREMENT_STOPPING_POINT_002.md` |

## Error that is still user-visible

From the 14 October ledger, in commercial seconds or program seconds. Later work did not remove these. It retired ways of removing them.

1. 6,406.8 ad seconds in 50 football pods with no DSP hit inside 3 s.
2. 5,862 s of football program, 3,993 episodes, if that DSP stream were the mute.
3. 1,369 s of RedZone if the same policy ran there.
4. Return latency. The ceiling pretends the gold end is known. Every measured return signal is slower than a product can be, or it is not causal.
5. Universal v1's 25 covered seconds are real and small, and both of those pods are released while the ad continues.
6. One gold miss found by ear: NBC `hush_20260909_213047` at 240 s. Not yet searched as a class. The ledger was not changed.

## What is already ruled out

Do not bring these back as the next build.

- Another absolute silence floor, including microgap.
- The 40 ms recoverable dip as a mute.
- CNN14 distance or penultimate embeddings as a gate, refit on these tapes.
- The v2 mel logistic, refit on October.
- The v4 lagged-feature action policy.
- Exp002's "absent 30 s, then any recurring speaker" return rule.
- A frozen acoustic or semantic self-distance as the unmute.
- Fingerprint count 10 as the baseline. It already missed its false-identification budget off ESPN.
- A stricter ad-fingerprint count as a return detector. Count 200 is already clean and already silent at 5 s. Disappearance of an ad match was not scored, and would not prove the game is back.
- Treating `.booth.json` or a cluster id as a verified announcer.

## Files that disagree on purpose

- Master status §8 and §10 say the listen table is empty. `BOUNDARY_EVIDENCE_001/REPORT.md` filled it on 15 October.
- `GOLD_DATASET_20261013.json` has a file-level sentence that the spans are empty until heard. The coverage rows say `fully_annotated: true`. Trust the row.
- Oracle-start numbers in IDENTITY-RETURN-001 use the gold start to place a reference. They are a diagnostic. They are not system performance.
- The DSP "within 3 s, pretending the gold end is known" line is a ceiling. It is not a causal mute.
- Universal v1 enrollment uses gold commercials from other recordings. The decision does not read future audio. The 25 seconds are not a blind-library result.
