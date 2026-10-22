# Start and end

**79.26% is neither score.** It is 67,428 program seconds heard, plus 0 commercial seconds muted, divided by 85,076.4 corpus seconds. Under a policy that never mutes, that percentage is just the share of the corpus that is football. Catching a commercial start would raise it. Catching an unmute cannot, because nothing was muted.

The two scores below are Universal v1, the published count-200 fingerprint. It is the research baseline. It is not a live mute. One row per break is in `receipts.jsonl`.

## Start

A start is caught when a cover begins during the labeled pod.

| | |
| --- | ---: |
| Pods | 136 |
| Starts caught | 2 |
| Starts missed | 134 |
| Caught within 3 seconds | 0 |
| Delays on the two that were caught | 9.937 s, 10.126 s |
| Commercial seconds actually covered | 25.0 |

**2 / 136, which is 1.5%.** The other 134 breaks were heard from the first second to the last.

The misses are ordinary pods: 19 shorter than a minute, 101 between one and three minutes, 14 longer than three minutes.

| Network | Pods | Starts caught | DSP alarm within 3 s, not used as a mute |
| --- | ---: | ---: | ---: |
| Cable / antenna | 44 | 1 | 24 |
| ESPN | 15 | 0 | 6 |
| NBC | 41 | 0 | 29 |
| Prime | 13 | 0 | 8 |
| Prime Video | 23 | 1 | 19 |

The two caught starts:

| Recording | Pod | What the listener got |
| --- | --- | --- |
| Prime Video, Oct 8 | 139.874–376.900, 237.0 s | Heard 10.1 s, covered 20 s, heard the remaining 206.9 s. No DSP hit inside 30 s. Song rise 11.9 s before the cut. |
| Cable, Oct 12 | 5080.063–5216.609, 136.5 s | Heard 9.9 s, covered 5 s, heard the remaining 121.6 s. DSP alarm 14.9 s after the cut. Song rise 4.1 s before the cut. |

A separate DSP alarm, which is not allowed to mute, sees 86 of 136 starts within 3 seconds and 131 within 30 seconds. The published music-rise scan sees 103 of 136 in the 30 seconds before the cut. Neither of those is a start decision. Using the DSP alarm itself as the mute is the scan that would hide 5,862 football-program seconds.

## End

An unmute is play resuming at the labeled end of the pod.

| | |
| --- | ---: |
| Unmuted at the gold end | 0 / 136 |
| Cover let go inside the ad | 2 |
| No mute, so no unmute existed | 134 |
| Program seconds still muted after the end | 0.0 |
| Ad seconds heard because the cover let go | 328.5 |

**0 / 136.** The two covers that started also ended inside the commercial. Letting go is a fingerprint score falling under 200. It is not a detection that the game came back. On those two pods the listener still heard 206.9 s and 121.6 s of the ad after the let-go.

The research tapes do not contain the live failure where a mute stays on for minutes after the announcer returns. That failure is still outside this ledger. These 136 ends never had a mute left on.

## What to attack, in order

1. The 134 missed starts. That is 17,222 commercial seconds with no cover at all. A start rule has to catch a break the fingerprint did not hold, and it has to leave program seconds at zero.
2. The return on a start that did catch. The two caught pods show the shape: a few seconds covered, then a let-go, then the rest of the ad. A real unmute has to be a reason the game is back, not a missing fingerprint.
3. The stuck mute on a live game. It is not in these receipts. It still comes before installing either of the above.

Script: `experiments/measurement/start_end_001.py`. The four-second trace from a minute before each miss to twenty seconds after it is in `TIMELINE.md` and `timeline_receipts.jsonl`.
