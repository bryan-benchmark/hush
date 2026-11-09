# Studio supervision on the frozen embeddings

The encoder, the controller, and the published frozen score are unchanged. Prime was not used to fit this head. The comparison below is the original gold.

The head was trained from scratch on the frozen frame embeddings, same size and same eight epochs as the published head. One quarter of each epoch's program examples came from 20.7 minutes of verified studio audio in the training games: the Sunday-night halftime report, the postgame desk, a pregame desk, a Monday-night highlight package, and the RedZone host bridge nearest the Prime desk. Local commercials after those games were left out. They are the training audio the frozen head already calls advertising, and teaching them as program would teach the model to play spots.

## Listener result on the two Prime games

| | Published frozen head | Studio head |
| --- | ---: | ---: |
| Commercial coverage | 86.0% | 88.2% |
| Commercial seconds covered | 3,702 | 3,798 |
| Program seconds covered | 495 | 602 |
| False interruptions per hour | 13.6 | 18.1 |
| Longest false mute | 60.2 s | 59.2 s |
| Named desk spans still covered | 288 s | 254 s |

The desk did not collapse. The 60-second Odell conversation is 59 seconds. The Whitworth desk is 29 seconds. The Palmer hit is 27 seconds. About 34 seconds of the named desk list came back, and 107 additional program seconds were taken elsewhere. Commercial coverage rose by about 95 seconds. That is not a better television.

## What the training tapes actually contain

NBC pregame, RedZone hosting, and most of halftime already score near zero with the published head. The long training stretches that head calls commercial, above 0.90 for eight seconds or more, are station spots and local news after the game, not a football desk. There is no large pool of studio audio in these recordings that the model is confidently missing. The Prime desk remains a sound without a close training neighbor.

## Reviewed boundaries, kept separate

`reviewed_boundaries.json` does not replace the gold file.

Heard edges:

- Oct 8, the Platinum and food spots run 3384.3–3437.1. The desk is still on the air at 3375. "Welcome back" is 3437.1. Of the 55-second mute, 49 seconds are the spots and 6 seconds are the show returning.
- Sept 24, the Chili's spot runs 2969.8–3006.5. The show is back at the return line. Of the 32-second mute, 31 seconds are the spot.
- Oct 8, the Carrie promo runs 4979.8–4993.2, after a labeled break that already contains Tide, USAA, and Quest. The museum feature starts at 4993.2. The 7-second mute is entirely the promo.
- The State Farm "personal game plan" at 3461 stays program. The hosts keep talking about the Cowboys.

Scored on the frozen head only, these three boundary fixes lower program seconds covered from 495 to 408. The longest mute stays 60.2 seconds and the interruption rate stays about 14 per hour. Relabeling is not a model improvement.

## Next experiment

One change: a longer past-only window into the same frozen frames, with the original training mix and the same controller. Prime stays the regression set. The result to watch is whether the 60-second and 30-second desk mutes shrink without program seconds covered going up. If they stay at or above 0.90 for the length of the scene, more labeled studio from these tapes will not fix it.

A new Prime broadcast, labeled before anyone reads the model's mistakes, is still required before calling any later gain general. The sealed tapes stay sealed. Nothing here is on the live television.
