# Audio signal replication 001 — 13 October 2026

Verdict: **INCONCLUSIVE**.

The existing Exp003 distance does generalize from ESPN to this NBC game: at 18 of 19 evaluable commercial starts, the next 30 seconds sit farther from the recent program than the 30 seconds before. That is not yet a fast alarm. The only causal operating point already frozen for this score crosses within 30 seconds on 9 of those 19 starts, and five of those nine still include pre-break audio in the 10-second window. No threshold was chosen on this recording. No mute decision was simulated.

## What was frozen before the table

Session `hush_20260909_213047`, recording clock 0–9,373 s, 20 commercials, 2,849.911 s. The analysis WAV is the file's own clock. It is 9,373.184 s. The catalog lists 9,373.2 s. No capture hole is recorded inside this range.

The cache was built with `truth_ledger_read: false`. Its parameters match `exp003-v1`: CNN14, 10 s window, 1 s hop, 180 s memory, 60 s minimum reference, first defined score at 80 s. The stored distances match the frozen formula recomputed from the stored embeddings. The checkpoint and WAV hashes match the cache metadata. Labels were not used to compute the series.

`exp003-v1` has no mute threshold. Two descriptions were applied unchanged, not refit:

- The listing keeps the 20 largest scores at least 45 s apart. The top 50 is the extra cut already published on ESPN. Neither is an alarm rate.
- The causal operating point is the existing Exp003b hit on this same score: above the 99th percentile of the prior 10 minutes, then 3 of 5 seconds, then 60 s quiet.

A start is evaluable when both the prior 30 s and the following 30 s contain at least 10 defined scores. The pass bars were: a majority of those starts rise; at least 11 of the top 20 peaks fall in a commercial or within 30 s after a start; causal freezes just after starts are denser per hour than freezes in the remaining program; and a majority of evaluable starts have a causal percentile hit within 30 s. Latency to the maximum inside 30 s is recorded and is not a detection delay.

```text
MPLCONFIGDIR=/tmp/mpl PYTHONPATH=src:. .venv/bin/python experiments/measurement/audio_signal_replication.py
```

## September 9 NBC

One commercial starts at 6.1 s, before any score exists. Scores begin at 80 s, so the first 74 s of that break are unseen. The break continues to 141.5 s, which is why it is not a fully missing interval. The other 19 starts are evaluable. Startup with no score is the first 80 s. There is no other gap.

| Region | Windows | p10 | Median | p90 |
|--------|--------:|----:|-------:|----:|
| Commercials | 2,781 | 0.113 | 0.213 | 0.357 |
| Program | 6,513 | 0.022 | 0.072 | 0.201 |

ESPN's published medians were 0.213 inside pods and 0.092 in program. The commercial median matches. Program here is a little lower. The distributions still overlap: commercial p10 is 0.113 and program p90 is 0.201.

The median rises after 18 of 19 evaluable starts. The miss is break 9, a 28 s pod whose median falls by 0.052. Break 4 rises by only 0.001. The other rises are larger, from 0.05 to 0.39.

The frozen top 20 peaks: 17 fall in a commercial or within 30 s after a start, and 3 fall in program. That is the same 17/20 published for ESPN. The top 50 is weaker: 32 associated, 18 in program. ESPN's published top 50 was 30 associated.

Causal freezes: 11 in the game. Five fall in the 30 s after a start (30 per hour of those windows). Three fall in ordinary program (1.66 per hour, across 6,518 s). The other three are inside a commercial but later than that 30 s window. Program alarms are real and much less dense than start-window alarms.

The speed bar fails. A causal percentile hit during the break, within 30 s, happens on 9 of 19 evaluable starts. The median of those nine delays is 8.0 s, and that number is flattering: five of the nine are under 10 s, so the scored window still contains the program. Four land between 10 and 30 s. Two more hits arrive at 39 s, after the 30 s cut. Seven starts rise in the median and never cross the percentile during the whole break.

A score that merely exceeds the previous 30 s maximum is not detection. It usually happens in the first second, which is still nine seconds of the show.

