# CONTINUOUS_DSP_001

The three Batch 1 probes were reproduced exactly, then run on every integer second of the 12 closed ranges. No new threshold was chosen. No mute decision was made.

| Artifact | sha256 |
| --- | --- |
| `experiments/broadcast_intelligence/continuous_dsp.py` | `89508da4ac5167e725772d80fe88d788e465d7e55d6306bd24fca6b1be48d417` |
| `docs/ohush/research/CONTINUOUS_DSP_001/results.json` | `83eb24602d8809190a3775660a760421fdb3cca3ca1ec13aa3b68d46c25f684d` |
| `docs/ohush/research/CONTINUOUS_DSP_001/recall_starts.png` | `774a06f4869e2d024d09a57ea5eac94a517a4c29ea3d1fd1a64494150143f274` |
| `docs/ohush/research/CONTINUOUS_DSP_001/program_episodes_per_hour.png` | `dd94bbf0b615805660cc31da639dfec12961d2946d558bef9d4295dcf28f97db` |

Command: `MPLCONFIGDIR=/tmp/mpl PYTHONPATH=src:. .venv/bin/python experiments/broadcast_intelligence/continuous_dsp.py`

Wall time 225.9 seconds. Peak resident memory 641 MB. That is this computer scanning about 31 hours of audio, not a measurement on a small board.

## Verdict: INCONCLUSIVE

The rule was frozen before this scan was read. A side passes when football OR-recall within 3 seconds is at least 0.50, and fails when it is under 0.25.

| Question | Result | Verdict |
| --- | --- | --- |
| Can it nominate football commercial starts without being shown the timestamp? | 86 / 136 within 3 s (0.632) | PASS |
| Can it nominate football commercial ends the same way? | 63 / 132 within 3 s (0.477) | INCONCLUSIVE |
| Both | | INCONCLUSIVE |

This is a candidate generator's score. It is not a mute score. The same OR rule raises about **215 episodes an hour** on ordinary football audio, and **474 an hour** on commercial-free RedZone.

## Phase 1 — the frozen probes match

The slim RMS, flatness, and centroid math matches `acoustics()` on a held window to 1e-9. Recomputing Batch 1's boundary windows and its 45-second program controls reproduces the published counts:

| | RMS | Flatness | Centroid |
| --- | --- | --- | --- |
| Starts over the other-recordings p95 | 71 | 74 | 62 |
| Any of the three | 103 | | |
| Flatness and RMS together | 54 | | |
| Only that feature | RMS 15, flatness 12, centroid 12 | | |
| In-game control windows over the bar | 24 / 440 | 22 / 440 | 19 / 440 |
| RedZone control windows | 1 / 40 | 4 / 40 | 5 / 40 |

The RedZone bars round to the published values 9.79367 dB, 0.077202, and 1652.848264 Hz. The continuous scan uses those same leave-one-recording thresholds. The 5% control-window rates from Batch 1 are not continuous false-alarm rates.

## What "every second" means

For integer t, the probe compares [t−2, t) with [t, t+1) and is available at t+1. A boundary is credited only when some positive t falls in [boundary, boundary+W]. An alarm in the 5 seconds before the boundary is counted as already active and is not credited. Consecutive positive seconds are one episode. Nothing is held, suppressed, or retriggered.

The integer grid is not the Batch 1 window. Batch 1 centered the probe on the gold timestamp. This scan never sees that timestamp.

## 1. Can the three features find boundaries on their own?

Yes for a majority of football starts, within 3 seconds. Not yet for a majority of returns.

Football starts, 136 eligible, none unavailable:

| Window | OR | RMS | Flatness | Centroid |
| --- | --- | --- | --- | --- |
| 1 s | 61 | 28 | 37 | 43 |
| 3 s | 86 | 36 | 68 | 67 |
| 5 s | 94 | 40 | 73 | 74 |
| 10 s | 114 | 47 | 89 | 94 |
| 30 s | 131 | 86 | 119 | 123 |
| Never within 30 s | 5 | 50 | 17 | 13 |

Median delay of the OR hits that land within 30 s is 1.12 s on the candidate clock, so the result is available about a second later. The 95th percentile delay is 22.4 s. Flatness and centroid carry the fast hits (medians 1.8 s and 2.4 s). RMS is slower (median 7.7 s).

Of the 86 starts credited within 3 s, **59 were already alarming in the previous 5 seconds**. An episode actually begins inside that 3-second window for 49 of the 136 starts. The other credited starts are seconds inside an alarm that had already started. Each second is a fresh comparison, not a latch, but the candidate did not turn on at the boundary.

