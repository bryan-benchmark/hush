# Evaluation protocol

## Unit

Score whole recordings on the capture-order audio clock. A decision at time t may use audio only up to its stated availability time. The continuous DSP baseline is available at integer second t+1 for a comparison of [t−2, t) with [t, t+1).

## Populations

- Football commercials: sports catalog, excluding RedZone, inside fully annotated spans. n = 136.
- RedZone: zero-commercial control, 0–7200 s.
- Scripted Hulu: reported separately. It is not pooled into the football rate.
- Sealed holdouts: not scored until a promotion review explicitly opens them.

## Metrics

Report these separately. Do not fold them into one accuracy percentage.

| Metric | What it counts |
| --- | --- |
| Starts found / missed | Gold commercial starts with a causal detection inside the stated collar |
| Ends found / missed | Gold commercial ends, same rule |
| Start and end delay | Time from the gold mark to the first causal detection |
| Commercial seconds exposed | Ad audio that would still be heard |
| Program seconds covered | Programming that would be hidden |
| False-mute incidents | Interruptions per program hour, and the longest hidden stretch |
| Premature returns | Unmute while the commercial continues |
| Insufficient evidence | Time the policy is required to abstain |
| Worst session | The broadcast with the largest user-visible error |

Collars used so far, and what they are:

- 0.25, 0.5, 1, 3, 5, 10, 30 seconds: detection windows. A credit requires the boundary to fall inside the window. A detector that was already alarming does not get a new-onset credit.
- 200 ms: annotation tolerance, following DCASE onset collars. Inside that band, do not rank one model above another.
- Pod collar 10 s and program collar 15 s from earlier DSP scoring are bins, not detector rules.

## Three layers

Keep these apart:

1. Boundary detection. Did a candidate land near a transition?
2. Content identity. Is this known advertising, a known announcer, or still unidentified?
3. Policy. What would the listener hear?

A feature's recall is layer 1 or 2. It becomes layer 3 only in a causal replay that also names the unmute rule. The current champion has no layer-3 policy. The error ledger in `docs/ohush/research/ACCURACY_NORTH_STAR_001/` is an accounting of the DSP candidate stream under two explicit fantasies: unmute exactly at the gold end, and mute for the length of a DSP episode. Neither fantasy is the champion.

## Calibration

A score is not a probability until a reliability check on recordings that were not used to fit the score shows that a stated probability matches the observed rate. Game-clock evidence and an announcer saying "two-minute warning" are one situation, not two independent votes.

## Promotion

Append a row to `SCOREBOARD.md`. Do not overwrite an earlier row. The champion changes only under the six rules in `RESEARCH_CONTRACT.md`.
