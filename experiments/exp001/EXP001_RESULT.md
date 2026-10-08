# EXP001 result

Status: **partial / negative** for standalone low-level acoustic separation. Spec `exp001-v1` is frozen. No threshold, clip, baseline length, feature weight, or freeze condition was changed after labels were opened.

Session `hush_20260914_212529`, 0–6899 s. Score used for the overlay is the already-computed `euclid_60`. Nothing was rescored.

## Verdict

Boundary signal: present, but not specific. A local maximum of `euclid_60` occurs about every 4 seconds, and 99% of the timeline is already within 10 seconds of one. Every commercial start and end therefore has a nearby peak. That fact does not distinguish breaks from the game.

Persistent commercial-pod identity: weak. The frozen baseline latched twice, both during play (2335–2360 s and 2917.5–2960 s), and never inside a labeled pod.

Standalone detector: no. Of 1,488 local maxima, 1,363 sit more than 10 seconds from any commercial start or end. 172 of those outside peaks are at least as large as the median peak nearest a true boundary (threshold 6.30). Using the median peak nearest a start (6.73) still leaves 135 outside peaks.

Keep the features as supporting evidence. Do not tune them against this ledger.

## Where the numbers live

- Unlabeled plots: `hush_20260914_212529/plots/`
- Labeled plots: `hush_20260914_212529/plots_labeled/`
- Per-boundary table: `hush_20260914_212529/overlay_boundaries.csv`
- Counts: `hush_20260914_212529/overlay_summary.json`
