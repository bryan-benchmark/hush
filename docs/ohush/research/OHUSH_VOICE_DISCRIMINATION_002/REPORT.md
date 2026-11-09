# OHUSH_VOICE_DISCRIMINATION_002

ECAPA can name Al Michaels and Kirk Herbstreit on these clips. The same cosine also names Joe Buck as Herbstreit, and the scoring tricks that were supposed to stop that do not. TitaNet, run on the same 168 marks with its own references, still does both things. The pause rule was not built. The 0.25 line was not moved. Gold was not changed. Nothing here is a second tape.

The frozen ECAPA count reproduced before any new rule was applied: 7 of 8 October clear clips correct at 3 seconds from clean September references, 25 of 74 other-show marks accepted, 17 of 19 Joe Buck marks accepted, and e0156 Tony Gonzalez accepted as Andrew Whitworth.

## What was compared

Every owner mark is 3.0 seconds. The windows are the first 1, 2, and 3 seconds of that mark. October probes use September references only. September has no earlier Thursday game in this label file, so a September number is the same broadcast with the probe left out.

Three ECAPA rules, all declared before the count:

| Rule | What it does |
| --- | --- |
| Frozen | Accept the nearest Thursday name at cosine 0.25. |
| Margin | Same line, and the runner-up must be at least 0.15 behind. That gap was fixed from the earlier separation description. It was not searched. |
| Max reference | Score each reference clip, keep the closest one per person, then apply 0.25. |
| S-norm | Symmetric cohort z-score against the other enrolled speakers' reference clips. No accept line was fit to it. A name is kept only when that normalized ranking still points at someone whose raw cosine is at least 0.25. |

The installed SpeechBrain package has no cohort function. The s-norm here is the usual half-sum of the enrollment z-score and the test z-score. The cohort is the other Thursday references, not a VoxCeleb download.

TitaNet-Large (`nvidia/speakerverification_en_titanet_large`) embedded the same wavs in a separate Python 3.11 environment. Its references are its own vectors. The SpeechBrain install was not changed. The 0.25 line below is the ECAPA line applied to TitaNet scores so the two models can be counted the same way. It is not a TitaNet operating point.

## Michaels and Herbstreit, and Joe Buck

October, 3 seconds. "Lowest genuine" is the correct-person cosine on the clear Michaels and Herbstreit clips. "Highest Buck" is the nearest Thursday name on a Buck clip.

| Enrollment | Model | Lowest Michaels or Herbstreit | Highest Joe Buck | The ranges |
| --- | --- | ---: | ---: | --- |
| Clean | ECAPA | 0.447 | 0.469 | Overlap. One threshold cannot keep all seven and reject all nineteen. |
| Published | ECAPA | 0.554 | 0.492 | The seven clear clips sit above every Buck clip. |
| Clean | TitaNet | 0.566 | 0.519 | The seven sit above every Buck clip, by 0.047. |
| Published | TitaNet | 0.613 | 0.511 | The seven sit above every Buck clip, by 0.102. |

Clean enrollment is what makes ECAPA overlap. The weak clip is e0148, Al Michaels, at 0.447. The strong Buck clip is e0080, at 0.469 against clean references and 0.492 against the published ones. Adding the song and crowd references lifts Michaels and Herbstreit more than it lifts Buck, which is why the published row separates and the clean row does not. That is an enrollment effect on ECAPA. It is not a new line.

TitaNet's gap is real on this set and it was not turned into a threshold. At the frozen 0.25 line TitaNet accepts 17 of 19 Buck clips, the same count as published ECAPA, because Buck's TitaNet scores run from 0.178 to 0.511 and most of them clear 0.25. The genuine scores sit higher, from 0.566 up. The line is below the gap.

