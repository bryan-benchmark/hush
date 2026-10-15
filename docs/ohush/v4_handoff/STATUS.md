# Accuracy handoff — 14 October 2026, Universal v4

Read this file, then `docs/ohush/research/UNIVERSAL_V4_BROADCAST_SEQUENCE_001/REPORT.md`, then `results.json` in that folder. A row in the json is stronger than a sentence in the report. Universal v1, v2, and v3 were not rewritten for this packet.

Champion: no authorized mute. Research baseline: Universal v1. Universal v2: **FAIL**, closed. Universal v3 embeddings: **FAIL**, closed. Universal v4 sequence: **FAIL**. Speaker enrollment: **NOT MEASURED**. Enhanced has no accuracy number.

October was already inspected. Fresh recordings in this run: 0. This is not a blind validation, and it is not a 99.99% result.

## Denominator

| Quantity | Seconds |
| --- | ---: |
| Gross coverage, nine football ranges | 85,391.084 |
| Scorable commercials | 17,555.716 |
| Scorable program | 67,560.368 |
| Read failures | 275.000 |

The published 67,428 is `18.73 × 3600`. 99.99% of the gross coverage is 8.539 s.

| Policy | Scorable commercial seconds heard |
| --- | ---: |
| No cover | 17,555.7 |
| Universal v1 | 17,530.7 |
| Universal v2, selected | 17,555.7 |
| Universal v3 embeddings, selected | 17,555.7 |
| Universal v4 sequence, selected | 17,555.7 |

v1's 25.0 covered seconds are 20.0 on Prime Video and 5.0 on cable. v4 covers none of them. Net versus v1: −25.0. Newly covered: 0.0.

## Universal v4 sequence

Script: `experiments/universal_v4/sequence.py`. Report: `docs/ohush/research/UNIVERSAL_V4_BROADCAST_SEQUENCE_001/`.

Three heads, trained on Sept 9 NBC, Sept 24 Prime, and RedZone as a negative. Thresholds: Sept 13 NBC and ESPN only. October did not choose the threshold or the feature set.

| Head | Positive training seconds |
| --- | ---: |
| depart_advance, a gold start in the next 10 seconds | 314 |
| depart_cut, a gold start in the past 1 second | 32 |
| return_cut, a gold end in the past 1 second | 32 |

One Prime Video pod starts at 1.618 seconds, before the first legal decision at 3.0 seconds. The features need 2.5 seconds of past audio.

The frozen CNN14 probability was checked before use: calibration bin 0.9–1.0, 191 windows, 74.3% commercial. It is an input to these heads. It is not a rerun of the v3 mute grid. The 18 dB micro-dip gate was not applied.

No feature set had a calibration point that covers commercial audio and stays within 10 program seconds. The tie at zero stays with the delay line plus the frozen probability. The selected thresholds are 1.1, which do not fire. `frontier_improved_on_calibration` is false.

Not selected. Least program spent while covering any commercial audio:

| Feature set | Commercial seconds | Program seconds | Incidents | Worst interruption |
| --- | ---: | ---: | ---: | ---: |
| Delay line, no CNN14 probability | 21.8 | 35.2 | 11 | 13.0 s |
| One-to-two second context | 195.0 | 229.0 | 2 | 228.0 s |
| Delay line plus frozen probability | 71.8 | 955.2 | 9 | 671.1 s |
| Subsecond change | 2,914.9 | 9,346.1 | 21 | 2,779.1 s |

The frozen probability alone, through these heads, never covers a commercial on the calibration grid.

RedZone program covered under the selected rule: 0. RedZone was a training negative, and the rule never covers anything.

Gold was not edited. Adjudication judgments applied: 0. Replays and booth transitions are not classes in the frozen gold.

## Not finished, and not in this zip

The 5-second speech scan is still running. It is evidence, not a mute, and it has no result yet. Partial transcripts are excluded so they are not audited as a finished count.

Verified speaker enrollments: 0. `.booth.json`, cluster ids, and `booth_present` were not read. See `docs/ohush/research/UNIVERSAL_V4_SPEAKER_ENROLLMENT_001/`.

## Not in this zip

WAV files, the CNN14 embedding cache, the v4 acoustic-feature cache, booth audio, `.booth.json`, the live mute engine, sealed holdouts `hush_20260917_205513` and `hush_20260920_200635`, the blinded adjudication key, and the unfinished 5-second transcripts.
