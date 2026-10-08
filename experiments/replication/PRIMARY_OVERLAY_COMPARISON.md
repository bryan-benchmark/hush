# Primary overlay comparison

Gold was hashed before these overlays ran. SHA-256:

- `experiments/annotations/truth_events.jsonl` `6e489a863d765c1333d2759210acccc2d18d239494ce95a1107ab20ec5184249`
- `experiments/gold/GOLD_REPLICATION_V1.json` `b36b6c1b7550696c7ddf3c5308901f00f289c1659eed1f3d4554db6c131ed3f0`

Recorded in `experiments/replication/freeze/gold_ledgers.json`. No threshold, window, collar, phrase list, matcher, freeze rule, or scoring formula was changed. August Hulu gold was shifted onto the experiment clock by subtracting 300 s. Existing collars are 10–30 s, so a mark that is off by two or three seconds still falls inside them. Hand labels were not tightened.

The Prime pod that ends at 7600 s is the span cap. There is no audio after it. That end is not a scored return and not a failed return. Twelve Prime returns are evaluable.

ESPN `hush_20260914_212529` remains development data. Match of its exact fractions is not the question.

## What replicated

On Prime, another football game and a streaming path, commercials still replace an identity the broadcast had already established.

Speaker continuity collapses near the commercial start on 10 of 13 Prime pods, median latency about 7 s. Collapses land at about 28 per hour inside pods and about 7 per hour in program. ESPN was about 28 per hour in pods and about 4 per hour in program. Audio-world distance is higher in the 30 s after the start than in the 30 s before on 11 of 13 Prime starts. Pod median distance is about 0.20 against a program median of about 0.06. ESPN was 15 of 15 starts, pod median about 0.21, program median about 0.09. The strongest Prime peaks still cluster on commercials (14 of the top 20), less tightly than ESPN (17 of 20).

The frozen audio copy stays unlike the Prime commercial. Frozen-program distance median is about 0.32 inside pods and about 0.05 outside. ESPN was about 0.29 inside and about 0.09 outside. The 99th-percentile freeze trigger still covers only 4 of 13 Prime starts. That trigger was already a weak mute on ESPN. The separation of the frozen state is the finding. The trigger rate is not.

Semantic distance tells the same departure story. Prime pod median about 0.81, program median about 0.53. ESPN was about 0.85 and about 0.52. Ad-vocabulary hits are denser in Prime pods (about 0.57 per minute) than in program (about 0.13). ESPN was about 1.06 against about 0.18. Both are too sparse to mute on. Exact “welcome back” occurs once on Prime and is not a collar hit on a return. The one return-collar phrase hit is generic “back to”, which is still not standalone evidence.

## What did not

August Hulu does not show that structure at the same strength.

Speaker collapse within 15 s happens on 5 of 11 Hulu starts. The pod rate is still higher than the program rate (about 21 per hour against about 4), and the program rate matches ESPN’s program rate. Half the commercial starts do not collapse. Audio-world distance rises after the start on 6 of 11 Hulu pods. Pod median is about 0.20 against a program median of about 0.11, a smaller gap than Prime or ESPN, and only 7 of the top 20 peaks sit on a commercial. Frozen-program distance is about 0.22 in Hulu pods and about 0.12 outside. The direction holds. The gap is small. The freeze trigger covers 1 of 11 starts.

Semantic distance on Hulu is about 0.83 in pods and about 0.65 in program. The pod level matches ESPN. The show itself sits closer to that pod level, so the departure is shallow. The known-start semantic return reaches the pre-break level within 120 s on 3 of 11 Hulu pods, against 10 of 15 on ESPN and 7 of 12 evaluable Prime returns. No exact “welcome back” appears. No Hulu return or departure phrase lands inside a collar. Ad vocabulary is the clearest Hulu enrichment, about 2.3 hits per pod minute against about 0.34 in program, and it is still too sparse to act on.

Return of the old identity remains the weak half everywhere. A recurring voice is heard within 10 s of 9 of 12 evaluable Prime returns and 10 of 11 Hulu returns. The voice that dominated before the break returns that fast on 1 of 12 evaluable Prime returns and 5 of 11 Hulu returns. ESPN’s own return result was already the negative half of that experiment. These overlays do not turn it into an unmute.

## Decision this pair supports

Prime agrees with the ESPN departure pattern: the game establishes an identity, commercials replace it, and a frozen copy of that identity stays distinguishable during the pod. August Hulu, the scripted streaming cell, does not show that replacement clearly. Many recurring voices and a smaller audio and semantic gap are what this show actually did.

Exp006 stays unstarted. The locked rule asks for the same qualitative structure on Prime, on this Hulu span, and on one linear scripted show. Linear scripted is still missing. October Hulu and the three football files stay closed until this pair has been read.
