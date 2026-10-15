# EXP-01 — Micro-production cuts

A continuous scan looked for brief energy dips at 10, 20, 40, 100, 250, and 500 ms. The rules were fixed before the recordings were scored. No threshold was moved afterward. No mute rule was changed.

| Artifact | sha256 |
| --- | --- |
| `experiments/first_principles_broadcast/exp01_micro_cuts.py` | `7af559990dd7495decb448fd38a103180750769718f71cf08686ece6123cc46e` |
| `docs/ohush/research/FIRST_PRINCIPLES_BROADCAST_V2/EXP_01_MICRO_PRODUCTION_CUTS/results.json` | `36323d7cd76eb527819aea94fe43eaf6988a8f1fd4ae1ab63ab906652b1561df` |
| `docs/ohush/research/FIRST_PRINCIPLES_BROADCAST_V2/EXP_01_MICRO_PRODUCTION_CUTS/quiet_location.json` | `fc5e30e6d7de3ef23a8866566bd76484f5a5bd00c885b8cb18207cea8faf6f7b` |
| `experiments/first_principles_broadcast/exp01_quiet_location.py` | characterization of where the quiet frame sits; not part of the gate |

Command:

```
MPLCONFIGDIR=/tmp/mpl PYTHONPATH=src:. \
  .venv/bin/python experiments/first_principles_broadcast/exp01_micro_cuts.py
```

Wall time 261.8 seconds. Peak resident memory 553 MB.

## Research gate: NOT_MET

The operating rule is the 40 ms short dip. On football it produces 134 program episodes per hour, against 215 for the frozen one-second DSP scan. That is not a fivefold reduction. RedZone falls from 474 episodes per hour to 4. Football-start recall within 1 second is 4 of 136, which is 0.029, under the predeclared 0.25. Three football starts that lacked a fresh DSP episode are hit within 0.5 seconds, under the predeclared complementary count of 10.

## What was frozen

