# EXP-A — Musical signatures

**Hypothesis.** A repeated 2-second spectrum, or a repeated short chroma sequence, occurs at football commercial boundaries and rarely during ordinary program audio.

**Verdict: FAIL.**

## Frozen rule

- Window: the 2 seconds immediately before the closed boundary.
- Spectrum: 24 log-frequency bands, 80 Hz–8 kHz, L2-normalized.
- Chroma: eight successive 12-bin pitch profiles, 80 Hz–5 kHz, concatenated and L2-normalized.
- Near-copy: cosine 0.90. Motif: at least 3 copies. Cross-game claims: leave-one-recording-out.
- Football only (`content_type=sports`). Program controls: the same 45-second sample used in EXP-B, at least 20 seconds from a commercial.

Code and numbers: `experiments/broadcast_intelligence/batch1.py`, `../batch1_results.json`.

## Result

Both representations form one giant motif per network. Boundary audio is about as similar to program audio as it is to other boundaries.

NBC, spectrum before starts: median cosine among 41 boundaries 0.9797; median cosine to same-recording program windows 0.9492. Leave-one-recording-out matches 41/41 boundaries and 72/80 program windows.

NBC, chroma before starts: median cosine among boundaries 0.9222; median cosine to program 0.9315. Leave-one-recording-out matches 39/41 boundaries and 79/80 program windows.

Cable / antenna, chroma before starts: 40/44 boundary matches and 139/160 program matches.

The same pattern holds for the 2 seconds before commercial ends. ESPN, Prime, and Prime Video have one football recording each, so leave-one-recording-out tested zero boundaries for those names.

## What failed

The cosine-0.90 rule accepts ordinary football audio. A network sting was not isolated. Landmark fingerprinting (audfprint or Chromaprint) was not run, so this does not close the sting hypothesis. It closes these two representations at this threshold.

## Next

Only after the continuous flatness/RMS/centroid clock in the Batch 1 report: spectral-landmark matching on these same windows, with the same program and RedZone controls, and the same cosine left unsearched until a separate predeclared similarity is frozen.
