# Outro fingerprint, then the broadcaster

Not a mute. The outro window is the 8 seconds that end at a labeled commercial start. The match uses only earlier outros. The look opens two minutes after that window has been heard, and the broadcaster is the locked return: the highest enrolled cosine in the last 30 seconds, at or over 0.10. Counts are the published short-query counts, 10, 20, 50, and 200. Holdouts stayed closed. October tapes were already inspected. Playback stays play.

The hasher sees each window. A window matched to itself scores 468 at the low end and 692 at the median. The same window matched to an earlier outro scores 2 at the median. The 90th percentile is 7. The highest is 44.

| Count | Later outros | Enrolled-show program | Cable program | Ad middles | RedZone |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 10 | 10 / 132 | 0 | 6 | 1 | 0 |
| 20 | 6 / 132 | 0 | 0 | 0 | 0 |
| 50 | 0 / 132 | 0 | 0 | 0 | 0 |
| 200 | 0 / 132 | 0 | 0 | 0 | 0 |

Three breaks start before 8 seconds of tape exist, so they have no window. One later outro is the first clip in the library and has nothing earlier to match. The program grid is an 8-second window every 30 seconds, kept 20 seconds away from commercials: 17.1 hours, of which 8.5 are shows with an enrolled booth. On those shows the best program score is 9. RedZone is 2.0 hours and its best score is 9. Ad middles are one window in the center of each long pod.

Count 200 is the published copy bar. Nothing reaches it. Count 50 is empty too. The last 8 seconds before a break are not a song that plays again.

The six scores at or over 20 sit between 24 and 44, against self-matches near 700. Three are cable windows matched to NBC or ESPN. The other three are the enrolled hits:

- Prime, September 24, at 6,854 seconds. Score 42 against an earlier Prime outro in the same game. The pod runs 166 seconds. The look opens with 46 seconds of the spot left and takes a 0.21 voice 44 seconds before the end.
- Prime Video, October 8, at 9,605 seconds. Score 44 against a Prime outro from September 24. The look takes a 0.11 voice inside the 13-second spot that follows this one.
- Prime Video, October 8, at 10,390 seconds. Score 26 against that same Prime outro. The pod is 50 seconds, so the look opens 70 seconds after the game is already back. No enrolled voice reaches 0.10 in the next 180 seconds. The look expires.

Those three covers hold 328.8 commercial seconds and 252.3 program seconds. The program seconds are the expired look. Count 10 adds the weaker hits and holds 638.7 commercial seconds and 329.1 program seconds. Both are broken. Cable has no enrolled booth, so a cable hit does not start this path.

## If every outro were already known

The fingerprint is the part that fails. The clock was scored separately, as if all 90 enrolled outros had been recognized. Cable stays out, because there is no booth to look for.

The two-minute mark is still inside that commercial on 73 of the 90. The median remainder is 16.4 seconds. On the other 17 that pod has already ended, and the median time already past the end is 72.3 seconds. Twelve of those 17 open while the tape is in the game.

The 0.10 voice then lands inside a labeled commercial 59 times, in the game 28 times, and nowhere in the horizon 3 times. On the early landings the median is 14.4 seconds before the gold end. Sixteen are more than 30 seconds early, and eight are more than 60.

Following the path on all 90 covers 10,122.0 commercial seconds and 1,979.4 program seconds.

| Where the hidden game seconds come from | Breaks | Program seconds |
| --- | ---: | ---: |
| Look opens after the game is already back | 12 | 839.0 |
| Look expires with no booth | 3 | 718.6 |
| Booth arrives after the ad | 16 | 334.3 |
| Booth score lands inside an ad | 59 | 87.5 |

The published 0.25 line, recorded on the same rows, lands in the game 61 times and inside an ad 21 times, and misses 8. Waiting for it covers 11,324.9 commercial seconds and 3,144.5 program seconds. The stricter line does not remove the hidden game.

The path stays off the television. A repeated outro is not in these windows, and the two-minute booth look hides the game even when the outro is handed to it.

Script: `experiments/measurement/outro_return_001.py`. Timing: `src/hush/outro_return.py`. Counts: `results.json`. One row per window: `receipts.jsonl`.
