# Reference content audit 001

Not a mute. The library, the counts, the gold, and the published decisions were not changed. Holdouts stayed sealed. Playback stays PLAY. Reviewer labels are empty. The classes below are from the waveform test and the existing five-second whisper scan.

The question was whether a high fingerprint score is the same sound. For the published matches at or above 200, it is. The correlation near zero was a shift of about 40 milliseconds.

## What zero correlation was

The frame offset is an integer number of analyzer hops. One hop is 23 milliseconds. Compared at that exact time, the two count-200 windows correlate at −0.009 and 0.087. Left against left, right against right, and either channel against the other stay in that range. Inverting the polarity does too.

Allowing the reference to slide, the same windows correlate at 0.995 and 0.975. The shifts are 38 and 51 milliseconds. One hop is not enough: inside ±23 milliseconds the correlation stays near 0.1. Inside five hops, 116 milliseconds, it reaches the copy. The same 31 to 53 millisecond shift appears on the other verified copies. That is about the length of the 512-point transform, 46 milliseconds. The two recordings do not share a sample grid, so the leftover is not one fixed number of samples.

## The published matches at or above 200

There are five, not two. Thursday `hush_20261008_205100` has four in a row, scores 272, 223, 260, and 242, all on the Prime Video pod that starts at 234.244 seconds. Monday `hush_20261012_204200` at 5085 seconds scores 208 on the ESPN pod that starts at 6852.564 seconds. Each score reproduced exactly.

| Pair | Query | Aligned reference | Lag | Correlation after the lag | Words |
| --- | --- | ---: | ---: | ---: | --- |
| p01 | 145 s | 314.491 s | 38 ms | 0.995 | DraftKings |
| p02 | 150 s | 319.483 s | 45 ms | 0.998 | same spot, five seconds on |
| p03 | 155 s | 324.476 s | 53 ms | 0.997 | same spot, five seconds on |
| p04 | 160 s | 329.491 s | 38 ms | 0.998 | same spot, the close |
| p05 | 5085 s | 6873.803 s | 51 ms | 0.975 | chili-lime chips |

The Thursday reference times step by 4.99, 4.99, and 5.02 seconds while the queries step by 5. The matcher is following one continuous spot, from 80 seconds into a 122-second pod. The Monday spot is 21 seconds into a 46-second pod. All ten windows, query and reference, sit inside gold commercials. These are repeated advertisement creatives. The library stored the whole pod. The match landed on the creative inside it.

## The five highest-damage pods

Twenty-nine pairs were aligned: the five count-200 windows, the strongest query on each of the five pods, a second query near that pod's median match when it was more than 10 seconds away, the three strongest queries that moved onto the busiest replacement pod, and the strongest hop of each of the 14 NBC September 13 false covers. Every published score reproduced.

The pod blamed for the most program seconds, NBC `hush_20260913_210542` at 9680.140, has its strongest query at score 27. The alignment is 9809.92 seconds, the same 9810-second boundary as the afternoon restart. After the lag search the correlation is 0.017. The waveforms are unrelated. Two of the three replacement matches, scores 20 and 17, are the same kind of miss, correlation 0.017, on Hulu queries that are outside gold.

The other queries on those pods are copies:

| Pair | Score | Correlation after the lag | Where it sits |
| --- | ---: | ---: | --- |
| p07 | 135 | 0.937 | Both sides inside gold commercials |
| p10 | 145 | 0.957 | Both sides inside gold commercials |
| p12 | 42 | 0.968 | Both sides inside gold commercials |
| p13 | 21 | 0.974 | The busiest replacement. Both sides inside gold commercials |

Deleting the five pods would remove these creatives along with the restart collisions. The collisions are the query restart already measured in the warm-context replay. Two further pairs on the same pods, scores 18 and 15, correlate at 0.55 and 0.59. One has no words in the scan. The other faces a drug-disclaimer line. They stay uncertain.

## NBC September 13

The 25.1-second interruption is incident 3, 75.0 to 100.1 seconds. Its strongest hop is pair p18, score 103. After a 16-millisecond shift the correlation is 0.956. The words are the FanDuel line, "make this your most rewarding season." The query window is outside gold. The reference window is inside a gold commercial. The longest false mute is a promo the fingerprint recognizes, on a span the labels call program.

The other strong hops split the same way.

- Copies inside gold on both sides: Traitors (p19, p27), AGT (p23), The Voice at a pod edge (p20, 3.5 of 5 query seconds inside gold), Sunday Ticket at a pod edge (p22).
- Copies on program-labeled query time: the FanDuel promo above, and a satellite spot at score 53, correlation 0.90 (p21).
- A shared line rather than the whole window: "self-optimizing" (p16, p17). A half second correlates above 0.96. The full five seconds stay near 0.56. The query is outside gold.
- Unrelated: p26, score 12, correlation 0.019, query outside gold.

## What can be corrected without deleting a real commercial

The unrelated collisions are the block restart. Warming the query already drops that family under count 10, and the reference pods that receive those collisions also contain verified creatives. Removing the pod is the wrong cut.

The remaining strong false covers are the same promo or the same advertisement, playing where gold says program or running past the edge of a pod. That is a label-boundary question. It is not fixed by a new threshold, and it is not fixed by discarding the reference.

The blind queue is `listen.html`. Clips are `clips/p01a.wav` through `clips/p29b.wav`. A and B are shuffled. The key is `reference_content_review.jsonl`, and `reviewer_label` is null on every row.