At 0.25, TitaNet also accepts more of the other booths than ECAPA does: 41 of 74 other-show marks, against ECAPA's 25 of 74. Mike Tomlin goes from 1 of 8 on ECAPA to 8 of 8 on TitaNet. Mike Tirico goes from 5 of 16 to 10 of 16. Maria Taylor stays rejected on both. A model that scores familiar voices higher will also accept more strangers if the line stays at 0.25.

The seven Michaels and Herbstreit clear clips are correct at 2 and 3 seconds on both models, clean enrollment. At 1 second, ECAPA leaves e0148 under the line (0.24, unknown). TitaNet names that same second as Kirk Herbstreit at 0.254 against a true score of 0.219. The short prefix is the fragile one. Median delay on the October clear and crowd clips that ECAPA gets right stays 1 second, and the margin rule does not change that median. Gonzalez is never correct.

## The margin, the max, and the cohort

Published ECAPA, 3 seconds, October clear clips plus Joe Buck.

| Rule | Michaels and Herbstreit | Tony Gonzalez e0156 | Joe Buck |
| --- | --- | --- | --- |
| Frozen 0.25 | 7 of 7 correct | Whitworth, 0.672 versus 0.594 | 17 of 19 accepted |
| Margin 0.15 | 7 of 7 correct | Unknown. The gap is 0.078. | 8 of 19 accepted |
| Max over references | 7 of 7 correct | Still Whitworth | 18 of 19 accepted |
| S-norm, then the raw line | 7 of 7 correct | Still Whitworth | 17 of 19 accepted |

S-norm did not change Buck's top name on any of the 19 clips. Max-over-references made Buck worse. The margin is the only one of the three that moves the count, and it moves it by withholding a name, not by finding the right one.

The eight Buck clips that still clear the margin are not a thin runner-up. Their gaps are 0.160, 0.197, 0.232, 0.238, 0.287, 0.290, 0.324, and 0.376. Seven are Herbstreit. e0091 is Michaels at 0.418, with Herbstreit at 0.129. e0080 is the far one: Herbstreit 0.492, Michaels 0.115, gap 0.376, 2.6 seconds of detector speech, condition crowd. Raising the gap until that clip falls out would be a search, and it would have to climb past 0.37.

The margin is not free on Whitworth. Same September broadcast, clean, probe left out, 3 seconds: 3 of 5 true Whitworth clear clips become unknown, because the single Gonzalez reference sits inside 0.15. The two that survive lead Gonzalez by 0.203 and 0.221. When that Gonzalez clip is itself the probe and is left out, so there is no Gonzalez reference at all, Whitworth leads by 0.481 and the margin accepts Whitworth. A missing reference plus a wide gap is a confident wrong name.

At 1 second the margin also drops one extra October crowd clip. At 2 and 3 seconds the ten crowd clips stay correct.

The same 0.15 gap on TitaNet does not withhold Gonzalez. TitaNet's lead is Whitworth 0.743 versus Gonzalez 0.579, gap 0.164, so the declared margin accepts the wrong name. It does cut Buck further, to 4 of 19, and it leaves 7 of 74 other-show marks accepted. Those four Buck clips still match Herbstreit with a gap over 0.15. e0080 is again one of them, at 0.511 versus a second of 0.252.

## Joe Buck, clip by clip

e0080 is not one bad Herbstreit reference. At 3 seconds the six nearest ECAPA references are all Herbstreit: clear, crowd, and loud, from 0.351 to 0.434. The published prototype then reaches 0.492 because those clips agree. TitaNet's five nearest references are also Herbstreit, from 0.410 to 0.477, and the next one is Michaels at 0.331.

The other Buck clips that the ECAPA margin still accepts are the same shape when the speech is long enough to trust. e0088 has 3.0 seconds of detector speech and Herbstreit at 0.353 with a gap of 0.287. e0079 has 2.9 seconds and a gap of 0.232. e0086 has only 0.4 seconds of detector speech and still clears, gap 0.160. That one is a short window. The long ones are not.