| # | Start | End | Post − pre | First above prior max | Causal hit | Peak in 30 s | What happened |
|---|------:|----:|-----------:|----------------------:|-----------:|-------------:|---------------|
| 1 | 6.1 | 141.5 | — | — | — | — | Starts before the signal exists |
| 2 | 623.3 | 806.3 | +0.127 | 0.7 s | 20.7 s | 21.7 s | Hit within 30 s |
| 3 | 1000.4 | 1048.2 | +0.179 | 0.6 s | — | 12.6 s | Rises, no causal hit |
| 4 | 1074.3 | 1255.2 | +0.001 | 11.7 s | — | 28.7 s | Rise is negligible, no hit |
| 5 | 1608.6 | 1743.9 | +0.389 | 0.4 s | 3.4 s | 11.4 s | Hit still contains pre-break audio |
| 6 | 2066.7 | 2199.5 | +0.308 | 0.3 s | — | 8.3 s | Rises, no causal hit |
| 7 | 2514.4 | 2647.2 | +0.283 | 0.6 s | — | 18.6 s | Rises, no causal hit |
| 8 | 2895.0 | 3038.8 | +0.333 | 1.0 s | 8.0 s | 15.0 s | Hit still contains pre-break audio |
| 9 | 3105.0 | 3133.3 | −0.052 | — | — | 22.0 s | Median does not rise |
| 10 | 3445.4 | 3576.1 | +0.323 | 0.6 s | 12.6 s | 14.6 s | Hit within 30 s |
| 11 | 3942.6 | 4075.1 | +0.314 | 0.4 s | — | 15.4 s | Rises, no causal hit |
| 12 | 4475.0 | 4614.6 | +0.251 | 0.0 s | — | 5.0 s | Rises, no causal hit |
| 13 | 5428.5 | 5574.3 | +0.298 | 2.5 s | 0.5 s | 6.5 s | Hit still contains pre-break audio |
| 14 | 6074.2 | 6210.5 | +0.271 | 0.8 s | 4.8 s | 8.8 s | Hit still contains pre-break audio |
| 15 | 6357.0 | 6508.5 | +0.287 | 6.0 s | 16.0 s | 25.0 s | Hit within 30 s |
| 16 | 7001.0 | 7178.2 | +0.067 | 8.0 s | 24.0 s | 25.0 s | Hit within 30 s |
| 17 | 7641.7 | 7849.4 | +0.178 | 0.3 s | 6.3 s | 6.3 s | Hit still contains pre-break audio |
| 18 | 8020.2 | 8207.4 | +0.074 | 0.8 s | 39.8 s | 26.8 s | Hit after 30 s |
| 19 | 8413.7 | 8585.4 | +0.050 | 1.3 s | — | 6.3 s | Rises, no causal hit |
| 20 | 9200.6 | 9350.3 | +0.069 | 3.4 s | 39.4 s | 12.4 s | Hit after 30 s |

"Peak in 30 s" is the old overlay statistic, the time of the highest score, not the first evidence. Every row is in `nbc_breaks.csv`. The series is `nbc_distance.png` and `nbc_audio_distance.parquet`.

No commercial-heard time, program-covered time, or false-cover count is reported. There is no frozen rule that turns this distance into play and mute.

## RedZone

Session `hush_20260913_150934`, 0–7,200 s, zero target commercials. The same score and the same causal freeze rule. Every freeze is a false commercial start.

The typical RedZone distance does not look like a commercial. Its median is 0.049 and its 90th percentile is 0.139, against the NBC commercial median of 0.213 and the NBC program median of 0.072. Changing games, if that is what this broadcast does, does not make the ordinary second look like an ad.

The tail does. Twelve causal freezes fire, 6.0 per hour, against 1.66 per hour in NBC program time. The strongest distances reach 0.46, which is commercial-sized. Of the ten strongest peaks, two coincide with a change in the frozen speaker-cluster id. The other eight do not. Several have no cluster on one side of the peak, which is missing speech assignment, not an identified announcer change. Game-to-game cuts were not labeled, so they cannot be offered as the cause. The recording was not relabeled.

