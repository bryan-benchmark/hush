# TNF experience 001

Not a mute. October 8 Prime, `hush_20261008_205100`. The cover intervals are the published count-10 decisions. Fades do not move them. Gold was not edited. The live 250 ms bed fade was not changed.

Open `listen.html` in this folder. The wav files sit beside it and are ignored by git.

## Detection, unchanged by the fades

Twelve false covers, 57.2 s, median 5.0 s, longest 7.2 s. Seven collisions total 35.0 s. Four copies that cross a labeled commercial end total 20.3 s. One weak boundary match is 2.0 s.

The correlation that separates those groups was computed on the five-second query that ends at the decision. None of the confirmation rows for these windows extend past `available_at`. The stored reference is an earlier recording, so the lag search does not read this game's future.

The count-10 score that created the hit can still see later audio: the fingerprint index is built in 90 s blocks. Rejecting a collision is causal once that hit exists. The hit itself is not a causal fingerprint. A full-file causal fingerprint was not run.

Count-10 covered 558.1 s of labeled commercials on this tape. The longest stretches it left uncovered:

| Start | End | Seconds |
| ---: | ---: | ---: |
| 3980.898 | 4105.0 | 124.102 |
| 8802.615 | 8925.0 | 122.385 |
| 1003.282 | 1125.233 | 121.951 |
| 7169.476 | 7275.0 | 105.524 |
| 6400.0 | 6500.0 | 100.0 |
| 7677.017 | 7770.0 | 92.983 |
| 4880.0 | 4965.0 | 85.0 |
| 3548.839 | 3630.0 | 81.161 |

Inside the DraftKings pod, count-10 lets go at 320.0 s. The labeled break continues to 376.9 s, so 56.9 s remain. The pod is 237 s and this replay covered 75 s of it, so the let-go is only the last gap. The conservative count-200 cover of the same pod is the earlier 20 s, from about 150 s to 170 s, which leaves roughly 207 s of the break still playing.

## Experience, same decisions, different fades

Loudness of each whole clip is ITU-R BS.1770 integrated loudness via the pyloudnorm meter. The jump is the change in RMS level from the 400 ms before the cover to the 400 ms after it. Overlap is time when both the television and the bed are above one fifth of full gain. No listener preference was collected.

| Version | Both audible | Game fully replaced | Game partly audible | Jump on the 7 collisions |
| --- | ---: | ---: | ---: | ---: |
| Television only | 0.0 s | 0.0 s | 0.0 s | -0.03 dB |
| Current mixer, 0.25 s bed fade | 0.0 s | 4.77 s | 0.0 s | 5.42 dB |
| Crossfade 0.25 s | 0.3 s | 4.295 s | 0.45 s | 5.77 dB |
| Crossfade 0.75 s in, 1.5 s back | 1.35 s | 2.647 s | 2.01 s | 0.9 dB |
| Crossfade 1.5 s | 1.763 s | 2.011 s | 2.61 s | -0.31 dB |
| Crossfade 3 s | 3.184 s | 0.122 s | 4.348 s | -0.4 dB |

The level jump across all 12 clips is not a useful average. Incidents 8, 10, and 11 open on a near-silent gap, around −64 to −86 dBFS in the 400 ms at the cut, then the program level returns. Incident 2 dips for a few seconds. Incident 12 stays at program level straight through. A bed entering at normal level after silence produces a huge arithmetic jump that is not the collision problem. On the seven collisions the television is already at program level, and the jump column is only those seven. Whole-clip loudness stays near −31 LUFS for every version, because the bed was matched to the television before the cover.

The current mixer cuts the television at the decision and fades only the bed. On the way back it fades the bed out and restores the television after that fade, so the game is gone for the whole mistake plus a quarter second.

A crossfade keeps some of the game audible at both edges. On a mistake shorter than the fade, the return begins before the cover is complete, so the game never goes fully away. That is measured above as partly audible seconds. It is not a claim that the result sounds better.

September 24 break 6 is a different tape. The labeled return is at 2,338.326 s. The booth voice on that break is 40.7 s later. Both moments are on the listening page. Acoustic return on the same break is 84.7 s. No new return detector was run.

