# OHUSH_LIVE_V0_SPORTS

**MacBook MNF tonight:** follow [`docs/ohush/MACBOOK_MNF_TONIGHT.md`](../docs/ohush/MACBOOK_MNF_TONIGHT.md) (assets, KPIs, desk commands). Show key `mnf` loads Buck/Aikman enroll for the return floor.

Tonight's desk is a live game or a replay of one. Mark a replay in the setup. Buccaneers–Cowboys on 8 October is a recording. The next Prime Thursday game after 23 October 2026 is Panthers–Packers on 29 October. This session does not change Exp001–005, and its logs stay out of the replication set.

The optical capture is recorded untouched, in 15-minute chunks. The same audio feeds the existing live helper. Only the Mac speakers change: the game, or Silence / Stadium / Rain. Commercial audio is still recorded and still analyzed.

Turn the television speakers down. Leave the optical output running. Listen on this Mac. Do not mute the Prime tab. Muting Prime can silence the capture.

## Before 8:15

1. Prime playing on the TV, optical cable into the USB capture box, headphones or speakers plugged into this Mac.
2. Preflight:

```bash
.venv/bin/python -m ohush_live.sports_daemon --preflight --input-device USB --output-device "External Headphones"
```

Use the output name this Mac actually has. For four seconds you should hear the television through the Mac. For the next four you should hear nothing, while the printed input level stays up. If that level collapses, the mute reached the source and tonight's gate will not work until the optical path stays live.

3. Prefer the split desk so UI hot-reload cannot kill listening:

```bash
./scripts/desk engine    # terminal 1 — leave this alone during the game
./scripts/desk ui        # terminal 2 — Next on :3010, hot-reloads freely
# or one shot: ./scripts/desk up
```

`OHUSH_ENGINE=external` means the monitor only talks to `:8770`; it will not spawn or kill the engine. Threshold / bed / Python changes need `./scripts/desk restart-engine` (session auto-resumes if you never clicked Stop). Plain `npm run dev` still auto-starts the engine for quick checks.

4. Open http://127.0.0.1:3010/. Tell it what you are watching, pick the TV optical input and your headphones, then press Start. Hotkeys still work in the engine terminal: F8 mute, F9 play, F10 auto, S sound, 1-5 pleasant, y/n every break.

Replacement beds are RMS-matched to each other, then gain-followed to the recent program level so cover audio sits near the TV loudness instead of dropping to a quiet bed. Default cover is hush (light shush). Soft options include pad, ocean, stream, birds, breeze, night, chimes, piano, harp, and meadow; the older crowd/rain/fire/noise set stays available. Sources are listed in `ohush_live/beds/SOURCES.txt`.

Automatic cover uses the speaker and the audio together. A missing speaker keeps the show on. Audio-only cover is not the default. Manual Show only holds auto-mute when leaving a covered break; pressing Show while already on program does not block the next ad, and pressing it during a cover does not let that same break cover again until the departure goes quiet. Live audio warm-up is the worker's own reference, 15 seconds in code. If return looks possible but not strong, you get a short cue and the replacement keeps playing until F9. F9 returns immediately. F10 off means the helper only watches. Missed ad and Muted my show write a report. They are not labels. Left the game and Show is back stamp this recording's clock when the broadcast leaves and when it returns. They do not change the speakers, and they do not become gold. If this program stops, turn the television speakers up.

The first launch can download the speaker model into `ohush_live/cache`. Closed chunks upload on their own to `gs://hushdev-748439071367-research/live/`. The open chunk is not uploaded. If that uploader stops, recording continues.
