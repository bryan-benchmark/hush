# First stopping point — 13 October 2026

No live auto-output was enabled. Exp001–005 were not modified. Closed gold was not edited. The dirty tree was not reset.

## Done

1. **Alignment.** `DATA_INTEGRITY_AUDIT.md` and `recording_registry.json`. Thursday has 32 frozen engine runs and 33 WAVs. 13 runs have a unique duration candidate. 19 do not, including `run00` and `run21`. Decision segment 12 is track `run29` by timestamp and audio score (14 of 15 returns), not by index.
2. **Blind labeling.** Already at `/label?task=dataset`. It does not show detector scores. Thursday runs are intentionally absent until a join is real. See `LABELING.md`. No new Thursday intervals were invented.
3. **Segment 12.** `SEGMENT12_ROOT_CAUSE.md`. The low-similarity `booth_present` flag (0.12–0.18 on a foreign cluster) no longer uncovers and no longer blocks solo audio. A human cover now holds 2.5 s against a high similarity before it uncovers. High similarity on a non-trusted cluster (0.71, 0.87) can still return after that hold. Tests: `tests/test_ohush_live_state.py`, fixture `D_low_similarity_booth_present_stays_covered`.
4. **Listening materials.** Seven 10-second candidates in `booth_excerpts/`, from the `run29` duration candidate only. Not an identity verdict. `.booth.json` was not edited. Its ids are not the ids `run29` was trusting.
5. **Metrics.** `experiments/measurement/metrics.py` scores commercial-heard time, program-covered time, false covers, false returns, and start delay on one clock. Degenerate never-cover and always-cover checks ran on the four closed ranges (`MEASUREMENT_V1_REPORT.md`). The live algorithm was not scored. Thursday has no gold.
6. **Hypotheses.** `HYPOTHESES_V1.md`. Smallest next falsifier: confirm or reject the `run19` ↔ `audio_0023.wav` join, then listen. Among signals, listen to the booth excerpts (H3) before any new detector.

## Not done, and why

| Item | Why it stopped |
|------|----------------|
| Thursday interval gold for `run00`, `run11`, `run19`, `run21` | `run00` and `run21` have no WAV join. `run11` is 1.45 s off. `run19` is a 0.30 s duration candidate and is not sample-locked. |
| Live-algorithm baseline scores | No Thursday gold, and re-extracting features on the closed games would be a new experiment. |
| Shadow mode | Not built. Automatic covering was not turned on. |
| A clean re-run of the speaker worker on Thursday audio | Needs the same WAV join. Historic `booth_present` values are not what today's worker would emit. |
| Identity verdict on the four stored ids | The excerpts are ready to hear. They are duration candidates from `run29` only. `run21`, which holds most of `c0001` and `c0002`, has no file join. |

## Safety change in the working tree

`ohush_live/state.py` no longer treats `booth_present` as verified when a similarity is present and below 0.55. `ohush_live/policy.py` adds `HUMAN_COVER_RETURN_PERSIST_S = 2.5` so a human cover is not undone by one verified-looking tick. Automatic covers still return immediately on a real similarity match. That constant was not fit to Thursday scores. It is a one-tick guard.

The speaker worker can still set `booth_present` from a trusted cluster id even when that frame's similarity is low. The state machine ignores that contradiction. Cluster-id trust, when no similarity was published at all, remains. It is tested so it stays visible.
