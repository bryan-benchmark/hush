# False-reference audit

The local `decisions.jsonl` is not empty. Each count-10 cover names a reference pod through `ref_session` and `ref_start`. The alignment offset inside that pod was computed by `best_match` and then discarded. It is not in `decisions.jsonl` or `receipts.jsonl`. `receipts.jsonl` is the count-200 action log, 9.2 MB locally, and its fingerprint block also has no interior offset.

Football reproduced 72 incidents. The raw program-second sum is 432.162, which is the published 432.1 after each session is rounded to a tenth.

They point at 32 earlier commercial pods. 3 incidents touch more than one pod. The largest pod accounts for 77.0 seconds. The top 5 account for 216.2 seconds (50%). The top 10 account for 299.9 seconds (69%).

That is concentration across whole pods. It is not evidence that the match landed on a bumper, a promo, or reused program audio. The interior offset is the missing measurement, so this audit stops before that claim.

| Rank | Reference session | Pod start | Program seconds |
| ---: | --- | ---: | ---: |
| 1 | hush_20260913_210542 | 9680.14 | 77.0 |
| 2 | hush_20260909_213047 | 2514.392 | 46.2 |
| 3 | hush_20260909_213047 | 1074.332 | 31.7 |
| 4 | hush_20260909_213047 | 6074.159 | 31.4 |
| 5 | hush_20260924_220624 | 3496.442 | 30.0 |
| 6 | hush_20260909_213047 | 6.07 | 25.1 |
| 7 | hush_20260909_213047 | 3942.562 | 20.0 |
| 8 | hush_20260909_213047 | 2894.999 | 15.2 |
| 9 | hush_20261008_205100 | 1615.71 | 12.0 |
| 10 | hush_20260909_213047 | 623.347 | 11.4 |

Every query that contributes to an incident is in `false_incidents_by_reference.csv`. `match_offset_inside_reference` is null on every row.
