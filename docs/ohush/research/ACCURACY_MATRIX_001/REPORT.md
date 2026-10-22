# Accuracy matrix

Retired as a score. The 79.26% counted 67,428 seconds of game as correct. A muted second of the game is broken, and the percentage is commercial seconds held after the true start. The rule is `docs/ohush/research/ACCURACY_LADDER_001/KPI.md`. The tables below are the old ledger, kept so the seconds can be re-read.

One denominator for every scored experiment: 67,428 program seconds and 17,648.4 commercial seconds. RedZone stays out.

True positive is commercial seconds muted. False positive is program seconds cut. False negative is commercial seconds heard. True negative is program seconds left playing. Accuracy is the first plus the fourth, over 85,076.4. Weighted harm is 100 times the false positives plus the false negatives.

Play is 79.26%, with every cell at the extremes: 0 muted, 0 cut, 17,648.4 heard, 67,428 kept. Universal v1 moves 25.0 seconds from heard to muted and cuts nothing. Accuracy becomes 79.29%. Weighted harm falls by those same 25 seconds. That is the only correct nudge.

Count 10 reaches 83.34% and weighted harm of 56,955, because it cuts 432.1 program seconds. The warm query is the best move inside that family: 5 more commercial seconds and 60 fewer program seconds than count 10. Harm is still 50,950. v2, v3, and v4 select play and give the 25 seconds back.

The 134 missed starts, read four seconds before and four seconds after: 7,131 seconds are a song with no speech window, 5,567 are a song with a voice under the 0.25 line, 3,380 are the booth leaving, 780 are still quiet. The 25 true-positive seconds and the 67,428 true-negative seconds stay. Numbers are in `results.json`.
