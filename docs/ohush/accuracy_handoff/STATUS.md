# Accuracy handoff — 14 October 2026

Read this file, then `docs/ohush/research/UNIVERSAL_V1/REPORT.md`, then `docs/ohush/research/ACCURACY_NORTH_STAR_001/REPORT.md`. The json and csv next to a report are stronger than a sentence in the report. `docs/ohush/swarm/SCOREBOARD.md` is the running record. Earlier rows are not replaced.

Champion: no authorized mute. Research baseline: Universal v1. Enhanced has no accuracy number.

## What changed

`ACCURACY_NORTH_STAR_001` is the scoring standard. Error is commercial seconds heard, program seconds covered, false-cover incidents, start delay, return delay, worst interruption, and unscorable time. A single percentage is not the score.

99.99% of the football corpus (17,648.4 commercial seconds + 67,428 published program seconds) is 8.51 seconds. 99.99% of a three-hour game is 1.08 seconds. About 31 hours cannot certify either number.

The 152.3 seconds from applying a 1.12-second delay to every football pod is a benchmark for the frozen DSP scan. It is not a physical lower bound on every reactive detector.

The three lanes are closed. Their reports are in `docs/ohush/swarm/AGENT_*`. They were not rerun for this packet.

## Universal v1

`experiments/universal_v1/replay.py` wrote the timeline. Self-match score 634. The stream reproduced the frozen fingerprint counts, 91 program-region and 813 in-pod windows at count 10, before the ledger was accepted.

Policy, frozen before the score was read:

- Cover only when a 5-second chronological audfprint query scores at least 200.
- The action applies after the query ends, to later audio only.
- References are gold commercials from earlier recordings. The recording under decision is excluded. Enrollment is label-informed.
- A later query under 200 returns to play because evidence is missing. That is not a detected program return.
- DSP is on the receipt and cannot cover alone.
- Handoff phrases are not on this clock. They were transcribed only beside gold marks.
- The 40 ms dip was not admitted.

Football result, count 200:

| | |
| --- | ---: |
| Commercial seconds heard | 17,530.7 |
| Commercial seconds covered | 25.0 |
| Program seconds covered | 0 |
| Pods with any cover | 2 / 136 |
| False-cover incidents | 0 |
| RedZone seconds covered | 0 |

The 25 seconds are 20 on Thursday Prime Video (`hush_20261008_205100`, gold 139.874–376.900, no DSP hit inside 30 s) and 5 on Monday cable (`hush_20261012_204200`, gold 5080.063–5216.609, DSP delay 14.937 s). Both covers end inside the pod. Read failures of 275 s are unscorable, not heard and not covered.

Count 10 is an ablation from the same queries, not a refit and not the baseline. It hears 13,652.5 football commercial seconds and covers 432.1 football program seconds, 72 false-cover incidents, worst interruption 25.1 s, plus 10.0 RedZone seconds.

Receipts: `docs/ohush/research/UNIVERSAL_V1/receipts.jsonl`. One row per decision. `decisions.jsonl` is the query scores before the action rule.

## Not in this zip

WAV files, embeddings, booth audio, `.booth.json`, the live mute engine, sealed holdouts `hush_20260917_205513` and `hush_20260920_200635`, and the blinded adjudication key. The human queue is 53 clips and is not part of this review.
