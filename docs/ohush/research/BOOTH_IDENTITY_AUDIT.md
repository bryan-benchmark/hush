# Booth identity listening materials

Nothing here deletes or replaces `.booth.json`.

## Two different id lists

The frozen session file `inputs/session_2026-10-08-tnf/.booth.json` trusts `c0001`, `c0002`, `c0015`, `c0017`.

`run29` readings carry `booth_ids` of `c0001`, `c0002`, `c0004`, `c0005`, and later swap `c0005` for `c0003`. `c0015` and `c0017` are in the file and almost absent from that run's trusted list. `c0001` is the dominant speech cluster in `run29` (232 speech rows). `c0017` has one.

So "the four stored ids" and "the ids the running daemon thought were the booth" are not the same set. A listen has to say which set, from which run.

## Excerpts

Cut from `ohush_live/sessions/2026-10-08-tnf/audio_0044.wav`, 10 seconds starting one second before the track time. That file is the unique duration candidate for frozen `run29` (WAV 780.16 s, track `t_end` 780.03 s, delta 0.13 s). This is not a sample-locked join. Hear them as candidates. Manifest: `booth_excerpts/manifest.json`.

| File | Track t | Why it was cut |
|------|--------:|----------------|
| `booth_excerpts/run29_c0001.wav` | 24.0 | Highest similarity for `c0001` in the run (0.97) |
| `booth_excerpts/run29_c0002.wav` | 762.0 | Highest similarity for `c0002` (0.70) |
| `booth_excerpts/run29_c0015.wav` | 277.0 | Similarity 1.0. This id is in `.booth.json` and not in that row's `booth_ids` |
| `booth_excerpts/run29_c0017.wav` | 375.0 | The only `c0017` speech row in the run (0.90) |
| `booth_excerpts/run29_c0013_t221.wav` | 221.0 | The false flag: `booth_present`, similarity 0.15, cluster `c0013` |
| `booth_excerpts/run29_c0016_t285.wav` | 285.0 | Similarity 0.87 on `c0016`, not a trusted id |
| `booth_excerpts/run29_c0010_t621.wav` | 621.0 | Similarity 0.71 during the one-second uncover |

`run21` holds more of `c0001` and `c0002` (268 and 314 speech rows) and has no unique WAV. Those voices are not in this packet.

## What a listen can decide

- If `c0001` at 24 s is an announcer, the dominant cluster is at least sometimes the booth.
- If `c0013` at 221 s is an ad read, the historic flag promoted a non-booth voice, which the similarity contract now refuses.
- If `c0016` at 285 s is an announcer, high prototype similarity is landing on a new cluster id. That is the "ids do not survive restarts" risk, and it is still allowed to uncover once it holds 2.5 s after a human cover.
- If `c0016` is an ad narrator, the prototypes in `.booth.json` are contaminated, and the similarity contract will not save the next game.

No id was removed.
