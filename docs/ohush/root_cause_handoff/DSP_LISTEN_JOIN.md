# DSP start table joined to the 25 listens

Verified locally on 15 October 2026. The two CSVs were not in the earlier upload. Join tolerance is 0.5 ms. Every one of the 25 start clips matched.

The sample was drawn from the DSP label, so `or_within_3` cannot explain itself. Every `dsp_hit_*` row is within 3 seconds. Every `dsp_miss_*` row is not. The listen's on-cut flag does not split them the other way.

| Group | Clips | Within 3 s | Already on in the prior 5 s | What the delay does |
| --- | ---: | ---: | ---: | --- |
| Miss, on the heard cut | 6 | 0 | 3 | Median about 9.4 s. None is a near miss of the 3-second line. |
| Miss, off the heard cut | 7 | 0 | 0 | Median about 8.0 s. Two never alarm within 30 s: q002 at 1000.4 s and q007 at 139.9 s. |
| Hit, on the heard cut | 9 | 9 | 8 | Median about 1.6 s. |
| Hit, off the heard cut | 3 | 3 | 3 | Delays 0.10 s, 0.14 s, and 0.69 s. The off-cut hits are the fastest rows in the sample. |

Sitting on the hole a person marked does not make the DSP episode fire. The hits in this sample are mostly alarms that were already on. The misses are alarms that arrive many seconds later, or not at all.

The published 49 is a different count from 86 minus 59, and both are in the files.

- 86 of 136 football starts have an OR-positive second in (boundary, boundary + 3 s].
- 59 of those 86 were already positive somewhere in the prior 5 seconds. That leaves 27 credits that were not already on.
- 49 of 136 have an OR episode whose own start falls in [boundary, boundary + 3 s]. That is `episodes.csv`, feature `or`, football only. An episode can begin inside the window even if some other alarm was on in the prior 5 seconds, and a credit can be a second inside an episode that began earlier. 37 of the 86 credits have no new episode start inside the window.

Sources: `docs/ohush/research/CONTINUOUS_DSP_001/starts.csv`, `episodes.csv`, `docs/ohush/research/BOUNDARY_EVIDENCE_001/cue_table.csv`, and `docs/ohush/swarm/adjudication/queue_key.json` for the session id. The key is the unblinding file. It does not belong on the review page.
