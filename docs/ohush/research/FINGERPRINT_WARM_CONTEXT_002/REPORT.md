# Fingerprint warm context 002

Not a mute. The published reader, its decisions, the counts, and the gold were not modified. Holdouts stayed sealed. Playback stays PLAY.

Cold means the published cut: each 90-second block starts where it starts, with two seconds after it and none before it. Warm means the same cut, plus 86 analyzer hops of audio already received, 1.997 seconds, with hashes from that lead discarded. The sample grid is the analyzer hop. Count 10 and count 200 were not refit.

Cold against cold reproduces the published ledger. Football count 10 is 3,903.2 commercial seconds covered, 432.1 program seconds, 72 incidents, and a longest interruption of 25.1 seconds. Count 200 is 25.0 commercial seconds and 0 program seconds.

## The 13 queries

On `hush_20261011_135700`, the cold read returns the published scores, 11 through 25. Warming the query drops all 13 to 3, 4, or 5, whether the reference is cold or warm. Warming only the reference leaves 11 of the 13 at or above 10. The lowest of those is 9, on two queries. The false match is the query restart.

The alignments still sit near 9809.7 seconds in the NBC reference, and 9810 is 109 times 90. That reference boundary is real, and warming it trims some scores. It does not create the match. A cold query still clears count 10 against the warmed reference.

Two of the 13, at 2700 and 4500 seconds, also land on a file-chunk boundary. The other 11 do not. The cluster follows the 90-second analyzer cut.

## Full ledger, count 10

Football, at the published decision times:

| Query | Reference | Commercial seconds covered | Program seconds covered | Incidents | Longest interruption |
| --- | --- | ---: | ---: | ---: | ---: |
| Cold | Cold | 3,903.2 | 432.1 | 72 | 25.1 |
| Warm | Cold | 3,908.2 | 372.1 | 59 | 25.1 |
| Cold | Warm | 3,885.2 | 415.2 | 68 | 25.1 |
| Warm | Warm | 3,900.2 | 355.2 | 55 | 25.1 |

Warming the query and leaving the reference cold recovers 60.0 football program seconds and covers 5.0 more commercial seconds. Incidents fall by 13. The 65.0-second afternoon rescue is inside that 60.0: the afternoon tape goes from 79.6 program seconds and 15 incidents to 14.6 and 2, and its commercial coverage stays 275.5. Saturday cable gives up another 10.0 program seconds. Thursday gains 5.0 program seconds, and Sunday night gains 10.0. Those two tapes are worse, and they are already in the net.

Warming both sides recovers 76.9 program seconds and gives up 3.0 commercial seconds. That is the same candidate measured in the block study. Part of the extra recovery is Thursday and Saturday. Part of the commercial movement is the warmed reference, including an extra 5.0 commercial seconds on the afternoon tape. The useful correction is the query side.

RedZone is separate. Its 10.0 program seconds and 2 incidents go to zero when the query is warm, and stay at 10.0 when only the reference is warm. No RedZone commercial seconds are covered in any arm.

Hulu is separate. The October 7 tape goes from 61.5 program seconds and 11 incidents to 26.5 and 4 when the query is warm. Commercial coverage stays 108.5. Warming only the reference changes nothing. The August Hulu tape stays at zero.

Count 200 does not move when the query is warmed against the cold reference: 25.0 football commercial seconds, 0 program seconds, the same two pods. Warming both sides reports 30.0 commercial seconds and a third pod. That extra 5.0 seconds is on Sunday night, the same recording where the warm read adds a 5-second hole. It is not a new confirmed advertisement. Count 200 still covers no program, on football, RedZone, or Hulu.

Return delay for football count 10 stays at a median of 5.256 seconds for cold/cold and for warm query against cold reference. Two covers are still on at the end of the annotation. The warm read does not hold a recognized commercial longer.

## By recording, count 10

Program seconds covered, then commercial seconds covered. Cold/cold, then warm query against the cold reference.

| Recording | Cold program | Warm-query program | Cold commercial | Warm-query commercial |
| --- | ---: | ---: | ---: | ---: |
| NBC Sept 9 | 0.0 | 0.0 | 5.0 | 5.0 |
| NBC Sept 13 | 122.8 | 122.8 | 837.3 | 832.3 |
| ESPN Sept 14 | 16.6 | 16.6 | 503.4 | 503.4 |
| Prime Sept 24 | 19.7 | 19.7 | 235.3 | 240.3 |
| Thursday Oct 8 | 57.2 | 62.2 | 558.1 | 558.1 |
| Saturday Oct 10 | 57.6 | 47.6 | 222.3 | 222.3 |
| Sunday afternoon Oct 11 | 79.6 | 14.6 | 275.5 | 275.5 |
| Sunday night Oct 11 | 20.0 | 30.0 | 265.0 | 275.0 |
| Monday Oct 12 | 58.6 | 58.6 | 1,001.3 | 996.3 |
| RedZone Sept 13 | 10.0 | 0.0 | 0.0 | 0.0 |
| Hulu Aug 27 | 0.0 | 0.0 | 0.0 | 0.0 |
| Hulu Oct 7 | 61.5 | 26.5 | 108.5 | 108.5 |

The 25.1-second interruption is the NBC Sept 13 tape. It is 122.8 program seconds and 14 incidents in every extraction arm. This repair does not touch it.

## Causality, starts, and gaps

The two seconds before the cut are audio the recorder already has. They are not playback latency.

The peak picker still looks past the query. On the afternoon block that opens at 2790, a cold read is identical to the full buffer only when the buffer continues 5 seconds past the query. The same query with the lead is identical at 2 seconds past the query. A decision stamped at the end of the five-second window is early by that amount.

Shifting every warm/warm decision later by that measured 2 seconds, without changing the hashes, is a worse ledger. Football commercial coverage falls from 3,900.2 to 3,848.8, and program seconds rise from 355.2 to 400.6. The covers slide past the pods. A 5-second shift is worse still: 3,755.3 commercial seconds and 485.0 program seconds. Waiting longer is not the correction.

The first block of each of the 12 sessions has no audio before coverage, so the warm reader starts cold there. The 13 rescued queries are not in those opening blocks. Queries inside the first 90 seconds that do score at or above 10 sit 10 to 85 seconds after coverage begins. They already have audio inside the block.

The warm read fails one block the cold read does not. Sunday night gains a 5-second unscorable hole, 35 seconds to 40. That is a lead reaching into a missing chunk. Both readers also warn that some buffers are identically zero, on the same tapes. The warnings are not new to the warm reader.

## What survived

Two published matches score at or above 200, on different recordings. Both keep their scores in all four arms: 272 and 208. Aligned to the match, the waveforms correlate at 0.028 and 0.001. The scores are stable. They are not a confirmed repeat of the reference audio.
