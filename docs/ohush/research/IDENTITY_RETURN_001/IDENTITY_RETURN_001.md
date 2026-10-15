# IDENTITY-RETURN-001

Read-only. No mute. Oracle-start rows are a diagnostic. They are not system performance.

## Hypothesis

After a real commercial, the broadcast should again resemble the program that was on the air before the break: the same announcers, the same acoustic environment, and the same kind of speech. If that resemblance returns within a few seconds, and rarely appears during the commercial, a later experiment could try to detect the start and the return as one causal sequence. If it returns slowly, or only when the true start is already known, similarity to a frozen program reference is not a return switch.

Two questions stay separate. Departure asks whether the published audio-only freeze marks the commercial without eating the previous program. Return asks whether, once a break is underway, the original program becomes recognizable before too much of it has been lost. Return is the question that matters. A mute that does not come back off is not a product.

## What was held fixed

Nothing here was fit to these sessions.

| Rule | Source | Value |
| --- | --- | --- |
| Reference window | Exp003b | Window ends in (trigger − 210 s, trigger − 30 s] |
| Minimum reference | Exp003 | At least 60 s of that window, and none of it may be commercial audio |
| Acoustic and semantic return | Exp003b / Exp005 frozen cloud | Distance to the frozen centroid falls to that snapshot's own median self-distance |
| Announcer match | Exp002 | Cosine similarity at least 0.25 to a cluster that was already the dominant recurring speaker for 30 s in the reference |
| Causal departure | Exp003b cover | A published freeze in (gold start, gold start + 60 s] whose reference ends at or before the start and does not overlap a commercial |
| Recovery search | Exp005 | 120 s after the true return |
| Report windows | This assignment | 2, 5, 10, 15, and 30 s |

The decision rule was written in the scorer before the table was read back. A service can support a later causal experiment only on the causal path, and only if a clean departure exists for at least half of its eligible breaks and one signal has a false-return rate of at most 0.20, operational recovery by 10 s on a majority of its available breaks, and a median program false-mute of at most 10 s. The oracle path cannot meet that rule.

Microgap stays closed. The census published no operating threshold, so none was applied. The audfprint library is vendored and has no frozen index for these sessions, so no fingerprints were built. Holdouts stayed sealed. October sessions were not read. Embeddings were not recomputed. Live workers, gold files, and the existing experiment specs were not modified.

## Implementation

Sessions, in recording time:

| Service | Session | Coverage | Clock |
| --- | --- | --- | --- |
| ESPN Monday Night Football | `hush_20260914_212529` | 0–6899 s | Feature time is recording time |
| Prime NFL | `hush_20260924_220624` | 0–7600 s | Feature time is recording time |
| August Hulu | `hush_20260827_135935` | 300–7200 s | Feature time is recording time minus 300 s |

Gold commercials are certain mute marks inside those ranges. A return with less than 2 s of recorded audio after it is excluded. That removes the last ESPN break (ends at 6898.9 s) and the last Prime break (ends at the coverage boundary). Hulu has no such break. Eligible denominators are 14, 12, and 11.

The oracle path uses the gold start only to place the reference. The causal path places the same kind of reference at a published Exp003b freeze, and only audio that had already ended is allowed into it. Each signal is scored alone. "Earliest valid" in the tables is the soonest of those three that did not already fire during the commercial. It is a description of the timeline. It was not scored as a combined mute.

Missed program seconds, and program false-mute seconds, are the same quantity for a single signal: how long the program has been back before the signal agrees, stopping at the next commercial or at 120 s. If the signal already matched during the commercial, those seconds are 0 and the damage is the advertisement that would have been uncovered.

## Results

Frozen acoustic distance almost never looks like the program during the commercial. Across the oracle breaks where a clean reference existed, that happened once: Hulu break 10, which would have uncovered about 32 s of the ad. ESPN was 0 of 11 and Prime was 0 of 9. The same distance then takes a long time to come back. Median recovery, where it happens inside 120 s, is about 34 s on ESPN, 56 s on Prime, and 39 s on Hulu. Two ESPN breaks, three Prime breaks, and two Hulu breaks never reach the self-line inside 120 s.

Semantic distance is weaker. It false-returns on 2 of 11 ESPN breaks and 1 of 11 Hulu breaks, and on Hulu it reaches the pre-break line inside 120 s on only 3 of 11 breaks. None of the three services has an operational semantic return by 10 s.

Announcer reappearance is the fastest of the three, and it is not fast enough. The pre-break dominant voice comes back with a median latency of about 6 s on ESPN (10 breaks with a voice to test) and about 9 s on Hulu (11 breaks). Prime's dominant voice, one cluster through the game, has a median of about 33 s. Operational returns by 10 s are 5 of 10 on ESPN, 5 of 11 on Hulu, and 1 of 9 on Prime. ESPN's one false announcer match, break 7, is a single second during the commercial and would have uncovered about 107 s of that ad.

