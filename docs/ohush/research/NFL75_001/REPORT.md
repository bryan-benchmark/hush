# NFL75_001

Product score only. The 99.99% ladder, the champion rule, the gold labels, and the sealed recordings were not changed. Nothing here is an authorized mute.

## Gate

Prime development champion (always play): **FAIL**.

The causal check on the existing fingerprint reader is **FAIL**. Further detector experiments stop here.

## Measured champion, both labeled Prime games

These are the authorized decisions: play. They do not look ahead. Oracle rows are not in this table.

| Metric | Measured | Acceptance |
| --- | ---: | --- |
| Ad coverage | 0.0% | ≥75% |
| False mutes / hour | 0.000 | <1 |
| Longest false mute | 0.000s | <10s |
| Program hidden / hour | 0.000s | <5s |

Eligible commercial seconds: 4306.496. Eligible program seconds: 13733.868. False-mute episodes: 0.

No confidence interval. A rate is episodes divided by program hours. Audio seconds are not independent trials, and a zero on tape that never mutes is not a bound on a future detector.

Per game:

- `hush_20261008_205100`: coverage 0.0%, commercial 2642.141s, program 7798.223s, breaks 23, false mutes 0, acceptance FAIL.
- `hush_20260924_220624`: coverage 0.0%, commercial 1664.355s, program 5935.645s, breaks 13, false mutes 0, acceptance FAIL.

## Bottleneck on the causal champion

The champion never covers. Perfect commercial endings and perfect commercial starts recover no advertising, because both oracles need a real cover to repair. Hidden football is zero. The bottleneck is the start: there is no authorized commercial start. The return cannot be separated until a cover exists.

Count 10, the waveform confirm, and the 180-second holds were not rescored. Those streams can read future audio, so they are not NFL75 measurements.

## Causal verification

Stamp order on `22205` rows of `causal_availability.jsonl`: **PASS**.
That check only confirms each row's `available_at` is at or after `sample_max_consumed_at`, which is at or after the query end. It does not prove the hash would survive deleting later audio.

Prefix invariance of the fingerprint reader: **FAIL**, already measured in `docs/ohush/research/FINGERPRINT_CAUSAL_STREAM_001/REPORT.md`. Interior hashes still changed at a 7.989-second backward window. `docs/ohush/research/UNIVERSAL_V1/decisions.jsonl` is not in this checkout (cited sha256 `08b1b8d9…86713`), so that file was not replayed. Recordings are not in this checkout either.

A synthetic prefix check is in `tests/test_nfl75.py`. A causal hopper matches. A hopper that reads the last sample of the buffer does not.

## Merge rule

Covered stretches of eligible program are one false-mute episode when the uncovered gap between them is at most 2.0 seconds. Duration is the sum of those program seconds. The gap itself was heard and is not part of the duration. A mute that starts in a commercial and continues into the game counts only the program seconds after the gold boundary. One second of unmute does not create a second episode.

## What is development, and what is not an exam set

Both labeled Prime games have already been inspected. October is a development score. September 24 is in the supervised train split. The sealed sessions have no NFL75 labels and were not opened. A 20-hour exam set is not in this checkout.

Active gold marks in the ledger: 177 (the 13 October handoff says 177). Truth sha256 `c658530b39099866229e9cefd20efe158e2b853890e0f982acffa0b75ecd7bd4`.

| Session | Broadcaster | Role | Inspected | Commercial s | Program s | Excluded s | Wall gap s |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| `hush_20260827_135935` | Hulu | development_other | True | 860.874 | 6039.126 | 0.000 | 0.000 |
| `hush_20260909_213047` | NBC | development_other | True | 2849.911 | 6041.280 | 481.809 | 0.000 |
| `hush_20260913_150934` | FOX | development_other | True | 0.000 | 7200.000 | 0.000 | 0.000 |
| `hush_20260913_210542` | NBC | development_other | True | 3052.457 | 9547.543 | 0.000 | 0.000 |
| `hush_20260914_212529` | ESPN | development_other | True | 1804.047 | 5094.953 | 0.000 | 0.000 |
| `hush_20260924_220624` | Prime Video | development_prime | True | 1664.355 | 5935.645 | 0.000 | 0.000 |
| `hush_20261007_220650` | Hulu | development_other | True | 1503.839 | 10227.161 | 0.000 | 0.000 |
| `hush_20261008_205100` | Prime Video | development_prime | True | 2642.141 | 7798.223 | 0.000 | 3395.100 |
| `hush_20261010_222400` | Cable | development_other | True | 1081.817 | 4982.951 | 0.000 | 0.000 |
| `hush_20261011_135700` | Cable | development_other | True | 982.955 | 3913.813 | 0.000 | 0.000 |
| `hush_20261011_204300` | Cable | development_other | True | 626.389 | 13778.987 | 0.000 | 1388.100 |
| `hush_20261012_204200` | Cable | development_other | True | 2944.327 | 10167.481 | 0.000 | 0.000 |

Sealed, not opened:
- `hush_20260917_205513`
- `hush_20260920_200635`

Unlabeled, not an exam set:
- `hush_20260921_204539` (ESPN)
- `hush_20261004_204010` (NBC)
- `hush_20260910_205330` (Netflix)

## Exclusions

Unsure gold is neither covered advertising nor hidden football. The September 9 NBC tape has an excluded gap between gold commercials: an AWS spot that was heard and left out of gold (`tools/gpu_lab/exclusions.json`). That gap is not program and not a covered ad.

Wall gaps on 8 October (3395.1s) and 11 October night (1388.1s) are holes already removed from the elapsed clock. They are listed above and are not scored as silence. Missing playback would block acceptance rather than count as a mute or as a clean game. This champion replay has no missing playback.

October 7 Hulu sums to 1503.839 commercial seconds on the current ledger. `docs/ohush/dataset_handoff/STATUS.md` and the Universal v1 results still say 1521.3. NFL75 uses the current ledger and does not relabel. The nine football games still sum to 17,648.4 commercial seconds.

## Next experiment

Do not train a model from this result. The authorized system covers none of the ads, and the fingerprint scores that cover some of them are not prefix-invariant.

The next experiment is one prefix-invariant feature on `hush_20261008_205100` only: decisions for the first 30 minutes must match when that prefix is scored alone and when it is scored inside the full file. The feature value at time t may use audio at or before t, plus a stated latency that is included in `available_at`. Restore the recording locally to run it. The WAV files and the AST score cache are not in this checkout. If that check fails, stop. If it passes, run the same three-way split — joint, perfect endings, perfect starts — on that one stream, still on development tape, before any new classifier.

## Receipts

- Experiment: NFL75_001
- Commit: `db414c099109338fd3eb912953e3a278ff91eaec`
- Scorer sha256: `70e686abec6eddfe8829f8d1c89ba9ab79e6f63f553240f2eeae946598243a39`
- Truth sha256: `c658530b39099866229e9cefd20efe158e2b853890e0f982acffa0b75ecd7bd4`
- Thresholds: `{"commercial_coverage_at_least": 0.75, "false_mute_episodes_per_program_hour_below": 1.0, "false_muted_program_seconds_per_program_hour_below": 5.0, "longest_false_mute_seconds_below": 10.0}`
- Command: `python -m unittest tests.test_nfl75`
- Command: `python -m experiments.nfl75`
- Live playback was not started. Holdouts were not opened. Gold was not written.
