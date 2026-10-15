# VIBE_STARTER_001

**Goal:** Test whether real CC0 music Vibes make commercial breaks more enjoyable than stadium noise.  
**Default:** Wednesday Night  
**Detection:** unchanged  
**Live output:** not enabled unless `OHUSH_VIBES_EXPERIMENT=1` (requires explicit approval)

## Delivered

- 10 sourced recordings (8 OpenGameArt originals + 2 Freesound HQ previews)
- License/download receipts + SHA-256
- Loudness-normalized 48 kHz stereo processed beds
- QC notes (speechish / crest / stadium calm crop)
- Manifest, catalog, loader, offline preview
- Opt-in wiring via env flag
- Unit tests for switch / missing / loop / normalize / Cover-Show / volume / flag-off default

## Evaluation matrix (manual)

Rate each during the same kinds of breaks:

| Condition | Preference 1–5 | Annoying after repeats? | Prefer to ads? | Transition issues | Select again? |
|-----------|----------------|-------------------------|----------------|-------------------|---------------|
| Silence | | | | | |
| Wednesday Night | | | | | |
| Friends Over | | | | | |
| Cocktail Lounge | | | | | |
| Rainy Night | | | | | |
| Stadium | | | | | |

Priority: audition the three Wednesday Night tracks first.
