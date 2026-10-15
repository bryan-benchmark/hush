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

All three closed spans are 48 kHz stereo PCM_16, and the scored sample counts match `session.json` except Prime `audio_0009.wav`, which is 16 frames (0.3 ms) longer than the session line. That tail is past the closed span, which ends at 7,600 s. File joins are not the notch.

## Decision

Keep the notch as a description of some joins. Do not advance it to a mute, and do not retune EXP-01. The 2018 Portuguese result remains a different corpus. No threshold here is both specific and present on all three closed recordings.
