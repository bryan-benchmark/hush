# Groove varied 001 — 15 October 2026

No live auto-output was enabled. The gate was not changed. These files are not installed as beds. Nobody has listened to them. The other catalogs in the brief were not fetched.

One question: on breaks a person marks, does a rotation of three full CC0 recordings beat silence for the next game? This night is a screening. It is not the week-long choice.

## The recordings

Source page: [Free Rhythm Game Music Pack 1](https://opengameart.org/content/free-rhythm-game-music-pack-1), author `tricksntraps`, license CC0, [public domain dedication](https://creativecommons.org/publicdomain/zero/1.0/). The page lists ten tracks. These three were downloaded. The other seven were not.

The tempos below are the tempos printed on that page. They were not measured from the audio. The files were not audited for samples the author may have used inside them.

Each source is 44.1 kHz stereo. Each prepared file is the full recording, resampled to 48 kHz stereo, with no trim. All three sit at RMS 0.10. The loudest peak is 0.42, under the 0.90 cap, so the shared level did not have to be lowered.

| Play order | Title | Page tempo | Duration | Prepared file |
| --- | --- | --- | --- | --- |
| 1 | Ascend | 130 | 226.8 s | `experiments/groove_varied_001/prepared/ascend.wav` |
| 2 | Starting Over | 122 | 289.4 s | `experiments/groove_varied_001/prepared/starting_over.wav` |
| 3 | Lost Utopia | 127 | 187.1 s | `experiments/groove_varied_001/prepared/lost_utopia.wav` |

Lost Utopia is the short one, just over three minutes. If a marked break outlasts the file, the rest of that break stays silent. Do not loop it, and do not start the next recording in the same break.

## How to run the eight breaks

Detection stays out. A is silence. B is the next recording, started at the beginning and left alone until the break ends or the file ends.

| Break | Condition | What plays |
| --- | --- | --- |
| 1 | B | Ascend |
| 2 | A | Silence |
| 3 | A | Silence |
| 4 | B | Starting Over |
| 5 | A | Silence |
| 6 | B | Lost Utopia |
| 7 | B | Ascend again |
| 8 | A | Silence |

The fourth music break is Ascend again because the order has four B slots and three recordings. Note a mute, a skip, a volume change, or a complaint. Note whether talk got harder. At the end of the night, one choice: varied music, silence, or neither. And whether the return to the game felt welcome, neutral, or like the music stopped too soon.

Play the files from another machine. This path does not use the listener gate, so the gate's 250 ms return drop is not part of this screening. That drop is still in the gate. A week-long trial that plays cover audio through the device inherits it until the return path is changed.

## Reproduce

```text
.venv/bin/python experiments/groove_varied_001/prepare.py
```

The WAVs are gitignored. `experiments/groove_varied_001/receipt.json` holds the source and prepared hashes.

| File | sha256 |
| --- | --- |
| `experiments/groove_varied_001/prepare.py` | `d43cb6b9313b07ba50a22e49890a7371b7b7c29eae61ef9543a4ef4645241f5e` |
| `experiments/groove_varied_001/receipt.json` | `9ddb573a569bd48eafa42b336f9e062c379cee16a35c7c9c81aa9115e425056b` |
| `docs/ohush/research/GROOVE_VARIED_001/REPORT.md` | this file |
