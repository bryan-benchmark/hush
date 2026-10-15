# LIVE_RECOVERY_001 — Phase 0 Baseline

**Experiment ID:** LIVE_RECOVERY_001  
**scientific_authority:** false  
**dataset_role:** live_dev  
**Frozen at:** 2026-10-08 (local)

## Code identity

| Item | Value |
|------|-------|
| HEAD commit | `eedcb444c2546e06f6b3cea16dc2efb92b8d6506` |
| Working tree | **dirty** (see `baseline/git_status.txt`, `baseline/working_tree.diff`) |
| Defect-peak snapshot | `baseline/defect_peak/` extracted from `ohush_live_false_negative_audit_2026-10-08.zip` (pre-recovery permanent-lock policy) |
| Git HEAD product snapshot | `baseline/code/` (no booth_locked veto — pre-dates booth hardening) |
| Working-tree snapshot at freeze | `baseline/working_tree_snapshot/` |

**Important:** Defects A–C described in the audit exist in the **defect-peak** snapshot, not in git HEAD. Git HEAD lacked the permanent booth veto. The regression was introduced in uncommitted live work on 2026-10-08.

## Environment

| Component | Version |
|-----------|---------|
| Root venv Python | 3.13.5 (`.venv`) |
| numpy (root) | 2.5.2 |
| Exp002 worker Python | 3.13.5 (`experiments/exp002/.venv`) |
| torch (exp002) | 2.14.1 |
| Cnn14 checkpoint | `experiments/exp003/models/Cnn14_mAP=0.431.pth` (unchanged; not modified) |

## Inputs

| Artifact | Location | Notes |
|----------|----------|-------|
| Session | `ohush_live/sessions/2026-10-08-tnf/` | TNF optical live_dev |
| WAV chunks | 25 files, ~0.905 GB | Hashes in `inputs/wav_inventory.json` + `inputs.sha256` |
| Track / decisions / labels | Copied under `inputs/session_2026-10-08-tnf/` | Point labels ≠ interval gold |
| Audit ZIP | `ohush_live_false_negative_audit_2026-10-08.zip` | Excluded WAVs |

Raw WAV **is recoverable locally** (not in the ChatGPT audit ZIP). Chronology is chunked `audio_NNNN.wav` with overlapping open-chunk recording; see inventory durations.

## Track structure

Frozen track copy has **32 engine runs** (timestamp resets). Runs must not be merged for evaluation.

## Baseline tests (at freeze)

Product unit tests were already green under the then-current working tree. Defect-peak included a unit test that **expected** permanent booth lock (`test_booth_locked_blocks_solo_audio_mute`) — a specification error, not an untested bug.

## What baseline metrics can / cannot establish

**Can:** Decision-replay of recorded family traces through frozen Machines; synthetic invariant fixtures; worker crash lines in `.desk.log`.

**Cannot yet:** Trustworthy commercial-recall % from point labels alone; held-out interval gold (Phase 2 provisional only).

## Non-negotiables honored

- Exp001–005 untouched.
- No live-path candidate enablement as part of promotion.
- Working tree preserved (no reset/clean/stash).
