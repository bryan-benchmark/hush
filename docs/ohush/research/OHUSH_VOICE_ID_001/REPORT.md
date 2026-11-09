# OHUSH_VOICE_ID_001

On the clips the owner actually named, frozen ECAPA can tell Al Michaels and Kirk Herbstreit from the rest of the Thursday cast. A cosine of 0.25 does not mean the name is verified. Joe Buck clears that line as Herbstreit. The pause rule stays on hold.

This is not a mute replay. The television was not changed. TitaNet was not run: NeMo is not installed, and the torch in this environment is the CPU build. Every owner mark is 3.0 seconds, so a 5-second identity was not scored. Extending the mark would have named audio nobody labeled. Pause tracking was not scored. The marks are isolated clips, not turns.

## What was scored

168 owner marks, latest label per clip. The accept rule is the published ECAPA cosine, 0.25. Below that the name is withheld. Rank-1 is reported beside it: the nearest enrolled voice, with no line. Rank-1 is not a new threshold.

Two enrollments, both built only from other clips:

| Enrollment | References |
| --- | --- |
| Published | The Thursday keep-set: clear, crowd, loud, and the four song clips. |
| Clean | Clear clips only. Songs and crowd stay out. |

October probes use the September 24 references and no October clip. That is the cross-tape test. September has no earlier Thursday enrollment in this label file, so September has no cross-tape number. Its same-game number leaves the probe clip out and is marked as the same broadcast.

The current mute research embeds about 2 seconds of speech. The 2-second row below is that length. The 1-second row is a shorter prefix of the same owner mark, not the one-second veto.

## October, from September references

Clean enrollment. Clock time from the start of the mark. Eight clear clips are five of Herbstreit, two of Michaels, and one of Tony Gonzalez. Ten crowd clips are Michaels, Herbstreit, and Clarissa Thompson.

| Window | Clear, named at 0.25 | Clear, nearest name | Crowd, named at 0.25 | Crowd, nearest name |
| --- | ---: | ---: | ---: | ---: |
| 1 second | 6 of 8 | 7 of 8 | 9 of 10 | 10 of 10 |
| 2 seconds | 7 of 8 | 7 of 8 | 10 of 10 | 10 of 10 |
| 3 seconds | 7 of 8 | 7 of 8 | 10 of 10 | 10 of 10 |

The seven Michaels and Herbstreit clear clips are named correctly at 2 and 3 seconds. At 3 seconds their cosine to the right person runs from 0.45 to 0.67. The nearest other Thursday voice on those clips runs from 0.03 to 0.18. One Michaels clip, e0148, is 0.24 at 1 second and 0.33 at 2 seconds, so the short prefix is under the line and the longer one is over it. Median delay on the clear clips that are recognized is 1 second from the start of the mark.

The miss that does not heal is e0156, Tony Gonzalez, clear. At 3 seconds he is 0.59 to his own September reference and 0.67 to Andrew Whitworth, and the line accepts Whitworth. September has one clear Gonzalez clip. Dropping the song clips does not change this row: the published enrollment is also 7 of 8, and the same clip is the error.

Cutting the mark down to detected speech did not raise the count. No October clear clip except Gonzalez contains 3 seconds of VAD speech. The owner's clear mark is not three seconds of detected speech. On the crowd clips, the 1-second speech crop accepted 6 of 10 where the raw 1-second prefix accepted 9 of 10.

## What 0.25 accepts besides the Thursday booth

Seventy-four owner marks from other broadcasts — Tirico, Collinsworth, Maria Taylor, Tomlin, Buck, Aikman — were scored against the same September Thursday references. They should have been unknown.

At 3 seconds, published enrollment, 25 of 74 were accepted as a Thursday voice. Sixteen of Joe Buck's 19 clips were accepted as Kirk Herbstreit, and one more as Al Michaels. Buck's cosines run from 0.11 to 0.49. Seventeen of the nineteen are at or above 0.25. Five Tirico clips, one Collinsworth, one Tomlin, and one Aikman also clear the line.

The weakest correct Michaels clear clip on October is 0.45. One Buck clip is 0.49. A single cosine cannot accept all seven Michaels and Herbstreit clear clips and reject all nineteen Buck clips. Clean enrollment still accepts 22 of the 74 other-show clips at 3 seconds. Removing the songs does not close that hole.

Four October clips the owner marked `not_them` stayed under the line at 3 seconds, on both enrollments. That is four clips.

Ryan Fitzpatrick is on the October labels and in neither September prototype. His clear clip is 0.18 at 3 seconds and stays unknown. At 1 second the same clip is 0.34 and is accepted as Whitworth.

## September is the same broadcast

Same-game, probe left out, 3 seconds, clean enrollment: 13 of 13 clear and 11 of 11 crowd are named correctly. That number uses other clips from September 24. It is not a second tape.

The one September Gonzalez clear clip, held out, is accepted as Whitworth at 0.68. Same pair as October.

## The four song clips

Scored against the other clear clips of the named person, same game, 3 seconds:

| Clip | Owner name | Cosine to that person's clear clips | Nearest other |
| --- | --- | ---: | ---: |
| e0101 | Kirk Herbstreit | 0.63 | 0.08 |
| e0112 | Al Michaels | 0.65 | 0.04 |
| e0116 | Clarissa Thompson | 0.54 | 0.13 |
| e0124 | Andrew Whitworth | 0.65 | 0.46 |

Each song clip is closer to the named person than to anyone else. Whitworth's margin is the thin one. Taking the songs out of October's enrollment does not change the 7 of 8 or the 10 of 10. They are a bad kind of reference to keep. They are not the clip that called Gonzalez Whitworth.

## What this separates

Hearing Michaels or Herbstreit for two or three seconds, and picking the nearest Thursday voice, works on every labeled October clip of those two. The sample is seven clear clips and the crowd clips above. It is the whole owner set, not a draw of 200.

The Gonzalez error is a reference problem: one clip, and Whitworth outscores it. A higher line would still accept the wrong name, because 0.67 is above 0.59.

The Buck error is the line. Rank among the Thursday cast is the wrong question for him, because he is not in that cast, and 0.25 lets him in. The forensics count of 677 seconds was a cosine near an enrolled voice. It was not a person confirming the name. This file is why that distinction matters.

VAD cropping of these marks did not beat the raw prefix. Five-second windows, TitaNet, and identity across a pause are unmeasured.

## Recommendation

Leave OHUSH_PAUSE_TRUST_001 as a measured policy result. Do not build it, and do not move 0.25. The next voice measurement is the same clips and the same frozen line on TitaNet, so the Buck and Gonzalez rows can be compared to a second embedding. That run waits on a NeMo install that does not replace the ECAPA environment. It does not add song clips, and it does not label new broadcast windows until the impostor result is reproduced on a tape that was not used here.
