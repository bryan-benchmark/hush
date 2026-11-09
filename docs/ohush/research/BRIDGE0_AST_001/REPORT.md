# Bridge 0 AST head

Verdict: **FAIL**. The head stays a research file. The live mute was not changed, and the engine was not restarted.

Scored 22 October 2026 on this machine. Artifacts: `C:\OHushData\gpu_lab\bridge0_result.json`, sha256 `f150c06ea9d17a02f9fe66bde41ff414d1f49e7c3547c737b769212816251597`. The later `NEED.json` in that folder is the Bridge 2 relative gate, which also failed. This note is the Bridge 0 result.

The model is `MIT/ast-finetuned-audioset-10-10-0.4593`. The head fit on the three pre-October games. The mute rule locked on ESPN `hush_20260914_212529`. October was scored after that. RedZone is the control. The sealed holdouts were not opened.

The selected window is 5 seconds, the ESPN lock with the most commercial seconds among rules that cut zero program seconds on that tape.

| Tape | Commercial seconds held | Program seconds cut | Incidents |
| --- | ---: | ---: | ---: |
| ESPN lock, 5 s window | 145.0 | 0.0 | 0 |
| October, five sessions | 659.405 | 233.595 | 127 |
| RedZone | 0.0 | 0.0 | 0 |

October is a broken run. It has no accuracy. The 145 ESPN seconds are not a win over the 25.0-second Universal v1 line, because that line is scored on the football corpus and this rule hides later games. RedZone has no gold commercials on this tape, and the locked threshold did not fire there.

October program seconds by session: Thursday 16.361, Saturday 54.0, Sunday afternoon 2.0, Sunday night 156.234, Monday 5.0. The worst stretch is Sunday night. Of the commercial seconds still heard, early unmute is 5,879.361, late start is 1,320.6, and missed pods are 418.261. Those figures describe a broken run.

The pass that was required: zero program seconds on the ESPN lock, on October, and on RedZone, and more commercial seconds held than the installed line. October has 233.595 program seconds. The rule is not promoted. It is not tuned on October.
