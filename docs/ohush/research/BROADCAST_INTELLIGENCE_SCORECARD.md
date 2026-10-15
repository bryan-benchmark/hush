# Broadcast intelligence scorecard

Blank cells were not measured. Do not read a blank as zero.

Batch 1 only. Detection delay for EXP-B is the probe's availability time (the feature uses the 1 second after the boundary), not a latency from a per-second scan. False alarms per program hour were not computed: program controls are a 45-second sample, capped at 40 per recording.

| experiment_id | signal | commercial_starts_supported | commercial_ends_supported | median_detection_delay_s | p95_detection_delay_s | false_alarms_per_program_hour | premature_returns | incremental_event_coverage | incremental_program_loss | incremental_ad_seconds_saved | cpu_cost | memory_cost | model_size | deployment_dependencies | scientific_verdict | confidence_limitations |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EXP-B | RMS jump | 71/164 | | 1 | 1 | | | 15 starts missed by flatness and centroid | | | | | none | numpy, scipy, soundfile | INCONCLUSIVE | In-game false windows 24/440. RedZone 1/40. Not a per-second alarm rate. |
| EXP-B | Flatness jump | 74/164 | | 1 | 1 | | | 12 starts missed by RMS and centroid | | | | | none | numpy, scipy, soundfile | INCONCLUSIVE | In-game false windows 22/440. RedZone 4/40. |
| EXP-B | Centroid jump | 62/164 | | 1 | 1 | | | 12 starts missed by flatness and RMS. On Sept 9 the union of the three jumps adds 7 starts the published CNN14 causal hit did not record, and misses 6 that it did. | | | | | none | numpy, scipy, soundfile | INCONCLUSIVE | In-game false windows 19/440. RedZone 5/40. CNN14 join is one recording. |
| EXP-B | Crest factor | 40/164 | | 1 | 1 | | | | | | | | none | numpy, scipy, soundfile | INCONCLUSIVE | Unique overlap with the top three was not measured. Program windows 24/440. RedZone 2/40. |
| EXP-B | Stereo correlation | 44/164 | | 1 | 1 | | | | | | | | none | numpy, scipy, soundfile | INCONCLUSIVE | Unique overlap not measured. Program windows 20/440. RedZone 4/40. |
| EXP-B | Side ratio | 31/164 | | 1 | 1 | | | | | | | | none | numpy, scipy, soundfile | INCONCLUSIVE | Unique overlap not measured. Program windows 21/440. RedZone 5/40. |
| EXP-B | High-band ratio | 31/164 | | 1 | 1 | | | | | | | | none | numpy, scipy, soundfile | INCONCLUSIVE | Unique overlap not measured. Program windows 23/440. RedZone 2/40. |
| EXP-B | Flux ratio ≥ 3 | 0/164 | | | | | | 0 | | | | | none | numpy, scipy, soundfile | FAIL | Start flux-ratio 90th percentile is 1.293. The rule was not lowered. |
| EXP-A | 24-band spectrum, cosine 0.90 | | | | | | | | | | | | none | numpy | FAIL | NBC leave-one-recording: 41/41 boundaries and 72/80 program windows. |
| EXP-A | 8-frame chroma, cosine 0.90 | | | | | | | | | | | | none | numpy | FAIL | NBC: boundary median cosine 0.922, program median cosine 0.932. Landmark fingerprints were not run. |
| EXP-C | Fixed 120 s timer | 0 | | | | | | 0 starts. 31/136 football pods end within 7.5 s of 120. | 1810.4 program-seconds if used as an unmute on 136 football pods | | | | none | none | FAIL as an unmute | Assumes the mute is already on. Exposes 3138.8 ad-seconds. Median absolute error 17.5 s. |
| EXP-C | Fixed 135 s timer | 0 | | | | | | 0 starts. 40/136 football pods end within 7.5 s of 135. | 2679.1 program-seconds if used as an unmute on 136 football pods | | | | none | none | FAIL as an unmute | Exposes 1967.5 ad-seconds. Median absolute error 14.6 s. |
| EXP-C | Within-game running median | 0 | | | | | | 0 starts. Predicted on 131 football pods. | 2391.5 program-seconds | | | | none | none | FAIL as an unmute | Median absolute error 16.2 s. Does not beat the fixed 135 s timer. |

Source: `docs/ohush/research/BROADCAST_INTELLIGENCE_001/batch1_results.json` sha256 `d9c7b13b8fa341aa7aae0b1c38800015991b1278cb6150d1e4daf17912c7cff1`.
