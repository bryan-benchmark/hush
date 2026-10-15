# KNOWN_AD_FINGERPRINT_001

Spectral-landmark fingerprints were run on the closed gold, offline, with audfprint's analyzer. No mute rule was changed. Holdouts stayed closed. CNN14 was not refit.

| Artifact | sha256 |
| --- | --- |
| `experiments/broadcast_intelligence/known_ad_fingerprint.py` | `5cea937491107dfe77f93115d1f0482d0746ca7e8568845cbc73264b4784849f` |
| `docs/ohush/research/KNOWN_AD_FINGERPRINT_001/results.json` | `6db540a94038f5054283fbd74427ebb4109e828459b6e110feee1f0877724c97` |
| `docs/ohush/research/KNOWN_AD_FINGERPRINT_001/pod_queries.csv` | `1b0dbfe705b8353f32a49ef4b016f852b4abf8065da3bf9d684c8ae302209407` |
| `docs/ohush/research/KNOWN_AD_FINGERPRINT_001/opening_recall.png` | `a6aaf09089efcae71a1f9d25eb05c7f06a2ce4fbca646c9e5ff30dd6f2e50416` |
| `experiments/broadcast_intelligence/third_party/audfprint/audfprint_analyze.py` | `46a9401e04cd31b1ffff1ce327c0dc84d852d3fb557e8195940e895d4391f9e1` |
| `experiments/broadcast_intelligence/third_party/audfprint/searching_for_ads.md` | `8302ba1ec78b32cb596d828f78854327127e883f3c78eb00093cc8c3766186fa` |

audfprint commit `cb03ba99feafd41b8874307f0f4e808a6ce34362`.

Command:

```
MPLCONFIGDIR=/tmp/mpl PYTHONPATH=src:experiments/broadcast_intelligence/third_party/audfprint:. \
  .venv/bin/python experiments/broadcast_intelligence/known_ad_fingerprint.py
```

Wall time 496.9 seconds. Peak resident memory 889 MB. Fingerprint extraction 267.3 seconds for 110,947 seconds of audio. Query phase 226.2 seconds, including 22,229 independent stream probes.

## Verdict: INCONCLUSIVE

The count chosen on ESPN recovers commercial starts the DSP scan missed, and it also accepts program audio often enough to miss the false-identification budget. The published audfprint bar of 200 common landmarks keeps program and RedZone false identifications at zero in this probe, and it recognizes no evaluation opening in 5 seconds.

A match names earlier commercial-region audio. It does not name a creative, and the end of a match is not a program return.

## Frozen rules

Definitions were written in the script header before matches were read.

- 11,025 Hz mono, density 100 peaks per second, match window ±2 frames. Reference time-shifts stay at 1. The ad note also builds references at 4 shifts; that multiplier was not applied. A separate 50 ms shift is a robustness probe.
- Counts 5, 10, 20, 50, and 200 are all eligible. The operating count is the smallest one whose ESPN leave-one-recording program probes stay at or below 1 false identification per probed hour. If none does, the count stays at the published 200.
- A query of W seconds keeps a landmark only when both peaks sit inside those W seconds.
- Oracle library: every other recording's commercial pods, including future games. Upper bound under verified enrollment. Not a deployable enrollment method.
- Chronological library: earlier recordings only. The query recording's own pods are excluded. Within-session repeats are a third library: earlier finished pods in the same recording.
- Enrollment uses gold commercial intervals. That approval is an offline assumption, stated here, and is not an automatic enrollment system.
- Program probes are 5 seconds long, every 10 seconds, at least 20 seconds from a pod. The independent stream uses a 5-second query every 5 seconds, on the chronological library, including seconds where DSP is silent.
- PASS if the operating count, on the chronological library, stays at or below 1 program false identification per probed hour on evaluation football, recognizes at least one evaluation DSP-missed start within 5 seconds, and the 5-second opening match rate exceeds the RedZone probe hit fraction.
- FAIL if no predeclared count both stays within that false-identification budget on evaluation football and matches any evaluation opening within 10 seconds.
- Otherwise INCONCLUSIVE.

ESPN selected count 10. Its oracle program probes: count 5 gave 33 hits in 4,410 probed seconds (26.9 per hour); count 10 gave 1 hit (0.82 per hour); counts 20, 50, and 200 gave 0.

## Gate 0 — episode inventory

The seven descriptive rows in `CANDIDATE_VERIFICATION_001` sum to 8,622 because 49 episodes are counted twice. Those 49 are inside-pod episodes that also reach a gold OUT. The flag is not a separate pile.

Exclusive classes, summing to 8,573:

| Class | Episodes |
| --- | --- |
| Fresh start | 59 |
| Already running at a commercial IN | 59 |
| Fresh end | 41 |
| Inside a pod | 2,001 |
| Ordinary program | 5,466 |
| RedZone | 947 |

