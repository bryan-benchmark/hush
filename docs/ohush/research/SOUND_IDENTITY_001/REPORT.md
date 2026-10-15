# Sound identity 001 — 15 October 2026

No live auto-output was enabled. The listener gate, the detector, and the vibe library were not changed. Nobody has rated these files.

The listening priority in this note is superseded by `SOUND_DIRECTION_002`. These files stay the silence, atmosphere, and single-groove cells of that comparison. They are not the proposed default.

The design goal is a cover that is pleasant at low attention for the length of a pod, with silence kept as a real choice. These files are the first comparison set for that goal. They are not a selected soundtrack.

## What the gate does today

Cover audio is already a bed, not the television. Three facts decide how a new sound would actually be heard.

The fade is 250 ms on the way in and the same 250 ms on the way out. `play_program` keeps the bed up until that ramp reaches zero. Program samples that arrive during the ramp are discarded down to the prime cushion, so the fade stands in for about a quarter-second of television. A faster return is a gate change. It was not made.

Loudness follows the recent program. While the television is playing, the gate stores that level and freezes it when the cover starts, so a loud commercial does not push the bed up mid-break. The bed is then gained to that level, clamped between RMS 0.05 and 0.28. It is not played 12–18 dB under the program. The sketches below are RMS 0.08, close to the live bed target of 0.10. Installed, they would be brought up to the television.

The playhead is not restarted by another cover. `play_replacement` fades in from the saved position. Choosing a different bed does restart it. A mute that stays muted across a whole pod is already one continuous bed. A detector that returns to the program between spots fades the bed out and back in.

The generated beds in `ohush_live/sounds.py` are 12-second loops. The return earcon is two tones, 880 Hz then 660 Hz, mixed when a return hint fires and the cover is still up. Neither was removed.

Wednesday Night and the other CC0 vibes stay the opt-in library. Silence is already a bed. This set does not replace them.

## The seven files

Sixty seconds, 48 kHz, stereo, PCM. Silence is digital silence. The other six share an RMS of 0.08. `low_pulses` counts 50 ms windows of energy below 80 Hz that rise above four times the median. Velvet Beat lands on 72 and Light Shuffle on 88, which is one pulse per beat for the minute. Warm Air, Slow Current, and Synthetic Arena do not.

| Sketch | RMS | Peak | Centroid | Low pulses |
| --- | --- | --- | --- | --- |
| Warm Air | 0.080 | 0.485 | 953 Hz | 1 |
| Velvet Beat, 72 BPM | 0.080 | 0.708 | 762 Hz | 72 |
| Light Shuffle, 88 BPM | 0.080 | 0.652 | 958 Hz | 88 |
| Slow Current | 0.080 | 0.498 | 1196 Hz | 0 |
| Sparse Mallets | 0.080 | 0.512 | 938 Hz | 4 |
| Synthetic Arena | 0.080 | 0.458 | 1064 Hz | 0 |
| Silence | 0 | 0 | — | 0 |

Warm Air is the quietest spectrum of the set only in the sense that it has no beat. Its centroid is still 953 Hz. Synthetic Arena is filtered noise with a slow swell. It is not a crowd, and it is the condition most likely to sound wrong next to a game. Sparse Mallets puts a few low notes on the warm bed. That is the repetition risk, not a proposed default.

A typical football pod in the closed set runs near two minutes. Each of these files would loop about twice inside one pod, and many times across a game. The 40 ms seam is only there to avoid a click. It is not an evolving score.

The cited listening studies were not re-read. Nothing in the table is evidence about attention, heart rate, or stress.

## What a later test has to clear

The first human pass is Warm Air, Velvet Beat, and Silence, in either order. The page at `experiments/sound_identity_001/listen.html` plays the files and can download a rating. A rating from that page is one impression of a one-minute file. It is not the result that matters.

The result that matters is which sound is still tolerated after a run of pods, against silence, without extra manual returns and without covering program audio. Thresholds for that come after a pilot. A cover test uses breaks a person has marked. Detector output is not the clock. Universal playback is still on PLAY.

No one has listened to these renders in this pass. The browser page was not exercised.

## Reproduce

```text
.venv/bin/python experiments/sound_identity_001/generate.py
.venv/bin/python -m http.server -d experiments/sound_identity_001 8765
```

The WAV files are gitignored. The receipt holds their hashes.

| File | sha256 |
| --- | --- |
| `experiments/sound_identity_001/generate.py` | `1de936285f4c88c0f058256c39ba9df331cb905e3d0c9a51311962fe05be1b1a` |
| `experiments/sound_identity_001/listen.html` | `a40f71f0eb9d8574d70b64afaaedb997c675dc76e4ee041a600491c5268cdb14` |
| `experiments/sound_identity_001/receipt.json` | `929de7ca7073ff9b8294943e56409a0c1c7e5f710ba04425f7b0695a451e5c74` |
| `docs/ohush/research/SOUND_IDENTITY_001/REPORT.md` | this file |
