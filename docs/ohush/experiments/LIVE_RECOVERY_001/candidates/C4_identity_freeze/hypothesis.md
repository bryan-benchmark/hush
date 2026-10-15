# C4 — Identity update controls

## Failure

Top recurring speakers were auto-promoted into the booth set; prototypes updated aggressively → risk of learning ad narrators.

## Change

- Trusted IDs = contents of `.booth.json` only (no live top-N promotion).
- New voices quarantined to `.booth_candidates.json`.
- Refresh embeddings only for already-trusted IDs (or matched trusted protos).
- Existing `.booth.json` not deleted.

## Decision

**PASS** for the invariant “no silent auto-promotion.”  
**INCONCLUSIVE** whether current stored IDs are clean announcer voices.
