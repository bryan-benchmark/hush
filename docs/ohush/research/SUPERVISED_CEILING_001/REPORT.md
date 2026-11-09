# What set the NBC cutoff

The line at 12.155 is one mixed second at the end of an ad. It is not a stretch of the game that sounds like a commercial. The cutoff was not moved. ESPN, Prime, RedZone, and October were not read. The live mute was not changed.

The head is the one fit for `SUPERVISED_HELDOUT_001` on Sept 9 NBC and Sept 13 NBC. A decision at time t uses audio from t−5 to t, and the second it would cover is t to t+1. "Touches the show" means that covered second overlaps verified program, which is the rule that produced 12.155. Rows labeled −1 are mixed, and the second that sets the line is one of them.

## Where the scores sit

On the two NBC games together:

| | Median | 95th percentile | 99th percentile | Maximum |
| --- | ---: | ---: | ---: | ---: |
| Commercial seconds | 4.103 | 10.403 | 13.221 | 17.383 |
| Seconds that touch the show | −6.155 | 0.796 | 3.296 | 12.155 |

No show-touching second reaches the 99th percentile of the ads. One show-touching second reaches the 95th percentile of the ads, and that second is the cutoff. Eighty-nine show-touching seconds, out of 15,617, sit above the commercial median.

Of those 89, 17 are mixed labels and 72 are entirely program. Sixteen of the 89 have a lookback that is five full seconds of a labeled commercial. Fifty-eight are entirely program and have no commercial audio in the lookback.

## The second that sets the line

`hush_20260913_210542`, session clock 154. The score is 12.155. The label is −1. Of the second that would be covered, 0.391 seconds are verified program and the rest overlaps a labeled commercial. The audio that produced the score, 149–154, is five seconds inside that commercial. The frozen AudioSet head calls it Music at 0.24 and Speech at 0.20. The clip was not copied.

The next two peaks are the same kind of second: Sept 13 at 7754, score 10.269, and Sept 13 at 1890, score 9.541. Each lookback is five seconds of commercial, and each covered second is mixed.

## The highest second that is actually the show

`hush_20260913_210542`, session clock 11412, score 8.285. The covered second is entirely program. The lookback, 11407–11412, contains no labeled commercial. The previous break ended 1,591 seconds earlier. The AudioSet head calls it Music at 0.29 and Speech at 0.22. A second show example is Sept 9 NBC at 1263, score 7.920, Music, 7.8 seconds after a break, with a clear lookback.

That 8.285 second is the top of the show once the ad still sitting in the window is set aside. It is below the 95th percentile of the NBC ads. A line that leaves this second on still sits above the middle of the ads, whose median is 4.103.

## What this says about the held-out result

The held-out games kept almost every commercial because the safe line was pinned by an ad that had not finished. The show's own scores are lower. Program median −6.2 against a commercial median of 4.1 is a real separation. The published line never uses it.

The next measurement keeps this head and these two games, and takes the ceiling from seconds labeled entirely program. It then scores the same held-out games once. The mixed second at 154 will fall above that line, so the fit game itself may lose a fraction of a second of the show. That count gets written down. The line at 12.155 stays the published one.

Numbers are in `results.json`. The reader is `experiments/measurement/supervised_ceiling_001.py`.
