# Block-start context

Not a mute. Count 10 was not changed, and block-start queries were not discarded. Playback stays PLAY.

The published fingerprint reads each 90-second block with two seconds of audio after the cut and none before it. The resampler and the peak picker both start over at that cut. This test asked whether the 13 afternoon false matches are that restart, or the same commercial playing again.

## The sound is not the commercial

Each of the 13 queries was scored again, cold, against the same reference pod named in the published decision. Twelve reproduce that score exactly. One published 11 comes back as 9.

The match lands on a time in the reference, and the two waveforms were compared there. The correlation is about zero on all 13. The largest is 0.013. Nine of them land on the same moment of one NBC commercial, `hush_20260913_210542` near 9809.7 seconds, about 130 seconds after that pod starts at 9680.1. The afternoon audio at 2790, 3960, 4050, and the later block starts does not sound like that moment.

The resampled query itself is not a click. After the first 50 milliseconds, a read that started at the block and a read that started two seconds earlier correlate at 1.0. The samples in the query are the same. What changes is which peaks the analyzer keeps.

The landmarks that agree with the reference sit about 1.2 seconds into the query, not in the opening tenth of a second. The peak picker carries a decaying threshold. A restart at the block boundary still changes which peaks survive a second later. A quarter second of leading audio is not enough. One second is only partial. Two seconds clears it.

## Two seconds of leading audio, on the same sample grid

The lead is an exact number of analyzer hops, so the fingerprint grid still hits the same samples. The reference stays the published cold extraction.

| Lead | What happens to the 13 false matches |
| --- | --- |
| None, the published read | Scores 11–25 |
| 11 hops, about 0.25 s | 9 of 13 still score at least 10 |
| 43 hops, about 1.0 s | 4 of 13 still score at least 10 |
| 86 hops, about 2.0 s | All 13 score 2–5 |

Under the count of 10, the two-second lead removes all 13. That is 65 seconds of the afternoon false mutes. It is not a new threshold.

## What this does not yet license

The strongest block-start match anywhere in the published queries scores 167. None reach Universal v1's 200, on this tape or any other. v1's 25 covered seconds do not come from a block-start query.

On the afternoon tape the two block-start queries that fall inside a commercial and score at least 50 were rescored with the same lead. The one that reproduces, at 540 seconds, stays at 76 cold and 81 with the two-second lead. Its waveform correlation with the reference is also about zero, so it is not a clean copy of that commercial either. The other, at 3780 seconds, was published at 65 and comes back at 43 cold. The lead leaves it at 47. That one is not a reproduced control.

So the lead removes the 13 false program matches without erasing the one reproduced in-commercial match on this tape. It has not been run on a block-start query that is actually the same advertisement, because the published stream does not contain a block-start match at the v1 bar. Applying it to every recording would still be a new extraction, and it needs that check before it replaces the published reader.

No count was changed. No query was discarded for being at a block start.
