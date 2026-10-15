# LIVE_RECOVERY_001 — Phase 3 Defect Audit

## Defect A — Permanent booth veto

**Status:** PROVEN  
**Source:** `baseline/defect_peak/ohush_live/state.py` `_quorum`  
**Mechanism:** `if depart and (booth_locked or _booth_still_talking(...))` requires speaker+audio or blocks forever.  
**Daemon assist:** `sports_daemon.py` synthesized `booth_locked=True` speaker when worker was null.  
**Repro:** fixture `A_permanent_booth_veto` → defect-peak stays PLAY; candidate mutes `solo_audio_depart`.  
**Track evidence:** veto-shaped stuck PLAY seconds: **88 → 11** under decision replay.

## Defect B — False announcer return

**Status:** PROVEN (on defect-peak)  
**Source:** `_booth_heard` accepted `recurring` or `continuity >= 0.12`.  
**Repro:** fixture `B_false_booth_return` → defect-peak returns `booth_voice`; candidate stays MUTED.  
**Safety retained:** fixture `C_verified_booth_return` still returns on verified `booth_present`.

## Defect C — Synthetic / stale speaker readings

**Status:** PROVEN in defect-peak daemon  
**Source:** `sports_daemon.tick` created synthetic speaker from `_booth_ids` when `families["speaker"] is None`.  
**Fix location (working tree):** synthetic injection removed; quiet worker → `speaker=None`; outro linger only after verified `booth_present`.  
**Worker health enum:** not yet first-class in live `/state` (Candidate 3 incomplete — see report).

## Defect D — Contaminated announcer identities

**Status:** PLAUSIBLE / PARTIALLY MITIGATED  
**Source:** defect-peak `speaker_worker._booth_ids` auto-added top recurring clusters; `booth_present |= recurring`; prototypes updated for any booth_present cluster.  
**Mitigation (Candidate 4 in working tree):** trusted `.booth.json` no longer auto-promotes; new voices go to `.booth_candidates.json`; refresh only trusted IDs.  
**Unverified:** whether specific stored IDs tonight are ad voices — not proven from archive alone. Existing `.booth.json` not deleted.

## Defect E — Startup blindness

**Status:** PROVEN as timing fact; not repaired in this work order  
**Evidence:** MISS_REVIEW + audio windowing: first scoreable audio ~35–36s with live `AUDIO_MIN_REFERENCE_S=15` + 10s window.  
**No threshold simultaneous retune performed.** Deferred to a later candidate after A–D receipts.

## Minimal reproducers

| Defect | Fixture / command |
|--------|-------------------|
| A,B,safety | `python -m ohush_live.recovery.compare_fixtures --defect-peak .../baseline/defect_peak --candidate .../C1.../code --out ...` |
| A track | `metrics.json` stuck_play_on_veto_shape_s |
| Determinism | identical `candidate-decisions.jsonl` on repeat replay |
