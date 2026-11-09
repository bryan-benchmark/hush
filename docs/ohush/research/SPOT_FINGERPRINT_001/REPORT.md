# Spot pieces at count 200

Splitting labeled breaks at the 12 dB holes, and enrolling those pieces from earlier games only, marks **30.0** commercial seconds and **0** program seconds. RedZone stays at 0. The count was not lowered. The live mute was not changed. The sealed tapes were not opened.

The hole is the published one: inside a 2-second window, the median tenth-second level is at least 12 dB above the quietest tenth. Centers are checked every second, from 2 seconds after a labeled break starts until 2 seconds before it ends. A run of holes becomes one cut, at the deepest center. A piece shorter than 2 seconds is not enrolled. The query is the Universal v1 clock: 5 seconds of audio that has already ended, and a score at or above 200 covers the next 5 seconds. RedZone is queried against Sept 9 only, because that is the football tape that aired before it, and RedZone is never enrolled.

A copy is visible. The first 5 seconds of the first long Sept 9 piece match that piece at 858.

## What transferred

| Broadcast | Pieces from earlier games | Commercial seconds marked | Program seconds marked | Highest ad score | Highest show score |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sept 9 NBC | 0 | 0 | 0 | — | — |
| Sept 13 RedZone | 294 | 0 | 0 | — | 10 |
| Sept 13 NBC | 294 | 0 | 0 | 189 | 148 |
| Sept 14 ESPN | 488 | 5.0 | 0 | 230 | 63 |
| Sept 24 Prime | 669 | 0 | 0 | 122 | 11 |
| Oct 8 Prime Video | 820 | 25.0 | 0 | 286 | 15 |
| Oct 10 cable | 1,041 | 0 | 0 | 160 | 24 |
| Oct 11 afternoon | 1,139 | 0 | 0 | 119 | 15 |
| Oct 11 night | 1,253 | 0 | 0 | 189 | 14 |
| Oct 12 MNF | 1,322 | 0 | 0 | 147 | 41 |

The 30 seconds are six covers.

ESPN, `hush_20260914_212529`, covers 2770–2775, score 230. The reference is Sept 9 NBC, `hush_20260909_213047`, 1696.591–1728.591.

Oct 8, `hush_20261008_205100`, covers 145–150, 155–160, and 170–175, scores 208, 286, and 207. The references are three Sept 24 Prime pieces between 310.244 and 340.244. The same tape covers 6385–6395, scores 216 and 234, against the Sept 24 piece at 1506.038–1520.038. The opening covers are separated by gaps, so the 15 seconds at the start are not one continuous hold.

Sept 13 NBC is the near miss. An ad query reached 189 and a show query reached 148, at session clock 90, before the first labeled break. Both stay under 200. Choosing a count between those two numbers would be fitting this tape. It was not done. RedZone's highest score is 10.

## Where this leaves the corpus

Thirty commercial seconds and no program seconds is five more than the whole-pod count-200 replay, which held 25.0. It is still 30 seconds out of the 17,648.4 commercial seconds in the nine games. The interior cuts were plentiful — 274 of them on Sept 9 alone — and they did not turn the later games into matches. Most breaks never reach 200. This replay is not wired into the television.

The count stays 200. The next measurement does not search for a new sound on these tapes and does not drop the count to admit the 189.

Numbers are in `results.json`. The reader is `experiments/measurement/spot_fingerprint_001.py`. The clips were not copied.
