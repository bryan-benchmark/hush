# Measurement v1

Definitions live in `experiments/measurement/metrics.py`. Tests: `tests/test_measurement_v1.py`. Numbers for the closed recordings: `gold_harness.json`.

## What is scored

Inside one fully annotated range, on one clock:

| Metric | Definition |
|--------|------------|
| Target commercial | `event_class=commercial`, `desired_action=mute`, `confidence` not `unsure` |
| Commercial-heard seconds | Target time whose playback state is `program` |
| Commercial-covered fraction | Target time whose playback state is `covered`, divided by target seconds |
| Program seconds | Annotated time that is not a target and not an unsure span. A network promo marked `play` counts as program for this product target. |
| Program-covered seconds | Program time whose playback state is `covered` |
| False-cover incidents | Covered playback spans that overlap program |
| False returns inside a commercial | A `program` span inside a target that follows a `covered` span in that same target |
| Start delay | Seconds from the target start to the first covered sample. Missing if the target is never covered. |
| Unscorable seconds | Coverage that is neither unsure nor overlapping a playback span |

Gaps in playback are unscorable. They are not called program. Resetting clocks must not be concatenated before this function is called.

The proposed consumer bars (90% of target seconds covered, under one second of program covered per hour, median start delay under 3 s) are not measured results. They are not used as a pass line here.

## What was run

Two degenerate policies, so the harness is executable on real intervals before any detector is replayed:

| Session | Target commercial s | Program s | Never-cover: commercial heard | Always-cover: program covered |
|---------|--------------------:|----------:|------------------------------:|-------------------------------:|
| ESPN 0–6899 | 1804.0 | 5095.0 | 1804.0 | 5095.0 |
| Prime 0–7600 | 1664.4 | 5935.6 | 1664.4 | 5935.6 |
| August Hulu 300–7200 | 860.9 | 6039.1 | 860.9 | 6039.1 |
| October Hulu 20–11751 | 1521.3 | 10209.7 | 1521.3 | 10209.7 |

Never-cover hears every target second and covers no program. Always-cover covers every target second and covers the entire program. Those are the two ends of the metric, not candidate detectors.

`ohush_live` was not replayed on these recordings. Doing that would be a new feature extraction, and this work order stops before that.

## What was not scored

Thursday 8 October has no interval gold. `run00` and `run21` have no WAV join. `run19` and `run29` have duration candidates only. There is no development-run baseline for the live algorithm, for C1/C2, or for the 0.14 / 0.18 / 0.22 audio bars.

`run25`–`run31` stay reserved. They were already read for the defect, so a later frozen-metric pass on them is a diagnostic, not an unseen broadcast.

September 9 NBC has commercial rows and no closed coverage. It is not in the table.