Football starts stay 49 fresh, 37 already running, 50 with no positive DSP second within 3 seconds. The fingerprint join reproduces that split: 49, 37, 50, plus 30 pods that are not football. ESPN holds 5, 1, and 9 of those three football groups. Evaluation football therefore holds 44, 36, and 41.

## What was hashed

Twelve closed ranges. 166 commercial pods, 20,030.5 seconds, 1,735,422 reference hashes. A pod is a container. A hit is shared commercial-region audio, which may be one advertisement, a bumper, a sponsor bed, or other recycled material. Individual spots are not labeled.

A pod's own 10-second opening, queried against an index that contains that pod, scored 634 on 631 hashes. The pipeline finds exact audio.

Read failures skipped 275 seconds. Some other blocks were identically zero and were hashed as silence. Thursday's known hole is larger than 275 seconds; silence was not filled in with invented samples.

Landmark counts in an opening, all 166 pods:

| Seconds heard | p10 hashes | median | p90 |
| --- | ---: | ---: | ---: |
| 1 | 0 | 19 | 85 |
| 2 | 3 | 137 | 232 |
| 3 | 90 | 233 | 357 |
| 5 | 279 | 428 | 579 |
| 10 | 647 | 850 | 1,071 |

Sixty-one of 166 openings have fewer than 5 landmarks in the first second. A 1-second query often cannot clear any predeclared count because the landmarks are not there. From 3 seconds onward, sparsity is no longer the usual reason for a miss.

## Repetition atlas

Cross-session, oracle library, 10-second openings:

| Count | Pods matched | Same broadcaster | Other broadcaster |
| --- | ---: | ---: | ---: |
| 10 | 77 / 166 | 19 | 58 |
| 200 | 9 / 166 | 1 | 8 |

Most loose matches cross broadcasters. At the published count, 9 openings still match some other recording's commercial audio, and 8 of those 9 cross broadcasters. That is compatible with a national spot. It is also compatible with shared production audio. The labels cannot decide.

Within one game, the within-session library, evaluation openings at 10 seconds: 15 / 121 score at least 10, and 0 / 121 score at least 200. The field `within_session_10s_at_operating` in `results.json` is 0 for a bookkeeping reason: it looked for a same-recording hit inside the chronological library, and that library excludes the query recording. The within-session rows in `pod_queries.csv` are the measurement.

A 10-second slice starting 30 seconds into each long pod, against the oracle library, has median score 6. Interior commercial audio matches other pods less often than the openings do. Openings are the repetitive part of this corpus, and even they are repetitive for a minority of pods once the count is strict.

Sept 9 NBC is the clean leakage example. Its chronological library contains only the August 27 Hulu pods. Chronological matches at count 10: 0 / 20 at 5 seconds and 0 / 20 at 10 seconds. Oracle matches, which may use later football games: 10 / 20 at both 5 and 10 seconds, and 0 / 20 at count 200. Future commercials create loose resemblance and, on this game, no published-bar identification.

## Oracle versus chronological

Evaluation football, 121 pods. A match must clear the count against another recording.

| Library | Count | 1 s | 2 s | 3 s | 5 s | 10 s | Program false IDs per probed hour | RedZone per probed hour |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Chronological | 10 | 1 | 18 | 24 | 33 | 40 | 2.08 (33 / 57,210 s) | 1.00 (2 / 7,170 s) |
| Chronological | 200 | 0 | 0 | 0 | 0 | 6 | 0 | 0 |
| Oracle | 10 | 3 | 27 | 39 | 56 | 63 | 3.40 (54 / 57,210 s) | 1.00 |
| Oracle | 200 | 0 | 0 | 0 | 0 | 7 | 0 | 0 |

The oracle adds matches, as expected when future games are allowed into the index. At count 200 the addition is one pod at 10 seconds (7 versus 6). At count 10 the addition is large, and the program false-identification rate is larger too.

Program probes are spaced every 10 seconds. The rate is false identifications per hour of that grid, not a continuous second-by-second mute rate. The independent 5-second stream, chronological, saved 91 program-region windows and 813 in-pod windows at count 10, out of 22,229 probes. Those 91 are additional evidence that program audio can resemble an earlier pod when the count is 10. Their hours are not separated in the saved stream tally; the probe-grid rate above is the false-identification figure used for the verdict.

First time an evaluation opening reaches the count, chronological library:

| Count | By 1 s | By 2 s | By 3 s | By 5 s | By 10 s | Never within 10 s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 10 | 1 | 18 | 24 | 33 | 40 | 81 |
| 20 | 0 | 9 | 18 | 27 | 33 | 88 |
| 200 | 0 | 0 | 0 | 0 | 6 | 115 |

