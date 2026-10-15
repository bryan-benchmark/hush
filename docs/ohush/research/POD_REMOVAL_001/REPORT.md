# Reference-pod removal

Verdict: exploratory, and not a better count-10 policy. Removing the five pods the ledger blamed clears 94.8 program seconds and 15 incidents, and it also gives back 265.2 commercial seconds. The matcher often lands on a different earlier pod, so the 216.2 seconds attributed to those pods are not seconds a deletion can recover. The pods were chosen from the same false mutes this replay scores. Playback stays PLAY.

Count 10, the query clock, chronological enrollment, and gold were not changed. `best_match` was run again with the chosen pods absent from the library. The published decisions were reproduced first, including the reference each query named.

The ranking is whole-pod attribution from the accuracy audit. It is not proof that the pod contains a bumper or a promo.

| Removal | Program seconds | Incidents | Commercial seconds muted | Commercial seconds lost | Program seconds eliminated | Worst interruption | RedZone program seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| top 1 | 417.1 | 69 | 3888.2 | 15.0 | 15.0 | 25.1 | 10.0 |
| top 5 | 337.3 | 57 | 3638.0 | 265.2 | 94.8 | 25.1 | 5.0 |
| top 10 | 268.9 | 51 | 3371.5 | 531.7 | 163.2 | 20.0 | 0.0 |

Count 10 before removal: 432.1 program seconds, 72 incidents, 3903.2 commercial seconds muted, worst interruption 25.1 s, RedZone 10.0 program seconds.

Universal v1 on the same reproduced queries: 0.0 program seconds and 25.0 commercial seconds muted.

## Where the removed queries went

- top 1: 23 queries had named a removed pod at count 10 or above. 17 still matched some other earlier pod at 10 or above (77.0 program seconds, 8.0 commercial seconds on those query spans). 6 fell below 10 (15.0 program seconds, 15.0 commercial seconds on those query spans).
  The busiest replacement was hush_20260913_210542 at 6838.403: 8 queries, 32.0 program seconds, 8.0 commercial seconds.
- top 5: 123 queries had named a removed pod at count 10 or above. 50 still matched some other earlier pod at 10 or above (146.3 program seconds, 103.7 commercial seconds on those query spans). 73 fell below 10 (99.8 program seconds, 265.1 commercial seconds on those query spans).
  The busiest replacement was hush_20260913_210542 at 6838.403: 13 queries, 51.3 program seconds, 13.7 commercial seconds.
- top 10: 215 queries had named a removed pod at count 10 or above. 74 still matched some other earlier pod at 10 or above (156.6 program seconds, 213.4 commercial seconds on those query spans). 141 fell below 10 (173.3 program seconds, 531.7 commercial seconds on those query spans).
  The busiest replacement was hush_20260913_210542 at 6838.403: 15 queries, 51.3 program seconds, 23.7 commercial seconds.

A query span is the interval from that decision to the next one. The table above is the merged timeline, so those two second-counts do not add to the eliminated total when neighboring queries still cover the same stretch.

## Pods removed

| Rank | Reference session | Pod start | Audit program seconds |
| ---: | --- | ---: | ---: |
| 1 | hush_20260913_210542 | 9680.140 | 77.0 |
| 2 | hush_20260909_213047 | 2514.392 | 46.2 |
| 3 | hush_20260909_213047 | 1074.332 | 31.7 |
| 4 | hush_20260909_213047 | 6074.159 | 31.4 |
| 5 | hush_20260924_220624 | 3496.442 | 30.0 |
| 6 | hush_20260909_213047 | 6.070 | 25.1 |
| 7 | hush_20260909_213047 | 3942.562 | 20.0 |
| 8 | hush_20260909_213047 | 2894.999 | 15.2 |
| 9 | hush_20261008_205100 | 1615.710 | 12.0 |
| 10 | hush_20260909_213047 | 623.347 | 11.4 |

Top-five removal cut 94.8 program seconds, so the alignment offset `best_match` already computed was kept for those 123 queries. Two sit in the first 5 seconds of the old pod and one sits in the last 5 seconds. The rest do not share a position. Median fraction of the way through the pod: 0.92 for 9680.140 (23 queries), 0.22 for 2514.392 (31), 0.67 for 6074.159 (38), 0.95 for 1074.332 (16), and 0.49 for 3496.442 (15). That is not one bumper and not one repeated interior segment. A creative-level library was not built.

On this same count-10 ledger, the October speaker backfill gives back 104.8 program seconds and 375.7 commercial seconds. Top-five removal gives back 94.8 program seconds and 265.2 commercial seconds. The pod removal spends fewer commercial seconds for each program second it clears. Both leave the 25.1-second interruption in place.

No threshold was retuned. No live playback changed.
