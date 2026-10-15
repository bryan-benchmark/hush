# C1 transition diff (decision replay)

Frozen track: `inputs/session_2026-10-08-tnf/track.jsonl`  
sha256: `f4850eccecfb8bbf734fefce0854fb3fe0677e6f339d9f6abe1672d4a02be442`

## Aggregate

| Metric | Defect-peak | C1 candidate |
|--------|-------------|--------------|
| mute events | 22 | 26 |
| play events | 16 | 19 |
| stuck PLAY on veto-shape (s) | 88 | 11 |
| mutes on veto-shape frames | 0 | 3 |

## Notable candidate-only mutes (improvements under veto removal)

- run19 t≈307, 586 `solo_audio_depart`
- run21 t≈39, 943, 958 `solo_audio_depart`
- run25 t≈117 `solo_audio_depart`
- run29 t≈158, 234, 613 `solo_audio_depart`

## Notable differences in return

Candidate still emits `booth_voice` on verified presence (e.g. run21 t≈948, run29 t≈216/262/620).  
Defect-peak had additional `booth_voice` flaps on run31 — some may be Defect B style; without interval gold these are logged, not scored as accuracy.

Full event lists: `baseline-decisions.jsonl`, `candidate-decisions.jsonl`.
