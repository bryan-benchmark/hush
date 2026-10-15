# Data integrity audit — 13 October 2026

Machine-readable copy: `recording_registry.json` in this folder. This pass did not reset, stash, or overwrite the dirty working tree, the frozen Thursday track, Exp001–005, or any closed gold file.

## What is preserved

| Item | Status |
|------|--------|
| Frozen Thursday track | `docs/ohush/experiments/LIVE_RECOVERY_001/inputs/session_2026-10-08-tnf/track.jsonl`, sha256 `f4850eccecfb8bbf734fefce0854fb3fe0677e6f339d9f6abe1672d4a02be442`, 5,368 rows, 32 runs |
| Live session folder | `ohush_live/sessions/2026-10-08-tnf/` continued after that freeze. Its track is larger (34 runs). Defect work uses the frozen track. |
| `GOLD_REPLICATION_V1.json` | sha256 still `b36b6c1b7550696c7ddf3c5308901f00f289c1659eed1f3d4554db6c131ed3f0`, the hash frozen before the Prime/Hulu overlays |
| ESPN, Prime, August Hulu coverage | Left as closed. Not relabeled. |
| September 17 and 20 holdouts | Not opened |
| Exp001–005 | Not modified |

`experiments/annotations/truth_events.jsonl` does **not** match the replication-freeze hash. Later rows were appended (October 7 Hulu, and a partial September 9 NBC pass). The replication coverage manifest itself is unchanged. This audit did not rewrite any truth row.

## Closed interval gold

Unmarked time inside these ranges is program. Scoring in `gold_harness.json` uses only these ranges.

| Session | Role | Closed range | Active certain commercials | Commercial seconds |
|---------|------|--------------|----------------------------:|-------------------:|
| `hush_20260914_212529` | ESPN development | 0–6899 s | 15 | 1804.0 |
| `hush_20260924_220624` | Prime replication | 0–7600 s | 13 | 1664.4 |
| `hush_20260827_135935` | August Hulu replication | 300–7200 s | 11 | 860.9 |
| `hush_20261007_220650` | October Hulu | 20–11751 s | 19 | 1521.3 |

`hush_20260909_213047` (NBC, Patriots at Seahawks) has active commercial rows and is **not** in a fully annotated coverage manifest. Those rows are partial. Unmarked time in that file is not program.

## Thursday 8 October alignment

Engine clocks reset. A decision-segment index is not a track-run index. WAV chunk numbers are not run indexes: `audio_0001.wav` is the duration neighbor of `run08`, not `run00`.

Each run was compared with every WAV duration in the live folder. A join is a unique duration candidate only when one file is within 1.5 s of that run's `t_end` and no other file is within 2 s. That is not a sample lock. There is no shared header timestamp.

| Priority run | Result |
|--------------|--------|
| `run00` (381 s) | Unresolved. Nearest file is 11.6 s off. |
| `run11` (369 s) | Weak candidate `audio_0007.wav`, 1.45 s off. Not close enough to label. |
| `run19` (675 s) | Unique candidate `audio_0023.wav`, 0.30 s off. Still not sample-locked, so it is not mounted in the labeler. |
| `run21` (1164 s) | Unresolved. Longest chunk is 900 s. This run crosses a chunk boundary and the join is not known. |
| `run25`–`run31` | Reserved. `run29` has a unique duration candidate (`audio_0044.wav`, 0.13 s) and was used only as a listening candidate for the defect, not as gold. These runs were already inspected during failure diagnosis. They are not an unseen broadcast. |

13 of 32 runs have a unique duration candidate. 19 are unresolved, including the two priority runs the labeling plan wanted first (`run00`, `run21`).

## Blocker

Thursday development intervals cannot be created honestly until a run is tied to audio by something stronger than duration (a sample offset, a recorded chunk-open event, or a listening check that the start of the file is the start of that engine clock). Until then, mounting those WAVs in the labeler would invent a timebase.
