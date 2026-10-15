# Paste this with the zip

You are checking an OHush evidence packet. Today is 14 October 2026. Read `STATUS.md` first, then `census/REPORT.md`, then `census/results.json` and `census/corroboration.json`. The code that produced the new files is `code/scan.py` and `code/corroborate.py`.

This packet is not a mute authorization. Universal v1 was not edited. October was not used to choose a threshold. Do not recommend opening a holdout, retuning EXP-01, or changing live playback.

## Check the receipts

1. Hash every file except `receipts.json`. The sha256 values in `receipts.json` must match. If a hash does not match, stop and name the file.
2. `census/results.json` may name only `hush_20260827_135935`, `hush_20260914_212529`, and `hush_20260924_220624`. `mute_policy`, `october_used`, and `holdouts_opened` must be false. `retunes_exp001` must be false.
3. Confirm no threshold in `code/scan.py` or the json is marked as a chosen operating point. The grid is −120, −100, −85, −70, −55, and −40 dBFS.
4. Recompute one row from `census/results.json` against `STATUS.md`: Prime at −85 dB, program events per hour, and causal starts within 1 second. Name any sentence in `STATUS.md` that the json does not support.
5. `prior/EXP01_results.json` is the already-finished short-dip gate. Confirm its `gate` field. Do not treat this packet as a new run of that experiment.
6. `prior/FINGERPRINT_REPORT.md` stays INCONCLUSIVE. Do not turn a fingerprint match into a named commercial or a return to the game.
7. `gold/HOLDOUT_V1.json` and the truth ledger are absent on purpose. Do not infer their contents.

## What to return

1. Whether the format receipt and the two silence scans support the kill decision for a universal mute.
2. Whether Hulu and Prime having a deeper floor than the program is enough to keep the notch as a research description. ESPN is the counterexample that has to survive in your answer.
3. What not to build next. In particular, do not fit a new threshold on these three tapes, do not sweep ffmpeg settings until a binary exists, and do not combine this cue with the fingerprint into a mute policy from this packet alone.

Disagree with `STATUS.md` where the json disagrees. Cite the file.