### How many breaks are back, oracle-start

Counts are operational: a during-ad match is not counted as a success. The denominator is the breaks with a usable reference.

| Service | Signal | Usable | By 2 s | By 5 s | By 10 s | By 15 s | By 30 s | Inside 120 s |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ESPN | Acoustic | 11 | 0 | 0 | 1 | 1 | 2 | 9 |
| ESPN | Semantic | 11 | 0 | 0 | 0 | 0 | 3 | 6 |
| ESPN | Announcer | 10 | 0 | 2 | 5 | 5 | 7 | 9 |
| Prime | Acoustic | 9 | 0 | 0 | 0 | 0 | 1 | 6 |
| Prime | Semantic | 9 | 0 | 0 | 0 | 0 | 1 | 5 |
| Prime | Announcer | 9 | 0 | 1 | 1 | 1 | 2 | 6 |
| Hulu | Acoustic | 11 | 0 | 0 | 0 | 1 | 3 | 8 |
| Hulu | Semantic | 11 | 0 | 0 | 0 | 0 | 0 | 3 |
| Hulu | Announcer | 11 | 0 | 2 | 5 | 6 | 6 | 9 |

No oracle cell is a majority by 10 s except ESPN announcers, and that cell is 5 of 10. The rule required a majority. Five of ten is not one. Median program false-mute on that ESPN announcer cell is about 6 s, which would have cleared the 10 s damage line, and the false-return rate is 1 of 10. The majority failure is enough. The causal path fails it more clearly.

### Causal departure

A clean published freeze inside the minute after the gold start, with at least one signal that could actually be scored, exists on 4 of 14 ESPN breaks, 2 of 12 Prime breaks, and 1 of 11 Hulu breaks. None of those rates reaches half. On the breaks that do have one, acoustic recovery is still tens of seconds (ESPN median about 35 s; the two Prime cases are about 85 s and no return inside 120 s; the one Hulu case is about 83 s). The ESPN announcer on those four causal breaks returns at 6 s, false-fires, 97 s, and 40 s. One clean causal announcer return inside 10 s, on one service, is not a system.

Most of the misses are absence, not a rejected reference. ESPN has no freeze in that minute on 8 of 14 eligible breaks, Prime on 9 of 12, Hulu on 10 of 11. One ESPN freeze overlaps the previous commercial. One Prime freeze would have built its reference out of the commercial it was trying to mark.

Separately, published freezes that are not sitting on a gold commercial were scored with the same self-line, as the program damage of treating those freezes as mutes. ESPN has two such freezes and both references contain commercial audio, so no mute seconds were counted. Prime has 7 scored freezes and about 276 s of program that would stay muted. Hulu has 10 scored freezes and about 758 s. That is the departure problem, measured with the trigger that already exists.

### Every break

Times are seconds after the true return, rounded. The CSV has the unrounded values. "None in 120 s" means the signal never reached its line in the published horizon, so the false-mute is the following program up to 120 s. "False" means it matched during the ad; the number is how much of the ad would have been uncovered, and the program false-mute for that signal is 0. "No clean ref" means the 180 s snapshot would have included an earlier commercial. Earliest-valid is not a combined rule.

#### ESPN

| Break | On recording | Acoustic | Semantic | Announcer | Earliest valid | Causal |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | 167–306 s | 47 s | 35 s | no announcer yet | semantic 35 s | no freeze in 60 s |
| 2 | 513–635 s | no clean ref | no clean ref | no clean ref | none | freeze at +9 s, but the 10 s windows still touch the previous ad |
| 3 | 1030–1079 s | none in 120 s | 35 s; false, 49 s of ad | 19 s | announcer 19 s | no freeze in 60 s |
| 4 | 1243–1308 s | no clean ref | no clean ref | no clean ref | none | no freeze in 60 s |
| 5 | 1539–1767 s | none in 120 s | none in 120 s | 6 s | announcer 6 s | no freeze in 60 s |
| 6 | 2072–2207 s | 59 s | 35 s | 6 s | announcer 6 s | freeze +6 s; acoustic 59 s; semantic 35 s; announcer 6 s |
| 7 | 2659–2780 s | 34 s | 49 s; false, 121 s of ad | 4 s; false, 107 s of ad | acoustic 34 s | freeze +5 s; same pattern, announcer false-fires |
| 8 | 3180–3290 s | 118 s | none in 120 s | 5 s | announcer 5 s | no freeze in 60 s |
| 9 | 3649–3785 s | 33 s | none in 120 s | 30 s | announcer 30 s | no freeze in 60 s |
| 10 | 4244–4379 s | 27 s | 21 s | 6 s | announcer 6 s | no freeze in 60 s |
| 11 | 4544–4675 s | no clean ref | no clean ref | no clean ref | none | freeze in the minute, reference overlaps the previous ad |
| 12 | 5020–5157 s | 10 s | 27 s | 5 s | announcer 5 s | no freeze in 60 s |
| 13 | 5665–5786 s | 36 s | 62 s | 97 s | acoustic 36 s | freeze +2 s; acoustic 36 s; semantic 62 s; announcer 97 s |
| 14 | 6345–6471 s | 31 s | 18 s | 40 s | semantic 18 s | freeze +0.4 s; acoustic 31 s; semantic 18 s; announcer 40 s |
| 15 | 6853–6899 s | excluded | excluded | excluded | — | no program audio after the return |