Counts 20 and 50 were not given their own saved program-probe rates. Opening scores for those counts are in `pod_queries.csv`. At 5 seconds, chronological evaluation openings: 27 / 121 at count 20, and 14 / 121 at count 50. DSP-missed evaluation starts at 5 seconds: 11 / 41 at count 20, and 7 / 41 at count 50. The verdict uses count 10, because that is the count ESPN selected.

## Per game

Chronological library. Pods matched / pods in the game.

| Recording | Broadcaster | 5 s at count 10 | 10 s at count 10 | 10 s at count 200 |
| --- | --- | ---: | ---: | ---: |
| 2026-09-09 | NBC | 0 / 20 | 0 / 20 | 0 / 20 |
| 2026-09-13 | NBC | 8 / 21 | 9 / 21 | 1 / 21 |
| 2026-09-14 ESPN | ESPN | 7 / 15 | 8 / 15 | 1 / 15 |
| 2026-09-24 | Prime | 1 / 13 | 3 / 13 | 1 / 13 |
| 2026-10-08 | Prime Video | 5 / 23 | 6 / 23 | 2 / 23 |
| 2026-10-10 | Cable | 2 / 6 | 3 / 6 | 0 / 6 |
| 2026-10-11 afternoon | Cable | 4 / 8 | 5 / 8 | 0 / 8 |
| 2026-10-11 night | Cable | 4 / 6 | 4 / 6 | 1 / 6 |
| 2026-10-12 | Cable | 9 / 24 | 10 / 24 | 1 / 24 |
| 2026-08-27 Hulu, scripted | Hulu | — | 0 / 11 at count 10 | 0 / 11 |
| 2026-10-07 Hulu, scripted | Hulu | — | 3 / 19 at count 10 | 0 / 19 |

Among the 40 chronological evaluation matches at 10 seconds and count 10, 9 stay on the same broadcaster string and 31 cross to another. Thirteen of the 31 are cable openings matching Prime Video. At count 200 the six matches are: Prime Video to Prime (2), NBC to NBC (1), Prime to NBC (1), cable to Prime Video (1), cable to ESPN (1). Strict matches occur inside a broadcaster family and across families. They are too few to call the benefit network-specific, and too few to call it a general commercial detector.

The strongest causal opening is Prime Video on Oct 8 at 139.9 seconds, a DSP-missed start. At 10 seconds it scores 471 on 914 hashes against the Prime pod at 234.2 seconds on Sept 24. At 5 seconds the same pair scores 169, which clears count 10 and does not clear 200. A second strict cross-network example is cable on Oct 12 at 5,080.1 seconds, score 355 on 879 hashes, against an ESPN pod. Both are known commercial-region audio. Neither has a creative name in the gold.

## DSP overlap

Chronological library, evaluation football only.

| Population | 3 s, count 10 | 5 s, count 10 | 10 s, count 10 | 5 s, count 200 | 10 s, count 200 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Fresh DSP start | 8 / 44 | 11 / 44 | 12 / 44 | 0 / 44 | 2 / 44 |
| Already-running DSP alarm | 6 / 36 | 9 / 36 | 10 / 36 | 0 / 36 | 1 / 36 |
| No positive DSP second within 3 s | 10 / 41 | 13 / 41 | 18 / 41 | 0 / 41 | 3 / 41 |

The 50 football starts with no positive DSP second are 41 evaluation plus 9 ESPN. At count 10 and 5 seconds, chronological matches are 13 evaluation and 5 ESPN, 18 in all. At count 200 and 5 seconds, the number is 0. At count 200 and 10 seconds, evaluation contributes 3 and ESPN contributes 1.

Those 13 evaluation starts are a real second route: the stream was not gated on DSP, and the opening audio itself matched an earlier pod. At the operating count the same route also flags ordinary program. At the published count the missed-start route produces nothing inside 5 seconds.

Ongoing alarms are a new recognition event when they match, in the same sense as the fresh starts. They are not credited as DSP's earlier alarm.

## False matches

The strongest saved program probes are oracle probes at count 10 or above.

Prime Video program at 3,390, 3,400, and 3,410 seconds scores 137, 93, and 89 against one cable pod from Oct 11. The offset stays on the same alignment across those probes. That is repeated audio, heard in program, also present in a stored commercial interval. The reference recording is in the future relative to Oct 8, so the chronological library cannot make this identification. The score is also below 200, so the published bar would reject it.

Other high oracle program scores include NBC at 1,100 seconds scoring 108 against an ESPN pod, and NBC at 12,260 seconds scoring 48 against an earlier NBC pod. A program passage that happens to have been inside some commercial interval remains program. The matcher has no second test that would refuse that promotion.

RedZone at count 10 produces 2 probe hits in 7,170 seconds. At count 200 it produces 0. RedZone has no commercial pods of its own in this gold.

## Robustness

