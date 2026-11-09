# Speech meaning on the causal transcript

The frozen acoustic head stays the champion. This probe does not change it, and it does not touch the live television.

The language model is the one already on this machine, `qwen2.5:3b`. It sees only a Whisper transcript of audio that ends at the decision. For an 8-second horizon the audio is `[t-8, t)`. Whisper is not given samples after `t`. Its clock and the model's clock are measured after that audio has ended. The prompt was fixed before these rows were read. Prime is a regression read. Reviewed label boundaries stay in `OHUSH_STUDIO_HEAD_001` and are not a model score.

## What the words already say

On the studio minutes the acoustic model scores near 1.00, the causal transcript is the show.

- Odell, at the mute: "unbelievable to Jamar Chase. Can we talk about that." Eight more seconds do not change it. At the middle: "Joe's jaw to be on the floor after that catch."
- Highlights: "Falcons leave 17-7 at halftime. But here we go, fourth quarter."
- Injury report: "injured it three times now... they'll meet and go over all the information."
- Live play the acoustic model leaves alone: "make this throw" and "drops the potential interception."

A reader does not need a later sentence. The same window also identifies real commercials, including football-themed ones: Chili's and the bottomless drink, DraftKings and the promo code, "game day memories with platinum" plus airport lounges and restaurants, and "It's NFL Sunday. Who's coming over? All of them."

One window is the opposite alignment. Palmer's mute starts where the gold break ends, and the 8 seconds before that point are still "stuffed French toast... IHOP." The report ("Matthew Golden... 45-yard reception") is in the window that ends 13 seconds later.

## What this model does with those words

It abstains. After the weights are loaded, 44 of 47 answers are `unsure`. The exceptions:

- The pregame desk is `program`.
- Chili's, DraftKings, and the IHOP line are `ad`.
- "Presented by State Farm," "presented by ChatGPT," and "brought to you by iPhone" are `sponsorship`.
- The Platinum pitch is also `sponsorship`. So is "Progressive Insurance for coverage you can..."

It does not call the Odell discussion, the Whitworth desk, the halftime highlights, the injury report, or either live play `program`. Longer transcripts of the same Odell and Whitworth stretches, 20 seconds instead of 8, are still `unsure`. Used as a veto on the acoustic mute, this model would leave the 60-second desk muted and would also keep the Platinum commercial audible.

Sponsorship lines are the one policy category it handles. "Welcome to the Toyota halftime," with no show sentence after it, is called `ad`.

## Time and cost

Warm transcription of an 8-second slice: median 0.015 seconds, max 0.039. Warm model answer: median 0.093 seconds, max 0.143. Together that is about a tenth of a second after the audio ends. The first answer, while the 1.9 GB model loaded, took 27 seconds. There is no per-call API fee. Latency is not why the desks stay muted.

## Next step

Resubmit these same 47 transcripts, unchanged, to one stronger instruction model. No new audio, no new window, no live controller.

Keep it if that model calls the desk, highlight, injury, and live-play lines the show, and calls Platinum, Chili's, DraftKings, and the Sunday-ticket line commercials. The experiment after that is a veto on the frozen acoustic mute, replayed across both Prime games, so a saved desk minute has to show up as fewer program seconds silenced.

Stop if the stronger model also treats the Platinum pitch as sponsorship, or still will not call the Odell lines the show. The words are already in the window. A model that cannot use them should not be wired to the volume.
