# Roster sync

The voice roster was read and not rewritten. Latest clip identity is the recording plus the clip start, because the card id `v001` was used on two different recordings.

Local HEAD is `18c7179cfd0df1e4776f0d5b3bc25c30d25e8cff`. The working tree is dirty. Nothing was reset, committed, or pushed. Holdouts were not opened.

## What the log contains

`names.jsonl` has the save history. `verified.jsonl` is the append log of every save that carried a name. Neither file is a count of people. The published enrollment report on this tree already says 14 named people across 29 spans. Rebuilding that count from the latest row per recording and clip start gives the same 14 people and 29 spans.

| Person | Named spans |
| --- | ---: |
| Al Michaels | 1 |
| Andrew Whitworth | 1 |
| Bijan Robinson | 1 |
| Clarissa Thompson | 3 |
| Cris Collinsworth | 2 |
| Joe Buck | 4 |
| Maria Taylor | 1 |
| Mike Tirico | 7 |
| Mike Tomlin | 2 |
| Richard Shermann | 1 |
| Ryan Fitzpatrick | 1 |
| Scott Hanson | 2 |
| Steve Harvey | 1 |
| Troy Aikman | 2 |

`v001` appears on NBC `hush_20260913_210542` and later on Prime `hush_20260924_220624`. Keeping only the latest row for the id `v001` would point at the Prime card. That does not drop a named span in the current file, because the NBC clip was saved again under a different card id. The two keys currently name the same 29 spans. The id is still not a stable clip. A future save of `v001` on one recording would hide the other recording if anyone collapsed by id.

Music, crowd, stream lag, and promo text are not in the table above. Steve Harvey and the TNF theme were stored in the name field by the person who labeled them. They stay in the log. They are not treated here as booth announcers for a new enrollment.

Hashes are in `SOURCE_RECEIPTS.json`.
