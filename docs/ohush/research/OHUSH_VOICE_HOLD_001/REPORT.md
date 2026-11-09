# Voice hold on the frozen mute

The frozen acoustic head stays the champion. This replay does not train, does not move 0.25, and does not change the live television. A SpeechBrain window counts only after it ends. The current rule lets that window veto the frozen mute for the next 1 second, which is the hop of the 2-second embedding. The tail rule lets it veto for 2 seconds. Prime is a regression read.

## Original gold

| Rule | Commercial coverage | Commercial seconds covered | Program seconds muted | Episodes | Longest mute |
| --- | ---: | ---: | ---: | ---: | ---: |
| Frozen | 86.0% | 3,702 | 495 | 52 | 60.2 s |
| Voice, 1 s | 79.5% | 3,422 | 263 | 51 | 32.0 s |
| Voice, 2 s | 77.6% | 3,342 | 255 | 49 | 32.0 s |

The 1-second veto returns 232 program seconds and opens 280 commercial seconds. September is the favorable side: 199 program seconds back, 47 commercial seconds opened. October is the other side: 32 program seconds back, 233 commercial seconds opened. No break is missed, and the median delay at the start of a break stays 0.91 seconds and 3.03 seconds. The opened commercials are voice matches inside the spots.

The extra second of tail returns 8 more program seconds and opens 80 more commercial seconds. October coverage falls to 75.8%. The tail is not kept.

## The named minutes, 1-second veto

| Span | Frozen | Voice, 1 s | Voice, 2 s |
| --- | ---: | ---: | ---: |
| Odell, 60 s | 60.2 | 14.5 | 12.0 |
| Whitworth, 29 s | 29.4 | 0.5 | 0.0 |
| Palmer report, 27 s | 27.1 | 5.1 | 4.1 |
| Injury desk, 19 s | 19.4 | 19.4 | 19.4 |

Whitworth comes back. Most of Odell comes back. Palmer comes back once a window has ended, and about 5 seconds at the start stay muted because the match is inside the report. The injury desk does not move. Nobody enrolled clears 0.25 there. The longest mute left on September is the Chili's spot at 2975–3007, which the gold still calls program and which the voice does not match.

## Reviewed boundaries

These are the three heard spots, scored separately. They do not replace the table above.

At 1 second, program muted on the reviewed labels falls from 408 seconds to 183. September's longest mute falls from 60.2 seconds to 19.5, which is the injury desk. October's longest falls from 11.0 seconds to 6.9. October commercial coverage is 78.0%. The original-gold decision stands.

## Decision

Do not install the veto. The desks it can hear come back, and the injury desk stays muted, which is what a missing voice should do. The same cosine opens 233 seconds of October commercials without slowing the start of the breaks. A longer tail spends more.

The next measurement is the guard already published for the older detector, scored here on the frozen controller: Al Michaels, Kirk Herbstreit, and Clarissa Thompson only, cosine 0.25, runner-up gap 0.15, one-second hop. Whitworth and Gonzalez stay out, as that guard already decided. Keep it only if the October holes shrink and the Odell, Whitworth, and Palmer releases remain. If the desks go mute again, this cosine cannot protect them without playing the ads.
