# How to test the next rule

`decisions.jsonl` is the evidence. A new test reads those rows. It does not rescan the recordings unless the row is missing a booth.

Four layers, and a row only climbs as far as its evidence allows:

1. Show. No enrolled booth means stop. Cable and antenna are in this layer.
2. Candidate. The sign-off may arm and confirm. That is an observation. It is not a mute.
3. Authorization. Only the published count-200 fingerprint may cover.
4. Score. Diff the action column. Commercial seconds may fall. Program seconds must stay at zero.

The 136 breaks sit in one bucket each. The first two readings are in `ROOT.md`. The next rows to read are the 15 where the booth is present and the music stays quiet.

| Bucket | Breaks | What the log already shows | Next test |
| --- | ---: | --- | --- |
| Confirm lands on the cut | 30 | Booth drops as the label arrives. Speech at that step has median 0.32, but the high end is still 0.82 | Separate these from the 20 in-game confirms using columns already on the row |
| Confirm more than 5 seconds early | 9 | Would mute the broadcast | Must stay blocked |
| Confirm during the game | 20 | Speech median 0.89, music high, booth under the line | Same comparison. These are the false ones |
| Armed, booth never drops | 9 | The song rose. The voice line did not give way | A different second step, still read from this file |
| No sign-off, booth exists | 43 | NBC 19, Prime Video 11, Prime 7, ESPN 6 | The song-then-booth sequence never started. Do not reuse it here |
| No booth | 43 | Cable and antenna | Enroll that show's booth, then rerun this same trace |
| Fingerprint already covered | 2 | The only authorized mutes | Leave them |

Play stays the action until a diff of this file shows a gain in covered commercial seconds and zero program seconds.
