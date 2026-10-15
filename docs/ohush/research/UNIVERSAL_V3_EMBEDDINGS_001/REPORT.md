# Universal v3 embeddings

Verdict: **FAIL**. No calibration point covers commercial audio inside the 10-second program cap. The named grid point never fires, so the playback rule is play. It is not a mute, and it is not a 99.99% result.

Universal v1 stays the research baseline. Universal v2 was not refit. The CNN14 anomaly distance, the fingerprint count, and the DSP thresholds were not changed. Sealed holdouts were not opened. Booth files were not read. Enhanced still has no accuracy number.

October was already inspected, so this evaluation is not blind. Fresh recordings in this run: 0.

| Artifact | sha256 |
| --- | --- |
| `experiments/universal_v3/embeddings.py` | `f4d12dabfc4dbb3e5c607f1e39615b799176cf9b7b96b14d9347fa4763fc4bc6` |
| `results.json` | `d4a58589ce3abce6f3df923c5844fe913d3775d8e23ae1298fd4b693c1829b1f` |

Command: `NUMBA_CACHE_DIR=/tmp/numba MPLCONFIGDIR=/tmp/mpl PYTHONPATH=src:. experiments/exp003/.venv/bin/python experiments/universal_v3/embeddings.py`

Wall clock 4,098.3 s. The vector is the L2-normalized CNN14 penultimate embedding. The AudioSet head was discarded. The anomaly distance was not computed. Window 10 s, hop 10 s, both fixed before any score was read. A decision at time t uses `[t-10, t)` and applies to later audio.

Train prototypes: Sept 9 NBC and Sept 24 Prime. 1,671 labeled windows, 455 commercial and 1,216 program. Windows with a partial commercial overlap were dropped. The score is the cosine to the commercial mean minus the cosine to the program mean. Those two means themselves have cosine 0.835. A two-parameter logistic maps the score to a probability on the train windows only.

Thresholds: Sept 13 NBC and ESPN only. The grid and the 10-second program cap are the same rule as v2. October was not used to choose a threshold.

Read failures reproduced before the score was accepted: Thursday 240.0 s, Sunday night 35.0 s.

## Selected point

Every grid point that stays within 10 program seconds covers 0 commercial seconds. The tie-break names `T_high` 0.999 and `T_low` 0.05. That point also covers 0 program seconds. It is play.

## October comparison with v1

Scorable commercial audio on the five October football recordings is the same clock as v2. v1 covers 25.0 s there. This policy covers none of it.

| Metric | Result |
| --- | ---: |
| Newly covered commercial seconds | 0.0 |
| Previously covered seconds lost | 25.0 |
| Net versus v1 | −25.0 |
| Programming incorrectly covered | 0.0 |
| False-cover incidents | 0 |
| False-cover duration | 0.0 s |
| Broadcasters with a net gain | none |

The lost 25.0 s is 20.0 s on Prime Video and 5.0 s on cable. Across all scorable football commercials the policy hears 17,555.7 s and covers 0.

The development gate required a net gain of at least 1,000 commercial seconds, at most 10 program seconds, and a gain on at least two broadcasters. The gate is not met.

RedZone, under this same non-firing rule, has 0 program seconds covered. That does not show the embedding is safe on RedZone. The rule never covers anything.

DSP-missed starts under the selected rule: 0 of 50.

## What the scores actually do

These rows were not selected. They are the calibration frontier.

The only points that cover any commercial audio use `T_high` 0.90. The least program among them is `T_low` 0.40:

| Commercial seconds covered | Program seconds covered | False-cover incidents | Worst interruption |
| ---: | ---: | ---: | ---: |
| 3,406.6 | 2,432.4 | 40 | 280.0 s |

At `T_high` 0.95 the commercial coverage drops to 0, and one program stretch remains. There is a single calibration window at or above 0.95: NBC `hush_20260913_210542`, window ending at 12,230 s, probability 0.957, commercial overlap 0. Holding that decision until the score falls covers 160 s to 370 s of program, depending on the return threshold, and no commercial audio.

Calibration reliability, windows with a pure label:

| Score bin | Windows | Share that are commercial |
| --- | ---: | ---: |
| 0.0–0.1 | 655 | 0.0% |
| 0.8–0.9 | 273 | 70.7% |
| 0.9–1.0 | 191 | 74.3% |

The top bin is not a high-confidence mute probability.

Descriptive count, not a policy: 44 of the 50 DSP-missed pods contain a window at or above 0.9, and none reach 0.95. The 0.9 threshold is the calibration point that hides 2,432.4 program seconds. It was not selected, and it is not a detection result.

Meeting the development gate would still not be a 99.99% claim or a clearance for live use. This candidate does not meet the gate.
