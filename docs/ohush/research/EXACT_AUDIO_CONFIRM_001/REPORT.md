# Exact audio confirm 001

Not a mute. The published decisions, both counts, the gold, and the 29-pair audit were not modified. Holdouts stayed sealed. Playback stays PLAY. FINGERPRINT_CAUSAL_STREAM_001 stays closed.

Question: can a waveform check, using only audio already in hand at the decision, separate audfprint copies from landmark collisions without giving up most of the real advertisement matches?

Answer: the correlation gap is real, and it does not make a causal mute. The check that uses the published alignments gives up 1,992.8 commercial seconds to avoid 337.0 program seconds. A fingerprint limited to the five seconds available at the decision does not recover those alignments. No generator was built.

## What was frozen before the ledger

Published `decisions.jsonl` is `08b1b8d9a56c33681b493dff1d3337951ac9a51b812c83d2e6009afdefb86713`. The same process re-scored count 10 with the published read-hole mask and matched the published football numbers before any confirmation was applied: 3,903.2 commercial seconds covered, 432.1 program seconds, 72 incidents, worst interruption 25.1 seconds, RedZone 10.0 program seconds, unscorable 275.0 seconds.

The 29 saved pairs still have an empty correlation gap between 0.7383 and 0.9021. The confirmation line is the midpoint, 0.85. It was not moved after the ledger. `reviewer_label` is null on every pair. No one listened for this pass.

Stop rules, also written before the ledger: retire if confirmed commercial seconds fall below half of 3,903.2, if at least half of the 432.1 program seconds remain, or if audio available at the decision time does not recover the published count-200 alignments.

## The 29 pairs

Classification uses the saved correlations only.

| Bucket | Pairs | At 0.85 |
| --- | --- | --- |
| Waveform copy, 0.9021–0.9983 | 16, including the five count-200 controls and the FanDuel pair p18 | keep |
| Unrelated collision, about 0.017 | p06, p14, p15, p26 | reject |
| Partial copy, a half-second piece at or above 0.90 | p16, p17, p24, p25 | reject |
| Ambiguous, between the collision floor and the copy line | p08, p09, p11, p28, p29 | reject |

All 16 copies are kept. All 4 collisions are rejected. The nine partial and ambiguous pairs are not a human judgment. Their meaning is still unlabeled.

Twenty-six pairs are the winning published reference. Recomputing their correlation from that alignment changed nothing: the largest absolute difference is 0.0. p13, p14, and p15 point at a reference that is not the winning published decision, so they were not resimulated as ledger rows. Their saved audit measurements were left as they are.

## Diagnostic on the saved count-10 set

906 cross-session decisions at count 10 or above. The alignment is the published reader's: 90-second blocks, a 2-second tail, and a 5-second skip where the file does not cover the slice. Every reproduced fingerprint score matched the published score. There were 0 mismatches. That recovers the saved alignment. It does not make the alignment available when the five-second query ends.

Correlation at 0.85 then keeps 407 decisions and drops 499. Kept correlations run from 0.851 to 0.998. Dropped correlations run from 0.015 to 0.848.

Same holes, 275.0 seconds. Football:

| | Published count 10 | After the waveform cut |
| --- | ---: | ---: |
| Commercial seconds covered | 3,903.2 | 1,910.4 |
| Program seconds covered | 432.1 | 95.1 |
| Program seconds avoided | — | 337.0 |
| False-cover incidents | 72 | 17 |
| Worst program interruption | 25.1 s | 15.0 s |
| RedZone program seconds | 10.0 | 0.0 |
| RedZone incidents | 2 | 0 |
| Unscorable | 275.0 | 275.0 |

The five count-200 controls are among the 407 kept decisions. The cut does not throw away those verified copies. It throws away the lower-correlation matches, and those matches were covering 1,992.8 seconds of commercial gold. Avoiding 337.0 program seconds costs that commercial coverage. Retained commercial coverage is 48.9 percent, under the predeclared half.

The 95.1 program seconds that remain are matches at or above 0.85. They are repeated audio, not the 0.017 collisions. On the NBC night recording, the FanDuel hops at 75, 80, 90, and 95 seconds stay (0.950–0.971). The hop at 85 seconds is 0.8458 and drops, so that interruption is split rather than removed. The session's worst remaining program interruption is 15.0 seconds, with 56.4 program seconds still covered. Confirmation recognizes the promo and still covers program-labeled time. That is the promotion-versus-program question. It is not answered here, and these figures are not a revision of the published count-10 claim.

RedZone's 10.0 seconds were low-correlation covers. The diagnostic drops them. That is not a live RedZone policy.

## Causal clock

The diagnostic above uses the published block alignment. A separate check fingerprints only the query audio from `query_t0` to `query_t1`, which is the audio present at `available_at`, against the same enrolled reference.

| Pair | Published score | Score from audio available at the decision |
| --- | ---: | ---: |
| p01 | 272 | 52 |
| p02 | 223 | 192 |
| p03 | 260 | 43 |
| p04 | 242 | 35 |
| p05 | 208 | 178 |

None match. The offset from that shorter read is a different alignment, so it was not used. Fail closed. The waveform number in the ledger cannot be computed at the decision time, because the alignment it depends on still uses audio after the query.

## Decision

Retire this branch. Do not build a bounded-latency generator to feed this check. A generator that waits for the rest of the 90-second block would reopen the causal stream that already failed. The offline correlation gap, by itself, gives up about half of the published commercial seconds and still keeps real repeated audio on program-labeled time.

CUE-OPTICAL-001 stays open for one paired manifest and optical capture. That capture was not started. Enhanced stays separate from Universal. Playback stays PLAY.

Command: `PYTHONPATH=. .venv/bin/python experiments/measurement/exact_audio_confirm_001.py`