All 15 ESPN openings, 5 seconds, oracle library. Median score:

| Version | Median |
| --- | ---: |
| Original | 7 |
| Gain ×0.5 | 7 |
| tanh compression | 7 |
| 16 kHz round trip | 7 |
| Noise at 20 dB SNR | 6 |
| 50 ms drop of the start | 7 |

The clean median is already 7, under the operating count. Gain, compression, resampling, noise, and a small shift do not move it. The misses on ESPN openings are present in the original audio. Exact self-match remains the separate pipeline check at score 634. No codec that is absent from these captures was invented. These files are 48 kHz stereo PCM.

## Compute and license

On this Mac, CPU only:

- Extraction is about 415 times realtime, 2.4 milliseconds per second of audio.
- The query phase covering openings, program probes, and 22,229 stream probes took 226 seconds.
- The commercial index is about 5,198 hashes per minute of pod audio. The in-memory estimate at 8 bytes per hash is 14 MB for the 1.7 million reference hashes.
- Peak RSS of 889 MB is the research process holding landmarks for every second of every recording. A library of advertisement references does not have to hold the program track.
- A 30-second reference at this hash rate is about 2,600 hashes, about 21 KB. One hundred such references are about 2 MB, one thousand about 21 MB, ten thousand about 208 MB. Bucket lists get longer as the library grows. This corpus did not measure a 10,000-reference query.
- No separate ARM board was timed. No GPU was used.

audfprint is MIT, copyright 2014–2015 Dan Ellis, Columbia University, and Google. The license covers the matcher. It does not authorize selling or redistributing the captured broadcasts, even after they have been hashed.

## Why the verdict is inconclusive

Count 10 meets the ESPN false-identification budget (0.82 per probed hour) and, on evaluation football, recognizes 13 of 41 DSP-missed starts within 5 seconds. The 5-second opening rate, 33 / 121, is above the RedZone probe fraction, 2 / 717. The same count produces 2.08 program false identifications per probed hour on the evaluation games, above the budget of 1. PASS requires all of those conditions together.

Count 200 meets the false-identification budget with room (0 on the evaluation probes and on RedZone) and matches 6 evaluation openings within 10 seconds, so FAIL does not trigger. It matches none of them within 5 seconds, and none of the DSP-missed starts within 5 seconds.

## Answers

1. At count 10, 77 of 166 pods have a 10-second opening that resembles some other recording's commercial audio. At count 200, 9 of 166 do. Within a game, 15 of 121 evaluation openings resemble an earlier pod in that game at count 10, and none do at count 200.
2. Under the causal library, 40 of 121 evaluation openings have a count-10 match within 10 seconds, 33 within 5 seconds, and 1 within 1 second. At count 200, 6 of 121 have a match within 10 seconds and none sooner. Eighty-one of 121 never reach count 10 inside 10 seconds.
3. At the published count, no. Zero of 121 evaluation openings match within 5 seconds. At count 10, 33 of 121 match within 5 seconds and 24 within 3 seconds, alongside the program false identifications above.
4. At count 10, chronological: 2.08 per probed hour on evaluation program probes, and 1.00 per probed hour on RedZone. At count 200, both are 0 in this probe.
5. Thirteen of the 41 evaluation DSP-missed starts match within 5 seconds at count 10. Five of the 9 ESPN members of that group do too. At count 200, none of the 50 match within 5 seconds, and 4 match within 10 seconds.
6. The independent route does see starts DSP missed. At the only count that keeps the program probes inside the budget on the development game and then fails that budget on the other games, the added coverage is mixed with program hits. At the count that stays clean, the added coverage inside 5 seconds is zero.
7. Strict matches are few and occur both within a broadcaster family and across families. Loose matches are mostly cross-broadcaster. Sept 9 shows that a game with no earlier football commercials in the library gets no chronological hits. The benefit tracks what has already been stored, which in this corpus is a small set of openings rather than a network rule.
8. Local CPU matching of this corpus is practical. Extraction is hundreds of times realtime, and the advertisement index for a few thousand 30-second references is tens of megabytes. A 10,000-reference latency was not measured. No GPU is required for this matcher.
9. An advertisement that is not already in the library cannot be returned as a known item. Sept 9's chronological result is that case. Eighty-one evaluation openings are still unknown at count 10 after 10 seconds, and 115 are unknown at count 200. Disappearance of a matched spot was not scored and would not establish that the game had returned.
10. The next experiment is verified announcer identity. A stricter fingerprint threshold is not justified: count 200 is already clean and already silent at 5 seconds. Automated enrollment is not justified as the next investment either: the oracle library already contains every other game's commercials, and it still matches 0 of 121 evaluation openings within 5 seconds at count 200. Another acoustic-distance cutoff has already failed transfer. Identifying the program's own recurring voices is the return question this experiment cannot answer.
