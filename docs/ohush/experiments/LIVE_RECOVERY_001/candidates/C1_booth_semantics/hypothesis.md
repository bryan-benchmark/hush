# C1 — Booth state semantics

## Failure

Remembered `booth_locked` blocked commercial detection without current announcer speech. Daemon could synthesize a speaker reading from stored IDs.

## Causal theory

Identity was conflated with live observation. Quorum treated `booth_locked` like an active protection condition.

## Intended improvement

Separate:

- `booth_identity_known` (metadata)
- `verified_booth_speaking_now` (`speech` + verified match)
- `bounded_outro_protection` (`booth_present` linger after verified speech only)

Remembered identity must never veto solo-audio commercial covering.
