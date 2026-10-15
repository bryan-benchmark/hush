# What to do with this packet

Read `docs/ohush/v4_handoff/STATUS.md` first. Then `docs/ohush/research/UNIVERSAL_V4_BROADCAST_SEQUENCE_001/REPORT.md` and `results.json`. Use Universal v1 as the baseline. Universal v2 and Universal v3 embeddings are closed failures. Do not treat a report sentence as stronger than the matching json.

Today is 14 October 2026. This packet is the v4 sequence decision. It is not a request to retune a threshold, promote a mute, or unseal a holdout.

## Do not

- Relabel closed gold because a detector disagrees.
- Unseal `hush_20260917_205513` or `hush_20260920_200635`.
- Reopen the v2 mel logistic, the v3 embedding rule, count 10, the CNN14 anomaly distance, or the 18 dB micro-dip gate.
- Treat the least-program rows in the report as selected policies. They cover commercial audio only by exceeding 10 program seconds. The selected rule is play.
- Treat a zero-cover grid point as evidence the model can tell ads from programming. It never fires.
- Treat RedZone's 0 covered seconds as a safety result. RedZone was a training negative, and the selected rule covers nothing.
- Call the frozen CNN14 probability, used here as one input, a rerun of the v3 mute grid.
- Score the unfinished 5-second speech scan. It is not in this zip.
- Treat speaker enrollment as measured. The verified count is 0.
- Report an Enhanced accuracy. No feed was aligned.
- Recommend a live mute change. October has already been inspected, so it is not a blind validation.

## What a useful answer is

1. Check the FAIL against `docs/ohush/research/UNIVERSAL_V4_BROADCAST_SEQUENCE_001/results.json`. Name any figure in `STATUS.md` the file does not support. Separate newly covered seconds, lost v1 seconds, and the net.
2. Say whether retiring the sequence rule follows from the calibration table, including the 35.2-second program point that was not selected.
3. Say whether departure and return were actually separate heads, and whether RedZone can be cited as an unseen control.
4. Say what not to build. In particular, do not retune this grid on October, do not open the holdouts, and do not enroll speakers from `.booth.json`.
