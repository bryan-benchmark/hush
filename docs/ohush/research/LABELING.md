# Where to mark intervals

The blind labeler is already the dataset task. Detector scores, suggested outs, and fade marks are not shown there. Computer guesses stay off until a range is closed, and this task never turns them on.

```text
http://127.0.0.1:3010/label?task=dataset
```

The four ranges already closed in `GOLD_DATASET_20261013` stay closed. Do not move those marks because a detector disagrees.

Open queue on that screen, in this order:

1. Thursday 8 October, Prime, Bucs at Cowboys. `hush_20261008_205100`. About 2:54:00 of captured audio. The first five minutes are a restart, then the recording is off until 9:48pm. Elapsed time is the audio in the order it was captured. It is not the live-engine clock, so it does not score Thursday's mute log.
2. Sunday 11 October night. `hush_20261011_204300`. About 4:00:05. The first two minutes stop, and the file resumes at 9:09pm. Mark where the program changes.
3. Monday 12 October, Monday Night Football. `hush_20261012_204200`. About 3:38:32, continuous from 8:42pm. This audio was sitting in the Sunday folder. It is its own session now.
4. Saturday 10 October, Browns at Jets. `hush_20261010_222400`. About 1:41:05, continuous.
5. Sunday 11 October afternoon. `hush_20261011_135700`. About 1:21:37, continuous. Separate from Sunday night.

The WAV files for those five stay in `ohush_live/sessions/`. The labeler sessions are symlinks built by `scripts/link_live_label_sessions.py`. None of these five ranges is marked fully annotated.

A new live start is its own session under `recordings/`, and it shows up on this screen when the first chunk closes. The same name and provider, started again within 30 minutes, continues that session and marks the hole. Hear the TV keeps the file rolling without ending it.

Holdouts `hush_20260917_205513` and `hush_20260920_200635` stay sealed.
