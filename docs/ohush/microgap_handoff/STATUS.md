# Microgap packet — 14 October 2026

Playback stays play. Universal v1 was not edited. October was not scored. Holdouts `hush_20260917_205513` and `hush_20260920_200635` were not opened and are not in this zip. Git HEAD is `eedcb444c2546e06f6b3cea16dc2efb92b8d6506`. The working tree is dirty. This packet is not a commit.

The screenshot of a waveform notch has no time scale. The numbers below are from the closed recordings.

## What was run

1. Unit check. A synthetic 50 ms digital hole in loud noise is one run below −80 dB. The census window is 240 samples, which is 5 ms at 48 kHz. Output: `unit_test.txt`.
2. Five-millisecond absolute census on three closed sessions only. Thresholds −120, −100, −85, −70, −55, −40 dBFS were fixed in `code/scan.py` before the audio was read. No row was selected afterward. Output: `census/results.json`, narrative in `census/REPORT.md`.
3. Format receipt and a separate 30 ms RMS check at −80 dBFS. `ffmpeg` is not on this machine, so this is not an ffmpeg log. Output: `census/corroboration.json`.
4. Prior results were hashed, not rerun. EXP-01 (the 2018-style short dip) stays NOT_MET. The known-ad fingerprint stays INCONCLUSIVE.

## Closed sessions

| Session | Service | Closed span | Pods |
| --- | --- | --- | ---: |
| hush_20260827_135935 | Hulu | 300–7200 s | 11 |
| hush_20260914_212529 | ESPN | 0–6899 s | 15 |
| hush_20260924_220624 | Prime | 0–7600 s | 13 |

All overlapping chunks are 48 kHz stereo PCM_16. Frame counts match `session.json` except Prime `audio_0009.wav`, 16 frames longer than its session line. The closed span ends at 7,600 s, before that tail.

## Census, descriptive floor

Deepest 5 ms within ±0.25 s of a commercial start, versus program half-seconds at least 2 s from every pod.

| Service | Start median | Program median |
| --- | ---: | ---: |
| Hulu | −102 dB | −53 dB |
| Prime | −91 dB | −46 dB |
| ESPN | −45 dB | −36 dB |

## Census, −85 dB, and the separate −80 dB / 30 ms check

Causal means the silence run finishes after the label and within 1 s. Descriptive means the run overlaps ±0.25 s, which can see both sides.

| Check | Service | Program / hour | Inside break / hour | Causal starts | Descriptive starts |
| --- | --- | ---: | ---: | ---: | ---: |
| 5 ms, −85 dB | Hulu | 5.37 | 276.00 | 5 / 11 | 10 / 11 |
| 5 ms, −85 dB | ESPN | 72.78 | 369.17 | 1 / 15 | 2 / 15 |
| 5 ms, −85 dB | Prime | 4.25 | 240.09 | 7 / 13 | 9 / 13 |
| 30 ms, −80 dB | Hulu | 1.79 | 146.36 | 5 / 11 | 10 / 11 |
| 30 ms, −80 dB | ESPN | 51.58 | 93.79 | 1 / 15 | 2 / 15 |
| 30 ms, −80 dB | Prime | 3.64 | 93.01 | 4 / 13 | 9 / 13 |

At −85 dB and below, the 5 ms census attributes zero events to file-chunk joins.

## Decisions

| Branch | Decision |
| --- | --- |
| B01 absolute near-silence | Retain as a description of some Hulu and Prime joins. Kill as a mute. ESPN has no matching hole, and every floor that catches ESPN fires thousands of times an hour in the game. |
| EXP-01 relative short dip | Already NOT_MET. Do not retune. |
| B03 known-ad fingerprint | Already INCONCLUSIVE. Not rerun. A match is not a program return. |
| B07 SCTE-35 | Not run. No authorized feed. Enhanced only. It is not in the optical PCM. |
| Live controller | Not touched. |

A correct boundary would still not say whether the break is starting, changing ads, or ending. The inside-break rates above are the evidence for that.
