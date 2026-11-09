# Volume action from the same causal transcripts

The frozen acoustic head stays the champion. Live playback was not changed. The 47 transcripts, windows, and clocks are the ones already saved. Whisper was not run again. Prime stays a regression read.

No hosted model was configured on this machine. The stronger instruction model that fits the 12 GB GPU is Qwen 2.5 14B. The 3B model was scored on the same frozen wording as a control. The wording was not edited after either run.

## Why the first prompt abstained

The first prompt asked what was on the air and allowed four labels: program, sponsorship, ad, and unsure. Unsure was defined as "these words do not say which." A fragment or a brand name fits two labels, so the instructed answer is abstention. Sponsorship was also a separate bucket from a pitch, which is how the Platinum commercial became a sponsorship. The label was not a volume decision.

The frozen replacement asks for one first-version action. Play is the game, the booth, a studio, highlights, or a host who keeps going after naming a sponsor. Mute is a standalone commercial or a standalone promo, including one that talks about football. Unknown stays unknown. It is not a guess that the audio is safe to mute.

## What 14B decides

Warm answer time is 0.14 seconds. The first call, while the 9 GB model loaded, took 5.5 seconds. The original transcription of an 8-second slice was about 0.02 seconds. Once the model is loaded, the action is available about 0.16 seconds after the audio ends.

It plays the clear show sentences and mutes the clear pitches.

| Window | Acoustic P(ad) | 14B action | Words at the decision |
| --- | ---: | --- | --- |
| Odell, first 8 s | 0.97 | unknown | "unbelievable to Jamar Chase. Can we talk about that" |
| Odell, first 20 s | 0.97 | play | the same catch, after a "next Thursday" line |
| Odell, middle 8 s | 0.97 | play | "Joe's jaw to be on the floor after that catch" |
| Whitworth, 8 s and 20 s | 0.96 | unknown | a garbled story about a mound and a mirror boy |
| Palmer, first 8 s | 0.98 | mute | "stuffed French toast. Now at IHOP" |
| Palmer, report | 1.00 | play | "Matthew Golden making the adjustment on the 45" |
| Falcons at halftime | 0.89 | play | "Falcons leave 17-7 at halftime" |
| Injury desk | 0.93 | unknown | "injured it three times now... the facility tomorrow" |
| Both live plays | 0.00 | play | a throw, and a dropped interception |
| Platinum, 8 s and 20 s | 0.98 | mute | lounges, restaurants, "experience it with platinum" |
| Chili's, DraftKings, NFL+ | 0.94–0.99 | mute | the sandwich, the bonus bets, "don't get stuck without football" |
| State Farm, ChatGPT, iPhone | 0.00–0.95 | play | the sponsor line, and the show is what continues |

In-show sponsor lines are play: State Farm with the Cowboys still being discussed, "presented by ChatGPT," "brought to you by iPhone," and "Welcome to the Toyota halftime." The 3B model, on this same wording, mutes the iPhone line and both live plays.

## Where it does not answer

The Whitworth desk stays unknown at 8 seconds and at 20 seconds. The transcript is a scrambled anecdote, not a product pitch, and 14B will not call it the show. The injury report stays unknown. The first 8 seconds of Odell stay unknown. Play on that discussion arrives with the 20-second window, and again at the middle. That can release the rest of a mute. It does not stop the opening.

"It's NFL Sunday. Who's coming over? All of them" stays unknown. So does the Carrie line. Unknown leaves the acoustic decision standing, so those spots stay muted if the acoustic model is already covering them. The one wrong mute is a transition whose ending is the show: "we'll be right back... let's go to the scores." 14B says mute.

On this wording the 3B model is decisive and wrong. It mutes the halftime quarterback talk, "time out inside of two minutes," and both live plays. The abstentions in the first probe were partly the old label set. The remaining misses are the 3B model itself. Fourteen billion parameters fixes the clear sentences and still does not read the Whitworth transcript or the injury sentence.

## Go / no-go

No-go for a transcript pipeline, and no-go for a full-game replay as the next step. The useful cases are real: a clear studio sentence, a clear pitch, and an in-show sponsor line get the right action, quickly, and the pitches are not played. The failures that dominate the listener score do not. Whitworth never becomes play. The injury desk never becomes play. Odell becomes play only after 20 seconds.

## Next test

Resubmit these 47 transcripts with the same frozen action wording and one added sentence: the viewer is watching Prime Thursday Night Football. Do not add a halftime or postgame label. Those phases are not known causally.

Keep the addition only if Whitworth, the injury report, and the first 8 seconds of Odell become play, and Platinum, Chili's, DraftKings, the Amex pitch, and "It's NFL Sunday... all of them" stay mute or unknown. If Whitworth is still unknown, the show's name is not the missing piece, and the transcript of that desk does not carry the decision.
