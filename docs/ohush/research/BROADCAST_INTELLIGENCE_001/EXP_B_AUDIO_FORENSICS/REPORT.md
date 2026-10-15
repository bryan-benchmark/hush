# EXP-B — Audio forensics

**Hypothesis.** A one-second change in level, spectrum, or stereo image at a closed commercial start exceeds the 95th percentile of the same change during program audio from other recordings, and a 3× spectral-flux splice does the same.

**Verdict: INCONCLUSIVE.**

Three jumps carry boundary information and are correlated with each other. They are not a mute rule. The splice rule marks nothing. RedZone still fires on flatness and centroid.

## Frozen rule

Compare the 1 second after the boundary with the 2 seconds before it. The feature is available 1 second after the boundary. The splice ratio is 3. Every other feature uses the 95th percentile of absolute change on program windows from the other recordings. That percentile was not refit after the table was read.

All 12 closed sessions are 48 kHz stereo PCM. 164 of 166 starts had a complete read. Program controls: every 45 seconds, outside a 20-second collar around each commercial, at most 40 per recording (480 windows).

## Separation

| Feature | Starts | In-game program windows | RedZone (`hush_20260913_150934`, 40 windows) |
| --- | --- | --- | --- |
| Flatness | 74 | 22/440 | 4/40 |
| RMS | 71 | 24/440 | 1/40 |
| Centroid | 62 | 19/440 | 5/40 |
| Crest | 40 | 24/440 | 2/40 |
| Stereo correlation | 44 | 20/440 | 4/40 |
| Side ratio | 31 | 21/440 | 5/40 |
| High-band ratio | 31 | 23/440 | 2/40 |

The 440 in-game windows are the controls whose recording contained commercials. RedZone has no commercials, so its 40 windows are the remaining controls and were scored against everyone else.

Overlap of the top three: flatness∩RMS = 54. Flatness only = 12. RMS only = 15. Centroid only = 12. Any of the three = 103. The other 61 starts are below all three bars.

Flux ratio at starts: n=164, median 0.972, 90th percentile 1.293. Program: n=473, median 0.883, 90th percentile 1.043. The predeclared ratio of 3 fired 0 times on starts and 0 times on program windows.

## Incremental value on one published CNN14 table

Sept 9 NBC, joined to `AUDIO_SIGNAL_REPLICATION_001/nbc_breaks.csv` by start time. 20 starts. Any of the three jumps: 12. Published CNN14 causal hit during the break: 11. Both: 5. DSP only: 7. CNN14 only: 6. Neither: 2.

DSP-only starts: `6.07` (CNN14 score not yet defined), `1000.416`, `1074.332`, `2066.723`, `3942.562`, `4474.953`, `8413.747`. The last six are rises without a causal CNN14 hit during the pod. This is one recording.

## Why the verdict is inconclusive

The enrichment is real, and the Sept 9 join shows starts the published CNN14 causal rule missed. A detector would still have to survive a per-second clock, a stated false-alarm budget, and RedZone. Centroid fires on 5 of 40 RedZone samples. Flatness fires on 4 of 40. Those rates are higher than the in-game sample. Alarms per program hour were not measured.

Stereo, crest, side, and high-band have lower start counts, and their overlap with the top three was not measured. They are not ranked as additional information.