Figure: `redzone_distance.png`. The three distributions are in `distributions.png`.

## Answers

1. Yes. The departure direction generalizes. Eighteen of nineteen evaluable NBC starts rise, the commercial median matches the published ESPN pod median, and the top-20 listing is 17/20, the same count as ESPN.
2. Not quickly, at the only predeclared causal operating point. Nine of nineteen evaluable starts cross it within 30 s, and five of those nine are still mostly the previous program. Seven rising starts never cross it during the break.
3. Three causal freezes during ordinary NBC play, 1.66 per hour. Three of the top 20 peaks sit there too. The top 50 leaves 18 peaks in program. That is too many to mute on, and it is the same caution the ESPN result already stated.
4. RedZone does not show that every broadcast change looks like an ad. Its center looks like program. It does show that the loud tail of a commercial-free football broadcast still produces 6 false departure alarms per hour, and speaker identity does not explain those peaks.
5. Not yet. The start signal is real and too slow, at this window and this operating point, to treat return detection as the next problem. The next measurement is a shorter causal window on this same embedding. Not a new model, and not a threshold fit on this game.

## Uncertainty

- A score at time t is the preceding 10 s. Anything under 10 s still contains the show.
- The 99th-percentile hit was frozen for Exp003b. It was not designed as Exp003's mute rule, and it was not refit here. It is the only causal operating point that already existed.
- Break 4 counts as a rise because the median moves by 0.001. It is not a useful separation.
- The first commercial is unevaluable because the warm-up has not finished, not because the distance was low.
- RedZone speaker ids are the frozen Exp002 assignment. A cluster change is not a verified person, and the absence of a cluster is not a verified game change.

## Hashes

| File | sha256 |
|------|--------|
| CNN14 checkpoint | `0dc499e40e9761ef5ea061ffc77697697f277f6a960894903df3ada000e34b31` |
| September 9 analysis WAV | `65722bb8ad1445b38a560b283e7912cc9c42571773896a5eb819e42de9e9a942` |
| `experiments/exp003/hush_20260909_213047/program_cloud.parquet` | `4ca30645c2c16730ae810383f3129e1f97772eebbed94ae69111363a3ef7f30a` |
| `experiments/exp003/hush_20260913_150934/program_cloud.parquet` | `80ebe6a7672f42d221d2cd4a23f083cbc025a325fac601ed4bf9e3c1e160d0dc` |
| `nbc_audio_distance.parquet` | `8f7f7607211a92e7efe4f49d0790937bfe0605fcfa78be5a368f3d30a0bd4667` |
| `experiments/annotations/truth_events.jsonl` | `a5e97a6d9b0af1a39355d610b32374cb974903b86b09cb625549019224a3313b` |
| `src/hush/program_cloud.py` | `437464395e5bca1c066162cccf4fbdf3eed957b386fc81fe2c29e90f8865c4e8` |
| `src/hush/frozen_identity.py` | `447927c7e7565cd3a710ddbb07610a5852349cbeb7a5dc8c91feb8d1140e4510` |
| `experiments/measurement/audio_signal_replication.py` | `fb68c636f33d954faea43905eeeaa7cad2cfae1479d6214e8b5f043be68ba40d` |
| `results.json` | `c1a6d7368913ae1737dcb77909f0cc023e40a0502027de7175bdf1eb9cadadf5` |
| `nbc_breaks.csv` | `7bd9e2d54f80a87c26391ea06b2bd885caac092e4d4bb7b8aae2cd4d61efa8b2` |

## Files this pass changed

- `experiments/measurement/audio_signal_replication.py`
- `docs/ohush/research/AUDIO_SIGNAL_REPLICATION_001/` (`REPORT.md`, `results.json`, `nbc_breaks.csv`, `nbc_audio_distance.parquet`, `nbc_distance.png`, `redzone_distance.png`, `distributions.png`)

The truth ledger, Exp003 outputs, thresholds, booth identities, and the live decision engine were not modified.
