# OHUSH_LIVE_V0_SPORTS

Tonight's Buccaneers–Cowboys game on Prime. This is a product session. It does not change Exp001–005, and its logs stay out of the replication set.

The optical capture is recorded untouched, in 15-minute chunks. The same audio feeds the existing live helper. Only the Mac speakers change: the game, or Silence / Stadium / Rain. Commercial audio is still recorded and still analyzed.

Turn the television speakers down. Leave the optical output running. Listen on this Mac. Do not mute the Prime tab. Muting Prime can silence the capture.

## Before 8:15

1. Prime playing on the TV, optical cable into the USB capture box, headphones or speakers plugged into this Mac.
2. Preflight:

```bash
.venv/bin/python -m ohush_live.sports_daemon --preflight --input-device USB --output-device "External Headphones"
```

Use the output name this Mac actually has. For four seconds you should hear the television through the Mac. For the next four you should hear nothing, while the printed input level stays up. If that level collapses, the mute reached the source and tonight's gate will not work until the optical path stays live.

3. Open the app at http://127.0.0.1:3010/ (`npm run dev` in apps/monitor if needed). Tell it what you are watching, pick the TV optical input and your headphones, then press Start watching. The page starts listening for you. Hotkeys still work in the terminal if you launched the listener yourself: F8 mute, F9 play, F10 auto, S sound, 1-5 pleasant, y/n every break.

The beds stay quiet, so they sit under the picture instead of replacing the commercial with another show. Stadium starts on a diffuse crowd loop, not a cheer or a chant. Rain and fireplace are longer field recordings. Pink, brown, and silence are generated. Sources are listed in `ohush_live/beds/SOURCES.txt`.

Automatic mute still needs the speaker vote and the audio vote to agree. A manual play stays on through the current break. If return looks possible but not strong, you get a short cue and the replacement keeps playing until F9. F10 off means the helper only watches.

The first launch can download the speaker model into `ohush_live/cache`. Closed chunks upload on their own to `gs://hushdev-748439071367-research/live/`. The open chunk is not uploaded. If that uploader stops, recording continues.
