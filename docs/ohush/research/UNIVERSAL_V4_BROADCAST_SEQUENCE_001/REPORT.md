# Universal v4 broadcast sequence

Verdict: **FAIL**. The calibrated frontier did not improve. The playback rule stays play. It is not a mute, and it is not a 99.99% result.

Universal v1 stays the research baseline. The 10-second CNN14 prototype, the anomaly-distance gate, the mel logistic, the fingerprint counts, and the 18 dB micro-dip gate were not retuned. October was not used to choose a threshold or a feature set. Sealed holdouts were not opened. Gold was not edited. The 53-clip queue has no judgments, so it was not applied. Enhanced still has no accuracy number.

October was already inspected. Fresh recordings in this run: 0.

| Artifact | sha256 |
| --- | --- |
| `experiments/universal_v4/sequence.py` | `dd5fd0f0779bf805039c16bb9bd193d584ae2ebcbd8702e357bfbc692b7c2788` |
| `results.json` | `8b309ce4ae13491e7991434c38e0917cf3d9bb72fffe5a75f3c62f53083e5e49` |

Command: `MPLCONFIGDIR=/tmp/mpl PYTHONPATH=src:. .venv/bin/python experiments/universal_v4/sequence.py`

## What was trained

Three heads, fit only on Sept 9 NBC, Sept 24 Prime, and RedZone as a negative. RedZone therefore is not an unseen control.

| Head | Positive training seconds | Meaning |
| --- | ---: | --- |
| depart_advance | 314 | A gold start falls in the next 10 seconds. The features end at the decision |
| depart_cut | 32 | A gold start falls in the past 1 second, so the cut has been heard |
| return_cut | 32 | A gold end falls in the past 1 second |

One Prime Video pod starts at 1.618 seconds, before the first decision at 3.0 seconds. The features need 2.5 seconds of past audio, so that pod is outside both cut heads. The other 32 training boundaries have a decision second.

A decision at time t uses audio that ends at t. Departure and return are different heads. A return is not one minus a departure. Replays and booth transitions are not classes in the frozen gold, so they were not a separate negative set. Hard negatives that do exist are ordinary non-events, seconds inside a pod, and RedZone.

The feature sets were a frozen CNN14 probability, a half-second level change plus a 40 ms frame-depth, a one-to-two second flux and flatness, and those acoustics on a delay line at 0, 2, 10, and 30 seconds. The CNN14 probability is the v3 prototype and logistic. Before it was used, the calibration bin was checked: 191 windows, 74.3% commercial. The 18 dB dip rule was not applied. The probability is an input, not a rerun of the v3 mute grid.

## Calibration

Thresholds were chosen on Sept 13 NBC and ESPN only. A point has to cover commercial audio and stay within 10 program seconds. No feature set had such a point.

The tie at zero stays with the preregistered full model, the delay line plus the frozen probability. Its playback rule does not fire.

These rows were not selected. They are the least program each feature set spent while covering any commercial audio.

| Feature set | Commercial seconds | Program seconds | Incidents | Worst interruption |
| --- | ---: | ---: | ---: | ---: |
| Delay line, no CNN14 probability | 21.8 | 35.2 | 11 | 13.0 s |
| One-to-two second context | 195.0 | 229.0 | 2 | 228.0 s |
| Delay line plus frozen probability | 71.8 | 955.2 | 9 | 671.1 s |
| Subsecond change | 2,914.9 | 9,346.1 | 21 | 2,779.1 s |
| Frozen probability alone, through these heads | 0 | — | — | — |

The nearest miss is still 35.2 program seconds, above the 10-second cap, and it covers 21.8 commercial seconds. That is not a policy.

## October

The selected rule covers nothing, so it loses v1's coverage and adds none.

| Metric | Result |
| --- | ---: |
| Newly covered commercial seconds | 0.0 |
| Previously covered seconds lost | 25.0 |
| Net versus v1 | −25.0 |
| Program seconds covered | 0.0 |
| False-cover incidents | 0 |

The lost 25.0 seconds are 20.0 on Prime Video and 5.0 on cable. Across scorable football audio the rule hears 17,555.7 commercial seconds.

RedZone program covered under this non-firing rule: 0. That does not show the sequence is safe on RedZone. The rule never covers anything, and RedZone was already a training negative.

The development gate is not met. A pass would still not be a live mute.
