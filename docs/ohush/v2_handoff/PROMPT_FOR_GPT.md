# What to do with this packet

Read `docs/ohush/v2_handoff/STATUS.md` first. Then `docs/ohush/research/UNIVERSAL_V2_CONTENT_STATE_001/REPORT.md` and `results.json`. Use `docs/ohush/research/UNIVERSAL_V1/REPORT.md` for the baseline. Do not treat a report sentence as stronger than the matching json.

Today is 14 October 2026. This packet is the v2 decision. It is not a request to retune the mel logistic, promote a mute, or unseal a holdout.

## Do not

- Relabel closed gold because a detector disagrees.
- Unseal `hush_20260917_205513` or `hush_20260920_200635`.
- Treat the October evaluation frontier as a chosen operating point. It was written after the calibration choice and was not allowed to change it.
- Treat 27 of 50 missed pods at `p ≥ 0.999` as a result. That count is descriptive. The selected policy covers none of them.
- Call a top-bin score a calibrated probability. On the calibration games that bin is about 70% commercial.
- Report an Enhanced accuracy. No feed was aligned.
- Recommend a live mute change.

## What a useful answer is

1. Check the scorable totals and the FAIL gate against `results.json`. Name any figure in `STATUS.md` the files do not support.
2. Say whether retiring this mel logistic, and refusing to refit it on the October games, follows from the calibration table.
3. Say what the next measurement should be, in commercial seconds and program seconds versus Universal v1, and what result would retire it. The threshold still has to be chosen on earlier games.
4. Say what not to build. In particular, do not retune count 10, do not spend the next run on the DSP distance, and do not open the holdouts.
