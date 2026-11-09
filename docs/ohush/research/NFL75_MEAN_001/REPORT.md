# NFL75_MEAN_001

One rolling mean of the frozen NBC score. The window and the start line were chosen on the two NBC fit games, then frozen. October 8 and September 24 did not move either number. Both Prime tapes are development inspections. The oracle column uses gold endings and is not a deployable result. Nothing was trained. Speakers were not moved.

## Verdict

**REJECT** this candidate as a muter.

The rolling mean can see advertising. With gold endings it covers 98.6% of October 8 ads and 98.5% of September 24 ads, and every break produces a start signal. The same rule also mutes football. A perfect return still leaves 70 false-mute episodes on October 8 and 37 on September 24. That is the failure.

| Metric | Rolling mean + oracle return | Rolling mean + actual return |
| --- | --- | --- |
| October 8 commercial coverage | 98.6% | 95.1% |
| September 24 commercial coverage | 98.5% | 95.2% |
| False starts | Oct 95 events, 70 episodes; Sept 55 events, 37 episodes | Oct 95 events, 77 episodes; Sept 55 events, 45 episodes |
| Late returns | 0 and 0 breaks | 19 and 11 breaks |
| Worst programming interruption | 54.0s; 34.0s | 54.0s; 83.6s |
| Total hidden programming | 617.6s (285s/hour); 473.1s (287s/hour) | 821.5s (379s/hour); 709.3s (430s/hour) |

False-start events are openings during programming. They come from the start rule, so the event counts match. Episodes are the scorer's merged program interruptions. The product caps are under 1 false mute per program hour, under 10 seconds worst, and under 5 hidden program seconds per hour. Both columns miss all three caps, on both games.

## Answers

1. **Yes.** Ideal returns make 75% coverage plausible. Every October break signals within 10 seconds, and 12 of 13 September breaks do. The median delay is 4.4 seconds on October 8 and 4.6 seconds on September 24. A 10-second window cannot claim a break until about half of its samples are inside it, and the medians sit on that floor. About 95% of commercial decision-seconds are at or above the line.

2. **Yes.** False starts are far too frequent. October opens a cover during programming 95 times (32 episodes per hour even after gold endings). September opens 55 times (22 per hour). Ordinary football, more than 60 seconds from every break, is still above the line 5.8% of the time on October 8 and 6.1% on September 24. The first 30 seconds after a break are above the line 49.5% and 61.4% of the time.

3. **The return adds 204 hidden program seconds on October 8 and 236 on September 24.** It stretches September's worst cut from 34 seconds to 84. With those tails removed, the worst cuts are still 54 and 34 seconds, and hidden football is still 285 and 287 seconds per program hour. The caps already fail on the oracle column.

4. **The next change is a different evidence source for "this is football," especially the return shoulder and the ordinary-play tail.** Another cutoff or timer on this same mean will not do it. Ad interiors and ordinary football barely share mass (overlap 0.09 and 0.08). Ad interiors and the 30 seconds after a break share much more (overlap 0.42 and 0.42). A line high enough to quiet that shoulder also sits in the commercial scores.

## How the line was frozen

Candidates were the 10-second and 20-second windows already measured. For each window, on the two NBC games pooled, the gap is the commercial 10th percentile minus the program 90th percentile. Program seconds include the boundaries. Commercial seconds include the edges. The wider gap won. It was the 10-second window, gap 1.91 against 1.36.

That gap was open, so the start line is the midpoint of commercial p10 (1.120) and program p90 (−0.793): **0.163**. The 20-second window was not scored on Prime. The return stays three raw seconds at or below zero.

The logistic head was fit on these same two NBC games (21,400 rows, train accuracy 0.9273). The line is in-sample. On those games, 96.7% of commercial seconds are above 0.163, and program seconds are above it 3.8% of the time on September 9 and 9.0% on September 13. Every NBC break signals within 30 seconds. September 24 is named in the gpu_lab train split. It was not used to fit this head or to place this line. October 8 was not used either.

Each score stamped at t uses audio [t−5, t). The mean uses only stamps at or before the decision. Both Prime caches match that stamp contract (model `MIT/ast-finetuned-audioset-10-10-0.4593`, hop 1 second, first stamp at 5.0). The encoder's prefix invariance was not re-measured.

## Where the score sits

Rolling-mean quantiles on the decision second. The start line is 0.163. Boundary seconds are included in every false-mute count above. These games have no music, promo, or halftime labels. Ordinary football means more than 60 seconds from every break.

| Slice | October 8 median (p10, p90) | Share ≥ line | September 24 median (p10, p90) | Share ≥ line |
| --- | --- | --- | --- | --- |
| Commercial interior | 4.34 (1.46, 8.12) | 96.6% | 4.63 (1.64, 7.79) | 97.3% |
| Ordinary football | −4.64 (−8.21, −0.88) | 5.8% | −4.83 (−8.01, −1.10) | 6.1% |
| 30s before a break | −3.72 (−7.80, 0.43) | 12.8% | −2.95 (−7.83, 1.66) | 28.3% |
| First 30s after a break | 0.11 (−5.03, 4.20) | 49.5% | 0.80 (−4.07, 5.06) | 61.4% |

