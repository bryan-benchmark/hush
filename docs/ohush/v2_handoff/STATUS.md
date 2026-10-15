# Accuracy handoff — 14 October 2026, Universal v2

Read this file, then `docs/ohush/research/UNIVERSAL_V2_CONTENT_STATE_001/REPORT.md`, then `results.json` in that folder. A row in the json is stronger than a sentence in the report. Universal v1's own report was not rewritten.

Champion: no authorized mute. Research baseline: Universal v1, label-informed historical enrollment, causal playback. Universal v2: **FAIL**. Enhanced has no accuracy number.

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

The published 67,428 is `18.73 × 3600`. The DSP integer program total is 67,446 s. `67,446 / 3600` rounds to 18.73, and multiplying back loses 18 seconds. 99.99% of the gross coverage is 8.539 s.

| Policy | Scorable commercial seconds heard |
| --- | ---: |
| No cover | 17,555.7 |
| Universal v1 | 17,530.7 |
| Universal v2, selected | 17,555.7 |

## Universal v2

Train: Sept 9 NBC and Sept 24 Prime. Thresholds: Sept 13 NBC and ESPN only. Evaluation: October Prime Video and the four October cable recordings. RedZone and both Hulu files were scored and did not choose the threshold.

No calibration grid point stayed within 10 program seconds. The least costly point covered 1,315.0 commercial seconds and 659.0 program seconds. The selected policy is play. On the evaluation recordings it covers 0 commercial seconds and 0 program seconds. v1 covers 25.0 commercial seconds there. Additional commercial seconds versus v1: 0. The gate is not met.

On the calibration games, predicted probability 0.9–1.0 is actually commercial on 70.4% of audited windows. The selected policy covers 0 of the 50 DSP-missed starts. A descriptive count, not a second policy: 27 of those 50 contain a decision with `p ≥ 0.999`. Acting on that score is the point that hides 659 program seconds.

The landmark test passed: a second peak on the decision frame is excluded. The v1 receipts do not store peak times, so this is a test of `window_hashes`, the function v1 calls, not a re-read of every query.

## Not in this zip

WAV files, embeddings, booth audio, `.booth.json`, the live mute engine, sealed holdouts `hush_20260917_205513` and `hush_20260920_200635`, and the blinded adjudication key.
