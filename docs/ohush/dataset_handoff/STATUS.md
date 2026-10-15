# Dataset handoff — 13 October 2026

Listening for this round is finished. 177 active marks, from 189 raw rows. Drop a row whose `gold_id` is named by a later `supersedes`, and drop retracted rows. Counts below use that rule. `digest.json` is the same table.

The scoring target is unchanged: `event_class` commercial, `desired_action` mute, `confidence` not unsure, inside a fully annotated span.

## Newly closed

| Session | What it is | Heard | Target commercials |
|---|---|---|---|
| `hush_20261008_205100` | Thu Oct 8 Prime, Bucs at Cowboys | 2.90 h | 23, 2642.1 s |
| `hush_20261011_204300` | Sun Oct 11 night, cable | 4.00 h | 6, 626.4 s. Program note: Gilmore Girls |
| `hush_20261012_204200` | Mon Oct 12, Monday Night Football | 3.64 h | 24, 2944.3 s. Program note: news |
| `hush_20261010_222400` | Sat Oct 10, cable | 1.68 h | 6, 1081.8 s. Program notes: SNL, Alabama–Georgia, LSU, Gilmore Girls, end |
| `hush_20261011_135700` | Sun Oct 11 afternoon, cable | 1.36 h | 8, 983.0 s. Program notes: football, end |

Thursday and Sunday night each contain a hole. Elapsed time skips it. The hole is in `live_label_sessions.json`, not filled with silence.

Thursday's marks use captured-audio order. They do not score the Thursday live mute log.

## Already closed before this round

| Session | What it is | Heard | Target commercials |
|---|---|---|---|
| `hush_20261007_220650` | Oct 7 Hulu, Gilmore Girls, from 20 s | 3.26 h | 19, 1521.3 s |
| `hush_20260909_213047` | Sept 9 NBC | 2.60 h | 20, 2849.9 s |
| `hush_20260913_210542` | Sept 13 NBC | 3.50 h | 21, 3052.5 s |
| `hush_20260913_150934` | Sept 13 FOX, first 2 h only | 2.00 h | 0. Program note: RedZone |
| `hush_20260924_220624` | Sept 24 Prime | 2.11 h | 13, 1664.4 s |
| `hush_20260827_135935` | Aug 27 Hulu, 300–7200 s | 1.92 h | 11, 860.9 s |
| `hush_20260914_212529` | Sept 14 ESPN, 0–6899 s | 1.92 h | 15, 1804.0 s |

Prime, August Hulu, and ESPN stay frozen. Do not relabel them because a detector disagrees.

## Not in this round

Sealed, and not in the ledger: `hush_20260917_205513`, `hush_20260920_200635`.

Still unlabeled, and not required for the next measurement talk: Sept 21 ESPN (`hush_20260921_204539`), Oct 4 NBC (`hush_20261004_204010`), and the long Sept 10 Netflix file (`hush_20260910_205330`).

No WAV files are in this zip.
