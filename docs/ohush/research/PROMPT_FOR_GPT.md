# Audit this packet

You are auditing the 13 October 2026 stopping point for OHush. Read `STOPPING_POINT.md` first, then `SEGMENT12_ROOT_CAUSE.md`, `DATA_INTEGRITY_AUDIT.md`, and `MEASUREMENT_V1_REPORT.md`. The earlier Thursday narrative is `HANDOFF.md`. Code under `code/` is the working tree after the safety change. `frozen/` is the Thursday log the claims were checked against.

## What to verify

1. Segment 12 really is track `run29`. The join rule is timestamp within 0.05 s and audio distance within 0.002. 14 automatic returns matched; t=235.008 did not. Confirm or refute from `frozen/track.jsonl` and `frozen/decisions.jsonl`. Do not equate segment index with run index.
2. At run29 t≈221 and t≈224, `booth_present` is true, similarity is about 0.15 and 0.12, and the cluster is not in that row's `booth_ids`. The state change refuses that as a return. Read `code/ohush_live/state.py` `_booth_match` and the tests. Say whether a remaining path can still uncover on the next tick.
3. `.booth.json` ids (`c0001`, `c0002`, `c0015`, `c0017`) are not the `booth_ids` list on those run29 rows. Do not treat them as the same set.
4. The WAV joins are duration candidates only. `run00` and `run21` are unresolved. `run19` and `run29` are unique duration candidates and are not sample-locked. Say if any join was over-claimed.
5. `experiments/measurement/metrics.py` matches `MEASUREMENT_V1_REPORT.md`. The never-cover / always-cover numbers are harness checks, not detector scores. Thursday has no interval gold, so there is no live-algorithm baseline.
6. Listen to `booth_excerpts/` if you can. They are 10-second candidates from `audio_0044.wav`, aligned only by duration to run29. Do not promote an id from a clip. Say what each clip sounds like (announcer, ad, crowd, unsure).

## Do not

- Invent commercial recall for 8 October.
- Retune Exp001–005.
- Treat `run25`–`run31` as unseen.
- Recommend deleting `.booth.json` from one listen.

Disagree with the writeups where the logs or the code disagree. Cite the file.
