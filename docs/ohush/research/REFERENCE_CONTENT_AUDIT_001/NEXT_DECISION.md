# Next decision

**Keep the warm-query candidate. Do not delete the five reference pods. Do not extend covers. The one next experiment is a causal clock for the fingerprint reader.**

The matches at or above 200 are the same advertisements. Thursday's four windows are one DraftKings spot, correlations 0.995 to 0.998 after a 38 to 53 millisecond shift. Monday's window is a chili-lime chip spot, correlation 0.975 after 51 milliseconds. At the unshifted frame time those correlations are about zero. One hop, 23 milliseconds, does not recover them. Channel swap and polarity reversal do not either.

The worst reference pod's strongest query is unrelated audio at the 9810-second boundary, correlation 0.017. Other queries on the high-damage pods are real creatives, scores 135, 145, and 42, correlations above 0.93. The busiest replacement is also a real Sunday Ticket spot. Deleting those pods would throw out verified commercials.

The 25.1-second interruption is the FanDuel promo, correlation 0.956, on a query the gold calls program. Several other NBC false covers are the same kind of promo or spot. A library deletion does not answer that.

## CAUSAL_FINGERPRINT_001

Build the reader so a decision at time T uses only audio already received, including the measured lookahead and excluding any extra charge for the two seconds of past context. Score that clock on the existing ledger. Leave count 10, count 200, gold, and Universal v1 frozen.

Pass only if all of these hold, against `docs/ohush/research/UNIVERSAL_V1/results.json`:

- Football program seconds covered at count 10 fall by at least 50 from 432.1.
- Football commercial seconds covered at count 10 fall by no more than 25 from 3,903.2.
- The DraftKings windows at Thursday 145, 150, 155, and 160 seconds, and the Monday window at 5085 seconds, still score at least 200.
- Football program seconds covered at count 200 stay 0.
- RedZone program seconds covered do not rise.

Fail if any verified count-200 window falls below 200, if count 200 covers any program, or if the count-10 trade misses either bound. Report the NBC promo covers separately. They are the same sound on program-labeled time, and this clock will not relabel them.

PLAY. Universal v1 unchanged. Holdouts sealed. No deployment.
