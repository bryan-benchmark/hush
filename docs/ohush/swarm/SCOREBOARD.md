# Scoreboard

Champion: **no authorized mute.** Research baseline for later deltas: **Universal v1** (`docs/ohush/research/UNIVERSAL_V1/`). No row below is a deployed policy. Earlier scores are not replaced.

Universal and Enhanced do not share an accuracy number.

User-visible seconds are from `docs/ohush/research/ACCURACY_NORTH_STAR_001/` unless the row names another report. Football program time is 18.73 h. Football ad seconds are 17,648.4.

| ID | Date | System | Claim | Result | User-visible note |
| --- | --- | --- | --- | --- | --- |
| champion | 2026-10-14 | none | No mute | Current research champion | Nothing is hidden and every commercial is heard |
| DSP-OR | frozen | Universal | Continuous DSP episodes as a candidate stream | Football ~215 episodes/h, RedZone ~474/h | If those episodes were mutes: 5,862 s of football program and 1,369 s of RedZone hidden; 3,993 program incidents |
| DSP-ceiling-3s | frozen | Universal | Mute at the first DSP hit within 3 s, unmute at the gold end | 86/136 pods, 50 pods missed | 6,479.6 ad seconds still heard, of which 6,406.8 s are the missed pods |
| DSP-ceiling-30s | frozen | Universal | Same ceiling, 30 s window | 131/136 pods, 5 missed | 1,116.9 ad seconds heard |
| DSP-delay-only | frozen | Universal | Every pod caught at the 1.12 s median delay | Accounting, not a detector | 152.3 ad seconds. About 15 s per three-hour game, against a 1.08 s north-star budget |
| CNN14-distance | frozen | Universal | Acoustic distance as the mute gate | Retired | Threshold fit on ESPN did not transfer. Embeddings may be reused. The gate may not |
| audfprint-10 | frozen | Universal | Spectral landmarks, chronological library, count 10 | Inconclusive | 13/41 eval DSP-missed starts within 5 s; about 2.08 false identifications per probed program hour |
| audfprint-200 | frozen | Universal | Published count 200 | Inconclusive | 0 eval openings within 5 s (0/121); 6/121 within 10 s; program false IDs 0 on the probed grid |
| micro-dip-40ms | frozen | Universal | 10–200 ms recoverable dip | Gate not met | 4/136 football starts within 1 s; 134 program episodes/h; RedZone 4/h |
| handoff-phrase | frozen | Universal | Strong sign-off phrase in a 20 s window | Not a policy | 12/133 starts, 0/135 program controls, 0/40 RedZone. Six of the twelve are one Monday game |
| break-timer-120 | frozen | Universal | Fixed 120/135 s unmute | Failed as an unmute | Pod lengths vary; median football pod 132.8 s, max 417.9 s |
| tv-timeout | not run | Enhanced | External television-timeout feed | Not measured | Documented by vendors. Not purchased. Not aligned to audio |
| universal-v1 | 2026-10-14 | Universal | Causal play/cover. Chronological fingerprint, count 200, applied after the 5 s query | Research baseline, not promoted | Football: 17,530.7 commercial seconds heard, 25.0 covered, 0 program seconds covered, 0 false-cover incidents. 2 of 136 pods touched, then released |
| universal-v1-count10 | 2026-10-14 | Universal | Same queries, count 10. Ablation, not the baseline | Not promoted | Football: 13,652.5 commercial seconds heard, 432.1 program seconds covered, 72 false-cover incidents, worst interruption 25.1 s. RedZone 10.0 s covered |
| universal-v2 | 2026-10-14 | Universal | Acoustic content state. Thresholds chosen on two earlier games. October games were not used to choose them | FAIL | Selected policy stays play. On scorable football audio it hears 17,555.7 commercial seconds and covers 0. No calibration grid point stayed within 10 program seconds |
| universal-v3-embeddings | 2026-10-14 | Universal | CNN14 penultimate embeddings. Prototype difference. Thresholds on the same two earlier games | FAIL | Points inside the 10 s program cap cover 0 commercial seconds. October: 0 new commercial seconds, 25.0 s of v1 coverage lost, 0 program seconds. Not a mute |
| handoff-full-stream | 2026-10-14 | Universal | Strong phrases on the full sports stream. Spoken time and recognizer time kept apart | Not a policy | 12 of 136 pods have the words in the 30 s before the start. The recognizer knew 3 of those before the start. Same phrases also occur in ads and on RedZone |
| universal-v4-sequence | 2026-10-14 | Universal | Separate departure and return heads. Multiscale features. Thresholds on the two earlier games | FAIL | No feature set covered any commercial audio inside 10 program seconds on calibration. October: 0 new commercial seconds, 25.0 s of v1 coverage lost. Not a mute |
| speaker-enrollment | 2026-10-14 | Universal | Human-verified program speakers | Not measured | 0 verified enrollments. Booth files, cluster ids, and booth_present were not read |
| voice-identity-001 | 2026-10-15 | Broadcast identity | Named voices at the published ECAPA cosine of 0.25 | The two Hanson examples match each other, 15/15 held-out windows. The same line also matches other announcers, other RedZone booths, and a few ads | Not a mute. 14 people and 29 named spans are in the voice roster. The October 14 zero was the unread counter |
| voice-guard-001 | 2026-10-15 | Broadcast identity | Count 10 covers, forced back to play when a named voice matches at 0.25 | 27.5 of 432.1 false program seconds given back; 88.9 of 3,903.2 commercial seconds also given back | Not a live rule. 273.0 of the false program seconds have no speaker embeddings |
| pod-removal-001 | 2026-10-15 | Universal | Count 10 with the five highest-damage reference pods removed and the matcher rerun | 94.8 program seconds and 15 incidents cleared; 265.2 commercial seconds lost | Exploratory. Second-best pods replace much of the attributed damage. Not a mute |
| ecapa-backfill-001 | 2026-10-15 | Broadcast identity | Same ECAPA pipeline and cosine 0.25 on the five October recordings, then the frozen voice guard | 104.8 of 273.0 previously unscored program seconds given back; 375.7 commercial seconds also given back | Earlier enrollments only. Those tapes have no named labels. Not a mute |
| combined-candidate-001 | 2026-10-15 | Universal | Count 10 with the top five reference pods removed and the voice guard applied | 197.3 program seconds cleared and 29 incidents cleared; 707.5 commercial seconds lost | The two changes mostly miss each other, so the commercial loss stacks. Not a mute |
| sprint-90-10-001 | 2026-10-15 | Universal | Top-one, top-five, and top-ten removal, the October voice guard, and the saved match offsets, compared on one ledger | No candidate keeps the commercial coverage and clears most of the 72 incidents. Continuation was not opened | Next prospective test is the two-second fingerprint lead on a recording that was not in this ledger |
| fingerprint-warm-context-002 | 2026-10-15 | Universal | Cold and warm fingerprint reads, query side and reference side, same windows and the same two counts | Warm query against the cold reference: 60.0 football program seconds recovered, 5.0 more commercial seconds covered, incidents 72 to 59. RedZone 10.0 to 0. Count 200 unchanged | Research candidate. Not installed. The 25.1 s interruption remains. Warming the reference leaves 11 of the 13 afternoon matches at or above 10 |

## Enhanced

| ID | Date | Status | Accuracy |
| --- | --- | --- | --- |
| enhanced-v1 | 2026-10-14 | Not measured. No feed, schedule, or device metadata was authorized or aligned | none |
| cue-optical-001 | 2026-10-15 | Opened. Google DAI playlist cues exist for one session. No optical recording was paired with that session | none |

## How to read the champion

Comparisons use scorable audio. Football gross commercials are 17,648.4 s. Read failures remove 92.7 s of that, leaving 17,555.7 s. A no-cover policy hears those 17,555.7 s. Universal v1 hears 17,530.7 s and covers 25.0 s. Universal v2's selected policy hears the 17,555.7 s again. Universal v3 embeddings do the same: 0 new commercial seconds, and the 25.0 s v1 had covered are lost. Universal v4's sequence rule does the same, because no calibration point covered any commercial audio inside 10 program seconds. That failure is accepted. The next measurement is a listen for departure and return cues, not another action policy. The published 67,428 program seconds is 18.73×3600. The DSP integer program total is 67,446 s, and the scorable program total is 67,560.4 s. None of the rows is a shipped mute.
