# Paste this with the zip

You are auditing OHush, a local system that tries to detect TV commercial breaks from optical audio and cover them on Mac speakers. Today is 13 October 2026. The packet has two workstreams. Do not mix them.

1. Research dataset. Read `DATASET_2026-10-13.md` first, then `identity_listen.json`. Prime and August Hulu already have interval gold. October Hulu and three football nights do not. The 10 Sep, 10 Oct, and 11 Oct captures are more than one program each. Probe answers are 18-second samples, not boundaries.
2. Thursday 8 Oct product failure. Read `HANDOFF.md`, then `LIVE_RECOVERY_001/REPORT.md`, then `LIVE_RECOVERY_001/01-defect-audit.md`. Use `tnf_digest.json` for the numbers. Open the raw `decisions.jsonl`, `labels.jsonl`, `overrides.jsonl`, and `track.jsonl` when you need a mechanism, not for a headline rate.

## Hard rules

- `scientific_authority` is false. Thursday is `live_dev`. It is not allowed to change Exp001–005.
- `labels.jsonl` are point markers. `gold-manifest.json` has an empty interval list on purpose. Do not publish recall, precision, or commercial-heard-time as if gold existed.
- The track has 32 engine runs. Clocks reset. Decision-segment index is not track-run index. Do not merge them. If you join them, show the join.
- `audio_world_score` on a `REPLACEMENT_TO_PROGRAM` row is the return-kind score. For the audio family, departure and return are the same PANNs distance. High means “unlike the recent window,” which is not a return.
- LIVE_RECOVERY_001 candidate C1 passed fixtures and a Mode A feature replay (veto-shaped stuck PLAY 88s → 11s). Mode A does not re-run the audio or speaker models. Do not call that a live fix. Live promotion was not authorized. Shadow mode was not built.
- Do not recommend deleting `.booth.json` without a listening test. Do not recommend retuning `AUDIO_STRONG` until interval gold exists. The evening used 0.14 and 0.18 at different times; the working tree now has 0.22, and 10 of 13 logged auto-covers sit below 0.22.

## What to return — research dataset

1. Confirm which sessions are safe to mark as one program, and which must be split, using only `DATASET_2026-10-13.md` and `identity_listen.json`. Do not invent boundaries between the 18-second probes.
2. A labeling order. Closed gold stays closed. Holdouts stay sealed. The cable scripted cell is still missing.
3. Do not score October Hulu or the unlabeled football files from freeze counts. Those runs were hashed before anyone listened for commercials.

## What to return — Thursday night

1. A failure narrative of 8 October, split into early (no auto cover), middle (solo-audio covers the human often undoes), and late (one-second uncover loops, including decision segment 12). Name the mechanism for each, with file and field, not a vibe.
2. Whether C1/C2 would have stopped segment 12’s flaps or whether recorded `booth_present` would still uncover, by design. Say which evidence would decide that, and whether it is already in `track.jsonl`.
3. The shortest path to a number we are allowed to believe: interval gold on 3–5 long runs, then commercial-heard time and program-covered time, per run, held-out runs 25–31 untouched until the metric is frozen.
4. What not to build next. In particular, do not revive adaptive-distance return (Exp003 already failed it) and do not invent Exp006 from the ESPN game.
5. A risk list for the next live game if someone turns auto on with the current working tree anyway: startup blindness, unaudited booth ids, `allow_auto_play` always true, `BOOTH_RETURN_PERSIST_S = 0`, semantic worker absent, no shadow mode.

Disagree with the handoff where the logs disagree with it. Cite the file.
