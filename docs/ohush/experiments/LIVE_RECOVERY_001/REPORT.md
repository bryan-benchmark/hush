# LIVE_RECOVERY_001 — Final decision report

**Governing rule honored:** No evidence, no promotion. No live-output enablement without authorization.

## 1. Baseline

| Item | Value |
|------|-------|
| HEAD | `eedcb444c2546e06f6b3cea16dc2efb92b8d6506` (dirty tree preserved) |
| Defect-peak | Audit ZIP snapshot with permanent `booth_locked` veto |
| Inputs | 25 WAVs (~0.905GB) hashed; frozen track 32 runs |
| Missing | Interval gold (provisional manifest only) |

Verified starting defect metric (decision replay): **88s** stuck PLAY on veto-shaped frames.

## 2. Root causes

| Defect | Status |
|--------|--------|
| A Permanent booth veto | **PROVEN** |
| B False booth return | **PROVEN** on defect-peak |
| C Synthetic speaker from IDs | **PROVEN** on defect-peak daemon |
| D Identity contamination | **PLAUSIBLE**; auto-promotion frozen |
| E Startup blindness | **PROVEN** timing; **not repaired** here |

## 3. Experiment results

| Candidate | Improvement | Regression | Evidence | Decision |
|-----------|-------------|------------|----------|----------|
| C1 booth semantics | Veto stuck 88→11s; +4 mute events on replay; fixtures A fixed | None on safety fixtures | fixtures + deterministic replay | **PASS** |
| C2 verified return | Blocks continuity/recurring false return | None on verified booth fixture | fixtures | **PASS** / real-world **UNPROVEN** |
| C3 worker health | Synthetic injection removed in WT daemon | Health enum incomplete | code inspection | **INCONCLUSIVE** |
| C4 identity freeze | No auto-promote to `.booth.json` | Existing IDs unaudited | code + quarantine file | **PASS** / purity **INCONCLUSIVE** |
| C5 startup | — | — | deferred | **not run** |

## 4. Winner (for product working tree — not live-promoted)

- **Change:** Identity ≠ speaking; verified return only; no synthetic speaker veto; booth auto-promotion frozen.
- **Regression tests:** `tests/test_ohush_live_recovery.py`, updated `tests/test_ohush_live_state.py`.
- **Replay:** Mode A deterministic on frozen track.
- **Remaining risks:** No interval gold; startup blindness; historical booth.json purity; Mode A families partly polluted by live daemon fields from the mixed evening.

## 5. Deployment readiness

| Gate | Status |
|------|--------|
| Replay (Mode A) | Ready |
| Held-out interval gold | **Not ready** |
| Shadow mode | **Not built / not run** |
| Live validation | **Not authorized** — do not claim |
| Rollback target | `baseline/defect_peak` (broken) or git HEAD + prior WT; keep C1 code under `candidates/C1_booth_semantics/code` |

## 6. Next highest-leverage experiment

**Build interval gold for 3–5 long runs (dev vs held-out), then Mode A metrics for commercial-heard-time and program-covered-time.**  
That unblocks honest recall/precision gates. Only after that: Candidate 5 startup readiness (prewarm), still without multi-threshold thrash.

---

Receipts live under `docs/ohush/experiments/LIVE_RECOVERY_001/`.
