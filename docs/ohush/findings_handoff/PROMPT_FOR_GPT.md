# OHush findings handoff

Today is 15 October 2026. This zip is the local research record. GitHub commit `18c7179` on `bryan-benchmark/hush` is behind it. The enrollment report on that commit still says zero verified enrollments. That sentence is stale.

No mute is authorized. Playback stays play. Universal v1 is the research baseline: 25.0 football commercial seconds covered, 0 program seconds covered. Count 10 is an ablation, not a live rule: 3,903.2 commercial seconds covered, 432.1 program seconds covered, 72 false-mute incidents, longest interruption 25.1 seconds. RedZone on this tape has 10.0 false program seconds and no gold commercials.

Universal and Enhanced do not share an accuracy number. October recordings have already been inspected and are not a blind test. Holdouts `hush_20260917_205513` and `hush_20260920_200635` stay sealed.

## Read in this order

1. `docs/ohush/swarm/SCOREBOARD.md`
2. `docs/ohush/research/FINGERPRINT_CAUSAL_STREAM_001/REPORT.md`, `NEXT_DECISION.md`, `results.json`, `session_ledger.csv`, and `control_matches.csv`
3. `docs/ohush/research/REFERENCE_CONTENT_AUDIT_001/REPORT.md`, `NEXT_DECISION.md`, `matched_pairs.csv`, and `reference_content_review.jsonl`
4. `docs/ohush/research/FINGERPRINT_WARM_CONTEXT_002/REPORT.md`, `NEXT_DECISION.md`, and `results.json`
5. `docs/ohush/research/FINGERPRINT_BLOCK_001/REPORT.md` and `docs/ohush/research/BLOCK_START_CONTEXT_001/REPORT.md`
6. `docs/ohush/research/SPRINT_90_10_001/REPORT.md` and `summary.json` and `session_comparison.csv`
7. `docs/ohush/research/POD_REMOVAL_001/REPORT.md`
8. `docs/ohush/research/ECAPA_BACKFILL_001/REPORT.md`
9. `docs/ohush/research/COMBINED_CANDIDATE_001/REPORT.md`
10. `docs/ohush/research/ACCURACY_LADDER_001/NEXT_DECISION.md`
11. `docs/ohush/research/CUE_OPTICAL_001/REPORT.md` and `docs/ohush/research/SIGNAL_ACCESS_001/REPORT.md` for the Enhanced track only

The other `REPORT.md` files are the earlier closed measurements. Quote the file for every number.

## Where the accuracy work stopped

Removing the five reference pods the audit blamed clears 94.8 program seconds and gives back 265.1 commercial seconds. The matcher was rerun. Many queries land on a different earlier pod. The 216.2 seconds attributed to those pods do not come back with them.

The five October recordings now have the existing ECAPA pass. Cosine 0.25 was not moved. Those tapes have no named labels, so every second they give back is a voice from another recording. The guard clears 132.3 program seconds in total and gives back 464.6 commercial seconds. It also raises premature releases from 186 to 320. A 2-, 5-, or 10-second continuation of a count-10 cover was not tested.

The match offsets inside the top-five pods do not share one interval. No creative was cut from the library.

The 13 afternoon false matches are the fingerprint reader restarting every 90 seconds. Two seconds of audio already received, on the query only, drops all 13 under count 10. Warming the reference and leaving the query cold leaves 11 of the 13 at or above 10. The alignment near 9809.7 seconds is a 90-second boundary in the NBC reference. It is not what creates the match.

On the full ledger, a warm query against the published cold references recovers 60.0 football program seconds and covers 5.0 more commercial seconds. Incidents go from 72 to 59. RedZone's 10.0 program seconds go to zero. Hulu on October 7 goes from 61.5 program seconds to 26.5, with commercial coverage unchanged. Count 200 stays 25.0 commercial seconds and 0 program seconds. The 25.1-second interruption is still the NBC September 13 tape. Thursday and Sunday night get worse, and that is inside the 60.0. Warming both sides recovers 76.9 program seconds and gives up 3.0 commercial seconds. That extra movement is not required for the 65-second rescue.

This replay used the same recordings that exposed the defect. It is not a later capture. Shifting every decision by the measured two-second lookahead makes the ledger worse. Adding these seconds to the voice-guard seconds is not a result.

The matches at or above 200 were then paired with the audio they point at. At the frame time the correlation is about zero. After a shift of 38 to 53 milliseconds it is 0.995 to 0.998 on Thursday and 0.975 on Monday. Thursday's four windows are one DraftKings spot. Monday is a chili-lime chip spot. One hop, 23 milliseconds, does not recover the correlation. Channel swap and polarity reversal do not either.

The worst reference pod's strongest query is unrelated audio at 9809.92 seconds, correlation 0.017. Other queries on the high-damage pods are real creatives, correlations above 0.93. The 25.1-second interruption is the FanDuel promo, correlation 0.956, on a query the gold calls program. The pods were not deleted. Known-ad continuation was not opened. The listening clips are not in this zip.

The causal clock was then run, in `FINGERPRINT_CAUSAL_STREAM_001`. Carrying the resampler and the peak state makes the same audio produce the same hashes in 7-, 45-, 90-, and 180-second pieces: 556,154 hashes, no holes, on the afternoon tape. The backward peak pass was still changing interior hashes at 8 seconds of later audio, so the first gate fails. The ledger at that window is not the published reader shifted later. Football count 10 covers 5,557.6 program seconds and 959 incidents. Count 200 covers 2.6 program seconds, on ESPN. The Thursday match stays on the same pod at 289. The Monday match stays on the same pod and falls from 208 to 35. This read's football holes are 155.0 seconds, not the published 275.0, so do not treat its commercial total as a gain. The warm replay's 280.0 against 275.0 is the same kind of hole mismatch. No new recording was made. The 25.1-second interruption stays on the published reader.

CUE-OPTICAL-001 is opened and unscored. One Google DAI playlist shows a 30-second cue. Nothing played that session through a television.

## Do not

- Authorize a mute or change live playback from play.
- Retune count 10, count 200, or cosine 0.25.
- Treat the 14 October enrollment row as current. Fourteen people and 29 named spans are enrolled.
- Treat a cluster id, `.booth.json`, or `booth_present` as a person.
- Call a pod removal or a voice-guard giveback a prospective result. The pods and the errors were chosen on this ledger.
- Sum the fingerprint-lead seconds and the voice-guard seconds.
- Open the sealed holdouts or edit gold.
- Treat a watermark, a slate, or a metadata label as proof of what the television played.
- Invent a continuation-rule result. That experiment was not opened.
