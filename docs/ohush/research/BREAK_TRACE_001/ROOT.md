# Root causes, read from the decision log

No new audio scan. Every number below is a row already in `decisions.jsonl`. Play stays the action. Nothing here is authorized to mute.

## 1. A confirm on the cut and a confirm in the game are different events

There are 95 sign-off confirms. Thirty-two of them fall in the five seconds around a labeled start. Twenty fall during the game.

On the cut, the booth is over the published line in the previous four-second window, 32 of 32 times. The cosine there has median 0.56 and the weakest is 0.386. In the next twelve seconds the booth does not come back, 0 of 32.

In the game, the previous window is over the line only 5 of 20 times. The cosine is already around 0.20. Speech stays high through the confirm and the next twelve seconds, 20 of 20, median about 0.89. Half of those booths are back over the line within twelve seconds. The arm looks back twenty seconds, so an older flicker counts as "the booth was just here." The announcer is still talking.

Speech on the confirm step itself does not separate them. At the cut the median speech is 0.32, then the next window is a different person and speech is back near 0.85 while the cosine stays near 0.08. In the game speech never takes that dip.

Requiring the previous window to be over the line, and the booth to still be gone twelve seconds later, keeps all 32 on-cut confirms and 1 of the 20 in-game confirms. That one is NBC, `hush_20260909_213047`, at 7860 seconds, eleven seconds after a commercial has already ended. Speech is 0.85 before, at, and after. Music falls twenty seconds later, at 7884. Waiting twelve seconds and then muting would hide about twelve seconds of the game. The reading stays blocked.

Six more confirms pass the same two checks and sit five to nine seconds before the labeled start. Waiting out the twelve seconds lands the decision a few seconds after the label, so those seconds of the broadcast would still be heard. They are not a reason to act at the confirm.

## 2. The breaks the sequence never starts

Forty-three breaks have an enrolled booth and no sign-off in the thirty seconds before the cut. They fail for three different reasons.

| Why the sequence never started | Breaks | What the rows show |
| --- | ---: | --- |
| Booth cosine never reaches 0.25 in the prior 40 seconds | 18 | Speech is still high, about 0.85 to 0.90. The nearest booth cosine tops out between 0.04 and 0.22 |
| Music stays quiet, so there is no rise to arm on | 15 | The song-rise latch has nothing to catch |
| Music is already high for the whole 40 seconds | 6 | There is no crossing from quiet to high, so the arm never fires |
| The rise and the booth do not line up | 4 | One file-start break has no rows. The rest are a rise with no recent booth, or a condition that the watcher reset |

The eighteen with a cosine under the line are a second voice. The transcripts name them:

- NBC at 623 seconds: "you're going to hang out here for halftime," then a Siri ad. Cosine to the booth is 0.09 to 0.18.
- NBC at 1074 seconds: "This has been the Toyota Halftime." Then Queen Latifah.
- ESPN at 1243 seconds: "you're watching the Allstate halftime," then the Allstate ad.
- Prime at 5355 seconds: "This has been the JCPenney Post Game Show."
- ESPN at 6853 seconds: "We will see you in just 90 seconds for SportsCenter."
- NBC at 8020 seconds: "Week one is in the books," then the Geico theme.

The published 0.25 line is refusing those voices. Lowering it would enroll the halftime desk and the sponsor read as the booth. The booth-departure sequence cannot see a break the booth is not in.

## 3. Nine arms that looked like misses

Seven of the nine do confirm. The confirm lands more than five seconds after the labeled start, so the earlier count filed it inside the ad.

Two never confirm, both NBC on September 9. At 3944 and at 6356 the music is high for one window (0.95 and 0.91) and under 0.30 on the next. The watcher resets when the music falls. At 6356 the booth cosine is 0.727 in that one high window, which is Tirico, and the following window is speech without the song. The song-holds requirement drops a real departure.

## What is left

| Still open | Breaks | Next reading |
| --- | ---: | --- |
| Confirm in the game that survives the two checks | 1 | Twelve seconds of program. Stays blocked |
| Music stayed quiet while the booth was present | 15 | The booth cosine is high in the last window and under the line after the cut. The song arrives with the cut. Read those rows next |
| Music already high, no rise | 6 | Same file. The arm needs a crossing that never happens |
| Second voice, booth correctly under the line | 18 | Needs that voice enrolled, or a separate desk rule. A lower cosine is the wrong fix |
| Cable and antenna, no booth | 43 | No national booth to test |
| Fingerprint covers | 2 | Leave them |

Forty-three cable breaks and the eighteen second-voice breaks are outside this sequence. The next rows to read are the fifteen where the booth is present, the music stays quiet, and the voice leaves at the cut.
