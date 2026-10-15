# Universal v1

First causal play/cover timeline. Research baseline only. It is not a promoted mute, and it is not a 99.99% result.

Enhanced has no number in this report. No game-event feed, schedule, or device metadata was aligned. That status is `not_measured` in `results.json`. It is not the football score below.

| Artifact | sha256 |
| --- | --- |
| `experiments/universal_v1/replay.py` | `829ffda4ccb68025f00154f80b6412681b8d15556ad2138a2328c0fe331dda86` |
| `results.json` | `8335b891c627b7965e44bd98cb11ee08ae634cedabd85aa4a7b2d6dffd75d1c4` |

Command: `MPLCONFIGDIR=/tmp/mpl PYTHONPATH="src:.:experiments/broadcast_intelligence/third_party/audfprint" .venv/bin/python experiments/universal_v1/replay.py`

Wall clock 379.3 s. The stream reproduced the frozen fingerprint counts before any of these seconds were accepted: 91 program-region and 813 in-pod windows at count 10. Self-match score 634.

## Policy

One independent path is allowed to cover. A 5-second chronological audfprint query must score at least 200, the published bar. The action changes when that query ends, and it applies only to audio after that instant. A later query under 200 returns the timeline to play. That let-go is missing evidence. It is not a detection that the program returned.

The reference library is gold commercial intervals from earlier recordings. The recording being decided is excluded. Enrollment is label-informed. The decision itself does not read future audio.

Count 10 is an ablation computed from the same queries. It was not refit. ESPN had already selected it, and it had already missed the false-identification budget, so it is not the baseline.

Left off the action, on purpose:

- DSP alarms are on the receipt and cannot cover alone.
- The 40 ms dip was not admitted. Its gate was not met, and the episode times were not kept.
- Sign-off phrases were transcribed only next to gold marks. Using those windows as the places to look would aim the timeline with the label.

Holdouts stayed sealed. Live output was not changed.

## Football ledger

Published corpus: 17,648.4 commercial seconds, 67,428 program seconds, 8.51 seconds at 99.99%. Read failures inside football spans total 275.0 s (240.0 on the Thursday Prime Video recording, 35.0 on Sunday night cable). Those seconds are unscorable. They are not counted as heard or covered.

| | Universal v1, count 200 | Ablation, count 10 |
| --- | ---: | ---: |
| Commercial seconds heard | 17,530.7 | 13,652.5 |
| Commercial seconds covered | 25.0 | 3,903.2 |
| Program seconds covered | 0.0 | 432.1 |
| Total scored error | 17,530.7 | 14,084.6 |
| False-cover incidents | 0 | 72 |
| Worst continuous program interruption | 0.0 s | 25.1 s |
| Pods with any cover | 2 / 136 | 105 / 136 |
| Pods with no cover | 134 | 31 |
| Premature let-go incidents | 2 | 186 |
| Ad seconds heard after a let-go | 328.5 | 6,321.5 |
| Start delay, median, on pods that were covered | 9.937 s | 17.436 s |
| Return delay | none; both covers ended inside the pod | median 5.256 s on 26 pods that were still covered at the gold end |

The 25.0 covered seconds are 20.0 on Thursday Prime Video and 5.0 on Monday cable. Every other football commercial second that could be scored was heard. Against the champion, which hears all 17,648.4 and hides nothing, v1 removes 25 commercial seconds and adds no hidden programming.

The 1.12-second figure in the north-star ledger is a benchmark for this DSP stream, not a physical lower bound on every reactive detector. A faster detector could beat 152 seconds. This configuration cannot: a cover starts only after a 5-second query, and the two pods it touched were both about 10 seconds late.

## The two covers

Both gold starts are outside the DSP 3-second window.

| Recording | Gold pod | What matched | Cover | What the listener got |
| --- | --- | --- | --- | --- |
| Prime Video, Oct 8 | 139.874–376.900 (237.0 s). No DSP hit inside 30 s | Sept 24 Prime, pod at 234.244 s. Scores 272, 223, 260, 242 | 150–170 s | 10.126 s heard, then 20 s covered, then the remaining 206.9 s heard |
| Cable, Oct 12 | 5080.063–5216.609 (136.5 s). DSP delay 14.937 s | ESPN pod at 6852.564 s. Score 208 | 5090–5095 s | 9.937 s heard, then 5 s covered, then the remaining 121.6 s heard |

The matches are earlier commercial-region audio, not named creatives. Letting go is why a recognized pod still contributes hundreds of heard seconds. Holding those two covers until the gold end would be an oracle return, and this replay does not do that.

RedZone, count 200: 0 program seconds covered. Scripted Hulu, count 200: 0 of 30 pods covered, 2,382.2 commercial seconds heard, 0 program seconds covered.

## Ablation

Count 10 hears 3,878.2 fewer football commercial seconds than v1 and covers 432.1 football program seconds that v1 left alone. It also covers 10.0 RedZone seconds in 2 incidents, and 61.5 scripted program seconds. Worst football program interruption 25.1 s, on NBC `hush_20260913_210542`. Net football error falls from 17,530.7 s to 14,084.6 s. That is still about 1,650 times the 8.51-second budget, and it spends the program-loss term the published bar had kept at zero. It is not the baseline.

## Receipts

Every decision is a row in `receipts.jsonl`: the query window, the score, the reference it matched, the DSP bit at that instant, the action, and the reason. DSP was not allowed to change the action. Handoff and the micro-dip are marked not on the clock.

## What this baseline asks for next

The 6,407 seconds are still there. Count 200 put 20 seconds of cover inside one of those missed pods and then released it. The return is still a let-go, not evidence that football came back. The next experiment has to add an independent path that recognizes breaks this fingerprint does not hold, and a positive reason to stay covered that is not a timer. That comparison is a delta against this ledger: commercial seconds removed, program seconds added, and whether the same delta appears on another broadcast.
