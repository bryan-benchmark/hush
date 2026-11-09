# OHUSH_NFL_EVENT_GROUNDING_002

The 4070 run was fast. The touchdown explosion was the model, and the code was willing to keep a touchdown that quoted nothing. After the code started requiring a quote, the explosion collapsed. The ledger is still not clean enough to judge a mute.

Automatic muting stayed off. No larger model. No video.

## Where the 94 touchdowns came from

Twenty unsupported October lines were sent back through the same prompt, and the raw JSON was saved. The parser did not invent the kind. On 18 of the 20, Qwen 2.5 3B returned a play that the line does not state. Twelve of those quotes were empty, and the ledger stored them anyway.

| Raw answer on the 20 lines | Count |
| --- | ---: |
| Touchdown, live, no quote | 7 |
| Touchdown, uncertain, no quote | 5 |
| Touchdown, live, with a quote of unrelated words | 2 |
| Touchdown, uncertain, with a quote | 2 |
| Fumble, live | 2 |
| No event | 2 |

"I got one." came back as a live touchdown with an empty quote. "Cowboys jumping off" came back as a touchdown. That is the model. Keeping the empty quote was the code.

## What changed

A live event now has to repeat words that are actually in the line. A touchdown quote has to be a scoring phrase, including "he's in" and "breaks the plane," not only the word touchdown. "I got one" is dropped. "49 yards and a touchdown" stays uncertain, so it does not open a new score. A score quote has to say it is the score or the lead, so "40-5" and "0 and 5" are dropped. "Quarterback" is not the end of a quarter. "Two minute warning" has to say both "two minute" and "warning," so a credit-card ad that says "two minutes" is dropped.

The model was not called again for that last pass. The quotes from the grounded run were checked a second time.

## Before and after, live events

| | October before | October after | September before | September after |
| --- | ---: | ---: | ---: | ---: |
| Live touchdowns | 94 | 12 | 48 | 6 |
| Touchdowns whose line never says touchdown | 81 | 4, and those four quote "end zone" or "in there" | 45 | — |
| Live events of every kind | 278 | 52 | 137 | 14 |
| Scores kept | 10, including 40–5 and 0–5 | 3, all 10–7 | 18 | 2 |

October scores that remain: "Dallas has the lead 10 7," "they trail the Cowboys 10 7 at the half," and "the Cowboys on top 10 to 7." "We're back in 30 seconds" at 1965 s and 2390 s is still a 30-second break. "End of the quarter" at 6350 s is still a quarter end. "Breaks the plane, easy touchdown" at 105 s is still a live touchdown.

Lines that are still live and should be listened to before anyone trusts them:

- 75 s, "floater that's taken there and to the end zone"
- 695 s, "Come and eat ... touchdown and Jack Brown"
- 3915 s, "end zone at Buka"
- 8175 s, "he got Jones in there"

"Come and eat" is the transcript, so that miss starts in speech recognition. The other three are the model treating "end zone" or "in there" as a finished score.

There is still no play-by-play, so this is not a precision percentage and it is not 95%.

## Commercial check, diagnostic only

Gold was read after the ledger was finished. It did not choose any event.

| | October | September |
| --- | ---: | ---: |
| In-scope breaks | 20 | 9 |
| Breaks with a live event already available in the prior 90 seconds | 17 | 4 |
| Live events with no break in the following 90 seconds | 28 | 9 |

Seventeen of twenty is the same shape as the old phrase ledger, and 28 of the 52 October events are not followed by an ad. An event-gated mute built on this list would still be armed in ordinary play. That is why the three-way mute scorecard was not run. Coverage and false-cut numbers from this ledger would not answer whether the idea works.

## Next ticket

`OHUSH_NFL_EVENT_REVIEW_002`. Listen to the 12 October and 6 September touchdown clips and mark each one real, recap, or wrong. The quotes are on the rows in `football_events.jsonl`. After that list is mostly real, `OHUSH_NFL_EVENT_TO_AD_003` can connect those events to the frozen sound detector and score coverage and false cuts. A larger model waits until a line that truly says the score is still being misread.