Buck talking in an NFL game is still programming. These 17 accepts are a wrong name. They are not, by themselves, 17 bad mute decisions. The dangerous cousin is a commercial voice with the same score. That sample is not in the 168 marks. Eight owner marks overlap a gold commercial by at least half a second: four Billy Bob Thornton `not_them` marks and four October `not_them` marks. All eight stay under 0.25 on ECAPA, best scores 0.020 to 0.186. None of them is a labeled broadcaster-voiced ad.

## Tony Gonzalez, clip by clip

e0156, October, clear, 3.0 seconds of detector speech. Published ECAPA prototype: Andrew Whitworth 0.672, Tony Gonzalez 0.594, then Herbstreit 0.139. The nearest single references are tied:

| Reference | Person | Condition | ECAPA | TitaNet |
| --- | --- | --- | ---: | ---: |
| e0125 | Andrew Whitworth | clear | 0.594 | 0.615 |
| e0123 | Tony Gonzalez | clear | 0.594 | 0.579 |
| e0126 | Andrew Whitworth | clear | 0.589 | 0.701 |
| e0129 | Andrew Whitworth | clear | 0.535 | 0.646 |
| e0128 | Andrew Whitworth | clear | 0.511 | 0.622 |
| e0124 | Andrew Whitworth | song | 0.502 |  |

On ECAPA the Gonzalez clip and the nearest Whitworth clip are the same number, 0.594. Five other Whitworth clips sit around them. The song clip is sixth. Averaging the Whitworth clips is what opens the prototype up to 0.672. There is no single rotten reference to delete. Max-over-references still names Whitworth, because 0.594 against e0125 is a hair over 0.594 against e0123, and 0.594 clears 0.25.

On TitaNet every one of those Whitworth clips beats the Gonzalez clip. The closest is e0126 at 0.701 against Gonzalez's own reference at 0.579. That is the embedding. Pooling did not create it.

September's held-out Gonzalez clip, e0123, has no Gonzalez reference left. Both models' story on ECAPA is Whitworth at 0.681 with a gap of 0.481. The margin calls that a match.

## What to label next

The 168 marks stay the diagnosis set. The untouched evaluation set is the next recorded game. It is not September 24, not October 8, and not the sealed holdouts. This run does not score it.

`queue.jsonl` has 56 unlabeled 3-second clips from the two diagnosis tapes. The model name in `why_queued` is why the clip was picked. It is not the label. Fill `label` only.

| Role you are answering | Clips |
| --- | --- |
| Speech inside a gold commercial, model cosine at or above 0.25 | 16 |
| Speech inside a gold commercial, model cosine under 0.15 | 16 |
| Program where the model leaned Whitworth or Gonzalez | 12 |
| Program where Herbstreit scored in the Buck band, 0.25 to 0.50 | 12 |

`role` is one of: enrolled broadcaster, other broadcaster, commercial voice, music under speech. Also who, the background, overlap, certainty, and the speech bounds. Who is talking is a different question from whether the moment is programming.

## The smallest change worth a new game

Take the frozen ECAPA cosine and withhold the name unless the runner-up is at least 0.15 behind. On these clips that keeps all seven Michaels and Herbstreit clear marks at 2 and 3 seconds, turns e0156 from a wrong name into unknown, and cuts Buck from 17 accepts to 8. Evaluate that exact rule on the next game. Do not search the gap again there.

Do not switch to TitaNet on this evidence. It leaves the Gonzalez collision more confident, and at 0.25 it accepts more strangers. Its Michaels and Herbstreit scores do sit above every Buck score here. Whether that gap survives a new game is a measurement to make before anyone chooses a line from it. Choosing the line on these 168 clips would spend the diagnosis set.

S-norm against the other Thursday voices changed nothing. Scoring the closest reference instead of the average made Buck worse. More references will not separate Gonzalez from Whitworth until a Gonzalez clip outscores the Whitworth clips, and on TitaNet none of the current ones do.
