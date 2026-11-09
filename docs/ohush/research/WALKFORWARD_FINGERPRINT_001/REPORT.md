# Walk-forward fingerprint transfer

One football game is enrolled, then the next game is scored, then that game is added. A later game is never in the library of an earlier game. The accept line stays the published count of 200. This pass does not choose a new line, does not open the sealed holdouts, and does not change the live mute.

The matches are the chronological queries already stored in `docs/ohush/research/KNOWN_AD_FINGERPRINT_001/pod_queries.csv`. The reader is `experiments/measurement/walkforward_fingerprint_001.py`. August 27 Hulu is in the library before the first football game. October 7 Hulu is in the library before October 8. Neither Hulu tape is a row below. RedZone has no commercial pods, so it is not a row. On the full clock, the same count and the same earlier-only library cover 0 seconds of RedZone and 0 seconds of football program (`docs/ohush/research/UNIVERSAL_V1/`).

## What carries from one game to the next

The query is the opening of a labeled commercial. Landmarks outside that opening are not used. A hit means the opening shares audio with a commercial from an earlier recording.

| Game scored | Earlier football games in the library | Pods | First 5 s at 200 | First 10 s at 200 | Best 10 s score |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sept 9 NBC | 0 | 20 | 0 | 0 | 4 |
| Sept 13 NBC | 1 | 21 | 0 | 1 | 206 |
| Sept 14 ESPN | 2 | 15 | 0 | 1 | 284 |
| Sept 24 Prime | 3 | 13 | 0 | 1 | 331 |
| Oct 8 Prime Video | 4 | 23 | 0 | 2 | 471 |
| Oct 10 cable | 5 | 6 | 0 | 0 | 75 |
| Oct 11 afternoon | 6 | 8 | 0 | 0 | 134 |
| Oct 11 night | 7 | 6 | 0 | 1 | 236 |
| Oct 12 MNF | 8 | 24 | 0 | 1 | 355 |

Zero of 136 openings reach 200 in the first 5 seconds. Seven of 136 reach 200 in the first 10 seconds. Adding the next game does not raise the earlier games, and it does not make the later games match. October 10 and October 11 afternoon still miss every opening after five and six earlier football games are in the library.

The seven that clear 200 are earlier football audio, not the Hulu tapes:

| Score | Heard first in | Heard again in |
| ---: | --- | --- |
| 471 | Sept 24 Prime | Oct 8 Prime Video |
| 355 | Sept 14 ESPN | Oct 12 MNF |
| 331 | Sept 9 NBC | Sept 24 Prime |
| 284 | Sept 9 NBC | Sept 14 ESPN |
| 236 | Oct 8 Prime Video | Oct 11 night |
| 234 | Sept 24 Prime | Oct 8 Prime Video |
| 206 | Sept 9 NBC | Sept 13 NBC |

Sept 9, scored with only the August Hulu commercials behind it, peaks at 4. Those scripted-show spots do not reappear as the NFL openings.

Inside a single game, an opening matched against earlier pods of that same game never reaches 200. The repeated element is a spot that already aired on an earlier day. It is not a spot repeating inside the game.

## What this does not change

Thirty-one openings score at least 50 after 10 seconds. That count was read off this table. It is not a second accept line. Count 200 remains the only line that has been held to 0 program seconds.

The published full-clock rule, a 5-second query at count 200, still holds 25.0 commercial seconds and 0 program seconds. These seven 10-second opening matches are a different clock. They are not added to that 25.0.
