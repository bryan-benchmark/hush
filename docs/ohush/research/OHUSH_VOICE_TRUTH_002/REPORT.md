# OHUSH_VOICE_TRUTH_002

Verdict: not recommended. The three-name entry guard is not installed.

The corrected development count is 31 ignored matches and 255.3 seconds. A causal replay of that rule, using only a window that has already finished, recovers 133 seconds of genuine programming and uncovers 4 seconds of commercial. The owner labels are in. Path B scored the speech boxes with the frozen ECAPA model. Where a reference already existed, Thompson and Whitworth match. Three ad boxes still clear the guard as Thompson or Herbstreit. The 255 seconds are not a verified saving.

## Accounting

Development rows only. The 16 eval rows stayed sealed.

| Group | Episodes | Seconds |
| --- | ---: | ---: |
| Ignored matches, cosine already at or above 0.25 | 33 | 278.3 |
| Of those, runner-up at least 0.15 behind | 32 | 262.3 |
| Andrew Whitworth inside that wide group | 1 | 7.0 |
| Whitworth with a thinner gap, also excluded | 1 | 16.0 |
| Al Michaels | 11 | 101.9 |
| Kirk Herbstreit | 16 | 88.0 |
| Clarissa Thompson | 4 | 65.4 |
| Three-name candidate | 31 | 255.3 |

October holds 163.9 of those seconds. September holds 91.4. These are the lengths of false mutes that already contained a finished match. They are not confirmed speakers, and they are not seconds the guard gave back.

## What the replay measured

The frozen 10-second mean stays at 0.1632588496059179. The cosine stays at 0.25. A new mute is blocked only when, at that decision, a Michaels, Herbstreit, or Thompson window has already ended and the runner-up is at least 0.15 behind. The window protects that decision for one second, the existing hop. It does not hold a pause, it does not close a mute already open, and the three-second return is unchanged. Whitworth and Gonzalez do not qualify.

Unprotected coverage reproduced the published tapes: October 95.06 percent, September 95.15 percent.

| Tape | Genuine programming recovered | Commercial seconds uncovered | Coverage after | Late starts | Late returns |
| --- | ---: | ---: | ---: | ---: | ---: |
| October 8 | 98.0 s | 4.0 s | 94.91 percent | 36.1 s, unchanged | 224.5 s, unchanged |
| September 24 | 35.0 s | 0.0 s | 95.15 percent, unchanged | 25.6 s, unchanged | 236.2 s, unchanged |

The 4 commercial seconds are October 304–307 and 4456–4457. No break was missed. Late starts and late returns did not move, so the return tail and the cold open were not the thing that changed. False-mute episodes went from 77 to 73 on October and from 45 to 43 on September. Most of the 255-second list was shortened, not removed: a match in the opening second often delays the mute by about a second, and the mean is still hot when that second expires.

The two desk segments, fn0008 and fn0009, stay unresolved. Their best scores are under 0.25, so this guard does not touch them. The dropped pass stays muted for the same reason: the first scores at that open are under the line or are Whitworth and Gonzalez.

## The seven commercial windows

Seven of the 15 development commercial samples pass the same rule. They are selected windows, not a count of missed breaks. Who is speaking is unlabeled.

| Clip | Tape | Window | Name the model offered | Cosine | Gap |
| --- | --- | --- | --- | ---: | ---: |
| fn0101 | September | 300.5–301.5 | Al Michaels | 0.250 | 0.278 |
| fn0102 | September | 1529.7–1531.7 | Kirk Herbstreit | 0.255 | 0.194 |
| fn0103 | September | 1808.7–1810.4 | Al Michaels | 0.325 | 0.404 |
| fn0109 | October | 141.0–143.0 | Clarissa Thompson | 0.444 | 0.311 |
| fn0110 | October | 572.8–574.3 | Kirk Herbstreit | 0.313 | 0.202 |
| fn0117 | October | 4036.8–4038.8 | Kirk Herbstreit | 0.304 | 0.313 |
| fn0118 | October | 4450.9–4452.9 | Clarissa Thompson | 0.266 | 0.158 |

