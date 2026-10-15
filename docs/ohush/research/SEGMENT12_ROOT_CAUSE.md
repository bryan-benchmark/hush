# Segment 12 root cause — frozen Thursday track

The handoff called this decision segment 12. In `tnf_digest.json` it is zero-based segment 11. It is track `run29`. The join is by event time and audio distance, not by index: 14 of 15 automatic returns in that segment match a `run29` row within 0.05 s and 0.002 distance. The unmatched return is t=235.008 (audio 0.2157). Evidence: `segment12_evidence.json`.

These rows are diagnostic readings from a held-out run. They are not labels of what was airing.

## What the track actually says

Frozen `.booth.json` ids are `c0001`, `c0002`, `c0015`, `c0017`. The speaker field on these rows lists a different set, `c0001`, `c0002`, `c0004`, `c0005` (later `c0003` replaces `c0005`). The identity file and the live readings are not the same list.

| Track t | `booth_present` | Similarity | Cluster | In that row's `booth_ids`? | Audio distance | Hearing |
|--------:|-----------------|------------|---------|----------------------------|---------------:|---------|
| 189.013 | false | 0.243 | c0010 | no | 0.283 | replacement, machine MUTED |
| 221.013 | true | 0.148 | c0013 | no | 0.234 | replacement, machine MUTED |
| 224.000 | true | 0.120 | c0013 | no | 0.264 | replacement, machine MUTED |
| 285.013 | true | 0.872 | c0016 | no | 0.115 | replacement, machine MUTED |
| 599.040 | true | 0.183 | c0020 | no | 0.345 | replacement, machine MUTED |
| 621.013 | true | 0.705 | c0010 | no | 0.318 | replacement, machine MUTED |

At 221 s and 224 s the flag says the booth is present while the similarity is far below 0.55 and the cluster is not a trusted id. A current re-run of `speaker_worker` would not set `booth_present` from similarity 0.15. The historic flag was written by older code. Replaying that flag through the old `state._booth_match` still uncovers, because the old function returned true on `booth_present` alone.

At 285 s and 621 s the similarity itself is above 0.55, on clusters that are not in the trusted id list. A clean worker that trusts high prototype similarity would still emit `booth_present`. Those two are not explained by the loose flag alone.

## What C1/C2 stopped, and what they left

| Moment | C1/C2 before this pass | After the similarity contract |
|--------|------------------------|-------------------------------|
| 221, 224, 599 (flag true, similarity ≤ 0.18, foreign cluster) | Uncover on the next tick, reason `booth_voice` | Stay covered. Fixture `D_low_similarity_booth_present_stays_covered`. |
| 189 (flag false, similarity 0.24) | Already not a booth match | Still not a booth match. The logged uncover at 189 s is a different path and is not closed by this contract. |
| 285, 621 (similarity 0.87 and 0.71) | Immediate `booth_voice` | Still a verified-looking match. An automatic cover still returns on the next tick. A **human** cover now has to hold 2.5 s (`HUMAN_COVER_RETURN_PERSIST_S`) before that match uncovers. The 621 s flap was about 0.2 s after the human mute, so that one-tick uncover is blocked. A real sustained match still uncovers. |
| Trusted cluster id with no similarity field | Treated as booth if `booth_present` | Still trusted, on purpose, and covered by a test so it cannot change silently. Cluster ids were not shown to be the same person across the 32 restarts. |

`Latch.allow_auto_play` still returns true. The hold lives on `Machine` after `manual("mute")`, which is what the daemon calls for a human cover. Automatic covers are unchanged: a similarity at or above 0.55 still returns immediately. That remaining path is a product choice, not a repaired false flag.

## Trust boundary

1. A similarity number, when present, outranks `booth_present`. Below 0.55 the flag cannot uncover and cannot block a solo-audio cover.
2. No similarity, and the cluster is listed in that row's `booth_ids`: still treated as the booth. Unaudiated.
3. No similarity, speech already over, `booth_present` still set: outro hold. Unchanged.
4. The four ids in `.booth.json` are not what `run29` was using as `booth_ids`. Listening excerpts are duration candidates, not an identity verdict. See `BOOTH_IDENTITY_AUDIT.md`.
