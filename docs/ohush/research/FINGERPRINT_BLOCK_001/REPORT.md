# Fingerprint block 001

Not a mute. The published reader and its decisions were not modified. Count 10 and count 200 were not changed. Holdouts stayed sealed. Playback stays PLAY.

The published fingerprint reads each 90-second block with two seconds after the cut and none before it. The 13 afternoon false matches are that restart. They are not the commercial they point at.

## The matches move with the cut

All 13 queries were scored again against the same reference pod. The cold read reproduces the published scores. Twelve match exactly. The published 11 comes back as 9.

The same five seconds, taken 45 seconds into a block instead of at its start, score 2 to 5. Two seconds of leading audio, and 45 seconds of leading audio on the analyzer's own hop grid, do the same. None of the 13 stay at or above 10.

The cut was then moved 45 seconds later, and those new beginnings were read cold, against the same references. Eleven of the thirteen score 11 to 26. The false match left the old time and appeared at the new block start.

The waveforms do not match. Correlation at the alignment is about zero. The largest is 0.013. Nine of the cold matches land on one moment of an NBC commercial, `hush_20260913_210542` near 9809.7 seconds. The agreeing landmarks sit about 1.2 seconds into the query, not in the first tenth of a second.

A two-second lead and a 45-second lead agree on most landmarks. The median overlap of those two hash sets is 0.89. They are not bit-identical. The cold read agrees with the long read at about 0.63. The false score is what becomes stable: once the analyzer has heard audio before the cut, the score stays at 2 to 5.

## What a five-second decision can see

The peak picker normalizes to the whole buffer, and its backward pass can delete an earlier peak because of a later one. Filling the rest of a block with noise keeps that threshold high, so a noise test overstates the delay.

Ending the real buffer is the latency test. For the block-start query at 2790, stopping the read 5 seconds after the query makes the landmarks identical to the full 92-second buffer. Stopping it 2 seconds after leaves three landmarks different, overlap 0.996. For a query 20 seconds into the same block, 2 seconds after the query is already identical, and the published two-second tail at the end of that block matches a longer read exactly.

The stored scores for these queries are the scores you get once a few seconds of later audio have arrived. The published timestamp says the decision is available when the five-second query ends. That is early by about 2 seconds inside a block, and by about 5 seconds when the query itself opens the block. The rest of the 92-second buffer does not change the result past that.

## The candidate

An isolated reader keeps the two-second tail and adds 86 analyzer hops, 1.997 seconds, before each block. Hashes before the block are dropped. It was scored on the full gold ledger. The published files were left as they are.

Count 10, football:

| | Published | With the lead |
| --- | ---: | ---: |
| Program seconds covered | 432.1 | 355.2 |
| Program seconds recovered | | 76.9 |
| Commercial seconds no longer covered | | 3.0 |
| False-cover incidents | 72 | 55 |
| Longest program interruption | 25.1 | 25.1 |
| Pods with any cover | 105 | 104 |
| Return delay, median | 5.3 s | 5.4 s |
| Still covering at the annotated end | 2 | 2 |

The 25.1-second interruption is not this cluster. Those block-start mutes were 5 seconds each. Afternoon block-start queries at or above 10 fell from 18 to 5, which is the 13 false program queries leaving and the other five staying.

RedZone count 10 covered 10.0 program seconds in 2 incidents. With the lead it covers none. No new RedZone program seconds. Hulu count 10 program covers fall from 61.5 seconds to 26.5, incidents from 11 to 4, with no change in commercial seconds heard.

Count 200 still covers no program, on football, RedZone, or Hulu. Football commercial seconds heard fall by 5.0, which is a gain of coverage, not a loss. Pods touched go from 2 to 3, and premature returns from 2 to 3. Read holes are 280 seconds against the published 275. That 5-second hole is the same size as the count-200 coverage change, so that change is not a new advertisement match.

The three second-count gates pass: 76.9 program seconds recovered, 3.0 commercial seconds given up, and no new RedZone false mute. Landmark sets are not invariant, and the decision time is still early by a few seconds. Those two are not fixed.

Adding this 76.9 to the voice guard's 27.5 was not measured. They are different errors. The sum is not a result.