The full-tape cost was 4 seconds, and those 4 seconds are not these seven windows. That does not make the seven safe. A recognized announcer can be reading an ad. An unrecognized voice can be programming. The rule cannot tell those apart until the labels do.

## Labels and Path B

All 71 clips on the voice page now have an owner label. The latest row for each id is in `VOICE_ROSTER_001/names.jsonl`. The 16 eval rows stayed sealed.

On the 10 priority failures, the two desk segments are not missed booth voices. fn0008 is an injury report. fn0009 is Ryan Fitzpatrick in the pregame. fn0010 and the first half of fn0011 are postgame locker-room noise. fn0001 is Al Michaels, with Kirk Herbstreit at the tail, in the opening where no reference existed yet. fn0006 and fn0025 are Clarissa Thompson after the game. fn0007 and fn0023 are show music, then Thompson over that music. The dropped pass, fn0054, is Richard Sherman and then Andrew Whitworth.

On the 15 commercial samples, none of the seven windows that pass the guard is an enrolled announcer reading an ad:

| Clip | What you heard | Name the model offered |
| --- | --- | --- |
| fn0101 | T-Mobile, Billy Bob Thornton | Al Michaels |
| fn0102 | Subway, Will Arnett | Kirk Herbstreit |
| fn0103 | Lowe's, Jordan Love | Al Michaels |
| fn0109 | Outro music, then a DraftKings ad | Clarissa Thompson |
| fn0110 | Outro music, then a FanDuel ad | Kirk Herbstreit |
| fn0117 | A streaming commercial | Kirk Herbstreit |
| fn0118 | A movie spot, then a Wendy's ad | Clarissa Thompson |

## Path B

Each box you drew was embedded on its own and scored with the same enrollment the pipeline uses. A reference counts only after it has already ended. These bounds were drawn after the broadcast, so a match here is not a real-time save.

Where your box is one enrolled person and that person's reference already exists, the model agrees 4 times: Thompson over the postgame music at 0.49 and 0.72, Thompson over the nightcap music at 0.65, and Whitworth on the second half of the dropped pass at 0.81. The nightcap and the 0.72 already have a finished pipeline window on the same speech. The postgame-music box does not: the full tape has no window there, so that miss is segmentation.

The opening, fn0001, is Michaels, and there is still no reference to score him against. His boxes come back empty. fn0006 is Thompson at 4529, and her first reference is not available until 4872. The model names Herbstreit at 0.13 and does not accept anyone. Giving it her exact words does not create a Thompson match before she is enrolled.

The injury report scores Whitworth at 0.11. Fitzpatrick scores Whitworth at 0.09. The locker room stays under 0.25. Richard Sherman's half of the dropped pass scores Gonzalez at 0.16 and is not accepted. The 0.43 Gonzalez reading was a different window, on the stretch you marked as Whitworth, where the whole box is Whitworth at 0.81.

Three ad boxes still pass the guard on your boundaries, not only on a short pipeline slice:

| Clip | What you heard | Path B | Cosine | Gap |
| --- | --- | --- | ---: | ---: |
| fn0109 | DraftKings | Clarissa Thompson | 0.493 | 0.413 |
| fn0110 | FanDuel | Kirk Herbstreit | 0.321 | 0.216 |
| fn0118 | Wendy's | Clarissa Thompson | 0.373 | 0.277 |

Billy Bob Thornton, Will Arnett, and Jordan Love fall under 0.25 when the box is the whole ad. The short pipeline slice was what put them over the line. DraftKings, FanDuel, and Wendy's do not. The embedding itself takes those voices for Thompson and Herbstreit.

## Decision

Do not install the guard. The labels reject it. The seven commercial windows that clear cosine 0.25 and a 0.15 gap are ads voiced by other people, and the model named Michaels, Herbstreit, or Thompson anyway. A wide gap was not the person. The desk seconds that looked like recognition misses are an injury report and Ryan Fitzpatrick.

Next correction: the guard stays off. The open question is the three ad voices that still clear the line on the box you drew, DraftKings as Thompson, FanDuel as Herbstreit, and Wendy's as Thompson. That is an embedding error, measured on your bounds. A second model can be aimed at those three clips. It is not justified by the desk segments or by the Michaels opening.
