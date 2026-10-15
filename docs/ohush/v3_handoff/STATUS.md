# Accuracy handoff — 14 October 2026, Universal v3

Read this file, then the two v3 reports, then their json. A row in the json is stronger than a sentence in the report. For speech, `chunks.jsonl` is stronger than both. Universal v1 and Universal v2 were not rewritten for this packet.

Champion: no authorized mute. Research baseline: Universal v1, label-informed historical enrollment, causal playback. Universal v2: **FAIL**, closed. Universal v3 embeddings: **FAIL**. Universal v3 speech: evidence, not a policy. Enhanced has no accuracy number.

October was already inspected. Fresh recordings in this run: 0. This is not a blind validation, and it is not a 99.99% claim.

## Denominator

Scorable football audio is the comparison clock. Read failures are neither successes nor failures.

| Quantity | Seconds |
| --- | ---: |
| Gross coverage, nine football ranges | 85,391.084 |
| Gross commercials | 17,648.400 |
| Gross program | 67,742.684 |
| Read failures | 275.000 |
| Missing inside commercials | 92.684 |
| Missing inside program | 182.316 |
| Scorable commercials | 17,555.716 |
| Scorable program | 67,560.368 |

The published 67,428 is `18.73 × 3600`. The DSP integer program total is 67,446 s. 99.99% of the gross coverage is 8.539 s.

| Policy | Scorable commercial seconds heard |
| --- | ---: |
| No cover | 17,555.7 |
| Universal v1 | 17,530.7 |
| Universal v2, selected | 17,555.7 |
| Universal v3 embeddings, selected | 17,555.7 |

v1's 25.0 covered seconds are 20.0 on Prime Video and 5.0 on cable. v2 found no new commercial seconds. Its net versus v1 is −25.0 because those 25.0 were lost. v3 embeddings do the same.

## Universal v3 embeddings

Script: `experiments/universal_v3/embeddings.py`. Report: `docs/ohush/research/UNIVERSAL_V3_EMBEDDINGS_001/`.

The vector is the L2-normalized CNN14 penultimate embedding. The anomaly distance was not computed. Window 10 s, hop 10 s, fixed before any score was read. A decision at time t uses `[t-10, t)` and applies after t.

Train prototypes: Sept 9 NBC and Sept 24 Prime. 1,671 labeled windows, 455 commercial and 1,216 program. The two class means have cosine 0.835. Thresholds: Sept 13 NBC and ESPN only. The grid and the 10-second program cap are the v2 rule. October did not choose the threshold. Read failures reproduced first: Thursday 240.0 s, Sunday night 35.0 s.

Every calibration point inside the 10-second program cap covers 0 commercial seconds. The tie-break names `T_high` 0.999 and `T_low` 0.05. That point also covers 0 program seconds. It is play.

October evaluation versus v1:

| Metric | Seconds or count |
| --- | ---: |
| Newly covered commercial seconds | 0.0 |
| Previously covered seconds lost | 25.0 |
| Net versus v1 | −25.0 |
| Program seconds covered | 0.0 |
| False-cover incidents | 0 |
| Broadcasters with a net gain | none |
| DSP-missed starts detected | 0 of 50 |

The development gate required a net gain of at least 1,000 commercial seconds, at most 10 program seconds, and a gain on at least two broadcasters. The gate is not met.

Not selected, calibration only: the least-program point that covers any commercial audio is `T_high` 0.90, `T_low` 0.40, with 3,406.6 commercial seconds and 2,432.4 program seconds, 40 incidents, worst interruption 280.0 s. One calibration window reaches 0.95: NBC `hush_20260913_210542`, window ending 12,230 s, probability 0.957, commercial overlap 0. The 0.9–1.0 reliability bin is 191 windows and 74.3% commercial.

Descriptive, not a policy: 44 of the 50 DSP-missed pods contain a window at or above 0.9. None reach 0.95.

RedZone program covered under the selected rule: 0. That does not show the embedding is safe there. The rule never covers anything.

## Universal v3 speech

Script: `experiments/universal_v3/speech_evidence.py`. Report: `docs/ohush/research/UNIVERSAL_V3_SPEECH_001/`. Transcripts: `chunks.jsonl`, `chunks_a.jsonl`, `chunks_b.jsonl`, `chunks_c.jsonl`.

Not a mute. No threshold was chosen. faster-whisper `base.en`, int8, CPU, beam 1, VAD off. Chunks are 20 seconds, back to back, on all ten sports recordings including RedZone. Gold was not used to place the chunks. The spoken time is the end of the completing word. The recognizer emits the chunk only at the chunk end.

136 football pods. 25 strong phrase rows, 18 distinct football moments, because some sentences match two list entries. 12 moments have the words finishing in the 30 seconds before a gold start. The recognizer finished before that start for 3 of the 12:

| Source | Phrase | Words finished before the start | Recognizer finished before the start |
| --- | --- | ---: | ---: |
| NBC, Sept 9 | after these messages | 3.8 s | 1.0 s |
| Prime Video, Oct 8 | these messages | 18.7 s | 2.6 s |
| Cable, Oct 12 | when we come back | 7.3 s | 4.3 s |

`strong_events_at_least_15s_from_every_pod` is 10 phrase rows, 8 moments. Two of those moments are also inside the 30-second lead window, because they sit 15 to 30 seconds before a start: Prime Video at 8,783.9 s and Monday cable at 2,542.3 s. The other six are the lines the report treats as not a 30-second warning. RedZone has 3 phrase rows and 1 moment. The host says "we'll be right back" and keeps talking. That file has no gold commercials in its two annotated hours.

Five of the twelve spoken-early moments are Monday cable. One of the twelve reads as a garble ("yards back after this"). ESPN and September 24 Prime have no strong moment in the 30-second window.

## Not in this zip

WAV files, the CNN14 embedding cache, booth audio, `.booth.json`, the live mute engine, sealed holdouts `hush_20260917_205513` and `hush_20260920_200635`, and the blinded adjudication key.
