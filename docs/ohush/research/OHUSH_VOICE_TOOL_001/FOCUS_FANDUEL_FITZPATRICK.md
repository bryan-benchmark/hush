# Focus pair: FanDuel vs Fitzpatrick

This pair was scored as a commercial-mean and AudioSet-tag comparison. It is not established as the same speaker. Owner label on fn0009 is Ryan Fitzpatrick. Owner Who on the FanDuel speech box is `Fanduel in game broadcast`, with no person name. If a later listen names the same person on both, speaker recognition should agree on that name, and mute stays a commercial decision.

Raw stamps from `tags_seconds.jsonl`. Classifier extract checked against `torch.nn.LayerNorm` + Linear: max abs diff `8.9e-8` on the FanDuel stamp at 575.0.

Stamp contract: decision time `t` uses audio `[t-5, t)`. `lookback_inside_box` is the fraction of that five seconds that overlaps the owner box.

## FanDuel in-game broadcast — fn0110

Box `572.06–577.30`. Path B: Kirk Herbstreit 0.3214, gap 0.2157, passes guard.

| t | lookback inside | mean10 | hot | top1 | Speech | Music | Bg music | Jingle | Crowd |
| ---: | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 573.0 | 0.19 | 2.160 | yes | Music 0.282 | 0.272 | 0.282 | 0.004 | 0.002 | 0.000 |
| 574.0 | 0.39 | 2.399 | yes | Speech 0.298 | 0.298 | 0.211 | 0.002 | 0.001 | 0.000 |
| 575.0 | 0.59 | 2.384 | yes | Speech 0.307 | 0.307 | 0.252 | 0.004 | 0.001 | 0.000 |
| 576.0 | 0.79 | 2.322 | yes | Speech 0.280 | 0.280 | 0.262 | 0.004 | 0.001 | 0.000 |
| 577.0 | 0.99 | 2.795 | yes | Speech 0.267 | 0.267 | 0.260 | 0.000 | 0.000 | 0.000 |

Box medians: Speech 0.280, Music 0.260, Background music 0.004, Jingle 0.001, Crowd 0.000, mean10 2.384, hot 5/5. Median lookback inside the box: 0.588.

## Ryan Fitzpatrick pregame — fn0009

Box `6589.00–6609.00`. Path B: Andrew Whitworth 0.0903, rejected.

| t | lookback inside | mean10 | hot | top1 | Speech | Music | Bg music | Jingle | Crowd |
| ---: | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 6590.0 | 0.20 | −0.831 | no | Speech 0.285 | 0.285 | 0.187 | 0.000 | 0.000 | 0.000 |
| 6591.0 | 0.40 | 0.052 | no | Speech 0.278 | 0.278 | 0.223 | 0.001 | 0.000 | 0.000 |
| 6592.0 | 0.60 | 0.759 | yes | Speech 0.270 | 0.270 | 0.205 | 0.000 | 0.000 | 0.000 |
| 6593.0 | 0.80 | 1.683 | yes | Speech 0.297 | 0.297 | 0.256 | 0.001 | 0.000 | 0.000 |
| 6594.0 | 1.00 | 2.393 | yes | Speech 0.284 | 0.284 | 0.176 | 0.000 | 0.000 | 0.000 |
| 6595.0 | 1.00 | 3.000 | yes | Speech 0.299 | 0.299 | 0.211 | 0.001 | 0.000 | 0.000 |
| 6596.0 | 1.00 | 3.405 | yes | Speech 0.302 | 0.302 | 0.231 | 0.001 | 0.000 | 0.000 |
| 6597.0 | 1.00 | 3.955 | yes | Speech 0.302 | 0.302 | 0.231 | 0.001 | 0.000 | 0.000 |
| 6598.0 | 1.00 | 4.158 | yes | Speech 0.332 | 0.332 | 0.225 | 0.001 | 0.000 | 0.000 |
| 6599.0 | 1.00 | 4.219 | yes | Speech 0.300 | 0.300 | 0.205 | 0.001 | 0.000 | 0.000 |
| 6600.0 | 1.00 | 4.030 | yes | Speech 0.293 | 0.293 | 0.119 | 0.000 | 0.000 | 0.000 |
| 6601.0 | 1.00 | 4.008 | yes | Speech 0.334 | 0.334 | 0.158 | 0.001 | 0.000 | 0.000 |
| 6602.0 | 1.00 | 3.901 | yes | Speech 0.295 | 0.295 | 0.114 | 0.000 | 0.000 | 0.000 |
| 6603.0 | 1.00 | 3.559 | yes | Speech 0.308 | 0.308 | 0.147 | 0.000 | 0.000 | 0.000 |
| 6604.0 | 1.00 | 2.746 | yes | Speech 0.339 | 0.339 | 0.102 | 0.000 | 0.000 | 0.000 |
| 6605.0 | 1.00 | 1.787 | yes | Speech 0.372 | 0.372 | 0.063 | 0.000 | 0.000 | 0.000 |
| 6606.0 | 1.00 | 0.710 | yes | Speech 0.428 | 0.428 | 0.064 | 0.000 | 0.000 | 0.000 |
| 6607.0 | 1.00 | −0.345 | no | Speech 0.404 | 0.404 | 0.047 | 0.000 | 0.000 | 0.000 |
| 6608.0 | 1.00 | −0.760 | no | Speech 0.288 | 0.288 | 0.141 | 0.000 | 0.000 | 0.000 |
| 6609.0 | 1.00 | −1.173 | no | Speech 0.330 | 0.330 | 0.103 | 0.000 | 0.000 | 0.000 |

Box medians: Speech 0.301, Music 0.167, Background music 0.000, Jingle 0.000, Crowd 0.000, mean10 2.570, hot 15/20. Median lookback inside the box: 1.000.

## Reading

Both boxes are Speech on top. FanDuel's median Music is 0.260 against Fitzpatrick's 0.167. Crowd and Jingle stay near zero on both. The commercial means still sit near each other at the box median. Fitzpatrick's mean10 path is cold, then hot, then cold again. FanDuel's five stamps stay hot. That shape difference is in the logistic mean, not in the AudioSet names.
