# OHUSH_VOICE_OPENSET_001

Verdict: at the frozen 0.25 line, open-set rejection is weak. One third of known non-gallery voices are accepted as someone on the TNF cast. When a gallery voice is accepted, the name is always right on this set, including Clarissa Thompson reading DraftKings.

## Rule under test

Gallery: Al Michaels, Kirk Herbstreit, Clarissa Thompson, Ryan Fitzpatrick, Andrew Whitworth, Tony Gonzalez. Enrollment is the same causal TNF references as Path B. A probe embeds on the owner box. Best cosine below the reject line → `unknown`. Otherwise → top name. Mute rules were not changed. Realtime false.

Probes came from existing labels only. Positives are a single gallery Who. Negatives are Billy Bob Thornton, Will Arnett, Jordan Love, Richard Sherman, or an explicit unknown / non-booth speaker. Music-only and unlabeled boxes stayed out. Joe Buck enroll marks sat on ESPN tapes with no prior TNF gallery, so they stayed out of v1.

## Frozen line 0.25

| | Count | Rate |
| --- | ---: | ---: |
| Positives | 13 | |
| Negatives | 12 | |
| False reject (gallery → unknown) | 8 | 0.615 |
| False accept (other → a cast name) | 4 | 0.333 |
| Wrong ID among accepts | 0 | |
| ID accuracy when accepted | 5 of 5 | 1.000 |

Same-voice ad: DraftKings is accepted as Clarissa Thompson at 0.493. Correct for identity. Mute still belongs to commercial recognition.

False accepts at 0.25:

| Clip | Who | Model said | Cosine |
| --- | --- | --- | ---: |
| fn0110 FanDuel | unknown male | Kirk Herbstreit | 0.321 |
| fn0118 Wendy's | unknown female | Clarissa Thompson | 0.373 |
| fn0113 FanDuel | unknown male | Andrew Whitworth | 0.282 |
| fn0119 laundry | active player | Tony Gonzalez | 0.253 |

False rejects are enrollment and coverage, not a high gallery score cut down: five Al Michaels boxes in the opening with no reference yet, two Clarissa Thompson boxes before her first reference, and Ryan Fitzpatrick at 0.090.

## Reject-line curve

| Line | False accept rate | False reject rate | ID accuracy when accepted |
| ---: | ---: | ---: | ---: |
| 0.15 | 0.833 | 0.615 | 1.000 |
| 0.20 | 0.583 | 0.615 | 1.000 |
| 0.25 | 0.333 | 0.615 | 1.000 |
| 0.30 | 0.167 | 0.615 | 1.000 |
| 0.35 | 0.083 | 0.615 | 1.000 |
| 0.40 | 0.000 | 0.615 | 1.000 |
| 0.45 | 0.000 | 0.615 | 1.000 |
| 0.50 | 0.000 | 0.769 | 1.000 |

On this small set, raising the reject line to 0.40 clears every false accept and does not add a false reject beyond the enrollment holes. That is not a new production line. It is the shape of this probe list: the true accepts sit at 0.49 and above, and the false accepts sit between 0.25 and 0.37.

## Files

| File | Contents |
| --- | --- |
| `openset.jsonl` | Every scored probe |
| `results.json` | Curve, false accepts, false rejects, DraftKings check |

## Next

Grow the negative list (Joe Buck and other booths against a fixed TNF gallery). Grow positives that already have a reference. The mute still does not read the name. A higher reject line is a research observation on this set, not a lock.