Football ends, 132 eligible. Four ends have no integer t in the next 30 s: Prime Video at 1125.2 s sits in the 417-second hole in `hush_20261008_205100`, and three ends sit on the last second of coverage (`10440.364`, ESPN `6898.920`, Prime `7600.000`).

| Window | OR | RMS | Flatness | Centroid |
| --- | --- | --- | --- | --- |
| 1 s | 44 | 32 | 24 | 24 |
| 3 s | 63 | 51 | 61 | 35 |
| 5 s | 76 | 61 | 47 | 42 |
| 10 s | 86 | 65 | 57 | 54 |
| 30 s | 112 | 83 | 91 | 87 |
| Never within 30 s | 20 | 49 | 41 | 45 |

Median OR delay 1.79 s. 95th percentile 25.4 s. Of the 63 ends credited within 3 s, 53 were already alarming, and 35 have an episode that begins in the window.

By 30 seconds the three features mostly fire on the same starts. Exactly one feature covers a start the other two miss within 30 s in only 12 cases: RMS 2, flatness 3, centroid 7. At 3 seconds the standalone counts are RMS 36, flatness 68, centroid 67, union 86, so the fast coverage is shared by flatness and centroid.

Chart: `recall_starts.png`.

## 2. How many candidates during ordinary football?

On the 9 football recordings that contain commercials, 18.73 hours of program audio:

| | Alarm-seconds per program hour | Fraction of program seconds | Episodes per program hour |
| --- | --- | --- | --- |
| OR of the three | 320.5 | 0.089 | 215.0 |
| RMS alone | 176.2 | 0.049 | |
| Flatness alone | 172.0 | 0.048 | |
| Centroid alone | 169.5 | 0.047 | |

Each feature's continuous program rate is close to the 5% the Batch 1 control sample was built to allow. The OR is what a listener would actually investigate, and it is about 9% of program seconds. Episodes are short: median 1 second, 90th percentile 3 seconds, longest wholly-program episode 18 seconds (Hulu, 7136–7153 s).

Program seconds within 15 s of a commercial boundary alarm at 0.098. Program seconds farther away alarm at 0.088. The candidates are not clustered on the breaks. Show-to-show transitions are not labeled, so that split is the one the gold supports.

The rate depends on the broadcast:

| Recording | Network | Program episodes / hour | Alarm-seconds / hour | Fraction far from any pod |
| --- | --- | --- | --- | --- |
| `hush_20260909_213047` | NBC | 207 | 285 | 0.077 |
| `hush_20260913_210542` | NBC | 198 | 264 | 0.073 |
| `hush_20260924_220624` | Prime | 68 | 91 | 0.022 |
| `hush_20261008_205100` | Prime Video | 49 | 62 | 0.013 |
| `hush_20260914_212529` | ESPN | 344 | 470 | 0.129 |
| `hush_20261012_204200` | Cable | 158 | 208 | 0.058 |
| `hush_20261011_204300` | Cable | 308 | 493 | 0.137 |
| `hush_20261011_135700` | Cable | 251 | 439 | 0.118 |
| `hush_20261010_222400` | Cable | 382 | 646 | 0.178 |
| `hush_20260913_150934` | FOX RedZone | 474 | 685 | 0.190 |
| `hush_20261007_220650` | Hulu, scripted | 336 | 562 | 0.151 |
| `hush_20260827_135935` | Hulu, scripted | 314 | 458 | 0.123 |

Prime is the quiet sports case. Cable, ESPN, and both Hulu recordings are not. Thursday's Prime Video row skips 417 seconds that could not be read; one commercial end falls in that hole.

Of 5,842 OR episodes on football-with-commercials, 50 begin in the 3 seconds after a start and 35 begin in the 3 seconds after an end. That is 1.5% of episodes. The rest begin during program audio (4,034) or in the middle of a pod (1,723).

Chart: `program_episodes_per_hour.png`.

## 3. What happens on RedZone?

`hush_20260913_150934`, 0–7200 s, zero commercials, 7,198 scanned seconds, no missing audio. The OR probe alarms on 1,369 seconds: 474 episodes per hour, 685 alarm-seconds per hour, 19% of the timeline. Median episode length is 1 second, 90th percentile 3, longest 8. Every one of those episodes is a program candidate. There is no commercial for them to land on.

RedZone is a harder negative control than in-game football. A threshold inherited from other broadcasts fires more often when the program itself keeps changing games.

## 4. Can the same signals nominate commercial ends?

