# EXP-C — Break clock

**Hypothesis.** Football commercial pods cluster at 120 or 135 seconds, and a broadcaster-specific or within-game clock predicts the return closely enough to bound an unmute.

**Verdict: FAIL as an unmute.** The duration distribution is real. A point timer is not a return decision.

## Frozen rule

Pod length is the closed commercial interval. Fixed timers are 120 and 135 seconds, chosen as the stated broadcast hypothesis before the histogram was read. The within-game clock is the median of earlier pods in the same recording only. A timer error assumes the mute is already on. Early means ads are still playing. Late means the unmute is after the game has returned. Timer-only unmute is not authorized.

Football is catalog `content_type=sports` (136 of 166 target commercials). The other 30 target commercials are in the all-target row and not in the network table.

## Distribution

| Set | n | Median | p10 | p90 | Near 120 (±7.5 s) | Near 135 (±7.5 s) | Near either |
| --- | --- | --- | --- | --- | --- | --- | --- |
| All target commercials | 166 | 123.9 s | 49.6 s | 174.4 s | 31 | 40 | 71 |
| Football | 136 | 132.8 s | 48.7 s | 181.9 s | 31 | 40 | 71 |
| NBC | 41 | 136.4 s | 54.5 s | 187.2 s | 4 | 17 | 21 |
| Prime | 13 | 122.3 s | 91.8 s | 162.2 s | 5 | 1 | 6 |
| Prime Video | 23 | 121.6 s | 34.8 s | 152.9 s | 9 | 2 | 11 |
| Cable / antenna | 44 | 129.2 s | 53.5 s | 190.5 s | 9 | 14 | 23 |
| ESPN | 15 | 126.0 s | 55.7 s | 138.6 s | 4 | 6 | 10 |

Prime and Prime Video are the catalog's two strings. Together: 36 pods, 14 near 120, 3 near 135. NBC leans toward 135 (17/41) rather than 120 (4/41). A majority of NBC pods are still outside ±7.5 s of 135. A majority of Prime pods are outside ±7.5 s of 120. Short pods are common: the football 10th percentile is 48.7 seconds.

Chart: `../break_durations.png`.

## If the timer were an unmute

| Rule | Pods | Median absolute error | Ad seconds still playing | Program seconds still muted |
| --- | --- | --- | --- | --- |
| Fixed 120 s | 136 | 17.5 s | 3138.8 | 1810.4 |
| Fixed 135 s | 136 | 14.6 s | 1967.5 | 2679.1 |
| Within-game running median | 131 | 16.2 s | 2387.1 | 2391.5 |

Five football pods are the first pod of their recording, so the running median has no prediction for them. That online clock is less accurate than the fixed 135 s timer on median absolute error.

A network-conditional assignment (NBC at 135, Prime at 120) was not predeclared, and it was not scored after the leans became visible.

## What the clock is good for

It is a wide prior, not a return detector. The mass of football pods sits between roughly 50 and 180 seconds, with clumps near 2:00 and 2:15 that differ by broadcaster. Any later audio check of a return can use that band. Unmuting because the timer expired would expose on the order of 2,000–3,000 ad-seconds across these 136 pods, or cover a similar amount of the game, depending on which fixed time is chosen.
