# Break trace

Every four seconds of labeled sports audio now has a decision. The row says the speech score, the music score, which booth voice was nearest, whether that voice was over the published line, what changed since the last step, which observations fired, which ones were blocked, and the action. The file is `decisions.jsonl`. There are 22,935 rows.

The action is play unless the published count-200 fingerprint is covering. That fingerprint is the only authorized mute. A song arriving, and the booth dropping under the line, are written as candidates and then blocked. Six rows cover. They are the same 25 seconds Universal v1 already covered, four on the October 8 Prime Video pod and the rest on the October 12 cable pod. Every other row plays.

Loudness and pitch are not in this decision. The traces already showed they do not move across the cut. Putting them in would add numbers that do not change the action.

## The sign-off, measured and not installed

The failure traces had a shape: music rises while the booth was just here, then the booth falls under the line while the music stays high. That watcher is in the log as `sign_off`. It does not mute.

| | |
| --- | ---: |
| Times the song armed after the booth had been over the line | 195 |
| Times the booth then fell under the line while the song held | 95 |
| Labeled breaks with that confirm in the 30 seconds around the start | 40 / 136 |
| Those confirms that land more than 5 seconds before the cut | 9 |
| Confirms during the game, away from a break | 20 |

When a confirm lands on a break, the median is 0.3 seconds after the labeled start. That is the booth leaving, not the song arriving. The song arrives earlier, about eleven seconds out, and the log keeps that as an arm that still plays. Nine confirms are early enough that acting on them would mute the broadcast. Twenty are in the game. The blocked line on those rows is: the sign-off sequence is not an authorized mute.

A new rule is another candidate and another blocked reason on these same rows. It becomes a mute only when a later diff shows commercial seconds covered and program seconds still at zero. Until that diff exists, the action stays play.

Script: `experiments/measurement/break_trace_001.py`. Rule: `src/hush/break_trace.py`.
