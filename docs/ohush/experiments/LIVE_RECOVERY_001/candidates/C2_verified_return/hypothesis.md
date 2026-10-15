# C2 — Verified return

## Failure

Generic `recurring` / low `continuity` could trigger `booth_voice` and uncover ads.

## Change

`_booth_heard` requires speech plus verified match (`booth_present` or `similarity_to_booth >= SPEAKER_BOOTH_MATCH`).

## Decision

**PASS** on synthetic fixture `B_false_booth_return` + safety `C_verified_booth_return`.  
Implemented in the same `state.py` as C1 (not a separate live deploy).  
Real-world false-return rate: **UNPROVEN** without interval gold.
