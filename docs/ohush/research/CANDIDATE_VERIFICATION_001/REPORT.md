# CANDIDATE_VERIFICATION_001

The frozen DSP episodes were kept as they are. CNN14 was joined from the existing adaptive-distance series, and only on recordings that already have that series. The cutoff was chosen on ESPN and applied unchanged. No new model was trained. No mute rule was changed.

| Artifact | sha256 |
| --- | --- |
| `experiments/broadcast_intelligence/candidate_verification.py` | `1b07b7edd5b1f4b76b993a8160d19310d60a06ab8518f900159a190ff4dabcc7` |
| `docs/ohush/research/CANDIDATE_VERIFICATION_001/results.json` | `6f72e2863bd875b9ed93f8111a0e33793c7c1a9d166901cf85638ed0a57ab170` |
| `docs/ohush/research/CANDIDATE_VERIFICATION_001/pr_curve.png` | `12f15da494694fcc28630e070f88f5b034bbfd402074249e5e92b88b62a12d0a` |

Command: `MPLCONFIGDIR=/tmp/mpl PYTHONPATH=src:. .venv/bin/python experiments/broadcast_intelligence/candidate_verification.py`

Wall time 63.1 seconds. Peak resident memory 332 MB. That time is the join plus reading three seconds of audio at each episode onset. It is not a new CNN14 forward pass. Every joined series uses checkpoint `Cnn14_mAP=0.431.pth` sha256 `0dc499e40e9761ef5ea061ffc77697697f277f6a960894903df3ada000e34b31`, with `truth_ledger_read: false`. The first defined score is at 80 seconds. Sept 9 and RedZone hashes match the files already cited in the audio-signal and frozen-return reports.

## Verdict: INCONCLUSIVE

CNN14's distance at a DSP episode is a real ranking signal on the development game. The cutoffs that satisfy the false-accept budgets on that game do not survive on the other football games, and they keep only a small share of the commercial starts.

This is Path B. The anomaly score does not reject ordinary football changes tightly enough to verify a mute. The accepts that do occur are available in about 2 seconds, so speed is not the failure.

## 1. Frozen candidate inventory

8,573 OR episodes from `CONTINUOUS_DSP_001`. An episode is fresh only when its first positive second falls inside the 3 seconds at or after a gold boundary. An episode that is already running is not relabeled as that boundary.

| Population | Episodes |
| --- | --- |
| Fresh, begins within 3 s after a commercial IN | 59 |
| Already running at a commercial IN | 59 |
| Fresh, begins within 3 s after a commercial OUT | 41 |
| Already running across a commercial OUT | 49 |
| Inside a pod, not in those 3-second windows | 2,001 |
| Ordinary program | 5,466 |
| RedZone | 947 |

Those seven rows add to 8,622 because one row is a flag, not a separate pile of episodes. The 49 episodes "already running across a commercial OUT" are 49 of the 2,001 inside-pod episodes; their onset is still inside the pod, and the flag only says the episode also reaches the gold OUT. The exclusive classes are fresh-start 59, already-running-at-IN 59, fresh-end 41, inside-pod 2,001, program 5,466, and RedZone 947. Those add to the 8,573 episodes. The 49 / 37 / 50 football-start split below uses the exclusive classes, not the flag.

On the 136 football starts, 49 have a fresh episode, 37 have only an episode that was already running, and 50 have no positive second within 3 seconds. That is the same 49 / 37 / 50 split as the continuous scan. The inventory did not move any ongoing alarm into the fresh column.

Onset RMS, flatness, and centroid are stored on each row of `episodes.csv`. They were recomputed at the frozen onset with the same three-second probe. They were not given a new threshold.

## 2. The CNN14 join

The score called `level` is the adaptive CNN14 distance whose 10-second window ends at the episode's availability time, one second after the onset. `rise` subtracts the median distance from 30 seconds before that to 10 seconds before. `ratio` divides by that median. Nothing after the availability time enters the score.

ESPN (`hush_20260914_212529`) is the development game. It has 5 fresh-start episodes and 471 program episodes with a finite distance. Average precision:

| Score | Average precision | Prevalence of fresh episodes |
| --- | --- | --- |
| level | 0.379 | 0.0105 |
| rise | 0.292 | |
| ratio | 0.157 | |

`level` is the selected score. A trajectory does not beat the distance itself. Five positives is a thin basis for a cutoff. That limitation stays attached to every number below.

Football recordings with no series, left unscored: Thursday Prime Video, and the four cable games (`hush_20261008_205100`, `hush_20261010_222400`, `hush_20261011_135700`, `hush_20261011_204300`, `hush_20261012_204200`).

Evaluation football is only Sept 9 NBC, Sept 13 NBC, and Prime. RedZone is the negative control. ESPN is not in the evaluation pool.

