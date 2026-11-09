# OHUSH_NFL_PBP_ALIGNMENT_001

nflverse play-by-play for 2026 names both Prime tapes. A play gets a time in the recording only when the transcript identifies that play. No model was trained. The mute was not changed.

## The games

| Recording | Kickoff date | Game | Source |
| --- | --- | --- | --- |
| hush_20261008_205100 | 2026-10-08 | Buccaneers at Cowboys | nflverse `2026_05_TB_DAL` |
| hush_20260924_220624 | 2026-09-24 | Falcons at Packers | nflverse `2026_03_ATL_GB` |

The October file says "Bucs at Cowboys" on Prime Video. The September transcript names the Falcons, the Packers, Bijan Robinson, and a 17–7 halftime, which is the nflverse halftime score. Away-home in the file is Tampa–Dallas and Atlanta–Green Bay.

October has five touchdowns. September has six. The full list, with quarter, clock, score, and the play description, is `plays.jsonl`.

## What could be placed on the audio

The game clock is not the recording clock. October also has a 51-minute hole in the capture at about five minutes of audio. Plays inside that hole are not in the file.

| Play | Audio | Why this time |
| --- | ---: | --- |
| J. Williams 1-yard touchdown, first score, Dallas 6–0 | 105 s | The announcer calls an opening-drive touchdown here, before the capture hole |
| B. Aubrey 41-yard field goal, Dallas leads 10–7 | 2655 s | The transcript says "41 yard attempt for Aubrey," the only such kick |
| B. Irving 1-yard touchdown, third quarter | 4790 s | The name Irving is on a touchdown call after the 10–7 kick, so it is the later Irving score |
| B. Robinson touchdown, third quarter, Falcons–Packers | 3390 s | "Robinson for the touchdown," and the fourth quarter is not announced until 5035 s |

Three October touchdowns and five September touchdowns stay unaligned. The words did not identify them, or the recording had not reached that part of the game. Those plays are not counted as model misses.

## The 94 and the 48

These are the live touchdown rows from the first 4070 pass, before a quote was required.

| | October | September |
| --- | ---: | ---: |
| Real touchdowns in the play-by-play | 5 | 6 |
| Real touchdowns placed on the recording | 2 | 1 |
| Live touchdown predictions | 94 | 48 |
| Predictions within 90 seconds of a placed touchdown | 6 | 2 |
| Placed touchdowns that have at least one of those predictions | 2 | 1 |

Five of the six October hits are the model talking about the opening score around 105 seconds. One is the Irving score at 4790 seconds. The other 88 October predictions, and 46 September predictions, are not within 90 seconds of any touchdown we could place. Some of those 88 may be the three October scores that have no audio time. They are not 88 confirmed false calls. They are 88 calls with no verified play at that moment.

The later ledger, the one that requires a quote from the line, has 12 October and 6 September live touchdowns. Three and one of those sit within 90 seconds of a placed score. That is a tighter list. It is still not a precision percentage, because three real October touchdowns have no timestamp to check against.

## Commercials, after the alignment

Gold was not used to place any play.

| Placed play | Next labeled break |
| --- | --- |
| Williams touchdown at 105 s | 35 seconds later |
| Irving touchdown at 4790 s | 68 seconds later |
| Aubrey field goal at 2655 s | none within 3 minutes |
| Robinson touchdown at 3390 s | 106 seconds later |

Two placed touchdowns are followed by a break. One field goal is not. That is four plays, not a rule.

## What this says about training

The records are real, and they are the right outside check. They are not yet a training set. Two October touchdowns and one September touchdown are tied to the audio. A fine-tune on those three calls would memorize this file, and the same file could not then be the test.

The 94 was mostly the model naming a touchdown with nothing in the line to support it. Requiring a quote already cut that list from 94 to 12 without any play-by-play. The play-by-play says that cut was the right direction: almost all of the 94 sit away from the scores we can actually locate.

The next alignment step is a picture of the on-screen clock, so the other touchdowns can be placed instead of guessed. Until more than a handful of plays have an audio time, prompting and the quote check remain the justified work. Supervised training is not.
