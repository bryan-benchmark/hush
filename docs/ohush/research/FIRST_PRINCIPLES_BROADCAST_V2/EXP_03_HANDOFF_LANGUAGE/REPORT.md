# EXP-03 — Announcer handoff language

Offline speech recognition on this Mac, `faster-whisper` 1.2.1, model `base.en`, int8, CPU. The model was not fine-tuned. Phrases were fixed before any transcript was read.

| Artifact | sha256 |
| --- | --- |
| `experiments/first_principles_broadcast/exp03_handoff_language.py` | `f2bfbbd2329eff8866224b8c32086148185e2b2e57383a7bdc28f4a31ece5b89` |
| `docs/ohush/research/FIRST_PRINCIPLES_BROADCAST_V2/EXP_03_HANDOFF_LANGUAGE/summary.json` | `391cb22cfecb610f83be4536e721910b5296cb6edd24464ff3ef676dcf8ce8df` |
| `docs/ohush/research/FIRST_PRINCIPLES_BROADCAST_V2/EXP_03_HANDOFF_LANGUAGE/transcripts.jsonl` | `d8d7bce92a27d918ffbb98b1429bc42d40aba75766b4c99a5b911e7da815309f` |

Command:

```
PYTHONPATH=src:. .venv/bin/python experiments/first_principles_broadcast/exp03_handoff_language.py
```

Wall time 628 seconds for 367 windows. A 20 or 30 second window took about 1.7 seconds, roughly 15 times realtime on this Mac. No GPU.

## Frozen phrases

Strong, and the only phrases that count as a handoff hit:

`we'll be right back`, `we will be right back`, `be right back`, `when we come back`, `after these messages`, `these messages`, `commercial break`, `going to commercial`, `we'll return`, `we will return`, `back after this`.

Weak, reported and not counted as a hit: `two-minute warning`, `two minute warning`, `end of the quarter`, `end of the half`, `end of quarter`.

The word `timeout` is a game-state token in EXP-02. It is not a handoff hit.

Each commercial start contributes the interval from 20 seconds before the label to 10 seconds after, when that interval sits inside the coverage. A hit is a strong phrase whose word starts before the label. One program control of 20 seconds was placed on a fixed stride for each commercial and kept only when it was at least 60 seconds from every pod. Forty RedZone windows use the same stride. Three football starts did not have a full window inside coverage, so the football-start denominator is 133.

## Automatic counts

| Set | Windows | Strong phrase before the split | Strong phrase after | Weak phrase |
| --- | ---: | ---: | ---: | ---: |
| Football starts | 133 | 12 | 0 | 6 |
| Football program controls | 135 | 0 | 0 | 0 |
| RedZone | 40 | 0 | 0 | 2 |
| Scripted starts | 29 | 0 | — | — |

Twelve of 133 is a recall of 0.090. None of the 135 program controls and none of the 40 RedZone windows contain a strong phrase. On this matched set the automatic false-cue count is zero. That is not a continuous scan of every program second. The control audio is 135 windows of 20 seconds.

Median word count in a football start window is 56. One football start window was empty.

## What the 12 transcripts actually say

Reading them changes two of the twelve. The other ten are intelligible sign-offs, and the words that follow are advertising or a network bumper.

| Recording | Lead | What was said | DSP class |
| --- | ---: | --- | --- |
| Sept 9 NBC | 1.7 s | "when we come back", then a Siri spot | no DSP episode within 3 s |
| Sept 13 NBC | 4.3 s | "after these messages", then a spot | already-running DSP |
| Oct 8 Prime Video | 19.1 s | "After all these messages", then Carrie White. This is already advertising copy, not a booth sign-off | already-running DSP |
| Oct 10 cable | 9.9 s | "headed overtime when we come back" | fresh DSP |
| Oct 11 cable | 4.1 s | "the two minute warning we're back after this" | no DSP episode within 3 s |
| Oct 11 cable | 1.4 s | "when we come back" | already-running DSP |
| Oct 12 cable | 9.4 s | "first down when we come back" | fresh DSP |
| Oct 12 cable | 7.5 s | "We'll get the call when we come back" during a challenge look | no DSP episode within 3 s |
| Oct 12 cable | 16.8 s | "Fourth down when we come back" | fresh DSP |
| Oct 12 cable | 4.5 s | "yards back after this" — an ASR garble, not a sign-off | fresh DSP |
| Oct 12 cable | 9.0 s | "When we come back, a quarter to go" | no DSP episode within 3 s |
| Oct 12 cable | 4.6 s | "Two minutes left, second and ten when we come back" | no DSP episode within 3 s |

The automatic lead times, including the two bad hits, have median 6.1 seconds. The shortest intelligible leads are 1.4 and 1.7 seconds. A phrase is not permission to mute. Several of the intelligible lines are immediately followed by the spot, so the warning is short.

Six of the twelve automatic hits, and five of the ten intelligible ones, are the Monday cable game. ESPN is 0 of 15. Sept 24 Prime is 0 of 12. Scripted Hulu is 0 of 29. The cue is a property of some football booths in this set, not of television in general.

Five of the twelve automatic hits, all intelligible, are football starts with no positive DSP second within 3 seconds. The 40 ms short-dip rule from EXP-01 credits only 4 football starts within 1 second in total, so most of these spoken sign-offs are starts that rule does not mark.

Weak phrases are not safe. RedZone, which has no commercial in the scored span, still says "two-minute warning" twice. A two-minute warning is not a commercial.

## Verdict

A small set of sign-off phrases occurs before some NFL commercial starts and did not occur in the matched program or RedZone controls. Coverage is about one start in eleven, concentrated on one game, and the lead is often only a few seconds. The cue is real. It is not a detector for the breaks that carry no sign-off, and it does not say when the game has returned.