Ramires, Cocharro, and Davies, [arXiv:1811.02411](https://arxiv.org/abs/1811.02411), partition 48 kHz audio into 1920-sample frames (40 ms) and mark energy at or below −60 dB. They then train a regression on Portuguese television to separate boundary silences from ordinary pauses, and they group the survivors across 150 seconds. The regression coefficients are not published. They were not fit on this gold.

The absolute baseline uses their −60 dB cut, keeps a run only when it lasts 10–200 ms, requires the previous 2 seconds to sit at or above −40 dB, and requires the next frame to recover to within 6 dB of that past level.

The relative candidate, also frozen, marks a frame that is at least 18 dB below the median of the previous 2 seconds when that median is at least −45 dB. A short dip is a hot run of 10–200 ms that recovers on the next frame. The same 18 dB, 6 dB, and 2 second numbers are used at every scale. A coarse episode drops the 200 ms cap so a 250 or 500 ms frame can still be scored. Availability is the end of the recovery frame for a short dip, and the end of the first hot frame for a coarse episode.

A synthetic 40 ms digital cut in loud noise was detected before any recording was read. The gate uses only the 40 ms mono short dip.

## The quiet moment is real, and it does not behave like a 40 ms blip

Around each football boundary, the minimum 10 ms energy inside ±0.25 seconds was compared with the median of the 2 seconds before that window. This description can see audio on both sides of the label. It is not the causal detector.

| Window | n | Median drop | Drop of at least 18 dB |
| --- | ---: | ---: | ---: |
| Football starts | 135 | 47.1 dB | 96 |
| Football starts, excluding 7 digital-zero frames on Oct 8 | 128 | 42.5 dB | 89 |
| Football ends | 130 | 42.5 dB | 78 |
| Football ends, excluding digital zeros | 119 | 29.6 dB | 67 |
| Football program, one window every 30 s and at least 20 s from a pod | 2,069 | 6.6 dB | p90 is 18.9 dB |
| RedZone, same spacing | 239 | 6.1 dB | p90 is 15.7 dB |

A separate half-second read puts the minimum frame on a clock. Of 136 football starts, 103 have at least one 10 ms frame at or below −60 dB inside ±0.5 seconds: 84 on the program side of the label and 81 on the commercial side. The median time of the minimum is 0.09 seconds after the label. Of 2,080 program half-seconds far from pods, 283 (14%) also reach −60 dB. Their median minimum is −41 dB.

So a deep frame is more common at a gold boundary than in ordinary football, and it is still common in ordinary football. The minimum is not systematically a few tens of milliseconds before the label. It sits on both sides. Session floors make the same point: the 1st percentile of 10 ms energy is about −95 dB on most football recordings, while the median level is between −26 and −38 dB. −60 dB is reachable without a commercial.

Seven Oct 8 starts reach digital zero (−240 dB with the epsilon used here). Those are captured silence, not a fade shape. They do not generalize. One ESPN start and one Sept 9 start have no drop at all (−2.2 dB and −1.4 dB).

## Causal recall

A boundary is credited only when a dip becomes available in the window after the label. A dip whose evidence is only before the label is not credited.

Football starts, 136. Football ends are scored separately.

| Rule | Scale | 0.25 s | 0.5 s | 1 s | 2 s | 3 s | Program episodes/hour | RedZone episodes/hour |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Short dip | 10 ms | 2 | 4 | 7 | 7 | 12 | 101 | 3.0 |
| Short dip | 20 ms | 1 | 3 | 4 | 5 | 11 | 120 | 3.0 |
| Short dip | 40 ms | 1 | 3 | 4 | 5 | 12 | 134 | 4.0 |
| Short dip | 100 ms | 3 | 4 | 6 | 7 | 9 | 71 | 1.5 |
| Short dip | 250 ms | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Short dip | 500 ms | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Absolute −60 dB | 40 ms | 2 | 3 | 3 | 3 | 5 | 18 | 0 |
| Coarse, no 200 ms cap | 40 ms | 10 | 15 | 18 | 26 | 41 | 478 | 207 |
| Coarse, no 200 ms cap | 500 ms | 15 | 41 | 65 | 69 | 72 | 87 | 196 |

The 250 and 500 ms short-dip rows are zero because one frame is already longer than the 200 ms cap. That was fixed in the rule, and the run confirmed it. A half-second average cannot represent a 40 ms edit. The coarse 500 ms row is the same energy drop without that cap: 65 of 136 starts within 1 second, at 87 football episodes per hour and 196 RedZone episodes per hour. That is fewer false episodes than the frozen DSP scan and still well above a fivefold cut, with RedZone still dense.

Requiring both channels to drop at least 12 dB does not change the 40 ms short dip. Program episodes go from 2,511 to 2,510.

Ends are missed. The 40 ms short dip credits 0 of 136 football ends within 1 second and 3 within 3 seconds.

## Why the descriptive drop and the detector disagree

At 40 ms the scanner rejected 4,389 runs as longer than 200 ms and 10,133 runs because the next frame did not recover. The accepted short dips are the minority. A transition into a quieter bed fails a test that wants loud audio on both sides of a brief hole. That is the shape the 2018 paper used for Portuguese commercials. It is not the usual shape at these NFL boundaries: the quiet often continues, so the recovery test discards it, while ordinary football still produces enough brief dips to leave 134 episodes per hour.

Inside commercial pods the 40 ms short dip fires 116 times per hour in the interior, against 134 per hour in football program. The rule does not separate ad-to-ad edits from ordinary play. Scripted Hulu program, outside its own pods, fires 491 times per hour. RedZone fires 4 times per hour. The rule is sensitive to how continuous and loud the mix is. It is not an NFL commercial-start detector, and it is not a universal rule for Hulu.

Log-spectral difference in the 40 ms frame at a start has median 0.94, against 0.82 in a program sample. Stereo correlation in that frame has median 0.58, against 0.89 in the program sample. Both are descriptive. Neither was given a threshold.

## Gate arithmetic

Football program audio actually measured: 67,445 seconds. Short-dip episodes outside pods: 2,511, which is 134 per hour. Far from pods, at least 15 seconds clear, the rate is 132 per hour, so the episodes are not piled against the boundaries. RedZone: 8 episodes in 7,200 seconds, 4 per hour.

Frozen DSP, for comparison, was about 215 ordinary-football episodes per hour and 474 RedZone episodes per hour, with 86 of 136 football starts credited within 3 seconds. The micro-cut rule is quieter on RedZone and does not keep the football starts.

The gate is a research gate. It is not evidence for or against muting.
