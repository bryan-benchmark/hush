# Broadcast Intelligence 001 — Batch 1

Batch 1 measured three cheap signals on the closed 166-commercial dataset: repeated short audio signatures, one-second production jumps, and break duration. No threshold was searched after the tables were seen. No live muter was changed. Holdouts `hush_20260917_205513` and `hush_20260920_200635` stayed sealed.

| Artifact | sha256 |
| --- | --- |
| `experiments/broadcast_intelligence/batch1.py` | `020b03d2ed73cdc2a6b467073210211553a4dcacc50495f0fee960a413fc093e` |
| `docs/ohush/research/BROADCAST_INTELLIGENCE_001/batch1_results.json` | `d9c7b13b8fa341aa7aae0b1c38800015991b1278cb6150d1e4daf17912c7cff1` |
| `docs/ohush/research/BROADCAST_INTELLIGENCE_001/break_durations.png` | `699aed7494e6ea14bfc4ff6fc558fbb19c7e8dbf96c14e5b2e0ee0513898afb3` |

Every closed session used here is 48 kHz stereo PCM. Commercials and the game share that capture format. A sample-rate or codec change is not available as a feature.

## Verdict

| Experiment | Verdict | What the measurement supports |
| --- | --- | --- |
| EXP-A music signatures | FAIL | At cosine 0.90, a 24-band spectrum and an 8-frame chroma sequence match ordinary program audio about as often as they match commercial boundaries. |
| EXP-B audio forensics | INCONCLUSIVE | Flatness, RMS, and centroid jumps mark 103 of 164 starts and add starts the published Sept 9 CNN14 causal hit missed. A predeclared 3× flux splice marks nothing. RedZone still fires. |
| EXP-C break clock | FAIL as an unmute | Football pods sit near 2:13, and 2:00 / 2:15 are real clumps. A point timer is off by about 15 s and would both expose ads and cover the game. |

Batch 2 was not started.

## 1. Are recurring start/end musical signatures present?

These two representations did not isolate one.

The signature is the 2 seconds immediately before a closed boundary. Cosine 0.90 and a motif size of 3 were fixed before the run. On football boundaries the 24-band spectrum collapses to one motif per network (NBC 41/41, cable 44/44, and the same pattern on ESPN and both Prime catalog names). The median cosine among NBC start boundaries is 0.980. The median cosine from those same boundaries to program windows in the same recording is 0.949. Leave-one-recording-out then matches 41/41 NBC boundaries and 72/80 NBC program windows.

The chroma sequence, eight successive 12-bin pitch profiles, was the check that a melody could still differ where the average spectrum cannot. It does not. NBC start boundaries have median cosine 0.922 to each other and 0.932 to program windows in the same recording. Leave-one-recording-out matches 39/41 NBC boundaries and 79/80 program windows. Cable matches 40/44 boundaries and 139/160 program windows. The same collapse holds for the 2 seconds before commercial ends.

ESPN, Prime, and Prime Video each have one football recording in this closed set, so a cross-game motif claim was not tested for them.

This is a failure of these fingerprints at this similarity. It is not a proof that a network sting is absent. Spectral-landmark matching was not run.

## 2. Are mixing and spectral characteristics useful without CNN14?

Three one-second jumps are, at the predeclared bar. Several other production measures are weak here.

The causal probe compares the 1 second after a boundary with the 2 seconds before it. A start counts when the absolute change meets the 95th percentile of program windows from the other recordings. Program controls are one window every 45 seconds, at least 20 seconds from any commercial, capped at 40 per recording. 164 of 166 starts had a full window. 440 of those program windows were scored; the other 40 are the RedZone negative control, scored separately.

| Feature | Starts over the bar | Program windows over the same bar | RedZone windows over the bar |
| --- | --- | --- | --- |
| Spectral flatness | 74 / 164 | 22 / 440 (0.050) | 4 / 40 |
| Short-time RMS | 71 / 164 | 24 / 440 (0.055) | 1 / 40 |
| Spectral centroid | 62 / 164 | 19 / 440 (0.043) | 5 / 40 |
| Crest factor | 40 / 164 | 24 / 440 (0.055) | 2 / 40 |
| Stereo correlation | 44 / 164 | 20 / 440 (0.046) | 4 / 40 |
| Side energy ratio | 31 / 164 | 21 / 440 (0.048) | 5 / 40 |
| High-band energy ratio | 31 / 164 | 23 / 440 (0.052) | 2 / 40 |
| Spectral flux, ratio ≥ 3 | 0 / 164 | 0 / 480 | — |

