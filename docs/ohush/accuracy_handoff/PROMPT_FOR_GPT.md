# What to do with this packet

Read `docs/ohush/accuracy_handoff/STATUS.md` first. Then `docs/ohush/research/UNIVERSAL_V1/REPORT.md` and `results.json`. Then `docs/ohush/research/ACCURACY_NORTH_STAR_001/REPORT.md`. Use `docs/ohush/swarm/SCOREBOARD.md` as the record of earlier rows. Do not treat a report sentence as stronger than the matching json.

Today is 14 October 2026. This packet is the accuracy baseline. It is not a request to retune a threshold, promote a mute, or unseal a holdout.

## Clocks

Times are capture-order audio clocks. `hush_20261008_205100` is Thursday 8 October, Prime Video, on that clock. It is not the live-engine clock. Do not score Thursday's mute log.

RedZone is `hush_20260913_150934`, 0–7200 s, zero commercials. It is a negative control.

## Do not

- Relabel closed gold because a detector disagrees.
- Unseal `hush_20260917_205513` or `hush_20260920_200635`.
- Call count 10 the baseline. It is the ablation.
- Report an Enhanced accuracy. No feed was aligned, so Enhanced has no number.
- Treat the 152.3-second DSP benchmark as a proof that every reactive detector is at least that slow.
- Treat a fingerprint match as a named creative, or the end of a match as a program return.
- Recommend a live mute change. Universal v1 was not promoted.

## What a useful answer is

1. Check the football ledger against `results.json` and the two cover rows in `receipts.jsonl`. Name any figure in `STATUS.md` that the files do not support.
2. Say whether Universal v1 is a valid causal baseline given label-informed enrollment, or whether that enrollment makes the 25 covered seconds an oracle result. Cite the policy fields.
3. Say what the next measurement should add, in commercial seconds and program seconds, and what result would retire that measurement. The comparison target is this ledger, not a new isolated detector.
4. Say what not to build. In particular, do not retune count 10, do not spend the next run shaving the 73 seconds of delay on pods the DSP scan already sees, and do not open the holdouts to develop a threshold.
