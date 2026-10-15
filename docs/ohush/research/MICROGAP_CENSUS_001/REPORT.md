# Microgap census 001

Absolute 5 ms silence on three closed recordings. Not a mute. Not a retune of the 2018-style short dip, which already failed its gate in EXP-01.

The screenshot has no time scale. This scan measures the recordings. Windows are 5 ms. The floors are −120, −100, −85, −70, −55, and −40 dBFS, fixed before the audio was scored. No row is an operating point. October was not read. The sealed holdouts were not opened. Playback stays play.

| Session | Service | Pods | Program | Commercials |
| --- | --- | ---: | ---: | ---: |
| hush_20260827_135935 | Hulu | 11 | 6,039 s | 861 s |
| hush_20260914_212529 | ESPN | 15 | 5,095 s | 1,804 s |
| hush_20260924_220624 | Prime | 13 | 5,936 s | 1,664 s |

A descriptive hit means a silence run overlaps the label, so it can see audio on both sides. A causal hit means the run finishes after the label, which is the earliest moment a listener could know the hole had closed. File-chunk joins inside the coverage are counted separately. At −85 dB and below, none of those joins are the events.

## The floor at the cut

Deepest 5 ms inside ±0.25 s of a commercial start, against the deepest 5 ms in program half-seconds at least 2 s from every pod.

| Service | Starts, median floor | Program, median floor |
| --- | ---: | ---: |
| Hulu | −102 dB | −53 dB |
| Prime | −91 dB | −46 dB |
| ESPN | −45 dB | −36 dB |

Hulu and Prime do get quieter at the cut than in the show. ESPN's cut is about as loud as the game.

## What each floor does

Program events per hour are silences whose middle is at least 2 s from every pod. Within-break events per hour sit inside a pod and at least 1 s from both of its edges.

| Service | Floor | Program / hour | Inside the break / hour | Starts, causal within 1 s | Starts, descriptive within 0.25 s |
| --- | ---: | ---: | ---: | ---: | ---: |
| Hulu | −120 | 0 | 0 | 1 / 11 | 1 / 11 |
| Hulu | −100 | 135 | 623 | 5 / 11 | 7 / 11 |
| Hulu | −85 | 5.4 | 276 | 5 / 11 | 10 / 11 |
| Hulu | −70 | 104 | 301 | 6 / 11 | 11 / 11 |
| ESPN | −120 | 0 | 16 | 0 / 15 | 0 / 15 |
| ESPN | −100 | 0.7 | 36 | 0 / 15 | 0 / 15 |
| ESPN | −85 | 73 | 369 | 1 / 15 | 2 / 15 |
| ESPN | −40 | 6,441 | 9,157 | 11 / 15 | 10 / 15 |
| Prime | −120 | 2.4 | 67 | 2 / 13 | 0 / 13 |
| Prime | −100 | 4.9 | 119 | 3 / 13 | 1 / 13 |
| Prime | −85 | 4.3 | 240 | 7 / 13 | 9 / 13 |
| Prime | −70 | 201 | 595 | 6 / 13 | 10 / 13 |

The full grid, including 0.25 / 0.5 / 2 / 5 s and the return side, is in `results.json`.

## Answers

1. A near-silence is common at Hulu and Prime starts. It is not common at ESPN starts. Digital zero (−120 dB) is rare at all three.
2. The same floors fire more often inside the break than in the show. On Prime at −85 dB that is 240 inside versus 4 in the program. A notch does not say whether the break is starting, changing ads, or ending.
3. During the game, ESPN produces about 73 runs an hour at −85 dB. Prime produces about 4. The show is not quiet in the same way on every network.
4. The events are not the recording's file joins. The same optical capture still disagrees by service: Prime's cuts go to about −91 dB and ESPN's stay near −45 dB. That argues against one recorder bug. It does not prove the notch was in the network feed before the television.
5. It does not survive as one cue across ESPN, Prime, and Hulu. A floor quiet enough to be uncommon in a game misses ESPN. A floor loud enough to catch ESPN fires thousands of times an hour.

## Independent check

`ffmpeg` is not installed here, so there is no ffmpeg log. A second scanner, written separately, uses one coarse setting named before this count: 30 ms RMS at or below −80 dBFS. It is not an operating point.

| Service | Program / hour | Inside the break / hour | Starts, causal within 1 s | Starts, descriptive within 0.25 s |
| --- | ---: | ---: | ---: | ---: |
| Hulu | 1.8 | 146 | 5 / 11 | 10 / 11 |
| ESPN | 52 | 94 | 1 / 15 | 2 / 15 |
| Prime | 3.6 | 93 | 4 / 13 | 9 / 13 |

The longer window removes some one-frame blips. ESPN remains dense in the game and almost empty at the cuts. The decision does not change.

## Format

`format_ok` is true for Hulu and ESPN. It is false for Prime. `audio_0009.wav` has 34,554,880 frames and the session line accounts for 34,554,864, a difference of 16 frames, about 0.3 ms. That tail is after the closed span, which ends at 7,600 s. It is still a format failure, and it is kept as one. File joins are not the notch.

## Stereo check

The census averages the two channels before it measures level. Opposite-phase audio could look silent in that average while both channels are loud. A later read of the same −85 dB runs, without moving the threshold or rescoring recall, measures left, right, and stereo energy at the quietest averaged window. `stereo_check.json`.

None of those windows is cancellation-shaped: stereo energy stays within about 2 dB of the average, correlation is not strongly negative, and neither channel is above −40 dB. Where one channel misses −85 dB, its level is still about −80 to −84 dB.

| Service | Runs | Both channels ≤ −85 dB | One channel just above the line | Cancellation-shaped |
| --- | ---: | ---: | ---: | ---: |
| Hulu | 103 | 86 | 17 | 0 |
| ESPN | 409 | 182 | 227 | 0 |
| Prime | 210 | 176 | 34 | 0 |

ESPN's program runs are quiet in both channels: 96 of 103. The false candidates are not a downmix artifact. The negative mute verdict stands.

## Decision

Accepted 15 October 2026. The absolute notch is not a universal mute. Hulu and Prime cuts are deeper than the surrounding show. ESPN is not. Do not refit the floor on these three tapes, do not sweep a missing ffmpeg, and do not combine this cue with the fingerprint into a mute. EXP-01 stays NOT_MET. The fingerprint stays INCONCLUSIVE. Universal v1 stays unchanged. Playback stays play.

The accepted zip `docs/ohush/microgap_handoff/ohush_microgap_2026-10-14.zip` is the audited snapshot. This stereo check and the Prime `format_ok: false` line were written after that audit. They do not replace its receipts.
