# OHUSH_GPU_BRAIN_001

Qwen 2.5 3B ran on the RTX 4070 SUPER and read both Prime games causally. Speakers were not moved. Commercial labels were not read. The run is not ready for a live television shadow.

## Hardware

`ollama ps` after the first answer:

`qwen2.5:3b` · 2.2 GB · 100% GPU · context 4096

The card held about 2288 MiB during the run. Wall time for both games was 632 seconds. No model call took longer than its 5-second chunk. October model time: median 0.26 s, 90th percentile 0.32 s, max 3.40 s. September: median 0.11 s, 90th 0.32 s, max 0.49 s. Model errors: 0.

## Ledger

| | October 8 | September 24 |
| --- | ---: | ---: |
| Chunks | 1921 | 1071 |
| Live events | 278 | 137 |
| Uncertain events | 377 | 160 |
| Duplicate windows dropped | 27 | 28 |
| Live touchdowns | 94 | 48 |
| Of those, line never says "touchdown" | 81 | 45 |
| Live scores kept | 10 | 18 |
| Live halftime mentions | 34 | 27 |

The phrase ledger had 14 October touchdown rows. This model kept 94. Eighty-one of those lines do not contain the word. That is the model adding a score, not Whisper missing one. Examples:

- 20 s, live touchdown: "And you got the Cowboys jumping off."
- 580 s, live touchdown: "I got one."
- 120 s, live touchdown, a new sequence: "49 yards and a touchdown for Kailin."

The real opening call is in there too. At 105 s, "breaks the plane, easy touchdown" is a live touchdown. At 1965 s, "We're back in 30 seconds" is a 30-second break and a halftime line. At 6350 s, "that's the end of the quarter" is a quarter end.

Scores the model kept on October:

| Audio | Stored | Line |
| ---: | --- | --- |
| 2670 s | 10–7 | "Dallas has the lead 10 7" |
| 3195 s | 10–7 | "They trail the Cowboys 10 7 at the half" |
| 3735 s | 10–7 | "the Cowboys on top 10 to 7" |
| 8665 s | 24–16 | "a 24 16 win" |
| 1210 s | 40–5 | "15 yards after that penalty. 40-5" |
| 2705 s | 0–5 | "sit there at 0 and 5" |

10–7 matches the lines where the announcer was stating the score. 40–5 is a spot on the field. 0–5 is a record. Both numbers were spoken, so the scorekeeper stored them.

## Review audio

86 clips are in `clips/`, listed in `clips.jsonl`. They are the scoring lines the model emitted, two examples of the other event kinds, and six stretches of ordinary talk. Listening to those is the precision check. There is still no play-by-play to turn that into a recall number.

## Stop

Experiment 2, the mute scorecard, does not start from this ledger. A watch opened on these touchdowns would arm on "I got one."

The smallest next change is the same rule already used for the score: drop a play event when the line does not contain the words for that play. Then rerun the ledger. A larger model waits until the lines that do say "touchdown" are still being misread.