They nominate some. 63 of 132 eligible football ends have a positive second within 3 s, and 112 of 132 within 30 s. Twenty ends have none within 30 s.

The last 10 seconds of a pod are positive on 18.7% of those seconds. The first 10 seconds are positive on 19.6%. The middle of the pod, excluding those collars, is positive on 14.7%. Program audio away from pods is positive on 8.8%. A return is a slightly denser moment than the middle of the pod, and the middle of the pod is denser than ordinary play. The three densities sit close together. An alarm at the end of a pod is not distinguishable from an alarm between ads by these features.

The busiest pod is Saturday cable `hush_20261010_222400`, 3567.6–3953.7 s: 60 alarm seconds inside 386 seconds of pod.

## 5. How often do ad-to-ad changes look the same?

On football pods, the middle — the region that is neither the opening nor the closing 10 seconds — alarms on 14.7% of seconds. That is the stand-in for advertisement-to-advertisement changes. Individual spots are not labeled, so a middle alarm is an unexplained change inside a known commercial, not a verified spot boundary.

Those middle alarms are common enough that a return rule of the form "the probe fired, so the game is back" would uncover during ads. 1,723 football episodes begin inside a pod and outside the 3-second return window.

## 6. Are they useful as a fast candidate generator?

As a start finder, yes, with a heavy verification bill. 63% of football starts have a positive second within 3 s, and the typical credited delay is about 1 second on the grid. Flatness and centroid do that work. RMS adds little at 3 seconds.

As something that can mute, no. About 215 short episodes an hour need a second look during football, and RedZone asks for 474. Only 1.5% of episode onsets sit on a real boundary. Keeping the break-duration distribution as a prior still makes sense: it says when a return is plausible. It does not decide the return. This scan does not change that.

## 7. Which missed starts are found now?

On Sept 9 NBC, joined to the published CNN14 causal table:

| | Count of 20 |
| --- | --- |
| Continuous OR within 3 s | 14 |
| Continuous OR within 30 s | 19 |
| Published CNN14 causal hit during the break | 11 |
| Both, within 30 s | 11 |
| DSP only, within 30 s | 8 |
| CNN14 only | 0 |
| Neither within 30 s | 1 |

The eight DSP-only starts are 6.07, 1074.3, 2066.7, 2514.4, 3105.0, 3942.6, 4475.0, and 8413.7. The one neither catches is 1000.4 s. That start fired centroid on the exact Batch 1 timestamp and does not fire on the integer grid within 30 seconds. Two starts the exact-timestamp probe did not list as DSP-only, 2514.4 and 3105.0, do show up once the scan can land on a nearby second. The Batch 1 figure of 7 additional starts does not carry over unchanged. Within 30 seconds the continuous scan covers every published CNN14 causal hit on this game and eight starts that hit missed. Within 3 seconds it covers 14 of 20, which is the operating point that matters for a fast candidate.

Five football starts, across the whole set, never alarm within 30 seconds.

## 8. Which errors remain?

- Returns: 20 of 132 eligible ends never alarm within 30 s, and a positive second near the end looks like a positive second in the middle of the pod.
- Already-on alarms: most 3-second credits are continuations. A new episode starts within 3 s of only 49 football starts and 35 football ends.
- Program burden: 215 episodes per hour, spread through the game rather than piled at the breaks.
- RedZone: 474 episodes per hour with nothing to detect.
- Network spread: Prime stays near 50–70 program episodes per hour. Cable Saturday is 382. One threshold does not describe these broadcasts.
- The integer grid can miss a boundary the exact timestamp caught, as at Sept 9, 1000.4 s.
- Speaker identity, repeated-ad fingerprints, landmark music fingerprints, and a shorter CNN14 window were not run.

## Next experiment

Lightweight verification of these episodes. Do not build another detector first.

The residual is specificity. Starts are found quickly often enough to clear the predeclared bar. The episodes are short, common, and mostly not boundaries: 4,034 of them begin in football program audio, 947 of them are all of RedZone, and in-pod alarms resemble return alarms. The next measurement is whether a second, already-available signal accepts the episodes that begin within 3 seconds of a gold start or end and rejects the program and RedZone episodes, at a false-accept budget declared before the count. The frozen CNN14 distance is the signal already measured on two of these games. Verified announcer identity is the return-side check, because end alarms are real and are not separable from ad-to-ad changes by RMS, flatness, or centroid.

Do not start that measurement here. Do not change the live muter, these thresholds, booth identities, gold, or the Batch 1 results.
