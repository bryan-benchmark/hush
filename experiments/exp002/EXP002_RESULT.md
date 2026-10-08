# EXP002 result

Status: **closed**. Spec `exp002-v1` is frozen. No match threshold, recurrence rule, window, absence, or cluster assignment was changed after labels were opened.

Session `hush_20260914_212529`, 0–6899 s. The overlay reads the already-computed speaker timeline. Nothing was rescored.

## Verdict

**Strong for detecting departure from the current program. Negative for detecting return with the current rule.**

Program-speaker disappearance has earned a place as candidate evidence. It is not safe to mute on by itself. The return score has not earned a place.

## Departure

Of 13 evaluable commercial starts, 12 produce the frozen continuity collapse within 15 seconds. A collapse is continuity at least 0.35 below the max of the previous 10 seconds, the unlabeled listing rule.

Two starts are outside that count because the design cannot score them. The break at 167 s is before any cluster qualifies as recurring (first qualification is at 484 s), so continuity is already zero. The last break is still open when the recording ends at 6899 s. The one evaluable miss is the break at 5020 s, where the collapse arrives at 52 s. Median latency on the collapses that do fire is 9.6 s.

Specificity: time-ordered collapses occur at about 28 per hour inside commercial pods and 4.2 per hour during programming, about a 6.6× enrichment. That false rate is too high to mute on. It is high enough to keep as a major feature.

## What “recurring” actually meant

Recurring speaker is not program speaker. Exp002 disproved that equivalence.

`c0001` accounts for 2,161 seconds of speech across nearly the whole game and about 4 seconds inside ads. `c0049` (835 s) and `c0002` (195 s) have no attributed speech inside ads. Several other recurring clusters are almost entirely inside ads (`c0009`, `c0011`, and `c0042` at 100%; `c0012` and `c0015` near 95%).

The useful formulation is narrower: the program develops a small set of unusually dominant, persistent speaker identities, and commercial breaks remove those identities. Other voices can recur too, including inside ads.

`c0001`’s causal prototype stays near cosine 0.99 to its early self. The early-versus-late centroid is 0.86. Low-margin assignments remain, including one window at 1900 s with cosine 0.21 to the centroid. That is a stable program-voice attractor, not a proof that the cluster is exactly one human. The listening clips are in `hush_20260914_212529/excerpts/`.

## Return

The frozen return rule is: an already-recurring speaker is absent at least 30 seconds, then matches again. It fires within 10 seconds of a true return on 5 of 15 breaks in the top-20 list, and on 7 of 15 if every such event is counted. 48 of those events occur during ordinary programming. Football pauses constantly, so that result is expected. The rule did not earn a place.

`c0001` is heard again within 10 seconds on 8 of 15 returns, and a 30-second absence of `c0001` also ends during play 16 times. Reappearance of the dominant voice is a later hypothesis. It was not built here.

## Where the numbers live

- Unlabeled plots: `hush_20260914_212529/`
- Labeled plots: `hush_20260914_212529/plots_labeled/`
- Break and return tables: `overlay_breaks.csv`, `overlay_returns.csv`
- Cluster versus pod: `cluster_pod_balance.csv`
- Cluster geometry: `cluster_integrity.csv`
- Counts: `overlay_summary.json`

Do not tune `exp002-v1` against this ledger. A different clustering rule, if one is ever tried, is a new experiment.
