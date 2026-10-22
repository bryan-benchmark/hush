# The accuracy scorecard for the song hold

Not installed. This is the hold already measured: the two published fingerprint covers, kept up until music falls under 0.30. No new cover was searched. Holdouts stayed closed. Playback stays play.

136 commercials. 17,648.4 commercial seconds. The run does not mute the game, so it has a percentage.

| | Seconds |
| --- | ---: |
| Held, after the true start | 116.0 |
| Still heard | 17,532.4 |
| Game muted | 0 |
| Return lag | 0 |

116.0 / 17,648.4 is 0.66%.

134 of the 136 commercials are never muted. On those, the start lag is the whole commercial. The median start lag across all 136 is 132.5 seconds.

The two that are muted start late and let go while the spot is still playing. Prime Video waits 10.1 seconds, holds 46, and then the last 180.9 seconds of that pod are heard. Cable waits 9.9 seconds, holds 70, and the last 56.6 seconds are heard. Both let-gos are before the game, so the return lag is 0.

The published fingerprint alone holds 25.0 seconds, 0.14%. Lowering the count, following the same creative, and starting from the song while the show is under 0.10 were each measured. None of them holds more than 116 seconds without muting the game.

Script: `experiments/measurement/v1_scorecard_001.py`. Counts: `results.json`.
