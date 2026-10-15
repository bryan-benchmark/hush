# What to do with this packet

Read `docs/ohush/v3_handoff/STATUS.md` first. Then the two v3 reports and their `results.json` files. Use Universal v1 as the baseline and Universal v2 as a closed failure. Do not treat a report sentence as stronger than the matching json. Where speech counts disagree between a sentence and `chunks.jsonl`, the jsonl wins.

Today is 14 October 2026. This packet is the v3 decision. It is not a request to retune a threshold, promote a mute, or unseal a holdout.

## Do not

- Relabel closed gold because a detector disagrees.
- Unseal `hush_20260917_205513` or `hush_20260920_200635`.
- Reopen the v2 mel-logistic decision. It failed. Do not refit it on the October games.
- Treat 44 of 50 DSP-missed pods at `p ≥ 0.9` as a detection. That count is descriptive. The selected embedding rule covers none of them, and the 0.9 threshold hides 2,432.4 calibration program seconds.
- Call a top-bin score a calibrated probability. On the calibration games the 0.9–1.0 bin is 74.3% commercial.
- Treat 12 spoken-early pods as 12 causal detections. The recognizer knew 3 of them before the gold start. The other nine were recognized after commercial audio had started.
- Treat `strong_events_at_least_15s_from_every_pod = 10` as ten extra false alarms on top of the twelve. Two of those moments are also inside the 30-second lead window. Count unique spoken times from `chunks.jsonl`.
- Report an Enhanced accuracy. No feed was aligned.
- Recommend a live mute change. October has already been inspected, so it is not a blind validation.

## What a useful answer is

1. Check the embedding FAIL against `docs/ohush/research/UNIVERSAL_V3_EMBEDDINGS_001/results.json`. Name any figure in `STATUS.md` the files do not support. Separate newly covered seconds, lost v1 seconds, and the net.
2. Check the speech counts against `chunks.jsonl`, not only against `results.json`. Keep the spoken-word time separate from the chunk-end time.
3. Say whether retiring the embedding rule, and refusing to refit it on October, follows from the calibration frontier.
4. Say whether the speech scan is evidence or an action policy, and what result would have made it an action policy. It was not given a mute threshold.
5. Say what not to build. In particular, do not retune count 10, the CNN14 anomaly distance, the DSP thresholds, or the v2 mel logistic. Do not open the holdouts. Do not add a television-timeout feed to Universal.
