# C1 Decision: **PASS** (invariant + decision-replay gates)

## Reasons

1. Synthetic fixtures: defect-peak reproduces A/B failures; candidate fixes them; safety fixtures still pass.
2. Decision replay on frozen track: veto-shaped stuck PLAY **88s → 11s**; mute events **22 → 26**; determinism OK.
3. Permanent regression suite: `tests/test_ohush_live_recovery.py` + updated `tests/test_ohush_live_state.py`.
4. Did **not** retune `AUDIO_STRONG` / `MIN_AGREE` / persist durations to hide the bug.

## Limits (not over-claimed)

- No interval-based commercial recall / program-covered-time on held-out gold yet → real-world accuracy remains **PROMISING / UNPROVEN**.
- Shadow + controlled live enablement **not authorized** in this work order.
- Candidate 3 worker-health enum incomplete.

## Promotion to live output path

**Not done.** Requires explicit authorization after shadow review.