The published 99th-percentile exceedance, unre-tuned, was joined at the same availability second. It fires on 1 of 7 fresh-start episodes on Sept 9, 0 of 5 on Sept 13, and 1 of 6 on Prime. It also fires on 3, 9, and 4 ordinary-program episodes on those games. Requiring the old CNN14 alarm would drop most of the fresh DSP candidates and would still accept program episodes. That rule was not used as the verifier.

## 3. Departure verification at each budget

ESPN has 1.415 program hours. One false accept is already 0.71 per hour, so the 0.5 and 0.1 budgets both allow zero ESPN program accepts. They share one cutoff: above every ESPN program episode (`0.3347`). The 1-per-hour budget allows one ESPN accept and cuts at `0.3114`. An episode is accepted only when its distance is strictly above the cutoff.

| Budget | ESPN cutoff | Eval false accepts / hour | Fresh-candidate starts kept | All eval starts kept | RedZone false accepts / hour |
| --- | --- | --- | --- | --- | --- |
| 1 / hour | 0.3114 | 5.24 | 5 / 18 (0.28) | 5 / 54 (0.09) | 2.00 |
| 0.5 / hour | 0.3347 | 3.60 | 3 / 18 (0.17) | 3 / 54 (0.06) | 2.00 |
| 0.1 / hour | 0.3347 | 3.60 | 3 / 18 (0.17) | 3 / 54 (0.06) | 2.00 |

On ESPN itself the 1-per-hour cutoff accepts 1 of 481 program episodes (0.71 / hour) and 2 of 5 fresh-candidate starts. That is the fit. It is not confirmation.

Widening the credit window from 3 seconds to 30 seconds adds no accepted starts. The episodes that begin later do not clear the cutoff. Median delay of the five accepted evaluation starts is 2.0 seconds. The 95th percentile is 2.8 seconds.

At the 1-per-hour cutoff the same distance also accepts 135 of 758 episodes inside evaluation commercial pods. A high distance is common once the break is underway. It is not evidence that the game has returned. This series stays a departure score only.

The precision-recall curve of fresh-start episodes against program episodes on the three evaluation games is `pr_curve.png`. The curve is descriptive. The operating points above are the only cutoffs.

## 4. Per recording

Evaluation, 1 false accept per hour on ESPN:

| Recording | Program episodes | Accepted | Per hour |
| --- | --- | --- | --- |
| Sept 9 NBC `hush_20260909_213047` | 370 | 5 | 2.76 |
| Sept 13 NBC `hush_20260913_210542` | 524 | 20 | 7.54 |
| Prime `hush_20260924_220624` | 109 | 7 | 4.25 |

No evaluation recording has zero false accepts. Sept 13 is the worst. At the stricter cutoff those rates are 1.66, 4.90, and 3.64 per hour. Still none are clean.

RedZone, 947 episodes, 2.00 hours: 4 episodes exceed either cutoff, 2.00 per hour. The development game's quietest program tail is not quiet on RedZone.

## 5. Where the football starts go

At the 1-per-hour cutoff, all 136 football starts:

| Cause | Starts | What was measured |
| --- | --- | --- |
| No DSP episode within 3 s | 50 | The candidate never began |
| Episode already running, not a new onset | 37 | Not credited, and not passed to the cutoff |
| Fresh episode, no CNN14 series on that recording | 26 | Thursday and the cable games |
| Fresh episode, distance below the cutoff | 15 | Verifier rejected it |
| Fresh episode, score not defined yet | 1 | Onset before the series exists |
| Accepted within 10 s | 7 | 2 of these are the ESPN fit, 5 are evaluation |

The verifier never sees the 50 starts with no episode, or the 37 whose alarm was already on. Of the 18 evaluation starts that do have a fresh episode, 12 are rejected, 1 has no score, and 5 are accepted. Candidate failure removes more starts than the cutoff does.

## 6. Returns

No verified program-speaker enrollment exists for these recordings. Cluster ids, `booth_present`, and `.booth.json` were not treated as announcer identity. The booth audit on the Thursday session already says those ids are unaudited, and that session is not in this CNN14 join.

Of 132 eligible football ends, 35 have a fresh DSP episode within 3 seconds and 97 do not. None of the 132 has a verified announcer match to accept or reject. The break-duration distribution remains a prior only. CNN14 was not asked to authorize a return.

## 7. What this leaves open

The measured gap is identity, not another change detector and not a faster window. A general distance can sit higher on some commercial onsets than on typical play, and on ESPN that ranking is visible. Transferred to three other football broadcasts, the cutoff that allows one ESPN mistake produces several mistakes an hour and keeps about one evaluation start in eleven. RedZone still produces two accepted episodes an hour. Half of football starts never generate the fresh episode a verifier would need.

## Next experiment

Known-advertisement fingerprints, on two sets at once: the fresh DSP episodes, and the 50 football starts that never produced one. A fingerprint either matches a previously heard ad or it does not. That is a different question from how far the audio moved. Do not enroll speakers from unaudited clusters as a shortcut, and do not start the fingerprint test in this run.
