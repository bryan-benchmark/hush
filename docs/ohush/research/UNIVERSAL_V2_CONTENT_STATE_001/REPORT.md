# Universal v2 content state

Verdict: **FAIL**. The selected policy is play. It is not a promoted mute, and Enhanced has no accuracy number.

Universal v1 is unchanged. Its name for this record is label-informed historical enrollment with a causal playback rule. This run did not rewrite its report, results, or receipts.

| Artifact | sha256 |
| --- | --- |
| `experiments/universal_v2/content_state.py` | `b9b14dce9e55d44e418b3cb1fc2a514700d660790fe98b19b7ddef5e735b0d7c` |
| `experiments/universal_v2/test_landmark_window.py` | `731f49e1d3f55827fd650b107c0e6df263636d407a1e953c4122c33910e12dcf` |
| `results.json` | `58783bf66b7f482af1e2869821e72de89c43e72f343a2181129fe700eb02e4bd` |

Command: `MPLCONFIGDIR=/tmp/mpl PYTHONPATH=src:. .venv/bin/python experiments/universal_v2/content_state.py`

The landmark test, run first: `PYTHONPATH="src:.:experiments/broadcast_intelligence/third_party/audfprint" .venv/bin/python -m unittest experiments.universal_v2.test_landmark_window`. Two tests, both passed. A landmark whose second peak lands on the decision frame is dropped. A landmark whose peaks both sit inside the query is kept. `window_hashes` is the function Universal v1 calls. The v1 receipts do not store peak times, so this is a replay of that gate, not a second pass over all 22,229 queries.

Wall clock 160.5 s.

## Denominator

These are the football recordings, RedZone excluded.

| Quantity | Seconds |
| --- | ---: |
| Gross coverage, nine capture ranges | 85,391.084 |
| Gross commercials | 17,648.400 |
| Gross program | 67,742.684 |
| Read failures | 275.000 |
| Of those, inside commercials | 92.684 |
| Of those, inside program | 182.316 |
| Scorable commercials | 17,555.716 |
| Scorable program | 67,560.368 |

The published 67,428 is `18.73 × 3600`. The DSP scan's integer program total is 67,446 s. `67,446 / 3600` is 18.735 hours, which rounds to 18.73, and multiplying back loses 18 seconds. That figure is also a different clock from the continuous gold spans: integer seconds, and a 417 s Thursday hole rather than the 240 s of reads that actually failed.

99.99% of the gross coverage is 8.539 s. The published 8.51 s used the rounded hour figure. Later comparisons in this report use scorable seconds only. Missing audio is neither a success nor a failure.

Like-for-like commercial exposure:

| Policy | Scorable commercial seconds heard |
| --- | ---: |
| No cover | 17,555.7 |
| Universal v1 | 17,530.7 |
| Universal v2, selected | 17,555.7 |

v1's improvement over no cover is 25.0 s. v2's selected policy gives those 25 s back.

## What was fit

Train, labels allowed: Sept 9 NBC and Sept 24 Prime. 3,362 non-overlapping 5 s windows, 904 commercial and 2,458 program. Boundary windows and read failures were left out of the fit.

Calibrate, threshold only: Sept 13 NBC and ESPN. Evaluate, no fitting: Oct 8 Prime Video and the four October cable recordings. RedZone and both Hulu files were scored and not used to choose anything.

The model is a class-balanced L2 logistic regression on five one-second summaries: 32 log-mel bins normalized to a shape, loudness, spectral flatness, and stereo correlation. A decision at time t uses `[t-5, t)` and applies after t. Cover requires `p(commercial) ≥ T_high`. Play requires `p(commercial) ≤ T_low`. Anything between holds the previous action. DSP, fingerprints, booth files, gold ends, and external feeds are not inputs.

The grid was `T_high` in 0.90, 0.95, 0.97, 0.99, 0.995, 0.999 and `T_low` in 0.05, 0.10, 0.20, 0.30, 0.40, with an unknown band of at least 0.20. The rule was: on the calibration games, take the most commercial seconds covered subject to at most 10 program seconds, then fewer incidents, then the higher `T_high`. If none qualify, stay on play.

## Gate

No calibration point stayed within 10 program seconds. The least costly point, `T_high` 0.999 and `T_low` 0.40, covered 1,315.0 commercial seconds and 659.0 program seconds, in 16 incidents, worst stretch 138.0 s. The selected policy is therefore play.

