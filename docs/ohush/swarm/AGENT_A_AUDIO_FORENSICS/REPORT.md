# Agent A — Broadcast audio forensics

Figures are copied from EXP-01 (`REPORT.md`, `results.json`, `quiet_location.json`). The frozen one-second DSP baseline contributes only 215 and 474 episodes/hour. Audio was not rescanned. A requested figure that is absent from those sources is marked not measured.

## Verdict

The 40 ms short-dip research gate is **NOT_MET**.

This is a research gate. It is not a mute policy. EXP-01 states that no mute rule was changed, and that the gate is not evidence for or against muting.

## Frozen rule

Ramires, Cocharro, and Davies, [arXiv:1811.02411](https://arxiv.org/abs/1811.02411), partition 48 kHz audio into 1920-sample frames (40 ms) and mark energy at or below −60 dB. They then train a regression on Portuguese television. The regression coefficients are not published. `results.json` records `regression_reproduced: false`. The Portuguese regression was not refit on this gold.

The operating rule is the 40 ms mono short dip. A frame is hot when it is at least 18 dB below the median of the previous 2 seconds and that median is at least −45 dB. A short dip is a hot run of 10–200 ms that recovers on the next frame to within 6 dB. The absolute −60 dB baseline uses the same 10–200 ms run, requires the previous 2 seconds at or above −40 dB, and requires the next frame within 6 dB of that past level.

Predeclared bars: football-start recall within 1 second of at least 0.25, and a fivefold reduction against the frozen DSP scan (215 ordinary-football episodes/hour; 474 RedZone episodes/hour).

## Gate counts

| Quantity | Copied value |
| --- | --- |
| 40 ms short dip, football starts within 1 s | 4/136 (0.029; `start_recall_1s` 0.029411764705882353) |
| 40 ms short dip, program episodes/hour | 134 (`per_hour` 134.028632688806; 2,511 episodes in 67,445.3 s) |
| 40 ms short dip, RedZone episodes/hour | 4 (`per_hour` 4.0; 8 episodes in 7,200.0 s) |
| 40 ms short dip, scripted Hulu program outside its pods | about 491/hour (`per_hour` 490.74211975486276) |
| Absolute −60 dB, 40 ms, football starts within 1 s | 3/136 |
| Absolute −60 dB, 40 ms, program episodes/hour | 18 (`per_hour` 18.148042657982494) |
| Frozen DSP, ordinary football | 215 episodes/hour |
| Frozen DSP, RedZone | 474 episodes/hour |

Football program falls from 215 episodes per hour to 134. RedZone falls from 474 to 4. EXP-01 states that is not a fivefold reduction. Recall 0.029 is under 0.25. Three football starts that lacked a fresh DSP episode are hit within 0.5 seconds, under the predeclared complementary count of 10.

The 40 ms short dip credits 0 of 136 football ends within 1 second and 3 within 3 seconds.

## Descriptive drop versus the detector

Around each football boundary, the minimum 10 ms energy inside ±0.25 seconds was compared with the median of the 2 seconds before that window. This description can see audio on both sides of the label. It is not the causal detector.

| Window | n | Median drop |
| --- | ---: | --- |
| Football starts | 135 | 47.1 dB (`p50` 47.06) |
| Football starts, excluding 7 digital-zero frames on Oct 8 | 128 | 42.5 dB |
| Football program, one window every 30 s and at least 20 s from a pod | 2,069 | 6.6 dB |

The descriptive median drop at starts is about 42 dB (42.5 dB once those seven digital-zero frames are excluded), against 6.6 dB in program.

`quiet_location.json`: of 136 football starts, 103 have at least one 10 ms frame at or below −60 dB inside ±0.5 seconds (84 before the label, 81 after). The median offset of the minimum is 0.09 seconds after the label. Of 2,080 program half-seconds, 283 reach −60 dB. Their median minimum in that file is −40.99 dB (EXP-01 report: −41 dB).

Recovery rejection is why the detector misses. At 40 ms the scanner rejected 4,389 runs as longer than 200 ms and 10,133 runs because the next frame did not recover. The accepted short dips are the minority. A transition into a quieter bed fails a test that wants loud audio on both sides of a brief hole, which is the shape in arXiv:1811.02411. On these NFL boundaries the quiet often continues, so the recovery test discards it, while ordinary football still leaves 134 episodes per hour.

Inside commercial pods the same 40 ms short dip fires 116 times per hour in the interior. Far from pods, at least 15 seconds clear, the football rate is 132 per hour (`per_hour` 132.16045182695487).

## 250 ms and 500 ms

Short-dip rows at 250 ms and 500 ms are zero at 0.25 s, 0.5 s, 1 s, 2 s, and 3 s, and their program and RedZone episode rates are 0. One frame at those scales already exceeds the 200 ms cap. That cap was fixed in the rule, and the run confirmed it.

## Not measured

Recurring network-sting landmarks: not measured.

## Next forensics measurement

The single next measurement is recurring network-sting landmarks on these closed recordings. It is not another recovery threshold.
