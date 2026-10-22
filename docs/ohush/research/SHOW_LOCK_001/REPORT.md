# Show lock

**79.26%.** The Hanson rule does not move it.

A second is correct when football programming is heard or a football commercial is muted. The published corpus is 67,428 program seconds and 17,648.4 commercial seconds, 85,076.4 seconds in total. Hearing every program second and every commercial second is 67,428 / 85,076.4 = 79.26%. Universal v1 mutes 25.0 of those commercial seconds and no program, which is 79.29%. One percentage point is 851 commercial seconds muted with no program second lost. The gap from 79.26% to the 99.99% target is 20.73 points, and the whole budget for that target is 8.51 seconds.

RedZone is a separate tape. `hush_20260913_150934` is 7,200 program seconds and 0 labeled commercials. Play is 100% of that tape. It is not folded into the 79.26%.

The rule under test: a Scott Hanson match disarms commercials until five minutes pass with no match. That is a reason to keep playing. The research champion already plays, so the rule changes 0.0 football seconds and 0.00 points. On the RedZone tape the longest measured quiet after the first Hanson example is 71 seconds, and the longest quiet on the whole file is 240 seconds. Five minutes would have held for the rest of that recording. There is no commercial second there for it to catch.

The voice line that would have to make the first decision is still cosine 0.25. At that line Hanson's name, on the short hold already measured, also forces play on other networks. Those matches give back program seconds and commercial seconds on the count-10 ablation. They do not add a muted commercial on Universal v1. The same guard, including the October backfill, leaves v1's 25.0 seconds muted. A five-minute hold was not replayed as its own ledger. Extending a loose match from one window to five minutes would keep more commercials playing, which spends points rather than earning them.

Playback stays play. The live gate was not changed.

## Where a point can still come from

A new veto cannot raise 79.26% while the champion already plays. The next point has to be commercial seconds muted at zero program cost.

| Rule | What is already measured | Points on this ledger |
| --- | --- | --- |
| Play, no mute | 17,648.4 commercial seconds heard, 0 program seconds hidden | 79.26% |
| Universal v1, count 200 | 25.0 commercial seconds muted, 0 program | 79.29% (+0.03) |
| Hanson show lock, 5 min | 0.0 seconds changed against play | 79.26% (+0.00) |
| Named-voice veto on count 10, short hold, plus October backfill | 132.3 false program seconds returned, 464.6 commercial seconds also returned | Below v1. The commercial loss is larger than the program save |
| Count 10 itself | 3,903.2 commercial seconds muted, 432.1 program seconds hidden | 83.34% if every second weighs the same. Weighted with program loss at 100×, the error is 56,955 against play's 17,648. Worse |
| Exact confirm at correlation 0.85 | 1,910.4 commercial seconds kept, 95.1 program seconds hidden | Same failure under the 100× weight. Not installed |
| DSP alarm as the mute, perfect return, 3 s | Would mute about 11,169 commercial seconds and still hear 6,480 | 92.4% only if the 5,862 football-program seconds and 3,993 interruptions stay at zero. They do not. The alarm is not the rule |

The largest open pile is that 13-point ceiling. It requires a second proof, legal for the locked show, that can authorize a mute the DSP scan only suggests, and a return that does not wait on the gold end. The music rise is not that proof. A looser fingerprint is not that proof. The strict fingerprint is the only proof that has bought points, and it has bought 0.03.

The restore deadline is still the higher product priority. It does not appear in the 79.26%, because these tapes were not scored for a mute that forgets to come back. One stuck mute takes a single game off this ledger entirely.

## Next rule worth measuring

Keep the hierarchy. Show first, then that show's commercial rule.

1. RedZone stays disarmed while Hanson is identified, and rearms only after five minutes without him. Do not arm it on cosine 0.25. The next measurement is a Hanson match that Tirico, Buck, and the labeled ads fail, scored on a second RedZone recording that contains commercials. Until that exists, this branch adds 0.00 points and is unsafe to run on a game channel.
2. The point-earning branch is unchanged: a commercial must match known commercial audio at the published count of 200, after the show lock has released. That is Universal v1. Widening it is a new experiment only if the program seconds stay at zero.
3. Do not add another play-veto expecting the percentage to rise.

Script for the arithmetic: the published totals in `docs/ohush/research/ACCURACY_NORTH_STAR_001/` and `docs/ohush/research/UNIVERSAL_V1/`. No threshold was fit. Holdouts stayed closed.