On the evaluation recordings that policy covers 0 commercial seconds and 0 program seconds. Universal v1 covers 25.0 commercial seconds there and 0 program seconds. Additional commercial seconds versus v1: 0. Broadcasters with a gain inside the cap: none. RedZone program covered: 0. Scripted program covered: 0.

The gate required 1,000 additional commercial seconds, at most 10 program seconds, and a gain on two sources. It is not met.

The same grid on the October games was written down after the choice and was not allowed to change it. Its least costly point still covers 1,646.1 program seconds to get 2,185.9 commercial seconds, worst stretch 463.0 s. There is no point on that curve inside the cap either.

## The fifty DSP-missed starts

Under the selected policy, 0 of 50 are covered. There is no earliest recognition time, and no evidence before the boundary, because the policy never covers.

A descriptive count, not a second policy: 27 of the 50 contain at least one decision with `p ≥ 0.999`. Using that score as a cover is the calibration point that hides 659 program seconds. The rank order is real. It is not pure enough to act on.

## Calibration

On the calibration games, gold is the audit of the score, not an input. Windows whose overlap with a pod is partial are omitted.

| Predicted p | Windows | Fraction actually commercial |
| --- | ---: | ---: |
| 0.0–0.1 | 8,815 | 0.010 |
| 0.5–0.6 | 697 | 0.283 |
| 0.8–0.9 | 1,194 | 0.622 |
| 0.9–1.0 | 3,394 | 0.704 |

A score of 0.95 is not a 95% chance the window is a commercial. The top bin is about 70% commercial. Holding a cover until the score falls is what turns the remaining 30% into stretches of hidden programming.

## Evidence

| Source | In the selected action | What it did |
| --- | --- | --- |
| Mel logistic | yes | No grid point met the program cap, so the action stayed play |
| Chronological fingerprint | no | v1's 25 s are not reproduced |
| DSP alarm | no | 0 of 50 missed starts covered |
| CNN14 embedding vector | not measured | Stored series are anomaly scores. October football has none. Torch is not installed |
| Audio-text model | not measured | No checkpoint is installed |
| Full-stream speech recognition | not measured | The sign-off transcripts are still gold-neighborhood only |
| Verified announcer | not measured | Enrollment count is 0. Booth files were not read |
| External feed | not measured | No Enhanced number |

## Largest viewer-seconds under the selected policy

The policy hides nothing, so the largest errors are commercials that play through. The first twenty scorable remainders:

| Seconds heard | Session | Pod start |
| ---: | --- | ---: |
| 417.9 | Sept 13 NBC | 6838.403 |
| 386.0 | Oct 10 cable | 3567.641 |
| 244.9 | Sept 13 NBC | 3470.982 |
| 228.6 | ESPN | 1538.857 |
| 222.2 | Oct 12 cable | 3737.485 |
| 207.8 | Sept 9 NBC | 7641.664 |
| 198.2 | Oct 12 cable | 12194.922 |
| 197.0 | Oct 8 Prime Video | 139.874 |
| 195.9 | Sept 13 NBC | 9187.148 |
| 195.9 | Oct 10 cable | 2369.207 |
| 195.5 | Oct 10 cable | 3009.899 |
| 187.2 | Sept 9 NBC | 8020.205 |
| 187.1 | Sept 13 NBC | 3072.966 |
| 183.0 | Sept 9 NBC | 623.347 |
| 180.9 | Sept 9 NBC | 1074.332 |
| 179.0 | Oct 11 afternoon cable | 3735.542 |
| 177.3 | Sept 9 NBC | 7000.981 |
| 171.6 | Sept 9 NBC | 8413.747 |
| 166.4 | Sept 24 Prime | 6854.004 |
| 164.1 | Oct 12 cable | 6254.226 |

The Oct 8 pod at 139.874 s is one of the two v1 covered. This policy hears its scorable 197.0 s.

## Where the policy failed

The acoustic shape separates the bulk of ordinary play (`p` under 0.1 is 1% commercial) from a high-score pile that is still 30% programming. A hold-until-return rule then keeps that programming covered. Raising the threshold inside the predeclared grid never made the pile pure. The 50 missed starts are not structurally invisible to this score, and they are not recoverable under the program cap.

This mel logistic is retired as an action policy. The grid is not to be refit on the October games. The holdouts stay sealed.

## Next measurement

A pretrained embedding, or full-stream speech with causal word times, scored against this same gate: 1,000 additional scorable commercial seconds versus v1, at most 10 program seconds, on at least two sources, with the threshold chosen on earlier games only. Advance break prediction waits until a content score can cover without taking the program with it. Another threshold on this logistic, on the DSP distance, or on fingerprint count 10, is not that measurement.
