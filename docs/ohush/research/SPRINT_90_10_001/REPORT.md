# Sprint 90/10

Stop. None of the three changes keeps count 10's commercial coverage while clearing most of the 72 false mutes. The 2-, 5-, and 10-second continuation rules were not opened. Playback stays PLAY.

Count 10, cosine 0.25, gold, and the holdouts were left as they are. The reference runs are the rematches already stored in `POD_REMOVAL_001`. The voice numbers use the October ECAPA pass. October recordings were already inspected, so they are not a blind test.

## Corpus

| Candidate | Commercial seconds covered | Program seconds covered | Incidents | Longest interruption | Commercial seconds after a premature release | Premature releases | RedZone program seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Universal v1 | 25.0 | 0.0 | 0 | 0.0 | 328.5 | 2 | 0.0 |
| Count 10 | 3,903.2 | 432.1 | 72 | 25.1 | 6,321.5 | 186 | 10.0 |
| Top 1 pod removed | 3,888.2 | 417.1 | 69 | 25.1 | 6,336.5 | 184 | 10.0 |
| Top 5 pods removed | 3,638.1 | 337.3 | 57 | 25.1 | 6,263.5 | 177 | 5.0 |
| Top 10 pods removed | 3,371.5 | 268.9 | 51 | 20.0 | 6,219.3 | 176 | 0.0 |
| Voice guard | 3,438.6 | 299.8 | 57 | 25.1 | 6,604.2 | 320 | 0.0 |

Top-five removal clears 94.8 program seconds and gives back 265.1 commercial seconds. Seventeen of the 23 queries on the single worst pod match a different earlier pod. The voice guard clears 132.3 program seconds and gives back 464.6 commercial seconds. Of that guard, 10.6 program seconds and 26.7 commercial seconds come from a voice enrolled on the same recording. The other 121.7 program seconds and 437.9 commercial seconds come from a different recording. The five October tapes have no named labels, so every second the new embeddings give back is a cross-recording match.

The guard also makes premature release worse: 186 let-gos become 320, and the commercial seconds heard after a let-go rise from 6,321.5 to 6,604.2. Holding a count-10 cover for another 2, 5, or 10 seconds would extend the false mutes that remain, including the 25.1-second interruption. That is why continuation stays unregistered.

## Sessions

Count 10, then the top-five removal, then the voice guard. Commercial and program figures are seconds covered.

| Session | Network | C10 ads | C10 program | C10 incidents | Top 5 ads | Top 5 program | Guard ads | Guard program | Guard incidents |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| hush_20260909_213047 | NBC | 5.0 | 0.0 | 0 | 5.0 | 0.0 | 5.0 | 0.0 | 0 |
| hush_20260913_210542 | NBC | 837.2 | 122.8 | 14 | 709.6 | 80.4 | 811.2 | 110.9 | 16 |
| hush_20261008_205100 | Prime Video | 558.1 | 57.2 | 12 | 548.1 | 32.3 | 466.7 | 17.0 | 4 |
| hush_20261011_204300 | Cable | 270.0 | 20.0 | 4 | 270.0 | 20.0 | 211.1 | 5.0 | 1 |
| hush_20261012_204200 | Cable | 1,001.4 | 58.6 | 11 | 996.4 | 53.6 | 834.7 | 29.1 | 8 |
| hush_20261010_222400 | Cable | 222.4 | 57.6 | 9 | 222.4 | 52.6 | 187.1 | 56.0 | 9 |
| hush_20261011_135700 | Cable | 275.4 | 79.6 | 15 | 255.4 | 69.6 | 252.0 | 61.1 | 13 |
| hush_20260914_212529 | ESPN | 503.4 | 16.6 | 3 | 410.9 | 9.1 | 463.4 | 11.1 | 3 |
| hush_20260924_220624 | Prime | 235.3 | 19.7 | 4 | 225.3 | 19.7 | 212.4 | 9.6 | 3 |
| hush_20260913_150934 | RedZone | 0.0 | 10.0 | 2 | 0.0 | 5.0 | 0.0 | 0.0 | 0 |

The session commercial figures sum to 3,908.2. The corpus total subtracts the 5-second read hole that sits inside those covers, which is how the published count-10 total is 3,903.2.

ESPN shows the aggregate hiding a bad trade. Top-five removal clears 7.5 program seconds there and gives back 92.5 commercial seconds. The 25.1-second interruption is on `hush_20260913_210542` and is still there after the top five are removed. Every session is in `session_comparison.csv`.

## Where the false matches sit

`best_match` already computes an alignment offset and the published decisions drop it. The rematch kept that offset for the 123 queries that had named a top-five pod. Two fall in the first 5 seconds of the pod and one falls in the last 5 seconds. Median fraction of the way through the pod: 0.92, 0.22, 0.67, 0.95, and 0.49. The queries do not share an interval, so no creative was removed from the library. The rows are `POD_REMOVAL_001/top_5_changed_queries.csv`.

## Receipts

Every changed query is the rematch row. Queries absent from those files kept the published decision. Together with `decisions.jsonl` they are the causal record. The comparison checked that count 10 still covers 3,903.2 commercial seconds and 432.1 program seconds, with 186 premature releases and 6,321.5 commercial seconds after them, and that the top-five program total is still 337.3.

| File | SHA-256 |
| --- | --- |
| docs/ohush/research/UNIVERSAL_V1/decisions.jsonl | `08b1b8d9a56c33681b493dff1d3337951ac9a51b812c83d2e6009afdefb86713` |
| docs/ohush/research/POD_REMOVAL_001/top_1_changed_queries.csv | `728d93798c3706b5924b84896286e2da55b15828c75081e36d2a60344b64bf61` |
| docs/ohush/research/POD_REMOVAL_001/top_5_changed_queries.csv | `b26864a8609d60f274a5307bd72a9cbbd09673e3582d81bf168c12158c7a2b48` |
| docs/ohush/research/POD_REMOVAL_001/top_10_changed_queries.csv | `61cd8a7107616bf007793c952e07ad5a3e806b795c913edcb0fa39ddc9cda4e3` |
| docs/ohush/research/VOICE_ROSTER_001/names.jsonl | `944e747a79a767c873401f88b0ab94c6da58527368fb0fbc2b171e80c862cefb` |

## Next prospective test

The one measured change that recovers program seconds at a small commercial cost is the two-second lead on the existing fingerprint reader, in `FINGERPRINT_BLOCK_001`. On this ledger it recovers 76.9 program seconds, gives up 3.0 commercial seconds, and takes the false-mute count from 72 to 55. RedZone's 10.0 program seconds go to zero. The 25.1-second interruption remains. That lead was scored on these same recordings, including October, so the next test is a later capture that was not used to find it. Adding 76.9 to the voice guard's seconds is not a result. The two errors were not measured together.

CUE-OPTICAL-001 stays on the Enhanced side. It still needs one player, that player's own manifest, and the television audio from that same session.
