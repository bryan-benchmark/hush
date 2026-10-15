# OHush Vibe starter library (VIBE_STARTER_001)

Isolated **playback** experiment. Default Vibe is **Wednesday Night**.

Does **not** change commercial detection, thresholds, Exp001–005, or LIVE_RECOVERY_001.

## Enable (opt-in only)

```bash
OHUSH_VIBES_EXPERIMENT=1 ./scripts/desk restart-engine
```

Without the flag, the desk keeps the existing neon/soft beds.

## Prepare audio

```bash
.venv/bin/python -m ohush_live.vibes.prepare
.venv/bin/python -m ohush_live.vibes.preview
```

Sources: `ohush_live/vibes/src/` (gitignored)  
Processed: `ohush_live/vibes/processed/` (gitignored)  
Manifest + licenses: `ohush_live/vibes/manifest.json`, `receipts/`

## Vibes

| Vibe | Default track | Alts |
|------|---------------|------|
| Wednesday Night | Chill Lofi Inspired (qubodup) | Lofi Again, A Cup of Tea |
| Friends Over | Funked Up (Joth) | Funky Disco, Empty Stretch |
| Cocktail Lounge | Coffee House Bump (OatCog) | Bossa Nova |
| Rainy Night | Soft Rain Loop (_lynks) | — |
| Stadium | Sports Crowd (FlatHill, calm crop) | — |
| Silence | baseline | — |

Freesound items used HQ previews where authenticated original download was blocked; see download receipt.