Flatness, RMS, and centroid overlap. 54 starts trip both flatness and RMS. The starts that only one of the three catches: flatness 12, RMS 15, centroid 12. Any of the three marks 103 / 164 starts. The other 61 starts are invisible to all three.

The 3× splice rule sits far above the data. The post/base flux ratio at starts has median 0.972 and 90th percentile 1.293. Program windows have median 0.883 and 90th percentile 1.043. A ratio of 3 was the predeclared rule, and it fired on nothing. That threshold was not lowered after seeing this.

On the published Sept 9 NBC CNN14 table (`AUDIO_SIGNAL_REPLICATION_001/nbc_breaks.csv`), joined by start time:

| | Count of 20 starts |
| --- | --- |
| Any of flatness, RMS, centroid | 12 |
| Published CNN14 causal hit during the break | 11 |
| Both | 5 |
| DSP only | 7 |
| CNN14 only | 6 |
| Neither | 2 |

Six of the seven DSP-only starts are breaks where the CNN14 median rose and the published causal exceedance never fired during the pod (`1000.416`, `1074.332`, `2066.723`, `3942.562`, `4474.953`, `8413.747`). The seventh, `6.07`, is the break whose CNN14 score does not exist yet because scores begin at 80 seconds; centroid still fired. This join is one recording. It is the only incremental comparison against CNN14 in this batch.

## 3. Are Prime and NBC break durations predictably different?

They lean different ways. Neither lean is a majority, and neither is a safe return time.

Football pods (catalog `content_type=sports`): n=136, median 132.8 s, 10th percentile 48.7 s, 90th percentile 181.9 s. 31 are within 7.5 s of 120. 40 are within 7.5 s of 135. 71 are within 7.5 s of one of those two. The chart is `break_durations.png`.

| Catalog network | Football pods | Median | Within 7.5 s of 120 | Within 7.5 s of 135 |
| --- | --- | --- | --- | --- |
| NBC | 41 | 136.4 s | 4 | 17 |
| Prime | 13 | 122.3 s | 5 | 1 |
| Prime Video | 23 | 121.6 s | 9 | 2 |
| Cable / antenna | 44 | 129.2 s | 9 | 14 |
| ESPN | 15 | 126.0 s | 4 | 6 |

Prime and Prime Video are separate catalog strings. Together they are 36 football pods, 14 near 120 seconds and 3 near 135. NBC is 17/41 near 135 and 4/41 near 120. A network-conditional timer was not a predeclared rule, so its error was not scored after the table was seen.

## 4. Which signatures are early enough to change a mute?

The one-second production probe is available 1 second after the boundary, by construction. That is the availability time of the feature, not a latency measured by scanning every second.

The music windows were placed with the closed label on the 2 seconds before the boundary. A match there is audio that has already played by the labeled IN. It is not evidence of a detector that finds the boundary without the label. Those fingerprints also match program audio, so they are not an early mute cue in this test.

The break clock applies only after a mute is already on. It does not detect the start.

## 5. How many boundaries do the top three cheap signals recognize uniquely?

Among the three jumps, unique starts are the ones the other two miss:

| Signal | Starts | Unique among the three |
| --- | --- | --- |
| RMS change | 71 | 15 |
| Spectral flatness change | 74 | 12 |
| Spectral centroid change | 62 | 12 |
| Any of the three | 103 | — |

Against the published Sept 9 CNN14 causal hit, the union adds 7 starts and misses 6 that CNN14 hit. Pooled incremental coverage against CNN14 on the other 11 recordings was not measured. Embeddings were not recomputed.

The clock recognizes no start. If a mute is already on, 40 of 136 football pods end within 7.5 s of 135, and 31 end within 7.5 s of 120.

