# Are the labels the commercials, or the announcer's ads?

The active gold is detached commercial breaks. An announcer reading a sponsor during the game is not its own class. If that read was not marked as a break, the scorer treats it as the show. That matches the listening rule already written down: keep an in-game sponsor read, mute the break that leaves the broadcast. It also means the "program" examples the classifier trained on are not all football talk.

Gold was not changed. The classifier was not retrained. The live mute was not changed. Sixteen of the 104 clips have notes. The sort is below. Model scores were not shown in the logger.

## What the ledger contains

The resolved active rows in `experiments/annotations/truth_events.jsonl` are 166 rows of `commercial` / `mute` / `certain`, and 11 rows of `program` / `play` / `certain`. There is no active promo class. A raw `network_promo` row on ESPN is not in that resolved set.

A commercial second, for training and for the KPI, is a second entirely inside one of those 166 breaks. Everything else inside a fully annotated stretch, other than an unsure mark, is program. That rule is `program_regions` in `experiments/measurement/metrics.py`. The 11 program rows do not list every second of the game. They leave the rest of the annotated stretch to be filled in as program.

So a FanDuel line spoken in the booth, outside a marked break, is a program example. A Toyota spot inside a marked break is a commercial example. The classifier was taught both.

## Places already listened to

These were found earlier. The gold rows were left as they are.

| Where | What was heard | How gold treats it |
| --- | --- | --- |
| Sept 13 NBC, 75–100, `hush_20260913_210542` | FanDuel, "make this your most rewarding season." The same line also sits inside a gold commercial. | The 75–100 window is outside gold. It is scored as program. |
| Sept 9 NBC, around 240, `hush_20260909_213047` | Mike Tirico says the broadcast will be back, then an AWS commercial. The previous gold break ends at 141.5. The next starts at 623. | The AWS spot is not in the gold. It is scored as program. |
| ESPN boundaries | Some marked starts fall in outro music or silence before the spot. | Those seconds are inside the commercial label. |
| Prime, after a Miller Lite spot | Al Michaels comes back reading a network promotion. | The return is the show, even when the first words are a promo. |

The FanDuel case can be the right product label if the viewer was still in the game and would want it heard. It is the wrong acoustic example if the model is being asked to learn "this sound is never an ad." The AWS case is the other way: a detached spot the listen found, still scored as the show. Neither row has been moved.

The category note in `docs/ohush/research/CATEGORY_POLICY_001/POLICY.md` already says the next mark keeps an in-game promo on, and keeps the booth talking about a product on. Closed gold stays binary. This audit does not reopen it.

## What 92.73% is

It is not 97%, and it is not a mute result. It is the share of the 21,400 labeled seconds on Sept 9 and Sept 13 NBC that the logistic head calls the same way as the gold, at the head's own midpoint. The fit is 15,537 program seconds and 5,863 commercial seconds. Calling every second program would already agree 72.6% of the time and would mute nothing.

The midpoint is not the line that was used to mute. That line is 12.155, one step above every score that touches the show on those two games. Typical commercial seconds score about 4.1. Typical program seconds score about −6.2. Most ads never reach 12.155, so a rule that refuses every program second on the fit games marks almost no advertising. The 92.73% lives at the midpoint, where the show does get cut. The two numbers answer different questions.

One second does a lot of the damage at 12.155. Sept 13 at 154: the five seconds just heard are inside a commercial, and 0.391 seconds of the next second are already the show. The score can be right about what just played and still be the wrong order for what to play next. The decision at time t uses audio from t−5 to t and would cover t to t+1.

## The listen

`queue.jsonl` has 104 clips in a shuffled order. Each row has a session and a clock range, and empty fields for what a person hears. The scores and the reason a clip was picked are in `key.jsonl`. Read the queue first.

The clips play in the existing review logger at http://127.0.0.1:3010/review. The note is whatever you type there. The categories come after those notes, not before.

The queue is the two NBC games plus RedZone. It holds the four known spots above, high-scoring clear show seconds, low-scoring seconds from the middle of gold breaks, fifteen seconds on either side of labeled starts and ends, and ordinary stretches away from breaks.

The reader is `experiments/measurement/label_audit_001.py`.

## What the first 16 notes say

Sorted 24 October 2026 from `judgments.json`. Gold was not edited. No model was fit. The seven break-logger notes were left unused.

| Pile | Clips | What was heard | What gold says |
| --- | --- | --- | --- |
| Keep, and gold agrees | q002, q005, q006, q008, q009 | Tirico, Collinsworth, a referee, the game | Program, away from a break |
| Mute, and gold agrees | q010, q011, q015, q016 | A commercial, a political ad then B-Dubs, Bud Light, Verizon | Middle of a gold commercial. These were picked because the model scored them low |
| Edge agrees | q012 | America's Got Talent until 15s, then Tirico and the SNF music | The gold end is at 15s |
| Edge within a second, content unsure | q004 | Field goal, then Peyton Manning Nationwide at 14s. Maybe still in the broadcast | The gold start is at 15s |
| Keep the booth line. The ad before it is missing | q007 | A commercial ends at 3s. Tirico's "brought to you by" stays on | The whole clip is program. The center second is 1124, score 6.586 |
| Gold calls a commercial the show | q003 | A regular commercial, not the broadcast. Hard to call | The whole clip is program. The center second is 1020, score 5.764, 101 seconds after the break that ends at 918.525 |
| A commercial, then a different program | q001 | A commercial until 4s, then Steve Harvey on Family Feud | The whole clip is program. The center is 11133, which is 22 minutes after the last football break on this tape |
| Gold ends the ad early | q013 | Ads through 27s, including YouTube TV. The program is back at 27s | The gold end is at 15s. That leaves 12 seconds of the ad in the program class |
| Keep the outro. Gold starts early | q014 | Football outro and a FanDuel call until 32.8s, then a Progressive commercial | FanDuel at 75–100 is already program. The gold start is 100.129, about 2.7s before Progressive |

Nine of the sixteen agree with gold: five keeps and four mutes. The four mutes are real detached ads that the model already scores as if they were the show. Changing their labels would not teach it anything new.

The notes do change what the loud "show" stretch was called. `SUPERVISED_STRETCH_001` described 1011–1124 as the game. The second at 1020 is one of its six loud seconds, and the note on q003 calls that second a commercial. The loudest second in that stretch is 1124, score 6.586, and q007 calls that the "brought to you by," which stays on. The four loud seconds at 3737–3765, score up to 7.342, start after q013 says the program is already back. Those stay on too.

The second that set the clear-lookback line, 11412 at 8.285, was not in these sixteen notes. It sits in 10151–11419, the same stretch as the Family Feud return at 11133. This listen does not say what 11412 is.

## What was not fit

A new target needs a second the owner wants heard to fall below the ads. The seconds they want heard are the loud ones: 6.586 at the sponsor mention, 7.342 just after the return they named. Taking q003's commercial out of the program class removes a score of 5.764. It does not move 8.285. The confirmed ads were chosen because their scores are the low ones. No new logistic was fit. ESPN, Prime, and RedZone were not scored again. Count 200 stays. 146.0 stays uninstalled.

The break logger has seven notes, all on Sept 9, each marking "the sound of a break." Five sit on or just before the logged line. The start at 623.347 was marked 11.8 seconds after the line. The start at 1000.416 was marked 1.9 seconds after the line. Those notes stay in `docs/ohush/research/BREAK_LISTEN_001/judgments.json`. They are not a training set.

The remaining 88 clips in this queue are not required for this result. The next evidence is a game whose break times and the optical audio share a clock. The next Prime game is 29 October.