#### Prime

| Break | On recording | Acoustic | Semantic | Announcer | Earliest valid | Causal |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | 2–50 s | ref under 60 s | ref under 60 s | ref under 60 s | none | no freeze in 60 s |
| 2 | 234–357 s | no clean ref | no clean ref | no clean ref | none | no freeze in 60 s |
| 3 | 913–1034 s | 46 s | none in 120 s | 70 s | acoustic 46 s | no freeze in 60 s |
| 4 | 1490–1611 s | 42 s | 54 s | 5 s | announcer 5 s | no freeze in 60 s |
| 5 | 1743–1895 s | no clean ref | no clean ref | no clean ref | none | no freeze in 60 s |
| 6 | 2218–2338 s | 85 s | none in 120 s | 41 s | announcer 41 s | freeze +7 s; acoustic 85 s; semantic none; announcer 41 s |
| 7 | 2797–2918 s | 113 s | none in 120 s | 30 s | announcer 30 s | no freeze in 60 s |
| 8 | 3496–3633 s | 30 s | 39 s | 36 s | acoustic 30 s | no freeze in 60 s |
| 9 | 4337–4493 s | 66 s | 29 s | none in 120 s | semantic 29 s | no freeze in 60 s |
| 10 | 5355–5519 s | none in 120 s | 99 s | 26 s | announcer 26 s | freeze +2 s; acoustic none; semantic 99 s; announcer 26 s |
| 11 | 6029–6181 s | none in 120 s | 31 s | none in 120 s | semantic 31 s | no freeze in 60 s |
| 12 | 6854–7020 s | none in 120 s | none in 120 s | none in 120 s | none | a freeze falls in the minute, but its reference includes this ad |
| 13 | 7515–7600 s | excluded | excluded | excluded | — | no program audio after the return |

#### Hulu

Recording times. Feature time is 300 s earlier.

| Break | On recording | Acoustic | Semantic | Announcer | Earliest valid | Causal |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | 1112–1154 s | none in 120 s | none in 120 s | 31 s | announcer 31 s | no freeze in 60 s |
| 2 | 1449–1540 s | 29 s | none in 120 s | 54 s | acoustic 29 s | no freeze in 60 s |
| 3 | 2076–2166 s | 81 s | none in 120 s | 12 s | announcer 12 s | freeze +24 s; acoustic 83 s; semantic none; announcer 12 s |
| 4 | 2711–2802 s | none in 120 s | none in 120 s | 4 s | announcer 4 s | no freeze in 60 s |
| 5 | 3344–3435 s | 27 s | 90 s | none in 120 s | acoustic 27 s | no freeze in 60 s |
| 6 | 4116–4166 s | 84 s | 36 s | 5 s | announcer 5 s | no freeze in 60 s |
| 7 | 4422–4511 s | 100 s | none in 120 s | 67 s | announcer 67 s | no freeze in 60 s |
| 8 | 5006–5089 s | 39 s | none in 120 s; false, 82 s of ad | none in 120 s | acoustic 39 s | no freeze in 60 s |
| 9 | 5425–5516 s | 70 s | none in 120 s | 9 s | announcer 9 s | no freeze in 60 s |
| 10 | 6404–6495 s | 15 s; false, 32 s of ad | none in 120 s | 6 s | announcer 6 s | no freeze in 60 s |
| 11 | 7028–7080 s | 11 s | 37 s | 7 s | announcer 7 s | no freeze in 60 s |

## Decision

Program identity does return. On a clean oracle snapshot the commercial rarely imitates the pre-break acoustic cloud. That is not the same as recognizing the return in time.

No service meets the rule that was declared before scoring. Acoustic and semantic recovery are slow on ESPN, Prime, and Hulu. Announcer reappearance is faster on ESPN and on Hulu than on Prime, so this is not a sports-versus-scripted split, and even the faster cells miss a majority at 10 s. The causal path cannot host a return test on most breaks, because the published freeze does not land in the first minute with a reference made only of program audio.

This does not authorize a mute, a combined start/return sequence, or a new similarity threshold. The next measurement has to recognize known program audio, or align to a verified stretch of the program, and otherwise stay in playback. That work is not started here.

Artifacts: `per_break_results.csv`, `timeline.jsonl` (15,684 samples; each `available_at_feature` is the window end, never later), `coverage_summary.json`, `receipts.json`. Code is `experiments/measurement/identity_return_001.py`. Git HEAD at the run is `eedcb444c2546e06f6b3cea16dc2efb92b8d6506`.