Ordinary-football p99 is 2.78 on October 8 and 3.98 on September 24, both above the line. The return shoulder's median is already near the line, and its p90 is in commercial territory. Thirty-one October seconds fall in both boundary bands because two breaks are close. They are counted in both boundary rows and in the false-mute totals.

## Per break

Signal delay is the first causal window with the mean at or above 0.163 and at least half its samples inside the break. Mute times are the first causal open and the last causal close that touch the break. A gap inside that span is in `results.json`. Late return is how far the causal cover runs past the gold end.

### October 8

| Break | Ad (s) | Delay | Already muting | Causal mute | Late |
| ---: | --- | ---: | --- | --- | ---: |
| 1 | 139.9–376.9 | 4.1 | yes | 134.0–405.0 | 28.1 |
| 2 | 571.7–683.4 | 4.3 | | 572.0–689.0 | 5.6 |
| 3 | 1003.3–1125.2 | 4.7 | yes | 1001.0–1134.0 | 8.8 |
| 4 | 1615.7–1737.1 | 4.3 | | 1619.0–1743.0 | 5.9 |
| 5 | 1973.0–2006.4 | 6.0 | | 1979.0–2007.0 | 0.6 |
| 6 | 2230.0–2365.7 | 4.0 | yes | 2223.0–2373.0 | 7.3 |
| 7 | 2396.2–2429.8 | 8.8 | | 2405.0–2435.0 | 5.2 |
| 8 | 3025.2–3178.4 | 4.8 | yes | 3022.0–3174.0 | 0 |
| 9 | 3548.8–3702.0 | 4.2 | | 3553.0–3712.0 | 10.0 |
| 10 | 3980.9–4118.0 | 4.1 | yes | 3974.0–4114.0 | 0 |
| 11 | 4419.3–4540.8 | 4.7 | yes | 4413.0–4548.0 | 7.2 |
| 12 | 4858.5–4979.7 | 4.5 | yes | 4851.0–4988.0 | 8.3 |
| 13 | 5331.9–5453.5 | 4.1 | | 5333.0–5475.0 | 21.5 |
| 14 | 5670.5–5792.7 | 4.5 | | 5671.0–5799.0 | 6.3 |
| 15 | 6055.4–6176.7 | 4.6 | | 6058.0–6184.0 | 7.3 |
| 16 | 6363.8–6515.4 | 4.2 | | 6366.0–6532.0 | 16.6 |
| 17 | 7169.5–7293.4 | 4.5 | | 7172.0–7331.0 | 37.6 |
| 18 | 7677.0–7797.8 | 5.0 | yes | 7675.0–7795.0 | 0 |
| 19 | 8136.6–8176.2 | 5.4 | | 8142.0–8178.0 | 1.8 |
| 20 | 8802.6–8950.2 | 4.4 | yes | 8802.0–8965.0 | 14.8 |
| 21 | 9604.9–9754.1 | 4.1 | yes | 9600.0–9778.0 | 23.9 |
| 22 | 9756.8–9769.8 | 4.2 | yes | 9613.0–9778.0 | 8.2 |
| 23 | 10390.0–10440.4 | 4.0 | yes | 10385.0–10440.0 | 0 |

### September 24

| Break | Ad (s) | Delay | Already muting | Causal mute | Late |
| ---: | --- | ---: | --- | --- | ---: |
| 1 | 1.6–49.6 | 12.4 | | 14.0–58.0 | 8.4 |
| 2 | 234.2–356.5 | 4.8 | | 237.0–362.0 | 5.5 |
| 3 | 913.4–1033.9 | 4.6 | yes | 909.0–1043.0 | 9.1 |
| 4 | 1490.0–1611.2 | 5.0 | yes | 1486.0–1633.0 | 21.8 |
| 5 | 1742.7–1894.7 | 4.3 | | 1746.0–1901.0 | 6.3 |
| 6 | 2217.9–2338.3 | 4.1 | | 2218.0–2362.0 | 23.7 |
| 7 | 2796.8–2917.9 | 4.2 | yes | 2795.0–2915.0 | 0 |
| 8 | 3496.4–3633.0 | 4.6 | yes | 3489.0–3649.0 | 16.0 |
| 9 | 4337.2–4492.7 | 4.8 | yes | 4331.0–4509.0 | 16.3 |
| 10 | 5354.8–5518.7 | 7.2 | | 5362.0–5536.0 | 17.3 |
| 11 | 6028.8–6180.7 | 4.2 | yes | 6021.0–6209.0 | 28.3 |
| 12 | 6854.0–7020.4 | 5.0 | yes | 6832.0–7104.0 | 83.6 |
| 13 | 7515.4–7600.0 | 4.6 | yes | 7489.0–7600.0 | 0 |

Twelve of 23 October breaks, and 8 of 13 September breaks, were already muted when the gold ad began. The scorer does not charge the 1.5-second return fade. Charging it would lengthen the hidden football.

## Stop

This is the keep-or-reject. The mean separates ordinary football from the middle of an ad, and it finds every break. It also starts during football often enough that ideal returns still miss the false-mute caps by more than an order of magnitude. Do not add another timer on 0.163, 8.285, or 12.155. Do not train a new network in this step. The published lines were left where they were.