## 6. How many false alarms during programming and RedZone?

On the 45-second program sample inside recordings that contain commercials: flatness 22/440, RMS 24/440, centroid 19/440.

On 40 RedZone windows (`hush_20260913_150934`, coverage 0–7200 s, zero commercials), scored against the 95th percentile of the other recordings' program windows: RMS 1/40, flatness 4/40, centroid 5/40. Centroid and flatness are harsher on RedZone than on the in-game sample. An alarms-per-hour figure was not computed. These are sampled windows, not a probe run every second.

The music rule's leave-one-recording false matches are 72/80 NBC program windows and 135/160 cable program windows for the average spectrum before starts, and 79/80 and 139/160 for chroma. That is the failure mode.

## 7. Which failures remain beyond inexpensive DSP?

- 61 of 164 commercial starts do not cross the flatness, RMS, or centroid bar.
- On Sept 9, 6 starts are CNN14 causal hits that none of those three jumps catch, and 2 starts are caught by neither.
- Return is unsolved. A fixed 135 s unmute across 136 football pods would still be inside the ads for 1967.5 seconds and would stay muted into the game for 2679.1 seconds. Median absolute error is 14.6 s. A fixed 120 s unmute exposes 3138.8 ad-seconds and covers 1810.4 program-seconds. Median absolute error is 17.5 s.
- A within-game running median, using only earlier pods in that recording, was predicted for 131 pods. Median absolute error is 16.2 s. Early ads 2387.1 s. Late program 2391.5 s. The online clock did not tighten the point prediction relative to a fixed 135 s timer.
- RedZone still produces flatness and centroid jumps. The short pods (10th percentile 48.7 s) are why a two-minute unmute cuts into ads.
- Speaker identity, repeated-ad fingerprints, and a shorter CNN14 window were not measured in this batch.

## 8. Does this justify a small neural model running all the time?

No. The useful new information in this batch is three correlated one-second jumps plus a duration distribution. The jumps already mark 103 starts at about a 5% rate on sampled in-game program audio, and on one NBC game they cover starts the published 10-second CNN14 causal rule missed. What they leave behind is a miss set, a RedZone false-jump problem, and a return clock that is too wide to act. A continuous model is not the next measurement those residuals ask for.

## 9. Next smallest falsifiable experiment

Score flatness, RMS, and centroid every second with the thresholds already published in `batch1_results.json` (the other-recordings program 95th percentile). Do not choose a new threshold. Count, per recording:

- commercial starts whose probe fires, and the delay from the closed IN
- alarms on program audio, as a count per program hour
- alarms on RedZone

That converts the 45-second sample into a causal clock. If that probe still misses a large set of starts at an acceptable RedZone rate, the following experiment is spectral-landmark fingerprinting on the same 2-second boundary windows. The average spectrum and the coarse chroma sequence were insensitive, so that test is still open. It was not run here.

## Rank by unique information

Standalone accuracy is not the rank. Uniqueness is.

1. RMS jump — 15 starts neither flatness nor centroid catch. Lowest RedZone rate of the three (1/40).
2. Flatness jump — 12 starts the other two miss. RedZone 4/40.
3. Centroid jump — 12 starts the other two miss. RedZone 5/40. On Sept 9 the union of these three adds 7 starts the published CNN14 causal hit did not record.
4. Crest factor — 40 starts at the same program rate as RMS. Overlap with the top three was not measured.
5. Stereo correlation — 44 starts. Unique overlap was not measured.
6. Side ratio and high-band ratio — 31 starts each. Unique overlap was not measured.
7. Break-duration distribution — no start coverage. It is the only measured return prior. As a point unmute it is off by about 15 seconds.
8. 24-band spectrum fingerprint — matches program windows along with boundaries.
9. 8-frame chroma sequence — program cosine is as high as boundary cosine.
10. Flux ratio of 3 — zero starts and zero program windows.

## What this batch does not authorize

No automated cover or uncover. No new gold boundary. No live-engine retune. No booth edit. No fine-tune. No GPU. Batch 2 (announcers, ad fingerprints, short-window CNN14) stays unstarted.
